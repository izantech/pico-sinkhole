"""Asynchronous DNS sinkhole and upstream forwarding server."""

import socket
import time

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

try:
    from .dns_packet import parse_dns_query, build_sinkhole_response, TYPE_A, TYPE_AAAA
except (ImportError, ValueError):
    from dns_packet import parse_dns_query, build_sinkhole_response, TYPE_A, TYPE_AAAA

try:
    _IO_ERRORS = (BlockingIOError, OSError)
except NameError:
    _IO_ERRORS = (OSError,)


class DNSServer:
    def __init__(self, config, filter_engine, stats, led=None, verbose=True):
        self.config = config
        self.filter_engine = filter_engine
        self.stats = stats
        self.led = led
        self.verbose = verbose

        dns_cfg = config.dns
        self.port = dns_cfg.get("port", 53)
        self.upstream_primary = dns_cfg.get("upstream_primary", "1.1.1.1")
        self.upstream_secondary = dns_cfg.get("upstream_secondary", "8.8.8.8")
        self.upstream_port = dns_cfg.get("upstream_port", 53)
        self.blocking_mode = dns_cfg.get("blocking_mode", "null_ip")
        self.ttl = dns_cfg.get("ttl", 60)
        self.sink_ipv4 = dns_cfg.get("sinkhole_ipv4", "0.0.0.0")
        self.query_timeout_s = dns_cfg.get("query_timeout_s", 4)

        self._client_sock = None
        self._upstream_sock = None
        self._pending = {}  # tx_id -> (client_addr, timestamp_s, domain, qtype_name)
        self._running = False

    def _setup_sockets(self):
        """Initialize non-blocking UDP sockets."""
        self._client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except (AttributeError, OSError):
            pass
        self._client_sock.setblocking(False)
        self._client_sock.bind(("0.0.0.0", self.port))

        self._upstream_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._upstream_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except (AttributeError, OSError):
            pass
        self._upstream_sock.setblocking(False)
        try:
            self._upstream_sock.bind(("0.0.0.0", 0))
        except Exception:
            pass

    def _handle_one_client_query(self, data, addr):
        """Process a single incoming client DNS query."""
        query = parse_dns_query(data)
        if not query:
            return

        domain = query.domain
        client_ip = addr[0]

        if self.filter_engine.is_blocked(domain):
            # Blocked domain -> build sinkhole response
            sink_res = build_sinkhole_response(
                query,
                blocking_mode=self.blocking_mode,
                ttl=self.ttl,
                sink_ipv4=self.sink_ipv4
            )
            try:
                self._client_sock.sendto(sink_res, addr)
            except Exception:
                pass

            self.stats.record_query(domain, query.qtype_name, "BLOCKED", client_ip)
            if self.led:
                self.led.pulse()
            if self.verbose:
                print(f"[BLOCKED] {domain} ({query.qtype_name}) <- {client_ip}")

        else:
            # Allowed domain -> race both upstream resolvers; first reply wins.
            # A dead/blackholed upstream (e.g. ISP-blocked 1.1.1.1) never errors
            # on sendto, so waiting to fail over on send errors would strand
            # every query on it. The duplicate reply is dropped (pending entry
            # already popped by the first one).
            now = time.time()
            self._pending[query.tx_id] = (addr, now, domain, query.qtype_name)
            targets = [self.upstream_primary]
            if self.upstream_secondary and self.upstream_secondary != self.upstream_primary:
                targets.append(self.upstream_secondary)
            sent = False
            for server in targets:
                try:
                    self._upstream_sock.sendto(data, (server, self.upstream_port))
                    sent = True
                except Exception:
                    pass
            if not sent:
                self._pending.pop(query.tx_id, None)
                self.stats.record_query(domain, query.qtype_name, "FAILED", client_ip)
                print(f"[UPSTREAM-ERROR] Cannot send query for {domain}")

    def _handle_one_upstream_reply(self, res_data):
        """Relay a response from upstream DNS back to the client."""
        if len(res_data) < 2:
            return

        tx_id = res_data[:2]
        entry = self._pending.pop(tx_id, None)
        if entry:
            client_addr, start_t, domain, qtype_name = entry
            try:
                self._client_sock.sendto(res_data, client_addr)
            except Exception:
                pass

            client_ip = client_addr[0]
            self.stats.record_query(domain, qtype_name, "ALLOWED", client_ip)
            if self.verbose:
                print(f"[ALLOWED] {domain} ({qtype_name}) <- {client_ip}")

    def _purge_expired(self, now):
        """Purge timed-out queries from pending table."""
        expired_keys = [
            k for k, v in self._pending.items()
            if (now - v[1]) > self.query_timeout_s
        ]
        for k in expired_keys:
            entry = self._pending.pop(k, None)
            if entry:
                client_addr, _, domain, qtype_name = entry
                self.stats.record_query(domain, qtype_name, "FAILED", client_addr[0])
                if self.verbose:
                    print(f"[TIMEOUT] {domain} ({qtype_name})")

    async def start(self):
        """Main non-blocking DNS server loop."""
        self._setup_sockets()
        self._running = True
        print(f"DNS Sinkhole server listening on UDP 0.0.0.0:{self.port}...")

        last_cleanup = time.time()

        while self._running:
            # 1. Drain all available incoming client packets
            while True:
                try:
                    data, addr = self._client_sock.recvfrom(512)
                except _IO_ERRORS:
                    break
                except Exception:
                    break
                self._handle_one_client_query(data, addr)

            # 2. Drain all available upstream replies
            while True:
                try:
                    res_data, _ = self._upstream_sock.recvfrom(1024)
                except _IO_ERRORS:
                    break
                except Exception:
                    break
                self._handle_one_upstream_reply(res_data)

            # 3. Purge expired in-flight queries
            now = time.time()
            if (now - last_cleanup) >= 2.0:
                last_cleanup = now
                self._purge_expired(now)

            # Yield control to asyncio loop (for Web Server and LED)
            if hasattr(asyncio, "sleep_ms"):
                await asyncio.sleep_ms(5)
            else:
                await asyncio.sleep(0.005)

    def stop(self):
        """Stop the DNS Server and close open sockets."""
        self._running = False
        if self._client_sock:
            try:
                self._client_sock.close()
            except Exception:
                pass
        if self._upstream_sock:
            try:
                self._upstream_sock.close()
            except Exception:
                pass
