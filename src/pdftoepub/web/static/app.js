"use strict";
const $ = (id) => document.getElementById(id);
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (_) {} },
};

// ---- i18n -----------------------------------------------------------------
const LANGS = Object.keys(STRINGS);
function pickLang() {
  const saved = store.get("pdftoepub-lang");
  if (saved && STRINGS[saved]) return saved;
  for (const l of navigator.languages?.length ? navigator.languages : [navigator.language || "en"]) {
    const short = l.toLowerCase().split("-")[0];
    if (STRINGS[short]) return short;
  }
  return "en";
}
let lang = pickLang();
const t = (key, params = {}) =>
  String(STRINGS[lang][key] ?? STRINGS.en[key] ?? key).replace(/\{(\w+)\}/g, (_, k) => params[k] ?? "");
function applyLang() {
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
  if ($("pv-frame")) $("pv-frame").title = t("previewTitle");
  items.forEach(render);
  refreshActions();
}
const langSel = $("lang");
LANGS.forEach((code) => langSel.append(new Option(STRINGS[code]._name, code)));
langSel.value = lang;
langSel.addEventListener("change", () => { lang = langSel.value; store.set("pdftoepub-lang", lang); applyLang(); });

// ---- state ----------------------------------------------------------------
let token = store.get("pdftoepub-token") || "";
let maxMb = 100;
let snapshot = null; // options captured when "Convert" is pressed
const items = [];
let uploading = false;
const headers = () => (token ? { Authorization: "Bearer " + token } : {});
const announce = (msg) => { $("live").textContent = ""; setTimeout(() => ($("live").textContent = msg), 50); };
const fmtSize = (b) => (b >= 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB");

// ---- items ----------------------------------------------------------------
function addFiles(fileList) {
  let added = 0;
  for (const file of fileList) {
    const it = { file, name: file.name, state: "ready", pct: 0, notes: [], key: crypto.randomUUID?.() ?? String(Math.random()) };
    if (file.type && file.type !== "application/pdf" && !/\.pdf$/i.test(file.name)) { it.state = "error"; it.errCode = "not_pdf"; }
    else if (!/\.pdf$/i.test(file.name) && !file.type) { it.state = "error"; it.errCode = "not_pdf"; }
    else if (file.size > maxMb * 1048576) { it.state = "error"; it.errCode = "too_big"; }
    it.li = buildItem(it);
    $("queue").append(it.li);
    items.push(it);
    render(it);
    added++;
  }
  if (added) announce(t("a_added", { n: added }));
  refreshActions();
}

function buildItem(it) {
  const li = document.createElement("li");
  li.className = "item";
  li.innerHTML = `<div class="item-head"><span class="name"></span><span class="size hint"></span></div>
    <div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100"><div class="fill"></div></div>
    <p class="status"></p><p class="stats hint"></p><ul class="notes"></ul><div class="err-slot"></div>
    <div class="row btns"></div>`;
  return li;
}

function btn(label, onClick, cls = "btn") {
  const b = document.createElement("button");
  b.type = "button"; b.className = cls; b.textContent = label;
  b.addEventListener("click", onClick);
  return b;
}

function render(it) {
  const li = it.li, q = (s) => li.querySelector(s);
  li.dataset.state = it.state;
  q(".name").textContent = it.name;
  q(".size").textContent = fmtSize(it.file.size);
  const bar = q(".bar");
  const active = ["uploading", "queued", "running"].includes(it.state);
  bar.hidden = !active;
  bar.setAttribute("aria-label", t("progressOf", { name: it.name }));
  const indet = it.state === "queued" || (it.state === "running" && !it.total);
  bar.classList.toggle("indet", indet);
  if (!indet) bar.setAttribute("aria-valuenow", Math.round(it.pct)); else bar.removeAttribute("aria-valuenow");
  q(".fill").style.width = indet ? "" : it.pct + "%";

  let status = "";
  if (it.state === "ready") status = t("st_ready");
  else if (it.state === "waiting") status = t("st_queued");
  else if (it.state === "uploading") status = t("st_uploading", { pct: Math.round(it.pct) });
  else if (it.state === "queued") status = t("st_queued");
  else if (it.state === "running") {
    status = it.stage && STRINGS.en["stage_" + it.stage] ? t("stage_" + it.stage) : t("st_start");
    if (it.total) status += " — " + t("page_of", { page: it.page, total: it.total });
  } else if (it.state === "done") status = t("st_done");
  else if (it.state === "error") status = t("st_error");
  q(".status").textContent = status;
  q(".stats").textContent = it.state === "done" && it.pages ? t("stats", { pages: it.pages, chapters: it.chapters }) : "";

  q(".notes").replaceChildren(...it.notes.map((n) => {
    const li2 = document.createElement("li");
    li2.textContent = STRINGS.en["n_" + n.code] ? t("n_" + n.code, { n: n.n, text: n.text }) : n.text;
    return li2;
  }));

  const slot = q(".err-slot");
  if (it.state === "error") {
    let p = slot.firstElementChild;
    if (!p) { p = document.createElement("p"); p.className = "err"; p.setAttribute("role", "alert"); slot.append(p); }
    p.textContent = errText(it);
  } else slot.replaceChildren();

  const row = q(".btns");
  const buttons = [];
  if (it.state === "done") {
    buttons.push(btn(t("download"), () => downloadOne(it), "btn primary"));
    buttons.push(btn(t("preview"), () => openPreview(it)));
  }
  if (it.state === "error" && it.errCode !== "not_pdf" && it.errCode !== "too_big") buttons.push(btn(t("retry"), () => retry(it)));
  buttons.push(btn(t("remove"), () => removeItem(it), "btn quiet"));
  // rebuild only if the set of labels changed, to keep keyboard focus stable during live updates
  const sig = buttons.map((b) => b.textContent).join("|") + lang;
  if (row.dataset.sig !== sig) { row.replaceChildren(...buttons); row.dataset.sig = sig; }
}

function errText(it) {
  const key = "e_" + (it.errCode || "failed");
  if (!STRINGS.en[key]) return it.errMsg || t("e_failed");
  return t(key, { max: maxMb });
}

function fail(it, code, msg) {
  it.state = "error"; it.errCode = code; it.errMsg = msg;
  render(it);
  announce(t("a_error", { name: it.name }));
  refreshActions();
}

function refreshActions() {
  const ready = items.filter((i) => i.state === "ready");
  $("queue-card").hidden = items.length === 0;
  $("go").disabled = ready.length === 0;
  $("go").textContent = ready.length > 1 ? t("convertN", { n: ready.length }) : t("convert");
  $("zip").hidden = items.filter((i) => i.state === "done").length < 2;
  const single = ready.length + items.filter((i) => i.state !== "ready" && i.state !== "error").length <= 1;
  $("o-title").disabled = !single;
  if (!single) $("o-title").value = "";
}

function removeItem(it) {
  it.abort?.abort(); it.xhr?.abort();
  if (it.id) fetch(`/api/jobs/${it.id}`, { method: "DELETE", headers: headers() }).catch(() => {});
  items.splice(items.indexOf(it), 1);
  it.li.remove();
  refreshActions();
  $("drop").focus();
}

function retry(it) { it.state = "waiting"; it.errCode = null; it.pct = 0; it.id = null; render(it); pump(); }

// ---- upload & follow ---------------------------------------------------------
function currentOptions() {
  return {
    ocr: $("o-ocr").value, ocr_langs: $("o-langs").value.trim() || "fra+eng",
    title: $("o-title").disabled ? null : $("o-title").value.trim() || null,
    author: $("o-author").value.trim() || null,
    drop_headers_footers: $("o-hf").checked, detect_columns: $("o-cols").checked,
    image_mode: $("o-img").checked ? "inline" : "none",
  };
}

$("go").addEventListener("click", () => {
  snapshot = currentOptions();
  items.filter((i) => i.state === "ready").forEach((i) => { i.state = "waiting"; render(i); });
  refreshActions();
  pump();
});

function pump() {
  if (uploading) return;
  const next = items.find((i) => i.state === "waiting");
  if (!next) return;
  uploading = true;
  upload(next).finally(() => { uploading = false; pump(); });
}

function upload(it) {
  return new Promise((resolve) => {
    it.state = "uploading"; it.pct = 0; render(it);
    const fd = new FormData();
    fd.append("file", it.file);
    fd.append("options", JSON.stringify(snapshot || currentOptions()));
    const xhr = new XMLHttpRequest();
    it.xhr = xhr;
    xhr.open("POST", "/api/jobs");
    if (token) xhr.setRequestHeader("Authorization", "Bearer " + token);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) { it.pct = (e.loaded / e.total) * 100; render(it); } };
    xhr.onerror = () => { fail(it, "network"); resolve(); };
    xhr.onabort = () => resolve();
    xhr.onload = () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText); } catch (_) {}
      if (xhr.status === 201) { it.id = body.id; it.state = "queued"; it.pct = 0; render(it); follow(it); }
      else if (xhr.status === 401) { $("auth").hidden = false; fail(it, "unauthorized"); }
      else if (xhr.status === 413) fail(it, "too_big");
      else if (xhr.status === 415) fail(it, "not_pdf");
      else if (xhr.status === 422) fail(it, "invalid", typeof body.detail === "string" ? body.detail : "");
      else fail(it, "network");
      resolve();
    };
    xhr.send(fd);
  });
}

function onState(it, s) {
  if (s.status === "done") {
    it.state = "done"; it.pct = 100; it.title = s.title; it.filename = s.filename;
    it.notes = s.notes || []; it.pages = s.page_count; it.chapters = s.chapter_count;
    render(it); announce(t("a_done", { name: it.name })); refreshActions();
    return true;
  }
  if (s.status === "error") { it.errMsg = s.error; fail(it, s.error_code || "failed", s.error); return true; }
  it.state = s.status === "queued" ? "queued" : "running";
  it.stage = s.stage; it.page = s.page; it.total = s.total_pages;
  it.pct = s.total_pages ? (s.page / s.total_pages) * 100 : 0;
  render(it);
  return false;
}

// SSE over fetch so the bearer header can be sent (EventSource cannot).
async function follow(it) {
  const ctl = (it.abort = new AbortController());
  for (let attempt = 0; attempt < 5; attempt++) {
    try {
      const r = await fetch(`/api/jobs/${it.id}/events`, { headers: headers(), signal: ctl.signal });
      if (!r.ok) throw new Error(r.status);
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const block = buf.slice(0, i); buf = buf.slice(i + 2);
          const data = block.split("\n").find((l) => l.startsWith("data: "));
          if (data && block.includes("event: progress") && onState(it, JSON.parse(data.slice(6)))) return;
        }
      }
    } catch (e) { if (ctl.signal.aborted) return; }
    await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
    const st = await fetch(`/api/jobs/${it.id}`, { headers: headers(), signal: ctl.signal }).then((r) => r.json()).catch(() => null);
    if (st && onState(it, st)) return;
  }
  fail(it, "network");
}

// ---- download / preview ------------------------------------------------------
function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
async function downloadOne(it) {
  const r = await fetch(`/api/jobs/${it.id}/download`, { headers: headers() });
  if (!r.ok) return fail(it, "network");
  saveBlob(await r.blob(), it.filename || "book.epub");
}
$("zip").addEventListener("click", async () => {
  const ids = items.filter((i) => i.state === "done").map((i) => i.id);
  const r = await fetch("/api/jobs/zip", { method: "POST", headers: { ...headers(), "Content-Type": "application/json" }, body: JSON.stringify({ ids }) });
  if (r.ok) saveBlob(await r.blob(), "epubs.zip");
});

// Not a <dialog>/top layer and not `inert` on the page: in Chromium a sandboxed (opaque-origin) iframe paints blank
// while the rest of the document is inert (which showModal() also causes). A fixed overlay + aria-hidden + our own
// Tab trap keeps the sandbox and renders everywhere.
const overlay = $("preview"), wrap = document.querySelector(".wrap");
let lastFocus = null;
function closePreview() {
  if (overlay.hidden) return;
  overlay.hidden = true; wrap.removeAttribute("aria-hidden"); $("pv-frame")?.remove();
  const back = lastFocus && document.contains(lastFocus) ? lastFocus : $("drop");
  back.focus();
}
async function openPreview(it) {
  lastFocus = document.activeElement;
  $("pv-title").textContent = it.title || it.name;
  $("pv-msg").textContent = t("previewLoading");
  $("pv-frame")?.remove();
  overlay.hidden = false; wrap.setAttribute("aria-hidden", "true");
  $("pv-close").focus();
  try {
    const r = await fetch(`/api/jobs/${it.id}/preview`, { headers: headers() });
    if (!r.ok) throw new Error(r.status);
    const html = await r.text();
    if (overlay.hidden) return;
    // A fresh, already-displayed frame each time: a sandboxed (out-of-process) iframe that is created or loaded
    // while display:none can come back blank in Chromium.
    $("pv-frame")?.remove();
    const f = document.createElement("iframe");
    Object.assign(f, { id: "pv-frame", title: t("previewTitle"), referrerPolicy: "no-referrer" });
    f.setAttribute("sandbox", "");
    $("pv-msg").after(f);
    // Chromium sometimes leaves the first out-of-process frame of a page unpainted until something invalidates it.
    f.addEventListener("load", () => requestAnimationFrame(() => {
      f.style.opacity = "0.99";
      requestAnimationFrame(() => { f.style.opacity = ""; });
    }));
    f.srcdoc = html;
    $("pv-msg").textContent = t("previewHint");
  } catch (_) { if (!overlay.hidden) $("pv-msg").textContent = t("previewNone"); }
}
$("pv-close").addEventListener("click", closePreview);
overlay.addEventListener("click", (e) => { if (e.target === overlay) closePreview(); });
document.addEventListener("keydown", (e) => {
  if (overlay.hidden) return;
  if (e.key === "Escape") { e.preventDefault(); closePreview(); }
  else if (e.key === "Tab") {
    const stops = [$("pv-close"), ...($("pv-frame") ? [$("pv-frame")] : [])];
    const i = stops.indexOf(document.activeElement);
    e.preventDefault();
    stops[(i + (e.shiftKey ? -1 : 1) + stops.length) % stops.length].focus();
  }
});

// ---- drop zone -----------------------------------------------------------------
const drop = $("drop");
drop.addEventListener("click", () => $("file").click());
$("file").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());
$("clear").addEventListener("click", () => { [...items].forEach(removeItem); });
$("token-save").addEventListener("click", () => {
  token = $("token").value.trim(); store.set("pdftoepub-token", token); $("auth").hidden = true;
});

fetch("/api/config").then((r) => r.json()).then((c) => {
  maxMb = c.max_upload_mb;
  if (c.auth_required && !token) $("auth").hidden = false;
}).catch(() => {});
applyLang();
