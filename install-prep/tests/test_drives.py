import json
import os
import unittest

from helpers import FIXTURES, prep


def load(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


class DriveFilterTests(unittest.TestCase):
    def test_laptop(self):
        cands, excluded = prep.classify_drives(load("lsblk_laptop_with_usb_and_sd.json"))
        paths = [c["path"] for c in cands]
        self.assertEqual(paths, ["/dev/sdb", "/dev/mmcblk0"])
        why = {e["path"]: e["excluded"] for e in excluded}
        self.assertIn("SYSTEM DISK", why["/dev/nvme0n1"])
        self.assertIn("internal", why["/dev/sda"])
        self.assertIn("no medium", why["/dev/sdc"])
        self.assertIn("type", why["/dev/loop0"])
        self.assertIn("type", why["/dev/sr0"])
        sdb = cands[0]
        self.assertEqual(sdb["serial"], "0401f7ab12cd")
        self.assertEqual(sdb["mounted"], ["/run/media/buck/STICK"])

    def test_usb_holding_root_is_excluded(self):
        # Booted from a live USB: that stick holds "/" and must never be offered.
        cands, excluded = prep.classify_drives(load("lsblk_booted_from_usb.json"))
        self.assertEqual([c["path"] for c in cands], ["/dev/sdb"])
        self.assertIn("SYSTEM DISK", excluded[0]["excluded"])

    def test_resolve_refuses_system_and_partitions(self):
        loader = lambda: load("lsblk_laptop_with_usb_and_sd.json")  # noqa: E731
        args = prep.build_parser().parse_args(["flash", "x.iso", "--device", "/dev/nvme0n1"])
        if prep.os_guidance():
            self.skipTest("Linux only")
        with self.assertRaisesRegex(prep.PrepError, "SYSTEM DISK"):
            prep.resolve_target(args, loader)
        args.device = "/dev/sdb1"
        with self.assertRaisesRegex(prep.PrepError, "partitions"):
            prep.resolve_target(args, loader)
        args.device = "/dev/sdb"
        t = prep.resolve_target(args, loader)
        self.assertEqual(t["confirm"], ["0401f7ab12cd"])   # serial, not path
        args.device = "/dev/mmcblk0"
        self.assertEqual(prep.resolve_target(args, loader)["confirm"], ["0x1234abcd"])


if __name__ == "__main__":
    unittest.main()
