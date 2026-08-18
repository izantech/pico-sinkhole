"""Main entrypoint for pico-sinkhole on Raspberry Pi Pico W / Pico 2 W."""

import gc
import sys
import time

try:
    import network
    _HAS_NETWORK = True
except ImportError:
    _HAS_NETWORK = False

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

try:
    from .bloom import BloomFilter
    from .config import Config
    from .dns_server import DNSServer
    from .filter_engine import FilterEngine
    from .led_indicator import LEDIndicator
    from .stats import Stats
except (ImportError, ValueError):
    from bloom import BloomFilter
    from config import Config
    from dns_server import DNSServer
    from filter_engine import FilterEngine
    from led_indicator import LEDIndicator
    from stats import Stats


def connect_wifi(config, led):
    """Establish WiFi station connection on Pico W / Pico 2 W."""
    wifi_cfg = config.wifi
    ssid = wifi_cfg.get("ssid", "")
    password = wifi_cfg.get("password", "")
    timeout_s = wifi_cfg.get("connect_timeout_s", 20)
    static_ip = wifi_cfg.get("static_ip", "")
    subnet = wifi_cfg.get("subnet", "255.255.255.0")
    gateway = wifi_cfg.get("gateway", "192.168.1.1")
    dns_server = wifi_cfg.get("dns", "1.1.1.1")

    if not _HAS_NETWORK:
        print("[INFO] Network module not found. Running in host / desktop mode.")
        return "127.0.0.1"

    if not ssid:
        print("[WARN] No WiFi SSID specified in config.json. Skipping WiFi setup.")
        return "0.0.0.0"

    led.set_mode(LEDIndicator.MODE_CONNECTING)
    print(f"Connecting to WiFi SSID: '{ssid}'...")

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if static_ip:
        print(f"Applying static IP: {static_ip} (Subnet: {subnet}, GW: {gateway})")
        try:
            wlan.ifconfig((static_ip, subnet, gateway, dns_server))
        except Exception as e:
            print(f"[WARN] Could not set static IP: {e}")

    wlan.connect(ssid, password)

    start = time.time()
    while not wlan.isconnected():
        if (time.time() - start) > timeout_s:
            print(f"\n[ERROR] Failed to connect to WiFi within {timeout_s} seconds.")
            return None
        print(".", end="")
        time.sleep(0.5)

    ip_info = wlan.ifconfig()
    local_ip = ip_info[0]
    print(f"\n[OK] WiFi Connected! Assigned IP: {local_ip}")
    print(f"     Subnet: {ip_info[1]} | Gateway: {ip_info[2]} | DNS: {ip_info[3]}")
    return local_ip


async def periodic_gc_task(interval_s=30):
    """Periodic garbage collection coroutine to prevent heap fragmentation."""
    while True:
        await asyncio.sleep(interval_s)
        gc.collect()


async def main_async():
    print("========================================")
    print("   PICO-SINKHOLE: Async DNS Shield      ")
    print("========================================")

    # 1. Load configuration
    config = Config.load("config.json")

    # 2. Setup LED indicator
    led_cfg = config.led
    led = LEDIndicator(pin_name=led_cfg.get("pin", "LED"), enabled=led_cfg.get("enabled", True))

    # 3. Connect WiFi
    local_ip = connect_wifi(config, led)
    led.set_mode(LEDIndicator.MODE_ONLINE)

    # 4. Initialize Filter Engine & Load Lists
    print("Loading blocklists & whitelists...")
    filter_engine = FilterEngine()

    blocked_count = filter_engine.load_from_file("blocklist.txt", is_whitelist=False)
    white_count = filter_engine.load_from_file("whitelist.txt", is_whitelist=True)

    # If no files exist, add a curated core set
    if blocked_count == 0:
        default_blocks = [
            "doubleclick.net", "google-analytics.com", "telemetry.microsoft.com",
            "adservice.google.com", "scorecardresearch.com", "adnxs.com",
            "criteo.com", "outbrain.com", "taboola.com", "pixel.facebook.com"
        ]
        for d in default_blocks:
            filter_engine.add_block(d)
        blocked_count = len(default_blocks)

    # Optional pre-built bloom filter for large blocklists (see tools/build_bloom.py)
    gc.collect()  # Free heap before the single large bit-array allocation
    try:
        bloom = BloomFilter.load("blocklist.bloom")
        filter_engine.attach_bloom(bloom)
        print(f"[OK] Bloom filter loaded: {bloom.count} domains in {bloom.size_bytes // 1024} KB.")
    except OSError:
        pass  # No blocklist.bloom deployed; text lists only
    except ValueError as e:
        print(f"[WARN] Ignoring invalid blocklist.bloom: {e}")
    except MemoryError:
        # Filter too large for this board's free heap; keep serving DNS without it
        gc.collect()
        print("[WARN] Not enough RAM to load blocklist.bloom; continuing with text lists only.")

    print(f"[OK] Filter ready: {blocked_count} blocked domains, {white_count} whitelisted domains.")

    # 5. Initialize Stats & Servers
    web_enabled = config.web.get("enabled", True)
    verbose = config.get("logging", "level", "INFO") == "INFO"

    # Ring buffer only matters for the dashboard; skip it entirely in production
    stats = Stats(max_recent=40 if web_enabled else 0)
    dns_server = DNSServer(config, filter_engine, stats, led, verbose=verbose)

    # 6. Start Web server if enabled (lazy import: keeps the module and its
    # HTML template out of RAM entirely when the dashboard is off)
    if web_enabled:
        try:
            from .web_server import WebServer
        except (ImportError, ValueError):
            from web_server import WebServer
        web_server = WebServer(config, stats, filter_engine, verbose=verbose)
        await web_server.start()

    # 7. Launch Concurrent Async Tasks
    tasks = [
        dns_server.start(),
        led.run(),
        periodic_gc_task(interval_s=30)
    ]

    print(f"\nSinkhole active! Set your devices DNS to: {local_ip or '127.0.0.1'}")
    if web_enabled:
        print(f"Web Dashboard available at: http://{local_ip or '127.0.0.1'}:{config.web.get('port', 80)}/\n")

    await asyncio.gather(*tasks)


def run():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nStopping pico-sinkhole...")


if __name__ == "__main__":
    run()
