"""pico-sinkhole root entrypoint for MicroPython."""

import sys

# Ensure src/ is in the import search path if files are in a folder
if "src" not in sys.path:
    sys.path.append("src")

try:
    from src.main import run
except (ImportError, ValueError):
    from main import run

if __name__ == "__main__":
    run()
