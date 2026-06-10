"""
market_brief.py  —  Daily AI market intelligence + evolving thesis memory
Requirements:  pip install yfinance anthropic
"""

import os, sys, json, re, time, datetime
import yfinance as yf
import anthropic

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_API_KEY_HERE")
OUTPUT_HTML   = "index.html"
THESIS_FILE   = "thesis.json"
HEADERS_FILE  = "_headers"

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

# ── Default thesis — overwritten by thesis.json after first run ──
DEFAULT_THESIS = {
    "last_updated": "",
    "pillars": {
        "hormuz_disruption": {
            "label": "Iran / Hormuz Disruption",
            "status": "INTACT",
            "confidence": 8,
            "last_note": "Core thesis — Hormuz disruption driving oil, gold, and insurance repricing globally."
        },
        "stagflation_regime": {
            "label": "Stagflation Regime",
            "status": "INTACT",
            "confidence": 7,
            "last_note": "CPI sticky at 3.8%, Fed on hold, RBA hiking — compressing equity multiples."
        },
        "ai_bubble_risk": {
            "label": "AI Bubble Risk Q4 2026",
            "status": "WATCH",
            "confidence": 6,
            "last_note": "Capex-to-revenue gap widening at hyperscalers. Trigger window Q4 2026 to Q2 2027."
        },
        "gold_supercycle": {
            "label": "Gold Supercycle",
            "status": "INTACT",
            "confidence": 8,
            "last_note": "Debasement + Hormuz + central bank buying driving structural gold bull market."
        },
        "copper_deficit": {
            "label": "Structural Copper Deficit",
            "status": "INTACT",
            "confidence": 7,
            "last_note": "AI data centre buildout + electrification = multi-year copper demand surge."
        },
        "nuclear_renaissance": {
            "label": "Nuclear Renaissance",
            "status": "INTACT",
            "confidence": 8,
            "last_note": "AI power demand forcing utilities back to nuclear. CEG, VST, CCJ direct beneficiaries."
        }
    },
    "stock_drift": {}
}

# ─────────────────────────────────────────────
# THESIS FILE — read / write
# ─────────────────────────────────────────────

def load_thesis():
    if os.path.exists(THESIS_FILE):
        try:
            with open(THESIS_FILE) as f:
                data = json.load(f)
            # Merge with default to ensure all keys exist
            for key, val in DEFAULT_THESIS["pillars"].items():
                if key not in data.get("pillars", {}):
                    data.setdefault("pillars", {})[key] = val
            return data
        except Exception as e:
            print(f"      Warning: could not read thesis.json: {e}")
    return dict(DEFAULT_THESIS)

def save_thesis(thesis):
    with open(THESIS_FILE, "w") as f:
        json.dump(thesis, f, indent=2)

# ─────────────────────────────────────────────
# DATA FETCHING
# ─────────────────────────────────────────────

def safe_round(val, digits=2):
    try:
        return round(float(val), digits) if val is not None else "N/A"
    except:
        return "N/A"

def fmt_millions(val):
    try:
        v = float(val)
        if abs(v) >= 1e9: return f"${v/1e9:.1f}B"
        if abs(v) >= 1e6: return f"${v/1e6:.0f}M"
        return f"${v:.0f}"
    except:
        return "N/A"

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

            # Next earnings — convert timestamp to readable date
            next_earn = "N/A"
            ts = inf.get("earningsTimestamp")
            if ts:
                try:
                    next_earn = datetime.datetime.utcfromtimestamp(ts).strftime("%d %b %Y")
                except:
                    pass

            return {
                "name":             inf.get("shortName") or inf.get("longName") or ticker,
                "sector":           inf.get("sector", ""),
                "industry":         inf.get("industry", ""),
                "price":            safe_round(price, 3),
                "change_pct":       safe_round(chg, 2),
                "day_high":         safe_round(fi.day_high, 3),
                "day_low":          safe_round(fi.day_low, 3),
                "52w_high":         safe_round(hi52, 3),
                "52w_low":          safe_round(lo52, 3),
                "mkt_cap":          fmt_millions(inf.get("marketCap")),
                "pe_trailing":      safe_round(inf.get("trailingPE")),
                "pe_forward":       safe_round(inf.get("forwardPE")),
                "peg_ratio":        safe_round(inf.get("pegRatio")),
                "ps_ratio":         safe_round(inf.get("priceToSalesTrailing12Months")),
                "pb_ratio":         safe_round(inf.get("priceToBook")),
                "ev_ebitda":        safe_round(inf.get("enterpriseToEbitda")),
                "revenue_growth":   safe_round(inf.get("revenueGrowth"), 3),
                "gross_margin":     safe_round(inf.get("grossMargins"), 3),
                "operating_margin": safe_round(inf.get("operatingMargins"), 3),
                "profit_margin":    safe_round(inf.get("profitMargins"), 3),
                "total_cash":       fmt_millions(inf.get("totalCash")),
                "total_debt":       fmt_millions(inf.get("totalDebt")),
                "fcf":              fmt_millions(inf.get("freeCashflow")),
                "roe":              safe_round(inf.get("returnOnEquity"), 3),
                "debt_to_equity":   safe_round(inf.get("debtToEquity")),
                "target_mean":      safe_round(inf.get("targetMeanPrice")),
                "target_high":      safe_round(inf.get("targetHighPrice")),
                "recommendation":   inf.get("recommendationKey", ""),
                "analyst_count":    inf.get("numberOfAnalystOpinions"),
                "next_earnings":    next_earn,
            }
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                print(f"      WARNING: {ticker}: {e}")
                return {"name": ticker, "price": "N/A", "change_pct": 0, "next_earnings": "N/A"}
    return {"name": ticker, "price": "N/A", "change_pct": 0, "next_earnings": "N/A"}

def fetch_all_stocks(tickers):
    results = {}
    for i, ticker in enumerate(tickers):
        results[ticker] = fetch_stock_full(ticker)
        if (i+1) % 5 == 0:
            print(f"      {i+1}/{len(tickers)} done...")
    return results

# ─────────────────────────────────────────────
# CALL 1 — FUNDAMENTALS ANALYSIS (no web search)
# ─────────────────────────────────────────────

FUNDAMENTALS_PROMPT = """You are a sharp independent market analyst. Direct, blunt, high-conviction. No disclaimers.

SIGNAL DEFINITIONS:
- MULTIBAGGER: asymmetric upside, structural trend, 3-5x potential over 2-3 years
- DEEP VALUE: significant discount to intrinsic value, catalyst needed
- UNDERVALUED: solid business below fair value, lower risk
- WATCH: interesting but wait for better entry or catalyst
- AVOID: deteriorating fundamentals or structurally challenged

CRITICAL RULES:
- Respond ONLY with valid JSON. No text outside the JSON. No markdown fences.
- Do NOT use apostrophes or contractions. Write "does not" not "doesn't".

JSON STRUCTURE:
{
  "regime": "3 sentence macro snapshot referencing actual numbers from the data",
  "sector_rotation": "2 sentences on where money is moving and why",
  "risks": "2 sentences on biggest near-term risk to risk assets",
  "top5": [
    {
      "rank": 1,
      "ticker": "XXX",
      "signal": "MULTIBAGGER",
      "thesis": "4 sentences: fundamental case, structural driver, what market misses, why now",
      "entry": "specific price or range",
      "target": "12-month target with reasoning",
      "invalidation": "specific level or event that breaks thesis",
      "risk_reward": "e.g. 3.5:1",
      "key_metric": "single most important fundamental metric",
      "next_earnings": "date from data or N/A"
    }
  ],
  "stock_analysis": [
    {
      "ticker": "XXX",
      "signal": "MULTIBAGGER",
      "one_liner": "one sentence verdict referencing a specific number",
      "entry": "specific price",
      "watch_level": "key price level"
    }
  ]
}"""

def build_fundamentals_context(stock_data, macro_data, audusd):
    today = datetime.date.today().strftime("%A %d %B %Y")
    lines = [f"DATE: {today}", "", "=== MACRO ==="]
    for name, data in macro_data.items():
        chg = data.get("change_pct", 0)
        lines.append(f"{name:15} {str(data.get('price','N/A')):>10}  {'UP' if isinstance(chg,(int,float)) and chg>0 else 'DOWN'} {abs(chg) if isinstance(chg,(int,float)) else 0:.2f}%")
    aud = f"{audusd:.4f}" if isinstance(audusd,(int,float)) else "N/A"
    lines += ["", f"AUD/USD: {aud}", "", "=== STOCKS ==="]

    for sector, tickers in SECTORS.items():
        lines.append(f"\n-- {sector} --")
        for ticker in tickers:
            d = stock_data.get(ticker, {})
            price = d.get("price","N/A")
            chg   = d.get("change_pct", 0)
            hi52  = d.get("52w_high","N/A")
            lo52  = d.get("52w_low","N/A")
            vs    = f"{round((price-hi52)/hi52*100,1)}%" if isinstance(price,(int,float)) and isinstance(hi52,(int,float)) and hi52 else "N/A"
            lines.append(f"\n{ticker} ({d.get('name',ticker)}) | {d.get('industry','')}")
            lines.append(f"  Price: ${price}  Chg: {chg:+.1f}%  52wH: {hi52}  52wL: {lo52}  vs52wH: {vs}")
            lines.append(f"  Cap: {d.get('mkt_cap','N/A')}  P/E fwd: {d.get('pe_forward','N/A')}  PEG: {d.get('peg_ratio','N/A')}  EV/EBITDA: {d.get('ev_ebitda','N/A')}")
            lines.append(f"  RevGrowth: {d.get('revenue_growth','N/A')}  GrossMargin: {d.get('gross_margin','N/A')}  OpMargin: {d.get('operating_margin','N/A')}  FCF: {d.get('fcf','N/A')}")
            lines.append(f"  Cash: {d.get('total_cash','N/A')}  Debt: {d.get('total_debt','N/A')}  D/E: {d.get('debt_to_equity','N/A')}  ROE: {d.get('roe','N/A')}")
            lines.append(f"  AnalystTarget: {d.get('target_mean','N/A')} / {d.get('target_high','N/A')}  Rec: {d.get('recommendation','N/A')}  NextEarnings: {d.get('next_earnings','N/A')}")

    lines += [
        "",
        "TASK: Analyse all stocks above.",
        "Pick the top 5 highest-conviction ideas for deep analysis in the top5 array.",
        "For ALL remaining stocks provide a one-liner in stock_analysis.",
        "Include next_earnings date in each top5 item (from the data above).",
        "Classify each: MULTIBAGGER, DEEP VALUE, UNDERVALUED, WATCH, or AVOID.",
        "Every stock_analysis item must have a non-empty one_liner, entry, and watch_level.",
        "No apostrophes or contractions anywhere in the JSON.",
    ]
    return "\n".join(lines)

# ─────────────────────────────────────────────
# CALL 2 — THESIS STRESS TEST (with web search)
# ─────────────────────────────────────────────

THESIS_PROMPT = """You are a macro analyst stress-testing an investment thesis against current reality. Direct and blunt.

YOUR JOB:
1. Use web_search to find TODAY's news on each macro pillar listed below
2. For each pillar: confirm INTACT, flag WATCH (weakening), or call BROKEN (thesis invalidated)
3. For stocks rated WATCH or AVOID: search for 1 better alternative in the same sector
4. Identify any thesis drift — stock bought for reason X but reason X has changed

CRITICAL RULES:
- Respond ONLY with valid JSON. No markdown fences. No text outside JSON.
- Do NOT use apostrophes or contractions.
- Search at least 3 times before responding — one for macro news, one for sector comparisons, one for earnings/catalysts.

JSON STRUCTURE:
{
  "news_summary": "3 sentences on the most important market-moving news found today",
  "pillars": {
    "hormuz_disruption":  {"status": "INTACT", "confidence": 8, "note": "one sentence update based on today's news"},
    "stagflation_regime": {"status": "INTACT", "confidence": 7, "note": "one sentence update"},
    "ai_bubble_risk":     {"status": "WATCH",  "confidence": 6, "note": "one sentence update"},
    "gold_supercycle":    {"status": "INTACT", "confidence": 8, "note": "one sentence update"},
    "copper_deficit":     {"status": "INTACT", "confidence": 7, "note": "one sentence update"},
    "nuclear_renaissance":{"status": "INTACT", "confidence": 8, "note": "one sentence update"}
  },
  "stock_drift": {
    "TICKER": {"status": "INTACT", "note": "one sentence — is the original thesis still valid"}
  },
  "alternatives": [
    {"instead_of": "TICKER", "consider": "TICKER2", "reason": "one sentence why"}
  ],
  "macro_shift": "2 sentences — has anything fundamentally changed in the macro picture today"
}"""

def build_thesis_context(stock_data, thesis, sa_map, macro_data, audusd):
    today = datetime.date.today().strftime("%A %d %B %Y")
    lines = [f"DATE: {today}", "", "=== KEY MACRO LEVELS ==="]

    # Only send the most important macro items
    key_macro = ["Gold", "Oil (WTI)", "10Y Yield", "VIX", "S&P 500", "Nasdaq"]
    for name in key_macro:
        data = macro_data.get(name, {})
        chg  = data.get("change_pct", 0)
        lines.append(f"{name:15} {str(data.get('price','N/A')):>10}  {'UP' if isinstance(chg,(int,float)) and chg>0 else 'DOWN'} {abs(chg) if isinstance(chg,(int,float)) else 0:.2f}%")

    aud = f"{audusd:.4f}" if isinstance(audusd,(int,float)) else "N/A"
    lines += [f"AUD/USD: {aud}", "", "=== THESIS PILLARS (current state) ==="]
    for key, pillar in thesis.get("pillars", {}).items():
        lines.append(f"{pillar.get('label', key)}: {pillar.get('status')} conf={pillar.get('confidence')}/10 — {pillar.get('last_note','')[:100]}")

    # Only send stocks rated WATCH or AVOID for comparison
    watch_avoid = [(t, d) for t, d in sa_map.items() if d.get("signal","") in ("WATCH","AVOID")]
    if watch_avoid:
        lines += ["", "=== STOCKS TO REVIEW (WATCH/AVOID only) ==="]
        for ticker, sa in watch_avoid[:8]:  # cap at 8 to save tokens
            d = stock_data.get(ticker, {})
            drift = thesis.get("stock_drift", {}).get(ticker, {})
            lines.append(f"{ticker} ({d.get('name',ticker)}) sector={d.get('sector','')} signal={sa.get('signal','')} price=${d.get('price','N/A')} P/E={d.get('pe_forward','N/A')} FCF={d.get('fcf','N/A')}")
            if drift:
                lines.append(f"  Prior: {drift.get('status','NEW')} — {drift.get('note','')[:80]}")

    lines += [
        "",
        "TASK:",
        "1. Search for news on each thesis pillar — Hormuz/oil, Fed/inflation, AI capex, gold, copper, nuclear.",
        "2. Update each pillar status: INTACT, WATCH, or BROKEN. Update confidence 1-10.",
        "3. For up to 3 WATCH/AVOID stocks, search for a better alternative in the same sector.",
        "4. Summarise today's most important news in news_summary (3 sentences).",
        "5. No apostrophes or contractions anywhere in the JSON.",
        "6. Keep notes concise — one sentence per pillar.",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────
# JSON PARSER
# ─────────────────────────────────────────────

def parse_json_robust(raw):
    while "```" in raw:
        raw = raw.replace("```json", "").replace("```", "")
    raw = raw.strip()
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found: " + raw[:200])
    raw = raw[start:end]
    errors = []

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        errors.append("attempt1: " + str(e))

    c2 = re.sub(r"[\x01-\x1f\x7f]", " ", raw)
    try:
        return json.loads(c2)
    except json.JSONDecodeError as e:
        errors.append("attempt2: " + str(e))

    c3 = c2.replace("\u2018", " ").replace("\u2019", " ").replace("\u201c", chr(34)).replace("\u201d", chr(34))
    try:
        return json.loads(c3)
    except json.JSONDecodeError as e:
        errors.append("attempt3: " + str(e))

    def drop_apos(m):
        return m.group(0).replace("'", " ")
    c4 = re.sub(r'"[^"]*"', drop_apos, c3)
    try:
        return json.loads(c4)
    except json.JSONDecodeError as e:
        errors.append("attempt4: " + str(e))

    # Truncation recovery
    try:
        last_good = max(c4.rfind("}],"), c4.rfind("}]"), c4.rfind("]}"))
        if last_good > len(c4) // 2:
            truncated = c4[:last_good+2].rstrip(",").rstrip() + "}"
            while truncated.count("{") > truncated.count("}"):
                truncated += "}"
            return json.loads(truncated)
    except Exception as e:
        errors.append("truncation: " + str(e))

    raise ValueError("All parse attempts failed:\n" + "\n".join(errors))

# ─────────────────────────────────────────────
# CLAUDE CALLS
# ─────────────────────────────────────────────

def call_claude_fundamentals(stock_data, macro_data, audusd):
    """Single call, no tools — analyses fundamentals for all 28 stocks."""
    context = build_fundamentals_context(stock_data, macro_data, audusd)
    client  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        system=FUNDAMENTALS_PROMPT,
        messages=[{"role": "user", "content": context}],
    )
    text = " ".join(b.text for b in msg.content if getattr(b,"type","") == "text" and b.text.strip())
    if not text:
        raise ValueError("No text in fundamentals response")
    print(f"      Fundamentals response: {len(text)} chars")
    return parse_json_robust(text)

def call_claude_thesis(stock_data, thesis, sa_map, macro_data, audusd):
    """Single call with web search — stress-tests thesis against today's news."""
    context = build_thesis_context(stock_data, thesis, sa_map, macro_data, audusd)
    client  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    tools    = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}]
    messages = [{"role": "user", "content": context}]

    for iteration in range(15):
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=6000,
            system=THESIS_PROMPT,
            tools=tools,
            messages=messages,
        )
        text_parts = []
        tool_uses  = []
        for block in msg.content:
            btype = getattr(block, "type", "")
            if btype == "text" and block.text.strip():
                text_parts.append(block.text)
            elif btype == "tool_use":
                tool_uses.append(block)

        print(f"      Thesis iter {iteration+1}: stop={msg.stop_reason} tools={len(tool_uses)} text={sum(len(t) for t in text_parts)} chars")

        if msg.stop_reason == "end_turn" and text_parts:
            raw = " ".join(text_parts)
            return parse_json_robust(raw)

        if msg.stop_reason == "tool_use" and tool_uses:
            messages.append({"role": "assistant", "content": msg.content})
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tu.id, "content": "Search completed."}
                for tu in tool_uses
            ]})
            continue

        if text_parts:
            return parse_json_robust(" ".join(text_parts))

        raise ValueError(f"Unexpected: stop={msg.stop_reason}")

    raise ValueError("Exceeded 15 iterations")

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
PILLAR_COLORS = {
    "INTACT": ("#39D353", "#0f2d18"),
    "WATCH":  ("#E3B341", "#2a1f0a"),
    "BROKEN": ("#F85149", "#2d0f0e"),
}

def sig_badge(signal):
    col, bg = SIGNAL_COLORS.get(signal.upper(), ("#8B949E","#1a1f24"))
    return f'<span style="background:{bg};color:{col};border:1px solid {col};padding:2px 8px;border-radius:3px;font-size:10px;font-weight:700;white-space:nowrap">{signal}</span>'

def pillar_badge(status):
    col, bg = PILLAR_COLORS.get(status.upper(), ("#8B949E","#1a1f24"))
    return f'<span style="background:{bg};color:{col};border:1px solid {col};padding:2px 8px;border-radius:3px;font-size:10px;font-weight:700">{status}</span>'

def conf_bar(conf):
    try:
        c = int(conf)
        col = "#39D353" if c >= 7 else ("#E3B341" if c >= 5 else "#F85149")
        bars = "█" * c + "░" * (10 - c)
        return f'<span style="color:{col};font-size:11px;letter-spacing:1px">{bars}</span> <span style="color:#8B949E;font-size:10px">{c}/10</span>'
    except:
        return ""

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

def th(right=False):
    base = "background:#0D1117;color:#8B949E;font-size:10px;text-transform:uppercase;letter-spacing:.05em;padding:8px 12px;border-bottom:1px solid #30363D"
    return base + (";text-align:right" if right else ";text-align:left")

def build_html(fund_analysis, thesis_result, thesis, stock_data, macro_data, audusd, today_str):
    aud_str   = f"{audusd:.4f}" if isinstance(audusd,(int,float)) else "N/A"
    sp_data   = macro_data.get("S&P 500",{})
    ndq_data  = macro_data.get("Nasdaq",{})
    sp_price  = sp_data.get("price","N/A")
    sp_chg    = sp_data.get("change_pct",0)
    ndq_price = ndq_data.get("price","N/A")
    ndq_chg   = ndq_data.get("change_pct",0)
    vix       = macro_data.get("VIX",{}).get("price","N/A")
    yld       = macro_data.get("10Y Yield",{}).get("price","N/A")

    # ── macro table ──
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

    # ── news banner ──
    news = thesis_result.get("news_summary") or fund_analysis.get("news_summary","")
    news_html = ""
    if news and news != "N/A":
        news_html = f'<div style="background:#0f1f30;border-left:3px solid #E3B341;border-radius:0 6px 6px 0;padding:12px 18px;margin-bottom:20px;color:#F0F6FC;font-size:12px;line-height:1.8"><span style="color:#E3B341;font-weight:700">TODAY IN MARKETS &nbsp;</span>{news}</div>'

    # ── thesis health dashboard ──
    pillars_html = ""
    updated_pillars = thesis_result.get("pillars", {})
    for key, pillar in thesis.get("pillars", {}).items():
        current = updated_pillars.get(key, {})
        status  = current.get("status", pillar.get("status","INTACT"))
        conf    = current.get("confidence", pillar.get("confidence", 7))
        note    = current.get("note", pillar.get("last_note",""))
        label   = pillar.get("label", key)
        pillars_html += f"""
        <div style="background:#1C2128;border:1px solid #30363D;border-radius:8px;padding:14px;margin-bottom:10px">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;flex-wrap:wrap">
            <span style="color:#F0F6FC;font-weight:700;font-size:12px">{label}</span>
            {pillar_badge(status)}
            {conf_bar(conf)}
          </div>
          <div style="color:#8B949E;font-size:11px;line-height:1.6">{note}</div>
        </div>"""

    # ── alternatives ──
    alts = thesis_result.get("alternatives", [])
    alts_html = ""
    for alt in alts:
        alts_html += f"""
        <div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid #21262d;flex-wrap:wrap">
          <span style="color:#F85149;font-weight:700">{alt.get('instead_of','')}</span>
          <span style="color:#8B949E">→</span>
          <span style="color:#39D353;font-weight:700">{alt.get('consider','')}</span>
          <span style="color:#F0F6FC;font-size:12px">{alt.get('reason','')}</span>
        </div>"""

    macro_shift = thesis_result.get("macro_shift","")

    # ── top 5 cards ──
    top5_tickers = set()
    top5_html    = ""
    rank_cols    = ["#E3B341","#F0F6FC","#8B949E","#8B949E","#8B949E"]

    for idea in fund_analysis.get("top5",[]):
        rank   = idea.get("rank",1)
        ticker = idea.get("ticker","")
        signal = idea.get("signal","")
        top5_tickers.add(ticker)
        d      = stock_data.get(ticker,{})
        price  = d.get("price","N/A")
        chg    = d.get("change_pct",0)
        name   = d.get("name",ticker)
        rc     = rank_cols[min(rank-1,4)]
        ne     = d.get("next_earnings") or idea.get("next_earnings","N/A")

        top5_html += f"""
        <div style="background:#161B22;border:1px solid #30363D;border-radius:10px;padding:22px;margin-bottom:16px">
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;flex-wrap:wrap">
            <span style="color:{rc};font-size:24px;font-weight:900">#{rank}</span>
            <span style="color:#00D4FF;font-size:18px;font-weight:800">{ticker}</span>
            <span style="color:#8B949E;font-size:12px">{name}</span>
            {sig_badge(signal)}
            <span style="margin-left:auto;color:{chg_col(chg)};font-weight:700;font-size:14px">{fmt_price(price)} &nbsp; {fmt_chg(chg)}</span>
          </div>
          <p style="color:#F0F6FC;line-height:1.8;margin-bottom:16px">{idea.get("thesis","")}</p>
          <div style="background:#0D1117;border-radius:4px;padding:10px;margin-bottom:14px;display:flex;gap:20px;flex-wrap:wrap">
            <span style="color:#8B949E;font-size:11px">KEY METRIC &nbsp;<span style="color:#00D4FF">{idea.get("key_metric","N/A")}</span></span>
            <span style="color:#8B949E;font-size:11px">NEXT EARNINGS &nbsp;<span style="color:#E3B341">{ne}</span></span>
          </div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px">
            <div style="background:#0D1117;border-radius:6px;padding:10px"><div style="color:#8B949E;font-size:10px;text-transform:uppercase;margin-bottom:3px">Entry</div><div style="color:#39D353;font-weight:700">{idea.get("entry","N/A")}</div></div>
            <div style="background:#0D1117;border-radius:6px;padding:10px"><div style="color:#8B949E;font-size:10px;text-transform:uppercase;margin-bottom:3px">12M Target</div><div style="color:#E3B341;font-weight:700">{idea.get("target","N/A")}</div></div>
            <div style="background:#0D1117;border-radius:6px;padding:10px"><div style="color:#8B949E;font-size:10px;text-transform:uppercase;margin-bottom:3px">Risk / Reward</div><div style="color:#00D4FF;font-weight:700">{idea.get("risk_reward","N/A")}</div></div>
            <div style="background:#0D1117;border-radius:6px;padding:10px"><div style="color:#8B949E;font-size:10px;text-transform:uppercase;margin-bottom:3px">Invalidation</div><div style="color:#F85149;font-weight:700;font-size:11px">{idea.get("invalidation","N/A")}</div></div>
          </div>
        </div>"""

    # ── sector tabs ──
    sa_map      = {item.get("ticker",""): item for item in fund_analysis.get("stock_analysis",[])}
    drift_map   = thesis_result.get("stock_drift", {})
    tab_buttons = ""
    tab_contents= ""

    for si, (sector, tickers) in enumerate(SECTORS.items()):
        active = "active" if si==0 else ""
        tab_buttons += f'<button class="tab-btn {active}" onclick="showTab({si})">{sector}</button>\n'
        rows = ""
        for ticker in tickers:
            d      = stock_data.get(ticker,{})
            price  = d.get("price","N/A")
            chg    = d.get("change_pct",0)
            hi52   = d.get("52w_high","N/A")
            name   = d.get("name",ticker)
            pe     = d.get("pe_forward","N/A")
            rev_g  = d.get("revenue_growth","N/A")
            fcf    = d.get("fcf","N/A")
            tgt    = d.get("target_mean","N/A")
            ne     = d.get("next_earnings","N/A")
            vs     = round((price-hi52)/hi52*100,1) if isinstance(price,(int,float)) and isinstance(hi52,(int,float)) and hi52 else "N/A"

            sa      = sa_map.get(ticker,{})
            signal  = sa.get("signal","WATCH")
            liner   = sa.get("one_liner","")
            entry   = sa.get("entry","")
            watch   = sa.get("watch_level","")
            drift   = drift_map.get(ticker,{})
            is_top5 = ticker in top5_tickers
            star    = '<span style="color:#E3B341;font-size:10px;font-weight:700;margin-left:5px">★ TOP 5</span>' if is_top5 else ""

            drift_indicator = ""
            if drift:
                ds = drift.get("status","")
                dc = "#39D353" if ds == "INTACT" else ("#E3B341" if ds == "WATCH" else "#F85149")
                drift_indicator = f'<span style="color:{dc};font-size:9px;margin-left:4px">● {ds}</span>'

            rows += f"""<tr style="border-bottom:1px solid #21262d" class="stock-row">
              <td style="padding:10px 12px;min-width:90px">
                <span style="color:#00D4FF;font-weight:700;font-size:14px">{ticker}</span>{star}{drift_indicator}
                <div style="color:#8B949E;font-size:11px;margin-top:1px">{name[:26]}</div>
              </td>
              <td style="padding:10px 12px;text-align:right;white-space:nowrap">
                <div style="color:#F0F6FC;font-weight:600">{fmt_price(price)}</div>
                <div style="color:{chg_col(chg)};font-size:11px">{fmt_chg(chg)}</div>
              </td>
              <td style="padding:10px 12px;text-align:right;white-space:nowrap">
                <div style="color:#8B949E;font-size:11px">H: {hi52}</div>
                <div style="color:{vs52_col(vs)};font-size:11px">{vs if vs=='N/A' else str(vs)+'%'}</div>
              </td>
              <td style="padding:10px 12px;text-align:right;white-space:nowrap">
                <div style="color:#8B949E;font-size:11px">P/E: {pe}</div>
                <div style="color:#8B949E;font-size:11px">RevG: {rev_g}</div>
              </td>
              <td style="padding:10px 12px;text-align:right;white-space:nowrap">
                <div style="color:#8B949E;font-size:11px">FCF: {fcf}</div>
                <div style="color:#8B949E;font-size:11px">Earn: {ne}</div>
              </td>
              <td style="padding:10px 12px">{sig_badge(signal)}</td>
              <td style="padding:10px 12px;color:#F0F6FC;font-size:12px;min-width:180px;max-width:300px">{liner}</td>
              <td style="padding:10px 12px;text-align:right;white-space:nowrap">
                <div style="color:#39D353;font-size:11px">Entry: {entry}</div>
                <div style="color:#8B949E;font-size:11px">Watch: {watch}</div>
              </td>
            </tr>"""

        display = "block" if si==0 else "none"
        tab_contents += (
            f'<div class="tab-content" id="tab-{si}" style="display:{display}">'
            f'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse">'
            f'<thead><tr>'
            f'<th style="{th()}">Stock</th>'
            f'<th style="{th(True)}">Price</th>'
            f'<th style="{th(True)}">52W</th>'
            f'<th style="{th(True)}">P/E / RevG</th>'
            f'<th style="{th(True)}">FCF / Earnings</th>'
            f'<th style="{th()}">Signal</th>'
            f'<th style="{th()}">Verdict</th>'
            f'<th style="{th(True)}">Levels</th>'
            f'</tr></thead><tbody>{rows}</tbody></table></div></div>\n'
        )

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
  .grid-3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px}}
  @media(max-width:900px){{.grid-2,.grid-3{{grid-template-columns:1fr}}}}
  .footer{{border-top:1px solid #30363D;padding-top:14px;margin-top:28px;color:#8B949E;font-size:11px;text-align:center}}
</style>
</head>
<body>
<div class="container">

  <div style="padding-bottom:20px;margin-bottom:22px;border-bottom:1px solid #30363D">
    <div style="font-size:clamp(16px,4vw,26px);font-weight:900;color:#00D4FF;letter-spacing:.04em">MARKET INTELLIGENCE</div>
    <div style="color:#8B949E;font-size:11px;margin-top:5px">{today_str} &nbsp;·&nbsp; Claude Sonnet 4.6 + Web Search &nbsp;·&nbsp; yFinance Fundamentals &nbsp;·&nbsp; {len(ALL_STOCKS)} stocks / 6 sectors</div>
  </div>

  <div class="stat-strip">
    <div class="stat"><div class="stat-label">S&amp;P 500</div><div class="stat-value" style="color:{chg_col(sp_chg)}">{sp_price}</div><div style="color:{chg_col(sp_chg)};font-size:11px">{fmt_chg(sp_chg)}</div></div>
    <div class="stat"><div class="stat-label">Nasdaq</div><div class="stat-value" style="color:{chg_col(ndq_chg)}">{ndq_price}</div><div style="color:{chg_col(ndq_chg)};font-size:11px">{fmt_chg(ndq_chg)}</div></div>
    <div class="stat"><div class="stat-label">VIX</div><div class="stat-value" style="color:#F0F6FC">{vix}</div></div>
    <div class="stat"><div class="stat-label">10Y Yield</div><div class="stat-value" style="color:#F0F6FC">{yld}</div></div>
    <div class="stat"><div class="stat-label">AUD / USD</div><div class="stat-value" style="color:#E3B341">{aud_str}</div></div>
  </div>

  {news_html}

  <div class="grid-2" style="margin-bottom:20px">
    <div class="card">
      <h2>Macro Regime</h2>
      <p style="color:#F0F6FC;line-height:1.8;margin-bottom:14px">{fund_analysis.get("regime","N/A")}</p>
      <h2 style="margin-top:4px">Sector Rotation</h2>
      <p style="color:#F0F6FC;line-height:1.8;margin-bottom:14px">{fund_analysis.get("sector_rotation","N/A")}</p>
      <h2 style="margin-top:4px">Key Risk</h2>
      <p style="color:#F85149;line-height:1.8">{fund_analysis.get("risks","N/A")}</p>
      {f'<h2 style="margin-top:16px">Macro Shift</h2><p style="color:#E3B341;line-height:1.8">{macro_shift}</p>' if macro_shift else ""}
    </div>
    <div class="card">
      <h2>Macro Data</h2>
      <table style="width:100%;border-collapse:collapse">
        <thead><tr>
          <th style="{th()}">Instrument</th>
          <th style="{th(True)}">Price</th>
          <th style="{th(True)}">Change</th>
          <th style="{th(True)}">52W High</th>
        </tr></thead>
        <tbody>{macro_rows}</tbody>
      </table>
    </div>
  </div>

  <div class="card" style="margin-bottom:20px">
    <h2>Thesis Health — Updated Today via Web Search</h2>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px">
      {pillars_html}
    </div>
    {f'<div style="margin-top:14px;padding-top:14px;border-top:1px solid #30363D"><h2>Consider Instead</h2>{alts_html}</div>' if alts_html else ""}
  </div>

  <div class="card" style="margin-bottom:20px">
    <h2>Top 5 High-Conviction Ideas — Fundamentals Based</h2>
    {top5_html if top5_html else '<p style="color:#8B949E">Analysis unavailable.</p>'}
  </div>

  <div class="card">
    <h2>All Stocks by Sector</h2>
    <div class="tab-bar">{tab_buttons}</div>
    {tab_contents}
  </div>

  <div class="footer">
    Updated {today_str} &nbsp;·&nbsp; Claude Sonnet 4.6 with web search &nbsp;·&nbsp; yFinance fundamentals &nbsp;·&nbsp; For informational purposes only
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

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    today_str = datetime.date.today().strftime("%d %b %Y")
    print(f"\n{'─'*52}")
    print(f"  MARKET INTELLIGENCE  //  {today_str}")
    print(f"{'─'*52}")

    if ANTHROPIC_API_KEY == "YOUR_API_KEY_HERE":
        print("\nERROR: Set ANTHROPIC_API_KEY.")
        sys.exit(1)

    # Load evolving thesis from file
    thesis = load_thesis()
    print(f"\n  Thesis last updated: {thesis.get('last_updated','never')}")

    print(f"\n[1/4] Fetching {len(ALL_STOCKS)} stocks with fundamentals...")
    stock_data = fetch_all_stocks(ALL_STOCKS)
    ok = sum(1 for v in stock_data.values() if v.get("price") != "N/A")
    print(f"      {ok}/{len(ALL_STOCKS)} fetched OK")

    print("[2/4] Fetching macro data...")
    macro_raw  = fetch_price_data(list(MACRO.values()))
    macro_data = {name: macro_raw.get(ticker,{}) for name, ticker in MACRO.items()}
    audusd_val = macro_raw.get("AUDUSD=X",{}).get("price", 0.65)
    audusd     = audusd_val if isinstance(audusd_val,(int,float)) else 0.65

    print("[3/4] Calling Claude — fundamentals analysis...")
    try:
        fund_analysis = call_claude_fundamentals(stock_data, macro_data, audusd)
        print(f"      Complete: {len(fund_analysis.get('top5',[]))} top picks, {len(fund_analysis.get('stock_analysis',[]))} one-liners")
    except Exception as e:
        import traceback
        print(f"      ERROR:\n{traceback.format_exc()}")
        fund_analysis = {"regime":"Analysis unavailable.","sector_rotation":"N/A","risks":"N/A","top5":[],"stock_analysis":[]}

    # Build sa_map for thesis call
    sa_map = {item.get("ticker",""): item for item in fund_analysis.get("stock_analysis",[])}

    print("[4/4] Calling Claude — thesis stress test (web search)...")
    try:
        thesis_result = call_claude_thesis(stock_data, thesis, sa_map, macro_data, audusd)
        print(f"      Complete: {len(thesis_result.get('pillars',{}))} pillars, {len(thesis_result.get('alternatives',[]))} alternatives")

        # Update and persist thesis
        thesis["last_updated"] = today_str
        for key, update in thesis_result.get("pillars",{}).items():
            if key in thesis["pillars"]:
                thesis["pillars"][key]["status"]     = update.get("status", thesis["pillars"][key]["status"])
                thesis["pillars"][key]["confidence"] = update.get("confidence", thesis["pillars"][key]["confidence"])
                thesis["pillars"][key]["last_note"]  = update.get("note", thesis["pillars"][key]["last_note"])
        for ticker, drift in thesis_result.get("stock_drift",{}).items():
            thesis["stock_drift"][ticker] = drift
        save_thesis(thesis)
        print(f"      thesis.json updated")
    except Exception as e:
        import traceback
        print(f"      Thesis error (non-fatal):\n{traceback.format_exc()}")
        thesis_result = {"news_summary":"","pillars":{},"stock_drift":{},"alternatives":[],"macro_shift":""}

    print("\nBuilding HTML...")
    html = build_html(fund_analysis, thesis_result, thesis, stock_data, macro_data, audusd, today_str)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Saved: {OUTPUT_HTML}")

    with open(HEADERS_FILE, "w") as f:
        f.write("/index.html\n  Cache-Control: no-cache, no-store, must-revalidate\n  Pragma: no-cache\n  Expires: 0\n\n/\n  Cache-Control: no-cache, no-store, must-revalidate\n")
    print(f"  Saved: {HEADERS_FILE}")
    print(f"\n{'─'*52}\n")

if __name__ == "__main__":
    main()
