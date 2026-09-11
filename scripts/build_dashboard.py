#!/usr/bin/env python3
"""
build_dashboard.py — turn the curated database into an interactive HTML
dashboard Kasi can actually work from: filter, sort, read the match reasoning,
track what he has applied to, and click straight through to the apply page.

    python scripts/build_dashboard.py            # → dashboard/index.html

The dashboard reads a JSON blob embedded at build time, so it is a single
self-contained file that works offline and can be emailed or opened from
OneDrive on a phone. Application progress is stored in the browser
(localStorage), so ticking "applied" survives a refresh without a server.
"""
from __future__ import annotations

import datetime as _dt
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

# Written to BOTH places: dashboard/ for local use, docs/ because that is the
# folder GitHub Pages serves from (Settings → Pages → main /docs).
OUT_DIRS = [os.path.join(common.ROOT, "dashboard"), os.path.join(common.ROOT, "docs")]


def load() -> tuple[list[dict], dict]:
    conn = common.get_db()
    jobs = []
    for row in conn.execute("SELECT * FROM jobs ORDER BY match_score DESC, date_posted DESC"):
        j = dict(row)
        j["reasons"] = [r[0] for r in conn.execute(
            "SELECT reason FROM job_reasons WHERE job_id=? ORDER BY idx", (j["job_id"],))]
        j["requirements"] = [r[0] for r in conn.execute(
            "SELECT requirement FROM job_requirements WHERE job_id=? ORDER BY idx",
            (j["job_id"],))][:12]
        j["description"] = (j.get("description") or "")[:1600]
        j["apply_form"] = common.application_form_for(j["company"])
        jobs.append(j)
    run = conn.execute("SELECT * FROM runs ORDER BY run_date DESC LIMIT 1").fetchone()
    rejected = conn.execute(
        "SELECT failed_gate, COUNT(*) c FROM rejected WHERE run_date=(SELECT MAX(run_date) FROM rejected)"
        " GROUP BY failed_gate ORDER BY c DESC").fetchall()
    meta = dict(run) if run else {}
    meta["rejected"] = [{"gate": r[0], "count": r[1]} for r in rejected]
    meta["have_ready"] = common.always_have_ready()
    conn.close()
    return jobs, meta


TEMPLATE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kasi — Cruise Ship Housekeeping Jobs</title>
<style>
  :root{
    --bg:#f6f7f9; --panel:#fff; --ink:#12181f; --muted:#5d6b7a; --line:#e2e6eb;
    --accent:#0b6b64; --accent-soft:#e6f2f1; --strong:#0b6b64; --stretch:#8a6d1f;
    --stretch-soft:#fdf3d8; --chip:#eef1f4; --shadow:0 1px 2px rgba(16,24,40,.06),0 1px 3px rgba(16,24,40,.1);
  }
  @media (prefers-color-scheme:dark){:root{
    --bg:#0e1216; --panel:#161c22; --ink:#e8edf2; --muted:#9aa8b6; --line:#252d36;
    --accent:#4fd1c5; --accent-soft:#11302e; --strong:#4fd1c5; --stretch:#e3b341;
    --stretch-soft:#2e2611; --chip:#1e252c; --shadow:none;}}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
  .wrap{max-width:1120px;margin:0 auto;padding:24px 18px 72px}
  header h1{font-size:26px;margin:0 0 4px;letter-spacing:-.02em}
  header p{margin:0;color:var(--muted);font-size:14px}
  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:20px 0}
  .stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;box-shadow:var(--shadow)}
  .stat b{display:block;font-size:22px;letter-spacing:-.02em}
  .stat span{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
  .funnel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:18px;box-shadow:var(--shadow)}
  .funnel h2{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:0 0 10px}
  .frow{display:flex;align-items:center;gap:10px;margin:5px 0;font-size:13px}
  .frow .bar{height:8px;border-radius:99px;background:var(--accent);opacity:.85;min-width:3px}
  .frow .lab{width:210px;color:var(--muted);flex:none}
  .frow .num{font-variant-numeric:tabular-nums;font-weight:600;width:44px;text-align:right;flex:none}
  .controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:14px}
  input[type=search],select{background:var(--panel);color:var(--ink);border:1px solid var(--line);
      border-radius:8px;padding:8px 10px;font-size:14px;font-family:inherit}
  input[type=search]{flex:1;min-width:200px}
  .toggle{display:inline-flex;align-items:center;gap:6px;background:var(--panel);border:1px solid var(--line);
      border-radius:8px;padding:8px 10px;font-size:13px;color:var(--muted);cursor:pointer;user-select:none}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;
        margin-bottom:12px;box-shadow:var(--shadow)}
  .card.done{opacity:.55}
  .top{display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap}
  .top h3{margin:0;font-size:17px;letter-spacing:-.01em;flex:1;min-width:240px}
  .score{font-variant-numeric:tabular-nums;font-weight:700;font-size:19px;color:var(--strong)}
  .meta{color:var(--muted);font-size:13px;margin:6px 0 10px}
  .chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
  .chip{background:var(--chip);border-radius:99px;padding:3px 10px;font-size:12px;color:var(--muted);white-space:nowrap}
  .chip.v-strong_match{background:var(--accent-soft);color:var(--strong);font-weight:600}
  .chip.v-stretch{background:var(--stretch-soft);color:var(--stretch);font-weight:600}
  .chip.warn{background:var(--stretch-soft);color:var(--stretch)}
  .actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:12px}
  a.apply{background:var(--accent);color:#fff;text-decoration:none;border-radius:8px;
          padding:9px 16px;font-weight:600;font-size:14px;display:inline-block}
  @media (prefers-color-scheme:dark){a.apply{color:#08201e}}
  a.apply:hover{filter:brightness(1.08)}
  .ghost{background:transparent;border:1px solid var(--line);color:var(--muted);border-radius:8px;
         padding:9px 12px;font-size:13px;cursor:pointer;font-family:inherit}
  details{margin-top:10px;border-top:1px solid var(--line);padding-top:10px}
  summary{cursor:pointer;font-size:13px;color:var(--muted);font-weight:600}
  details ul{margin:8px 0 0;padding-left:18px;font-size:13.5px}
  details li{margin:3px 0}
  .why li{color:var(--ink)}
  pre.jd{white-space:pre-wrap;font:12.5px/1.5 inherit;color:var(--muted);
         max-height:280px;overflow:auto;margin:8px 0 0;background:var(--bg);
         border:1px solid var(--line);border-radius:8px;padding:10px}
  .ghost.no{border-color:#d9b3b3}
  @media (prefers-color-scheme:dark){.ghost.no{border-color:#4a2b2b}}
  .card.rejected{opacity:.4}
  .exportbar{background:var(--panel);border:1px solid var(--line);border-radius:12px;
             padding:14px 16px;margin-bottom:14px;box-shadow:var(--shadow)}
  .exportbar h2{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:0 0 8px}
  .exportbar p{margin:0 0 10px;font-size:13px;color:var(--muted)}
  .exportbar textarea{width:100%;min-height:120px;background:var(--bg);color:var(--ink);
      border:1px solid var(--line);border-radius:8px;padding:10px;font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;resize:vertical}
  .empty{background:var(--panel);border:1px dashed var(--line);border-radius:12px;padding:36px;text-align:center;color:var(--muted)}
  footer{color:var(--muted);font-size:12.5px;margin-top:28px;line-height:1.7;border-top:1px solid var(--line);padding-top:16px}
  code{background:var(--chip);padding:1px 5px;border-radius:4px;font-size:12px}
</style></head><body><div class="wrap">

<header>
  <h1>Cruise ship housekeeping — jobs for Kasi</h1>
  <p>__SUBTITLE__</p>
</header>

<div class="stats" id="stats"></div>
<div class="funnel"><h2>How __SCRAPED__ postings became __KEPT__</h2><div id="funnel"></div></div>

<div class="funnel" id="readybox"><h2>Have these ready before you start any application</h2>
  <ul id="readylist" style="margin:0;padding-left:18px;font-size:13.5px;color:var(--ink)"></ul></div>

<div class="controls">
  <input type="search" id="q" placeholder="Search title, company, ship, requirement…">
  <select id="verdict"><option value="">All verdicts</option>
    <option value="strong_match">Strong match only</option><option value="stretch">Stretch only</option></select>
  <select id="bucket"><option value="">All role types</option></select>
  <select id="company"><option value="">All employers</option></select>
  <select id="english"><option value="">English: any</option>
    <option value="certificate">Needs an English certificate</option>
    <option value="fluency">Fluency only — no certificate</option></select>
  <select id="sort">
    <option value="score">Sort: best match</option>
    <option value="date">Sort: newest posted</option>
    <option value="exp">Sort: least experience required</option>
  </select>
  <label class="toggle"><input type="checkbox" id="hideApplied"> Hide applied</label>
</div>

<div class="exportbar" id="exportbar" hidden>
  <h2>Roles Kasi turned down (<span id="rejCount">0</span>)</h2>
  <p>These are hidden from his list on this device. To make them stick for good — on every
     device and in every future scrape — paste the block below into
     <code>profile/not_interested.json</code> under <code>"exclusions"</code> and commit it.</p>
  <textarea id="exportJson" readonly spellcheck="false"></textarea>
  <div class="actions">
    <button class="ghost" id="copyExport">Copy to clipboard</button>
    <button class="ghost" id="downloadExport">Download JSON</button>
    <button class="ghost" id="clearRejects">Undo all — show them again</button>
  </div>
</div>

<div id="list"></div>
<footer id="foot"></footer>
</div>

<script>
const JOBS = __JOBS__;
const META = __META__;
const KEY = "kasi-applied-v1";
const RKEY = "kasi-notinterested-v1";
// Some contexts block site storage entirely (private windows, embedded
// previews, browsers set to block it). Fall back to an in-memory store so the
// buttons still respond within the session instead of silently doing nothing —
// and tell the reader their ticks won't survive a refresh.
let MEM = {}, STORAGE_OK = true;
function readStore(k){
  try { return JSON.parse(localStorage.getItem(k) || "null") ?? (MEM[k] || {}); }
  catch(e){ STORAGE_OK = false; return MEM[k] || {}; }
}
function writeStore(k, v){
  MEM[k] = v;
  try { localStorage.setItem(k, JSON.stringify(v)); }
  catch(e){ STORAGE_OK = false; }
}
const state = () => readStore(KEY);
const save = s => writeStore(KEY, s);
// "Not interested" is keyed by company + normalised title, matching how the
// pipeline excludes roles — so a repost under a new requisition id stays hidden.
const rkeyOf = j => (j.company + "||" + j.title_norm).toLowerCase();
const rejects = () => readStore(RKEY);
const saveRejects = r => writeStore(RKEY, r);
const esc = s => String(s==null?"":s).replace(/[&<>"']/g, c => (
  {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

function fillSelect(id, values){
  const el = document.getElementById(id);
  [...new Set(values)].filter(Boolean).sort().forEach(v => {
    const o = document.createElement("option"); o.value = v; o.textContent = v; el.appendChild(o);
  });
}
fillSelect("bucket", JOBS.map(j => j.role_bucket));
fillSelect("company", JOBS.map(j => j.company));

function stats(){
  const s = state(), applied = JOBS.filter(j => s[j.job_id]).length;
  const strong = JOBS.filter(j => j.match_verdict === "strong_match").length;
  const fresh = JOBS.filter(j => (j.age_days!=null && j.age_days <= 7)).length;
  const nRej = Object.keys(rejects()).length;
  const cards = [
    [JOBS.length - nRej, "jobs to apply to"], [strong, "strong matches"],
    [fresh, "posted this week"], [applied, "marked applied"],
    [nRej, "turned down"], [(META.kasi_years ?? 0) + " yrs", "Kasi's experience"]];
  document.getElementById("stats").innerHTML = cards.map(([b,l]) =>
    `<div class="stat"><b>${esc(b)}</b><span>${esc(l)}</span></div>`).join("");
}

function funnel(){
  const rows = [["All postings on record", META.scraped],
    ["1 · worked on a ship", META.passed_ship], ["2 · housekeeping role", META.passed_hk],
    ["3 · matches Kasi's experience", META.passed_exp],
    ["4 · not turned down by Kasi", META.passed_wanted],
    ["5 · still open", META.passed_active],
    ["6 · posted within " + META.max_age_days + " days", META.passed_fresh]];
  const max = Math.max(1, ...rows.map(r => r[1] || 0));
  document.getElementById("funnel").innerHTML = rows.map(([l,n]) =>
    `<div class="frow"><span class="lab">${esc(l)}</span>
     <span class="bar" style="width:${((n||0)/max*100).toFixed(1)}%"></span>
     <span class="num">${n==null?"–":n}</span></div>`).join("");
}

function card(j){
  const s = state(), done = !!s[j.job_id];
  const chips = [
    `<span class="chip v-${esc(j.match_verdict)}">${j.match_verdict === "strong_match" ? "Strong match" : "Stretch"}</span>`,
    `<span class="chip">${esc(j.role_bucket.replace(/_/g," "))}</span>`,
    j.req_years_min != null ? `<span class="chip">asks ${j.req_years_min}+ yrs · Kasi has ${j.kasi_years}</span>`
                            : `<span class="chip">no experience bar stated</span>`,
    j.age_days != null ? `<span class="chip">${j.age_days === 0 ? "posted today" : "posted " + j.age_days + "d ago"}</span>` : "",
    j.evergreen ? `<span class="chip warn">evergreen req — re-dated by the board</span>` : "",
    j.english_tier === "certificate"
      ? `<span class="chip warn">English certificate needed${j.english_certs?" · "+esc(j.english_certs):""}</span>`
      : (j.english_tier === "fluency" ? `<span class="chip">English fluency — no certificate</span>` : ""),
    done ? `<span class="chip v-strong_match">✓ applied</span>` : ""
  ].filter(Boolean).join("");

  return `<div class="card ${done?"done":""}" data-id="${esc(j.job_id)}">
    <div class="top"><h3>${esc(j.title)}</h3><div class="score">${j.match_score}</div></div>
    <div class="meta">${esc(j.company)}${j.brand?" · "+esc(j.brand):""} — ${esc(j.location||"Fleetwide (onboard)")}
      ${j.date_posted?" · posted "+esc(j.date_posted):""}</div>
    <div class="chips">${chips}</div>
    <div class="actions">
      <a class="apply" href="${esc(j.apply_url)}" target="_blank" rel="noopener noreferrer">Apply on ${esc(j.company)} →</a>
      <button class="ghost mark">${done?"Mark not applied":"Mark as applied"}</button>
      ${j.posting_url && j.posting_url !== j.apply_url
        ? `<a class="ghost" style="text-decoration:none" href="${esc(j.posting_url)}" target="_blank" rel="noopener noreferrer">Read full posting</a>` : ""}
      <button class="ghost no reject">Not interested</button>
    </div>
    <details class="why"><summary>Why this matches Kasi (${j.reasons.length})</summary>
      <ul>${j.reasons.map(r=>`<li>${esc(r)}</li>`).join("")}</ul>
      <ul><li><em>Shipboard because:</em> ${esc(j.shipboard_reason)}</li></ul></details>
    ${applyBlock(j)}
    ${j.requirements.length ? `<details><summary>What the posting asks for (${j.requirements.length})</summary>
      <ul>${j.requirements.map(r=>`<li>${esc(r)}</li>`).join("")}</ul></details>` : ""}
    ${j.description ? `<details><summary>Full description</summary><pre class="jd">${esc(j.description)}</pre></details>` : ""}
  </div>`;
}

function applyBlock(j){
  const f = j.apply_form || {};
  const req = f.required_fields || [];
  if (!req.length) return "";
  const cv = f.cv_upload || {};
  const verified = f.verified_on
    ? `Form checked ${esc(f.verified_on)}${f.verified_against ? " on " + esc(f.verified_against) : ""}.`
    : `<strong>Not yet checked</strong> — this is the usual minimum, not a verified list.`;
  return `<details><summary>What you'll need to fill in (${req.length} required)</summary>
    <p style="font-size:12.5px;color:var(--muted);margin:8px 0 4px">${verified}
      ${f.steps ? "Steps: " + f.steps.map(esc).join(" → ") + "." : ""}</p>
    ${cv.required ? `<p style="font-size:13px;margin:6px 0"><strong>CV upload required</strong> —
        ${(cv.formats||[]).map(esc).join(", ")}, max ${esc(cv.max_size||"?")}.
        ${cv.note?esc(cv.note):""}</p>` : ""}
    <ul>${req.map(r=>`<li>${esc(r)}</li>`).join("")}</ul>
    ${(f.watch_out||[]).length ? `<p style="font-size:12.5px;color:var(--muted);margin:8px 0 0">
        <strong>Watch out:</strong></p><ul>${f.watch_out.map(w=>`<li>${esc(w)}</li>`).join("")}</ul>` : ""}
  </details>`;
}

function render(){
  const q = document.getElementById("q").value.toLowerCase().trim();
  const v = document.getElementById("verdict").value;
  const b = document.getElementById("bucket").value;
  const c = document.getElementById("company").value;
  const en = document.getElementById("english").value;
  const sort = document.getElementById("sort").value;
  const hide = document.getElementById("hideApplied").checked;
  const s = state();
  const rj = rejects();

  let rows = JOBS.filter(j => {
    if (rj[rkeyOf(j)]) return false;
    if (v && j.match_verdict !== v) return false;
    if (b && j.role_bucket !== b) return false;
    if (c && j.company !== c) return false;
    if (en && j.english_tier !== en) return false;
    if (hide && s[j.job_id]) return false;
    if (q) {
      const hay = [j.title,j.company,j.brand,j.location,j.department,
                   j.requirements.join(" "),j.description].join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  rows.sort((x,y) => sort === "date" ? String(y.date_posted).localeCompare(String(x.date_posted))
    : sort === "exp" ? ((x.req_years_min ?? 99) - (y.req_years_min ?? 99)) || (y.match_score - x.match_score)
    : (y.match_score - x.match_score));

  document.getElementById("list").innerHTML = rows.length
    ? rows.map(card).join("")
    : `<div class="empty">No jobs match these filters.<br>
       Clear the search box, or run <code>scripts/run_pipeline.sh</code> to refresh.</div>`;
  stats(); exportBar();
}

document.addEventListener("click", e => {
  const mark = e.target.closest(".mark");
  if (mark) {
    const id = mark.closest(".card").dataset.id;
    const s = state();
    if (s[id]) delete s[id]; else s[id] = new Date().toISOString().slice(0,10);
    save(s); render(); return;
  }
  const no = e.target.closest(".reject");
  if (no) {
    const id = no.closest(".card").dataset.id;
    const j = JOBS.find(x => x.job_id === id);
    if (!j) return;
    const rj = rejects();
    rj[rkeyOf(j)] = {company: j.company, title_norm: j.title_norm, title: j.title,
                     added: new Date().toISOString().slice(0,10)};
    saveRejects(rj); render(); return;
  }
});

function exportBar(){
  const rj = rejects();
  const keys = Object.keys(rj);
  const bar = document.getElementById("exportbar");
  bar.hidden = keys.length === 0;
  document.getElementById("rejCount").textContent = keys.length;
  if (!keys.length) return;
  const payload = keys.map(k => ({
    company: rj[k].company, title_norm: rj[k].title_norm,
    reason: "not interested (marked on dashboard)", added: rj[k].added
  }));
  document.getElementById("exportJson").value = JSON.stringify(payload, null, 2);
}

document.getElementById("copyExport").addEventListener("click", async () => {
  const ta = document.getElementById("exportJson");
  try { await navigator.clipboard.writeText(ta.value); }
  catch(e) { ta.select(); document.execCommand("copy"); }
  const b = document.getElementById("copyExport");
  b.textContent = "Copied"; setTimeout(()=>b.textContent="Copy to clipboard", 1500);
});
document.getElementById("downloadExport").addEventListener("click", () => {
  const blob = new Blob([document.getElementById("exportJson").value], {type:"application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "not_interested.json";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(a.href), 2000);
});
document.getElementById("clearRejects").addEventListener("click", () => {
  saveRejects({}); render();
});
["q","verdict","bucket","company","english","sort","hideApplied"].forEach(id =>
  document.getElementById(id).addEventListener("input", render));

document.getElementById("foot").innerHTML =
  `Built ${esc(META.run_date||"")} from <code>data/kasi_jobs.db</code>. `
  + `Every job here is on a ship, in housekeeping, open, posted within ${META.max_age_days} days, `
  + `and asks for experience within reach of Kasi's ${META.kasi_years} years. `
  + `Housekeeping postings turned away this run: `
  + (META.rejected||[]).map(r=>`${r.count} failed <code>${esc(r.gate)}</code>`).join(", ")
  + `. "Applied" and "Not interested" are saved in this browser only — use the export box to make them permanent.`
  + (STORAGE_OK ? "" : ` <strong>This browser is blocking site storage, so your ticks will be lost when you close the page — export them before you go.</strong>`);

document.getElementById("readylist").innerHTML =
  (META.have_ready||[]).map(x=>`<li>${esc(x)}</li>`).join("");
if (!(META.have_ready||[]).length) document.getElementById("readybox").hidden = true;

funnel(); render();
</script></body></html>"""


def main() -> None:
    jobs, meta = load()
    subtitle = (f"{len(jobs)} open shipboard housekeeping roles matched to Kasi's "
                f"{meta.get('kasi_years','?')} years of experience · "
                f"scraped {meta.get('run_date', common.TODAY)}")
    htmlout = (TEMPLATE
               .replace("__JOBS__", json.dumps(jobs, ensure_ascii=False))
               .replace("__META__", json.dumps(meta, ensure_ascii=False))
               .replace("__SUBTITLE__", html.escape(subtitle))
               .replace("__SCRAPED__", str(meta.get("scraped", "?")))
               .replace("__KEPT__", str(len(jobs))))
    for d in OUT_DIRS:
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, "index.html")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(htmlout)
        print(f"Dashboard → {out}  ({len(jobs)} jobs)")


if __name__ == "__main__":
    main()
