import json
import os
import tempfile
import unittest
from src.config import Config, DEFAULT_CONFIG


class TestConfig(unittest.TestCase):

    def test_default_config(self):
        cfg = Config()
        self.assertEqual(cfg.dns["port"], 53)
        self.assertEqual(cfg.dns["upstream_primary"], "1.1.1.1")
        self.assertEqual(cfg.web["enabled"], True)

    def test_load_custom_config(self):
        custom_data = {
            "wifi": {
                "ssid": "MyHomeWiFi",
                "password": "SecretPassword123"
            },
            "dns": {
                "port": 5353,
                "upstream_primary": "9.9.9.9"
            }
        }
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as f:
            json.dump(custom_data, f)
            temp_path = f.name

        try:
            cfg = Config.load(temp_path)
            self.assertEqual(cfg.wifi["ssid"], "MyHomeWiFi")
            self.assertEqual(cfg.wifi["password"], "SecretPassword123")
            self.assertEqual(cfg.dns["port"], 5353)
            self.assertEqual(cfg.dns["upstream_primary"], "9.9.9.9")
            # Default values should still be intact
            self.assertEqual(cfg.dns["upstream_secondary"], "8.8.8.8")
            self.assertEqual(cfg.web["enabled"], True)
        finally:
            os.remove(temp_path)

    def test_load_nonexistent_file(self):
        cfg = Config.load("non_existent_file_path_12345.json")
        self.assertEqual(cfg.dns["port"], 53)


if __name__ == "__main__":
    unittest.main()
