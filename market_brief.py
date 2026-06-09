"""
market_brief.py  —  Daily AI-powered market analysis → HTML (public)
Requirements:  pip install yfinance anthropic
"""

import os, sys, json, re, time, datetime
import yfinance as yf
import anthropic

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_API_KEY_HERE")
OUTPUT_HTML = "index.html"

# Stocks grouped by sector — add more any time
SECTORS = {
    "AI Infrastructure": ["NVDA", "ALAB", "POWL", "MOD", "VRT", "GFS"],
    "Semiconductors":    ["MRVL", "MU", "AMD", "AVGO", "CRDO", "ARM"],
    "Cybersecurity":     ["S", "ZS", "AXON"],
    "Software & AI":     ["NOW", "ADBE", "CRM", "META", "GOOG", "BIDU"],
    "Pharma & Biotech":  ["ISRG", "REGN", "RXRX"],
    "Other":             ["CCJ", "JEDI", "CWAN", "GRAB"],
}

# Flat list for fetching
ALL_STOCKS = [t for stocks in SECTORS.values() for t in stocks]

MACRO = {
    "Gold":      "GC=F",
    "Copper":    "HG=F",
    "Oil (WTI)": "CL=F",
    "10Y Yield": "^TNX",
    "VIX":       "^VIX",
    "AUD/USD":   "AUDUSD=X",
    "S&P 500":   "^GSPC",
    "Nasdaq":    "^IXIC",
    "PHLX Semi": "^SOX",
    "ASX 200":   "^AXJO",
}

# ─────────────────────────────────────────────
# DATA FETCHING
# ─────────────────────────────────────────────

def fetch_price_data(tickers):
    results = {}
    for ticker in tickers:
        for attempt in range(3):
            try:
                t   = yf.Ticker(ticker)
                fi  = t.fast_info
                inf = t.info
                price = fi.last_price
                prev  = fi.previous_close
                if price is None:
                    raise ValueError("price is None")
                chg  = ((price - prev) / prev * 100) if prev else 0
                hi52 = inf.get("fiftyTwoWeekHigh") or inf.get("52WeekHigh")
                lo52 = inf.get("fiftyTwoWeekLow")  or inf.get("52WeekLow")
                name = inf.get("shortName") or inf.get("longName") or ticker
                results[ticker] = {
                    "name":       name,
                    "price":      round(price, 3),
                    "prev_close": round(prev, 3) if prev else "N/A",
                    "change_pct": round(chg, 2),
                    "day_high":   round(fi.day_high, 3) if fi.day_high else "N/A",
                    "day_low":    round(fi.day_low,  3) if fi.day_low  else "N/A",
                    "52w_high":   round(hi52, 3) if hi52 else "N/A",
                    "52w_low":    round(lo52, 3) if lo52 else "N/A",
                    "mkt_cap":    inf.get("marketCap"),
                    "pe_ratio":   inf.get("trailingPE") or inf.get("forwardPE"),
                    "sector":     inf.get("sector", ""),
                }
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(2)
                else:
                    print(f"      WARNING: Could not fetch {ticker}: {e}")
                    results[ticker] = {"name": ticker, "price": "N/A", "change_pct": 0}
    return results

# ─────────────────────────────────────────────
# CLAUDE ANALYSIS
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are a sharp, independent market analyst producing a public-facing daily market intelligence page. No disclaimers. No mention of any personal portfolio. Direct, blunt, high-conviction. Flag rationalisations.

MACRO FRAMEWORK: Iran/Hormuz disruption central thesis. Stagflation regime: sticky CPI 3.8%, Fed on hold, RBA hiking. AI bubble repricing risk Q4 2026 to Q2 2027 (25-40% on AI names). Gold supercycle. Structural copper deficit. Nuclear renaissance. AI infrastructure arms race.

SIGNAL DEFINITIONS:
- MULTIBAGGER: asymmetric upside, early in a structural trend, 3-5x potential over 2-3 years
- DEEP VALUE: trading at significant discount to intrinsic value, catalyst needed
- UNDERVALUED: solid business, below fair value, lower risk than multibagger
- WATCH: interesting but wait for better entry or catalyst confirmation
- AVOID: deteriorating fundamentals or structurally challenged

CRITICAL RULES:
- Respond ONLY with valid JSON. No text outside the JSON object.
- No markdown fences. No preamble.
- Do NOT use apostrophes or contractions. Write "does not" not "doesn't".
- Do NOT use single quotes inside JSON string values.

JSON STRUCTURE:
{
  "regime": "3 sentence macro regime snapshot covering Fed, inflation, AI bubble risk, and key macro themes",
  "sector_rotation": "2 sentences on where institutional money is moving right now",
  "risks": "2 sentences on the single biggest near-term risk to risk assets",
  "top5": [
    {
      "rank": 1,
      "ticker": "XXX",
      "signal": "MULTIBAGGER",
      "thesis": "3-4 sentence deep dive: why this stock, what is the structural driver, what does the market miss",
      "entry": "specific price or range",
      "target": "12-month price target with reasoning",
      "invalidation": "specific level or event that breaks the thesis",
      "risk_reward": "e.g. 3:1"
    }
  ],
  "stock_analysis": [
    {
      "ticker": "XXX",
      "signal": "MULTIBAGGER",
      "one_liner": "one sentence verdict without apostrophes",
      "entry": "price or range",
      "watch_level": "key level to watch"
    }
  ]
}"""

def get_claude_analysis(stock_data, macro_data, audusd):
    today = datetime.date.today().strftime("%A %d %B %Y")
    lines = [f"DATE: {today}", "", "=== MACRO ==="]
    for name, data in macro_data.items():
        chg = data.get("change_pct", 0)
        lines.append(f"{name:15} {str(data.get('price','N/A')):>10}  {'UP' if chg>0 else 'DOWN'} {abs(chg):.2f}%")

    lines += ["", f"AUD/USD: {audusd:.4f}" if isinstance(audusd,(int,float)) else "AUD/USD: N/A"]
    lines += ["", "=== STOCKS FOR ANALYSIS ==="]

    for sector, tickers in SECTORS.items():
        lines.append(f"\n-- {sector} --")
        for ticker in tickers:
            d = stock_data.get(ticker, {})
            price = d.get("price", "N/A")
            chg   = d.get("change_pct", 0)
            hi52  = d.get("52w_high", "N/A")
            lo52  = d.get("52w_low", "N/A")
            pe    = d.get("pe_ratio")
            vs_high = round((price-hi52)/hi52*100,1) if isinstance(price,(int,float)) and isinstance(hi52,(int,float)) and hi52 else "N/A"
            lines.append(
                f"{ticker:6} ${str(price):>8}  chg:{chg:+.1f}%  52wH:{hi52}  52wL:{lo52}  "
                f"vs52wH:{vs_high}%  PE:{pe if pe else 'N/A'}"
            )

    lines += [
        "",
        "TASK: Analyse all stocks above.",
        "Pick the top 5 highest-conviction ideas for deep analysis (top5 array).",
        "For ALL remaining stocks provide a one-liner verdict in stock_analysis array.",
        "Classify each with a signal: MULTIBAGGER, DEEP VALUE, UNDERVALUED, WATCH, or AVOID.",
        "Be specific with entry prices. No apostrophes or contractions in any string value.",
    ]

    context = "\n".join(lines)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}]
    )
    raw = msg.content[0].text.strip()
    raw = raw.replace("```json","").replace("```","").strip()
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON found: {raw[:200]}")
    raw = raw[start:end]

    for attempt_fn in [
        lambda r: json.loads(r),
        lambda r: json.loads(re.sub(r'[\x00-\x1f\x7f]', ' ', r)),
        lambda r: json.loads(re.sub(r'[\x00-\x1f\x7f]', ' ', r).replace('\u2018',' ').replace('\u2019',' ').replace('\u201c','"').replace('\u201d','"')),
        lambda r: json.loads(re.sub(r'"[^"\\n]*"', lambda m: m.group(0).replace("'", " "), re.sub(r'[\x00-\x1f\x7f]', ' ', r))),
    ]:
        try:
            return attempt_fn(raw)
        except (json.JSONDecodeError, Exception):
            continue
    raise ValueError("All JSON parse attempts failed")

# ─────────────────────────────────────────────
# HTML BUILDER
# ─────────────────────────────────────────────

SIGNAL_COLORS = {
    "MULTIBAGGER": ("#39D353", "#0f2d18"),
    "DEEP VALUE":  ("#00D4FF", "#0a1f2e"),
    "UNDERVALUED": ("#E3B341", "#2a1f0a"),
    "WATCH":       ("#8B949E", "#1a1f24"),
    "AVOID":       ("#F85149", "#2d0f0e"),
}

def sig_badge(signal):
    col, bg = SIGNAL_COLORS.get(signal.upper(), ("#8B949E","#1a1f24"))
    return f'<span style="background:{bg};color:{col};border:1px solid {col};padding:2px 8px;border-radius:3px;font-size:10px;font-weight:700;letter-spacing:.05em">{signal}</span>'

def chg_col(chg):
    if isinstance(chg,(int,float)):
        return "#39D353" if chg>0 else ("#F85149" if chg<0 else "#8B949E")
    return "#8B949E"

def fmt_chg(chg):
    return f"{chg:+.2f}%" if isinstance(chg,(int,float)) else "N/A"

def fmt_price(p):
    return f"${p:,.2f}" if isinstance(p,(int,float)) else str(p)

def vs52_col(vs):
    if not isinstance(vs,(int,float)): return "#8B949E"
    return "#39D353" if vs>-10 else ("#E3B341" if vs>-25 else "#F85149")

def build_html(analysis, macro_data, stock_data, audusd, today_str):
    aud_str = f"{audusd:.4f}" if isinstance(audusd,(int,float)) else "N/A"

    # ── macro rows ──
    macro_rows = ""
    for name, data in macro_data.items():
        price = data.get("price","N/A")
        chg   = data.get("change_pct",0)
        hi52  = data.get("52w_high","N/A")
        arrow = "▲" if isinstance(chg,(int,float)) and chg>0 else "▼"
        macro_rows += f"""<tr>
          <td style="color:#F0F6FC;font-weight:600;padding:8px 12px">{name}</td>
          <td style="text-align:right;padding:8px 12px;color:#F0F6FC">{price}</td>
          <td style="text-align:right;padding:8px 12px;color:{chg_col(chg)}">{arrow} {fmt_chg(chg)}</td>
          <td style="text-align:right;padding:8px 12px;color:#8B949E">{hi52}</td>
        </tr>"""

    # ── top 5 cards ──
    top5_html = ""
    rank_labels = ["#1","#2","#3","#4","#5"]
    rank_cols   = ["#E3B341","#F0F6FC","#8B949E","#8B949E","#8B949E"]
    top5_tickers = set()

    for idea in analysis.get("top5",[]):
        rank    = idea.get("rank",1)
        ticker  = idea.get("ticker","")
        signal  = idea.get("signal","")
        top5_tickers.add(ticker)
        sig_col = SIGNAL_COLORS.get(signal.upper(),("#8B949E","#1a1f24"))[0]
        rc      = rank_cols[min(rank-1,4)]
        rl      = rank_labels[min(rank-1,4)]
        d       = stock_data.get(ticker,{})
        price   = d.get("price","N/A")
        chg     = d.get("change_pct",0)
        name    = d.get("name",ticker)

        top5_html += f"""
        <div style="background:#161B22;border:1px solid #30363D;border-radius:10px;padding:20px;margin-bottom:16px">
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;flex-wrap:wrap">
            <span style="color:{rc};font-size:22px;font-weight:900;min-width:36px">{rl}</span>
            <span style="color:#00D4FF;font-size:17px;font-weight:800">{ticker}</span>
            <span style="color:#8B949E;font-size:12px">{name}</span>
            {sig_badge(signal)}
            <span style="margin-left:auto;color:{chg_col(chg)};font-weight:700">{fmt_price(price)} &nbsp; {fmt_chg(chg)}</span>
          </div>
          <p style="color:#F0F6FC;line-height:1.7;margin-bottom:14px">{idea.get("thesis","")}</p>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px">
            <div style="background:#0D1117;border-radius:6px;padding:10px">
              <div style="color:#8B949E;font-size:10px;text-transform:uppercase;margin-bottom:3px">Entry</div>
              <div style="color:#39D353;font-weight:700">{idea.get("entry","N/A")}</div>
            </div>
            <div style="background:#0D1117;border-radius:6px;padding:10px">
              <div style="color:#8B949E;font-size:10px;text-transform:uppercase;margin-bottom:3px">12M Target</div>
              <div style="color:#E3B341;font-weight:700">{idea.get("target","N/A")}</div>
            </div>
            <div style="background:#0D1117;border-radius:6px;padding:10px">
              <div style="color:#8B949E;font-size:10px;text-transform:uppercase;margin-bottom:3px">Risk/Reward</div>
              <div style="color:#00D4FF;font-weight:700">{idea.get("risk_reward","N/A")}</div>
            </div>
            <div style="background:#0D1117;border-radius:6px;padding:10px">
              <div style="color:#8B949E;font-size:10px;text-transform:uppercase;margin-bottom:3px">Invalidation</div>
              <div style="color:#F85149;font-weight:700;font-size:11px">{idea.get("invalidation","N/A")}</div>
            </div>
          </div>
        </div>"""

    # ── build lookup from stock_analysis ──
    stock_analysis_map = {}
    for item in analysis.get("stock_analysis",[]):
        stock_analysis_map[item.get("ticker","")] = item

    # ── sector tabs content ──
    tab_buttons = ""
    tab_contents = ""
    all_sector_names = list(SECTORS.keys())

    for si, (sector, tickers) in enumerate(SECTORS.items()):
        active = "active" if si == 0 else ""
        tab_buttons += f'<button class="tab-btn {active}" onclick="showTab({si})" id="tab-btn-{si}">{sector}</button>\n'

        rows = ""
        for ticker in tickers:
            d       = stock_data.get(ticker,{})
            price   = d.get("price","N/A")
            chg     = d.get("change_pct",0)
            hi52    = d.get("52w_high","N/A")
            lo52    = d.get("52w_low","N/A")
            name    = d.get("name",ticker)
            vs_high = round((price-hi52)/hi52*100,1) if isinstance(price,(int,float)) and isinstance(hi52,(int,float)) and hi52 else "N/A"

            sa      = stock_analysis_map.get(ticker,{})
            signal  = sa.get("signal","WATCH")
            liner   = sa.get("one_liner","")
            entry   = sa.get("entry","")
            watch   = sa.get("watch_level","")
            is_top5 = ticker in top5_tickers

            top5_marker = '<span style="color:#E3B341;font-size:10px;font-weight:700;margin-left:6px">★ TOP 5</span>' if is_top5 else ""

            rows += f"""
            <tr style="border-bottom:1px solid #21262d" class="stock-row">
              <td style="padding:10px 12px;min-width:80px">
                <span style="color:#00D4FF;font-weight:700;font-size:14px">{ticker}</span>{top5_marker}
                <div style="color:#8B949E;font-size:11px;margin-top:2px">{name[:28]}</div>
              </td>
              <td style="padding:10px 12px;text-align:right">
                <div style="color:#F0F6FC;font-weight:600">{fmt_price(price)}</div>
                <div style="color:{chg_col(chg)};font-size:11px">{fmt_chg(chg)}</div>
              </td>
              <td style="padding:10px 12px;text-align:right">
                <div style="color:#8B949E;font-size:11px">{hi52}</div>
                <div style="color:{vs52_col(vs_high)};font-size:11px">{vs_high if vs_high=='N/A' else str(vs_high)+'%'}</div>
              </td>
              <td style="padding:10px 12px">{sig_badge(signal)}</td>
              <td style="padding:10px 12px;color:#F0F6FC;font-size:12px;max-width:300px">{liner}</td>
              <td style="padding:10px 12px;text-align:right">
                <div style="color:#39D353;font-size:11px">Entry: {entry}</div>
                <div style="color:#8B949E;font-size:11px">Watch: {watch}</div>
              </td>
            </tr>"""

        display = "block" if si == 0 else "none"
        tab_contents += f'<div class="tab-content" id="tab-{si}" style="display:{display}">\n<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse">{rows}</table></div>\n</div>\n'

    # ── full HTML ──
    vix_price   = macro_data.get("VIX",{}).get("price","N/A")
    yield_price = macro_data.get("10Y Yield",{}).get("price","N/A")
    sp_price    = macro_data.get("S&P 500",{}).get("price","N/A")
    sp_chg      = macro_data.get("S&P 500",{}).get("change_pct",0)
    ndq_price   = macro_data.get("Nasdaq",{}).get("price","N/A")
    ndq_chg     = macro_data.get("Nasdaq",{}).get("change_pct",0)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Market Intelligence // {today_str}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0D1117;color:#F0F6FC;font-family:'JetBrains Mono','Fira Code','Consolas',monospace;font-size:13px;line-height:1.6}}
  .container{{max-width:1200px;margin:0 auto;padding:24px 16px}}
  h2{{color:#E3B341;font-size:10px;text-transform:uppercase;letter-spacing:.12em;margin-bottom:14px;padding-bottom:6px;border-bottom:1px solid #30363D}}
  .card{{background:#161B22;border:1px solid #30363D;border-radius:10px;padding:20px;margin-bottom:20px}}
  .header{{padding-bottom:20px;margin-bottom:24px;border-bottom:1px solid #30363D}}
  .stat-strip{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin-bottom:24px}}
  .stat{{background:#161B22;border:1px solid #30363D;border-radius:8px;padding:12px 16px}}
  .stat-label{{color:#8B949E;font-size:10px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px}}
  .stat-value{{font-size:18px;font-weight:900}}
  .tab-bar{{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:16px;border-bottom:1px solid #30363D;padding-bottom:12px}}
  .tab-btn{{background:transparent;border:1px solid #30363D;color:#8B949E;padding:6px 14px;border-radius:6px;cursor:pointer;font-family:inherit;font-size:11px;font-weight:600;transition:all .15s}}
  .tab-btn:hover{{border-color:#00D4FF;color:#00D4FF}}
  .tab-btn.active{{background:#00D4FF;border-color:#00D4FF;color:#0D1117}}
  .stock-row:hover td{{background:#1C2128}}
  table td{{border-bottom:1px solid #21262d;vertical-align:middle}}
  .macro-table td{{padding:7px 12px;border-bottom:1px solid #21262d}}
  .macro-table tr:hover td{{background:#1C2128}}
  .grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
  @media(max-width:700px){{.grid-2{{grid-template-columns:1fr}}}}
  .footer{{border-top:1px solid #30363D;padding-top:14px;margin-top:28px;color:#8B949E;font-size:11px;text-align:center}}
</style>
</head>
<body>
<div class="container">

  <!-- HEADER -->
  <div class="header">
    <div style="font-size:clamp(16px,4vw,26px);font-weight:900;color:#00D4FF;letter-spacing:.04em">MARKET INTELLIGENCE</div>
    <div style="color:#8B949E;font-size:11px;margin-top:5px">{today_str} &nbsp;·&nbsp; Claude Sonnet 4.6 &nbsp;·&nbsp; yFinance &nbsp;·&nbsp; 28 stocks across 6 sectors</div>
  </div>

  <!-- STAT STRIP -->
  <div class="stat-strip">
    <div class="stat"><div class="stat-label">S&amp;P 500</div><div class="stat-value" style="color:{chg_col(sp_chg)}">{sp_price}</div><div style="color:{chg_col(sp_chg)};font-size:11px">{fmt_chg(sp_chg)}</div></div>
    <div class="stat"><div class="stat-label">Nasdaq</div><div class="stat-value" style="color:{chg_col(ndq_chg)}">{ndq_price}</div><div style="color:{chg_col(ndq_chg)};font-size:11px">{fmt_chg(ndq_chg)}</div></div>
    <div class="stat"><div class="stat-label">VIX</div><div class="stat-value" style="color:#F0F6FC">{vix_price}</div></div>
    <div class="stat"><div class="stat-label">10Y Yield</div><div class="stat-value" style="color:#F0F6FC">{yield_price}</div></div>
    <div class="stat"><div class="stat-label">AUD / USD</div><div class="stat-value" style="color:#E3B341">{aud_str}</div></div>
  </div>

  <!-- REGIME + MACRO -->
  <div class="grid-2">
    <div class="card">
      <h2>Macro Regime</h2>
      <p style="color:#F0F6FC;line-height:1.8;margin-bottom:14px">{analysis.get("regime","N/A")}</p>
      <h2 style="margin-top:16px">Sector Rotation</h2>
      <p style="color:#F0F6FC;line-height:1.8;margin-bottom:14px">{analysis.get("sector_rotation","N/A")}</p>
      <h2 style="margin-top:16px">Key Risk</h2>
      <p style="color:#F85149;line-height:1.8">{analysis.get("risks","N/A")}</p>
    </div>
    <div class="card">
      <h2>Macro Data</h2>
      <table class="macro-table" style="width:100%;border-collapse:collapse">
        <thead><tr>
          <th style="color:#8B949E;font-size:10px;text-transform:uppercase;padding:6px 12px;text-align:left;border-bottom:1px solid #30363D">Instrument</th>
          <th style="color:#8B949E;font-size:10px;text-transform:uppercase;padding:6px 12px;text-align:right;border-bottom:1px solid #30363D">Price</th>
          <th style="color:#8B949E;font-size:10px;text-transform:uppercase;padding:6px 12px;text-align:right;border-bottom:1px solid #30363D">Change</th>
          <th style="color:#8B949E;font-size:10px;text-transform:uppercase;padding:6px 12px;text-align:right;border-bottom:1px solid #30363D">52W High</th>
        </tr></thead>
        <tbody>{macro_rows}</tbody>
      </table>
    </div>
  </div>

  <!-- TOP 5 -->
  <div class="card">
    <h2>Top 5 High-Conviction Ideas</h2>
    {top5_html if top5_html else '<p style="color:#8B949E">Analysis unavailable.</p>'}
  </div>

  <!-- SECTOR TABS -->
  <div class="card">
    <h2>All Stocks by Sector</h2>
    <div class="tab-bar">
      {tab_buttons}
    </div>
    {tab_contents}
  </div>

  <div class="footer">
    Updated {today_str} &nbsp;·&nbsp; Powered by Claude Sonnet 4.6 + yFinance &nbsp;·&nbsp; For informational purposes only
  </div>

</div>
<script>
function showTab(idx) {{
  document.querySelectorAll('.tab-content').forEach(function(el,i){{el.style.display=i===idx?'block':'none'}});
  document.querySelectorAll('.tab-btn').forEach(function(el,i){{el.classList.toggle('active',i===idx)}});
}}
</script>
</body>
</html>"""
    return html

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    today_str = datetime.date.today().strftime("%d %b %Y")
    print(f"\n{'─'*50}")
    print(f"  MARKET INTELLIGENCE  //  {today_str}")
    print(f"{'─'*50}")

    if ANTHROPIC_API_KEY == "YOUR_API_KEY_HERE":
        print("\nERROR: Set your ANTHROPIC_API_KEY.")
        sys.exit(1)

    print(f"\n[1/3] Fetching {len(ALL_STOCKS)} stocks...")
    stock_data = fetch_price_data(ALL_STOCKS)
    print(f"      {sum(1 for v in stock_data.values() if v.get('price') != 'N/A')}/{len(ALL_STOCKS)} fetched successfully")

    print("[2/3] Fetching macro data...")
    macro_raw  = fetch_price_data(list(MACRO.values()))
    macro_data = {name: macro_raw.get(ticker,{}) for name, ticker in MACRO.items()}
    audusd_val = macro_raw.get("AUDUSD=X",{}).get("price",0.65)
    audusd     = audusd_val if isinstance(audusd_val,(int,float)) else 0.65

    print("[3/3] Calling Claude for analysis...")
    try:
        analysis = get_claude_analysis(stock_data, macro_data, audusd)
        top5_count = len(analysis.get("top5",[]))
        all_count  = len(analysis.get("stock_analysis",[]))
        print(f"      Analysis complete — {top5_count} top picks, {all_count} one-liners")
    except Exception as e:
        print(f"      Claude error: {e}")
        analysis = {
            "regime": f"Analysis unavailable: {str(e)[:80]}",
            "sector_rotation": "N/A", "risks": "N/A",
            "top5": [], "stock_analysis": []
        }

    print("\nBuilding HTML...")
    html = build_html(analysis, macro_data, stock_data, audusd, today_str)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Saved: {OUTPUT_HTML}")
    print(f"\n{'─'*50}\n")

if __name__ == "__main__":
    main()
