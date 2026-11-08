import json
import os
import subprocess
import unittest

from helpers import FIXTURES, HERE, prep

with open(os.path.join(FIXTURES, "scan_cases.json")) as f:
    DATA = json.load(f)
CATALOG = {d["id"]: d for d in prep.load_catalog()["distros"]}


def check_fields(tc, scan, fields):
    for k, v in fields.items():
        if k.endswith("_count"):
            tc.assertEqual(len(scan[k[:-6]]), v, k)
        else:
            tc.assertEqual(scan[k], v, k)


class ScanParseTests(unittest.TestCase):
    def test_cases(self):
        for case in DATA["cases"]:
            with self.subTest(case["name"]):
                scan = prep.parse_scan(case["paste"])
                check_fields(self, scan, case["fields"])
                for did, verdict in case["verdicts"].items():
                    got, reason = prep.score_distro(CATALOG[did], scan)
                    self.assertEqual(got, verdict, f"{did}: {reason}")
                    self.assertTrue(reason.endswith("."))

    def test_bad_input(self):
        for text in DATA["bad"]:
            with self.subTest(text), self.assertRaises(prep.PrepError):
                prep.parse_scan(text)
        with self.assertRaises(prep.PrepError):
            prep.parse_scan("RADIX-SCAN-1:" + "A" * 30000)

    def test_round_trip(self):
        scan = prep.parse_scan(DATA["cases"][0]["paste"])
        self.assertEqual(prep.parse_scan(prep.scan_to_paste(scan)), scan)
        self.assertEqual(prep.parse_scan(json.dumps(scan)), scan)

    def test_paste_has_no_identifiers(self):
        scan = prep.parse_scan(DATA["cases"][0]["paste"])
        body = prep.scan_to_paste(scan)
        for key in ("serial", "hostname", "mac", "uuid"):
            self.assertNotIn(key, prep.base64.b64decode(body[len(prep.SCAN_PREFIX):]).decode().lower())

    def test_live_scan_and_one_liner_agree(self):
        if prep.platform.system() != "Linux":
            self.skipTest("Linux only")
        live = prep.collect_scan()
        out = subprocess.run(["sh", prep.ONE_LINER], capture_output=True, text=True, timeout=30).stdout
        self.assertTrue(out.startswith(prep.SCAN_PREFIX))
        shell = prep.parse_scan(out)
        for k in ("arch", "cpu_model", "cores", "mem_kb", "boot", "secure_boot", "fw_vendor", "board", "gpu", "wifi"):
            self.assertEqual(shell[k], live[k], k)
        self.assertEqual(len(out.strip().splitlines()), 1)

    def test_one_liner_is_one_line_and_read_only(self):
        with open(prep.ONE_LINER) as f:
            text = f.read()
        self.assertEqual(text.count("\n"), 1)
        for bad in ("sudo", "curl", "wget", "rm ", "> /", "dd "):
            self.assertNotIn(bad, text)

    def test_page_embeds_the_same_one_liner(self):
        with open(prep.ONE_LINER) as f:
            cmd = f.read().strip()
        with open(os.path.join(os.path.dirname(HERE), "web", "index.html")) as f:
            page = f.read()
        import html
        self.assertIn(html.escape(cmd, quote=False), page)


if __name__ == "__main__":
    unittest.main()
