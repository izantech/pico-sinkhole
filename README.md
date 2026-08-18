# 🛡️ pico-sinkhole

A lightweight, asynchronous **DNS Sinkhole** (Ad & Tracker Blocker) designed specifically for the **Raspberry Pi Pico W** and **Raspberry Pi Pico 2 W** running **MicroPython**.

Turn your $6 micro-controller into a silent, ultra-low-power, network-wide ad shield with a real-time web dashboard and LED status feedback!

---

## ✨ Features

- **⚡ Truly Asynchronous (`asyncio`)**: Uses non-blocking UDP I/O. DNS queries are handled concurrently without freezing the Pico when upstream DNS latency or packet loss occurs.
- **🏁 Racing Upstream Resolvers**: Every allowed query is sent to both upstream DNS servers at once and the first reply wins — resolution keeps working at full speed even if one upstream is down or silently blocked by your ISP (e.g. networks that null-route `1.1.1.1`).
- **🚫 Smart Domain Filtering**: Fast $O(K)$ set-based lookup with automatic **subdomain/wildcard matching** (blocking `doubleclick.net` automatically blocks `ad.doubleclick.net` and all nested subdomains).
- **🌐 Dual-Stack Protection**: Generates RFC 1035-compliant responses for both **IPv4 (`A` -> `0.0.0.0`)** and **IPv6 (`AAAA` -> `::`)**, preventing dual-stack operating system timeouts.
- **📊 Embedded Web Dashboard**: Built-in async HTTP server (port 80) showing real-time query counts, blocked rates, RAM usage (`gc.mem_free`), and live activity logs. Auto-refreshes every 5 seconds.
- **🔌 REST API Endpoint**: `/api/stats` endpoint returning JSON formatted metrics for Prometheus, Home Assistant, or custom integrations.
- **💡 Hardware LED Status**: Visual indicator for WiFi connection progress, steady heartbeat online, and flash pulses on blocked DNS queries.
- **📝 Whitelist & False-Positive Prevention**: Built-in whitelist for critical connectivity checks (Android, Apple, Microsoft NCSI, NTP).
- **🌸 Bloom Filter Blocklists**: Load 40,000+ domains (e.g. [hagezi lists](https://github.com/hagezi/dns-blocklists)) in ~75 KB of RAM via a pre-built bloom filter — zero false negatives, ~0.1% false-positive rate.
- **🧪 100% Host Testable**: Comprehensive test suite that runs directly on PC via standard Python `unittest`.

---

## 📁 Project Structure

```
pico-sinkhole/
├── dev.ps1                # PowerShell development & deployment automation
├── config.example.json   # Configuration template
├── blocklist.txt          # Default curated ad & tracker blocklist
├── whitelist.txt          # Essential domains whitelist (connectivity checks)
├── .gitignore             # Git ignore rules for secrets and build files
├── README.md              # Project documentation
├── main.py                # Device root entrypoint
├── src/
│   ├── __init__.py        # Package init
│   ├── main.py            # Main application bootstrap & WiFi connector
│   ├── config.py          # Configuration manager with deep merge
│   ├── dns_packet.py      # Binary DNS parser & RFC 1035 response builder
│   ├── filter_engine.py   # Exact and wildcard domain matcher
│   ├── bloom.py           # Bloom filter for large blocklists in tiny RAM
│   ├── dns_server.py      # Async UDP DNS server & upstream relay
│   ├── web_server.py      # Lightweight async HTTP dashboard server
│   ├── stats.py           # Metrics aggregator & circular activity log
│   └── led_indicator.py   # Non-blocking LED status supervisor
├── tools/
│   └── build_bloom.py     # PC-side bloom filter builder (hagezi lists etc.)
└── tests/
    ├── test_config.py        # Configuration tests
    ├── test_dns_packet.py    # Binary parser & sinkhole serializer tests
    ├── test_filter_engine.py # Subdomain matching & whitelist precedence tests
    ├── test_bloom.py         # Bloom filter & FilterEngine integration tests
    ├── test_stats.py         # Stats & ring buffer tests
    ├── test_dns_server.py    # Async DNS UDP integration tests
    └── test_web_server.py    # Async HTTP dashboard & JSON API tests
```

---

## 🚀 Quick Start Guide

### 1. Requirements
- **Raspberry Pi Pico W** or **Raspberry Pi Pico 2 W**.
- MicroPython firmware installed (download latest `.uf2` from [micropython.org](https://micropython.org/download/RPI_PICO2_W/)).
- **Thonny IDE** (recommended) or `mpremote` / `ampy`.

### 2. Configuration
Copy `config.example.json` to `config.json` and enter your WiFi credentials:

```bash
cp config.example.json config.json
```

Edit `config.json`:
```json
{
  "wifi": {
    "ssid": "YOUR_WIFI_SSID",
    "password": "YOUR_WIFI_PASSWORD",
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
    "ttl": 60
  },
  "web": {
    "enabled": true,
    "port": 80
  },
  "led": {
    "enabled": true,
    "pin": "LED"
  }
}
```

### 3. Deploy to Pico W / Pico 2 W
You can deploy automatically using the development script:

```pwsh
# 1. Ensure Thonny is closed so COM port is free
# 2. Deploy files, soft-reset Pico, and start streaming logs:
.\dev.ps1 deploy
```

Alternatively, you can manually upload using **Thonny IDE**:
1. Connect your Pico to your computer via USB.
2. Open **Thonny IDE** and select MicroPython on Raspberry Pi Pico as interpreter.
3. Upload `config.json`, `blocklist.txt`, `whitelist.txt`, `main.py`, and `src/` to the device root.
4. Run `main.py`.

---

## 🌸 Large Blocklists via Bloom Filter

The in-memory sets in `blocklist.txt` are limited to a few thousand domains by the Pico's RAM. To use large curated lists like [hagezi/dns-blocklists](https://github.com/hagezi/dns-blocklists) (~43k domains for the Light list), build a compact bloom filter on your PC:

```pwsh
# Build blocklist.bloom from hagezi Multi Light (~75 KB for ~43k domains)
.\dev.ps1 update-lists

# Or pick your own mix (any 'hagezi:<name>' shorthand, URL, or local file):
python tools\build_bloom.py --source hagezi:native.apple --source hagezi:native.samsung
python tools\build_bloom.py --source hagezi:pro.mini --fp-rate 0.001
```

`.\dev.ps1 deploy` automatically copies `blocklist.bloom` to the device if present, and it is loaded at boot alongside the text lists. Bloom filters have **no false negatives** (every listed domain is always blocked) and a small tunable false-positive chance (default 0.1%). If a legitimate domain is ever wrongly blocked, add it to `whitelist.txt` — the whitelist always wins.

---

## 🔋 Production Mode (Saving RAM)

The dashboard is great while debugging but costs RAM: the HTML renderer churns the heap on every auto-refresh, and each query allocates a ring-buffer entry and log strings. For day-to-day operation, switch to the production profile in `config.json`:

```json
{
  "web": { "enabled": false },
  "logging": { "level": "WARN" }
}
```

With the web server disabled, the dashboard module is never even imported (its code and HTML template stay out of RAM entirely), the recent-query ring buffer is skipped, and `"WARN"` silences the per-query serial logs. Counters keep working. Flip both settings back to re-enable the dashboard for debugging.

For extra headroom, deploy precompiled bytecode instead of source:

```pwsh
.\dev.ps1 deploy -Mpy
```

This compiles `src/` with `mpy-cross` on the PC, removing the on-device compile spike at boot. The installed `mpy-cross` version must match the firmware's MicroPython version — if the device reports `incompatible .mpy file` at boot, run a plain `.\dev.ps1 deploy` (it cleans up the `.mpy` files automatically).

---

## 🖥️ Using the Sinkhole

### Point Your Devices / Router
Once booted, the Pico will display its assigned IP (e.g., `192.168.1.50`):
- **For entire network:** In your home router's DHCP settings, set the **Primary DNS Server** to your Pico's IP address.
- **For single device:** In your PC or smartphone Wi-Fi network settings, set DNS manually to the Pico's IP address.

### Web Dashboard
Open your browser and navigate to:
```
http://<PICO_IP>/
```
Example: `http://192.168.1.50/`

You will see the real-time statistics dashboard with active query counts, blocked rates, and live query history.

### JSON API
Fetch stats programmatically:
```bash
curl http://192.168.1.50/api/stats
```

---

## 🧪 Testing & Development on PC

You can run the entire test suite on your computer (Windows / Linux / macOS) without needing physical hardware:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

To run the sinkhole locally on your PC in desktop mode:
```bash
python -m src.main
```

Then test with `nslookup`:
```bash
# Test blocked ad domain (returns 0.0.0.0)
nslookup ads.google.com 127.0.0.1

# Test allowed domain (forwards to 1.1.1.1)
nslookup wikipedia.org 127.0.0.1
```

---

## 📜 License

MIT License. Feel free to use and modify for personal or commercial projects.
