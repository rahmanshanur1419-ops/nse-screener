from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import numpy as np

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ── NSE Stocks List ──
NSE_STOCKS = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "BAJFINANCE", "LT", "SUNPHARMA", "MARUTI", "WIPRO",
    "KOTAKBANK", "ADANIENT", "POWERGRID", "ASIANPAINT", "TATAMOTORS"
]

# ── Supertrend Calculator ──
def calc_supertrend(df, period=10, multiplier=3):
    try:
        high = df['High']
        low  = df['Low']
        close = df['Close']

        # True Range
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs()
        ], axis=1).max(axis=1)

        atr = tr.ewm(span=period, adjust=False).mean()
        hl2 = (high + low) / 2

        upper_band = hl2 + multiplier * atr
        lower_band = hl2 - multiplier * atr

        supertrend = [np.nan] * len(df)
        direction  = [1] * len(df)   # 1 = bullish, -1 = bearish

        for i in range(1, len(df)):
            # Upper band
            if upper_band.iloc[i] < upper_band.iloc[i-1] or close.iloc[i-1] > upper_band.iloc[i-1]:
                upper_band.iloc[i] = upper_band.iloc[i]
            else:
                upper_band.iloc[i] = upper_band.iloc[i-1]

            # Lower band
            if lower_band.iloc[i] > lower_band.iloc[i-1] or close.iloc[i-1] < lower_band.iloc[i-1]:
                lower_band.iloc[i] = lower_band.iloc[i]
            else:
                lower_band.iloc[i] = lower_band.iloc[i-1]

            # Direction
            if close.iloc[i] > upper_band.iloc[i-1]:
                direction[i] = 1
            elif close.iloc[i] < lower_band.iloc[i-1]:
                direction[i] = -1
            else:
                direction[i] = direction[i-1]

            supertrend[i] = lower_band.iloc[i] if direction[i] == 1 else upper_band.iloc[i]

        last_close = close.iloc[-1]
        last_st    = supertrend[-1]
        prev_dir   = direction[-2]
        curr_dir   = direction[-1]

        if curr_dir == 1 and prev_dir == -1:
            status = "Broken Above"   # Fresh breakout this week
        elif curr_dir == 1:
            status = "Above"          # Already above
        else:
            status = "Below"          # Bearish

        trend = "Strong Bullish" if curr_dir == 1 and prev_dir == -1 else \
                "Bullish"        if curr_dir == 1 else \
                "Bearish"

        return status, trend, round(last_st, 2) if last_st else 0

    except Exception as e:
        return "Unknown", "Neutral", 0


# ── Volume Check ──
def get_volume_label(df):
    try:
        avg_vol  = df['Volume'].iloc[:-1].mean()
        last_vol = df['Volume'].iloc[-1]
        ratio = last_vol / avg_vol if avg_vol > 0 else 1
        if ratio > 1.8:  return "Very High"
        if ratio > 1.2:  return "High"
        if ratio > 0.8:  return "Average"
        return "Below Average"
    except:
        return "Average"


# ── Single Stock Endpoint ──
@app.get("/stock/{symbol}")
def get_stock(symbol: str):
    try:
        sym = symbol.upper() + ".NS"
        tk  = yf.Ticker(sym)
        info = tk.info

        # Weekly OHLC for Supertrend
        hist_weekly = tk.history(period="1y", interval="1wk")
        # Quarterly for growth calcs
        hist_qtr    = tk.history(period="1y", interval="3mo")

        st_status, trend, st_val = calc_supertrend(hist_weekly)
        vol_label = get_volume_label(hist_weekly)

        # Revenue & Profit Growth (QoQ from quarterly financials)
        fin = tk.quarterly_financials
        rev_qoq  = 0
        prof_qoq = 0
        if fin is not None and not fin.empty:
            try:
                rev  = fin.loc['Total Revenue'] if 'Total Revenue' in fin.index else None
                prof = fin.loc['Net Income']    if 'Net Income'    in fin.index else None
                if rev  is not None and len(rev)  >= 2:
                    rev_qoq  = round((rev.iloc[0] - rev.iloc[1]) / abs(rev.iloc[1]) * 100, 1)
                if prof is not None and len(prof) >= 2:
                    prof_qoq = round((prof.iloc[0] - prof.iloc[1]) / abs(prof.iloc[1]) * 100, 1)
            except:
                pass

        price         = round(info.get("currentPrice") or info.get("regularMarketPrice") or 0, 2)
        change        = round(info.get("regularMarketChangePercent") or 0, 2)
        mkt_cap       = info.get("marketCap") or 0
        mkt_cap_str   = f"₹{round(mkt_cap/1e7):,} Cr" if mkt_cap else "N/A"

        return {
            "ticker":        symbol.upper(),
            "name":          info.get("longName") or info.get("shortName") or symbol,
            "sector":        info.get("sector") or "N/A",
            "price":         price,
            "change":        change,
            "mktCap":        mkt_cap_str,
            "revGrowthQoQ":  rev_qoq,
            "profGrowthQoQ": prof_qoq,
            "revGrowthYoY":  round(info.get("revenueGrowth", 0) * 100, 1) if info.get("revenueGrowth") else 0,
            "epsGrowthYoY":  round(info.get("earningsGrowth", 0) * 100, 1) if info.get("earningsGrowth") else 0,
            "currentRatio":  round(info.get("currentRatio") or 0, 2),
            "quickRatio":    round(info.get("quickRatio") or 0, 2),
            "roe":           round((info.get("returnOnEquity") or 0) * 100, 1),
            "roce":          round((info.get("returnOnAssets") or 0) * 100, 1),
            "dte":           round((info.get("debtToEquity") or 0) / 100, 2),
            "netMargin":     round((info.get("profitMargins") or 0) * 100, 1),
            "opMargin":      round((info.get("operatingMargins") or 0) * 100, 1),
            "ocf":           round((info.get("operatingCashflow") or 0) / 1e7, 1),
            "fcf":           round((info.get("freeCashflow") or 0) / 1e7, 1),
            "surprise":      0,
            "supertrend":    st_status,
            "stValue":       st_val,
            "trend":         trend,
            "volume":        vol_label,
            "breakout":      st_status == "Broken Above",
            "signal":        "BUY" if st_status == "Broken Above" else
                             "AVOID" if st_status == "Below" else "WATCHLIST"
        }
    except Exception as e:
        return {"error": str(e), "ticker": symbol}


# ── All Stocks Endpoint ──
@app.get("/all")
def get_all():
    results = []
    for sym in NSE_STOCKS:
        data = get_stock(sym)
        if "error" not in data:
            results.append(data)
    return results


# ── Search Endpoint ──
@app.get("/search/{query}")
def search_stock(query: str):
    sym = query.upper().strip()
    return get_stock(sym)