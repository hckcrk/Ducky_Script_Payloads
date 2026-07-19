# Quack Quack

# Flipper Zero BadUSB / DuckyScript Payloads (2026)

Flipper Zero **BadUSB** payloads in the Flipper DuckyScript dialect, organized by
target OS. These demonstrate the real BadUSB attack *classes* (HID injection,
local reconnaissance, clipboard/data-at-rest access, security-posture read-outs,
and awareness demos of current 2024–2026 techniques) using modern, built-in
OS tooling.

> **Authorized use only.** BadUSB devices inject keystrokes as the logged-in
> user. Run these only on machines you own or are contracted to test. HID
> injection against systems you're not authorized to touch is illegal.

## Design boundary (what's here and what isn't)

Every payload is **local-only and non-destructive** by design:

- Recon/report payloads write to the **local Desktop/home only** — no network
  callbacks, no upload, **no exfiltration**.
- Posture payloads are **read-only** — they *report* Defender/Gatekeeper/SELinux
  status, they never disable it.
- Awareness payloads type benign text or show a notification.

Intentionally **not** included (these are malware, not test artifacts):
remote download-and-execute / stagers / reverse shells, credential or data
**exfiltration off the host**, AV/Defender-disable or AMSI/ETW evasion,
persistence/backdoors, and anything destructive (wipe/ransomware). If an
engagement genuinely needs those, they belong in a scoped, written-authorized
C2 framework — not a drive-by USB payload — and you'd add them yourself.

## Deploying to the Flipper

1. Copy the `.txt` files to the Flipper SD card under **`badusb/`** (subfolders
   are fine, e.g. `badusb/windows/`). Use qFlipper or a card reader.
2. On the Flipper: **Apps → USB → Bad USB**, pick the script, plug into the
   target, **Run**.
3. **Keyboard layout matters.** Set the BadUSB layout to match the target's
   keyboard (default is US `en-US`). A mismatched layout mistypes symbols. In
   the Bad USB app: open the script → left-arrow / layout option → choose the
   matching `.kl`.

## DuckyScript dialect notes (Flipper)

Flipper extends classic Rubber Ducky 1.0. Commands used here / available:
`REM`, `DELAY`, `DEFAULT_DELAY`, `STRING`, `STRINGLN` (types + Enter),
`STRING_DELAY`, `REPEAT`, `ENTER`, `GUI`/`WINDOWS` (= Cmd on macOS),
`CTRL`/`ALT`/`SHIFT`, arrows, `F1`–`F12`. Also available: `HOLD`/`RELEASE`,
`WAIT_FOR_BUTTON_PRESS`, `ALTSTRING`/`ALTCHAR`/`ALTCODE`, `SYSRQ`, mouse
(`LEFTCLICK`/`MOUSEMOVE`/…), and a custom `ID` line for USB VID/PID.

The `DELAY` values assume an app/terminal takes ~1–2 s to open. Slow machines
may need larger delays; bump the `DELAY`/`DEFAULT_DELAY` values.

## Catalog

### `windows/`
| Payload | Class | Effect |
|---|---|---|
| `awareness_usbdrop.txt` | awareness | Notepad message about USB-drop risk |
| `clickfix_awareness.txt` | social-eng (ClickFix) | Run-dialog paste demo, **benign** message only |
| `recon_local.txt` | recon (LOLBins) | systeminfo/ipconfig/wifi/ports/users → Desktop file |
| `wifi_profiles_local.txt` | credential recon | `netsh wlan export key=clear` → **local** folder |
| `security_posture_report.txt` | posture (read-only) | Defender/firewall/BitLocker status → Desktop file |
| `clipboard_snapshot_local.txt` | data-at-rest | current clipboard → Desktop file |

### `macos/`
| Payload | Class | Effect |
|---|---|---|
| `awareness_usbdrop.txt` | awareness | TextEdit awareness message |
| `recon_local.txt` | recon | sw_vers/system_profiler/ifconfig/wifi → Desktop file |
| `notification_demo.txt` | HID/LOLBin | `osascript` system notification |
| `clipboard_snapshot_local.txt` | data-at-rest | `pbpaste` → Desktop file |
| `security_posture_report.txt` | posture (read-only) | Gatekeeper/SIP/FileVault/firewall status → Desktop file |

### `linux/`
| Payload | Class | Effect |
|---|---|---|
| `awareness_usbdrop.txt` | awareness | terminal awareness message |
| `recon_local.txt` | recon | uname/ip/nmcli/ss/who → `~/recon_*.txt` |
| `notify_demo.txt` | HID/LOLBin | `notify-send` desktop notification |
| `clipboard_snapshot_local.txt` | data-at-rest | `wl-paste`/`xclip` → `~/clipboard_*.txt` |
| `security_posture_report.txt` | posture (read-only) | SELinux/AppArmor/ufw/updates/logins → `~/posture_*.txt` |

macOS uses `GUI SPACE` (Spotlight) to launch apps; Linux uses `CTRL ALT T` for a
terminal (varies by desktop — adjust if yours differs).

## Marauder Red-Team Automation Chains

Host-side automation for the **ESP32 Marauder firmware v1.13.0**, driven over the
board's **USB serial CLI** (115200 baud). These are *chains* — multi-step
workflows that stitch the firmware's existing primitives into one hands-off run.
They are **not** wrappers around single touchscreen features; each does something
the board can't do on its own (loop/iterate, react to serial output, pull data
back to your computer, clone + deploy in sequence).

> **Authorized use only.** Everything here is for security testing on networks and
> devices you own or have **explicit written permission** to assess. Deauth,
> beacon/probe transmission, and captive-portal credential capture are illegal
> against systems you are not authorized to test.

### Target hardware / firmware

Primary target is the **AWOK Dynamics "Dual Touch V3"** board. It has **two
ESP32-WROOM chips**: one drives the touchscreen UI, the other is the **CLI/GPIO
ESP32 exposed on the ORANGE USB port**, flashed with
**`esp32_marauder_dev_board_pro.bin`**. The board is fully self-contained (its own
SD card + GPS); a Flipper Zero or battery pack only supplies power. Automation
happens by talking to that orange-port ESP32's Marauder CLI over serial — the
Flipper is **not** involved and there is **no companion app**.

| Firmware `.bin` | Board | Chip | BT | SD | Chains that apply |
|---|---|---|---|---|---|
| `esp32_marauder_dev_board_pro.bin` | AWOK Dual Touch V3 (orange port) | ESP32-WROOM | yes | yes | **all** |
| `esp32_marauder_v6_1.bin` | Marauder v6 / v6.1 | ESP32-WROOM | yes | yes | **all** (CLI is identical — same scripts, no changes) |
| `esp32_marauder_flipper.bin` | Official Flipper WiFi Dev Board | **ESP32-S2** | no | no | recon/report/presence only; **no evil portal or SD captures** |

The chains talk to the firmware's CLI, so they run **unchanged** on any WROOM
Marauder (dev_board_pro *and* v6_1 — no need for per-bin copies). The only real
difference is `esp32_marauder_flipper.bin`: that board is an **ESP32-S2** with no
Bluetooth and no SD card, so anything needing SD (portal, pcap captures) or BT
does not work there.

### Requirements

```
python3 -m pip install pyserial
```

If two serial ports show up (the Dual board exposes one per ESP32), pass the
CLI/orange-port one explicitly: `--port /dev/ttyUSB0` (Linux/mac) or `--port COM5`
(Windows).

### The engine — `marauder.py`

A small serial driver every chain imports. It runs commands, reads the stream,
and parses `scanap` / `list -a` / `list -c` output into Python objects
(`AP`, `Station`) so chains can pick targets, lock channels, toggle settings, and
wait for markers. Command syntax and the `list -a` format
(`[0][CH:3] Octoglass -66 0 selected`) are taken from Marauder v1.13.0.

### The chains — `chains/`

| Chain | What one run does end-to-end |
|---|---|
| `evil_twin_portal.py` | scan → pick target AP → **clone its SSID** (`evilportal -c setap`) → select it + enable **EPDeauth** (deauth the real AP while the twin runs) → serve your cloned portal → stream captured creds |
| `target_pmkid.py` | scan → locate ONE AP by **SSID or BSSID** → lock its channel → select it → `sniffpmkid -l -d` → stop on a capture marker or timeout |
| `handshake_harvester.py` | scan → find active channels → walk each channel running `sniffpmkid -c <ch> -d` for a dwell window → PMKID/EAPOL `.pcap`s land on SD (feed to hcxpcapngtool → hashcat) |
| `beacon_probe.py` | build the SSID list the mode needs → `beacon-list` / `beacon-random` / `beacon-clone` / `probe` / `rickroll` transmit → timed → `stopscan` |
| `recon_report.py` | `scanap` + `scansta` → pull the lists back over serial → write `recon_*.csv` + `.json` **on your computer** |
| `presence_monitor.py` | rescan on an interval → diff vs. last pass → log every AP that **appeared/disappeared** with timestamps |

```
python3 chains/recon_report.py --ap-seconds 25 --sta-seconds 30
python3 chains/target_pmkid.py --target-bssid 50:ff:20:84:d6:0f --capture-seconds 90
python3 chains/handshake_harvester.py --dwell 45
python3 chains/beacon_probe.py --mode beacon-list --ssids "FreeWiFi,Guest,Lobby" --duration 60
python3 chains/presence_monitor.py --interval 60 --events presence.log
```

BSSID targeting note: `list -a` doesn't expose BSSIDs, so
`target_pmkid.py` reads them from the streaming `scanap` output and correlates
by (SSID, channel). A BSSID that never lands in `list -a` can't be selected —
fall back to `--target-ssid` or `handshake_harvester.py` for that channel.

### The evil-twin workflow (clone → deploy → harvest)

Marauder's evil portal serves **one self-contained `index.html`** from the SD
root, **<= ~20 KB**, and captures credentials from a form that
**`POST`s to `/get`** with inputs named **`email`** / **`password`**
(-> `evil_portal_x.log` on SD + serial). It redirects *all* requests to itself, so
remote resource links won't load — everything must be inlined.

1. **Clone the target page you're authorized to mimic** into a Marauder-ready file:
   ```
   python3 clone_portal.py --url http://portal.example.com/login --ssid "Corp-Guest" --out index.html
   ```
   `clone_portal.py` fetches the page, inlines CSS/images, rewires the form to
   `/get` (email/password), minifies, and **enforces the 20 KB budget** — trimming
   JS/fonts/large images to fit and telling you exactly what it dropped. A literal
   pixel-perfect clone of a heavy site often won't fit 20 KB; that's a Marauder
   limit, not a tool bug.
2. **Copy `index.html` to the board's SD card root** (pull the card / use a reader).
3. **Run the chain:**
   ```
   python3 chains/evil_twin_portal.py --target-ssid "Corp-Guest" --html index.html --duration 600
   ```

#### Ready-made neutral portals — `portals/`

Generic, brand-neutral captive-portal templates that already meet Marauder's
contract (single file, <= 20 KB, `/get`, `email`/`password`). Use for
guest-network / user-susceptibility assessments without impersonating a third
party. Rename to `index.html` on the SD root, or `evilportal -c sethtml <file>`.

- `generic_guest_wifi.html` — dark "Guest WiFi Access" sign-in
- `generic_hotspot_light.html` — light "Public WiFi" sign-in

These intentionally do **not** impersonate Google/Apple/ISPs or any real brand.
For a specific authorized target, clone that target with `clone_portal.py`.

### Notes on accuracy

Command syntax is from Marauder **v1.13.0** (e.g. the signal command is `foxhunt`,
not the older `sigmon`; BT wardrive is `btwardrive -c`). Scan dwell times and the
serial-output parser are built to the documented v1.13.0 formats; if your unit
prints slightly differently, the timings/regex in `marauder.py` are the only
things to tune.
