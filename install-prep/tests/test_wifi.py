"""Wi-Fi pre-seeding. Uses temp directories as the 'boot partition' and a made-up
password only; never a real device, never a real password."""
import contextlib
import hashlib
import io
import os
import tempfile
import unittest

from helpers import prep

FAKE_PSK = "not-a-real-pass-123"


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = prep.main(argv)
    return code, out.getvalue(), err.getvalue()


class WifiSeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.boot = os.path.join(self.tmp.name, "bootfs")
        os.mkdir(self.boot)
        for name, text in (("config.txt", "arm_64bit=1\n"), ("cmdline.txt", "console=tty1\n"),
                           ("meta-data", "instance_id: rpios\n"),
                           ("user-data", "#cloud-config\nhostname: raspberrypi\n"),
                           ("network-config", "network:\n  version: 2\n")):
            with open(os.path.join(self.boot, name), "w") as f:
                f.write(text)
        self.pskfile = os.path.join(self.tmp.name, "psk")
        with open(self.pskfile, "w") as f:
            f.write(FAKE_PSK + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, name):
        with open(os.path.join(self.boot, name)) as f:
            return f.read()

    def test_detect(self):
        self.assertEqual(prep.detect_seed_target(self.boot), "rpi-cloud-init")
        os.remove(os.path.join(self.boot, "config.txt"))
        self.assertEqual(prep.detect_seed_target(self.boot), "nocloud")
        self.assertIsNone(prep.detect_seed_target(self.tmp.name))

    def test_seed_writes_config_and_notice_once(self):
        prep.seed_wifi(self.boot, "Home Net", FAKE_PSK, "US")
        nc = self.read("network-config")
        self.assertIn('"Home Net":', nc)
        self.assertIn(f'password: "{FAKE_PSK}"', nc)
        self.assertIn('regulatory-domain: "US"', nc)
        self.assertEqual(os.stat(os.path.join(self.boot, "network-config")).st_mode & 0o777, 0o600)
        ud = self.read("user-data")
        self.assertTrue(ud.startswith("#cloud-config\nhostname: raspberrypi\n"))
        self.assertIn(prep.WIFI_DISCLAIMER.replace('"', '\\"'), ud)
        prep.seed_wifi(self.boot, "Home Net", FAKE_PSK, "US")          # idempotent
        self.assertEqual(self.read("user-data").count("runcmd:"), 1)

    def test_existing_runcmd_is_extended_not_duplicated(self):
        with open(os.path.join(self.boot, "user-data"), "w") as f:
            f.write("#cloud-config\nruncmd:\n  - echo hi\n")
        prep.seed_wifi(self.boot, "N", FAKE_PSK, "GB")
        ud = self.read("user-data")
        self.assertEqual(ud.count("runcmd:"), 1)
        self.assertRegex(ud, r"runcmd:\n  - \[\"sh\".*\n  - echo hi")

    def test_quoting_is_safe(self):
        nc = prep.render_network_config('a"b: c', 'p\'"\\x12345', "US")
        self.assertIn('"a\\"b: c":', nc)
        self.assertIn('password: "p\'\\"\\\\x12345"', nc)

    def test_validation(self):
        for ssid, psk, cc in (("", FAKE_PSK, "US"), ("x" * 33, FAKE_PSK, "US"),
                              ("n", "short", "US"), ("n", FAKE_PSK, "usa"), ("n", "a\nbcdefghi", "US")):
            with self.assertRaises(prep.PrepError):
                prep.validate_wifi(ssid, psk, cc)

    def test_generic_iso_refused(self):
        with self.assertRaisesRegex(prep.PrepError, "not supported"):
            prep.seed_wifi(self.tmp.name, "N", FAKE_PSK, "US")

    def test_seed_cli_never_prints_password(self):
        code, out, err = run(["seed-wifi", "--boot-dir", self.boot, "--wifi-ssid", "Home",
                              "--wifi-psk-file", self.pskfile, "--wifi-country", "US"])
        self.assertEqual(code, 0, err)
        self.assertIn(prep.WIFI_DISCLAIMER, out)
        self.assertIn("also stored", out)
        self.assertNotIn(FAKE_PSK, out + err)
        self.assertIn(f'password: "{FAKE_PSK}"', self.read("network-config"))  # newline stripped

    def test_no_password_on_command_line(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            prep.build_parser().parse_args(["seed-wifi", "--boot-dir", self.boot,
                                            "--wifi-ssid", "x", "--wifi-psk", FAKE_PSK])

    def test_flash_file_target_with_wifi(self):
        img = os.path.join(self.tmp.name, "pi.img")
        data = os.urandom(200000)
        with open(img, "wb") as f:
            f.write(data)
        tgt = os.path.join(self.tmp.name, "card.bin")
        base = ["flash", img, "--target-file", tgt, "--wifi-ssid", "Home",
                "--wifi-psk-file", self.pskfile, "--wifi-country", "US", "--boot-dir", self.boot]
        code, out, _ = run(base)                       # rehearsal shows the warning
        self.assertEqual(code, 0)
        self.assertIn(prep.WIFI_DISCLAIMER, out)
        self.assertNotIn("Home Net", self.read("network-config"))
        self.assertNotIn(FAKE_PSK, self.read("network-config"))
        code, out, err = run(base + ["--write", "--confirm", os.path.abspath(tgt),
                                     "--expect-sha256", hashlib.sha256(data).hexdigest()])
        self.assertEqual(code, 0, err)
        self.assertIn("Added to the flashed image", out)
        self.assertNotIn(FAKE_PSK, out + err)
        self.assertIn(FAKE_PSK, self.read("network-config"))

    def test_flash_bad_psk_writes_nothing(self):
        img = os.path.join(self.tmp.name, "pi.img")
        with open(img, "wb") as f:
            f.write(b"x" * 1000)
        with open(self.pskfile, "w") as f:
            f.write("short")
        tgt = os.path.join(self.tmp.name, "card.bin")
        code, _, err = run(["flash", img, "--target-file", tgt, "--wifi-ssid", "Home",
                            "--wifi-psk-file", self.pskfile, "--wifi-country", "US",
                            "--boot-dir", self.boot, "--write", "--confirm", os.path.abspath(tgt)])
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(tgt))


class InfoTests(unittest.TestCase):
    def test_info_prints_details_and_blanks(self):
        code, out, _ = run(["info", "mint-cinnamon"])
        self.assertEqual(code, 0)
        self.assertIn("Cinnamon", out)
        self.assertIn("File manager", out)
        code, out, _ = run(["info", "rpi-os-lite-arm64"])
        self.assertIn("cloud-init", out)


if __name__ == "__main__":
    unittest.main()
