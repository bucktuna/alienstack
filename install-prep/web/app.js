"use strict";
(function () {
  const $ = (id) => document.getElementById(id);
  const SLICE = 4 * 1024 * 1024;
  let catalog = null, stopFlag = false;

  function el(tag, text, attrs) {
    const e = document.createElement(tag);
    if (text != null) e.textContent = text;
    for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
    return e;
  }
  function link(url) {
    if (!url) return el("span", "none published", { class: "note" });
    return el("a", url, { href: url, rel: "noopener noreferrer" });
  }

  function showDistro(d) {
    const box = $("details");
    box.replaceChildren();
    const dl = el("dl");
    const sig = d.signature || {};
    const rows = [
      ["Image", link(d.image_url)],
      ["Official page", link(d.official_page)],
      ["Checksum (" + d.checksum.algorithm + ")", link(d.checksum.url)],
      ["Signature", link(sig.url)],
      ["Signing key", el("code", sig.key_fingerprint || "not pinned")],
      ["Media", el("span", d.media === "sd" ? "SD card (" + d.arch + ")" : "USB stick (" + d.arch + ")")],
    ];
    if (sig.covers === "checksum_file_clearsigned") rows[3][1] = el("span", "the checksum file is itself signed");
    for (const [k, v] of rows) { dl.append(el("dt", k)); const dd = el("dd"); dd.append(v); dl.append(dd); }
    box.append(dl);
    if (!sig.key_fingerprint) box.append(el("p", sig.fingerprint_note || "No pinned key.", { class: "note warn" }));
    const det = d.details || {};
    const more = el("details", null, { class: "more" });
    more.append(el("summary", "More details"));
    const mdl = el("dl");
    const labels = [["family", "Base / family"], ["desktop", "Default desktop"], ["file_manager", "File manager"],
      ["packages", "Package manager / format"], ["init", "Init system"], ["release_model", "Release model"]];
    for (const [k, label] of labels) {
      mdl.append(el("dt", label));
      mdl.append(el("dd", det[k] || "—"));
    }
    mdl.append(el("dt", "Looks like"));
    const ll = el("dd"); ll.append(det.looks_like ? link(det.looks_like) : el("span", "—")); mdl.append(ll);
    mdl.append(el("dt", "Wi-Fi pre-seeding"));
    mdl.append(el("dd", d.wifi_preseed ? d.wifi_preseed.method + " (see the flashing step)" : "not supported for this image"));
    more.append(mdl);
    const srcs = el("p", "Facts from official pages, checked " + (det.checked || "?") + ". “—” means not confirmed there, left blank on purpose. Display only: Radix doesn't change a distro's desktop or package manager. Sources: ", { class: "note" });
    (det.sources || []).forEach((u, i) => { if (i) srcs.append(" · "); srcs.append(link(u)); });
    more.append(srcs);
    box.append(more);
    box.append(el("p", "CLI: python3 prep.py info " + d.id + " · python3 prep.py download " + d.id + " && python3 prep.py fetch-sums " + d.id, { class: "note" }));
    $("flashcmd").textContent = "python3 prep.py flash " + d.image_name + " --device /dev/sdX\n" +
      "# rehearsal only. To write, add:  --write --confirm <drive serial> --sums-file " +
      d.checksum.url.split("/").pop() + "  (with sudo)";
    $("expected").placeholder = d.checksum.algorithm === "sha256"
      ? "64 hex characters, from " + d.checksum.url.split("/").pop()
      : "this distro publishes " + d.checksum.algorithm + " only; use prep.py";
  }

  async function loadCatalog() {
    const sel = $("distro");
    try {
      // Hosted copy serves distros.json next to the page; in the repo it is ../catalog/.
      let r = await fetch("distros.json", { cache: "no-store" });
      if (!r.ok) r = await fetch("../catalog/distros.json", { cache: "no-store" });
      catalog = await r.json();
    } catch (e) {
      sel.replaceChildren(el("option", "Could not load catalog (open via a local web server, see README)"));
      return;
    }
    sel.replaceChildren(...catalog.distros.map((d) => el("option", d.name, { value: d.id })));
    sel.onchange = () => showDistro(catalog.distros.find((d) => d.id === sel.value));
    showDistro(catalog.distros[0]);
  }

  function updateButton() {
    $("go").disabled = !($("file").files.length && /^[0-9a-fA-F]{64}$/.test($("expected").value.trim()));
  }

  async function hashFile(file) {
    const h = new window.Sha256();
    const prog = $("prog");
    prog.hidden = false; prog.max = file.size || 1; prog.value = 0;
    for (let off = 0; off < file.size; off += SLICE) {
      if (stopFlag) throw new Error("stopped");
      const buf = await file.slice(off, off + SLICE).arrayBuffer();
      h.update(new Uint8Array(buf));
      prog.value = Math.min(off + SLICE, file.size);
      await new Promise((r) => setTimeout(r, 0)); // keep the page responsive
    }
    return h.hex();
  }

  async function run() {
    const file = $("file").files[0];
    const want = $("expected").value.trim().toLowerCase();
    const out = $("result");
    out.className = "result"; out.textContent = "Hashing " + file.name + "…";
    stopFlag = false; $("go").disabled = true; $("stop").hidden = false;
    const t0 = performance.now();
    try {
      const got = await hashFile(file);
      const secs = ((performance.now() - t0) / 1000).toFixed(1);
      const ok = got === want;
      out.className = "result " + (ok ? "ok" : "bad");
      out.textContent = (ok ? "MATCH: this is the published image." : "MISMATCH: do not use this file. Download it again.") +
        "\nexpected " + want + "\nactual   " + got + "\n(" + secs + " s)";
    } catch (e) {
      out.textContent = "Stopped.";
    } finally {
      $("stop").hidden = true; updateButton();
    }
  }


  // ---------------------------------------------------------------- step 1: scan
  const LABEL = { recommended: "Recommended", works: "Works", not_a_fit: "Not a fit", unknown: "Can't tell" };
  let lastScores = {};

  function fmtScan(scan) {
    const u = (x) => (x === null || x === undefined || x === "" || (Array.isArray(x) && !x.length)) ? "unknown" : x;
    const fw = [scan.fw_vendor, scan.fw_version, scan.fw_date].filter(Boolean).join(" ") || "unknown";
    return [
      ["CPU", u(scan.cpu_model) + " (" + u(scan.arch) + ", " + u(scan.cores) + " threads)"],
      ["Memory", scan.mem_kb ? (scan.mem_kb / 1048576).toFixed(1) + " GB" : "unknown"],
      ["Boot", scan.boot ? (scan.boot === "uefi" ? "UEFI" : "legacy BIOS") : "unknown"],
      ["Secure Boot", u(scan.secure_boot)],
      ["Firmware", fw],
      ["Board", u(scan.board)],
      ["Disk", scan.disk_bytes ? Math.round(scan.disk_bytes / 1e9) + " GB (largest disk)" : "unknown"],
      ["GPU", (scan.gpu || []).join("; ") || "unknown"],
      ["Wi-Fi", (scan.wifi || []).join("; ") || "unknown"],
    ];
  }

  function fillDl(dl, rows) {
    dl.replaceChildren();
    for (const [k, v] of rows) { dl.append(el("dt", k)); dl.append(el("dd", String(v))); }
  }

  function applyScan(scan) {
    fillDl($("scanSummary"), fmtScan(scan));
    const list = $("fitList");
    list.replaceChildren();
    lastScores = {};
    const order = { recommended: 0, works: 1, unknown: 2, not_a_fit: 3 };
    const rows = catalog.distros.map((d) => [d, window.RadixCore.scoreDistro(d, scan)])
      .sort((a, b) => order[a[1][0]] - order[b[1][0]]);
    for (const [d, [verdict, reason]] of rows) {
      lastScores[d.id] = verdict;
      const li = el("li");
      li.append(el("span", LABEL[verdict], { class: "badge " + verdict }));
      const txt = el("span");
      const a = el("a", d.name, { href: "#pick" });
      a.onclick = () => { $("distro").value = d.id; $("distro").onchange(); };
      txt.append(a, el("br"), el("span", reason, { class: "why" }));
      li.append(txt);
      list.append(li);
    }
    for (const opt of $("distro").options) {
      const d = catalog.distros.find((x) => x.id === opt.value);
      if (d) opt.textContent = d.name + (lastScores[d.id] ? "  ·  " + LABEL[lastScores[d.id]] : "");
    }
    $("scanResult").hidden = false;
  }

  function onPaste() {
    const text = $("pasteScan").value;
    $("scanError").textContent = "";
    if (!text.trim()) { $("scanResult").hidden = true; return; }
    if (!catalog) { $("scanError").textContent = "Catalog not loaded yet."; return; }
    try { applyScan(window.RadixCore.parseScan(text)); }
    catch (e) { $("scanResult").hidden = true; $("scanError").textContent = e.message; }
  }

  async function copyCmd() {
    const text = $("oneliner").textContent;
    try { await navigator.clipboard.writeText(text); $("copied").textContent = "Copied."; }
    catch (e) {
      const r = document.createRange(); r.selectNodeContents($("oneliner"));
      const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
      $("copied").textContent = "Selected: press Ctrl+C.";
    }
  }

  async function estimate() {
    const est = await window.RadixCore.browserEstimate();
    let gpu = "unknown";
    try {
      const gl = document.createElement("canvas").getContext("webgl");
      const ext = gl && gl.getExtension("WEBGL_debug_renderer_info");
      if (ext) gpu = gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || "unknown";
    } catch (e) { /* no WebGL */ }
    fillDl($("estimateOut"), [
      ["CPU type", est.arch ? est.arch + " (from " + est.source.join(", ") + ")" : "unknown"],
      ["Threads", est.cores || "unknown"],
      ["Memory", est.mem_min_gb ? "about " + est.mem_min_gb + " GB" + (est.mem_min_gb >= 8 ? " or more" : " (rounded down)") : "unknown"],
      ["GPU", gpu + (/nvidia/i.test(gpu) ? " (NVIDIA)" : "")],
      ["Secure Boot / firmware / boot mode", "unknown (browsers can't see these)"],
    ]);
    if (catalog && !$("pasteScan").value.trim()) {
      applyScan(window.RadixCore.estimateToScan(est));
      $("scanError").textContent = "Showing fit from the browser estimate (this device only). Paste a real scan for a full answer.";
    }
  }

  $("copyCmd").onclick = copyCmd;
  $("pasteScan").addEventListener("input", onPaste);
  $("estimate").onclick = estimate;
  $("file").onchange = updateButton;
  $("expected").oninput = updateButton;
  $("go").onclick = run;
  $("stop").onclick = () => { stopFlag = true; };
  loadCatalog();
})();
