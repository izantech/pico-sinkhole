"""Non-blocking LED status indicator for Pico W / Pico 2 W with host fallback."""

try:
    import machine
    _HAS_MACHINE = True
except ImportError:
    _HAS_MACHINE = False

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio


class LEDIndicator:
    MODE_OFF = 0
    MODE_CONNECTING = 1  # Fast blinking (100ms)
    MODE_ONLINE = 2      # Solid ON with occasional flash
    MODE_HEARTBEAT = 3   # Gentle breathing pulse

    def __init__(self, pin_name="LED", enabled=True):
        self.enabled = enabled
        self.mode = self.MODE_OFF
        self._led = None
        self._flash_until = 0

        if self.enabled and _HAS_MACHINE:
            try:
                self._led = machine.Pin(pin_name, machine.Pin.OUT)
                self._led.value(0)
            except Exception:
                # Handle numeric pin fallback (e.g. pin 25)
                try:
                    self._led = machine.Pin(25, machine.Pin.OUT)
                    self._led.value(0)
                except Exception:
                    self._led = None

    def on(self):
        if self._led:
            try:
                self._led.value(1)
            except Exception:
                pass

    def off(self):
        if self._led:
            try:
                self._led.value(0)
            except Exception:
                pass

    def toggle(self):
        if self._led:
            try:
                self._led.value(not self._led.value())
            except Exception:
                pass

    def set_mode(self, mode):
        self.mode = mode
        if mode == self.MODE_OFF:
            self.off()
        elif mode == self.MODE_ONLINE:
            self.on()

    def pulse(self):
        """Trigger a brief LED activity pulse (e.g. on blocked query)."""
        if self.enabled and self._led:
            try:
                # If online (solid ON), pulse off briefly
                # If off, pulse on briefly
                current = self._led.value()
                self._led.value(not current)
                # Revert after tiny delay in async loop
            except Exception:
                pass

    async def run(self):
        """Async background task controlling LED state transitions."""
        if not self.enabled or not self._led:
            while True:
                await asyncio.sleep(5)

        state = 0
        while True:
            if self.mode == self.MODE_CONNECTING:
                self.toggle()
                await asyncio.sleep(0.15)
            elif self.mode == self.MODE_HEARTBEAT:
                self.on()
                await asyncio.sleep(0.05)
                self.off()
                await asyncio.sleep(0.1)
                self.on()
                await asyncio.sleep(0.05)
                self.off()
                await asyncio.sleep(1.5)
            elif self.mode == self.MODE_ONLINE:
                # Keep solid ON
                self.on()
                await asyncio.sleep(1.0)
            else:
                self.off()
                await asyncio.sleep(1.0)
