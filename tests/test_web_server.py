import asyncio
import json
import unittest
from src.config import Config
from src.filter_engine import FilterEngine
from src.stats import Stats
from src.web_server import WebServer


class TestWebServer(unittest.IsolatedAsyncioTestCase):

    async def test_dashboard_and_api_stats(self):
        config_data = {
            "web": {
                "enabled": True,
                "port": 18090  # Non-privileged port for testing
            }
        }
        config = Config(config_data)
        stats = Stats()
        stats.record_query("ads.google.com", "A", "BLOCKED", "192.168.1.50")
        stats.record_query("wikipedia.org", "A", "ALLOWED", "192.168.1.50")

        filter_engine = FilterEngine(["ads.google.com"])
        web_server = WebServer(config, stats, filter_engine)

        await web_server.start()

        try:
            # 1. Test GET / (HTML Dashboard)
            reader, writer = await asyncio.open_connection("127.0.0.1", 18090)
            writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()

            chunks = []
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            response_str = b"".join(chunks).decode("utf-8")

            self.assertIn("HTTP/1.1 200 OK", response_str)
            self.assertIn("Pico Sinkhole Dashboard", response_str)
            self.assertIn("ads.google.com", response_str)
            self.assertIn("BLOCKED", response_str)

            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

            # 2. Test GET /api/stats (JSON API)
            reader, writer = await asyncio.open_connection("127.0.0.1", 18090)
            writer.write(b"GET /api/stats HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()

            chunks = []
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            response_str = b"".join(chunks).decode("utf-8")

            self.assertIn("HTTP/1.1 200 OK", response_str)
            self.assertIn("application/json", response_str)

            body = response_str.split("\r\n\r\n", 1)[1]
            data = json.loads(body)
            self.assertEqual(data["total_queries"], 2)
            self.assertEqual(data["blocked_queries"], 1)
            self.assertEqual(data["forwarded_queries"], 1)
            self.assertEqual(data["block_rate_percent"], 50.0)

            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

        finally:
            web_server.stop()


if __name__ == "__main__":
    unittest.main()
