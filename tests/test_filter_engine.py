import os
import tempfile
import unittest
from src.filter_engine import FilterEngine


class TestFilterEngine(unittest.TestCase):

    def setUp(self):
        self.engine = FilterEngine()
        self.engine.add_block("doubleclick.net")
        self.engine.add_block("google-analytics.com")
        self.engine.add_block("telemetry.microsoft.com")

    def test_exact_block(self):
        self.assertTrue(self.engine.is_blocked("doubleclick.net"))
        self.assertTrue(self.engine.is_blocked("google-analytics.com"))
        self.assertTrue(self.engine.is_blocked("telemetry.microsoft.com"))

    def test_subdomain_block(self):
        self.assertTrue(self.engine.is_blocked("ad.doubleclick.net"))
        self.assertTrue(self.engine.is_blocked("static.ad.doubleclick.net"))
        self.assertTrue(self.engine.is_blocked("ssl.google-analytics.com"))

    def test_allowed_domains(self):
        self.assertFalse(self.engine.is_blocked("example.com"))
        self.assertFalse(self.engine.is_blocked("google.com"))
        self.assertFalse(self.engine.is_blocked("microsoft.com"))
        self.assertFalse(self.engine.is_blocked("wikipedia.org"))

    def test_whitelist_precedence(self):
        self.engine.add_white("safe.doubleclick.net")
        # Base domain is blocked
        self.assertTrue(self.engine.is_blocked("doubleclick.net"))
        # Whitelisted subdomain is allowed
        self.assertFalse(self.engine.is_blocked("safe.doubleclick.net"))
        # Non-whitelisted subdomain is still blocked
        self.assertTrue(self.engine.is_blocked("other.doubleclick.net"))

    def test_load_from_file_with_comments_and_hosts_format(self):
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as f:
            f.write("# This is a comment\n")
            f.write("badtracker.com\n")
            f.write("0.0.0.0 hosts-format-ad.com # trailing comment\n")
            f.write("127.0.0.1 another-ad.net\n")
            f.write("\n")
            temp_path = f.name

        try:
            loaded_count = self.engine.load_from_file(temp_path, is_whitelist=False)
            self.assertEqual(loaded_count, 3)
            self.assertTrue(self.engine.is_blocked("badtracker.com"))
            self.assertTrue(self.engine.is_blocked("hosts-format-ad.com"))
            self.assertTrue(self.engine.is_blocked("sub.another-ad.net"))
        finally:
            os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
