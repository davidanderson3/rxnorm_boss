#!/usr/bin/env python3
# build_boss_view.py
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# ---------- Column indices ----------
# RXNSAT (13 columns):
# 0 CUI | 1 LUI | 2 SUI | 3 METAUI | 4 STYPE | 5 CODE | 6 ATUI | 7 SATUI |
# 8 ATN | 9 SAB | 10 ATV | 11 SUPPRESS | 12 CVF
RXNSAT_ATN_COL = 8
RXNSAT_SAB_COL = 9
RXNSAT_ATV_COL = 10
RXNSAT_CODE_COL = 5
RXNSAT_SUPPRESS_COL = 11

# RXNCONSO (18 columns):
# 0 CUI | 1 LAT | 2 TS | 3 LUI | 4 STT | 5 SUI | 6 ISPREF | 7 AUI | 8 SAUI |
# 9 SCUI | 10 SDUI | 11 SAB | 12 TTY | 13 CODE | 14 STR | 15 SRL | 16 SUPPRESS | 17 CVF
RXNCONSO_LAT_COL = 1
RXNCONSO_SAB_COL = 11
RXNCONSO_TTY_COL = 12
RXNCONSO_CODE_COL = 13
RXNCONSO_STR_COL = 14
RXNCONSO_ISPREF_COL = 6
RXNCONSO_SUPPRESS_COL = 16

# ---------- Attribute names we care about ----------
ATN_AI = "RXN_AI"
ATN_AM = "RXN_AM"
ATN_BOSS_FROM = "RXN_BOSS_FROM"

# ---------- Regex helpers ----------
BRACED_RXCUI = re.compile(r"\{(\d+)\}")
DIGITS = re.compile(r"\b(\d+)\b")
TOKEN_AI = re.compile(r"\bAI\b")
TOKEN_AM = re.compile(r"\bAM\b")

# ---------- Load RxNorm labels ----------
def load_labels(rxnconso_path: Path):
    """
    Build two indices:
      primary[rxcui] -> (tty, str)  # ISPREF='Y' if possible, else first
      by_tty[rxcui] -> {tty: [str, ...]}  # to query IN/PIN vs SCDC/SBDC
    Only SAB=RXNORM, LAT=ENG, SUPPRESS!='Y'
    """
    primary: Dict[str, Tuple[str, str]] = {}
    by_tty: Dict[str, Dict[str, List[str]]] = {}
    with rxnconso_path.open(encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("|")
            if len(p) < 18:
                continue
            if p[RXNCONSO_SAB_COL] != "RXNORM":
                continue
            if p[RXNCONSO_LAT_COL] != "ENG":
                continue
            if p[RXNCONSO_SUPPRESS_COL] == "Y":
                continue
            rxcui = p[RXNCONSO_CODE_COL]
            tty   = p[RXNCONSO_TTY_COL]
            s     = p[RXNCONSO_STR_COL]
            pref  = p[RXNCONSO_ISPREF_COL]
            if not rxcui:
                continue
            by_tty.setdefault(rxcui, {}).setdefault(tty, []).append(s)
            # choose primary
            if rxcui not in primary or pref == "Y":
                primary[rxcui] = (tty, s)
    return primary, by_tty

# ---------- Parse ATVs ----------
def parse_ai_am_atv(atv: str):
    """
    For RXN_AI / RXN_AM:
      ATV format (post-2021): "{SCDC_RXCUI} IN_or_PIN_RXCUI"
    Returns (scdc_rxcui, substance_rxcui) or (None, None)
    """
    if not atv:
        return None, None
    scdc = None
    m = BRACED_RXCUI.search(atv)
    if m:
        scdc = m.group(1)
    # pick the first number that's NOT the braced one
    ing = None
    for d in DIGITS.findall(atv):
        if d != scdc:
            ing = d
            break
    return scdc, ing

def parse_boss_from_atv(atv: str):
    """
    For RXN_BOSS_FROM:
      Expected format: "{SCDC_RXCUI} AI" or "{SCDC_RXCUI} AM"
      Returns (scdc_rxcui, from_value) where from_value in {"AI","AM", None}
    """
    if not atv:
        return None, None
    scdc = None
    m = BRACED_RXCUI.search(atv)
    if m:
        scdc = m.group(1)
    from_val = "AI" if TOKEN_AI.search(atv) else ("AM" if TOKEN_AM.search(atv) else None)
    return scdc, from_val

# ---------- Pickers ----------
def pick_preferred(rxcui: Optional[str], primary, by_tty, prefer_ttys=None):
    """
    Return dict with rxcui, tty, str (best-effort).
    prefer_ttys: e.g., ["SCDC","SBDC"] or ["IN","PIN"]
    """
    if not rxcui:
        return {"rxcui": None, "tty": None, "str": None}
    # try to honor preferred ttys
    if prefer_ttys and rxcui in by_tty:
        for tty in prefer_ttys:
            if tty in by_tty[rxcui]:
                return {"rxcui": rxcui, "tty": tty, "str": by_tty[rxcui][tty][0]}
    # fallback to primary label
    if rxcui in primary:
        tty, s = primary[rxcui]
        return {"rxcui": rxcui, "tty": tty, "str": s}
    return {"rxcui": rxcui, "tty": None, "str": None}

def pick_in_or_pin(rxcui: Optional[str], primary, by_tty):
    """
    Prefer IN over PIN for display, but report whichever exists.
    Also return the actual kind detected ("IN" or "PIN" or None).
    """
    disp = pick_preferred(rxcui, primary, by_tty, prefer_ttys=["IN","PIN"])
    kind = disp["tty"] if disp["tty"] in ("IN","PIN") else None
    return disp, kind

# ---------- Build groups ----------
def build_groups(rxnsat_path: Path, primary, by_tty):
    """
    Group by (parent_rxcui, scdc_rxcui):
      each group has fields: parent, scdc, ai_list, am_list, boss_from (set), raw_atv {ATN: [ATV,...]}
    """
    groups: Dict[Tuple[str, str], dict] = {}

    with rxnsat_path.open(encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("|")
            if len(p) < 13:
                continue
            if p[RXNSAT_SAB_COL] != "RXNORM":
                continue
            if p[RXNSAT_SUPPRESS_COL] == "Y":
                continue
            atn = p[RXNSAT_ATN_COL]
            if atn not in (ATN_AI, ATN_AM, ATN_BOSS_FROM):
                continue

            parent = p[RXNSAT_CODE_COL]  # SCD/SBD RXCUI
            atv = p[RXNSAT_ATV_COL]

            if atn in (ATN_AI, ATN_AM):
                scdc, sub = parse_ai_am_atv(atv)
                if not scdc:
                    # can't group without SCDC key
                    continue
                key = (parent, scdc)
                g = groups.setdefault(key, {
                    "parent": pick_preferred(parent, primary, by_tty),
                    "scdc": pick_preferred(scdc, primary, by_tty, prefer_ttys=["SCDC","SBDC"]),
                    "ai_list": [],
                    "am_list": [],
                    "boss_from": set(),
                    "raw_atv": {ATN_AI: [], ATN_AM: [], ATN_BOSS_FROM: []}
                })
                if atn == ATN_AI and sub:
                    disp, kind = pick_in_or_pin(sub, primary, by_tty)
                    g["ai_list"].append({**disp, "kind": kind})
                elif atn == ATN_AM and sub:
                    disp, kind = pick_in_or_pin(sub, primary, by_tty)
                    g["am_list"].append({**disp, "kind": kind})
                g["raw_atv"][atn].append(atv)

            elif atn == ATN_BOSS_FROM:
                scdc, from_val = parse_boss_from_atv(atv)
                if not scdc:
                    continue
                key = (parent, scdc)
                g = groups.setdefault(key, {
                    "parent": pick_preferred(parent, primary, by_tty),
                    "scdc": pick_preferred(scdc, primary, by_tty, prefer_ttys=["SCDC","SBDC"]),
                    "ai_list": [],
                    "am_list": [],
                    "boss_from": set(),
                    "raw_atv": {ATN_AI: [], ATN_AM: [], ATN_BOSS_FROM: []}
                })
                if from_val:
                    g["boss_from"].add(from_val)
                g["raw_atv"][ATN_BOSS_FROM].append(atv)

    # finalize groups
    out = []
    for (parent, scdc), g in groups.items():
        out.append({
            "parent": g["parent"],
            "scdc": g["scdc"],
            "ai": g["ai_list"],
            "am": g["am_list"],
            "boss_from": sorted(list(g["boss_from"])) if g["boss_from"] else [],
            "raw_atv": g["raw_atv"],
            "explanation": build_explanation(g)
        })
    return out

def build_explanation(g: dict) -> str:
    parent = g["parent"]
    scdc = g["scdc"]
    boss = "/".join(g["boss_from"]) if g["boss_from"] else "—"
    ai_names = ", ".join([x["str"] or (x["rxcui"] or "?") for x in g["ai"]]) or "—"
    am_names = ", ".join([x["str"] or (x["rxcui"] or "?") for x in g["am"]]) or "—"
    return (f"Parent {parent['rxcui']} ({parent['tty'] or '?'}, {parent['str'] or '?'}) "
            f"has BoSS component SCDC {scdc['rxcui']} ({scdc['tty'] or '?'}, {scdc['str'] or '?'}) "
            f"with RXN_AI → [{ai_names}] and RXN_AM → [{am_names}]. "
            f"RXN_BOSS_FROM indicates strength measured from: {boss}.")

# ---------- HTML writer ----------
HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>RxNorm BoSS (AI / AM / BOSS_FROM) Viewer</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
:root {
  --bg: #0b0f14; --fg: #e7eef7; --muted: #9fb3c8; --accent: #5aa9ff;
  --chip: #1e2a38; --chip2: #243345; --row: #0f141b; --rowalt: #121924;
  --border: #223047;
}
body { background: var(--bg); color: var(--fg); font: 14px/1.45 system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; margin: 0; }
header { padding: 18px 20px; border-bottom: 1px solid var(--border); }
h1 { margin: 0; font-size: 20px; }
small { color: var(--muted); }
.container { padding: 16px 20px; }
.controls { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
input[type="text"], select { background: #0e1621; color: var(--fg); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; }
button { background: var(--accent); color: #06233f; border: none; border-radius: 10px; padding: 8px 12px; font-weight: 600; cursor: pointer; }
button[disabled] { opacity: 0.5; cursor: not-allowed; }
.table { width: 100%; border-collapse: collapse; }
th, td { padding: 10px 8px; border-bottom: 1px solid var(--border); vertical-align: top; }
tbody tr:nth-child(even) { background: var(--rowalt); }
tbody tr:nth-child(odd) { background: var(--row); }
.badge { display: inline-block; padding: 2px 6px; border-radius: 12px; background: var(--chip); color: var(--fg); font-size: 12px; margin-right: 4px; }
.badge.am { background: #3b2c4a; }
.badge.ai { background: #2a3a52; }
.badge.from { background: #304b2e; }
.rxcui { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; background: var(--chip2); padding: 2px 6px; border-radius: 8px; }
.tt { color: var(--muted); }
details { background: #0e1621; border: 1px solid var(--border); border-radius: 10px; padding: 8px 10px; }
summary { cursor: pointer; }
footer { color: var(--muted); padding: 14px 20px; border-top: 1px solid var(--border); }
kbd { background:#101820; border:1px solid #203040; border-bottom-width:2px; padding:1px 5px; border-radius:6px; }
.help { color: var(--muted); }
.explain { background: #0f161f; border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; margin-bottom: 14px; }
</style>
</head>
<body>
<header>
  <h1>RxNorm BoSS Viewer <small>(RXN_AI · RXN_AM · RXN_BOSS_FROM, grouped by Parent × SCDC)</small></h1>
</header>
<div class="container">

  <div class="explain">
    <strong>What am I looking at?</strong>
    <p>This view groups Basis of Strength Substance (BoSS) data by the <em>Parent</em> drug (SCD/SBD) and the <em>SCDC</em> component that carries strength.</p>
    <ul>
      <li><span class="badge ai">RXN_AI</span> = “Active Ingredient”: <code>{SCDC_RXCUI}</code> then the Ingredient/Precise Ingredient RXCUI.</li>
      <li><span class="badge am">RXN_AM</span> = “Active Moiety”: <code>{SCDC_RXCUI}</code> then the Moiety (IN/PIN) RXCUI.</li>
      <li><span class="badge from">RXN_BOSS_FROM</span> says whether the strength is measured <em>from</em> the AI or the AM for that SCDC: value is <kbd>AI</kbd> or <kbd>AM</kbd>.</li>
    </ul>
    <p class="help">Format notes: post-2021, <code>ATV</code> for AI/AM is <code>{SCDC_RXCUI} IN_or_PIN_RXCUI</code>. For BOSS_FROM it’s <code>{SCDC_RXCUI} AI|AM</code>. Attributes live on the SCD/SBD (parent). SCDC is shown because it’s the component whose strength is being measured.</p>
  </div>

  <div class="controls">
    <input id="q" type="text" placeholder="Filter by RXCUI or name…"/>
    <label>Page size:
      <select id="pageSize">
        <option>25</option><option selected>50</option><option>100</option><option>200</option>
      </select>
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
  Built from RXNSAT/RXNCONSO (SAB=RXNORM, ENG, not suppressed). Grouped by Parent×SCDC. Use the search box to filter; pagination is client-side.
</footer>

<script>
const DATA = __DATA__;

const state = { page: 1, pageSize: 50, query: "" };

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

def write_html(out_path: Path, data: list):
    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    out_path.write_text(html, encoding="utf-8")

def main():
    base = Path(__file__).parent
    rxnsat = base / "RXNSAT.RRF"
    rxnconso = base / "RXNCONSO.RRF"
    out_html = base / "rxnorm_boss_view.html"

    primary, by_tty = load_labels(rxnconso)
    groups = build_groups(rxnsat, primary, by_tty)
    write_html(out_html, groups)

    print(f"✅ Wrote {out_html} with {len(groups)} grouped rows (Parent×SCDC).")

if __name__ == "__main__":
    main()
