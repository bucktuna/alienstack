#!/usr/bin/env python3
"""Linux install prep: catalog, download, verify, drive listing and a guarded flasher.

Python 3 standard library only, so it runs on a fresh live system.
Nothing here talks to a server other than the distro URLs in the catalog.
"""
import argparse
import getpass
import hashlib
import hmac
import json
import lzma
import gzip
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG = os.path.join(HERE, "catalog", "distros.json")
CHUNK = 4 * 1024 * 1024          # 4 MiB: constant memory for hashing and writing
ALGOS = ("sha256", "sha512")
# A disk holding any of these mount points is a system disk and is never offered.
SYSTEM_MOUNTS = {"/", "/boot", "/boot/efi", "/efi", "/usr", "/var", "/home", "[SWAP]"}
REMOVABLE_TRAN = {"usb", "mmc", "sd"}
UA = "install-prep/0.1 (+https://github.com/bucktuna/alienstack)"


class PrepError(Exception):
    """A refusal or failure we explain to the user and exit non-zero on."""


# ---------------------------------------------------------------- catalog
def load_catalog(path=CATALOG):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find_distro(cat, distro_id):
    for d in cat["distros"]:
        if d["id"] == distro_id:
            return d
    ids = ", ".join(d["id"] for d in cat["distros"])
    raise PrepError(f"unknown distro '{distro_id}'. Known: {ids}")


def cmd_list(args):
    cat = load_catalog(args.catalog)
    print(f"Catalog checked {cat.get('checked')}:")
    for d in cat["distros"]:
        sig = d.get("signature") or {}
        fp = "pinned key" if sig.get("key_fingerprint") else "no pinned key"
        print(f"  {d['id']:20} {d['name']}  [{d['arch']}, {d['media']}, "
              f"{d['checksum']['algorithm']}, {fp}]")
    return 0


DETAIL_LABELS = [("family", "Base / family"), ("desktop", "Default desktop"),
                 ("file_manager", "File manager"), ("packages", "Package manager / format"),
                 ("init", "Init system"), ("release_model", "Release model"),
                 ("looks_like", "Looks like (official page)")]


def cmd_info(args):
    d = find_distro(load_catalog(args.catalog), args.distro)
    det = d.get("details") or {}
    print(f"{d['name']}  ({d['arch']}, for {'SD card' if d['media'] == 'sd' else 'USB stick'})")
    for key, label in DETAIL_LABELS:
        print(f"  {label:28} {det.get(key) or '-'}")
    print(f"  {'Wi-Fi pre-seeding':28} {(d.get('wifi_preseed') or {}).get('method') or 'not supported'}")
    print(f"  {'Official page':28} {d.get('official_page')}")
    for src in det.get("sources") or []:
        print(f"  {'Source':28} {src}")
    print("  '-' = not confirmed on an official page, left blank on purpose. Display only:")
    print("  Radix does not change a distro's desktop or package manager.")
    return 0


# ---------------------------------------------------------------- download
def _require_https(url):
    if not url or not url.lower().startswith("https://"):
        raise PrepError(f"refusing non-HTTPS URL: {url!r}")


def http_download(url, dest, quiet=False, opener=urllib.request.urlopen):
    """Resumable download to dest (via dest.part). Returns dest."""
    _require_https(url)
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    if have:
        req.add_header("Range", f"bytes={have}-")
    try:
        resp = opener(req, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code == 416 and have:       # already complete
            os.replace(part, dest)
            return dest
        raise PrepError(f"download failed: HTTP {e.code} for {url}")
    with resp:
        status = getattr(resp, "status", 200)
        mode = "ab" if (have and status == 206) else "wb"
        if mode == "wb":
            have = 0
        total = resp.headers.get("Content-Length")
        total = int(total) + have if total else None
        done, last = have, 0.0
        with open(part, mode) as out:
            while True:
                buf = resp.read(CHUNK)
                if not buf:
                    break
                out.write(buf)
                done += len(buf)
                now = time.monotonic()
                if not quiet and now - last > 0.5:
                    last = now
                    pct = f"{done * 100 / total:5.1f}%" if total else ""
                    print(f"\r  {done / 1e6:10.1f} MB {pct}", end="", file=sys.stderr)
        if not quiet:
            print(file=sys.stderr)
    if total is not None and done != total:
        raise PrepError(f"short download ({done} of {total} bytes); run again to resume")
    os.replace(part, dest)
    return dest


def cmd_download(args):
    d = find_distro(load_catalog(args.catalog), args.distro)
    os.makedirs(args.dir, exist_ok=True)
    dest = os.path.join(args.dir, d["image_name"])
    print(f"Downloading {d['name']}\n  from {d['image_url']}\n  to   {dest}")
    print("  (interrupt any time; running the same command resumes)")
    http_download(d["image_url"], dest)
    print("Done. Now fetch and check the official sums:\n"
          f"  prep.py fetch-sums {d['id']} --dir {args.dir}\n"
          f"  prep.py verify {dest} --sums-file {os.path.join(args.dir, sums_name(d))}")
    return 0


# ---------------------------------------------------------------- hashing
def hash_stream(fobj, algo="sha256", limit=None):
    """Hash a file object in CHUNK pieces. Constant memory. limit = max bytes."""
    if algo not in ALGOS:
        raise PrepError(f"unsupported algorithm {algo}")
    h = hashlib.new(algo)
    left = limit
    while True:
        n = CHUNK if left is None else min(CHUNK, left)
        if n == 0:
            break
        buf = fobj.read(n)
        if not buf:
            break
        h.update(buf)
        if left is not None:
            left -= len(buf)
    return h.hexdigest()


def hash_file(path, algo="sha256"):
    with open(path, "rb") as f:
        return hash_stream(f, algo)


def strip_clearsign(text):
    """Return the body of an OpenPGP clearsigned message (or text unchanged)."""
    if "-----BEGIN PGP SIGNED MESSAGE-----" not in text:
        return text
    body = text.split("-----BEGIN PGP SIGNED MESSAGE-----", 1)[1]
    body = body.split("-----BEGIN PGP SIGNATURE-----", 1)[0]
    lines = body.splitlines()
    while lines and lines[0].strip():        # armor headers like "Hash: SHA256"
        lines.pop(0)
    return "\n".join(l[2:] if l.startswith("- ") else l for l in lines)


_GNU = re.compile(r"^\\?([0-9a-fA-F]{64}|[0-9a-fA-F]{128})\s+[ *]?(.+?)\s*$")
_BSD = re.compile(r"^(SHA256|SHA512)\s*\((.+)\)\s*=\s*([0-9a-fA-F]{64}|[0-9a-fA-F]{128})\s*$")


def parse_sums(text, filename):
    """Find filename's digest in GNU ('hex  name' / 'hex *name') or BSD
    ('SHA256 (name) = hex') sums text. Returns (algo, hex) or None."""
    base = os.path.basename(filename)
    for line in strip_clearsign(text).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _BSD.match(line)
        if m:
            name, hx = m.group(2), m.group(3)
            algo = m.group(1).lower()
        else:
            m = _GNU.match(line)
            if not m:
                continue
            hx, name = m.group(1), m.group(2)
            algo = "sha256" if len(hx) == 64 else "sha512"
        if os.path.basename(name.lstrip("*")) == base:
            return algo, hx.lower()
    return None


def verify_file(path, algo, expected):
    expected = expected.strip().lower()
    want_len = 64 if algo == "sha256" else 128
    if not re.fullmatch(r"[0-9a-f]{%d}" % want_len, expected):
        raise PrepError(f"expected {algo} must be {want_len} hex characters")
    actual = hash_file(path, algo)
    return hmac.compare_digest(actual, expected), actual


def cmd_verify(args):
    if not os.path.isfile(args.image):
        raise PrepError(f"no such file: {args.image}")
    if args.sha256:
        algo, expected = "sha256", args.sha256
    elif args.sha512:
        algo, expected = "sha512", args.sha512
    else:
        with open(args.sums_file, encoding="utf-8", errors="replace") as f:
            found = parse_sums(f.read(), args.image)
        if not found:
            raise PrepError(f"{os.path.basename(args.image)} is not listed in {args.sums_file}")
        algo, expected = found
    print(f"Hashing {args.image} ({algo}, streaming)...")
    ok, actual = verify_file(args.image, algo, expected)
    print(f"  expected {expected.lower()}\n  actual   {actual}")
    if args.sig:
        gpg_verify(args.sig, args.image, args.fingerprint, args.keyserver, args.key_url)
        print("  signature over the image: GOOD (pinned key)")
    if not ok:
        print("MISMATCH: do not use this file. Delete it and download again.")
        return 1
    print("OK: checksum matches.")
    return 0


# ---------------------------------------------------------------- gpg
def sums_name(d):
    return os.path.basename(d["checksum"]["url"])


def _norm_fp(fp):
    return re.sub(r"\s+", "", fp or "").upper()


def gpg_verify(sig, data, fingerprint, keyserver=None, key_url=None):
    """Verify sig (detached, or clearsigned when sig is None) over data with a
    throwaway keyring holding only the pinned key. Raises PrepError on failure."""
    gpg = shutil.which("gpg")
    if not gpg:
        raise PrepError("gpg is not installed; cannot check the signature")
    fp = _norm_fp(fingerprint)
    if not re.fullmatch(r"[0-9A-F]{40}", fp):
        raise PrepError("no valid pinned fingerprint; refusing to 'verify' a signature")
    with tempfile.TemporaryDirectory(prefix="prep-gpg-") as home:
        os.chmod(home, 0o700)
        base = [gpg, "--homedir", home, "--batch", "--no-tty", "--quiet"]
        if key_url:
            keyfile = os.path.join(home, "key.asc")
            http_download(key_url, keyfile, quiet=True)
            r = subprocess.run(base + ["--import", keyfile], capture_output=True, text=True)
        else:
            r = subprocess.run(base + ["--keyserver", keyserver or "hkps://keyserver.ubuntu.com",
                                       "--recv-keys", fp], capture_output=True, text=True)
        if r.returncode != 0:
            raise PrepError(f"could not fetch key {fp}: {r.stderr.strip()[:300]}")
        cmd = base + ["--status-fd", "1", "--verify"]
        cmd += [sig, data] if sig else [data]
        r = subprocess.run(cmd, capture_output=True, text=True)
        valid = [l.split() for l in r.stdout.splitlines() if l.startswith("[GNUPG:] VALIDSIG")]
        # VALIDSIG <signing-fpr> ... <primary-fpr>: accept if either is the pinned key.
        if r.returncode == 0 and any(fp in (v[2], v[-1]) for v in valid):
            return True
        raise PrepError("BAD or unverifiable signature (not made by pinned key " + fp + ")")


def cmd_fetch_sums(args):
    d = find_distro(load_catalog(args.catalog), args.distro)
    os.makedirs(args.dir, exist_ok=True)
    ck, sig = d["checksum"], d.get("signature") or {}
    sums_path = os.path.join(args.dir, sums_name(d))
    print(f"Fetching {ck['url']}")
    http_download(ck["url"], sums_path, quiet=True)
    sig_path = None
    if sig.get("url"):
        sig_path = os.path.join(args.dir, os.path.basename(sig["url"]))
        print(f"Fetching {sig['url']}")
        http_download(sig["url"], sig_path, quiet=True)
    covers = sig.get("covers")
    if ck.get("expected"):
        found = parse_sums(open(sums_path, encoding="utf-8").read(), d["image_name"])
        if not found or found[1] != ck["expected"].lower():
            raise PrepError("mirror checksum file disagrees with the official download page value")
        print("  mirror checksum matches the value on the official page")
    if covers == "image":
        if sig.get("key_fingerprint"):
            print("The signature covers the image itself; after downloading run:\n"
                  f"  prep.py verify <iso> --sums-file {sums_path} --sig {sig_path} "
                  f"--fingerprint {sig['key_fingerprint']}")
        else:
            print("WARNING: no pinned signing key for this distro; only the checksum can be checked.")
        return 0
    if not sig.get("key_fingerprint"):
        print("WARNING: no pinned signing key; the checksum file is NOT authenticated.")
        return 0
    if args.no_gpg or not shutil.which("gpg"):
        print("WARNING: gpg not available (or --no-gpg); checksum file NOT authenticated.")
        return 0
    gpg_verify(sig_path if covers == "checksum_file" else None, sums_path,
               sig["key_fingerprint"], sig.get("key_keyserver"), sig.get("key_url"))
    print(f"GOOD signature on {os.path.basename(sums_path)} from pinned key {sig['key_fingerprint']}")
    return 0


# ---------------------------------------------------------------- drives
def _truthy(v):
    return v in (True, 1, "1", "true", "True")


def _mounts(node):
    mps = node.get("mountpoints")
    if mps is None:
        mps = [node.get("mountpoint")]
    return [m for m in mps if m]


def _walk(node):
    yield node
    for c in node.get("children") or []:
        yield from _walk(c)


def classify_drives(lsblk):
    """Split lsblk -J output into (candidates, excluded). Pure, for testing.

    A candidate is a whole disk on USB or SD/MMC that is removable or
    hot-pluggable and holds none of the system mount points."""
    cands, excluded = [], []
    for dev in lsblk.get("blockdevices", []):
        name = dev.get("name", "")
        path = dev.get("path") or f"/dev/{name}"
        mounts = sorted({m for n in _walk(dev) for m in _mounts(n)})
        info = {
            "name": name, "path": path, "size": int(dev.get("size") or 0),
            "model": (dev.get("model") or "").strip(), "serial": (dev.get("serial") or "").strip(),
            "tran": dev.get("tran") or "", "mounted": mounts,
        }
        tran = (dev.get("tran") or "").lower()
        is_mmc = name.startswith("mmcblk")
        reason = None
        if dev.get("type") != "disk":
            reason = f"type {dev.get('type')}"
        elif any(m in SYSTEM_MOUNTS for m in mounts):
            reason = "SYSTEM DISK (holds " + ", ".join(m for m in mounts if m in SYSTEM_MOUNTS) + ")"
        elif tran not in REMOVABLE_TRAN and not is_mmc:
            reason = f"internal bus ({tran or 'unknown'})"
        elif not (_truthy(dev.get("rm")) or _truthy(dev.get("hotplug")) or is_mmc):
            reason = "not removable or hot-pluggable"
        elif info["size"] == 0:
            reason = "no medium (empty card reader?)"
        if reason:
            info["excluded"] = reason
            excluded.append(info)
        else:
            cands.append(info)
    return cands, excluded


def run_lsblk():
    out = subprocess.run(
        ["lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,MODEL,SERIAL,TRAN,RM,HOTPLUG,TYPE,MOUNTPOINTS"],
        capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1000.0


def os_guidance():
    sysname = platform.system()
    if sysname == "Darwin":
        return ("macOS: run `diskutil list external physical` before and after inserting the "
                "card. Flash with Raspberry Pi Imager or balenaEtcher, or see docs/FLASHING.md.")
    if sysname == "Windows":
        return ("Windows: open Disk Management (diskmgmt.msc) to see the card. Flash with "
                "Rufus, Raspberry Pi Imager or balenaEtcher; see docs/FLASHING.md.")
    return None


def cmd_drives(args):
    g = os_guidance()
    if g:
        print(g)
        return 0
    cands, excluded = classify_drives(run_lsblk())
    if not cands:
        print("No removable USB or SD drive found. Insert one and run again "
              "(see docs/SD-CARDS.md).")
    else:
        print("Removable drives you could flash:")
        for c in cands:
            warn = f"  MOUNTED: {', '.join(c['mounted'])} (will be unmounted)" if c["mounted"] else ""
            print(f"  {c['path']:14} {human(c['size']):>9}  {c['model'] or '?':24} "
                  f"serial {c['serial'] or '?'}  via {c['tran'] or 'mmc'}{warn}")
    if args.verbose:
        for e in excluded:
            print(f"  (hidden) {e['path']}: {e['excluded']}")
    return 0


# ---------------------------------------------------------------- wifi pre-seed
WIFI_DISCLAIMER = ("If you used this tool to pre-program a Wi-Fi password, the password will "
                   "remain on this machine, so don't give the machine away.")
WIFI_CARD_NOTE = ("The Wi-Fi password is also stored in plain text on the USB/SD card's boot "
                  "partition (network-config), and on a Raspberry Pi that partition stays "
                  "readable at /boot/firmware after boot.")
NOTICE_MARK = "radix-wifi-notice"


def wifi_warning():
    return "WARNING: " + WIFI_DISCLAIMER + "\n  " + WIFI_CARD_NOTE


def read_psk(path):
    """Read the passphrase from a file (or prompt). Never from argv, never printed."""
    if path:
        with open(path, encoding="utf-8") as f:
            psk = f.read()
        psk = psk[:-1] if psk.endswith("\n") else psk
        return psk[:-1] if psk.endswith("\r") else psk
    if not sys.stdin.isatty():
        raise PrepError("give --wifi-psk-file (passwords are never taken on the command line)")
    return getpass.getpass("Wi-Fi password (not shown): ")


def validate_wifi(ssid, psk, country):
    if not ssid or len(ssid.encode("utf-8")) > 32:
        raise PrepError("Wi-Fi SSID must be 1-32 bytes")
    if not (8 <= len(psk) <= 63 or re.fullmatch(r"[0-9a-fA-F]{64}", psk)):
        raise PrepError("Wi-Fi password must be 8-63 characters (or 64 hex digits)")
    if any(ord(c) < 32 for c in psk + ssid):
        raise PrepError("Wi-Fi SSID/password contain control characters")
    if not country or not re.fullmatch(r"[A-Z]{2}", country):
        raise PrepError("--wifi-country must be a two-letter country code like US (legal radio limits)")


def detect_seed_target(boot_dir):
    """Which headless-config mechanism does this mounted boot partition offer?"""
    has = lambda n: os.path.isfile(os.path.join(boot_dir, n))  # noqa: E731
    if has("config.txt") and has("cmdline.txt") and (has("user-data") or has("network-config")):
        return "rpi-cloud-init"
    if has("meta-data") and has("user-data"):
        return "nocloud"
    return None


def _q(text):
    return json.dumps(text, ensure_ascii=False)   # a JSON string is a valid YAML scalar


def render_network_config(ssid, psk, country):
    return ("# Written by Radix (install-prep). Read by cloud-init on first boot.\n"
            "# Contains a Wi-Fi password in plain text.\n"
            "network:\n"
            "  version: 2\n"
            "  renderer: NetworkManager\n"
            "  ethernets:\n"
            "    eth0:\n"
            "      dhcp4: true\n"
            "      optional: true\n"
            "  wifis:\n"
            "    wlan0:\n"
            "      dhcp4: true\n"
            f"      regulatory-domain: {_q(country)}\n"
            "      access-points:\n"
            f"        {_q(ssid)}:\n"
            f"          password: {_q(psk)}\n"
            "      optional: true\n")


def notice_command():
    """One cloud-init runcmd entry. runcmd runs once per instance (first boot only).
    It prints the notice on the console and puts it in /run/motd.d, which is tmpfs,
    so it shows at logins during that first boot and is gone after a reboot."""
    script = ('printf "\\n*** %s ***\\n\\n" "$1" > /dev/console 2>/dev/null || true; '
              'mkdir -p /run/motd.d && printf "%s\\n" "$1" > /run/motd.d/90-radix-wifi-notice')
    return _q(["sh", "-c", script, NOTICE_MARK, WIFI_DISCLAIMER])


def add_notice_to_user_data(text):
    if NOTICE_MARK in text:
        return text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "#cloud-config":
        if any(l.strip() for l in lines):
            raise PrepError("user-data is not a #cloud-config file; refusing to edit it")
        lines = ["#cloud-config"]
    entry = "- " + notice_command()
    for i, line in enumerate(lines):
        if re.match(r"^runcmd\s*:", line):
            if line.split(":", 1)[1].strip():
                raise PrepError("user-data has an inline runcmd; refusing to edit it")
            indent = ""
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    m = re.match(r"^(\s*)- ", nxt)
                    indent = m.group(1) if m else ""
                    break
            lines.insert(i + 1, indent + entry + "  # " + NOTICE_MARK)
            return "\n".join(lines) + "\n"
    lines += ["", "# Added by Radix (install-prep): one-time first-boot Wi-Fi notice.",
              "runcmd:", "  " + entry]
    return "\n".join(lines) + "\n"


def _write_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    try:
        os.chmod(path, 0o600)   # no effect on FAT; the mount options decide there
    except OSError:
        pass


def seed_wifi(boot_dir, ssid, psk, country):
    """Write Wi-Fi config + the one-time notice into a mounted boot partition.
    Returns a list of (path, description). Never prints the password."""
    kind = detect_seed_target(boot_dir)
    if not kind:
        raise PrepError("this image has no headless network config on its boot partition "
                        "(no cloud-init files). Wi-Fi pre-seeding is only supported for "
                        "Raspberry Pi OS (2025-11-24 or newer) and cloud-init/NoCloud images; "
                        "generic live ISOs are not supported (see docs/WIFI.md)")
    validate_wifi(ssid, psk, country)
    ud_path = os.path.join(boot_dir, "user-data")
    old = open(ud_path, encoding="utf-8").read() if os.path.exists(ud_path) else ""
    new_ud = add_notice_to_user_data(old)       # validate before touching anything
    nc_path = os.path.join(boot_dir, "network-config")
    _write_private(nc_path, render_network_config(ssid, psk, country))
    _write_private(ud_path, new_ud)
    return [(nc_path, f"Wi-Fi network {ssid!r}, country {country}, password (hidden, {len(psk)} chars)"),
            (ud_path, "one-time first-boot notice (cloud-init runcmd)")]


def mount_boot_partition(device):
    """Root only: re-read partitions, mount the first FAT partition privately."""
    subprocess.run(["blockdev", "--rereadpt", device], capture_output=True)
    subprocess.run(["udevadm", "settle"], capture_output=True)
    out = subprocess.run(["lsblk", "-J", "-o", "PATH,FSTYPE,TYPE", device],
                         capture_output=True, text=True, check=True).stdout
    parts = [c for d in json.loads(out)["blockdevices"] for c in d.get("children") or []]
    vfat = [p for p in parts if p.get("type") == "part" and p.get("fstype") == "vfat"]
    if not vfat:
        raise PrepError("no FAT boot partition found on the written drive")
    mnt = tempfile.mkdtemp(prefix="radix-boot-")
    r = subprocess.run(["mount", "-t", "vfat", "-o", "umask=0077", vfat[0]["path"], mnt],
                       capture_output=True, text=True)
    if r.returncode != 0:
        os.rmdir(mnt)
        raise PrepError(f"could not mount {vfat[0]['path']}: {r.stderr.strip()}")
    return mnt


def report_seed(changes):
    print("Wi-Fi pre-seeded. Added to the flashed image:")
    for path, what in changes:
        print(f"  {path}: {what}")
    print("  At first boot the machine shows: " + WIFI_DISCLAIMER)


def cmd_seed_wifi(args):
    print(wifi_warning())
    psk = read_psk(args.wifi_psk_file)
    validate_wifi(args.wifi_ssid, psk, args.wifi_country)
    report_seed(seed_wifi(args.boot_dir, args.wifi_ssid, psk, args.wifi_country))
    return 0


# ---------------------------------------------------------------- flash
def open_source(image):
    """Return a binary stream of the bytes to write (decompressing .xz/.gz)."""
    if image.endswith(".xz"):
        return lzma.open(image, "rb")
    if image.endswith(".gz"):
        return gzip.open(image, "rb")
    return open(image, "rb")


def manual_steps(image, target):
    cat = "xzcat" if image.endswith(".xz") else ("zcat" if image.endswith(".gz") else None)
    src = f"{cat} '{image}' | sudo dd of={target}" if cat else f"sudo dd if='{image}' of={target}"
    return [
        f"Linux dd:  {src} bs=4M conv=fsync oflag=direct status=progress && sync",
        "GNOME Disks: select the drive > menu (⋮) > Restore Disk Image… > pick the image > Start Restoring",
        "Raspberry Pi Imager: Choose OS > Use Custom > pick the image > Choose Storage > the card",
        "balenaEtcher (Linux/macOS/Windows): Flash from file > Select target > Flash (it verifies)",
        "macOS: diskutil unmountDisk /dev/diskN && sudo dd if=IMG of=/dev/rdiskN bs=4m",
        "Windows: Rufus (DD mode for Linux ISOs when asked) or Raspberry Pi Imager",
    ]


def resolve_target(args, lsblk_loader=None):
    """Return a dict describing the target and what the user must type."""
    if args.target_file:
        p = os.path.abspath(args.target_file)
        if os.path.exists(p) and stat.S_ISBLK(os.stat(p).st_mode):
            raise PrepError("--target-file must be a regular file, not a block device")
        return {"kind": "file", "path": p, "confirm": [p], "size": None, "mounted": []}
    if not args.device:
        raise PrepError("give --device /dev/sdX (see `prep.py drives`) or --target-file")
    if os_guidance():
        raise PrepError(os_guidance())
    cands, excluded = classify_drives((lsblk_loader or run_lsblk)())
    for c in cands:
        if c["path"] == args.device:
            return {"kind": "device", "path": c["path"], "size": c["size"],
                    # Typing the serial proves you looked at the drive, not just a name.
                    # The path is accepted only when the drive reports no serial.
                    "confirm": [c["serial"]] if c["serial"] else [c["path"]],
                    "mounted": c["mounted"], "model": c["model"], "serial": c["serial"]}
    for e in excluded:
        if e["path"] == args.device:
            raise PrepError(f"refusing {args.device}: {e['excluded']}")
    raise PrepError(f"{args.device} is not a removable USB/SD disk (partitions are not allowed; use the whole disk)")


def write_and_verify(image, target_path, is_device, progress=True):
    """Write image bytes to target with fsync, then read back and compare SHA-256."""
    h = hashlib.sha256()
    total = 0
    flags = os.O_WRONLY | getattr(os, "O_BINARY", 0)
    if is_device:
        flags |= os.O_EXCL         # Linux: fails if the device is mounted/in use
    else:
        flags |= os.O_CREAT | os.O_TRUNC
    with open_source(image) as src:
        fd = os.open(target_path, flags, 0o644)
        try:
            while True:
                buf = src.read(CHUNK)
                if not buf:
                    break
                view = memoryview(buf)
                while view:
                    n = os.write(fd, view)
                    view = view[n:]
                h.update(buf)
                total += len(buf)
                if progress:
                    print(f"\r  wrote {total / 1e6:10.1f} MB", end="", file=sys.stderr)
            os.fsync(fd)
        finally:
            os.close(fd)
    if progress:
        print(file=sys.stderr)
    written = h.hexdigest()
    if is_device:
        try:   # drop cached pages so the read-back comes from the medium
            with open(target_path, "rb") as f:
                os.posix_fadvise(f.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
        except (AttributeError, OSError):
            pass
    with open(target_path, "rb") as f:
        readback = hash_stream(f, "sha256", limit=total)
    if not hmac.compare_digest(readback, written):
        raise PrepError(f"READ-BACK MISMATCH: wrote {written}, read {readback}. "
                        "The card may be fake-capacity or failing (see docs/SD-CARDS.md, f3).")
    return total, written


def cmd_flash(args):
    if not os.path.isfile(args.image):
        raise PrepError(f"no such image: {args.image}")
    tgt = resolve_target(args)
    img_size = os.path.getsize(args.image)
    print("FLASH PLAN")
    print(f"  image   {args.image} ({human(img_size)}{', compressed' if args.image.endswith(('.xz', '.gz')) else ''})")
    if tgt["kind"] == "device":
        print(f"  target  {tgt['path']}  {human(tgt['size'])}  model {tgt['model'] or '?'}  serial {tgt['serial'] or '?'}")
        if tgt["mounted"]:
            print(f"  mounted {', '.join(tgt['mounted'])}: will be unmounted first")
        if not args.image.endswith((".xz", ".gz")) and img_size > tgt["size"]:
            raise PrepError("image is larger than the target drive")
    else:
        print(f"  target  regular file {tgt['path']} (test target)")
    print("  then    fsync, read back the written bytes and compare SHA-256")
    wifi = bool(args.wifi_ssid)
    if wifi:
        print(f"  then    pre-seed Wi-Fi {args.wifi_ssid!r} (country {args.wifi_country}) into the boot "
              "partition's network-config, plus a one-time first-boot notice in user-data")
        print("  " + wifi_warning())
        if tgt["kind"] == "file" and not args.boot_dir:
            raise PrepError("with --target-file, Wi-Fi pre-seeding needs --boot-dir "
                            "(the mounted boot partition)")
    print("  EVERYTHING ON THE TARGET WILL BE ERASED.")
    print("Equivalent manual steps:")
    for s in manual_steps(args.image, tgt["path"]):
        print("  - " + s)
    if not args.write:
        extra = " --sums-file <official sums file>" if tgt["kind"] == "device" else ""
        print("\nDry run only (nothing written). To write for real add:\n"
              f"  --write --confirm {tgt['confirm'][0]}{extra}")
        return 0
    psk = None
    if wifi:                     # collect and check before writing anything
        psk = read_psk(args.wifi_psk_file)
        validate_wifi(args.wifi_ssid, psk, args.wifi_country)
        if args.boot_dir and not detect_seed_target(args.boot_dir):
            raise PrepError(f"{args.boot_dir} has no cloud-init files; see docs/WIFI.md")
    if args.confirm not in tgt["confirm"]:
        what = "path" if tgt["kind"] == "file" or not tgt.get("serial") else "serial number"
        raise PrepError(f"confirmation did not match. Type the target's {what} exactly: "
                        + tgt["confirm"][0])
    if tgt["kind"] == "device" and not (args.expect_sha256 or args.sums_file):
        raise PrepError("a device write needs --expect-sha256 or --sums-file so the image is "
                        "checked first")
    expected = args.expect_sha256
    algo = "sha256"
    if args.sums_file:
        with open(args.sums_file, encoding="utf-8", errors="replace") as f:
            found = parse_sums(f.read(), args.image)
        if not found:
            raise PrepError(f"{os.path.basename(args.image)} is not listed in {args.sums_file}")
        algo, expected = found
    if expected:
        print(f"Checking the image file's {algo} before writing...")
        ok, actual = verify_file(args.image, algo, expected)
        if not ok:
            raise PrepError(f"image checksum MISMATCH ({actual}); nothing was written")
        print("  image checksum OK")
    if tgt["kind"] == "device":
        if os.geteuid() != 0:
            raise PrepError("writing to a device needs root: re-run this exact command with sudo")
        for part_mount in tgt["mounted"]:
            r = subprocess.run(["umount", part_mount], capture_output=True, text=True)
            if r.returncode != 0:
                raise PrepError(f"could not unmount {part_mount}: {r.stderr.strip()}")
    total, digest = write_and_verify(args.image, tgt["path"], tgt["kind"] == "device")
    print(f"Wrote and read back {total} bytes; SHA-256 {digest} matches.")
    if wifi:
        if args.boot_dir:
            report_seed(seed_wifi(args.boot_dir, args.wifi_ssid, psk, args.wifi_country))
        else:
            mnt = mount_boot_partition(tgt["path"])
            try:
                report_seed(seed_wifi(mnt, args.wifi_ssid, psk, args.wifi_country))
            finally:
                subprocess.run(["sync"])
                subprocess.run(["umount", mnt])
                os.rmdir(mnt)
        psk = None
    if tgt["kind"] == "device":
        print(f"Safe to remove after: sudo eject {tgt['path']}  (or udisksctl power-off -b {tgt['path']})")
    return 0


# ---------------------------------------------------------------- main
def add_wifi_args(s, required):
    s.add_argument("--wifi-ssid", required=required, help="Wi-Fi network name to pre-seed")
    s.add_argument("--wifi-psk-file", help="file holding the Wi-Fi password (else prompt; never argv)")
    s.add_argument("--wifi-country", default=None, help="two-letter regulatory country, e.g. US")


def build_parser():
    p = argparse.ArgumentParser(prog="prep.py", description=__doc__.splitlines()[0])
    p.add_argument("--catalog", default=CATALOG, help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show the distro catalog").set_defaults(fn=cmd_list)
    s = sub.add_parser("download", help="resumable download of a distro image")
    s.add_argument("distro"); s.add_argument("--dir", default=".")
    s.set_defaults(fn=cmd_download)
    s = sub.add_parser("verify", help="streaming checksum (and optional signature) check")
    s.add_argument("image")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--sha256"); g.add_argument("--sha512"); g.add_argument("--sums-file")
    s.add_argument("--sig", help="detached signature over the image itself")
    s.add_argument("--fingerprint", help="pinned key fingerprint for --sig")
    s.add_argument("--keyserver"); s.add_argument("--key-url")
    s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("fetch-sums", help="download official checksum file and check its signature")
    s.add_argument("distro"); s.add_argument("--dir", default=".")
    s.add_argument("--no-gpg", action="store_true")
    s.set_defaults(fn=cmd_fetch_sums)
    s = sub.add_parser("drives", help="list removable USB/SD drives (never system disks)")
    s.add_argument("-v", "--verbose", action="store_true", help="also say why other disks are hidden")
    s.set_defaults(fn=cmd_drives)
    s = sub.add_parser("flash", help="plan (default) or perform a verified write")
    s.add_argument("image")
    t = s.add_mutually_exclusive_group(required=True)
    t.add_argument("--device"); t.add_argument("--target-file")
    s.add_argument("--write", action="store_true", help="actually write (default is a dry run)")
    s.add_argument("--confirm", help="type the drive's serial exactly (path only if it has no serial; file path for --target-file)")
    s.add_argument("--expect-sha256", help="expected SHA-256 of the image file (checked before writing)")
    s.add_argument("--sums-file", help="official sums file to check the image against before writing")
    add_wifi_args(s, required=False)
    s.add_argument("--boot-dir", help="mounted boot partition to pre-seed (needed with --target-file)")
    s.set_defaults(fn=cmd_flash)
    s = sub.add_parser("seed-wifi", help="pre-seed Wi-Fi into an already-flashed, mounted boot partition")
    s.add_argument("--boot-dir", required=True, help="e.g. /run/media/$USER/bootfs")
    add_wifi_args(s, required=True)
    s.set_defaults(fn=cmd_seed_wifi)
    s = sub.add_parser("info", help="more details about a distro (display only)")
    s.add_argument("distro")
    s.set_defaults(fn=cmd_info)
    # No abbreviations: '--wifi-psk <password>' must never be accepted as '--wifi-psk-file'.
    p.allow_abbrev = False
    for child in sub.choices.values():
        child.allow_abbrev = False
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except PrepError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
