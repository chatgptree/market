"""
market_brief.py
---------------
Fetches live market data, runs it through Claude's API using your investment
framework, and writes a fully formatted Excel workbook.

Run daily:  python market_brief.py
Schedule:   cron / Task Scheduler (see README at bottom of file)

Requirements:
    pip install yfinance openpyxl anthropic requests

API keys needed:
    ANTHROPIC_API_KEY  — https://console.anthropic.com/
    (yFinance needs no key for free tier data)
"""

import os
import sys
import json
import datetime
import yfinance as yf
import time
import anthropic
from openpyxl import Workbook
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side, GradientFill
)
from openpyxl.utils import get_column_letter
from openpyxl.chart import LineChart, Reference

# ─────────────────────────────────────────────
# 1. CONFIGURATION  ← edit this section
# ─────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_API_KEY")

OUTPUT_FILE = "Market_Brief.xlsx"

# Your portfolio: ticker → (units, avg_cost_AUD)
PORTFOLIO = {
    "FCX":   {"units": None,  "avg_aud": None,  "note": "Copper / AI power demand"},
    "CEG":   {"units": None,  "avg_aud": None,  "note": "Nuclear / AI power"},
    "VST":   {"units": None,  "avg_aud": None,  "note": "Nuclear / AI power"},
    "CSL.AX":{"units": 22,    "avg_aud": 149.0, "note": "Pharma – binary Aug 18 result"},
    "CI":    {"units": None,  "avg_aud": None,  "note": "Defensive / uncorrelated"},
    "WGX.AX":{"units": 354,   "avg_aud": 4.93,  "note": "Gold – unhedged, FY result Sep 2"},
}

# NDQ is a Betashares ETF (ASX) — tracked separately
NDQ_UNITS = None   # fill in your units
NDQ_AVG   = None   # fill in your avg cost AUD

# Watchlist tickers
WATCHLIST = ["SLX.AX", "IREN", "MARA", "MRVL", "MU", "ALAB", "BIDU", "GOOG"]

# Macro instruments
MACRO = {
    "Gold":     "GC=F",
    "Copper":   "HG=F",
    "Oil (WTI)":"CL=F",
    "10Y Yield":"^TNX",
    "VIX":      "^VIX",
    "AUD/USD":  "AUDUSD=X",
    "S&P 500":  "^GSPC",
    "Nasdaq":   "^IXIC",
    "PHLX Semi":"^SOX",
    "ASX 200":  "^AXJO",
}

# ─────────────────────────────────────────────
# 2. COLOUR PALETTE (dark terminal aesthetic)
# ─────────────────────────────────────────────

C = {
    "bg_dark":    "0D1117",
    "bg_mid":     "161B22",
    "bg_card":    "1C2128",
    "accent":     "00D4FF",
    "green":      "39D353",
    "red":        "F85149",
    "gold":       "E3B341",
    "text_white": "F0F6FC",
    "text_dim":   "8B949E",
    "border":     "30363D",
    "header_bg":  "0D1117",
}

def hex_fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)

def make_border(color="30363D"):
    s = Side(style="thin", color=color)
    return Border(left=s, right=s, top=s, bottom=s)

def style_header(cell, bg=None, fg=None, size=10, bold=True):
    cell.font = Font(name="Consolas", bold=bold, color=fg or C["text_white"], size=size)
    cell.fill = hex_fill(bg or C["bg_dark"])
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell.border = make_border()

def style_data(cell, bg=None, fg=None, bold=False, align="right"):
    cell.font = Font(name="Consolas", color=fg or C["text_white"], size=9, bold=bold)
    cell.fill = hex_fill(bg or C["bg_card"])
    cell.alignment = Alignment(horizontal=align, vertical="center")
    cell.border = make_border()

# ─────────────────────────────────────────────
# 3. DATA FETCHING
# ─────────────────────────────────────────────

def fetch_price_data(tickers):
    """Returns dict: ticker → {price, prev_close, change_pct, 52w_high, 52w_low, ...}"""
    results = {}
    for ticker in tickers:
        for attempt in range(3):
            try:
                t  = yf.Ticker(ticker)
                fi = t.fast_info          # fast: price, prev_close, day hi/lo
                inf = t.info              # slower: 52w hi/lo, volume

                price = fi.last_price
                prev  = fi.previous_close
                if price is None:
                    raise ValueError("price is None")

                chg = ((price - prev) / prev * 100) if prev else 0

                # 52w data lives in .info — key names vary by asset type
                hi52 = inf.get("fiftyTwoWeekHigh") or inf.get("52WeekHigh")
                lo52 = inf.get("fiftyTwoWeekLow")  or inf.get("52WeekLow")

                results[ticker] = {
                    "price":      round(price, 3),
                    "prev_close": round(prev,  3) if prev else "N/A",
                    "change_pct": round(chg,   2),
                    "day_high":   round(fi.day_high, 3) if fi.day_high else "N/A",
                    "day_low":    round(fi.day_low,  3) if fi.day_low  else "N/A",
                    "52w_high":   round(hi52, 3) if hi52 else "N/A",
                    "52w_low":    round(lo52, 3) if lo52 else "N/A",
                }
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(2)
                else:
                    print(f"      ⚠ Could not fetch {ticker}: {e}")
                    results[ticker] = {"price": "N/A", "change_pct": 0, "error": str(e)}
    return results

def fetch_history(ticker, period="3mo"):
    """Returns list of (date, close) tuples for sparkline data."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=period)
        return [(str(d.date()), round(c, 2)) for d, c in zip(hist.index, hist["Close"])]
    except:
        return []

def build_market_context(portfolio_data, macro_data, watchlist_data, audusd):
    """Builds a structured text payload to send to Claude."""
    today = datetime.date.today().strftime("%A %d %B %Y")
    lines = [f"DATE: {today}", "", "=== MACRO SNAPSHOT ==="]
    for name, data in macro_data.items():
        chg = data.get("change_pct", 0)
        arrow = "▲" if chg > 0 else "▼"
        lines.append(f"{name:15} {data.get('price','N/A'):>10}  {arrow} {abs(chg):.2f}%")

    lines += ["", "=== PORTFOLIO POSITIONS ==="]
    for ticker, cfg in PORTFOLIO.items():
        d = portfolio_data.get(ticker, {})
        price = d.get("price", "N/A")
        chg   = d.get("change_pct", 0)
        avg   = cfg.get("avg_aud")
        units = cfg.get("units")
        if avg and units and isinstance(price, (int, float)):
            pnl_pct = (price - avg) / avg * 100
            pnl_str = f"P&L: {pnl_pct:+.1f}%"
        else:
            pnl_str = "P&L: N/A"
        lines.append(
            f"{ticker:10} Price: {price:>10}  Today: {chg:+.2f}%  {pnl_str}  | {cfg.get('note','')}"
        )

    lines += ["", "=== WATCHLIST ==="]
    for ticker in WATCHLIST:
        d = watchlist_data.get(ticker, {})
        lines.append(
            f"{ticker:10} Price: {d.get('price','N/A'):>10}  Today: {d.get('change_pct',0):+.2f}%"
        )

    # FIX: safely format audusd whether it's a float or fallback string
    audusd_display = f"{audusd:.4f}" if isinstance(audusd, (int, float)) else str(audusd)
    lines += ["", "=== AUD/USD ===", f"  {audusd_display}"]
    return "\n".join(lines)

# ─────────────────────────────────────────────
# 4. CLAUDE ANALYSIS
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are a blunt, macro-aware investment analyst working for a sophisticated
retail investor (Giacky) based in Melbourne, Australia. AUD base currency. Platform: Trading 212
(0.80% FX round-trip for USD stocks). No disclaimers. Flag rationalisations.

STANDING PORTFOLIO: FCX (copper/AI power), CEG (nuclear), VST (nuclear), CSL.AX (22 shares avg
~A$149 — underwater, binary catalyst Aug 18 full-year result, no averaging down), WGX.AX (354
units avg ~A$4.93 — unhedged gold, Sep 2 full-year result), NDQ (Betashares ETF, weekly DCA).

MACRO FRAMEWORK: Iran/Hormuz disruption central thesis. Stagflation-adjacent regime: sticky CPI
~3.8%, Fed on hold, RBA hiking cycle. AI bubble repricing risk Q4 2026–Q2 2027 (25–40% on AI
names). Portfolio ~72% correlated to AI demand (FCX, CEG, VST, NDQ). WGX and CI provide
uncorrelated exposure. Gold supercycle. Structural copper deficit. Nuclear renaissance.

WATCHLIST: SLX.AX (uranium enrichment — tranched entry thesis), IREN (AI infrastructure pivot,
top crypto miner idea), MARA (watchlist only), MRVL (wait for Aug earnings, chase risk after
Computex spike), MU, ALAB, BIDU, GOOG.

OUTPUT FORMAT — respond ONLY in this exact JSON structure, no preamble, no markdown fences:
{
  "regime": "2-3 sentence macro regime snapshot",
  "sector_rotation": "1-2 sentences on where money is moving",
  "portfolio_alerts": [
    {"ticker": "XXX", "signal": "HOLD/TRIM/ADD/WATCH", "reason": "one sentence"}
  ],
  "top_ideas": [
    {
      "rank": 1,
      "ticker": "XXX",
      "thesis": "2 sentences",
      "entry": "specific price or range",
      "sizing": "% of portfolio or AUD amount",
      "invalidation": "specific level or event"
    }
  ],
  "risks": "2 sentences on biggest near-term risk to the portfolio",
  "watchlist_notes": "1-2 sentences on any watchlist names worth flagging today"
}"""

def get_claude_analysis(market_context):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": f"Here is today's live market data:\n\n{market_context}\n\nProvide your analysis."}
        ]
    )
    raw = message.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    # extract just the JSON object in case Claude adds any trailing text
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found in response: {raw[:200]}")
    raw = raw[start:end]
    return json.loads(raw)

# ─────────────────────────────────────────────
# 5. EXCEL BUILDER
# ─────────────────────────────────────────────

def set_col_widths(ws, widths: dict):
    for col, w in widths.items():
        ws.column_dimensions[col].width = w

def write_title_row(ws, row, text, span_end, bg=None, fg=None, size=11):
    ws.merge_cells(f"A{row}:{span_end}{row}")
    c = ws[f"A{row}"]
    c.value = text
    c.font = Font(name="Consolas", bold=True, color=fg or C["accent"], size=size)
    c.fill = hex_fill(bg or C["bg_dark"])
    c.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[row].height = 22

# ── Sheet 1: Dashboard ──────────────────────

def build_dashboard(wb, analysis, macro_data, portfolio_data, audusd, today_str):
    ws = wb.create_sheet("📊 Dashboard", 0)
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A6"

    for row in ws.iter_rows(min_row=1, max_row=60, min_col=1, max_col=20):
        for cell in row:
            cell.fill = hex_fill(C["bg_dark"])

    set_col_widths(ws, {
        "A": 2, "B": 18, "C": 14, "D": 12, "E": 12,
        "F": 2, "G": 18, "H": 14, "I": 12, "J": 12
    })

    ws.merge_cells("B1:J1")
    title_cell = ws["B1"]
    title_cell.value = f"  MARKET BRIEF  //  {today_str}"
    title_cell.font = Font(name="Consolas", bold=True, color=C["accent"], size=14)
    title_cell.fill = hex_fill(C["bg_dark"])
    title_cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 32

    ws.merge_cells("B2:J2")
    sub = ws["B2"]
    sub.value = "  Powered by Claude · Live via yFinance · AUD base"
    sub.font = Font(name="Consolas", color=C["text_dim"], size=9)
    sub.fill = hex_fill(C["bg_dark"])
    sub.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[2].height = 16

    ws.merge_cells("B4:J4")
    regime_cell = ws["B4"]
    regime_cell.value = "  ⬡ REGIME: " + analysis.get("regime", "N/A")
    regime_cell.font = Font(name="Consolas", color=C["text_white"], size=9, italic=True)
    regime_cell.fill = hex_fill("1A2332")
    regime_cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[4].height = 40

    write_title_row(ws, 6, "  MACRO", "E", size=9)
    headers = ["INSTRUMENT", "PRICE", "CHG %", "52W HIGH"]
    for i, h in enumerate(headers):
        c = ws.cell(row=7, column=2+i, value=h)
        style_header(c, bg=C["bg_mid"], fg=C["text_dim"], size=8)
    ws.row_dimensions[7].height = 18

    for r, (name, data) in enumerate(macro_data.items(), start=8):
        chg = data.get("change_pct", 0)
        fg_chg = C["green"] if chg > 0 else (C["red"] if chg < 0 else C["text_dim"])
        row_bg = C["bg_card"] if r % 2 == 0 else C["bg_mid"]
        vals = [name, data.get("price", "N/A"), f"{chg:+.2f}%", data.get("52w_high", "N/A")]
        colors = [C["text_white"], C["text_white"], fg_chg, C["text_dim"]]
        for i, (v, fc) in enumerate(zip(vals, colors)):
            c = ws.cell(row=r, column=2+i, value=v)
            style_data(c, bg=row_bg, fg=fc, align="left" if i == 0 else "right")
        ws.row_dimensions[r].height = 16

    write_title_row(ws, 6, "  PORTFOLIO", "J", bg=C["bg_dark"])

    p_headers = ["TICKER", "PRICE", "TODAY", "AVG COST"]
    for i, h in enumerate(p_headers):
        c = ws.cell(row=7, column=7+i, value=h)
        style_header(c, bg=C["bg_mid"], fg=C["text_dim"], size=8)

    for r, (ticker, cfg) in enumerate(PORTFOLIO.items(), start=8):
        d = portfolio_data.get(ticker, {})
        price = d.get("price", "N/A")
        chg   = d.get("change_pct", 0)
        avg   = cfg.get("avg_aud", "—")
        fg_chg = C["green"] if chg > 0 else (C["red"] if chg < 0 else C["text_dim"])
        row_bg = C["bg_card"] if r % 2 == 0 else C["bg_mid"]
        vals = [ticker, price, f"{chg:+.2f}%", avg if avg else "—"]
        colors = [C["accent"], C["text_white"], fg_chg, C["text_dim"]]
        for i, (v, fc) in enumerate(zip(vals, colors)):
            c = ws.cell(row=r, column=7+i, value=v)
            style_data(c, bg=row_bg, fg=fc, align="left" if i == 0 else "right")
        ws.row_dimensions[r].height = 16

    aud_row = max(8 + len(macro_data), 8 + len(PORTFOLIO)) + 1
    # FIX: safely format audusd
    audusd_display = f"{audusd:.4f}" if isinstance(audusd, (int, float)) else str(audusd)
    ws.merge_cells(f"B{aud_row}:J{aud_row}")
    aud_cell = ws[f"B{aud_row}"]
    aud_cell.value = f"  AUD/USD  {audusd_display}   |   Sector rotation: {analysis.get('sector_rotation','')}"
    aud_cell.font = Font(name="Consolas", color=C["gold"], size=9)
    aud_cell.fill = hex_fill(C["bg_mid"])
    aud_cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[aud_row].height = 18

    return ws

# ── Sheet 2: Daily Brief ─────────────────────

def build_brief(wb, analysis):
    ws = wb.create_sheet("📋 Daily Brief")
    ws.sheet_view.showGridLines = False
    for row in ws.iter_rows(min_row=1, max_row=80, min_col=1, max_col=14):
        for cell in row:
            cell.fill = hex_fill(C["bg_dark"])

    set_col_widths(ws, {"A": 2, "B": 16, "C": 60, "D": 2})
    ws.row_dimensions[1].height = 30

    ws.merge_cells("B1:C1")
    t = ws["B1"]
    t.value = "  CLAUDE DAILY BRIEF"
    t.font = Font(name="Consolas", bold=True, color=C["accent"], size=13)
    t.fill = hex_fill(C["bg_dark"])
    t.alignment = Alignment(horizontal="left", vertical="center")

    sections = [
        ("REGIME",          analysis.get("regime", "")),
        ("SECTOR ROTATION", analysis.get("sector_rotation", "")),
        ("RISKS",           analysis.get("risks", "")),
        ("WATCHLIST NOTES", analysis.get("watchlist_notes", "")),
    ]

    row = 3
    for label, content in sections:
        ws.merge_cells(f"B{row}:C{row}")
        h = ws[f"B{row}"]
        h.value = f"  {label}"
        h.font = Font(name="Consolas", bold=True, color=C["gold"], size=9)
        h.fill = hex_fill(C["bg_mid"])
        h.alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[row].height = 18
        row += 1

        ws.merge_cells(f"B{row}:C{row}")
        d = ws[f"B{row}"]
        d.value = "  " + content
        d.font = Font(name="Consolas", color=C["text_white"], size=9)
        d.fill = hex_fill(C["bg_card"])
        d.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.row_dimensions[row].height = 36
        row += 2

    ws.merge_cells(f"B{row}:C{row}")
    h = ws[f"B{row}"]
    h.value = "  PORTFOLIO ALERTS"
    h.font = Font(name="Consolas", bold=True, color=C["gold"], size=9)
    h.fill = hex_fill(C["bg_mid"])
    h.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[row].height = 18
    row += 1

    signal_colors = {
        "ADD":   C["green"],
        "TRIM":  C["gold"],
        "HOLD":  C["text_dim"],
        "WATCH": C["accent"],
    }

    for alert in analysis.get("portfolio_alerts", []):
        ticker = alert.get("ticker", "")
        signal = alert.get("signal", "")
        reason = alert.get("reason", "")
        sig_color = signal_colors.get(signal.upper(), C["text_white"])

        c_ticker = ws.cell(row=row, column=2, value=ticker)
        style_data(c_ticker, bg=C["bg_card"], fg=C["accent"], bold=True, align="left")

        c_signal = ws.cell(row=row, column=3, value=f"[{signal}]  {reason}")
        style_data(c_signal, bg=C["bg_card"], fg=sig_color, align="left")
        ws.row_dimensions[row].height = 20
        row += 1

    return ws

# ── Sheet 3: Top Ideas ───────────────────────

def build_ideas(wb, analysis):
    ws = wb.create_sheet("🎯 Top Ideas")
    ws.sheet_view.showGridLines = False
    for row in ws.iter_rows(min_row=1, max_row=60, min_col=1, max_col=14):
        for cell in row:
            cell.fill = hex_fill(C["bg_dark"])

    set_col_widths(ws, {
        "A": 2, "B": 12, "C": 40, "D": 18, "E": 20, "F": 28
    })

    ws.merge_cells("B1:F1")
    t = ws["B1"]
    t.value = "  TOP 3 ACTIONABLE IDEAS"
    t.font = Font(name="Consolas", bold=True, color=C["accent"], size=13)
    t.fill = hex_fill(C["bg_dark"])
    t.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 30

    headers = ["TICKER", "THESIS", "ENTRY", "SIZING", "INVALIDATION"]
    for i, h in enumerate(headers):
        c = ws.cell(row=3, column=2+i, value=h)
        style_header(c, bg=C["bg_mid"], fg=C["text_dim"], size=8)
    ws.row_dimensions[3].height = 18

    rank_colors = [C["gold"], C["text_white"], C["text_dim"]]

    for idea in analysis.get("top_ideas", []):
        rank = idea.get("rank", 1)
        row_num = 3 + rank
        row_bg = C["bg_card"] if rank % 2 == 0 else "1A2332"
        fc = rank_colors[min(rank-1, 2)]

        vals = [
            idea.get("ticker", ""),
            idea.get("thesis", ""),
            idea.get("entry", ""),
            idea.get("sizing", ""),
            idea.get("invalidation", ""),
        ]
        for i, v in enumerate(vals):
            c = ws.cell(row=row_num, column=2+i, value=v)
            style_data(c, bg=row_bg, fg=fc if i == 0 else C["text_white"], align="left")
        ws.row_dimensions[row_num].height = 40
        ws.cell(row=row_num, column=4).alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.cell(row=row_num, column=5).alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.cell(row=row_num, column=6).alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

    return ws

# ── Sheet 4: Portfolio P&L ───────────────────

def build_portfolio(wb, portfolio_data, audusd):
    ws = wb.create_sheet("💼 Portfolio")
    ws.sheet_view.showGridLines = False
    for row in ws.iter_rows(min_row=1, max_row=40, min_col=1, max_col=14):
        for cell in row:
            cell.fill = hex_fill(C["bg_dark"])

    set_col_widths(ws, {
        "A": 2, "B": 14, "C": 10, "D": 12, "E": 12,
        "F": 12, "G": 12, "H": 14, "I": 30
    })

    ws.merge_cells("B1:I1")
    t = ws["B1"]
    t.value = "  PORTFOLIO POSITIONS & P&L"
    t.font = Font(name="Consolas", bold=True, color=C["accent"], size=13)
    t.fill = hex_fill(C["bg_dark"])
    t.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 30

    headers = ["TICKER", "UNITS", "AVG COST", "CURR PRICE", "TODAY %", "P&L %", "MKT VALUE", "NOTES"]
    for i, h in enumerate(headers):
        c = ws.cell(row=3, column=2+i, value=h)
        style_header(c, bg=C["bg_mid"], fg=C["text_dim"], size=8)
    ws.row_dimensions[3].height = 18

    total_invested = 0
    total_value    = 0

    # FIX: ensure audusd is a usable float
    audusd_rate = audusd if isinstance(audusd, (int, float)) else 0.65

    for r, (ticker, cfg) in enumerate(PORTFOLIO.items(), start=4):
        d     = portfolio_data.get(ticker, {})
        price = d.get("price")
        chg   = d.get("change_pct", 0)
        units = cfg.get("units")
        avg   = cfg.get("avg_aud")
        note  = cfg.get("note", "")

        if price and units and avg and isinstance(price, (int, float)):
            if ticker.endswith(".AX"):
                price_aud = price
            else:
                price_aud = price / audusd_rate if audusd_rate else price
            mkt_val  = round(price_aud * units, 2)
            invested = round(avg * units, 2)
            pnl_pct  = round((price_aud - avg) / avg * 100, 2)
            total_invested += invested
            total_value    += mkt_val
        else:
            price_aud = price
            mkt_val   = "N/A"
            pnl_pct   = "N/A"
            invested  = "N/A"

        row_bg = C["bg_card"] if r % 2 == 0 else C["bg_mid"]
        fg_today = C["green"] if chg > 0 else (C["red"] if chg < 0 else C["text_dim"])
        fg_pnl   = (C["green"] if isinstance(pnl_pct, float) and pnl_pct > 0
                    else (C["red"] if isinstance(pnl_pct, float) and pnl_pct < 0
                    else C["text_dim"]))

        row_data = [
            (ticker,                     C["accent"]),
            (units or "—",               C["text_white"]),
            (f"A${avg:.2f}" if avg else "—", C["text_dim"]),
            (f"{price_aud:.3f}" if isinstance(price_aud, float) else "N/A", C["text_white"]),
            (f"{chg:+.2f}%",             fg_today),
            (f"{pnl_pct:+.2f}%" if isinstance(pnl_pct, float) else "N/A", fg_pnl),
            (f"A${mkt_val:,.0f}" if isinstance(mkt_val, float) else "N/A", C["text_white"]),
            (note,                       C["text_dim"]),
        ]
        for i, (v, fc) in enumerate(row_data):
            c = ws.cell(row=r, column=2+i, value=v)
            style_data(c, bg=row_bg, fg=fc, align="left" if i in (0, 7) else "right")
        ws.row_dimensions[r].height = 18

    tot_row = 4 + len(PORTFOLIO) + 1
    ws.merge_cells(f"B{tot_row}:F{tot_row}")
    c = ws[f"B{tot_row}"]
    c.value = "TOTAL PORTFOLIO"
    c.font = Font(name="Consolas", bold=True, color=C["gold"], size=9)
    c.fill = hex_fill(C["bg_mid"])
    c.alignment = Alignment(horizontal="left", vertical="center")

    tot_pnl = round((total_value - total_invested) / total_invested * 100, 2) if total_invested else 0
    c2 = ws.cell(row=tot_row, column=8,
                 value=f"A${total_value:,.0f}  ({tot_pnl:+.1f}%)")
    c2.font = Font(name="Consolas", bold=True,
                   color=C["green"] if tot_pnl > 0 else C["red"], size=9)
    c2.fill = hex_fill(C["bg_mid"])
    c2.alignment = Alignment(horizontal="right", vertical="center")
    ws.row_dimensions[tot_row].height = 20

    return ws

# ── Sheet 5: Watchlist ───────────────────────

def build_watchlist(wb, watchlist_data):
    ws = wb.create_sheet("👁 Watchlist")
    ws.sheet_view.showGridLines = False
    for row in ws.iter_rows(min_row=1, max_row=40, min_col=1, max_col=14):
        for cell in row:
            cell.fill = hex_fill(C["bg_dark"])

    set_col_widths(ws, {
        "A": 2, "B": 14, "C": 12, "D": 10, "E": 12, "F": 12, "G": 14
    })

    ws.merge_cells("B1:G1")
    t = ws["B1"]
    t.value = "  WATCHLIST"
    t.font = Font(name="Consolas", bold=True, color=C["accent"], size=13)
    t.fill = hex_fill(C["bg_dark"])
    t.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 30

    headers = ["TICKER", "PRICE", "TODAY %", "52W HIGH", "52W LOW", "VS 52W HIGH"]
    for i, h in enumerate(headers):
        c = ws.cell(row=3, column=2+i, value=h)
        style_header(c, bg=C["bg_mid"], fg=C["text_dim"], size=8)
    ws.row_dimensions[3].height = 18

    for r, ticker in enumerate(WATCHLIST, start=4):
        d     = watchlist_data.get(ticker, {})
        price = d.get("price")
        chg   = d.get("change_pct", 0)
        hi52  = d.get("52w_high")
        lo52  = d.get("52w_low")

        vs_high = (
            round((price - hi52) / hi52 * 100, 1)
            if isinstance(price, (int, float)) and isinstance(hi52, (int, float)) and hi52 != 0
            else "N/A"
        )

        row_bg = C["bg_card"] if r % 2 == 0 else C["bg_mid"]
        fg_chg  = C["green"] if chg > 0 else (C["red"] if chg < 0 else C["text_dim"])
        fg_vs   = (C["green"] if isinstance(vs_high, float) and vs_high > -10
                   else (C["gold"] if isinstance(vs_high, float) and vs_high > -25
                   else C["red"]))

        vals = [
            (ticker,                                         C["accent"]),
            (price if isinstance(price, (int, float)) else "N/A", C["text_white"]),
            (f"{chg:+.2f}%",                                fg_chg),
            (hi52 if isinstance(hi52, (int, float)) else "N/A",   C["text_dim"]),
            (lo52 if isinstance(lo52, (int, float)) else "N/A",   C["text_dim"]),
            (f"{vs_high:+.1f}%" if isinstance(vs_high, float) else "N/A", fg_vs),
        ]
        for i, (v, fc) in enumerate(vals):
            c = ws.cell(row=r, column=2+i, value=v)
            style_data(c, bg=row_bg, fg=fc, align="left" if i == 0 else "right")
        ws.row_dimensions[r].height = 16

    return ws

# ─────────────────────────────────────────────
# 6. MAIN
# ─────────────────────────────────────────────

def main():
    today_str = datetime.date.today().strftime("%d %b %Y")
    print(f"\n{'─'*50}")
    print(f"  MARKET BRIEF  //  {today_str}")
    print(f"{'─'*50}")

    if ANTHROPIC_API_KEY == "YOUR_API_KEY_HERE":
        print("\n❌  Set your ANTHROPIC_API_KEY in the script or as an environment variable.")
        sys.exit(1)

    print("\n[1/4] Fetching macro data...")
    macro_tickers = list(MACRO.values())
    macro_raw = fetch_price_data(macro_tickers)
    macro_data = {}
    for name, ticker in MACRO.items():
        macro_data[name] = macro_raw.get(ticker, {})

    print("[2/4] Fetching portfolio data...")
    port_tickers = list(PORTFOLIO.keys())
    portfolio_data = fetch_price_data(port_tickers)

    print("[3/4] Fetching watchlist data...")
    watchlist_data = fetch_price_data(WATCHLIST)

    audusd_raw = fetch_price_data(["AUDUSD=X"])
    audusd_val = audusd_raw.get("AUDUSD=X", {}).get("price", 0.65)
    # FIX: guarantee audusd is always a float, never a string
    audusd = audusd_val if isinstance(audusd_val, (int, float)) else 0.65

    print("[4/4] Calling Claude for analysis...")
    market_context = build_market_context(portfolio_data, macro_data, watchlist_data, audusd)
    try:
        analysis = get_claude_analysis(market_context)
        print("      ✓ Analysis complete")
    except Exception as e:
        print(f"      ✗ Claude error (full): {e}")
        print(f"      ✗ Error type: {type(e).__name__}")
        analysis = {
            "regime":           f"Claude API error: {str(e)[:120]}",
            "sector_rotation":  "N/A",
            "portfolio_alerts": [],
            "top_ideas":        [],
            "risks":            "N/A",
            "watchlist_notes":  "N/A",
        }

    print("\nBuilding Excel workbook...")
    wb = Workbook()
    del wb[wb.sheetnames[0]]

    build_dashboard(wb, analysis, macro_data, portfolio_data, audusd, today_str)
    build_brief(wb, analysis)
    build_ideas(wb, analysis)
    build_portfolio(wb, portfolio_data, audusd)
    build_watchlist(wb, watchlist_data)

    out_path = OUTPUT_FILE
    wb.save(out_path)
    print(f"\n✅  Saved → {out_path}")
    print(f"{'─'*50}\n")


if __name__ == "__main__":
    main()


# ─────────────────────────────────────────────
# QUICK SETUP GUIDE
# ─────────────────────────────────────────────
#
# 1. INSTALL DEPENDENCIES
#    pip install yfinance openpyxl anthropic
#
# 2. SET YOUR API KEY (choose one):
#    a) Edit ANTHROPIC_API_KEY = "sk-ant-..." in this file
#    b) Set environment variable:
#         Mac/Linux:  export ANTHROPIC_API_KEY="sk-ant-..."
#         Windows:    set ANTHROPIC_API_KEY=sk-ant-...
#
# 3. FILL IN YOUR PORTFOLIO
#    Edit the PORTFOLIO dict at the top with your units and avg costs.
#    Tickers ending in .AX are ASX stocks (prices in AUD).
#    All others are US stocks (script converts to AUD via live rate).
#
# 4. RUN
#    python market_brief.py
#    Opens Market_Brief.xlsx in the same folder.
#
# 5. SCHEDULE (optional)
#    Mac/Linux — add to crontab (runs weekdays at 7am):
#      0 7 * * 1-5 cd /path/to/script && python market_brief.py
#
#    Windows — Task Scheduler:
#      Action: python C:\path\to\market_brief.py
#      Trigger: Daily, weekdays, 7:00 AM
#
# 6. AUTO-OPEN (optional, Mac)
#    Change OUTPUT_FILE to an absolute path, then add to cron:
#      0 7 * * 1-5 cd ~/Desktop && python market_brief.py && open Market_Brief.xlsx
#
# ─────────────────────────────────────────────
