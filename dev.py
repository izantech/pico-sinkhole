#!/usr/bin/env python3
"""Cross-platform development & deployment tool for pico-sinkhole.

All dev-task logic lives here; ./dev (bash), dev.ps1, and dev.cmd are thin
shims that invoke this script. Requires Python 3.8+ on any OS. mpremote and
mpy-cross are installed on demand via pip and invoked as modules, so they work
even when the pip scripts directory is not on PATH.

Usage: python dev.py <command> [options]   (or ./dev, .\\dev.ps1, dev)
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

PORT = None  # set by --port; otherwise mpremote auto-detects

USAGE = """\
Pico-Sinkhole Dev Tool
Usage: dev <command> [options]

Commands:
  deploy        Sync all files to connected Pico, reset, and stream logs
  monitor       Open live serial monitor / REPL (aliases: logs, repl)
  ls            List files on Pico filesystem
  reset         Soft reset connected Pico
  test          Run Python test suite on PC
  run-local     Run sinkhole locally on PC for testing
  update-lists  Build blocklist.bloom from hagezi lists (see tools/build_bloom.py)
  help          Show this help (default)

Options:
  --mpy           deploy only: precompile src/ with mpy-cross (less RAM on
                  device; mpy-cross version must match firmware version)
  --no-repl       deploy only: skip the log stream after deploying
  --port <dev>    Serial port (e.g. COM7, /dev/ttyACM0, /dev/cu.usbmodem101);
                  auto-detected when omitted
"""


def log(msg):
    print(f"[dev] {msg}")


def die(msg):
    print(f"[dev] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def ensure_installed(module, package):
    try:
        __import__(module)
    except ImportError:
        log(f"Installing {package}...")
        subprocess.run([sys.executable, "-m", "pip", "install", package], check=True)


def mp(*args, check=True, capture=False):
    """Run an mpremote command, honoring --port."""
    cmd = [sys.executable, "-m", "mpremote"]
    if PORT:
        cmd += ["connect", PORT]
    cmd += list(args)
    return subprocess.run(cmd, check=check, capture_output=capture, text=True)


def ensure_config():
    config = ROOT / "config.json"
    if not config.exists():
        log("config.json not found; copying config.example.json -> config.json")
        shutil.copyfile(ROOT / "config.example.json", config)
        log("IMPORTANT: edit config.json to add your WiFi SSID and password!")


def sweep_stale(expected):
    """Remove anything in :src not in the expected set: stale .py after --mpy,
    stale .mpy after a plain deploy, and orphans from deleted/renamed modules."""
    listing = mp("ls", ":src", check=False, capture=True)
    if listing.returncode != 0:
        return
    for line in listing.stdout.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or not parts[0].isdigit():
            continue  # header or unexpected line
        name = parts[1].strip()
        if name.endswith("/"):
            log(f"Removing stale directory :src/{name[:-1]}...")
            mp("rm", "-r", f":src/{name[:-1]}", check=False, capture=True)
        elif name not in expected:
            log(f"Removing stale :src/{name}...")
            mp("rm", f":src/{name}", check=False, capture=True)


def cmd_deploy(mpy=False, repl=True):
    ensure_installed("mpremote", "mpremote")
    ensure_config()

    log("Syncing files to Pico...")
    try:
        mp("cp", str(ROOT / "config.json"), ":config.json")
        mp("cp", str(ROOT / "blocklist.txt"), ":blocklist.txt")
        mp("cp", str(ROOT / "whitelist.txt"), ":whitelist.txt")
        if (ROOT / "blocklist.bloom").exists():
            log("Copying blocklist.bloom...")
            mp("cp", str(ROOT / "blocklist.bloom"), ":blocklist.bloom")
        mp("cp", str(ROOT / "main.py"), ":main.py")
        mp("mkdir", ":src", check=False, capture=True)

        src_files = sorted((ROOT / "src").glob("*.py"))
        expected = set()

        if mpy:
            # Precompiled deploy: mpy-cross version must match the firmware's
            # MicroPython version, or imports fail with "incompatible .mpy file"
            ensure_installed("mpy_cross", "mpy-cross")
            out_dir = ROOT / "build" / "mpy"
            out_dir.mkdir(parents=True, exist_ok=True)
            for f in src_files:
                out = out_dir / f"{f.stem}.mpy"
                log(f"Compiling src/{f.name} -> build/mpy/{out.name}...")
                subprocess.run(
                    [sys.executable, "-m", "mpy_cross", str(f), "-o", str(out)],
                    check=True,
                )
                mp("cp", str(out), f":src/{out.name}")
                expected.add(out.name)
        else:
            for f in src_files:
                log(f"Copying src/{f.name}...")
                mp("cp", str(f), f":src/{f.name}")
                expected.add(f.name)

        sweep_stale(expected)

        log("Resetting Pico and starting application...")
        mp("reset")
    except subprocess.CalledProcessError as e:
        die(
            f"Deployment failed ({e}). If Thonny, a monitor, or another program "
            "is using the serial port, close it and retry."
        )

    if repl:
        log("Streaming serial logs (Ctrl+] exits; Ctrl+C stops the app on the device until reset)")
        mp("repl", check=False)


def cmd_monitor():
    ensure_installed("mpremote", "mpremote")
    log("Opening serial monitor / REPL (Ctrl+] to exit)")
    mp("repl", check=False)


def cmd_ls():
    ensure_installed("mpremote", "mpremote")
    log("Files on Pico root (/)")
    mp("ls", ":")
    log("Files on Pico (/src)")
    mp("ls", ":src")


def cmd_reset():
    ensure_installed("mpremote", "mpremote")
    log("Resetting device...")
    mp("reset")


def cmd_test():
    log("Running host unit test suite")
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
        cwd=ROOT,
    )
    sys.exit(result.returncode)


def cmd_run_local():
    log("Starting sinkhole on local PC (desktop mode)")
    result = subprocess.run([sys.executable, str(ROOT / "main.py")], cwd=ROOT)
    sys.exit(result.returncode)


def cmd_update_lists(extra_args):
    log("Building bloom filter blocklist (blocklist.bloom)")
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "build_bloom.py"), *extra_args],
        cwd=ROOT,
    )
    sys.exit(result.returncode)


def main(argv):
    global PORT

    command = argv[0] if argv else "help"
    args = argv[1:]

    mpy = False
    repl = True
    passthrough = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--mpy":
            mpy = True
        elif arg == "--no-repl":
            repl = False
        elif arg == "--port":
            i += 1
            if i >= len(args):
                die("--port requires a device path")
            PORT = args[i]
        elif arg in ("-h", "--help"):
            print(USAGE)
            return
        else:
            passthrough.append(arg)
        i += 1

    if command in ("deploy", "sync"):
        cmd_deploy(mpy=mpy, repl=repl)
    elif command in ("monitor", "logs", "repl"):
        cmd_monitor()
    elif command == "ls":
        cmd_ls()
    elif command == "reset":
        cmd_reset()
    elif command == "test":
        cmd_test()
    elif command == "run-local":
        cmd_run_local()
    elif command == "update-lists":
        cmd_update_lists(passthrough)
    elif command in ("help", "-h", "--help"):
        print(USAGE)
    else:
        print(USAGE)
        die(f"Unknown command: {command}")


if __name__ == "__main__":
    main(sys.argv[1:])
