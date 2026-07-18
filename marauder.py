#!/usr/bin/env python3
"""
marauder.py -- serial engine for automating an ESP32 Marauder (v1.13.0) over USB.

This is the shared building block used by every chain in chains/. It owns the
serial link and turns the Marauder text CLI into Python calls: run a scan and
get back a list of AP objects, select a target, lock a channel, toggle a
setting, watch the serial stream for a marker, etc.

Target hardware: a Marauder board's CLI ESP32 reached over its USB port at
115200 baud -- e.g. the AWOK Dynamics "Dual Touch V3" ORANGE port
(esp32_marauder_dev_board_pro.bin) or a Marauder v6/v6.1
(esp32_marauder_v6_1.bin). Both are ESP32-WROOM with SD + Bluetooth, so every
chain that needs SD (captures, evil portal) or BT works on them.

The Marauder CLI is line oriented: commands are sent LF-terminated at 115200,
and the firmware streams results back as plain text. Nothing here is guessed --
the command syntax and the `list -a` output shape are taken from Marauder
v1.13.0 (`[0][CH:3] Octoglass -66 0 selected`).

Requires: pip install pyserial
"""

import re
import sys
import threading
import time
from dataclasses import dataclass

# pyserial is imported lazily so the pure-logic helpers (parse_aps, find_target,
# ...) stay importable and testable without the dependency. Opening a real
# connection raises a clear error if pyserial is missing.
try:
    import serial
    from serial.tools import list_ports
    _SERIAL_ERR = None
except ImportError as _e:  # pragma: no cover - depends on environment
    serial = None
    list_ports = None
    _SERIAL_ERR = _e


def _require_serial():
    if serial is None:
        raise RuntimeError("pyserial is required for serial I/O. Install it with: "
                           "pip install pyserial")

BAUD = 115200
LINE_ENDING = b"\n"
# Firmware needs a beat to parse each command before the next one arrives.
POST_COMMAND_SETTLE_S = 0.15

# Example line parsed:  [0][CH:3] Octoglass -66 0 selected
#   [index][CH:channel] <ESSID (may contain spaces)> <RSSI (negative)> <n> [selected]
_AP_LINE = re.compile(r"^\s*\[(\d+)\]\[CH:\s*(\d+)\]\s+(.+?)\s+(-\d+)\b")
# Raw scan stream line:  RSSI: -57 Ch: 3 BSSID: 50:ff:20:84:d6:0f ESSID: Octoglass
_RAW_AP_LINE = re.compile(
    r"RSSI:\s*(-?\d+)\s+Ch:\s*(\d+)\s+BSSID:\s*([0-9a-fA-F:]{17})\s+ESSID:\s*(.*)")
# Station/client line from `list -c`:  [0] AA:BB:CC:DD:EE:FF -> ...
_STA_LINE = re.compile(r"^\s*\[(\d+)\]\s+([0-9a-fA-F:]{17})")


@dataclass
class AP:
    index: int
    channel: int
    essid: str
    rssi: int
    bssid: str = ""

    def __str__(self):
        b = " " + self.bssid if self.bssid else ""
        return "[{}] ch{:>2} {:>4}dBm  {}{}".format(
            self.index, self.channel, self.rssi, self.essid, b)


@dataclass
class Station:
    index: int
    mac: str

    def __str__(self):
        return "[{}] {}".format(self.index, self.mac)


class Marauder:
    """Thin, blocking driver around the Marauder serial CLI."""

    def __init__(self, port=None, baud=BAUD, echo=True, logfile=None):
        self.port = port or self._autodetect()
        self.baud = baud
        self.echo = echo
        self._logfile = logfile
        self._ser = None
        self._buf = ""
        self._lock = threading.Lock()
        self._stop_reader = threading.Event()
        self._thread = None

    # -- connection -------------------------------------------------------
    def _autodetect(self):
        _require_serial()
        found = []
        for p in list_ports.comports():
            blob = "{} {}".format(p.description or "", p.manufacturer or "").lower()
            dev = (p.device or "")
            if any(k in blob for k in ("cp210", "ch340", "wch", "usb", "uart", "serial")) \
                    or "ttyusb" in dev.lower() or "ttyacm" in dev.lower() \
                    or "cu.usb" in dev.lower() or dev.upper().startswith("COM"):
                found.append(dev)
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            raise RuntimeError(
                "Multiple serial ports found: {}. The Dual board exposes TWO ports "
                "(one per ESP32); pass port=... for the CLI (orange) ESP32.".format(", ".join(found)))
        raise RuntimeError("No serial port found; pass port=... explicitly.")

    def open(self):
        _require_serial()
        self._ser = serial.Serial(self.port, self.baud, timeout=0.1)
        self._stop_reader.clear()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        time.sleep(1.0)  # let the port settle (some adapters auto-reset the ESP)
        self.send("stopscan")  # known-idle starting state
        time.sleep(0.3)
        self.drain()
        return self

    def close(self):
        try:
            self.send("stopscan")
            time.sleep(0.3)
        except Exception:
            pass
        self._stop_reader.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._ser:
            self._ser.close()
        if self._logfile:
            self._logfile.flush()

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()
        return False

    # -- io ---------------------------------------------------------------
    def _read_loop(self):
        while not self._stop_reader.is_set():
            try:
                data = self._ser.read(4096)
            except (OSError, serial.SerialException):
                break
            if not data:
                continue
            text = data.decode("utf-8", errors="replace")
            if self.echo:
                sys.stdout.write(text)
                sys.stdout.flush()
            if self._logfile:
                self._logfile.write(text)
            with self._lock:
                self._buf += text
                if len(self._buf) > 262144:
                    self._buf = self._buf[-262144:]

    def send(self, cmd):
        """Send one CLI command (LF-terminated) and let the firmware settle."""
        if self.echo:
            sys.stdout.write("\n>>> {}\n".format(cmd))
            sys.stdout.flush()
        self._ser.write(cmd.encode("utf-8") + LINE_ENDING)
        self._ser.flush()
        time.sleep(POST_COMMAND_SETTLE_S)

    def drain(self):
        """Forget any buffered output so the next capture() starts clean."""
        with self._lock:
            self._buf = ""

    def snapshot(self):
        with self._lock:
            return self._buf

    def capture(self, cmd, settle=2.0):
        """Send a command, wait `settle` seconds, and return everything printed since."""
        self.drain()
        self.send(cmd)
        time.sleep(settle)
        return self.snapshot()

    def wait_for(self, needles, timeout=30.0):
        """Block until any string in `needles` appears in the stream, or timeout.

        Returns the matched needle, or None on timeout. Case-insensitive.
        """
        if isinstance(needles, str):
            needles = [needles]
        needles_l = [n.lower() for n in needles]
        self.drain()
        deadline = time.time() + timeout
        while time.time() < deadline:
            blob = self.snapshot().lower()
            for orig, low in zip(needles, needles_l):
                if low in blob:
                    return orig
            time.sleep(0.1)
        return None

    def sleep(self, seconds):
        time.sleep(seconds)

    # -- high level helpers ----------------------------------------------
    def stop(self, force=False):
        self.send("stopscan -f" if force else "stopscan")
        time.sleep(0.3)

    def set_channel(self, channel):
        self.send("channel -s {}".format(int(channel)))

    def select_ap(self, index):
        self.send("select -a {}".format(int(index)))

    def select_station(self, index):
        self.send("select -c {}".format(int(index)))

    def clear_aps(self):
        self.send("clearlist -a")

    def setting(self, name, enabled):
        self.send("settings -s {} {}".format(name, "enable" if enabled else "disable"))

    def scan_aps(self, seconds=20, clear=True):
        """Run scanap for `seconds`, then parse `list -a` into AP objects.

        Indices in the returned APs are the firmware's own list indices, so they
        can be handed straight to select_ap()/`evilportal -c setap`.
        """
        self.stop()
        if clear:
            self.clear_aps()
        self.send("scanap")
        time.sleep(seconds)
        self.stop()
        text = self.capture("list -a", settle=2.5)
        return self.parse_aps(text)

    def scan_stations(self, ap_seconds=15, sta_seconds=20):
        """scanap (needed first) then scansta, then parse `list -c`."""
        self.stop()
        self.clear_aps()
        self.send("scanap")
        time.sleep(ap_seconds)
        self.stop()
        self.send("scansta")
        time.sleep(sta_seconds)
        self.stop()
        text = self.capture("list -c", settle=2.5)
        return self.parse_stations(text)

    # -- parsing ----------------------------------------------------------
    @staticmethod
    def parse_aps(text):
        aps = []
        for line in text.splitlines():
            m = _AP_LINE.search(line)
            if m:
                aps.append(AP(index=int(m.group(1)), channel=int(m.group(2)),
                              essid=m.group(3).strip(), rssi=int(m.group(4))))
        return aps

    @staticmethod
    def parse_raw_scan(text):
        """Parse the streaming scanap output (includes BSSID)."""
        out = []
        for line in text.splitlines():
            m = _RAW_AP_LINE.search(line)
            if m:
                out.append(AP(index=-1, channel=int(m.group(2)), essid=m.group(4).strip(),
                              rssi=int(m.group(1)), bssid=m.group(3).lower()))
        return out

    @staticmethod
    def parse_stations(text):
        stations = []
        for line in text.splitlines():
            m = _STA_LINE.search(line)
            if m:
                stations.append(Station(index=int(m.group(1)), mac=m.group(2).lower()))
        return stations


def find_target(aps, ssid=None):
    """Pick a target AP: exact/substring SSID match if given, else strongest RSSI."""
    if not aps:
        return None
    if ssid:
        want = ssid.lower()
        exact = [a for a in aps if a.essid.lower() == want]
        if exact:
            return max(exact, key=lambda a: a.rssi)
        partial = [a for a in aps if want in a.essid.lower()]
        if partial:
            return max(partial, key=lambda a: a.rssi)
        return None
    return max(aps, key=lambda a: a.rssi)


def add_common_args(parser):
    """Wire up the flags every chain shares."""
    parser.add_argument("--port", help="serial port (e.g. /dev/ttyUSB0, COM5). Auto-detected if omitted.")
    parser.add_argument("--baud", type=int, default=BAUD, help="baud rate (default 115200)")
    parser.add_argument("--quiet", action="store_true", help="do not echo the board's serial output")
    parser.add_argument("--log", help="append all board serial output to this file")
    return parser


def connect_from_args(args):
    logfile = open(args.log, "a", encoding="utf-8") if getattr(args, "log", None) else None
    m = Marauder(port=getattr(args, "port", None), baud=getattr(args, "baud", BAUD),
                 echo=not getattr(args, "quiet", False), logfile=logfile)
    return m.open()
