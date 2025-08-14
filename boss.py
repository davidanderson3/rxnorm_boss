#!/usr/bin/env python3
# boss.py
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# ---------- Column indices ----------
# RXNSAT (13 columns):
RXNSAT_ATN_COL = 8
RXNSAT_SAB_COL = 9
RXNSAT_ATV_COL = 10
RXNSAT_CODE_COL = 5
RXNSAT_SUPPRESS_COL = 11

# RXNCONSO (18 columns):
RXNCONSO_LAT_COL = 1
RXNCONSO_SAB_COL = 11
RXNCONSO_TTY_COL = 12
RXNCONSO_CODE_COL = 13
RXNCONSO_STR_COL = 14
RXNCONSO_ISPREF_COL = 6
RXNCONSO_SUPPRESS_COL = 16

# ---------- Attribute names ----------
ATN_AI = "RXN_AI"
ATN_AM = "RXN_AM"
ATN_BOSS_FROM = "RXN_BOSS_FROM"

# ---------- Regex ----------
BRACED_RXCUI = re.compile(r"\{(\d+)\}")
DIGITS = re.compile(r"\b(\d+)\b")
TOKEN_AI = re.compile(r"\bAI\b")
TOKEN_AM = re.compile(r"\bAM\b")

# ---------- Load RxNorm labels ----------
def load_labels(rxnconso_path: Path):
    primary: Dict[str, Tuple[str, str]] = {}
    by_tty: Dict[str, Dict[str, List[str]]] = {}
    with rxnconso_path.open(encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("|")
            if len(p) < 18: continue
            if p[RXNCONSO_SAB_COL] != "RXNORM": continue
            if p[RXNCONSO_LAT_COL] != "ENG": continue
            if p[RXNCONSO_SUPPRESS_COL] == "Y": continue
            rxcui = p[RXNCONSO_CODE_COL]; tty = p[RXNCONSO_TTY_COL]; s = p[RXNCONSO_STR_COL]; pref = p[RXNCONSO_ISPREF_COL]
            if not rxcui: continue
            by_tty.setdefault(rxcui, {}).setdefault(tty, []).append(s)
            if rxcui not in primary or pref == "Y":
                primary[rxcui] = (tty, s)
    return primary, by_tty

# ---------- Parse ATVs ----------
def parse_ai_am_atv(atv: str):
    if not atv: return None, None
    m = BRACED_RXCUI.search(atv)
    scdc = m.group(1) if m else None
    ing = None
    for d in DIGITS.findall(atv):
        if d != scdc:
            ing = d; break
    return scdc, ing

def parse_boss_from_atv(atv: str):
    if not atv: return None, None
    m = BRACED_RXCUI.search(atv)
    scdc = m.group(1) if m else None
    from_val = "AI" if TOKEN_AI.search(atv) else ("AM" if TOKEN_AM.search(atv) else None)
    return scdc, from_val

# ---------- Pickers ----------
def pick_preferred(rxcui: Optional[str], primary, by_tty, prefer_ttys=None):
    if not rxcui:
        return {"rxcui": None, "tty": None, "str": None}
    if prefer_ttys and rxcui in by_tty:
        for tty in prefer_ttys:
            if tty in by_tty[rxcui]:
                return {"rxcui": rxcui, "tty": tty, "str": by_tty[rxcui][tty][0]}
    if rxcui in primary:
        tty, s = primary[rxcui]; return {"rxcui": rxcui, "tty": tty, "str": s}
    return {"rxcui": rxcui, "tty": None, "str": None}

def pick_in_or_pin(rxcui: Optional[str], primary, by_tty):
    disp = pick_preferred(rxcui, primary, by_tty, prefer_ttys=["IN","PIN"])
    kind = disp["tty"] if disp["tty"] in ("IN","PIN") else None
    return disp, kind

# ---------- Build groups ----------
def build_groups(rxnsat_path: Path, primary, by_tty):
    groups: Dict[Tuple[str, str], dict] = {}
    with rxnsat_path.open(encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("|")
            if len(p) < 13: continue
            if p[RXNSAT_SAB_COL] != "RXNORM": continue
            if p[RXNSAT_SUPPRESS_COL] == "Y": continue
            atn = p[RXNSAT_ATN_COL]
            if atn not in (ATN_AI, ATN_AM, ATN_BOSS_FROM): continue
            parent = p[RXNSAT_CODE_COL]
            atv = p[RXNSAT_ATV_COL]

            if atn in (ATN_AI, ATN_AM):
                scdc, sub = parse_ai_am_atv(atv)
                if not scdc: continue
                key = (parent, scdc)
                g = groups.setdefault(key, {
                    "parent": pick_preferred(parent, primary, by_tty),
                    "scdc": pick_preferred(scdc, primary, by_tty, prefer_ttys=["SCDC","SBDC"]),
                    "ai_list": [],
                    "am_list": [],
                    "boss_from": set(),
                    "raw_atv": {ATN_AI: [], ATN_AM: [], ATN_BOSS_FROM: []}
                })
                if sub:
                    disp, kind = pick_in_or_pin(sub, primary, by_tty)
                    (g["ai_list"] if atn == ATN_AI else g["am_list"]).append({**disp, "kind": kind})
                g["raw_atv"][atn].append(atv)

            else:  # RXN_BOSS_FROM
                scdc, from_val = parse_boss_from_atv(atv)
                if not scdc: continue
                key = (parent, scdc)
                g = groups.setdefault(key, {
                    "parent": pick_preferred(parent, primary, by_tty),
                    "scdc": pick_preferred(scdc, primary, by_tty, prefer_ttys=["SCDC","SBDC"]),
                    "ai_list": [],
                    "am_list": [],
                    "boss_from": set(),
                    "raw_atv": {ATN_AI: [], ATN_AM: [], ATN_BOSS_FROM: []}
                })
                if from_val: g["boss_from"].add(from_val)
                g["raw_atv"][ATN_BOSS_FROM].append(atv)

    # finalize
    out_rows = []
    for (_parent, _scdc), g in groups.items():
        row = {
            "parent": g["parent"],
            "scdc": g["scdc"],
            "ai": g["ai_list"],
            "am": g["am_list"],
            "boss_from": sorted(list(g["boss_from"])) if g["boss_from"] else [],
            "raw_atv": g["raw_atv"],
        }
        row["explanation"] = build_explanation(row)  # <- now uses ai/am keys
        out_rows.append(row)
    return out_rows

def build_explanation(g: dict) -> str:
    parent = g["parent"]; scdc = g["scdc"]
    ai_list = g.get("ai", g.get("ai_list", []))
    am_list = g.get("am", g.get("am_list", []))
    boss = "/".join(g.get("boss_from", [])) if g.get("boss_from") else "—"
    ai_names = ", ".join([x.get("str") or (x.get("rxcui") or "?") for x in ai_list]) or "—"
    am_names = ", ".join([x.get("str") or (x.get("rxcui") or "?") for x in am_list]) or "—"
    return (f"Parent {parent['rxcui']} ({parent.get('tty') or '?'}, {parent.get('str') or '?'}) "
            f"has BoSS component SCDC {scdc['rxcui']} ({scdc.get('tty') or '?'}, {scdc.get('str') or '?'}) "
            f"with RXN_AI → [{ai_names}] and RXN_AM → [{am_names}]. "
            f"RXN_BOSS_FROM indicates strength measured from: {boss}.")

# ---------- Stats ----------
def compute_stats(rows: List[dict]) -> dict:
    n = len(rows)
    ai = sum(1 for r in rows if len(r["ai"]) > 0)
    am = sum(1 for r in rows if len(r["am"]) > 0)
    both = sum(1 for r in rows if len(r["ai"]) > 0 and len(r["am"]) > 0)
    ai_only = sum(1 for r in rows if len(r["ai"]) > 0 and len(r["am"]) == 0)
    am_only = sum(1 for r in rows if len(r["am"]) > 0 and len(r["ai"]) == 0)
    none = sum(1 for r in rows if len(r["ai"]) == 0 and len(r["am"]) == 0)

    boss_ai = sum(1 for r in rows if "AI" in r["boss_from"])
    boss_am = sum(1 for r in rows if "AM" in r["boss_from"])
    boss_none = sum(1 for r in rows if len(r["boss_from"]) == 0)

    # “consistency” snapshots (not normative, just descriptive):
    boss_ai_with_ai = sum(1 for r in rows if "AI" in r["boss_from"] and len(r["ai"]) > 0)
    boss_am_with_am = sum(1 for r in rows if "AM" in r["boss_from"] and len(r["am"]) > 0)

    # rows where AI and AM lists both exist but differ
    def _ai_am_sets(r):
        ai_set = {x.get("rxcui") for x in r["ai"] if x.get("rxcui")}
        am_set = {x.get("rxcui") for x in r["am"] if x.get("rxcui")}
        return ai_set, am_set

    diff_rows = []
    for r in rows:
        ai_set, am_set = _ai_am_sets(r)
        if ai_set and am_set and ai_set != am_set:
            diff_rows.append(r)

    diff = len(diff_rows)
    boss_ai_diff = sum(1 for r in diff_rows if "AI" in r["boss_from"])
    boss_am_diff = sum(1 for r in diff_rows if "AM" in r["boss_from"])

    def pct(x): return (100.0 * x / n) if n else 0.0
    def pct_diff(x): return (100.0 * x / diff) if diff else 0.0

    return {
        "total_groups": n,
        "has_ai": {"count": ai, "pct": pct(ai)},
        "has_am": {"count": am, "pct": pct(am)},
        "has_both_ai_am": {"count": both, "pct": pct(both)},
        "ai_only": {"count": ai_only, "pct": pct(ai_only)},
        "am_only": {"count": am_only, "pct": pct(am_only)},
        "neither_ai_nor_am": {"count": none, "pct": pct(none)},
        "boss_from_AI": {"count": boss_ai, "pct": pct(boss_ai)},
        "boss_from_AM": {"count": boss_am, "pct": pct(boss_am)},
        "boss_from_missing": {"count": boss_none, "pct": pct(boss_none)},
        "boss_AI_and_AI_present": {"count": boss_ai_with_ai, "pct": pct(boss_ai_with_ai)},
        "boss_AM_and_AM_present": {"count": boss_am_with_am, "pct": pct(boss_am_with_am)},
        "ai_am_different": {"count": diff, "pct": pct(diff)},
        "boss_from_AI_when_ai_am_different": {
            "count": boss_ai_diff,
            "pct": pct_diff(boss_ai_diff),
        },
        "boss_from_AM_when_ai_am_different": {
            "count": boss_am_diff,
            "pct": pct_diff(boss_am_diff),
        },
    }

def load_data(base: Path = Path(__file__).parent):
    """Load grouped BoSS data and statistics from RRF files.

    Parameters
    ----------
    base: Path
        Directory containing RXNSAT.RRF and RXNCONSO.RRF.
    """
    rxnsat = base / "RXNSAT.RRF"
    rxnconso = base / "RXNCONSO.RRF"
    primary, by_tty = load_labels(rxnconso)
    rows = build_groups(rxnsat, primary, by_tty)
    stats = compute_stats(rows)
    return rows, stats

# ---------- HTML ----------
HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>RxNorm BoSS Viewer (AI · AM · BOSS_FROM)</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
:root { --bg:#0b0f14; --fg:#e7eef7; --muted:#9fb3c8; --accent:#5aa9ff; --chip:#1e2a38; --chip2:#243345; --row:#0f141b; --rowalt:#121924; --border:#223047; }
body { background:var(--bg); color:var(--fg); font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; margin:0; }
header { padding:18px 20px; border-bottom:1px solid var(--border); }
h1 { margin:0; font-size:20px; }
small { color:var(--muted); }
.container { padding:16px 20px; }
.controls { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:10px; }
input[type="text"], select { background:#0e1621; color:var(--fg); border:1px solid var(--border); border-radius:8px; padding:8px 10px; }
button { background:var(--accent); color:#06233f; border:none; border-radius:10px; padding:8px 12px; font-weight:600; cursor:pointer; }
button[disabled]{ opacity:.5; cursor:not-allowed; }
.table { width:100%; border-collapse:collapse; }
th, td { padding:10px 8px; border-bottom:1px solid var(--border); vertical-align:top; }
tbody tr:nth-child(even){ background:var(--rowalt); }
tbody tr:nth-child(odd){ background:var(--row); }
.badge { display:inline-block; padding:2px 6px; border-radius:12px; background:var(--chip); color:var(--fg); font-size:12px; margin-right:4px; }
.badge.am { background:#3b2c4a; }
.badge.ai { background:#2a3a52; }
.badge.from { background:#304b2e; }
.rxcui { font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; background:var(--chip2); padding:2px 6px; border-radius:8px; }
.tt { color:var(--muted); }
details { background:#0e1621; border:1px solid var(--border); border-radius:10px; padding:8px 10px; }
summary { cursor:pointer; }
footer { color:var(--muted); padding:14px 20px; border-top:1px solid var(--border); }
kbd { background:#101820; border:1px solid #203040; border-bottom-width:2px; padding:1px 5px; border-radius:6px; }
.help { color:var(--muted); }
.explain, .summarybox { background:#0f161f; border:1px solid var(--border); border-radius:12px; padding:12px 14px; margin-bottom:14px; }
.summarybox table { width:100%; border-collapse:collapse; }
.summarybox th, .summarybox td { border-bottom:1px solid var(--border); padding:6px 8px; }
</style>
</head>
<body>
<header>
  <h1>RxNorm BoSS Viewer <small>(RXN_AI · RXN_AM · RXN_BOSS_FROM, grouped by Parent × SCDC)</small></h1>
</header>
<div class="container">

  <div class="explain">
    <strong>What am I looking at?</strong>
    <p>BoSS data grouped by the <em>Parent</em> drug (SCD/SBD) and the <em>SCDC</em> component whose strength is measured.</p>
    <ul>
      <li><span class="badge ai">RXN_AI</span> “Active Ingredient”: ATV format <code>{SCDC_RXCUI}</code> then the Ingredient/Precise Ingredient RXCUI.</li>
      <li><span class="badge am">RXN_AM</span> “Active Moiety”: ATV format <code>{SCDC_RXCUI}</code> then the Moiety (IN/PIN) RXCUI.</li>
      <li><span class="badge from">RXN_BOSS_FROM</span> indicates whether the strength (for that SCDC) is measured from <kbd>AI</kbd> or <kbd>AM</kbd>.</li>
    </ul>
    <p class="help">Attributes live on SCD/SBD. Post-2021, AI/AM ATVs carry two RXCUIs: the SCDC (braced) and the IN/PIN.</p>
  </div>

  <div class="summarybox">
    <strong>Summary (counts & % of Parent×SCDC groups)</strong>
    <table id="statsTbl"></table>
  </div>

  <div class="controls">
    <input id="q" type="text" placeholder="Filter by RXCUI or name…"/>
    <label>Page size:
      <select id="pageSize"><option>25</option><option selected>50</option><option>100</option><option>200</option></select>
    </label>
    <div style="margin-left:auto">
      <button id="prevBtn">Prev</button>
      <span id="pageInfo" class="help"></span>
      <button id="nextBtn">Next</button>
    </div>
  </div>

  <table class="table" id="tbl">
    <thead>
      <tr>
        <th>#</th>
        <th>Parent (SCD/SBD)</th>
        <th>SCDC</th>
        <th>AI (IN/PIN)</th>
        <th>AM (IN/PIN)</th>
        <th>BOSS_FROM</th>
        <th>Details</th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>
</div>

<footer>
  Built from RXNSAT/RXNCONSO (SAB=RXNORM, ENG, not suppressed). Grouped by Parent×SCDC. Filter & paginate client-side.
</footer>

<script>
const DATA = __DATA__;
const STATS = __STATS__;

function pct(x){ return (x||0).toFixed(1) + "%"; }

function renderStats(){
  const rows = [
    ["Total groups", STATS.total_groups, ""],
    ["Has AI", STATS.has_ai.count, pct(STATS.has_ai.pct)],
    ["Has AM", STATS.has_am.count, pct(STATS.has_am.pct)],
    ["Has both AI & AM", STATS.has_both_ai_am.count, pct(STATS.has_both_ai_am.pct)],
    ["AI & AM differ", STATS.ai_am_different.count, pct(STATS.ai_am_different.pct)],
    ["When AI≠AM: BOSS_FROM = AI", STATS.boss_from_AI_when_ai_am_different.count, pct(STATS.boss_from_AI_when_ai_am_different.pct)],
    ["When AI≠AM: BOSS_FROM = AM", STATS.boss_from_AM_when_ai_am_different.count, pct(STATS.boss_from_AM_when_ai_am_different.pct)],
    ["AI only", STATS.ai_only.count, pct(STATS.ai_only.pct)],
    ["AM only", STATS.am_only.count, pct(STATS.am_only.pct)],
    ["Neither AI nor AM", STATS.neither_ai_nor_am.count, pct(STATS.neither_ai_nor_am.pct)],
    ["BOSS_FROM = AI", STATS.boss_from_AI.count, pct(STATS.boss_from_AI.pct)],
    ["BOSS_FROM = AM", STATS.boss_from_AM.count, pct(STATS.boss_from_AM.pct)],
    ["BOSS_FROM missing", STATS.boss_from_missing.count, pct(STATS.boss_from_missing.pct)],
    ["BOSS_FROM AI & AI present", STATS.boss_AI_and_AI_present.count, pct(STATS.boss_AI_and_AI_present.pct)],
    ["BOSS_FROM AM & AM present", STATS.boss_AM_and_AM_present.count, pct(STATS.boss_AM_and_AM_present.pct)]
  ];
  const tbl = document.getElementById("statsTbl");
  tbl.innerHTML = "<tr><th>Scenario</th><th>Count</th><th>%</th></tr>" +
    rows.map(r=>`<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td></tr>`).join("");
}

const state = { page:1, pageSize:50, query:"" };
function norm(s){ return (s||"").toLowerCase(); }
function matchRow(r, q){
  if(!q) return true;
  const hay = [
    r.parent.rxcui, r.parent.str, r.parent.tty,
    r.scdc.rxcui, r.scdc.str, r.scdc.tty,
    ...(r.ai||[]).map(x=>[x.rxcui,x.str,x.kind]).flat(),
    ...(r.am||[]).map(x=>[x.rxcui,x.str,x.kind]).flat(),
    ...(r.boss_from||[])
  ].map(x => (x||"").toString().toLowerCase());
  return hay.some(s => s.includes(q));
}
function fmtConcept(c){
  const rxcui = c && c.rxcui ? `<span class="rxcui">${c.rxcui}</span>` : "—";
  const name = c && c.str ? c.str : "—";
  const tty  = c && c.tty ? `<span class="tt">${c.tty}</span>` : "";
  return `${rxcui}<br/>${name} ${tty}`;
}
function fmtList(list){
  if(!list || list.length===0) return "—";
  return list.map(x=>{
    const kind = x.kind ? x.kind : "";
    const kindBadge = kind ? `<span class="badge ${kind==='IN'?'ai':'am'}">${kind}</span>` : "";
    const rxcui = x.rxcui ? `<span class="rxcui">${x.rxcui}</span>` : "—";
    const name  = x.str || "—";
    return `${kindBadge} ${rxcui}<br/>${name}`;
  }).join("<hr style='border-color:#223047'/>");
}
function fmtBoss(b){
  if(!b || b.length===0) return "—";
  return b.map(x=>`<span class="badge from">${x}</span>`).join(" ");
}
function fmtDetails(r){
  const raw = r.raw_atv || {};
  const ai  = (raw.RXN_AI||[]).map(x=>`<code>${x}</code>`).join("<br/>") || "—";
  const am  = (raw.RXN_AM||[]).map(x=>`<code>${x}</code>`).join("<br/>") || "—";
  const bf  = (raw.RXN_BOSS_FROM||[]).map(x=>`<code>${x}</code>`).join("<br/>") || "—";
  const expl = r.explanation || "";
  return `<details><summary>Show</summary>
    <div style="margin-top:6px">
      <div><strong>Explanation:</strong> ${expl}</div>
      <div style="margin-top:6px"><strong>Raw ATV</strong></div>
      <div><span class="badge ai">RXN_AI</span> ${ai}</div>
      <div><span class="badge am">RXN_AM</span> ${am}</div>
      <div><span class="badge from">RXN_BOSS_FROM</span> ${bf}</div>
    </div>
  </details>`;
}
function render(){
  renderStats();
  const q = norm(state.query);
  const filtered = DATA.filter(r => matchRow(r,q));
  const total = filtered.length;
  const pages = Math.max(1, Math.ceil(total / state.pageSize));
  if(state.page > pages) state.page = pages;
  const start = (state.page-1) * state.pageSize;
  const rows = filtered.slice(start, start + state.pageSize);

  const tbody = document.querySelector("#tbl tbody");
  tbody.innerHTML = "";
  rows.forEach((r, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${start + i + 1}</td>
      <td>${fmtConcept(r.parent)}</td>
      <td>${fmtConcept(r.scdc)}</td>
      <td>${fmtList(r.ai)}</td>
      <td>${fmtList(r.am)}</td>
      <td>${fmtBoss(r.boss_from)}</td>
      <td>${fmtDetails(r)}</td>
    `;
    tbody.appendChild(tr);
  });

  document.getElementById("pageInfo").textContent =
    `Page ${state.page} of ${pages} — ${total} group${total===1?"":"s"}`;
  document.getElementById("prevBtn").disabled = state.page<=1;
  document.getElementById("nextBtn").disabled = state.page>=pages;
}
document.getElementById("pageSize").addEventListener("change", e=>{
  state.pageSize = parseInt(e.target.value,10)||50; state.page=1; render();
});
document.getElementById("q").addEventListener("input", e=>{
  state.query = e.target.value; state.page=1; render();
});
document.getElementById("prevBtn").addEventListener("click", ()=>{
  state.page = Math.max(1, state.page-1); render();
});
document.getElementById("nextBtn").addEventListener("click", ()=>{
  state.page = state.page+1; render();
});
render();
</script>
</body>
</html>
"""

def _js_escape(s: str) -> str:
    """Escape JSON for embedding inside a <script> tag.

    Browsers treat certain characters (U+2028, U+2029, ``</``, ``<!--``, ``-->``)
    specially when parsing JavaScript inside HTML. If these appear unescaped in
    our JSON data the generated ``rxnorm_boss_view.html`` can produce
    ``SyntaxError`` when loaded in a browser. ``json.dumps`` with
    ``ensure_ascii=False`` will emit those characters verbatim, so we replace
    them with escaped sequences that JavaScript can safely evaluate.
    """
    return (
        s.replace("\u2028", "\\u2028")
         .replace("\u2029", "\\u2029")
         .replace("<!--", "<\\!--")
         .replace("-->", "--\\>")
         .replace("</", "<\\/")
    )


def write_html(out_path: Path, data: list, stats: dict):
    html = (
        HTML_TEMPLATE
        .replace("__DATA__", _js_escape(json.dumps(data, ensure_ascii=False)))
        .replace("__STATS__", _js_escape(json.dumps(stats, ensure_ascii=False)))
    )
    out_path.write_text(html, encoding="utf-8")

def main():
    base = Path(__file__).parent
    out_html = base / "rxnorm_boss_view.html"
    rows, stats = load_data(base)
    write_html(out_html, rows, stats)
    print(f"✅ Wrote {out_html} with {len(rows)} Parent×SCDC rows.")

if __name__ == "__main__":
    main()
