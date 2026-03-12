from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

NSE_STOCKS = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "BAJFINANCE", "LT", "SUNPHARMA", "MARUTI", "WIPRO",
    "KOTAKBANK", "ADANIENT", "POWERGRID", "ASIANPAINT", "TATAMOTORS"
]

cache = {}
CACHE_TTL = 600

def get_cached(key):
    if key in cache:
        data, ts = cache[key]
        if time.time() - ts < CACHE_TTL:
            return data
    return None

def set_cache(key, data):
    cache[key] = (data, time.time())

def make_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    })
    return session

def calc_supertrend(df, period=10, multiplier=3):
    try:
        high  = df['High']
        low   = df['Low']
        close = df['Close']
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs()
        ], axis=1).max(axis=1)
        atr        = tr.ewm(span=period, adjust=False).mean()
        hl2        = (high + low) / 2
        upper_band = (hl2 + multiplier * atr).copy()
        lower_band = (hl2 - multiplier * atr).copy()
        direction  = [1] * len(df)
        for i in range(1, len(df)):
            upper_band.iloc[i] = upper_band.iloc[i] if upper_band.iloc[i] < upper_band.iloc[i-1] or close.iloc[i-1] > upper_band.iloc[i-1] else upper_band.iloc[i-1]
            lower_band.iloc[i] = lower_band.iloc[i] if lower_band.iloc[i] > lower_band.iloc[i-1] or close.iloc[i-1] < lower_band.iloc[i-1] else lower_band.iloc[i-1]
            if   close.iloc[i] > upper_band.iloc[i-1]: direction[i] =  1
            elif close.iloc[i] < lower_band.iloc[i-1]: direction[i] = -1
            else:                                       direction[i] =  direction[i-1]
        curr   = direction[-1]
        prev   = direction[-2]
        status = "Broken Above" if curr == 1 and prev == -1 else "Above" if curr == 1 else "Below"
        trend  = "Strong Bullish" if curr == 1 and prev == -1 else "Bullish" if curr == 1 else "Bearish"
        st_val = round(lower_band.iloc[-1] if curr == 1 else upper_band.iloc[-1], 2)
        return status, trend, st_val
    except:
        return "Unknown", "Neutral", 0

def volume_label(df):
    try:
        avg  = df['Volume'].iloc[:-1].mean()
        last = df['Volume'].iloc[-1]
        r    = last / avg if avg > 0 else 1
        return "Very High" if r > 1.8 else "High" if r > 1.2 else "Average" if r > 0.8 else "Below Average"
    except:
        return "Average"

def fetch_stock(symbol):
    cached = get_cached(symbol)
    if cached:
        return cached
    try:
        time.sleep(2)
        session = make_session()
        tk      = yf.Ticker(symbol + ".NS", session=session)
        info    = tk.info or {}
        hist    = tk.history(period="1y", interval="1wk")
        if hist.empty:
            return {"error": "No data", "ticker": symbol}

        st_status, trend, st_val = calc_supertrend(hist)
        vol = volume_label(hist)

        rev_qoq = prof_qoq = 0
        try:
            fin  = tk.quarterly_financials
            if fin is not None and not fin.empty:
                rev  = fin.loc['Total Revenue'] if 'Total Revenue' in fin.index else None
                prof = fin.loc['Net Income']    if 'Net Income'    in fin.index else None
                if rev  is not None and len(rev)  >= 2:
                    rev_qoq  = round((rev.iloc[0]  - rev.iloc[1])  / abs(rev.iloc[1])  * 100, 1)
                if prof is not None and len(prof) >= 2:
                    prof_qoq = round((prof.iloc[0] - prof.iloc[1]) / abs(prof.iloc[1]) * 100, 1)
        except:
            pass

        price   = round(info.get("currentPrice") or info.get("regularMarketPrice") or 0, 2)
        change  = round(info.get("regularMarketChangePercent") or 0, 2)
        mkt_cap = info.get("marketCap") or 0

        result = {
            "ticker":        symbol,
            "name":          info.get("longName") or info.get("shortName") or symbol,
            "sector":        info.get("sector") or "N/A",
            "price":         price,
            "change":        change,
            "mktCap":        f"₹{round(mkt_cap/1e7):,} Cr" if mkt_cap else "N/A",
            "revGrowthQoQ":  rev_qoq,
            "profGrowthQoQ": prof_qoq,
            "revGrowthYoY":  round((info.get("revenueGrowth")  or 0) * 100, 1),
            "epsGrowthYoY":  round((info.get("earningsGrowth") or 0) * 100, 1),
            "currentRatio":  round(info.get("currentRatio") or 0, 2),
            "quickRatio":    round(info.get("quickRatio")   or 0, 2),
            "roe":           round((info.get("returnOnEquity")  or 0) * 100, 1),
            "roce":          round((info.get("returnOnAssets")  or 0) * 100, 1),
            "dte":           round((info.get("debtToEquity")    or 0) / 100, 2),
            "netMargin":     round((info.get("profitMargins")   or 0) * 100, 1),
            "opMargin":      round((info.get("operatingMargins") or 0) * 100, 1),
            "ocf":           round((info.get("operatingCashflow") or 0) / 1e7, 1),
            "fcf":           round((info.get("freeCashflow")     or 0) / 1e7, 1),
            "surprise":      0,
            "supertrend":    st_status,
            "stValue":       st_val,
            "trend":         trend,
            "volume":        vol,
            "breakout":      st_status == "Broken Above",
            "signal":        "BUY"       if st_status == "Broken Above" else
                             "AVOID"     if st_status == "Below"        else "WATCHLIST"
        }
        set_cache(symbol, result)
        return result
    except Exception as e:
        return {"error": str(e), "ticker": symbol}

@app.get("/")
def root():
    return {"status": "NSE Screener API is live!"}

@app.get("/stock/{symbol}")
def get_stock(symbol: str):
    return fetch_stock(symbol.upper())

@app.get("/all")
def get_all():
    return [d for sym in NSE_STOCKS if "error" not in (d := fetch_stock(sym))]

@app.get("/search/{query}")
def search(query: str):
    return fetch_stock(query.upper())
```

---

### Step 6 — Commit Changes
Scroll down → Click **"Commit changes"** → Click **"Commit changes"** again

---

### Step 7 — Wait for Render to Redeploy
Render auto-detects GitHub changes and redeploys in ~2 minutes. Then test:
```
https://nse-screener-h6xs.onrender.com/stock/RELIANCE
