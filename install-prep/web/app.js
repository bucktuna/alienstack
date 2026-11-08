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

  $("file").onchange = updateButton;
  $("expected").oninput = updateButton;
  $("go").onclick = run;
  $("stop").onclick = () => { stopFlag = true; };
  loadCatalog();
})();
