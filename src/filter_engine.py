"""Domain filter engine with exact, subdomain, and hosts-format matching."""


class FilterEngine:
    def __init__(self, initial_blocklist=None, initial_whitelist=None):
        self._blocklist = set()
        self._whitelist = set()
        self._bloom = None

        if initial_blocklist:
            for d in initial_blocklist:
                self.add_block(d)
        if initial_whitelist:
            for d in initial_whitelist:
                self.add_white(d)

    @staticmethod
    def _clean_domain(entry):
        """Clean and normalize a domain string, handling hosts-file format."""
        if not entry:
            return None
        # Remove comments
        line = entry.split("#", 1)[0].strip().lower()
        if not line:
            return None

        # Handle '0.0.0.0 example.com' or '127.0.0.1 example.com'
        parts = line.split()
        if len(parts) >= 2 and (parts[0] in ("0.0.0.0", "127.0.0.1", "::1")):
            domain = parts[1]
        else:
            domain = parts[0]

        domain = domain.rstrip(".")
        # Ignore localhost / broad invalid names
        if domain in ("localhost", "local", "broadcasthost", ""):
            return None
        return domain

    def add_block(self, domain):
        cleaned = self._clean_domain(domain)
        if cleaned:
            self._blocklist.add(cleaned)

    def add_white(self, domain):
        cleaned = self._clean_domain(domain)
        if cleaned:
            self._whitelist.add(cleaned)

    def load_from_file(self, filepath, is_whitelist=False):
        """Load domains from a text file."""
        count = 0
        try:
            with open(filepath, "r") as f:
                for line in f:
                    cleaned = self._clean_domain(line)
                    if cleaned:
                        if is_whitelist:
                            self._whitelist.add(cleaned)
                        else:
                            self._blocklist.add(cleaned)
                        count += 1
        except OSError:
            pass
        return count

    def attach_bloom(self, bloom):
        """Attach a pre-built BloomFilter (or None to detach) as an extra blocklist."""
        self._bloom = bloom

    def is_blocked(self, domain):
        """
        Check if a domain or any of its parent domains is blocked.
        Whitelist takes precedence over blocklist and bloom filter.
        """
        if not domain:
            return False

        domain = domain.lower().rstrip(".")

        # 1. Whitelist Check (exact & subdomain)
        if self._is_in_set(domain, self._whitelist):
            return False

        # 2. Blocklist Check (exact & subdomain)
        if self._is_in_set(domain, self._blocklist):
            return True

        # 3. Bloom Filter Check (exact & subdomain; probabilistic, no false negatives)
        return self._is_in_bloom(domain)

    def _is_in_bloom(self, domain):
        """Check domain and parent subdomain levels against the bloom filter."""
        if not self._bloom:
            return False

        if self._bloom.contains(domain):
            return True

        parts = domain.split(".")
        for i in range(1, len(parts) - 1):
            if self._bloom.contains(".".join(parts[i:])):
                return True

        return False

    def _is_in_set(self, domain, domain_set):
        """Check domain and parent subdomain levels against a target set."""
        if not domain_set:
            return False

        # Fast exact match check
        if domain in domain_set:
            return True

        # Subdomain / wildcard check (e.g. sub.ads.google.com -> ads.google.com -> google.com)
        parts = domain.split(".")
        # Need at least 2 labels for domain name (e.g. example.com)
        for i in range(1, len(parts) - 1):
            subdomain = ".".join(parts[i:])
            if subdomain in domain_set:
                return True

        return False

    @property
    def blocklist_size(self):
        size = len(self._blocklist)
        if self._bloom:
            size += self._bloom.count
        return size

    @property
    def whitelist_size(self):
        return len(self._whitelist)
