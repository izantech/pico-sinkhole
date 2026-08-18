"""Configuration loader for pico-sinkhole."""

try:
    import ujson as json
except ImportError:
    import json

DEFAULT_CONFIG = {
    "wifi": {
        "ssid": "",
        "password": "",
        "connect_timeout_s": 20
    },
    "dns": {
        "port": 53,
        "upstream_primary": "1.1.1.1",
        "upstream_secondary": "8.8.8.8",
        "upstream_port": 53,
        "sinkhole_ipv4": "0.0.0.0",
        "sinkhole_ipv6": "::",
        "blocking_mode": "null_ip",
        "ttl": 60,
        "query_timeout_s": 4
    },
    "web": {
        "enabled": True,
        "port": 80
    },
    "led": {
        "enabled": True,
        "pin": "LED"
    },
    "logging": {
        "level": "INFO"
    }
}


def _deep_merge(default, user):
    """Recursively merge user config over defaults."""
    result = dict(default)
    for k, v in user.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


class Config:
    def __init__(self, data=None):
        self._data = data or DEFAULT_CONFIG

    @classmethod
    def load(cls, filepath="config.json"):
        """Load config from a JSON file, merging over defaults."""
        config_data = dict(DEFAULT_CONFIG)
        try:
            with open(filepath, "r") as f:
                user_data = json.load(f)
                if isinstance(user_data, dict):
                    config_data = _deep_merge(DEFAULT_CONFIG, user_data)
        except (OSError, ValueError):
            # File not found or invalid JSON; use defaults
            pass
        return cls(config_data)

    def get(self, section, key=None, default=None):
        sec = self._data.get(section)
        if sec is None:
            return default
        if key is None:
            return sec
        if isinstance(sec, dict):
            return sec.get(key, default)
        return default

    @property
    def wifi(self):
        return self._data.get("wifi", DEFAULT_CONFIG["wifi"])

    @property
    def dns(self):
        return self._data.get("dns", DEFAULT_CONFIG["dns"])

    @property
    def web(self):
        return self._data.get("web", DEFAULT_CONFIG["web"])

    @property
    def led(self):
        return self._data.get("led", DEFAULT_CONFIG["led"])

    @property
    def raw(self):
        return self._data
