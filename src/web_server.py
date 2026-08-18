"""Lightweight async HTTP web server and dashboard for pico-sinkhole."""

import gc

try:
    import ujson as json
except ImportError:
    import json

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio


class WebServer:
    def __init__(self, config, stats, filter_engine, verbose=True):
        self.config = config
        self.stats = stats
        self.filter_engine = filter_engine
        self.verbose = verbose

        web_cfg = config.web
        self.enabled = web_cfg.get("enabled", True)
        self.port = web_cfg.get("port", 80)
        self._server = None

    def _get_memory_info(self):
        """Get RAM statistics if available."""
        if hasattr(gc, "mem_free") and hasattr(gc, "mem_alloc"):
            free = gc.mem_free()
            alloc = gc.mem_alloc()
            total = free + alloc
            return {
                "free_kb": round(free / 1024, 1),
                "alloc_kb": round(alloc / 1024, 1),
                "total_kb": round(total / 1024, 1)
            }
        return {"free_kb": "N/A", "alloc_kb": "N/A", "total_kb": "N/A"}

    def _render_dashboard(self):
        """Render self-contained HTML dashboard with embedded CSS & live updates."""
        stats_data = self.stats.to_dict()
        mem = self._get_memory_info()
        blocklist_count = self.filter_engine.blocklist_size
        whitelist_count = self.filter_engine.whitelist_size

        rows = []
        for q in reversed(stats_data["recent_queries"]):
            badge_class = "badge-blocked" if q["action"] == "BLOCKED" else "badge-allowed"
            if q["action"] == "FAILED":
                badge_class = "badge-failed"
            rows.append(
                f"<tr>"
                f"<td>{q['time']}</td>"
                f"<td>{q['client']}</td>"
                f"<td class='domain-cell'>{q['domain']}</td>"
                f"<td><span class='type-tag'>{q['type']}</span></td>"
                f"<td><span class='badge {badge_class}'>{q['action']}</span></td>"
                f"</tr>"
            )
        table_rows = "".join(rows) if rows else "<tr><td colspan='5' style='text-align:center;color:#666;'>No queries recorded yet</td></tr>"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="5">
    <title>Pico Sinkhole Dashboard</title>
    <style>
        :root {{
            --bg: #0f172a;
            --card-bg: #1e293b;
            --text: #f8fafc;
            --text-muted: #94a3b8;
            --accent: #38bdf8;
            --blocked: #ef4444;
            --allowed: #10b981;
            --failed: #f59e0b;
            --border: #334155;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        body {{ background: var(--bg); color: var(--text); padding: 20px; }}
        .container {{ max-width: 960px; margin: 0 auto; }}
        header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }}
        .brand {{ display: flex; align-items: center; gap: 12px; }}
        .logo {{ font-size: 24px; font-weight: 700; color: var(--accent); }}
        .status-pill {{ background: rgba(16, 185, 129, 0.2); color: var(--allowed); padding: 4px 12px; border-radius: 9999px; font-size: 13px; font-weight: 600; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .card {{ background: var(--card-bg); padding: 20px; border-radius: 12px; border: 1px solid var(--border); }}
        .card-title {{ color: var(--text-muted); font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }}
        .card-value {{ font-size: 28px; font-weight: 700; }}
        .card-sub {{ font-size: 12px; color: var(--text-muted); margin-top: 4px; }}
        .val-blocked {{ color: var(--blocked); }}
        .val-allowed {{ color: var(--allowed); }}
        .panel {{ background: var(--card-bg); border-radius: 12px; border: 1px solid var(--border); padding: 20px; margin-bottom: 24px; }}
        .panel-title {{ font-size: 16px; font-weight: 600; margin-bottom: 16px; display: flex; justify-content: space-between; }}
        table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; }}
        th {{ color: var(--text-muted); padding: 10px; border-bottom: 1px solid var(--border); font-weight: 600; }}
        td {{ padding: 10px; border-bottom: 1px solid var(--border); }}
        .domain-cell {{ font-family: monospace; word-break: break-all; }}
        .badge {{ padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; text-transform: uppercase; }}
        .badge-blocked {{ background: rgba(239, 68, 68, 0.2); color: var(--blocked); }}
        .badge-allowed {{ background: rgba(16, 185, 129, 0.2); color: var(--allowed); }}
        .badge-failed {{ background: rgba(245, 158, 11, 0.2); color: var(--failed); }}
        .type-tag {{ background: var(--border); padding: 2px 6px; border-radius: 4px; font-size: 11px; font-family: monospace; }}
        footer {{ text-align: center; color: var(--text-muted); font-size: 12px; margin-top: 32px; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="brand">
                <div class="logo">&#x1F6E1; Pico Sinkhole</div>
                <span class="status-pill">&#x25CF; Online</span>
            </div>
            <div style="color: var(--text-muted); font-size: 13px;">Uptime: {stats_data['uptime_seconds']}s</div>
        </header>

        <div class="grid">
            <div class="card">
                <div class="card-title">Total Queries</div>
                <div class="card-value">{stats_data['total_queries']}</div>
                <div class="card-sub">Active listening</div>
            </div>
            <div class="card">
                <div class="card-title">Blocked</div>
                <div class="card-value val-blocked">{stats_data['blocked_queries']}</div>
                <div class="card-sub">{stats_data['block_rate_percent']}% block rate</div>
            </div>
            <div class="card">
                <div class="card-title">Allowed</div>
                <div class="card-value val-allowed">{stats_data['forwarded_queries']}</div>
                <div class="card-sub">Forwarded upstream</div>
            </div>
            <div class="card">
                <div class="card-title">Rules in Memory</div>
                <div class="card-value">{blocklist_count}</div>
                <div class="card-sub">{whitelist_count} whitelisted | Free RAM: {mem['free_kb']} KB</div>
            </div>
        </div>

        <div class="panel">
            <div class="panel-title">
                <span>Recent DNS Activity</span>
                <span style="font-size: 12px; font-weight: normal; color: var(--text-muted);">Auto-refreshes every 5s</span>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Client</th>
                        <th>Domain</th>
                        <th>Type</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
        </div>

        <footer>
            Pico-Sinkhole &bull; Raspberry Pi Pico W / Pico 2 W DNS Shield
        </footer>
    </div>
</body>
</html>"""
        return html

    async def _handle_request(self, reader, writer):
        """Handle incoming HTTP connection."""
        try:
            req_data = await reader.read(1024)
            if not req_data:
                writer.close()
                return

            req_str = req_data.decode("utf-8", "ignore")
            first_line = req_str.split("\r\n")[0].strip()
            parts = first_line.split()
            if len(parts) < 2:
                writer.close()
                return

            method, path = parts[0], parts[1]
            if self.verbose:
                print(f"[HTTP] {method} {path}")

            if path == "/api/stats":
                data = self.stats.to_dict()
                data["rules_blocked"] = self.filter_engine.blocklist_size
                data["rules_whitelisted"] = self.filter_engine.whitelist_size
                data["memory"] = self._get_memory_info()
                payload = json.dumps(data).encode("utf-8")
                headers = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    "Access-Control-Allow-Origin: *\r\n"
                    f"Content-Length: {len(payload)}\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("utf-8")
                writer.write(headers)
                writer.write(payload)
                await writer.drain()

            else:
                html_body = self._render_dashboard()
                body_bytes = html_body.encode("utf-8")
                headers = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: text/html; charset=utf-8\r\n"
                    f"Content-Length: {len(body_bytes)}\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("utf-8")
                writer.write(headers)
                await writer.drain()

                # Stream body in 1024-byte chunks for microcontroller reliability
                chunk_size = 1024
                for offset in range(0, len(body_bytes), chunk_size):
                    writer.write(body_bytes[offset:offset + chunk_size])
                    await writer.drain()

                # Reclaim the render's multi-KB transient strings immediately
                # instead of letting them pile up until the periodic GC
                html_body = body_bytes = None
                gc.collect()
        except Exception as e:
            print(f"[HTTP Error] {e}")
        finally:
            try:
                writer.close()
                if hasattr(writer, "wait_closed"):
                    await writer.wait_closed()
            except Exception:
                pass

    async def start(self):
        """Start async HTTP web server."""
        if not self.enabled:
            return
        print(f"Web Dashboard starting on HTTP 0.0.0.0:{self.port}...")
        self._server = await asyncio.start_server(self._handle_request, "0.0.0.0", self.port)

    def stop(self):
        """Stop async HTTP web server."""
        if self._server:
            try:
                self._server.close()
            except Exception:
                pass
