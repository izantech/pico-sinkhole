import unittest
from src.stats import Stats


class TestStats(unittest.TestCase):

    def setUp(self):
        self.stats = Stats(max_recent=3)

    def test_initial_values(self):
        self.assertEqual(self.stats.total_queries, 0)
        self.assertEqual(self.stats.blocked_queries, 0)
        self.assertEqual(self.stats.forwarded_queries, 0)
        self.assertEqual(self.stats.failed_queries, 0)
        self.assertEqual(self.stats.block_rate_percent, 0.0)

    def test_record_queries(self):
        self.stats.record_query("ads.google.com", "A", "BLOCKED", "192.168.1.50")
        self.stats.record_query("example.com", "A", "ALLOWED", "192.168.1.50")
        self.stats.record_query("timeout.site", "AAAA", "FAILED", "192.168.1.51")

        self.assertEqual(self.stats.total_queries, 3)
        self.assertEqual(self.stats.blocked_queries, 1)
        self.assertEqual(self.stats.forwarded_queries, 1)
        self.assertEqual(self.stats.failed_queries, 1)
        # 1 blocked out of 3 = 33.3%
        self.assertEqual(self.stats.block_rate_percent, 33.3)

    def test_ring_buffer_limit(self):
        for i in range(5):
            self.stats.record_query(f"domain{i}.com", "A", "ALLOWED", "192.168.1.100")

        self.assertEqual(len(self.stats.recent_queries), 3)
        # Should keep only the last 3: domain2, domain3, domain4
        self.assertEqual(self.stats.recent_queries[0]["domain"], "domain2.com")
        self.assertEqual(self.stats.recent_queries[2]["domain"], "domain4.com")

    def test_max_recent_zero_counters_only(self):
        # Production mode: counters still work, but no ring buffer entries
        stats = Stats(max_recent=0)
        stats.record_query("ads.google.com", "A", "BLOCKED", "192.168.1.50")
        stats.record_query("example.com", "A", "ALLOWED", "192.168.1.50")

        self.assertEqual(stats.total_queries, 2)
        self.assertEqual(stats.blocked_queries, 1)
        self.assertEqual(stats.forwarded_queries, 1)
        self.assertEqual(stats.recent_queries, [])

    def test_to_dict(self):
        self.stats.record_query("test.com", "A", "BLOCKED", "127.0.0.1")
        data = self.stats.to_dict()
        self.assertIn("uptime_seconds", data)
        self.assertIn("total_queries", data)
        self.assertIn("recent_queries", data)
        self.assertEqual(data["total_queries"], 1)
        self.assertEqual(data["blocked_queries"], 1)


if __name__ == "__main__":
    unittest.main()
