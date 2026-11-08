# Recommendations and options (design, not built)

Radix will **recommend** distros rather than make the user guess. The flow is **scan first**:

1. **Scan the target machine** (the computer Linux will run on)
2. **Recommend**: scored options driven by that scan, side by side
3. **Pick** a distro (any catalog entry stays available)
4. **Download**
5. **Verify** checksum and signature
6. **Flash** with the Radix Flasher ([FLASHING.md](FLASHING.md)), optionally **try it in a VM** first

In the build order this is step 3 (hardware scan) and step 4 (rules and scoring). **Both now
exist in a first form:** the one-line scan, `prep.py scan` and the scoring rules are described
in [SCAN.md](SCAN.md); the web page runs the scan as its step 1.

## Hardware scan (step 3, runs first)

Read locally on the target machine, no uploads: **CPU architecture** and features (x86-64
level, ARM), **RAM**, **disk** size and type, **GPU** vendor including **NVIDIA**,
**Wi-Fi chip**, **Secure Boot** state and **firmware type** (UEFI/BIOS), and for SD use the
board (Raspberry Pi model). Linux sources: `/proc/cpuinfo`, `/proc/meminfo`, `lsblk`,
`lspci -nn`/`/sys/bus/pci`, `/sys/firmware/efi`, `mokutil --sb-state`. If the target is a
different computer from the one doing the download (or has no OS yet), the scan runs from a
live USB or the user answers a short questionnaire instead. The report **stays on the
machine** unless the user exports it.

## Compatibility rules and scoring (step 4, driven by the scan)

* **Hard rules** remove options that cannot work (arm64 board → arm64 images only; too little
  RAM for a desktop edition; 32-bit CPU).
* **Soft scores** rank what remains: NVIDIA GPU (distros with an easy proprietary-driver path),
  older hardware (lighter desktops), newcomer vs. experienced user, release model (LTS vs.
  rolling), Secure Boot support.
* **Every pick gets a one-line reason**, e.g. "Mint Cinnamon: familiar desktop, driver manager
  handles your NVIDIA card."
* **Several options side by side** (typically 3), never one forced answer; the user can always
  pick anything in the catalog.

## Planned popularity indicator

A small "interest" badge, sourced **only** from a verifiable, cited source, for example the
DistroWatch page-hit ranking, with the source link and date shown and clearly labeled as
*page interest, not install counts*. It is a tie-breaker hint, not part of the hard rules.
**No popularity numbers are included yet.**

## Distro details (display only)

`prep.py info <distro>` and the "More details" expander on the web page show, per distro:
base/family, default desktop, file manager, package manager/format, init, release model and
a "looks like" link to an official screenshot or tour page. Values come only from official
pages (listed under `details.sources` in the catalog, checked 2026-11-08); anything not
confirmed there is left blank rather than guessed.

**Out of scope:** configuring or swapping a distro's package manager or desktop environment.
Radix only shows the facts. Possible later.

# Try it in a VM (design, not built)

A downloaded and verified ISO can boot as a virtual CD for a no-risk live session:

```bash
qemu-system-x86_64 -enable-kvm -m 4G -smp 2 -cdrom <iso> -boot d
```

or GNOME Boxes, virt-manager or VirtualBox ("new VM from ISO"). The installer inside the VM
installs only to a virtual disk; the real disks are untouched.

**Limits**

* Virtual hardware: it **cannot** validate real Wi-Fi, GPU/NVIDIA drivers, suspend/resume,
  touchpad or audio quirks. Use a live USB on the real machine for that.
* Graphics are basic unless you set up GPU passthrough or virgl.
* Needs VT-x/AMD-V enabled in firmware (otherwise very slow emulation).
* Costs RAM (give the VM 2-4 GB) and disk for a virtual disk, and runs the CPU harder,
  so expect extra heat and fan noise.

**Planned:** `prep.py try <distro>` that **prints** (never runs) the matching QEMU command for
the verified ISO.
