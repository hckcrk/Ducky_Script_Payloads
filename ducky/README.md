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
