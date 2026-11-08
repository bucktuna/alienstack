import contextlib
import hashlib
import io
import lzma
import os
import tempfile
import unittest
from unittest import mock

from helpers import prep


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = prep.main(argv)
    return code, out.getvalue(), err.getvalue()


class FlashTests(unittest.TestCase):
    """Only regular files are ever written here, never a block device."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.img = os.path.join(self.tmp.name, "disk.img")
        self.data = os.urandom(3 * 1024 * 1024 + 123)
        with open(self.img, "wb") as f:
            f.write(self.data)
        self.target = os.path.join(self.tmp.name, "target.bin")

    def tearDown(self):
        self.tmp.cleanup()

    def test_dry_run_is_default_and_writes_nothing(self):
        code, out, _ = run(["flash", self.img, "--target-file", self.target])
        self.assertEqual(code, 0)
        self.assertIn("Dry run only", out)
        self.assertIn("dd", out)
        self.assertIn("GNOME Disks", out)
        self.assertFalse(os.path.exists(self.target))

    def test_wrong_confirmation_refused(self):
        code, _, err = run(["flash", self.img, "--target-file", self.target,
                            "--write", "--confirm", "/dev/sdb"])
        self.assertEqual(code, 2)
        self.assertIn("confirmation did not match", err)
        self.assertFalse(os.path.exists(self.target))

    def test_real_write_to_file_with_readback(self):
        good = hashlib.sha256(self.data).hexdigest()
        code, out, err = run(["flash", self.img, "--target-file", self.target, "--write",
                              "--confirm", os.path.abspath(self.target), "--expect-sha256", good])
        self.assertEqual(code, 0, err)
        self.assertIn("matches", out)
        with open(self.target, "rb") as f:
            self.assertEqual(f.read(), self.data)

    def test_checksum_mismatch_writes_nothing(self):
        code, _, err = run(["flash", self.img, "--target-file", self.target, "--write",
                            "--confirm", os.path.abspath(self.target), "--expect-sha256", "0" * 64])
        self.assertEqual(code, 2)
        self.assertIn("MISMATCH", err)
        self.assertFalse(os.path.exists(self.target))

    def test_xz_image_is_decompressed(self):
        xz = os.path.join(self.tmp.name, "disk.img.xz")
        with lzma.open(xz, "wb") as f:
            f.write(self.data)
        total, digest = prep.write_and_verify(xz, self.target, False, progress=False)
        self.assertEqual(total, len(self.data))
        self.assertEqual(digest, hashlib.sha256(self.data).hexdigest())

    def test_readback_mismatch_detected(self):
        real_hash = prep.hash_stream

        def corrupt(fobj, algo="sha256", limit=None):
            return "0" * 64 if limit else real_hash(fobj, algo, limit)
        with mock.patch.object(prep, "hash_stream", corrupt):
            with self.assertRaisesRegex(prep.PrepError, "READ-BACK MISMATCH"):
                prep.write_and_verify(self.img, self.target, False, progress=False)

    def test_device_write_needs_checksum_and_root(self):
        if prep.os_guidance():
            self.skipTest("Linux only")
        fake = {"blockdevices": [{"name": "sdz", "path": "/dev/sdz", "size": 16000000000,
                                  "model": "Stick", "serial": "SER1", "tran": "usb", "rm": True,
                                  "hotplug": True, "type": "disk", "mountpoints": [None]}]}
        with mock.patch.object(prep, "run_lsblk", lambda: fake), \
                mock.patch.object(prep, "write_and_verify") as w:
            code, _, err = run(["flash", self.img, "--device", "/dev/sdz", "--write", "--confirm", "SER1"])
            self.assertEqual(code, 2)
            self.assertIn("--expect-sha256 or --sums-file", err)
            good = hashlib.sha256(self.data).hexdigest()
            with mock.patch.object(prep.os, "geteuid", lambda: 1000):
                code, _, err = run(["flash", self.img, "--device", "/dev/sdz", "--write",
                                    "--confirm", "SER1", "--expect-sha256", good])
            self.assertEqual(code, 2)
            self.assertIn("needs root", err)
            code, _, err = run(["flash", self.img, "--device", "/dev/sdz", "--write",
                                "--confirm", "/dev/sdz", "--expect-sha256", good])
            self.assertEqual(code, 2)
            self.assertIn("serial number", err)
            w.assert_not_called()

    def test_target_file_cannot_be_block_device(self):
        if not os.path.exists("/dev/loop0"):
            self.skipTest("no /dev/loop0 to stat")
        args = prep.build_parser().parse_args(["flash", self.img, "--target-file", "/dev/loop0"])
        with self.assertRaisesRegex(prep.PrepError, "regular file"):
            prep.resolve_target(args)


if __name__ == "__main__":
    unittest.main()
