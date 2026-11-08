# Wi-Fi pre-seeding at flash time

Radix does not build custom boot images. Wi-Fi can be pre-seeded only where the image itself
reads a headless network config on first boot.

> **If you used this tool to pre-program a Wi-Fi password, the password will remain on this
> machine, so don't give the machine away.**
>
> The password is also stored in plain text on the USB/SD card's boot partition
> (`network-config`). On a Raspberry Pi that partition stays mounted and readable at
> `/boot/firmware` after boot.

Radix shows this warning in the CLI (`flash` rehearsal and write, `seed-wifi`) and on the web
guidance page before you write.

## Supported

| Image | Mechanism | Source |
|---|---|---|
| Raspberry Pi OS, images from 2025-11-24 on (incl. the catalog's 2026-10-06 trixie Lite) | cloud-init `network-config` + `user-data` on the FAT boot partition | <https://www.raspberrypi.com/news/cloud-init-on-raspberry-pi-os/> |
| Other cloud-init NoCloud images with `meta-data` + `user-data` on a writable partition | same files | cloud-init NoCloud docs |

```bash
# at flash time (Linux, root at write time; the password is read from a file or prompted)
sudo python3 prep.py flash 2026-10-06-raspios-trixie-arm64-lite.img.xz --device /dev/sdX \
     --sums-file 2026-10-06-raspios-trixie-arm64-lite.img.xz.sha256 \
     --wifi-ssid "Home" --wifi-psk-file ~/wifi.txt --wifi-country US \
     --write --confirm <drive serial>

# or later, on a card flashed with any tool whose boot partition is mounted
python3 prep.py seed-wifi --boot-dir /run/media/$USER/bootfs --wifi-ssid "Home" \
     --wifi-psk-file ~/wifi.txt --wifi-country US
```

The password is **never** accepted on the command line (argument abbreviations are off, so
`--wifi-psk` is rejected) and never printed; output says only "password (hidden, N chars)".
Delete `~/wifi.txt` afterwards. Inputs are checked before anything is written: SSID 1-32 bytes,
password 8-63 characters or 64 hex digits, two-letter regulatory country.

## Exactly what is added to the flashed image

Only the boot partition, after the image has been written and read-back verified (so the
checksum check covers the pristine image):

1. **`network-config`** (replaced). Netplan v2 for cloud-init, `renderer: NetworkManager`:
   `eth0` DHCP (optional) and `wlan0` DHCP with `regulatory-domain`, one access point (your SSID)
   and its `password`, `optional: true`. Created with mode `0600`; note that **FAT has no
   per-file permissions**, so on the card the mount options decide who can read it (Radix
   mounts it `umask=0077` while writing; the Pi mounts `/boot/firmware` its own way).
2. **`user-data`** (existing `#cloud-config` kept, one entry added). One `runcmd` item, marked
   `# radix-wifi-notice`, that runs `sh -c` to:
   * print `*** If you used this tool to pre-program a Wi-Fi password, the password will
     remain on this machine, so don't give the machine away. ***` to `/dev/console`, and
   * write the same sentence to `/run/motd.d/90-radix-wifi-notice`.

   cloud-init runs `runcmd` **once per instance** (first boot only). `/run` is a tmpfs, so the
   login message appears on console/SSH logins during that first boot and disappears after the
   next reboot. Nothing is installed and nothing needs disabling. If `user-data` already has a
   `runcmd:` list the entry is added to it; an inline `runcmd` or a non-cloud-config file is
   refused. Seeding twice does not add a second notice.

Nothing else on the image changes. After first boot cloud-init copies the network into
`/etc/netplan/` on the root filesystem, which is why the password "remains on this machine".

## Not supported (planned / possible later)

* **Generic live ISOs** (Ubuntu, Mint, Fedora, Debian, EndeavourOS in the catalog). They are
  read-only ISO 9660 hybrid images; editing them would break the published checksum and the
  Secure Boot-signed boot chain, and the live session has no first-boot network config to read.
  Radix says so and refuses rather than faking it. Possible later: a separate writable
  partition read by an installer answer file (autoinstall / preseed / kickstart).
* Enterprise (802.1X) Wi-Fi, hidden networks, several networks.
* Windows and macOS flashing paths.
