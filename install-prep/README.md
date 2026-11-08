# Radix: Linux install assistant (`install-prep/`)

Radix helps you go from "I want Linux" to a verified, bootable USB stick or SD card:

**scan → recommend → pick → download → verify → flash**

The first, browser-independent parts are built. Everything is Python 3 standard library
(plus `gpg` if present), so it runs on a fresh live system.

| Path | What it is |
|---|---|
| `prep.py` | CLI: `scan`, `list`, `info`, `download`, `verify`, `fetch-sums`, `drives`, `flash`, `seed-wifi` |
| `catalog/distros.json` | distro catalog: image, checksum and signature URLs, pinned key fingerprints (all checked 2026-11-08) |
| `web/` | static guidance page with an in-browser streaming SHA-256 checker, no tracking, no external scripts |
| `scan/radix-scan.sh` | the one-line, read-only scan shown on the page (prints `RADIX-SCAN-1:…`) |
| `docs/SCAN.md` | step 1: scan format, browser estimate, Windows/macOS guidance, scoring rules and sources |
| `docs/FLASHING.md` | flashing workflow, why WebUSB can't do it, the Radix Flasher and localhost-bridge plan, manual steps per OS |
| `docs/SD-CARDS.md` | finding the right card/stick, sizing, fake-capacity cards, safe ejection |
| `docs/WIFI.md` | optional Wi-Fi pre-seeding (Raspberry Pi OS / cloud-init only), what it adds, the first-boot notice |
| `docs/RECOMMENDATIONS.md` | scan-first recommendations and options, planned popularity indicator, "try it in a VM" |
| `tests/` | stdlib `unittest` suite plus a node check for the JS SHA-256 |

## Quick start

```bash
python3 prep.py scan                                            # step 1: read-only scan + distro fit
python3 prep.py list
python3 prep.py info mint-cinnamon                              # display-only details
python3 prep.py download debian-netinst --dir ~/isos          # resumable
python3 prep.py fetch-sums debian-netinst --dir ~/isos        # checksum file + GPG check vs pinned key
python3 prep.py verify ~/isos/debian-13.7.0-amd64-netinst.iso --sums-file ~/isos/SHA256SUMS
python3 prep.py drives -v                                     # removable USB/SD only
python3 prep.py flash ~/isos/debian-13.7.0-amd64-netinst.iso --device /dev/sdX   # rehearsal (dry run)
# real write: sudo python3 prep.py flash IMG --device /dev/sdX --write --confirm <drive serial> --sums-file SUMS
```

`fetch-sums` uses a throwaway GPG home, so nothing is added to your keyring, and accepts
the file only if the signature is from the pinned fingerprint.

## Safety rails

* System disks (anything holding `/`, `/boot`, `/boot/efi`, `/usr`, `/var`, `/home`, swap)
  and internal SATA/NVMe disks are never listed or written, including the live USB you
  booted from.
* `flash` is a rehearsal unless you add `--write` and type the drive's **serial**.
* A device write checks the image checksum first, needs root, unmounts the drive, opens it
  exclusively, `fsync`s, then reads the written bytes back and compares SHA-256.
* HTTPS only. The hardware report (planned) stays on your machine.

## Optional Wi-Fi pre-seeding

For Raspberry Pi OS (cloud-init) only: `--wifi-ssid NAME --wifi-psk-file FILE --wifi-country US`
on `flash`, or `seed-wifi --boot-dir` afterwards. The password is never taken on the command
line. **If you used this tool to pre-program a Wi-Fi password, the password will remain on
this machine, so don't give the machine away.** It is also stored on the card. See
[docs/WIFI.md](docs/WIFI.md).

## Web page

```bash
cd install-prep && python3 -m http.server 8000 --bind 127.0.0.1
# open http://127.0.0.1:8000/web/
```

Flashing happens **outside the browser**: browsers block USB mass-storage access on purpose
(see `docs/FLASHING.md`).

## Tests

```bash
cd install-prep/tests && python3 -m unittest -v
node install-prep/tests/sha256_js_test.js      # optional, if node is installed
node install-prep/tests/scan_js_test.js        # JS scan parser/scoring must match prep.py
```

Tests only ever write regular temporary files, never a block device.

## Not built yet

Richer scoring data (more official RAM / Secure Boot facts, GPU and Wi-Fi driver notes), Wi-Fi pre-seeding for live ISOs, Radix Flasher (localhost bridge or desktop wrapper),
`prep.py try` (prints a QEMU command), Windows/macOS writing, signed releases, hosting the
page on opencommons.app.
