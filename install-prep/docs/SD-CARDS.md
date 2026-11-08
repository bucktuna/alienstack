# SD cards and USB sticks: finding the right drive

Writing an image erases the whole target. The most important step is being sure which device
is the card.

## How cards show up on Linux

* **Built-in SD slot** (many laptops, Raspberry Pi): `/dev/mmcblk0`, partitions
  `/dev/mmcblk0p1`, `p2`… `lsblk` shows no `TRAN` (or `mmc`).
* **USB card reader or USB stick:** `/dev/sdX` (`sdb`, `sdc`…), partitions `/dev/sdb1`…,
  `TRAN` is `usb`. An empty USB card reader often appears as a disk of size 0.
* Internal SATA disks are also `/dev/sdX` (with `TRAN` `sata`), and NVMe disks are
  `/dev/nvme0n1`. Never pick by name alone.

## Before / after insertion

```bash
lsblk -o NAME,PATH,SIZE,MODEL,SERIAL,TRAN,RM,HOTPLUG,TYPE,MOUNTPOINTS   # before
# insert the card, then
lsblk -o NAME,PATH,SIZE,MODEL,SERIAL,TRAN,RM,HOTPLUG,TYPE,MOUNTPOINTS   # after: the new disk is the card
sudo dmesg -w      # or watch kernel messages while inserting (Ctrl+C to stop)
python3 prep.py drives -v   # removable candidates only, and why other disks are hidden
```

Check that the size matches the card's label (a "64 GB" card shows about 62-64 GB).

**macOS:** `diskutil list external physical` before and after; the card is `/dev/diskN`.
**Windows:** Disk Management (`diskmgmt.msc`) or Rufus / Raspberry Pi Imager's drive list.

## Sizing

* Raspberry Pi OS Lite: 8 GB minimum, 16-32 GB comfortable. Desktop distros on a USB stick
  for installing: 8 GB is enough for most ISOs (Fedora/Ubuntu are 3-6 GB).
* Prefer A1/A2, U3/V30 cards from known brands for a Pi's root filesystem.

## Fake-capacity cards

Cheap cards may report more space than they have; writes past the real size silently
vanish. Symptoms: a read-back mismatch from `prep.py flash`, corrupted files later.
Test a new card with **f3** (`f3probe --destructive --time-ops /dev/sdX` erases it;
`f3write`/`f3read` on a mounted card is non-destructive to other files) or H2testw on Windows.

## Safe ejection

After writing: `sync`, then `sudo eject /dev/sdX` or `udisksctl power-off -b /dev/sdX`.
macOS: `diskutil eject /dev/diskN`. Windows: *Safely Remove Hardware*. Only then pull the card.
