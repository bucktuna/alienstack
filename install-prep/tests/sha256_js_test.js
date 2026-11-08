const { Sha256 } = require(require("path").join(__dirname, "..", "web", "sha256.js"));
const crypto = require("crypto");
const enc = (s) => new TextEncoder().encode(s);
let fails = 0;
const check = (name, got, want) => { if (got !== want) { fails++; console.log("FAIL", name, got, want); } };
check("empty", new Sha256().hex(), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
check("abc", new Sha256().update(enc("abc")).hex(), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
for (const n of [55, 56, 63, 64, 65, 119, 120, 1000, 100003]) {
  const d = crypto.randomBytes(n);
  const s = new Sha256();
  for (let i = 0; i < n; i += 37) s.update(d.subarray(i, i + 37));   // odd chunking
  check("rand" + n, s.hex(), crypto.createHash("sha256").update(d).digest("hex"));
}
console.log(fails ? fails + " failures" : "js sha256: all vectors OK");
process.exit(fails ? 1 : 0);
