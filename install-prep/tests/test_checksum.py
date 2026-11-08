import hashlib
import io
import os
import tempfile
import unittest

from helpers import prep

ABC256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


class ChecksumTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.iso = os.path.join(self.tmp.name, "test.iso")
        # Larger than one CHUNK so the streaming loop runs more than once.
        self.data = os.urandom(1024) * (prep.CHUNK // 1024 + 7)
        with open(self.iso, "wb") as f:
            f.write(self.data)
        self.good = hashlib.sha256(self.data).hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def test_known_vector(self):
        self.assertEqual(prep.hash_stream(io.BytesIO(b"abc")), ABC256)

    def test_streaming_matches_hashlib(self):
        self.assertEqual(prep.hash_file(self.iso), self.good)
        self.assertEqual(prep.hash_file(self.iso, "sha512"), hashlib.sha512(self.data).hexdigest())

    def test_limit(self):
        self.assertEqual(prep.hash_stream(io.BytesIO(b"abcdef"), limit=3), ABC256)

    def test_verify_ok_and_mismatch(self):
        ok, _ = prep.verify_file(self.iso, "sha256", self.good.upper())
        self.assertTrue(ok)
        bad = ("0" if self.good[0] != "0" else "1") + self.good[1:]
        ok, actual = prep.verify_file(self.iso, "sha256", bad)
        self.assertFalse(ok)
        self.assertEqual(actual, self.good)

    def test_rejects_malformed_expected(self):
        with self.assertRaises(prep.PrepError):
            prep.verify_file(self.iso, "sha256", "abc123")

    def test_parse_gnu_bsd_and_clearsigned(self):
        gnu = f"{'1' * 64} *other.iso\n{self.good}  test.iso\n"
        self.assertEqual(prep.parse_sums(gnu, "/x/test.iso"), ("sha256", self.good))
        bsd = f"# test.iso: 123 bytes\nSHA256 (test.iso) = {self.good}\n"
        clear = ("-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\n" + bsd +
                 "-----BEGIN PGP SIGNATURE-----\nxyz\n-----END PGP SIGNATURE-----\n")
        self.assertEqual(prep.parse_sums(clear, "test.iso"), ("sha256", self.good))
        sha512 = f"{'a' * 128}  test.iso\n"
        self.assertEqual(prep.parse_sums(sha512, "test.iso"), ("sha512", "a" * 128))
        self.assertIsNone(prep.parse_sums(gnu, "missing.iso"))

    def test_cli_verify_exit_codes(self):
        sums = os.path.join(self.tmp.name, "SHA256SUMS")
        with open(sums, "w") as f:
            f.write(f"{self.good}  test.iso\n")
        self.assertEqual(prep.main(["verify", self.iso, "--sums-file", sums]), 0)
        self.assertEqual(prep.main(["verify", self.iso, "--sha256", "f" * 64]), 1)

    def test_https_only(self):
        with self.assertRaises(prep.PrepError):
            prep.http_download("http://example.com/x.iso", os.path.join(self.tmp.name, "x"))


class CatalogTests(unittest.TestCase):
    def test_catalog_is_sane(self):
        cat = prep.load_catalog()
        ids = [d["id"] for d in cat["distros"]]
        self.assertEqual(len(ids), len(set(ids)))
        for d in cat["distros"]:
            for url in (d["image_url"], d["checksum"]["url"], (d["signature"] or {}).get("url")):
                if url:
                    self.assertTrue(url.startswith("https://"), url)
            self.assertIn(d["checksum"]["algorithm"], prep.ALGOS)
            fp = d["signature"].get("key_fingerprint")
            if fp is not None:
                self.assertRegex(fp, r"^[0-9A-F]{40}$")
            else:
                self.assertTrue(d["signature"].get("fingerprint_note"), d["id"])


if __name__ == "__main__":
    unittest.main()
