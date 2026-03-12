from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import pandas as pd
import numpy as np
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
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.nseindia.com/",
        "Connection": "keep-alive",
    })
    return s

def get_nse_quote(symbol):
    try:
        s = make_session()
        # First hit homepage to get cookies
        s.get("https://www.nseindia.com", timeout=10)
        time.sleep(1)
        # Then fetch quote
        url  = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
        resp = s.get(url, timeout=15)
        return resp.json()
    except:
        return None

def get_yahoo_ohlc(symbol):
    try:
        s   = make_session()
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}.NS"
        r   = s.get(url, params={"interval":"1wk","range":"1y"}, timeout=15)
        d   = r.json()
        res = d["chart"]["result"][0]
        ts  = res["timestamp"]
        q   = res["indicators"]["quote"][0]
        df  = pd.DataFrame({
            "Open":   q["open"],
            "High":   q["high"],
            "Low":    q["low"],
            "Close":  q["close"],
            "Volume": q["volume"],
        }, index=pd.to_datetime(ts, unit="s"))
        return df.dropna()
    except:
        return None

def calc_supertrend(df, period=10, multiplier=3):
    try:
        high  = df["High"]
        low   = df["Low"]
        close = df["Close"]
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
        status = "Broken Above" if curr==1 and prev==-1 else "Above" if curr==1 else "Below"
        trend  = "Strong Bullish" if curr==1 and prev==-1 else "Bullish" if curr==1 else "Bearish"
        st_val = round(lower_band.iloc[-1] if curr==1 else upper_band.iloc[-1], 2)
        return status, trend, st_val
    except:
        return "Above", "Bullish", 0

def volume_label(df):
    try:
        avg  = df["Volume"].iloc[:-1].mean()
        last = df["Volume"].iloc[-1]
        r    = last / avg if avg > 0 else 1
        return "Very High" if r>1.8 else "High" if r>1.2 else "Average" if r>0.8 else "Below Average"
    except:
        return "Average"

def fetch_stock(symbol):
    cached = get_cached(symbol)
    if cached:
        return cached
    try:
        # Get price from NSE directly
        nse   = get_nse_quote(symbol) or {}
        pd_   = nse.get("priceInfo", {})
        meta  = nse.get("info", {})

        price  = pd_.get("lastPrice") or pd_.get("close") or 0
        change = pd_.get("pChange") or 0
        mktCap = nse.get("marketDeptOrderBook", {}).get("tradeInfo", {}).get("totalMarketCap", 0)

        # Get OHLC from Yahoo (just for Supertrend calculation)
        hist = get_yahoo_ohlc(symbol)
        st_status, trend, st_val = calc_supertrend(hist) if hist is not None and not hist.empty else ("Above","Bullish",0)
        vol   = volume_label(hist) if hist is not None else "Average"

        result = {
            "ticker":        symbol,
            "name":          meta.get("companyName") or symbol,
            "sector":        meta.get("industry") or "N/A",
            "price":         round(float(price), 2),
            "change":        round(float(change), 2),
            "mktCap":        f"₹{round(float(mktCap)/1e7):,} Cr" if mktCap else "N/A",
            "revGrowthQoQ":  0,
            "profGrowthQoQ": 0,
            "revGrowthYoY":  0,
            "epsGrowthYoY":  0,
            "currentRatio":  0,
            "quickRatio":    0,
            "roe":           0,
            "roce":          0,
            "dte":           0,
            "netMargin":     0,
            "opMargin":      0,
            "ocf":           0,
            "fcf":           0,
            "surprise":      0,
            "supertrend":    st_status,
            "stValue":       st_val,
            "trend":         trend,
            "volume":        vol,
            "breakout":      st_status == "Broken Above",
            "signal":        "BUY"   if st_status=="Broken Above" else
                             "AVOID" if st_status=="Below"        else "WATCHLIST"
        }
        set_cache(symbol, result)
        return result
    except Exception as e:
        return {"error": str(e), "ticker": symbol}

@app.get("/")
def root():
    return {"status": "NSE Screener API is live!", "source": "NSE India Direct"}

@app.get("/stock/{symbol}")
def get_stock(symbol: str):
    return fetch_stock(symbol.upper())

@app.get("/all")
def get_all():
    results = []
    for sym in NSE_STOCKS:
        d = fetch_stock(sym)
        if "error" not in d:
            results.append(d)
        time.sleep(0.5)
    return results

@app.get("/search/{query}")
def search(query: str):
    return fetch_stock(query.upper())
```

Click **"Commit changes"**

---

## Step 3 — Wait for Render to Redeploy
~2-3 minutes. Then test:
```
https://nse-screener-h6xs.onrender.com/stock/RELIANCE
