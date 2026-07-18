#!/usr/bin/env python3
"""
presence_monitor.py -- watch an area over time and log devices coming and going.

  loop: scanap -> parse -> diff against the last pass -> print/log every AP that
  APPEARED or DISAPPEARED, with timestamps -> wait the interval -> repeat.

Turns the board into an unattended presence/logging sensor and writes an event
log on the HOST. Marauder v1.13.0 primitives only.

Note: `list -a` exposes ESSID/channel/RSSI (not BSSID), so devices are keyed by
"essid@channel". Two APs sharing an SSID+channel look like one entry.
AUTHORIZED USE ONLY.

  python3 chains/presence_monitor.py --interval 60 --scan-seconds 15
  python3 chains/presence_monitor.py --interval 120 --log presence.log --port /dev/ttyUSB0
"""

import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from marauder import add_common_args, connect_from_args  # noqa: E402


def key(ap):
    return "{}@{}".format(ap.essid, ap.channel)


def ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main():
    ap = argparse.ArgumentParser(description="Log AP appear/disappear events over time")
    add_common_args(ap)
    ap.add_argument("--interval", type=int, default=60, help="seconds between passes (default 60)")
    ap.add_argument("--scan-seconds", type=int, default=15, help="scan duration per pass (default 15)")
    ap.add_argument("--events", help="append appear/disappear events to this host file")
    args = ap.parse_args()

    evfile = open(args.events, "a", encoding="utf-8") if args.events else None

    def emit(line):
        print(line)
        if evfile:
            evfile.write(line + "\n")
            evfile.flush()

    m = connect_from_args(args)
    known = {}
    first = True
    try:
        emit("# presence monitor started {}".format(ts()))
        while True:
            aps = m.scan_aps(args.scan_seconds)
            seen = {key(a): a for a in aps}
            if first:
                for k, a in sorted(seen.items()):
                    emit("{}  BASELINE  {}  ch{} {}dBm".format(ts(), a.essid, a.channel, a.rssi))
                first = False
            else:
                for k, a in seen.items():
                    if k not in known:
                        emit("{}  APPEARED  {}  ch{} {}dBm".format(ts(), a.essid, a.channel, a.rssi))
                for k, a in known.items():
                    if k not in seen:
                        emit("{}  GONE      {}  ch{}".format(ts(), a.essid, a.channel))
            known = seen
            emit("{}  --- {} APs in view; sleeping {}s ---".format(ts(), len(seen), args.interval))
            m.sleep(args.interval)
    except KeyboardInterrupt:
        emit("# stopped {}".format(ts()))
    finally:
        m.close()
        if evfile:
            evfile.close()


if __name__ == "__main__":
    main()
