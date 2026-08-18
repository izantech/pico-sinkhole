"""Build a blocklist.bloom file from one or more domain blocklists (PC-side).

Downloads (or reads locally) plain domain lists — e.g. hagezi *-onlydomains.txt
or hosts-format files — deduplicates them, prunes subdomains already covered by
a parent entry, and writes a compact bloom filter for deployment to the Pico.

Examples:
    # Default: hagezi Multi Light (~43k domains, ~75 KB filter)
    python tools/build_bloom.py

    # Smart-TV focused: native tracker lists for living-room devices
    python tools/build_bloom.py \
        --source hagezi:native.apple \
        --source hagezi:native.samsung \
        --source hagezi:native.lgwebos \
        --source hagezi:native.roku

    # Custom mix: any URL or local file, hagezi shorthand allowed
    python tools/build_bloom.py --source hagezi:pro.mini --source my-extra-list.txt
"""

import argparse
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bloom import BloomFilter
from src.filter_engine import FilterEngine

HAGEZI_BASE = "https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/wildcard/{}-onlydomains.txt"
DEFAULT_SOURCE = "hagezi:light"


def resolve_source(source):
    """Expand 'hagezi:<name>' shorthand to the CDN URL; pass through URLs/paths."""
    if source.startswith("hagezi:"):
        return HAGEZI_BASE.format(source.split(":", 1)[1])
    return source


def read_lines(source):
    url = resolve_source(source)
    if url.startswith("http://") or url.startswith("https://"):
        print(f"Downloading {url} ...")
        req = urllib.request.Request(url, headers={"User-Agent": "pico-sinkhole-build-bloom"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode("utf-8", "replace").splitlines()
    print(f"Reading {url} ...")
    with open(url, "r", encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()


def collect_domains(sources):
    domains = set()
    for source in sources:
        before = len(domains)
        for line in read_lines(source):
            # Some wildcard-style lists prefix entries with '*.'
            if line.startswith("*."):
                line = line[2:]
            cleaned = FilterEngine._clean_domain(line)
            if cleaned:
                domains.add(cleaned)
        print(f"  -> {len(domains) - before} new domains ({len(domains)} total)")
    return domains


def prune_covered_subdomains(domains):
    """Drop entries whose parent domain is also listed (subdomain matching covers them)."""
    pruned = set()
    for domain in domains:
        parts = domain.split(".")
        covered = False
        for i in range(1, len(parts) - 1):
            if ".".join(parts[i:]) in domains:
                covered = True
                break
        if not covered:
            pruned.add(domain)
    return pruned


def main():
    parser = argparse.ArgumentParser(description="Build a bloom filter blocklist for pico-sinkhole.")
    parser.add_argument(
        "--source", action="append", default=None,
        help="Blocklist source: URL, local file, or 'hagezi:<name>' "
             f"(repeatable; default: {DEFAULT_SOURCE})"
    )
    parser.add_argument("--fp-rate", type=float, default=0.001,
                        help="Target false-positive rate (default: 0.001 = 0.1%%)")
    parser.add_argument("--output", default="blocklist.bloom",
                        help="Output file path (default: blocklist.bloom)")
    args = parser.parse_args()

    sources = args.source or [DEFAULT_SOURCE]
    domains = collect_domains(sources)
    if not domains:
        print("[ERROR] No domains collected; nothing to build.")
        return 1

    before = len(domains)
    domains = prune_covered_subdomains(domains)
    print(f"Pruned {before - len(domains)} subdomains already covered by parent entries.")

    bloom = BloomFilter.create(len(domains), args.fp_rate)
    for domain in domains:
        bloom.add(domain)
    bloom.save(args.output)

    print(f"\n[OK] Wrote {args.output}:")
    print(f"     {bloom.count} domains | {bloom.size_bytes / 1024:.1f} KB "
          f"| k={bloom.num_hashes} hashes | target FP rate {args.fp_rate:g}")
    print("     Deploy with: .\\dev.ps1 deploy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
