#!/usr/bin/env python3
"""
recon_report.py -- one hands-off recon pass that lands a structured report on
your COMPUTER (something the standalone board never gives you).

  scanap  ->  scansta  ->  pull `list -a` + `list -c` back over serial  ->
  parse  ->  write recon_<timestamp>.csv and .json on the host.

This is the value the touchscreen can't provide: the data comes off the board
and into files you can grep, diff, or hand to a report. Marauder v1.13.0
primitives only. AUTHORIZED USE ONLY.

  python3 chains/recon_report.py --ap-seconds 25 --sta-seconds 30
  python3 chains/recon_report.py --out engagement1 --port /dev/ttyUSB0
"""

import argparse
import csv
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from marauder import add_common_args, connect_from_args  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Recon -> CSV/JSON report on the host")
    add_common_args(ap)
    ap.add_argument("--ap-seconds", type=int, default=20, help="scanap duration (default 20)")
    ap.add_argument("--sta-seconds", type=int, default=25, help="scansta duration (default 25)")
    ap.add_argument("--out", help="output basename (default recon_<timestamp>)")
    args = ap.parse_args()

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = args.out or "recon_{}".format(stamp)

    m = connect_from_args(args)
    try:
        print("\n[*] AP scan {}s ...".format(args.ap_seconds))
        aps = m.scan_aps(args.ap_seconds)
        print("[*] {} APs".format(len(aps)))
        print("\n[*] Station scan {}s ...".format(args.sta_seconds))
        stations = m.scan_stations(ap_seconds=max(10, args.ap_seconds // 2),
                                   sta_seconds=args.sta_seconds)
        print("[*] {} stations".format(len(stations)))
    finally:
        m.close()

    report = {
        "captured_at": stamp,
        "access_points": [vars(a) for a in aps],
        "stations": [vars(s) for s in stations],
    }
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    with open(base + "_aps.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["index", "channel", "essid", "rssi", "bssid"])
        for a in aps:
            w.writerow([a.index, a.channel, a.essid, a.rssi, a.bssid])
    with open(base + "_stations.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["index", "mac"])
        for s in stations:
            w.writerow([s.index, s.mac])

    print("\n[*] Wrote {0}.json, {0}_aps.csv, {0}_stations.csv".format(base))


if __name__ == "__main__":
    main()
