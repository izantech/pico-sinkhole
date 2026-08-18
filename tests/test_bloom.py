import os
import tempfile
import unittest
from src.bloom import BloomFilter
from src.filter_engine import FilterEngine


def _fake_domains(count, prefix="site"):
    return [f"{prefix}{i}.example{i % 13}.com" for i in range(count)]


class TestBloomFilter(unittest.TestCase):

    def test_create_sizing(self):
        bloom = BloomFilter.create(1000, fp_rate=0.01)
        # ~9.6 bits per entry at 1% FP
        self.assertGreater(bloom.bit_size, 9000)
        self.assertLess(bloom.bit_size, 11000)
        self.assertGreaterEqual(bloom.num_hashes, 5)
        self.assertLessEqual(bloom.num_hashes, 9)

    def test_create_invalid_args(self):
        with self.assertRaises(ValueError):
            BloomFilter.create(0)
        with self.assertRaises(ValueError):
            BloomFilter.create(100, fp_rate=0.0)
        with self.assertRaises(ValueError):
            BloomFilter.create(100, fp_rate=1.0)

    def test_no_false_negatives(self):
        domains = _fake_domains(2000)
        bloom = BloomFilter.create(len(domains), fp_rate=0.01)
        for d in domains:
            bloom.add(d)
        for d in domains:
            self.assertTrue(bloom.contains(d), f"false negative for {d}")
        self.assertEqual(bloom.count, len(domains))

    def test_false_positive_rate_reasonable(self):
        members = _fake_domains(1000, prefix="member")
        bloom = BloomFilter.create(len(members), fp_rate=0.01)
        for d in members:
            bloom.add(d)

        non_members = _fake_domains(10000, prefix="other")
        fp = sum(1 for d in non_members if bloom.contains(d))
        # Target is 1%; allow generous slack to keep the test non-flaky
        self.assertLess(fp / len(non_members), 0.05)

    def test_empty_filter_and_empty_domain(self):
        bloom = BloomFilter.create(100)
        self.assertFalse(bloom.contains("anything.com"))
        self.assertFalse(bloom.contains(""))
        bloom.add("")
        self.assertEqual(bloom.count, 0)

    def test_save_load_roundtrip(self):
        domains = _fake_domains(500)
        bloom = BloomFilter.create(len(domains), fp_rate=0.001)
        for d in domains:
            bloom.add(d)

        fd, path = tempfile.mkstemp(suffix=".bloom")
        os.close(fd)
        try:
            bloom.save(path)
            loaded = BloomFilter.load(path)
            self.assertEqual(loaded.bit_size, bloom.bit_size)
            self.assertEqual(loaded.num_hashes, bloom.num_hashes)
            self.assertEqual(loaded.count, bloom.count)
            self.assertEqual(bytes(loaded.bits), bytes(bloom.bits))
            for d in domains:
                self.assertTrue(loaded.contains(d))
        finally:
            os.remove(path)

    def test_load_missing_file_raises_oserror(self):
        with self.assertRaises(OSError):
            BloomFilter.load("does_not_exist.bloom")

    def test_load_corrupt_file_raises_valueerror(self):
        fd, path = tempfile.mkstemp(suffix=".bloom")
        os.close(fd)
        try:
            with open(path, "wb") as f:
                f.write(b"NOT A BLOOM FILTER FILE")
            with self.assertRaises(ValueError):
                BloomFilter.load(path)
        finally:
            os.remove(path)


class TestFilterEngineBloomIntegration(unittest.TestCase):

    def _engine_with_bloom(self, blocked_domains, whitelist=None):
        engine = FilterEngine(initial_whitelist=whitelist)
        bloom = BloomFilter.create(max(len(blocked_domains), 10), fp_rate=0.001)
        for d in blocked_domains:
            bloom.add(d)
        engine.attach_bloom(bloom)
        return engine

    def test_exact_match_via_bloom(self):
        engine = self._engine_with_bloom(["doubleclick.net", "taboola.com"])
        self.assertTrue(engine.is_blocked("doubleclick.net"))
        self.assertTrue(engine.is_blocked("taboola.com"))
        self.assertFalse(engine.is_blocked("wikipedia.org"))

    def test_subdomain_match_via_bloom(self):
        engine = self._engine_with_bloom(["doubleclick.net"])
        self.assertTrue(engine.is_blocked("ads.doubleclick.net"))
        self.assertTrue(engine.is_blocked("stats.g.doubleclick.net"))
        self.assertFalse(engine.is_blocked("notdoubleclick.net"))

    def test_whitelist_precedence_over_bloom(self):
        engine = self._engine_with_bloom(
            ["tracker.example.com"],
            whitelist=["tracker.example.com"]
        )
        self.assertFalse(engine.is_blocked("tracker.example.com"))
        self.assertFalse(engine.is_blocked("sub.tracker.example.com"))

    def test_bloom_and_set_blocklist_combine(self):
        engine = self._engine_with_bloom(["bloomblocked.com"])
        engine.add_block("setblocked.com")
        self.assertTrue(engine.is_blocked("bloomblocked.com"))
        self.assertTrue(engine.is_blocked("setblocked.com"))
        self.assertEqual(engine.blocklist_size, 2)

    def test_no_bloom_attached_unchanged_behavior(self):
        engine = FilterEngine(initial_blocklist=["ads.example.com"])
        self.assertTrue(engine.is_blocked("ads.example.com"))
        self.assertFalse(engine.is_blocked("example.org"))


if __name__ == "__main__":
    unittest.main()
