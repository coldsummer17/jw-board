/* Doc Job Workstation dashboard.
 * Reads meta.json (plain, tiny) and data.enc (encrypted) or data.json (plain, local testing).
 * Your marks (saved / applied / dismissed) and notes live in this browser's localStorage;
 * use "Back up my marks" / "Restore" to move them between devices.
 */
(() => {
  "use strict";

  const LS = {
    pw: "djw.pw.v1",
    tracking: "djw.tracking.v1",
    filters: "djw.filters.v1",
    seenUpdate: "djw.seenUpdate.v1",
  };
  const PAGE = 40;
  const TZ = "Asia/Shanghai";

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k, fallback) { try { const v = localStorage.getItem(k); return v == null ? fallback : JSON.parse(v); } catch { return fallback; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
    del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
  };

  let DATA = null;          // payload from the fetcher
  let META = null;
  let tracking = store.get(LS.tracking, {});  // {jobId: {status, note, t}}
  let F = null;             // current filter state
  let shown = PAGE;
  let onlyNew = false;
  let noteJobId = null;

  // ------------------------------------------------------------ data loading / decryption

  const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

  async function gunzip(bytes) {
    const ds = new DecompressionStream("gzip");
    const stream = new Blob([bytes]).stream().pipeThrough(ds);
    return await new Response(stream).text();
  }

  async function decrypt(blob, password) {
    const baseKey = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
    const key = await crypto.subtle.deriveKey(
      { name: "PBKDF2", salt: b64(blob.salt), iterations: blob.iter, hash: "SHA-256" },
      baseKey, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(blob.iv) }, key, b64(blob.ct));
    return JSON.parse(await gunzip(new Uint8Array(plain)));
  }

  async function fetchJSON(url) {
    const r = await fetch(`${url}?t=${Date.now()}`, { cache: "no-store" });
    if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
    return r.json();
  }

  async function boot() {
    try {
      META = await fetchJSON("meta.json");
    } catch {
      showLock("The job pool hasn't been generated yet. Run the GitHub Action once (see SETUP.md), then reload.");
      $("#unlock-btn").disabled = true;
      return;
    }
    if (!META.encrypted) {
      try { DATA = await fetchJSON("data.json"); start(); } catch (e) { showLock(`Could not load data: ${e.message}`); }
      return;
    }
    const saved = store.get(LS.pw, null);
    if (saved) {
      try { await unlock(saved); return; } catch { store.del(LS.pw); }
    }
    showLock("");
  }

  function showLock(msg) {
    $("#lock").hidden = false;
    $("#app").hidden = true;
    $("#lock-error").textContent = msg || "";
  }

  async function unlock(password) {
    const blob = await fetchJSON("data.enc");
    DATA = await decrypt(blob, password);
    start();
  }

  $("#lock-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const pw = $("#pw").value;
    const btn = $("#unlock-btn");
    btn.disabled = true; btn.textContent = "Unlocking…";
    try {
      await unlock(pw);
      if ($("#remember").checked) store.set(LS.pw, pw);
    } catch (err) {
      $("#lock-error").textContent = err && err.name === "OperationError" ? "Wrong password." : `Could not unlock: ${err.message || err}`;
    } finally {
      btn.disabled = false; btn.textContent = "Unlock";
    }
  });

  $("#lock-btn").addEventListener("click", () => { store.del(LS.pw); location.reload(); });

  // ------------------------------------------------------------ formatting

  const fmtBJ = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
  const fmtDay = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, day: "numeric", month: "short", year: "numeric" });

  function ago(iso) {
    if (!iso) return "";
    const d = (Date.now() - new Date(iso).getTime()) / 86400000;
    if (d < 1 / 24) return "just now";
    if (d < 1) return `${Math.max(1, Math.round(d * 24))}h ago`;
    if (d < 30) return `${Math.round(d)}d ago`;
    return fmtDay.format(new Date(iso));
  }
  const jobDate = (j) => j.posted_at || j.first_seen;
  const isNew = (j) => j.first_seen && DATA && j.first_seen >= DATA.updated_at;
  const fitClass = (n) => (n >= 70 ? "hi" : n >= 45 ? "mid" : "lo");
  const fitLabel = (n) => (n >= 70 ? "Strong fit" : n >= 45 ? "Good fit" : "Possible");
  const statusOf = (id) => (tracking[id] && tracking[id].status) || "";

  // ------------------------------------------------------------ filters

  function defaultFilters() {
    const fc = DATA.filters || {};
    const f = {
      sort: (fc.sort && fc.sort.default) || "fit",
      date: (fc.date_posted && fc.date_posted.default) || "any",
      status: (fc.status && fc.status.default) || "active",
      q: "",
      loc: "",
      multi: {},
    };
    (fc.multi || []).forEach((m) => { f.multi[m.key] = []; });
    return f;
  }

  function multiOptions(m) {
    if (Array.isArray(m.options)) return m.options;
    // "auto": derive from the data
    const set = new Set();
    DATA.jobs.forEach((j) => { set.add(j[m.field]); (m.field === "source" ? j.also_on || [] : []).forEach((s) => set.add(s)); });
    return [...set].filter(Boolean).sort((a, b) => a.localeCompare(b));
  }

  function matchesMulti(j, m, selected) {
    if (!selected || !selected.length) return true;
    if (m.field === "source") return selected.includes(j.source) || (j.also_on || []).some((s) => selected.includes(s));
    return selected.includes(j[m.field]);
  }

  function filtered({ skipMulti = null } = {}) {
    const fc = DATA.filters || {};
    const q = F.q.trim().toLowerCase();
    const loc = F.loc.trim().toLowerCase();
    const days = F.date === "any" ? null : Number(F.date);
    const cutoff = days ? Date.now() - days * 86400000 : null;
    return DATA.jobs.filter((j) => {
      if (onlyNew && !isNew(j)) return false;
      const st = statusOf(j.id);
      if (F.status === "active" && st === "dismissed") return false;
      if (F.status === "unmarked" && st) return false;
      if (["saved", "applied", "dismissed"].includes(F.status) && st !== F.status) return false;
      if (cutoff && new Date(jobDate(j)).getTime() < cutoff) return false;
      if (loc && !(`${j.location} ${j.region}`.toLowerCase().includes(loc))) return false;
      if (q && !(`${j.title} ${j.company} ${j.snippet} ${j.location} ${(tracking[j.id] || {}).note || ""}`.toLowerCase().includes(q))) return false;
      for (const m of fc.multi || []) {
        if (m.key === skipMulti) continue;
        if (!matchesMulti(j, m, F.multi[m.key])) return false;
      }
      return true;
    });
  }

  function sorted(list) {
    const out = list.slice();
    if (F.sort === "recent") {
      out.sort((a, b) => (jobDate(b) || "").localeCompare(jobDate(a) || "") || b.fit - a.fit);
    } else {
      out.sort((a, b) => b.fit - a.fit || (jobDate(b) || "").localeCompare(jobDate(a) || ""));
    }
    return out;
  }

  function renderFilters() {
    const fc = DATA.filters || {};
    const body = $("#filter-body");
    let html = "";

    const pills = (key, cfg) => cfg ? `
      <div class="fgroup"><div class="fgroup-title">${esc(cfg.label)}</div>
        <div class="radio-row">${cfg.options.map((o) => `<button class="pill-opt${F[key] === o.value ? " on" : ""}" data-pill="${key}" data-value="${esc(o.value)}">${esc(o.label)}</button>`).join("")}</div>
      </div>` : "";

    html += pills("status", fc.status);
    html += pills("date", fc.date_posted);

    (fc.multi || []).forEach((m) => {
      const base = filtered({ skipMulti: m.key });
      const counts = {};
      base.forEach((j) => {
        const vals = m.field === "source" ? [j.source, ...(j.also_on || [])] : [j[m.field]];
        new Set(vals).forEach((v) => { counts[v] = (counts[v] || 0) + 1; });
      });
      const sel = F.multi[m.key] || [];
      const opts = multiOptions(m);
      html += `<div class="fgroup"><div class="fgroup-title">${esc(m.label)}${sel.length ? `<button data-clear="${esc(m.key)}">Clear</button>` : ""}</div><div class="fopts">`;
      opts.forEach((o) => {
        html += `<label class="check"><input type="checkbox" data-multi="${esc(m.key)}" value="${esc(o)}"${sel.includes(o) ? " checked" : ""}><span>${esc(o)}</span><span class="opt-n">${counts[o] || 0}</span></label>`;
      });
      html += `</div></div>`;
      if (m.key === "region" && fc.location_text) {
        html += `<div class="fgroup"><div class="fgroup-title">${esc(fc.location_text.label)}</div><input type="text" id="loc-text" placeholder="${esc(fc.location_text.placeholder || "")}" value="${esc(F.loc)}"></div>`;
      }
    });
    body.innerHTML = html;

    const sortSel = $("#sort");
    if (!sortSel.options.length && fc.sort) {
      sortSel.innerHTML = fc.sort.options.map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("");
    }
    sortSel.value = F.sort;

    const nActive = Object.values(F.multi).reduce((a, v) => a + v.length, 0) + (F.date !== "any") + (F.loc ? 1 : 0);
    $("#filter-count").textContent = nActive || "";
  }

  $("#filter-body").addEventListener("click", (e) => {
    const p = e.target.closest("[data-pill]");
    if (p) { F[p.dataset.pill] = p.dataset.value; changed(); return; }
    const c = e.target.closest("[data-clear]");
    if (c) { F.multi[c.dataset.clear] = []; changed(); }
  });
  $("#filter-body").addEventListener("change", (e) => {
    const cb = e.target.closest("[data-multi]");
    if (!cb) return;
    const arr = new Set(F.multi[cb.dataset.multi] || []);
    cb.checked ? arr.add(cb.value) : arr.delete(cb.value);
    F.multi[cb.dataset.multi] = [...arr];
    changed();
  });
  let locTimer;
  $("#filter-body").addEventListener("input", (e) => {
    if (e.target.id !== "loc-text") return;
    clearTimeout(locTimer);
    locTimer = setTimeout(() => { F.loc = e.target.value; changed({ keepFocus: "loc-text" }); }, 250);
  });
  let qTimer;
  $("#search").addEventListener("input", (e) => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => { F.q = e.target.value; changed(); }, 200);
  });
  $("#sort").addEventListener("change", (e) => { F.sort = e.target.value; changed(); });
  $("#reset-filters").addEventListener("click", () => { F = defaultFilters(); onlyNew = false; $("#search").value = ""; changed(); });
  $("#open-filters").addEventListener("click", () => $("#filters").classList.add("open"));
  $("#close-filters").addEventListener("click", () => $("#filters").classList.remove("open"));

  function changed({ keepFocus } = {}) {
    shown = PAGE;
    store.set(LS.filters, F);
    renderFilters();
    if (keepFocus) { const el = document.getElementById(keepFocus); if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } }
    renderJobs();
  }

  // ------------------------------------------------------------ jobs list

  function renderChips() {
    const chips = [];
    if (onlyNew) chips.push(["Only new in this update", () => { onlyNew = false; }]);
    const fc = DATA.filters || {};
    (fc.multi || []).forEach((m) => (F.multi[m.key] || []).forEach((v) => chips.push([`${m.label}: ${v}`, () => { F.multi[m.key] = F.multi[m.key].filter((x) => x !== v); }])));
    if (F.loc) chips.push([`Location: “${F.loc}”`, () => { F.loc = ""; }]);
    const el = $("#active-chips");
    el.innerHTML = chips.map((c, i) => `<span class="chip">${esc(c[0])}<button data-chip="${i}" aria-label="Remove">✕</button></span>`).join("");
    el.onclick = (e) => { const b = e.target.closest("[data-chip]"); if (b) { chips[+b.dataset.chip][1](); changed(); } };
  }

  function jobCard(j) {
    const t = tracking[j.id] || {};
    const st = t.status || "";
    const dateTxt = j.posted_at ? `Posted ${ago(j.posted_at)}` : `First seen ${ago(j.first_seen)}`;
    const sub = [j.company, j.location].filter(Boolean).map(esc).join(" · ");
    const tags = [];
    if (isNew(j)) tags.push(`<span class="tag new">NEW</span>`);
    if (st) tags.push(`<span class="tag status-${st}">${st[0].toUpperCase() + st.slice(1)}</span>`);
    tags.push(`<span class="tag src">${esc(j.source)}</span>`);
    (j.also_on || []).forEach((s) => tags.push(`<span class="tag src" title="Also listed here">${esc(s)}</span>`));
    tags.push(`<span class="tag">${esc(dateTxt)}</span>`);
    if (j.workplace_type && j.workplace_type !== "Not specified") tags.push(`<span class="tag">${esc(j.workplace_type)}</span>`);
    if (j.employment_type && j.employment_type !== "Not specified") tags.push(`<span class="tag">${esc(j.employment_type)}</span>`);
    if (j.region && j.region !== "Other / Unknown") tags.push(`<span class="tag">${esc(j.region)}</span>`);
    if (j.salary) tags.push(`<span class="tag">${esc(j.salary)}</span>`);
    const btn = (s, label) => `<button class="btn small act${st === s ? ` on-${s}` : ""}" data-act="${s}" data-id="${esc(j.id)}" aria-pressed="${st === s}">${label}</button>`;
    return `<li class="job${st ? ` st-${st}` : ""}" data-id="${esc(j.id)}">
      <div class="job-top">
        <div class="job-main">
          <a class="job-title" href="${esc(j.url)}" target="_blank" rel="noopener noreferrer">${esc(j.title)}</a>
          <div class="job-sub">${sub || "&nbsp;"}</div>
        </div>
        <div class="fit ${fitClass(j.fit)}" title="Matched: ${esc((j.matched || []).join(", "))}"><b>${j.fit}</b><small>${fitLabel(j.fit)}</small></div>
      </div>
      <div class="tags">${tags.join("")}</div>
      ${j.snippet ? `<p class="snippet">${esc(j.snippet)}</p>` : ""}
      ${t.note ? `<p class="note-view">${esc(t.note)}</p>` : ""}
      <div class="job-actions">
        ${btn("saved", st === "saved" ? "★ Saved" : "☆ Save")}
        ${btn("applied", st === "applied" ? "✓ Applied" : "Applied")}
        ${btn("dismissed", st === "dismissed" ? "Dismissed" : "Dismiss")}
        <button class="btn small ghost" data-note="${esc(j.id)}">${t.note ? "Edit note" : "Add note"}</button>
        ${j.snippet && j.snippet.length > 180 ? `<button class="btn small ghost" data-expand>More</button>` : ""}
        <span class="spacer"></span>
        <a class="btn small primary" href="${esc(j.url)}" target="_blank" rel="noopener noreferrer">Open posting ↗</a>
      </div>
    </li>`;
  }

  function renderJobs() {
    const list = sorted(filtered());
    const total = DATA.jobs.length;
    $("#result-count").textContent = `${list.length} of ${total} jobs`;
    $("#job-list").innerHTML = list.slice(0, shown).map(jobCard).join("");
    $("#more-btn").hidden = list.length <= shown;
    $("#more-btn").textContent = `Show more (${list.length - shown} left)`;
    $("#empty").hidden = list.length > 0;
    renderChips();
  }

  $("#more-btn").addEventListener("click", () => { shown += PAGE; renderJobs(); });

  $("#job-list").addEventListener("click", (e) => {
    const act = e.target.closest("[data-act]");
    if (act) {
      const id = act.dataset.id, s = act.dataset.act;
      const t = tracking[id] || {};
      t.status = t.status === s ? "" : s;
      t.t = new Date().toISOString();
      if (!t.status && !t.note) delete tracking[id]; else tracking[id] = t;
      store.set(LS.tracking, tracking);
      renderFilters();
      renderJobs();
      return;
    }
    const n = e.target.closest("[data-note]");
    if (n) { openNote(n.dataset.note); return; }
    const x = e.target.closest("[data-expand]");
    if (x) { const li = x.closest(".job"); li.classList.toggle("open"); x.textContent = li.classList.contains("open") ? "Less" : "More"; }
  });

  function openNote(id) {
    noteJobId = id;
    const j = DATA.jobs.find((x) => x.id === id);
    $("#note-title").textContent = j ? `Note — ${j.title}` : "Note";
    $("#note-text").value = (tracking[id] || {}).note || "";
    $("#note-dialog").showModal();
  }
  $("#note-dialog").addEventListener("close", () => {
    if ($("#note-dialog").returnValue !== "save" || !noteJobId) return;
    const t = tracking[noteJobId] || {};
    t.note = $("#note-text").value.trim();
    t.t = new Date().toISOString();
    if (!t.status && !t.note) delete tracking[noteJobId]; else tracking[noteJobId] = t;
    store.set(LS.tracking, tracking);
    renderJobs();
  });

  // ------------------------------------------------------------ CSV export & backups

  function download(name, text, type) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }

  $("#export-csv").addEventListener("click", () => {
    const cols = ["Title", "Company", "Location", "Region", "Workplace type", "Employment type", "Fit", "Posted", "First seen", "Source", "Also on", "Salary", "My status", "My note", "URL"];
    const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const rows = sorted(filtered()).map((j) => {
      const t = tracking[j.id] || {};
      return [j.title, j.company, j.location, j.region, j.workplace_type, j.employment_type, j.fit, j.posted_at || "", j.first_seen, j.source, (j.also_on || []).join("; "), j.salary, t.status || "", t.note || "", j.url].map(q).join(",");
    });
    const stamp = new Date().toISOString().slice(0, 10);
    download(`doc-jobs-${stamp}.csv`, "﻿" + [cols.map(q).join(","), ...rows].join("\r\n"), "text/csv;charset=utf-8");
  });

  $("#backup-btn").addEventListener("click", () => {
    const jobsById = Object.fromEntries(DATA.jobs.map((j) => [j.id, j]));
    const out = {};
    Object.entries(tracking).forEach(([id, t]) => { out[id] = { ...t, title: (jobsById[id] || {}).title, url: (jobsById[id] || {}).url }; });
    download(`doc-jobs-marks-${new Date().toISOString().slice(0, 10)}.json`, JSON.stringify({ version: 1, tracking: out }, null, 2), "application/json");
  });

  $("#restore-input").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const obj = JSON.parse(await file.text());
      const incoming = obj.tracking || {};
      let n = 0;
      Object.entries(incoming).forEach(([id, t]) => {
        const cur = tracking[id];
        if (!cur || (t.t || "") > (cur.t || "")) { tracking[id] = { status: t.status || "", note: t.note || "", t: t.t || new Date().toISOString() }; n++; }
      });
      store.set(LS.tracking, tracking);
      alert(`Restored ${n} marks/notes.`);
      changed();
    } catch (err) {
      alert(`That file couldn't be read: ${err.message}`);
    }
    e.target.value = "";
  });

  // ------------------------------------------------------------ tabs, links, sources, banner

  $$(".tab").forEach((b) => b.addEventListener("click", () => {
    $$(".tab").forEach((x) => x.classList.toggle("active", x === b));
    ["jobs", "links", "sources"].forEach((t) => { $(`#tab-${t}`).hidden = t !== b.dataset.tab; });
  }));

  function renderLinks() {
    const groups = Object.entries(DATA.quick_links || {}).filter(([k]) => !k.startsWith("_"));
    $("#links-body").innerHTML = groups.map(([name, links]) => `
      <div class="link-group"><h3>${esc(name)}</h3><ul>
        ${links.map((l) => `<li><a href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">${esc(l.label)} ↗</a></li>`).join("")}
      </ul></div>`).join("");
  }

  function renderSources() {
    const rows = (DATA.sources_status || []).map((s) => `<tr>
      <td>${esc(s.source)}</td>
      <td><span class="state ${esc(s.state)}">${esc(s.state)}</span></td>
      <td class="num">${s.fetched ?? ""}</td><td class="num">${s.kept ?? ""}</td>
      <td class="num">${s.seconds != null ? `${s.seconds}s` : ""}</td>
      <td class="muted">${esc(s.note || "")}</td></tr>`).join("");
    $("#sources-table").innerHTML = `<thead><tr><th>Source</th><th>Status</th><th class="num">Fetched</th><th class="num">Kept</th><th class="num">Time</th><th>Notes</th></tr></thead><tbody>${rows}</tbody>`;
  }

  function renderHeader() {
    const when = DATA.updated_at ? fmtBJ.format(new Date(DATA.updated_at)) : "—";
    $("#updated-line").textContent = `Updated ${when} (Beijing) · ${DATA.total} jobs · next update at ${nextUpdate()}`;
    const seen = store.get(LS.seenUpdate, "");
    const fresh = DATA.updated_at && DATA.updated_at !== seen;
    if (fresh) {
      const n = DATA.new_count || 0;
      $("#banner-text").textContent = `Workstation updated ${when} Beijing time: ${n} new job${n === 1 ? "" : "s"} added.`;
      $("#banner-show-new").hidden = n === 0;
      $("#banner").hidden = false;
    }
  }
  function nextUpdate() {
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(new Date()).map((p) => [p.type, p.value]));
    const mins = +parts.hour * 60 + +parts.minute;
    return mins < 9 * 60 || mins >= 22 * 60 ? "09:00" : "22:00";
  }
  $("#banner-close").addEventListener("click", () => { store.set(LS.seenUpdate, DATA.updated_at); $("#banner").hidden = true; });
  $("#banner-show-new").addEventListener("click", () => {
    store.set(LS.seenUpdate, DATA.updated_at);
    $("#banner").hidden = true;
    onlyNew = true;
    changed();
  });

  // Check for a newer update every 10 minutes while the page is open.
  setInterval(async () => {
    if (!DATA) return;
    try {
      const m = await fetchJSON("meta.json");
      if (m.updated_at && m.updated_at > DATA.updated_at) $("#toast").hidden = false;
    } catch { /* offline */ }
  }, 10 * 60 * 1000);

  // ------------------------------------------------------------ start

  function start() {
    $("#lock").hidden = true;
    $("#app").hidden = false;
    const savedF = store.get(LS.filters, null);
    F = defaultFilters();
    if (savedF) {
      // keep only keys that still exist in the config
      ["sort", "date", "status", "loc"].forEach((k) => { if (savedF[k] != null) F[k] = savedF[k]; });
      Object.keys(F.multi).forEach((k) => { if (Array.isArray(savedF.multi && savedF.multi[k])) F.multi[k] = savedF.multi[k]; });
    }
    renderHeader();
    renderFilters();
    renderJobs();
    renderLinks();
    renderSources();
  }

  boot();
})();
