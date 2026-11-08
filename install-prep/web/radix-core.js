// Radix scan parsing and distro scoring. Mirrors prep.py (parse_scan, score_distro);
// tests/scan_js_test.js checks both give identical results on the same fixtures.
"use strict";
(function (root) {
  const PREFIX = "RADIX-SCAN-1:";
  const KEYS = ["arch", "cpu_model", "cores", "mem_kb", "boot", "secure_boot", "fw_vendor",
    "fw_version", "fw_date", "board", "disk_bytes"];
  const LISTS = ["gpu", "wifi"];
  const INTS = ["cores", "mem_kb", "disk_bytes"];
  const MAX_PASTE = 20000;

  function normArch(a) {
    a = String(a || "").trim().toLowerCase();
    if (["x86_64", "amd64", "x64", "x86-64"].includes(a)) return "x86_64";
    if (["aarch64", "arm64", "armv8l"].includes(a)) return "arm64";
    if (a.startsWith("armv7") || a === "armhf") return "armhf";
    if (["i386", "i486", "i586", "i686", "x86"].includes(a)) return "x86";
    return a || null;
  }

  function normalize(raw) {
    const scan = { radix_scan: 1 };
    for (const k of KEYS) {
      let v = raw[k];
      if (typeof v === "string") v = v.trim().slice(0, 200) || null;
      if (v === undefined) v = null;
      if (INTS.includes(k) && v !== null) {
        const n = /^\d+$/.test(String(v).trim()) ? parseInt(v, 10) : NaN;
        v = Number.isFinite(n) && n > 0 ? n : null;
      }
      scan[k] = v;
    }
    scan.arch = normArch(scan.arch);
    if (!["uefi", "bios"].includes(scan.boot)) scan.boot = null;
    if (!["enabled", "disabled", "not-applicable"].includes(scan.secure_boot)) scan.secure_boot = null;
    for (const k of LISTS) {
      let v = raw[k] || [];
      if (typeof v === "string") v = [v];
      scan[k] = v.map((x) => String(x).trim().slice(0, 200)).filter(Boolean).slice(0, 8);
    }
    return scan;
  }

  function b64decodeUtf8(b64) {
    const bin = (typeof atob === "function") ? atob(b64) : Buffer.from(b64, "base64").toString("binary");
    const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  }

  function parseScan(text) {
    text = String(text || "").trim();
    if (text.length > MAX_PASTE) throw new Error("pasted scan is too large");
    const i = text.indexOf(PREFIX);
    if (i >= 0) {
      let b64 = text.slice(i + PREFIX.length).replace(/\s+/g, "");
      b64 = (b64.match(/^[A-Za-z0-9+/=]*/) || [""])[0];
      b64 = b64.replace(/=+$/, "");
      b64 += "=".repeat((4 - (b64.length % 4)) % 4);
      let body;
      try { body = b64decodeUtf8(b64); } catch (e) {
        throw new Error("scan block is damaged; copy the whole RADIX-SCAN-1 line again");
      }
      const raw = { gpu: [], wifi: [] };
      for (const line of body.split(/\r?\n/)) {
        const j = line.indexOf("=");
        if (j < 0) continue;
        const k = line.slice(0, j), v = line.slice(j + 1);
        if (LISTS.includes(k)) raw[k].push(v);
        else if (KEYS.includes(k)) raw[k] = v;
      }
      return normalize(raw);
    }
    if (text.startsWith("{")) {
      let raw;
      try { raw = JSON.parse(text); } catch (e) { throw new Error("scan JSON is not valid"); }
      if (!raw || raw.radix_scan !== 1) throw new Error("not a Radix scan (missing radix_scan: 1)");
      return normalize(raw);
    }
    throw new Error("no RADIX-SCAN-1 block or scan JSON found");
  }

  const gb = (mb) => String(mb / 1024) + " GB";

  function scoreDistro(d, scan) {
    const req = d.requirements || {};
    const arches = req.arch || [];
    const arch = scan.arch;
    if (!arch) return ["unknown", "Can't tell: the scan has no CPU architecture."];
    if (!arches.includes(arch)) return ["not_a_fit", "Built for " + arches.join("/") + "; this machine is " + arch + "."];
    if (req.board) {
      const have = scan.board || "";
      if (!have.toLowerCase().includes(req.board.toLowerCase())) {
        if (have) return ["not_a_fit", "Made for " + req.board + " boards; this is " + have + "."];
        return ["works", "Only for " + req.board + " boards; the scan couldn't confirm this is one."];
      }
    }
    const memMb = scan.mem_kb ? scan.mem_kb / 1024 : null;
    const rmin = req.ram_min_mb, rrec = req.ram_rec_mb;
    if (memMb && rmin && memMb < 0.9 * rmin)
      return ["not_a_fit", "Needs " + gb(rmin) + " RAM (official minimum); this machine has " + (memMb / 1024).toFixed(1) + " GB."];
    const sbOn = scan.secure_boot === "enabled";
    const sb = req.secure_boot;
    if (sbOn && sb === false) return ["works", "Secure Boot is on and this image doesn't support it: turn Secure Boot off first."];
    const target = rrec || rmin;
    const ramOk = Boolean(memMb && target && memMb >= 0.9 * target);
    if (sbOn && (sb === null || sb === undefined))
      return ["works", "Matches your CPU; Secure Boot is on and Radix hasn't confirmed this distro's support, so you may need to turn it off."];
    if (ramOk) {
      const extra = sbOn && sb ? " and boots with Secure Boot on (signed shim)" : "";
      return ["recommended", "Matches your " + arch + " CPU, meets the official " + gb(target) + " RAM " + (rrec ? "recommendation" : "minimum") + extra + "."];
    }
    if (sbOn && sb) return ["recommended", "Matches your " + arch + " CPU and boots with Secure Boot on (signed shim)."];
    if (rmin && !memMb) return ["works", "Matches your CPU; RAM unknown (official minimum " + gb(rmin) + ")."];
    if (rrec && memMb && memMb < 0.9 * rrec) return ["works", "Matches your CPU; below the recommended " + gb(rrec) + " RAM, so expect it to be slow."];
    return ["works", "Matches your " + arch + " CPU; no official RAM or Secure Boot figure in the catalog yet."];
  }

  // Quick estimate from the browser itself. Only ever describes THIS device.
  async function browserEstimate(nav) {
    nav = nav || (typeof navigator !== "undefined" ? navigator : {});
    const est = { arch: null, cores: null, mem_min_gb: null, gpu: [], source: [] };
    try {
      if (nav.userAgentData && nav.userAgentData.getHighEntropyValues) {
        const h = await nav.userAgentData.getHighEntropyValues(["architecture", "bitness"]);
        if (h.architecture === "x86" && h.bitness === "64") est.arch = "x86_64";
        else if (h.architecture === "arm" && h.bitness === "64") est.arch = "arm64";
        else if (h.architecture === "x86" && h.bitness === "32") est.arch = "x86";
        if (est.arch) est.source.push("userAgentData");
      }
    } catch (e) { /* not available */ }
    if (!est.arch) {
      const ua = String(nav.userAgent || "");
      // Macs report "Intel" even on Apple Silicon, so a Mac UA tells us nothing.
      if (!/Macintosh|iPhone|iPad/.test(ua)) {
        if (/aarch64|arm64/i.test(ua)) est.arch = "arm64";
        else if (/x86_64|Win64|x64|amd64|WOW64/i.test(ua)) est.arch = "x86_64";
        if (est.arch) est.source.push("user agent");
      }
    }
    if (nav.hardwareConcurrency) est.cores = nav.hardwareConcurrency;
    // deviceMemory is rounded down and capped at 8; only a value of 8 is a useful lower bound.
    if (nav.deviceMemory) est.mem_min_gb = nav.deviceMemory;
    return est;
  }

  function estimateToScan(est) {
    return normalize({
      arch: est.arch, cores: est.cores,
      mem_kb: est.mem_min_gb && est.mem_min_gb >= 8 ? est.mem_min_gb * 1048576 : null,
      gpu: est.gpu || [],
    });
  }

  const api = { PREFIX, normArch, parseScan, normalize, scoreDistro, browserEstimate, estimateToScan };
  root.RadixCore = api;
  if (typeof module !== "undefined") module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
