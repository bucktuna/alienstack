# Step 1: scan the target machine

Radix starts by looking at the computer Linux will run on. The scan drives the
recommendations in step 2. Everything is **read-only, needs no sudo, and stays local**.

## One thing to run, one thing to paste

1. **Copy & run** the command shown on the Radix page (the same text is in
   [`scan/radix-scan.sh`](../scan/radix-scan.sh)) in a terminal on the target machine: its
   existing Linux or a Linux live USB. It is plain POSIX `sh`, works on a stock live system,
   needs nothing from Radix, and is printed in full on the page (no `curl | sh`).
2. **Paste the result**, one line `RADIX-SCAN-1:<base64>`, into the big box on the page. It is
   decoded in your browser and never uploaded. Wrapped lines and surrounding prompt text are
   fine.

`python3 prep.py scan --paste` prints the same format; `prep.py scan` prints a summary and the
fit of each catalog distro; `prep.py scan --json` prints JSON, which the page also accepts.
`prep.py scan --from-paste FILE` scores a saved block.

### Format `RADIX-SCAN-1`

Base64 of UTF-8 `key=value` lines. Unknown values are empty and are shown as "unknown".

| key | from |
|---|---|
| `arch` | `uname -m` (normalized: x86_64, arm64, armhf, x86) |
| `cpu_model` | `lscpu` "Model name", else `/proc/cpuinfo` |
| `cores` | `getconf _NPROCESSORS_ONLN` (threads) |
| `mem_kb` | `/proc/meminfo` MemTotal |
| `boot` | `uefi` if `/sys/firmware/efi` exists, else `bios` |
| `secure_boot` | `mokutil --sb-state` if present, else byte 5 of the `SecureBoot-*` efivar; `not-applicable` on BIOS; otherwise empty (unknown) |
| `fw_vendor`, `fw_version`, `fw_date` | `/sys/class/dmi/id/bios_*` |
| `board` | `/proc/device-tree/model` (Raspberry Pi and other ARM boards) |
| `disk_bytes` | largest whole disk from `lsblk` |
| `gpu`, `wifi` (repeatable) | `lspci` display / network controller names, bus address stripped |

Deliberately **not** collected: serial numbers, UUIDs, hostnames, MAC/IP addresses, user names.

## Quick in-browser estimate

The page can also estimate from the browser itself, clearly labeled *estimate, this device
only*: CPU type from `navigator.userAgentData` (high-entropy `architecture`/`bitness`) or the
user agent (Macs always report "Intel", so a Mac stays unknown), thread count from
`hardwareConcurrency`, memory from `deviceMemory` (rounded down and capped at 8 GB, so only
"8 GB or more" is used for scoring), and the WebGL renderer name for the GPU where the browser
exposes it. Secure Boot, firmware and boot mode are invisible to web pages and stay unknown.

## Windows and macOS (manual for now)

* **Windows:** `msinfo32` → System Type (x64-based / ARM64-based), Installed Physical Memory,
  BIOS Mode (UEFI / Legacy), Secure Boot State, BIOS Version/Date. For a full scan, boot a
  Linux live USB and run the one-liner.
* **macOS:** Apple menu → About This Mac (chip, memory). Intel Macs are x86_64; Apple Silicon
  needs Asahi Linux (not in this catalog).

## Scoring rules

Implemented twice with identical results (checked by `tests/scan_js_test.js`):
`score_distro` in `prep.py` and `scoreDistro` in `web/radix-core.js`. Facts live in each
catalog entry's `requirements`; `null` means unknown and is never guessed.

1. No architecture in the scan → **Can't tell**.
2. Architecture not in the image's `requirements.arch` → **Not a fit** ("Built for arm64; this
   machine is x86_64").
3. Image needs a board (`Raspberry Pi`) and the scan names another board → **Not a fit**; no
   board in the scan → **Works** with "couldn't confirm".
4. RAM below 90% of an official minimum → **Not a fit** (10% slack because MemTotal reads
   below installed RAM).
5. Secure Boot enabled and the distro's support is unconfirmed → **Works**, "you may need to
   turn it off".
6. RAM meets the official recommendation (or minimum), or Secure Boot is on and officially
   supported → **Recommended**.
7. Otherwise → **Works**, saying what is unconfirmed.

### Facts used and their sources (checked 2026-11-08)

| Distro | Fact | Source |
|---|---|---|
| all | architecture of the image | the catalog entry (official image name/URL) |
| Ubuntu 26.04.1 | 6 GB system memory | <https://ubuntu.com/download/desktop> |
| Debian 13 | with desktop: 1 GB minimum, 2 GB recommended | <https://www.debian.org/releases/trixie/amd64/ch03s04.en.html> |
| Debian 13 | Secure Boot supported via Microsoft-signed shim | <https://wiki.debian.org/SecureBoot> |
| Raspberry Pi OS | Raspberry Pi boards only, arm64 | the official image name |

Not yet confirmed (left unknown): RAM figures for Mint, Fedora, EndeavourOS and Raspberry Pi
OS; Secure Boot support for Ubuntu, Mint, Fedora and EndeavourOS (their pages either did not
state it or blocked automated reading today). Add them only with a source.
