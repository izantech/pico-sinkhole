import asyncio
import socket
import unittest
from src.config import Config
from src.dns_packet import TYPE_A
from src.dns_server import DNSServer
from src.filter_engine import FilterEngine
from src.stats import Stats


class TestDNSServer(unittest.IsolatedAsyncioTestCase):

    def _craft_query(self, domain, qtype=TYPE_A, tx_id=b"\xaa\xbb"):
        flags = b"\x01\x00"
        counts = b"\x00\x01\x00\x00\x00\x00\x00\x00"
        parts = domain.split(".")
        qname_bytes = bytearray()
        for p in parts:
            b_part = p.encode("ascii")
            qname_bytes.append(len(b_part))
            qname_bytes.extend(b_part)
        qname_bytes.append(0x00)
        return tx_id + flags + counts + bytes(qname_bytes) + b"\x00\x01\x00\x01"

    async def test_blocked_domain_resolution(self):
        await self._run_blocked_query(port=15353, verbose=True)

    async def test_blocked_domain_resolution_quiet_mode(self):
        # verbose=False (production logging) must not change DNS behavior
        await self._run_blocked_query(port=15354, verbose=False)

    async def _run_blocked_query(self, port, verbose):
        config_data = {
            "dns": {
                "port": port,  # Non-privileged port for testing
                "upstream_primary": "1.1.1.1",
                "upstream_secondary": "8.8.8.8",
                "blocking_mode": "null_ip",
                "ttl": 30,
                "sinkhole_ipv4": "0.0.0.0"
            }
        }
        config = Config(config_data)
        filter_engine = FilterEngine(["doubleclick.net", "ads.example.com"])
        stats = Stats()

        server = DNSServer(config, filter_engine, stats, verbose=verbose)
        server_task = asyncio.create_task(server.start())

        # Give server time to bind socket
        await asyncio.sleep(0.05)

        # Client non-blocking UDP socket
        client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client_sock.setblocking(False)

        try:
            req_packet = self._craft_query("ad.doubleclick.net", TYPE_A, tx_id=b"\x77\x88")
            client_sock.sendto(req_packet, ("127.0.0.1", port))

            res_packet = None
            for _ in range(50):
                await asyncio.sleep(0.02)
                try:
                    res_packet, _ = client_sock.recvfrom(512)
                    break
                except (BlockingIOError, OSError):
                    continue

            self.assertIsNotNone(res_packet, "Should have received sinkhole response")
            self.assertEqual(res_packet[:2], b"\x77\x88")  # Correct TX ID
            self.assertEqual(res_packet[2:4], b"\x81\x80")  # Response flag
            self.assertEqual(res_packet[-4:], b"\x00\x00\x00\x00")  # 0.0.0.0 null IP

            self.assertEqual(stats.blocked_queries, 1)
            self.assertEqual(stats.total_queries, 1)

        finally:
            client_sock.close()
            server.stop()
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    unittest.main()
