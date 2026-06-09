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

SECTORS = {
    "AI Infrastructure": ["NVDA", "ALAB", "POWL", "MOD", "VRT", "GFS"],
    "Semiconductors":    ["MRVL", "MU", "AMD", "AVGO", "CRDO", "ARM"],
    "Cybersecurity":     ["S", "ZS", "AXON"],
    "Software & AI":     ["NOW", "ADBE", "CRM", "META", "GOOG", "BIDU"],
    "Pharma & Biotech":  ["ISRG", "REGN", "RXRX"],
    "Other":             ["CCJ", "JEDI", "CWAN", "GRAB"],
}

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
# DATA FETCHING — price + fundamentals
# ─────────────────────────────────────────────

def safe_round(val, digits=2):
    try:
        return round(float(val), digits) if val is not None else "N/A"
    except:
        return "N/A"

def fmt_millions(val):
    try:
        v = float(val)
        if abs(v) >= 1e9:  return f"${v/1e9:.1f}B"
        if abs(v) >= 1e6:  return f"${v/1e6:.0f}M"
        return f"${v:.0f}"
    except:
        return "N/A"

def fetch_price_data(tickers):
    """Fetch price-only data for macro instruments."""
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
                results[ticker] = {
                    "price":      safe_round(price, 3),
                    "change_pct": safe_round(chg, 2),
                    "52w_high":   safe_round(hi52, 3),
                    "52w_low":    safe_round(lo52, 3),
                }
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(2)
                else:
                    results[ticker] = {"price": "N/A", "change_pct": 0}
    return results

def fetch_stock_full(ticker):
    """Fetch full price + fundamentals for a stock ticker."""
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

            # ── fundamentals from .info ──
            result = {
                # identity
                "name":              inf.get("shortName") or inf.get("longName") or ticker,
                "sector":            inf.get("sector",""),
                "industry":          inf.get("industry",""),
                # price
                "price":             safe_round(price, 3),
                "change_pct":        safe_round(chg, 2),
                "day_high":          safe_round(fi.day_high, 3),
                "day_low":           safe_round(fi.day_low, 3),
                "52w_high":          safe_round(hi52, 3),
                "52w_low":           safe_round(lo52, 3),
                # valuation
                "mkt_cap":           fmt_millions(inf.get("marketCap")),
                "pe_trailing":       safe_round(inf.get("trailingPE")),
                "pe_forward":        safe_round(inf.get("forwardPE")),
                "peg_ratio":         safe_round(inf.get("pegRatio")),
                "ps_ratio":          safe_round(inf.get("priceToSalesTrailing12Months")),
                "pb_ratio":          safe_round(inf.get("priceToBook")),
                "ev_ebitda":         safe_round(inf.get("enterpriseToEbitda")),
                # growth & margins
                "revenue_growth":    safe_round(inf.get("revenueGrowth"), 3),
                "earnings_growth":   safe_round(inf.get("earningsGrowth"), 3),
                "gross_margin":      safe_round(inf.get("grossMargins"), 3),
                "operating_margin":  safe_round(inf.get("operatingMargins"), 3),
                "profit_margin":     safe_round(inf.get("profitMargins"), 3),
                # balance sheet
                "total_cash":        fmt_millions(inf.get("totalCash")),
                "total_debt":        fmt_millions(inf.get("totalDebt")),
                "fcf":               fmt_millions(inf.get("freeCashflow")),
                "roe":               safe_round(inf.get("returnOnEquity"), 3),
                "debt_to_equity":    safe_round(inf.get("debtToEquity")),
                # analyst
                "target_mean":       safe_round(inf.get("targetMeanPrice")),
                "target_high":       safe_round(inf.get("targetHighPrice")),
                "recommendation":    inf.get("recommendationKey",""),
                "analyst_count":     inf.get("numberOfAnalystOpinions"),
                # earnings
                "next_earnings":     str(inf.get("earningsTimestamp","")) if inf.get("earningsTimestamp") else "N/A",
            }
            return result

        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                print(f"      WARNING: Could not fetch {ticker}: {e}")
                return {"name": ticker, "price": "N/A", "change_pct": 0}
    return {"name": ticker, "price": "N/A", "change_pct": 0}

def fetch_all_stocks(tickers):
    print(f"      Fetching {len(tickers)} stocks with fundamentals...")
    results = {}
    for i, ticker in enumerate(tickers):
        results[ticker] = fetch_stock_full(ticker)
        if (i+1) % 5 == 0:
            print(f"      {i+1}/{len(tickers)} done...")
    return results

# ─────────────────────────────────────────────
# CONTEXT BUILDER
# ─────────────────────────────────────────────

def build_context(stock_data, macro_data, audusd):
    today = datetime.date.today().strftime("%A %d %B %Y")
    lines = [f"DATE: {today}", "", "=== MACRO ==="]
    for name, data in macro_data.items():
        chg = data.get("change_pct", 0)
        lines.append(
            f"{name:15} {str(data.get('price','N/A')):>10}  "
            f"{'UP' if isinstance(chg,(int,float)) and chg>0 else 'DOWN'} {abs(chg) if isinstance(chg,(int,float)) else 0:.2f}%"
        )
    aud = f"{audusd:.4f}" if isinstance(audusd,(int,float)) else "N/A"
    lines += ["", f"AUD/USD: {aud}", "", "=== STOCKS (with fundamentals) ==="]

    for sector, tickers in SECTORS.items():
        lines.append(f"\n-- {sector} --")
        for ticker in tickers:
            d = stock_data.get(ticker, {})
            price  = d.get("price","N/A")
            chg    = d.get("change_pct",0)
            hi52   = d.get("52w_high","N/A")
            lo52   = d.get("52w_low","N/A")
            vs_high = (
                f"{round((price-hi52)/hi52*100,1)}%"
                if isinstance(price,(int,float)) and isinstance(hi52,(int,float)) and hi52
                else "N/A"
            )
            lines.append(
                f"\n{ticker} ({d.get('name',ticker)}) | {d.get('industry','')}"
            )
            lines.append(
                f"  Price: ${price}  Chg: {chg:+.1f}%  52wH: {hi52}  52wL: {lo52}  vs52wH: {vs_high}"
            )
            lines.append(
                f"  Mkt Cap: {d.get('mkt_cap','N/A')}  "
                f"P/E fwd: {d.get('pe_forward','N/A')}  "
                f"PEG: {d.get('peg_ratio','N/A')}  "
                f"EV/EBITDA: {d.get('ev_ebitda','N/A')}  "
                f"P/S: {d.get('ps_ratio','N/A')}"
            )
            lines.append(
                f"  Rev growth: {d.get('revenue_growth','N/A')}  "
                f"Gross margin: {d.get('gross_margin','N/A')}  "
                f"Op margin: {d.get('operating_margin','N/A')}  "
                f"FCF: {d.get('fcf','N/A')}"
            )
            lines.append(
                f"  Cash: {d.get('total_cash','N/A')}  "
                f"Debt: {d.get('total_debt','N/A')}  "
                f"D/E: {d.get('debt_to_equity','N/A')}  "
                f"ROE: {d.get('roe','N/A')}"
            )
            lines.append(
                f"  Analyst target (mean/high): {d.get('target_mean','N/A')} / {d.get('target_high','N/A')}  "
                f"Rec: {d.get('recommendation','N/A')}  "
                f"Next earnings: {d.get('next_earnings','N/A')}"
            )

    lines += [
        "",
        "TASK:",
        "1. Pick the top 5 highest-conviction ideas based on fundamentals + price position.",
        "2. Provide a one-liner signal for ALL remaining stocks.",
        "3. Classify each: MULTIBAGGER, DEEP VALUE, UNDERVALUED, WATCH, or AVOID.",
        "4. Reference specific numbers from the fundamentals in your verdicts.",
        "5. No apostrophes or contractions in any JSON string value.",
        "6. Every stock in stock_analysis must have a non-empty one_liner, entry, and watch_level.",
    ]
    return "\n".join(lines)

# ─────────────────────────────────────────────
# CLAUDE ANALYSIS WITH WEB SEARCH
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are a sharp independent market analyst producing a daily market intelligence briefing. No disclaimers. No mention of any personal portfolio. Direct, blunt, high-conviction. Flag rationalisations.

MACRO FRAMEWORK: Iran/Hormuz disruption central thesis. Stagflation regime: sticky CPI 3.8%, Fed on hold, RBA hiking. AI bubble repricing risk Q4 2026 to Q2 2027 (25-40% on AI names). Gold supercycle. Structural copper deficit. Nuclear renaissance. AI infrastructure arms race.

SIGNAL DEFINITIONS:
- MULTIBAGGER: asymmetric upside, early in a structural trend, 3-5x potential over 2-3 years
- DEEP VALUE: significant discount to intrinsic value, catalyst needed to unlock
- UNDERVALUED: solid business below fair value, lower risk than multibagger
- WATCH: interesting but wait for better entry or catalyst confirmation
- AVOID: deteriorating fundamentals or structurally challenged

PROCESS:
1. Analyse the fundamentals provided for each stock — P/E, FCF, revenue growth, margins, debt
2. Identify mispricing, structural trends, and risk/reward asymmetry
3. Be specific — reference actual numbers from the data provided
4. Cross-reference price position (vs 52W high/low) with fundamental quality

CRITICAL OUTPUT RULES:
- Respond ONLY with a single valid JSON object. No text before or after.
- No markdown fences. No preamble.
- Do NOT use apostrophes or contractions. Write "does not" not "doesn't".
- Do NOT use single quotes anywhere in JSON string values.

JSON STRUCTURE:
{
  "regime": "3 sentence macro regime snapshot — reference actual current data points",
  "sector_rotation": "2 sentences on where institutional money is moving right now and why",
  "risks": "2 sentences on the single biggest near-term risk to risk assets",
  "news_summary": "2-3 sentences on the most important market-moving news found today",
  "top5": [
    {
      "rank": 1,
      "ticker": "XXX",
      "signal": "MULTIBAGGER",
      "thesis": "4-5 sentences: fundamental case + news catalyst + what the market is missing + why now",
      "entry": "specific price or range",
      "target": "12-month price target with brief reasoning",
      "invalidation": "specific price level or event that breaks the thesis",
      "risk_reward": "e.g. 3.5:1",
      "key_metric": "the single most important fundamental metric supporting this call"
    }
  ],
  "stock_analysis": [
    {
      "ticker": "XXX",
      "signal": "MULTIBAGGER",
      "one_liner": "one sentence verdict referencing a specific fundamental or news item",
      "entry": "specific price or range",
      "watch_level": "key price level to watch"
    }
  ]
}"""

def parse_json_robust(raw):
    # Strip all markdown fences including with leading whitespace
    while "```" in raw:
        raw = raw.replace("```json", "").replace("```", "")
    raw = raw.strip()

    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in: " + raw[:200])
    raw = raw[start:end]

    errors = []

    # Attempt 1: direct
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        errors.append("attempt1: " + str(e))

    # Attempt 1b: truncation recovery — if JSON was cut off, close open arrays/objects
    try:
        # Find the last complete top-level field by truncating at last valid comma or closing brace
        # Strategy: find last complete "}" in top5 or stock_analysis and close the structure
        truncated = raw
        # Remove trailing incomplete content after last complete item
        last_good = max(truncated.rfind('}],'), truncated.rfind('}]'), truncated.rfind(']}'))
        if last_good > len(truncated) // 2:
            truncated = truncated[:last_good+3] if truncated[last_good:last_good+3] == '}],' else truncated[:last_good+2]
            # Close the outer object
            truncated = truncated.rstrip(',').rstrip() + '}}'
            if not truncated.endswith('}}'):
                truncated += '}'
            return json.loads(truncated)
    except Exception:
        pass

    # Attempt 2: strip control characters
    c2 = re.sub(r"[-]", " ", raw)
    try:
        return json.loads(c2)
    except json.JSONDecodeError as e:
        errors.append("attempt2: " + str(e))

    # Attempt 3: fix fancy quotes + control chars
    c3 = c2
    c3 = c3.replace("‘", " ").replace("’", " ")
    c3 = c3.replace("“", chr(34)).replace("”", chr(34))
    try:
        return json.loads(c3)
    except json.JSONDecodeError as e:
        errors.append("attempt3: " + str(e))

    # Attempt 4: remove apostrophes from string values
    def drop_apos(m):
        return m.group(0).replace("'", " ")
    c4 = re.sub(r'"[^"]*"', drop_apos, c3)
    try:
        return json.loads(c4)
    except json.JSONDecodeError as e:
        errors.append("attempt4: " + str(e))

    # Attempt 5: remove ALL non-printable ASCII from inside string values
    def scrub(m):
        s = m.group(0)
        s = re.sub(r"[^ -~]", " ", s)
        s = s.replace("'", " ")
        return s
    c5 = re.sub(r'"[^"]*"', scrub, c3)
    try:
        return json.loads(c5)
    except json.JSONDecodeError as e:
        errors.append("attempt5: " + str(e))

    raise ValueError("All JSON parse attempts failed:\n" + "\n".join(errors))

def get_claude_analysis(stock_data, macro_data, audusd):
    context = build_context(stock_data, macro_data, audusd)
    client  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Single call — Claude analyses fundamentals directly, no web search tool
    # Web search was causing silent failures in the agentic loop
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}],
    )

    text_parts = [
        block.text for block in msg.content
        if getattr(block, "type", "") == "text" and block.text.strip()
    ]
    if not text_parts:
        print(f"      stop_reason: {msg.stop_reason}")
        print(f"      content types: {[getattr(b,'type','?') for b in msg.content]}")
        raise ValueError("No text in Claude response")

    raw = " ".join(text_parts)
    print(f"      Raw response length: {len(raw)} chars")
    print(f"      First 200 chars: {raw[:200]}")
    return parse_json_robust(raw)

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
    return (
        f'<span style="background:{bg};color:{col};border:1px solid {col};'
        f'padding:2px 8px;border-radius:3px;font-size:10px;font-weight:700;'
        f'letter-spacing:.05em;white-space:nowrap">{signal}</span>'
    )

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
    aud_str    = f"{audusd:.4f}" if isinstance(audusd,(int,float)) else "N/A"
    sp_data    = macro_data.get("S&P 500",{})
    ndq_data   = macro_data.get("Nasdaq",{})
    vix_price  = macro_data.get("VIX",{}).get("price","N/A")
    yld_price  = macro_data.get("10Y Yield",{}).get("price","N/A")
    sp_price   = sp_data.get("price","N/A")
    sp_chg     = sp_data.get("change_pct",0)
    ndq_price  = ndq_data.get("price","N/A")
    ndq_chg    = ndq_data.get("change_pct",0)

    # ── macro table rows ──
    macro_rows = ""
    for name, data in macro_data.items():
        price = data.get("price","N/A")
        chg   = data.get("change_pct",0)
        hi52  = data.get("52w_high","N/A")
        arrow = "▲" if isinstance(chg,(int,float)) and chg>0 else "▼"
        macro_rows += (
            f"<tr>"
            f"<td style='color:#F0F6FC;font-weight:600;padding:8px 12px'>{name}</td>"
            f"<td style='text-align:right;padding:8px 12px;color:#F0F6FC'>{price}</td>"
            f"<td style='text-align:right;padding:8px 12px;color:{chg_col(chg)}'>{arrow} {fmt_chg(chg)}</td>"
            f"<td style='text-align:right;padding:8px 12px;color:#8B949E'>{hi52}</td>"
            f"</tr>"
        )

    # ── top 5 cards ──
    top5_tickers = set()
    top5_html    = ""
    rank_cols    = ["#E3B341","#F0F6FC","#8B949E","#8B949E","#8B949E"]

    for idea in analysis.get("top5",[]):
        rank   = idea.get("rank",1)
        ticker = idea.get("ticker","")
        signal = idea.get("signal","")
        top5_tickers.add(ticker)
        d      = stock_data.get(ticker,{})
        price  = d.get("price","N/A")
        chg    = d.get("change_pct",0)
        name   = d.get("name",ticker)
        rc     = rank_cols[min(rank-1,4)]
        sig_col = SIGNAL_COLORS.get(signal.upper(),("#8B949E","#1a1f24"))[0]

        top5_html += f"""
        <div style="background:#161B22;border:1px solid #30363D;border-radius:10px;padding:22px;margin-bottom:16px">
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;flex-wrap:wrap">
            <span style="color:{rc};font-size:24px;font-weight:900">#{rank}</span>
            <span style="color:#00D4FF;font-size:18px;font-weight:800">{ticker}</span>
            <span style="color:#8B949E;font-size:12px">{name}</span>
            {sig_badge(signal)}
            <span style="margin-left:auto;color:{chg_col(chg)};font-weight:700;font-size:14px">{fmt_price(price)} &nbsp; {fmt_chg(chg)}</span>
          </div>
          <p style="color:#F0F6FC;line-height:1.8;margin-bottom:16px;font-size:13px">{idea.get("thesis","")}</p>
          <div style="background:#0D1117;border-radius:4px;padding:10px;margin-bottom:14px;color:{sig_col};font-size:12px;font-weight:600">
            Key metric: {idea.get("key_metric","N/A")}
          </div>
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
              <div style="color:#8B949E;font-size:10px;text-transform:uppercase;margin-bottom:3px">Risk / Reward</div>
              <div style="color:#00D4FF;font-weight:700">{idea.get("risk_reward","N/A")}</div>
            </div>
            <div style="background:#0D1117;border-radius:6px;padding:10px">
              <div style="color:#8B949E;font-size:10px;text-transform:uppercase;margin-bottom:3px">Invalidation</div>
              <div style="color:#F85149;font-weight:700;font-size:11px">{idea.get("invalidation","N/A")}</div>
            </div>
          </div>
        </div>"""

    # ── stock analysis lookup ──
    sa_map = {item.get("ticker",""): item for item in analysis.get("stock_analysis",[])}

    # ── sector tabs ──
    tab_buttons  = ""
    tab_contents = ""

    for si, (sector, tickers) in enumerate(SECTORS.items()):
        active = "active" if si==0 else ""
        tab_buttons += f'<button class="tab-btn {active}" onclick="showTab({si})">{sector}</button>\n'

        rows = ""
        for ticker in tickers:
            d      = stock_data.get(ticker,{})
            price  = d.get("price","N/A")
            chg    = d.get("change_pct",0)
            hi52   = d.get("52w_high","N/A")
            lo52   = d.get("52w_low","N/A")
            name   = d.get("name",ticker)
            pe     = d.get("pe_forward","N/A")
            rev_g  = d.get("revenue_growth","N/A")
            fcf    = d.get("fcf","N/A")
            target = d.get("target_mean","N/A")
            rec    = d.get("recommendation","")
            vs_high = (
                round((price-hi52)/hi52*100,1)
                if isinstance(price,(int,float)) and isinstance(hi52,(int,float)) and hi52
                else "N/A"
            )
            sa      = sa_map.get(ticker,{})
            signal  = sa.get("signal","WATCH")
            liner   = sa.get("one_liner","")
            entry   = sa.get("entry","")
            watch   = sa.get("watch_level","")
            is_top5 = ticker in top5_tickers

            star = '<span style="color:#E3B341;font-size:10px;font-weight:700;margin-left:5px">★ TOP 5</span>' if is_top5 else ""

            rows += f"""<tr style="border-bottom:1px solid #21262d" class="stock-row">
              <td style="padding:10px 12px;min-width:90px">
                <span style="color:#00D4FF;font-weight:700;font-size:14px">{ticker}</span>{star}
                <div style="color:#8B949E;font-size:11px;margin-top:1px">{name[:26]}</div>
              </td>
              <td style="padding:10px 12px;text-align:right;white-space:nowrap">
                <div style="color:#F0F6FC;font-weight:600">{fmt_price(price)}</div>
                <div style="color:{chg_col(chg)};font-size:11px">{fmt_chg(chg)}</div>
              </td>
              <td style="padding:10px 12px;text-align:right;white-space:nowrap">
                <div style="color:#8B949E;font-size:11px">H: {hi52}</div>
                <div style="color:{vs52_col(vs_high)};font-size:11px">{vs_high if vs_high=='N/A' else str(vs_high)+'%'}</div>
              </td>
              <td style="padding:10px 12px;text-align:right;white-space:nowrap">
                <div style="color:#8B949E;font-size:11px">P/E: {pe}</div>
                <div style="color:#8B949E;font-size:11px">RevG: {rev_g}</div>
              </td>
              <td style="padding:10px 12px;text-align:right;white-space:nowrap">
                <div style="color:#8B949E;font-size:11px">FCF: {fcf}</div>
                <div style="color:#8B949E;font-size:11px">Tgt: ${target}</div>
              </td>
              <td style="padding:10px 12px">{sig_badge(signal)}</td>
              <td style="padding:10px 12px;color:#F0F6FC;font-size:12px;min-width:200px;max-width:320px">{liner}</td>
              <td style="padding:10px 12px;text-align:right;white-space:nowrap">
                <div style="color:#39D353;font-size:11px">Entry: {entry}</div>
                <div style="color:#8B949E;font-size:11px">Watch: {watch}</div>
              </td>
            </tr>"""

        display = "block" if si==0 else "none"
        tab_contents += (
            f'<div class="tab-content" id="tab-{si}" style="display:{display}">'
            f'<div style="overflow-x:auto">'
            f'<table style="width:100%;border-collapse:collapse">'
            f'<thead><tr>'
            f'<th style="{th()}">Stock</th>'
            f'<th style="{th(right=True)}">Price</th>'
            f'<th style="{th(right=True)}">52W</th>'
            f'<th style="{th(right=True)}">P/E / RevG</th>'
            f'<th style="{th(right=True)}">FCF / Target</th>'
            f'<th style="{th()}">Signal</th>'
            f'<th style="{th()}">Verdict</th>'
            f'<th style="{th(right=True)}">Levels</th>'
            f'</tr></thead>'
            f'<tbody>{rows}</tbody>'
            f'</table></div></div>\n'
        )

    news = analysis.get("news_summary","")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>Market Intelligence // {today_str}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0D1117;color:#F0F6FC;font-family:'JetBrains Mono','Fira Code','Consolas',monospace;font-size:13px;line-height:1.6}}
  .container{{max-width:1300px;margin:0 auto;padding:24px 16px}}
  h2{{color:#E3B341;font-size:10px;text-transform:uppercase;letter-spacing:.12em;margin-bottom:14px;padding-bottom:6px;border-bottom:1px solid #30363D}}
  .card{{background:#161B22;border:1px solid #30363D;border-radius:10px;padding:20px;margin-bottom:20px}}
  .stat-strip{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin-bottom:22px}}
  .stat{{background:#161B22;border:1px solid #30363D;border-radius:8px;padding:12px 16px}}
  .stat-label{{color:#8B949E;font-size:10px;text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px}}
  .stat-value{{font-size:18px;font-weight:900}}
  .tab-bar{{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:16px;border-bottom:1px solid #30363D;padding-bottom:12px}}
  .tab-btn{{background:transparent;border:1px solid #30363D;color:#8B949E;padding:6px 14px;border-radius:6px;cursor:pointer;font-family:inherit;font-size:11px;font-weight:600;transition:all .15s}}
  .tab-btn:hover{{border-color:#00D4FF;color:#00D4FF}}
  .tab-btn.active{{background:#00D4FF;border-color:#00D4FF;color:#0D1117}}
  .stock-row:hover td{{background:#1C2128}}
  .grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
  @media(max-width:750px){{.grid-2{{grid-template-columns:1fr}}}}
  .footer{{border-top:1px solid #30363D;padding-top:14px;margin-top:28px;color:#8B949E;font-size:11px;text-align:center}}
  .news-box{{background:#0f1f30;border-left:3px solid #E3B341;border-radius:0 6px 6px 0;padding:12px 16px;margin-bottom:18px;color:#F0F6FC;font-size:12px;line-height:1.8}}
</style>
</head>
<body>
<div class="container">

  <div style="padding-bottom:20px;margin-bottom:22px;border-bottom:1px solid #30363D">
    <div style="font-size:clamp(16px,4vw,26px);font-weight:900;color:#00D4FF;letter-spacing:.04em">MARKET INTELLIGENCE</div>
    <div style="color:#8B949E;font-size:11px;margin-top:5px">{today_str} &nbsp;·&nbsp; Claude Sonnet 4.6 &nbsp;·&nbsp; yFinance Fundamentals &nbsp;·&nbsp; {len(ALL_STOCKS)} stocks / 6 sectors</div>
  </div>

  <div class="stat-strip">
    <div class="stat"><div class="stat-label">S&amp;P 500</div><div class="stat-value" style="color:{chg_col(sp_chg)}">{sp_price}</div><div style="color:{chg_col(sp_chg)};font-size:11px">{fmt_chg(sp_chg)}</div></div>
    <div class="stat"><div class="stat-label">Nasdaq</div><div class="stat-value" style="color:{chg_col(ndq_chg)}">{ndq_price}</div><div style="color:{chg_col(ndq_chg)};font-size:11px">{fmt_chg(ndq_chg)}</div></div>
    <div class="stat"><div class="stat-label">VIX</div><div class="stat-value" style="color:#F0F6FC">{vix_price}</div></div>
    <div class="stat"><div class="stat-label">10Y Yield</div><div class="stat-value" style="color:#F0F6FC">{yld_price}</div></div>
    <div class="stat"><div class="stat-label">AUD / USD</div><div class="stat-value" style="color:#E3B341">{aud_str}</div></div>
  </div>

  {"<div class='news-box'><span style='color:#E3B341;font-weight:700'>TODAY IN MARKETS &nbsp;</span>" + news + "</div>" if news else ""}

  <div class="grid-2">
    <div class="card">
      <h2>Macro Regime</h2>
      <p style="color:#F0F6FC;line-height:1.8;margin-bottom:16px">{analysis.get("regime","N/A")}</p>
      <h2 style="margin-top:4px">Sector Rotation</h2>
      <p style="color:#F0F6FC;line-height:1.8;margin-bottom:16px">{analysis.get("sector_rotation","N/A")}</p>
      <h2 style="margin-top:4px">Key Risk</h2>
      <p style="color:#F85149;line-height:1.8">{analysis.get("risks","N/A")}</p>
    </div>
    <div class="card">
      <h2>Macro Data</h2>
      <table style="width:100%;border-collapse:collapse">
        <thead><tr>
          <th style="{th()}">Instrument</th>
          <th style="{th(right=True)}">Price</th>
          <th style="{th(right=True)}">Change</th>
          <th style="{th(right=True)}">52W High</th>
        </tr></thead>
        <tbody>{macro_rows}</tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <h2>Top 5 High-Conviction Ideas — Fundamental + News Driven</h2>
    {top5_html if top5_html else '<p style="color:#8B949E">Analysis unavailable.</p>'}
  </div>

  <div class="card">
    <h2>All Stocks by Sector</h2>
    <div class="tab-bar">{tab_buttons}</div>
    {tab_contents}
  </div>

  <div class="footer">
    Updated {today_str} &nbsp;·&nbsp; Claude Sonnet 4.6 with web search &nbsp;·&nbsp; Fundamentals via yFinance &nbsp;·&nbsp; For informational purposes only
  </div>

</div>
<script>
function showTab(idx){{
  document.querySelectorAll('.tab-content').forEach(function(el,i){{el.style.display=i===idx?'block':'none'}});
  document.querySelectorAll('.tab-btn').forEach(function(el,i){{el.classList.toggle('active',i===idx)}});
}}
</script>
</body>
</html>"""
    return html

def th(right=False):
    base = "background:#0D1117;color:#8B949E;font-size:10px;text-transform:uppercase;letter-spacing:.05em;padding:8px 12px;border-bottom:1px solid #30363D"
    return base + (";text-align:right" if right else ";text-align:left")

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

    print(f"\n[1/3] Fetching {len(ALL_STOCKS)} stocks with fundamentals...")
    stock_data = fetch_all_stocks(ALL_STOCKS)
    ok = sum(1 for v in stock_data.values() if v.get("price") != "N/A")
    print(f"      {ok}/{len(ALL_STOCKS)} fetched successfully")

    print("[2/3] Fetching macro data...")
    macro_raw  = fetch_price_data(list(MACRO.values()))
    macro_data = {name: macro_raw.get(ticker,{}) for name, ticker in MACRO.items()}
    audusd_val = macro_raw.get("AUDUSD=X",{}).get("price", 0.65)
    audusd     = audusd_val if isinstance(audusd_val,(int,float)) else 0.65

    print("[3/3] Calling Claude for analysis...")
    try:
        analysis = get_claude_analysis(stock_data, macro_data, audusd)
        print(f"      Complete — {len(analysis.get('top5',[]))} top picks, {len(analysis.get('stock_analysis',[]))} one-liners")
    except Exception as e:
        import traceback
        print(f"\n======= CLAUDE ERROR =======")
        print(traceback.format_exc())
        print(f"======= END ERROR =======\n")
        analysis = {
            "regime":"Analysis unavailable.", "sector_rotation":"N/A",
            "risks":"N/A", "news_summary":"N/A", "top5":[], "stock_analysis":[]
        }

    print("\nBuilding HTML...")
    html = build_html(analysis, macro_data, stock_data, audusd, today_str)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Saved: {OUTPUT_HTML}")

    # Write _headers file — tells GitHub Pages CDN never to cache index.html
    headers_content = """/index.html
  Cache-Control: no-cache, no-store, must-revalidate
  Pragma: no-cache
  Expires: 0

/
  Cache-Control: no-cache, no-store, must-revalidate
  Pragma: no-cache
  Expires: 0
"""
    with open("_headers", "w") as f:
        f.write(headers_content)
    print(f"  Saved: _headers")
    print(f"\n{'─'*50}\n")

if __name__ == "__main__":
    main()
