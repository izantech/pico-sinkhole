"""Memory-efficient Bloom filter for large domain blocklists.

The filter is built offline on a PC (see tools/build_bloom.py) and loaded
on the device as a flat bit array, so tens of thousands of domains fit in
tens of kilobytes of RAM. False negatives are impossible; the false-positive
rate is fixed at build time.

Binary file format (little-endian), 16-byte header + bit array:
    offset 0:  magic  b"PBLM"
    offset 4:  version (1 byte, currently 1)
    offset 5:  k = number of hash probes (1 byte)
    offset 6:  reserved (2 bytes)
    offset 8:  m = bit array size in bits (uint32)
    offset 12: n = number of entries added (uint32)
    offset 16: bit array, (m + 7) // 8 bytes
"""

import math

_MAGIC = b"PBLM"
_VERSION = 1
_HEADER_SIZE = 16

_FNV_OFFSET = 2166136261
_FNV_PRIME = 16777619
_MASK32 = 0xFFFFFFFF


def _fmix32(h):
    """Murmur3 finalizer: full avalanche so double-hashing probes are uncorrelated."""
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & _MASK32
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & _MASK32
    h ^= h >> 16
    return h


def _hash_pair(data):
    """Compute two independent 32-bit hashes (FNV-1a and DJB2) in one pass."""
    h1 = _FNV_OFFSET
    h2 = 5381
    for b in data:
        h1 = ((h1 ^ b) * _FNV_PRIME) & _MASK32
        h2 = ((h2 * 33) + b) & _MASK32
    return _fmix32(h1), _fmix32(h2 ^ 0x9E3779B9)


class BloomFilter:
    def __init__(self, bit_size, num_hashes, bits=None, count=0):
        if bit_size <= 0 or num_hashes <= 0:
            raise ValueError("bit_size and num_hashes must be positive")
        self.bit_size = bit_size
        self.num_hashes = num_hashes
        self.count = count
        byte_size = (bit_size + 7) // 8
        if bits is None:
            self.bits = bytearray(byte_size)
        else:
            if len(bits) != byte_size:
                raise ValueError("bit array length does not match bit_size")
            # Adopt an existing bytearray without copying: on-device RAM is too
            # tight to hold the bit array twice during load.
            self.bits = bits if isinstance(bits, bytearray) else bytearray(bits)

    @classmethod
    def create(cls, capacity, fp_rate=0.001):
        """Size a filter for `capacity` entries at the target false-positive rate."""
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if not (0.0 < fp_rate < 1.0):
            raise ValueError("fp_rate must be between 0 and 1")
        ln2 = math.log(2)
        m = int(math.ceil(-capacity * math.log(fp_rate) / (ln2 * ln2)))
        k = max(1, int(round((m / capacity) * ln2)))
        return cls(m, k)

    def _probes(self, domain):
        """Yield the k bit positions for a domain via double hashing."""
        h1, h2 = _hash_pair(domain.encode("utf-8"))
        m = self.bit_size
        h1 %= m
        h2 %= m
        if h2 == 0:
            h2 = 1
        for _ in range(self.num_hashes):
            yield h1
            h1 = (h1 + h2) % m

    def add(self, domain):
        if not domain:
            return
        bits = self.bits
        for idx in self._probes(domain):
            bits[idx >> 3] |= 1 << (idx & 7)
        self.count += 1

    def contains(self, domain):
        """True if domain is probably in the set; False means definitely not."""
        if not domain:
            return False
        bits = self.bits
        for idx in self._probes(domain):
            if not (bits[idx >> 3] & (1 << (idx & 7))):
                return False
        return True

    @property
    def size_bytes(self):
        return _HEADER_SIZE + len(self.bits)

    def save(self, filepath):
        header = bytearray(_HEADER_SIZE)
        header[0:4] = _MAGIC
        header[4] = _VERSION
        header[5] = self.num_hashes
        header[8:12] = self.bit_size.to_bytes(4, "little")
        header[12:16] = self.count.to_bytes(4, "little")
        with open(filepath, "wb") as f:
            f.write(header)
            f.write(self.bits)

    @classmethod
    def load(cls, filepath):
        """Load a filter from disk. Raises OSError if missing, ValueError if corrupt."""
        with open(filepath, "rb") as f:
            header = f.read(_HEADER_SIZE)
            if len(header) != _HEADER_SIZE or header[0:4] != _MAGIC:
                raise ValueError("not a bloom filter file")
            if header[4] != _VERSION:
                raise ValueError("unsupported bloom filter version")
            num_hashes = header[5]
            bit_size = int.from_bytes(header[8:12], "little")
            count = int.from_bytes(header[12:16], "little")
            # Single allocation + readinto: avoids holding two copies of the
            # bit array, which would exhaust the Pico's heap for large filters.
            bits = bytearray((bit_size + 7) // 8)
            if f.readinto(bits) != len(bits):
                raise ValueError("truncated bloom filter file")
        return cls(bit_size, num_hashes, bits=bits, count=count)
