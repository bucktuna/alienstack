// Node check: web/radix-core.js must agree with prep.py on the shared fixtures.
const path = require("path");
const fs = require("fs");
const { execFileSync } = require("child_process");
const core = require(path.join(__dirname, "..", "web", "radix-core.js"));
const data = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "scan_cases.json")));
const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "catalog", "distros.json")));
const byId = Object.fromEntries(catalog.distros.map((d) => [d.id, d]));
let fails = 0;
const fail = (...a) => { fails++; console.log("FAIL", ...a); };

const py = JSON.parse(execFileSync("python3", ["-c", `
import json,sys
sys.path.insert(0, ${JSON.stringify(path.join(__dirname, ".."))})
import prep
data=json.load(open(${JSON.stringify(path.join(__dirname, "fixtures", "scan_cases.json"))}))
cat=prep.load_catalog()["distros"]
out=[]
for c in data["cases"]:
    s=prep.parse_scan(c["paste"])
    out.append({"scan":s,"scores":{d["id"]:list(prep.score_distro(d,s)) for d in cat}})
print(json.dumps(out))
`]).toString());

data.cases.forEach((c, i) => {
  const scan = core.parseScan(c.paste);
  if (JSON.stringify(scan) !== JSON.stringify(py[i].scan)) fail(c.name, "scan differs", JSON.stringify(scan), JSON.stringify(py[i].scan));
  for (const d of catalog.distros) {
    const js = core.scoreDistro(d, scan);
    if (JSON.stringify(js) !== JSON.stringify(py[i].scores[d.id])) fail(c.name, d.id, js, py[i].scores[d.id]);
  }
  for (const [id, v] of Object.entries(c.verdicts)) {
    if (core.scoreDistro(byId[id], scan)[0] !== v) fail(c.name, id, "expected", v);
  }
});
for (const bad of data.bad) {
  let threw = false;
  try { core.parseScan(bad); } catch (e) { threw = true; }
  if (!threw) fail("accepted bad input", bad);
}
(async () => {
  const est = await core.browserEstimate({ userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)", hardwareConcurrency: 8, deviceMemory: 4 });
  if (est.arch !== null) fail("mac UA should be unknown arch");
  if (core.estimateToScan(est).mem_kb !== null) fail("deviceMemory 4 must not become a RAM figure");
  const est2 = await core.browserEstimate({ userAgent: "Mozilla/5.0 (X11; Linux x86_64)", deviceMemory: 8,
    userAgentData: { getHighEntropyValues: async () => ({ architecture: "arm", bitness: "64" }) } });
  if (est2.arch !== "arm64") fail("high-entropy arch should win");
  console.log(fails ? fails + " failures" : "js scan parser + scoring: all cases agree with prep.py");
  process.exit(fails ? 1 : 0);
})();
