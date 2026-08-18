"""DNS packet parser and sinkhole response generator adhering to RFC 1035."""

# DNS Query Types
TYPE_A = 1
TYPE_NS = 2
TYPE_CNAME = 5
TYPE_SOA = 6
TYPE_PTR = 12
TYPE_MX = 15
TYPE_TXT = 16
TYPE_AAAA = 28
TYPE_HTTPS = 65
TYPE_ANY = 255

# DNS Response Codes (RCODE)
RCODE_NOERROR = 0
RCODE_FORMERR = 1
RCODE_SERVFAIL = 2
RCODE_NXDOMAIN = 3
RCODE_NOTIMP = 4
RCODE_REFUSED = 5

TYPE_NAMES = {
    TYPE_A: "A",
    TYPE_AAAA: "AAAA",
    TYPE_CNAME: "CNAME",
    TYPE_PTR: "PTR",
    TYPE_MX: "MX",
    TYPE_TXT: "TXT",
    TYPE_HTTPS: "HTTPS",
    TYPE_ANY: "ANY"
}


class DNSQuery:
    __slots__ = ("tx_id", "flags", "domain", "qtype", "qtype_name", "qclass", "question_raw")

    def __init__(self, tx_id, flags, domain, qtype, qclass, question_raw):
        self.tx_id = tx_id
        self.flags = flags
        self.domain = domain
        self.qtype = qtype
        self.qtype_name = TYPE_NAMES.get(qtype, f"TYPE{qtype}")
        self.qclass = qclass
        self.question_raw = question_raw

    def __repr__(self):
        return f"<DNSQuery id={self.tx_id} domain='{self.domain}' type={self.qtype_name}>"


def parse_ipv4(ip_str):
    """Convert IPv4 string '1.2.3.4' to 4-byte buffer."""
    try:
        parts = ip_str.split(".")
        if len(parts) == 4:
            return bytes([int(p) for p in parts])
    except (ValueError, TypeError):
        pass
    return b"\x00\x00\x00\x00"


def parse_dns_query(data):
    """
    Parse a raw DNS UDP payload.
    Returns a DNSQuery instance, or None if packet is invalid / not a standard query.
    """
    if not data or len(data) < 12:
        return None

    # Transaction ID (2 bytes)
    tx_id = data[:2]

    # Flags (2 bytes)
    flags = int.from_bytes(data[2:4], "big")
    qr = (flags >> 15) & 0x01
    opcode = (flags >> 11) & 0x0F

    # Only process standard incoming queries (QR=0, Opcode=0)
    if qr != 0 or opcode != 0:
        return None

    qdcount = int.from_bytes(data[4:6], "big")
    if qdcount < 1:
        return None

    # Parse Question Section (starts at byte 12)
    domain_parts = []
    i = 12
    data_len = len(data)

    while i < data_len:
        length = data[i]
        if length == 0:
            i += 1
            break
        # Pointer in question (unusual in standard single query)
        if (length & 0xC0) == 0xC0:
            i += 2
            break
        i += 1
        if i + length > data_len:
            return None  # Truncated label
        try:
            domain_parts.append(data[i:i + length].decode("utf-8").lower())
        except UnicodeError:
            domain_parts.append(data[i:i + length].decode("latin-1").lower())
        i += length

    domain = ".".join(domain_parts)

    # Need 4 more bytes for QTYPE (2) and QCLASS (2)
    if i + 4 > data_len:
        return None

    qtype = int.from_bytes(data[i:i + 2], "big")
    qclass = int.from_bytes(data[i + 2:i + 4], "big")
    question_raw = data[12:i + 4]

    return DNSQuery(tx_id, flags, domain, qtype, qclass, question_raw)


def build_sinkhole_response(query, blocking_mode="null_ip", ttl=60, sink_ipv4="0.0.0.0"):
    """
    Construct an RFC 1035-compliant DNS sinkhole response.
    Supports 'null_ip' (0.0.0.0 / ::) and 'nxdomain'.
    """
    tx_id = query.tx_id
    question_section = query.question_raw

    if blocking_mode == "nxdomain":
        # Standard query response, Authoritative, Recursion Available, NXDOMAIN (RCODE=3)
        flags = b"\x85\x83"
        counts = b"\x00\x01\x00\x00\x00\x00\x00\x00"  # 1 Question, 0 Answers, 0 Authority, 0 Additional
        return tx_id + flags + counts + question_section

    # Null IP blocking mode
    ttl_bytes = int(ttl).to_bytes(4, "big")

    if query.qtype == TYPE_A:
        # IPv4 Sinkhole: Return 0.0.0.0
        flags = b"\x81\x80"  # Response, No Error, Recursion Available
        counts = b"\x00\x01\x00\x01\x00\x00\x00\x00"  # 1 Question, 1 Answer
        rdata = parse_ipv4(sink_ipv4)
        # Pointer to QNAME at byte 12 (0xC00C), Type A (0x0001), Class IN (0x0001), TTL, Length (4), RDATA
        answer_section = b"\xc0\x0c\x00\x01\x00\x01" + ttl_bytes + b"\x00\x04" + rdata
        return tx_id + flags + counts + question_section + answer_section

    elif query.qtype == TYPE_AAAA:
        # IPv6 Sinkhole: Return :: (16 null bytes)
        flags = b"\x81\x80"
        counts = b"\x00\x01\x00\x01\x00\x00\x00\x00"
        rdata = b"\x00" * 16
        # Pointer (0xC00C), Type AAAA (0x001C), Class IN (0x0001), TTL, Length (16), RDATA
        answer_section = b"\xc0\x0c\x00\x1c\x00\x01" + ttl_bytes + b"\x00\x10" + rdata
        return tx_id + flags + counts + question_section + answer_section

    else:
        # For non-IP queries (HTTPS, MX, TXT, etc.) on blocked domains: return NODATA (NoError, 0 answers)
        flags = b"\x81\x80"
        counts = b"\x00\x01\x00\x00\x00\x00\x00\x00"
        return tx_id + flags + counts + question_section
