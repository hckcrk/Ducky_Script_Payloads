#!/usr/bin/env python3
"""
send.py -- drive an ESP32 Marauder (v1.13.0) over its USB serial CLI.

Target hardware for this repo: the AWOK Dynamics "Dual Touch V3" board's
CLI/GPIO ESP32 (the ORANGE USB port), flashed with
`esp32_marauder_dev_board_pro.bin`. The board is fully self-contained --
the Flipper Zero (or a battery pack) only supplies power. There is NO Flipper
companion app involved; this script talks straight to the Marauder command
line over serial.

It reads a plain-text "playlist" of Marauder CLI commands plus a few timing
directives and streams them to the board at 115200 baud.

Playlist directives (case-insensitive on the directive keyword):
    # ...                  comment line (blank lines ignored too)
    REM ...                comment line
    DELAY <n>              wait n milliseconds (use e.g. `DELAY 20000`)
    DELAY <n>s             wait n seconds (e.g. `DELAY 20s`)
    WAITFOR "text" [<ms>]  wait until the board prints <text> (max <ms>, default 20000)
    STOP                   convenience alias -> sends `stopscan`
    <anything else>        sent verbatim to the board as one CLI command (LF-terminated)

Usage:
    python3 send.py PLAYLIST.txt
    python3 send.py payloads/dev_board_pro/recon_scan_aps.txt --port /dev/ttyUSB0
    python3 send.py PLAYLIST.txt --baud 115200 --delay-scale 1.5 --log run.txt

Notes:
    * Requires pyserial:  pip install pyserial
    * If --port is omitted the script tries to auto-detect a USB-serial adapter.
      On the Dual board there are TWO serial ports (one per ESP32); pass --port
      explicitly to be sure you are driving the CLI (orange-port) ESP32.
    * On exit (normal, error, or Ctrl-C) the script sends `stopscan` so the
      board is left idle. Disable with --no-safe-stop.
"""

import argparse
import sys
import threading
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.stderr.write(
        "ERROR: pyserial is not installed.\n"
        "Install it with:  pip install pyserial\n"
    )
    sys.exit(1)

# Marauder's serial CLI runs at 115200 and processes a command when it receives
# a newline (LF). CR is ignored by the firmware parser.
DEFAULT_BAUD = 115200
LINE_ENDING = b"\n"
# Small settle time after each command so the firmware can parse before the next.
POST_COMMAND_SETTLE_S = 0.15


class SerialReader:
    """Background reader: prints everything the board sends and keeps a small
    rolling buffer so WAITFOR can match on recent output."""

    def __init__(self, ser, logfile=None, quiet=False):
        self._ser = ser
        self._logfile = logfile
        self._quiet = quiet
        self._buf = ""
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=1.0)

    def _run(self):
        while not self._stop.is_set():
            try:
                data = self._ser.read(4096)
            except (OSError, serial.SerialException):
                break
            if not data:
                continue
            text = data.decode("utf-8", errors="replace")
            if not self._quiet:
                sys.stdout.write(text)
                sys.stdout.flush()
            if self._logfile:
                self._logfile.write(text)
                self._logfile.flush()
            with self._lock:
                self._buf += text
                # keep only the last 64 KB so matching stays cheap
                if len(self._buf) > 65536:
                    self._buf = self._buf[-65536:]

    def reset_match_buffer(self):
        with self._lock:
            self._buf = ""

    def contains(self, needle):
        with self._lock:
            return needle in self._buf


class MarauderDriver:
    def __init__(self, ser, reader, delay_scale=1.0):
        self._ser = ser
        self._reader = reader
        self._delay_scale = delay_scale

    def send_command(self, cmd):
        print(">>> {}".format(cmd))
        self._ser.write(cmd.encode("utf-8") + LINE_ENDING)
        self._ser.flush()
        time.sleep(POST_COMMAND_SETTLE_S)

    def delay_ms(self, ms):
        secs = (ms / 1000.0) * self._delay_scale
        print("... DELAY {} ms{}".format(
            ms, "" if self._delay_scale == 1.0 else " (x{} = {:.1f}s)".format(self._delay_scale, secs)))
        time.sleep(secs)

    def waitfor(self, needle, timeout_ms):
        print('... WAITFOR "{}" (<= {} ms)'.format(needle, timeout_ms))
        self._reader.reset_match_buffer()
        deadline = time.time() + (timeout_ms / 1000.0) * self._delay_scale
        while time.time() < deadline:
            if self._reader.contains(needle):
                print('    matched "{}"'.format(needle))
                return True
            time.sleep(0.05)
        print('    (timeout waiting for "{}", continuing)'.format(needle))
        return False


def parse_waitfor(rest):
    """Parse the argument part of `WAITFOR "text" [ms]`. Returns (needle, timeout_ms)."""
    rest = rest.strip()
    timeout_ms = 20000
    if rest.startswith('"'):
        end = rest.find('"', 1)
        if end == -1:
            return rest[1:], timeout_ms
        needle = rest[1:end]
        tail = rest[end + 1:].strip()
        if tail:
            try:
                timeout_ms = int(tail)
            except ValueError:
                pass
        return needle, timeout_ms
    # unquoted: first token is the needle, optional second token is the timeout
    parts = rest.split()
    needle = parts[0] if parts else ""
    if len(parts) > 1:
        try:
            timeout_ms = int(parts[1])
        except ValueError:
            pass
    return needle, timeout_ms


def parse_delay(rest):
    """Parse `<n>` (ms) or `<n>s` (seconds). Returns milliseconds (int)."""
    token = rest.strip().split()[0] if rest.strip() else "0"
    if token.lower().endswith("s"):
        return int(round(float(token[:-1]) * 1000))
    return int(round(float(token)))


def run_playlist(path, driver):
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for raw in lines:
        line = raw.rstrip("\r\n")
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue

        # split off the first word to check for a directive
        head = stripped.split(None, 1)
        keyword = head[0].upper()
        rest = head[1] if len(head) > 1 else ""

        if keyword == "REM":
            continue
        if keyword == "DELAY":
            driver.delay_ms(parse_delay(rest))
            continue
        if keyword == "WAITFOR":
            needle, timeout_ms = parse_waitfor(rest)
            driver.waitfor(needle, timeout_ms)
            continue
        if keyword == "STOP":
            driver.send_command("stopscan")
            continue

        # anything else is a raw Marauder CLI command
        driver.send_command(stripped)


def autodetect_port():
    candidates = []
    for p in list_ports.comports():
        desc = "{} {}".format(p.description or "", p.manufacturer or "").lower()
        if any(k in desc for k in ("cp210", "ch340", "ch910", "usb", "uart", "serial", "wch")):
            candidates.append(p.device)
        elif p.device and ("ttyusb" in p.device.lower() or "ttyacm" in p.device.lower()
                           or "cu.usb" in p.device.lower() or p.device.upper().startswith("COM")):
            candidates.append(p.device)
    return candidates


def main():
    ap = argparse.ArgumentParser(
        description="Drive an ESP32 Marauder v1.13.0 over its USB serial CLI.")
    ap.add_argument("playlist", help="path to a .txt command playlist")
    ap.add_argument("--port", help="serial port (e.g. /dev/ttyUSB0, COM5). Auto-detected if omitted.")
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="baud rate (default 115200)")
    ap.add_argument("--delay-scale", type=float, default=1.0,
                    help="multiply every DELAY/WAITFOR by this factor (e.g. 1.5 for slower boards)")
    ap.add_argument("--log", help="also write all board output to this file")
    ap.add_argument("--quiet", action="store_true", help="do not echo board output to the console")
    ap.add_argument("--no-safe-stop", action="store_true",
                    help="do NOT send `stopscan` on start and exit")
    args = ap.parse_args()

    port = args.port
    if not port:
        found = autodetect_port()
        if len(found) == 1:
            port = found[0]
            print("Auto-detected serial port: {}".format(port))
        elif len(found) > 1:
            sys.stderr.write(
                "Multiple serial ports found: {}\n"
                "The Dual board exposes TWO ports (one per ESP32). "
                "Re-run with --port <the CLI/orange-port ESP32>.\n".format(", ".join(found)))
            sys.exit(2)
        else:
            sys.stderr.write("No serial port found. Pass one with --port.\n")
            sys.exit(2)

    logfile = open(args.log, "w", encoding="utf-8") if args.log else None

    try:
        ser = serial.Serial(port, args.baud, timeout=0.1)
    except serial.SerialException as e:
        sys.stderr.write("ERROR: could not open {} @ {}: {}\n".format(port, args.baud, e))
        if logfile:
            logfile.close()
        sys.exit(2)

    reader = SerialReader(ser, logfile=logfile, quiet=args.quiet)
    driver = MarauderDriver(ser, reader, delay_scale=args.delay_scale)

    print("Connected to {} @ {} baud. Running: {}".format(port, args.baud, args.playlist))
    print("-" * 60)
    reader.start()
    # give the port a moment to settle after opening (ESP auto-reset on some adapters)
    time.sleep(1.0)

    try:
        if not args.no_safe_stop:
            driver.send_command("stopscan")
            time.sleep(0.3)
        run_playlist(args.playlist, driver)
    except KeyboardInterrupt:
        print("\n[interrupted]")
    finally:
        try:
            if not args.no_safe_stop:
                print("-" * 60)
                driver.send_command("stopscan")
                time.sleep(0.5)
        except Exception:
            pass
        reader.stop()
        ser.close()
        if logfile:
            logfile.close()
        print("Done. Port closed.")


if __name__ == "__main__":
    main()
