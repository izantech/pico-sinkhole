import unittest
from src.dns_packet import (
    parse_dns_query,
    build_sinkhole_response,
    parse_ipv4,
    TYPE_A,
    TYPE_AAAA,
    TYPE_HTTPS,
    DNSQuery
)


class TestDNSPacket(unittest.TestCase):

    def _make_query_packet(self, domain, qtype=TYPE_A, tx_id=b"\x12\x34"):
        """Helper to craft standard raw DNS query payload."""
        flags = b"\x01\x00"  # Standard query, RD=1
        counts = b"\x00\x01\x00\x00\x00\x00\x00\x00"  # 1 question
        # Encode domain labels
        parts = domain.split(".")
        qname_bytes = bytearray()
        for p in parts:
            b_part = p.encode("ascii")
            qname_bytes.append(len(b_part))
            qname_bytes.extend(b_part)
        qname_bytes.append(0x00)  # Terminator

        qtype_bytes = int(qtype).to_bytes(2, "big")
        qclass_bytes = b"\x00\x01"  # IN
        return tx_id + flags + counts + bytes(qname_bytes) + qtype_bytes + qclass_bytes

    def test_parse_valid_a_query(self):
        packet = self._make_query_packet("ads.google.com", TYPE_A, tx_id=b"\xab\xcd")
        query = parse_dns_query(packet)
        self.assertIsNotNone(query)
        self.assertEqual(query.tx_id, b"\xab\xcd")
        self.assertEqual(query.domain, "ads.google.com")
        self.assertEqual(query.qtype, TYPE_A)
        self.assertEqual(query.qtype_name, "A")
        self.assertEqual(query.qclass, 1)

    def test_parse_valid_aaaa_query(self):
        packet = self._make_query_packet("tracker.example.org", TYPE_AAAA, tx_id=b"\x56\x78")
        query = parse_dns_query(packet)
        self.assertIsNotNone(query)
        self.assertEqual(query.tx_id, b"\x56\x78")
        self.assertEqual(query.domain, "tracker.example.org")
        self.assertEqual(query.qtype, TYPE_AAAA)
        self.assertEqual(query.qtype_name, "AAAA")

    def test_parse_invalid_or_truncated(self):
        self.assertIsNone(parse_dns_query(b""))
        self.assertIsNone(parse_dns_query(b"\x00" * 11))  # Less than 12 bytes
        # Non-standard query (QR=1, Response flag)
        res_packet = b"\x12\x34\x81\x80\x00\x01\x00\x00\x00\x00\x00\x00\x07example\x03com\x00\x00\x01\x00\x01"
        self.assertIsNone(parse_dns_query(res_packet))

    def test_build_sinkhole_response_a_record(self):
        packet = self._make_query_packet("ads.doubleclick.net", TYPE_A, tx_id=b"\x1a\x2b")
        query = parse_dns_query(packet)
        sink_res = build_sinkhole_response(query, blocking_mode="null_ip", ttl=60, sink_ipv4="0.0.0.0")

        self.assertIsNotNone(sink_res)
        self.assertEqual(sink_res[:2], b"\x1a\x2b")  # Matching Transaction ID
        self.assertEqual(sink_res[2:4], b"\x81\x80")  # Response flags (QR=1, RA=1, NoError)
        self.assertEqual(sink_res[4:6], b"\x00\x01")  # QDCOUNT = 1
        self.assertEqual(sink_res[6:8], b"\x00\x01")  # ANCOUNT = 1

        # Check last 4 bytes are 0.0.0.0
        self.assertEqual(sink_res[-4:], b"\x00\x00\x00\x00")

    def test_build_sinkhole_response_aaaa_record(self):
        packet = self._make_query_packet("ads.doubleclick.net", TYPE_AAAA, tx_id=b"\x3c\x4d")
        query = parse_dns_query(packet)
        sink_res = build_sinkhole_response(query, blocking_mode="null_ip", ttl=60)

        self.assertIsNotNone(sink_res)
        self.assertEqual(sink_res[:2], b"\x3c\x4d")
        self.assertEqual(sink_res[2:4], b"\x81\x80")
        self.assertEqual(sink_res[6:8], b"\x00\x01")  # 1 answer
        # Check last 16 bytes are null bytes (::)
        self.assertEqual(sink_res[-16:], b"\x00" * 16)

    def test_build_sinkhole_response_nxdomain(self):
        packet = self._make_query_packet("blocked.site", TYPE_A, tx_id=b"\xfe\xdc")
        query = parse_dns_query(packet)
        sink_res = build_sinkhole_response(query, blocking_mode="nxdomain")

        self.assertEqual(sink_res[:2], b"\xfe\xdc")
        # Flags with RCODE=3 (NXDOMAIN) -> 0x8583
        self.assertEqual(sink_res[2:4], b"\x85\x83")
        self.assertEqual(sink_res[6:8], b"\x00\x00")  # 0 answers

    def test_parse_ipv4(self):
        self.assertEqual(parse_ipv4("0.0.0.0"), b"\x00\x00\x00\x00")
        self.assertEqual(parse_ipv4("192.168.1.1"), b"\xc0\xa8\x01\x01")
        self.assertEqual(parse_ipv4("invalid"), b"\x00\x00\x00\x00")


if __name__ == "__main__":
    unittest.main()
