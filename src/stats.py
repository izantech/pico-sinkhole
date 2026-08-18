"""Statistics and telemetry tracker with recent query ring buffer."""

import time

try:
    import utime
    _HAS_UTIME = True
except ImportError:
    _HAS_UTIME = False


class Stats:
    def __init__(self, max_recent=30):
        self.total_queries = 0
        self.blocked_queries = 0
        self.forwarded_queries = 0
        self.failed_queries = 0
        self.max_recent = max_recent
        self.recent_queries = []
        self._start_time = self._get_time_s()

    @staticmethod
    def _get_time_s():
        if _HAS_UTIME:
            try:
                return utime.ticks_ms() // 1000
            except AttributeError:
                return utime.time()
        return int(time.time())

    def record_query(self, domain, qtype_name, action, client_ip=""):
        """Record a processed DNS query and update counters."""
        self.total_queries += 1
        if action == "BLOCKED":
            self.blocked_queries += 1
        elif action == "ALLOWED":
            self.forwarded_queries += 1
        elif action == "FAILED":
            self.failed_queries += 1

        # max_recent == 0 (production mode): counters only, no per-query allocations
        if self.max_recent <= 0:
            return

        uptime_s = self.uptime_seconds
        mins, secs = divmod(uptime_s, 60)
        hours, mins = divmod(mins, 60)
        time_str = f"{hours:02d}:{mins:02d}:{secs:02d}"

        entry = {
            "time": time_str,
            "client": client_ip or "unknown",
            "domain": domain,
            "type": qtype_name,
            "action": action
        }

        self.recent_queries.append(entry)
        if len(self.recent_queries) > self.max_recent:
            self.recent_queries.pop(0)

    @property
    def uptime_seconds(self):
        current = self._get_time_s()
        diff = current - self._start_time
        # Handle MicroPython ticks wraparound if needed
        return diff if diff >= 0 else 0

    @property
    def block_rate_percent(self):
        if self.total_queries == 0:
            return 0.0
        return round((self.blocked_queries / self.total_queries) * 100, 1)

    def to_dict(self):
        return {
            "uptime_seconds": self.uptime_seconds,
            "total_queries": self.total_queries,
            "blocked_queries": self.blocked_queries,
            "forwarded_queries": self.forwarded_queries,
            "failed_queries": self.failed_queries,
            "block_rate_percent": self.block_rate_percent,
            "recent_queries": list(self.recent_queries)
        }
