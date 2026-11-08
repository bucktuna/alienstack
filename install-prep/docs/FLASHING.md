# Flashing workflow (design)

Radix (the Linux install assistant) runs **scan → recommend → pick → download → verify →
flash**. The scan of the target machine comes first and drives the recommendations
([RECOMMENDATIONS.md](RECOMMENDATIONS.md)); this page covers the last step. The work is split
in two:

| Part | Runs where | Does |
|---|---|---|
| Web page (`web/`) | any browser, static files, no tracking | pick a distro, official download and checksum links, in-browser SHA-256 check, SD/USB guidance, flashing steps |
| `prep.py` (today), native helper (later) | the user's own computer | download, checksum + signature check, list removable drives, write and read-back verify |

**Flashing always happens outside the browser.**

## Why the browser cannot write the card (the WebUSB limit)

* The WebUSB spec defines a list of **protected interface classes** that a page may never
  claim. **0x08 Mass Storage** is on it, along with audio, HID, video, smart card and others:
  <https://usb.spec.whatwg.org/#protected-interface-classes> (checked 2026-11-08).
* Chrome implements this: `USBDevice.claimInterface()` on such an interface is rejected with
  *"The requested interface implements a protected class."*
  ([Chromium `usb_device.cc`](https://chromium.googlesource.com/chromium/src/+/HEAD/third_party/blink/renderer/modules/webusb/usb_device.cc)).
  Every USB stick and USB card reader is a mass-storage device, so WebUSB cannot reach it.
* Built-in SD/MMC slots are not USB at all, so WebUSB never sees them.
* No other web API writes raw bytes to a disk. The File System Access API writes files
  inside a chosen folder, never to a block device.

So a pure in-browser flasher is not possible, by design, and this is a good security property.
The page does guidance, downloading and verifying; a native tool writes.

## The safe write, as `prep.py flash` does it today

1. **Dry run by default.** Prints the image, the target (path, size, model, serial), which
   partitions will be unmounted, and the equivalent manual commands. Nothing is written.
2. **Only removable targets.** Targets come from `lsblk`: whole disks on USB or SD/MMC that
   are removable or hot-pluggable. Any disk holding `/`, `/boot`, `/boot/efi`, `/efi`, `/usr`,
   `/var`, `/home` or swap is refused, including a live USB you booted from. Internal
   SATA/NVMe disks, partitions, loop, optical and empty readers are never offered.
3. **Checksum before writing.** A device write requires `--expect-sha256` or `--sums-file`;
   the image file is hashed (streaming, 4 MiB chunks) and a mismatch stops before any write.
   Use `fetch-sums` first so the sums file itself is signature-checked against a pinned key.
4. **Typed serial confirmation.** `--write --confirm <drive serial>`, typed exactly. The device
   path is accepted only for a drive that reports no serial; `--target-file` tests confirm
   with the file path.
5. **Root only at write time.** Listing and planning run as a normal user; the write refuses
   without root ("re-run this exact command with sudo").
6. **Unmount, then exclusive open.** Mounted partitions are unmounted; the device is opened
   `O_EXCL` so the kernel refuses if anything still holds it.
7. **Write, fsync, read back.** Bytes are written in 4 MiB chunks (`.xz`/`.gz` images are
   decompressed on the fly), `fsync`ed, the page cache is dropped, then exactly the written
   length is read back and its SHA-256 compared with what was written. A mismatch reports a
   failing or fake-capacity card (see [SD-CARDS.md](SD-CARDS.md)).

Tests exercise steps 1-7 against regular files only (`--target-file`), never a block device.

## Radix Flasher (plan): Radix's own Rufus-like helper

Flow: scan the target machine → recommendations → pick a distro → download → checksum (and signature) verified → Radix offers
**"Flash to a USB stick / SD card"** → the page hands off to the Radix Flasher on the user's
own machine, because the browser cannot write raw USB (see above).

The Flasher is a thin wrapper around `prep.py flash`, so it keeps every rail above:

* **Rehearse first.** The default is a dry run ("rehearsal") showing image, drive model,
  size, serial and what gets unmounted. Nothing is written.
* **Removable drives only**; the system disk and the disk holding the running root are refused.
* **Type the drive's serial** to confirm a real write.
* **Checksum before, read-back verify after** every write.
* **Elevation per write**: root via polkit/`pkexec` for that one write, never a resident root
  daemon.
* **Linux first**; Windows (raw `\\.\PhysicalDriveN` write) and macOS (`/dev/rdiskN`) later.
* Tests never touch a real device; they write regular files only.

Delivery options, to decide later:

| Option | How the page reaches it | Pros | Cons |
|---|---|---|---|
| Localhost helper (`radix-flasher serve`) | `fetch()` to `127.0.0.1:<port>` with pairing token (model below) | one-click from the web page | needs the bridge hardening below; browsers increasingly restrict public→local requests (Private Network Access), so expect a permission prompt |
| Desktop wrapper (small GTK/Qt or Tauri app) | user opens the app; page offers a "copy plan" / deep link | no network surface at all | separate install per OS |
| CLI only (today) | page shows the exact `prep.py` commands | nothing to install beyond Python | terminal needed |

## Native helper plan (not built yet)

A small open-source helper the page can talk to, so the user gets a button instead of a
terminal. Build order: (1) catalog + verify CLI ✅, (2) drives + guarded write ✅ (CLI),
(3) hardware scan ✅ (first form, see SCAN.md), (4) compatibility rules and distro scoring ✅ (first form), (5) localhost bridge,
(6) web UI, (7) signed releases.

### Localhost bridge security model

* **Loopback only.** Binds `127.0.0.1` (and `::1`), never `0.0.0.0`; random high port.
* **Pairing token.** On start the helper prints/shows a one-time token; the page must send it
  in a header. No token, no access. Tokens expire when the helper exits.
* **Strict Origin check.** Only the exact origin(s) configured (for example
  `https://opencommons.app`) are accepted; no wildcard CORS, preflight required.
* **DNS-rebinding defence.** Reject any request whose `Host` header is not `127.0.0.1:<port>`
  or `localhost:<port>`.
* **Narrow API.** List drives, start a verified write of a catalog image to a confirmed serial,
  report progress. No arbitrary file paths or commands from the page.
* **Confirmation stays local.** The final "erase this drive" confirmation is shown by the
  helper itself, not just by the page.
* **Elevate only at write time** (polkit/pkexec on Linux), with the same refusals as the CLI.
* **Hardware report stays local** unless the user explicitly exports it.
* **Signed releases** (step 7) with published checksums, so the helper itself is verifiable.

## Manual workaround per OS (works today)

Always verify the image first (`prep.py fetch-sums` + `prep.py verify`, or the web page's
in-browser check).

**Linux**
* GNOME Disks: select the stick/card → ⋮ menu → *Restore Disk Image…* → choose the image →
  *Start Restoring*.
* Raspberry Pi Imager: *Choose OS → Use Custom* → image → *Choose Storage*.
* `dd` (double-check the device with `lsblk` first; `of=` the whole disk, not a partition):
  `sudo dd if=image.iso of=/dev/sdX bs=4M conv=fsync oflag=direct status=progress && sync`
  For `.img.xz`: `xzcat image.img.xz | sudo dd of=/dev/sdX bs=4M conv=fsync oflag=direct status=progress`
* Or `prep.py flash` as above.

**macOS**
* Raspberry Pi Imager or balenaEtcher (both verify after writing).
* `diskutil list external physical` → `diskutil unmountDisk /dev/diskN` →
  `sudo dd if=image.iso of=/dev/rdiskN bs=4m` → `diskutil eject /dev/diskN`.

**Windows**
* Rufus (choose *DD Image mode* if it asks about a hybrid ISO), Raspberry Pi Imager, or
  balenaEtcher. Check the target letter/size in Disk Management (`diskmgmt.msc`) first.
