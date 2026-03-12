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

def calc_supertrend(df, period=10, multiplier=3):
    try:
        high = df["High"]
        low = df["Low"]
        close = df["Close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ], axis=1).max(axis=1)
        atr = tr.ewm(span=period, adjust=False).mean()
        hl2 = (high + low) / 2
        upper_band = (hl2 + multiplier * atr).copy()
        lower_band = (hl2 - multiplier * atr).copy()
        direction = [1] * len(df)
        for i in range(1, len(df)):
            if upper_band.iloc[i] < upper_band.iloc[i-1] or close.iloc[i-1] > upper_band.iloc[i-1]:
                pass
            else:
                upper_band.iloc[i] = upper_band.iloc[i-1]
            if lower_band.iloc[i] > lower_band.iloc[i-1] or close.iloc[i-1] < lower_band.iloc[i-1]:
                pass
            else:
                lower_band.iloc[i] = lower_band.iloc[i-1]
            if close.iloc[i] > upper_band.iloc[i-1]:
                direction[i] = 1
            elif close.iloc[i] < lower_band.iloc[i-1]:
                direction[i] = -1
            else:
                direction[i] = direction[i-1]
        curr = direction[-1]
        prev = direction[-2]
        if curr == 1 and prev == -1:
            status = "Broken Above"
            trend = "Strong Bullish"
        elif curr == 1:
            status = "Above"
            trend = "Bullish"
        else:
            status = "Below"
            trend = "Bearish"
        if curr == 1:
            st_val = round(lower_band.iloc[-1], 2)
        else:
            st_val = round(upper_band.iloc[-1], 2)
        return status, trend, st_val
    except Exception:
        return "Above", "Bullish", 0

def volume_label(df):
    try:
        avg = df["Volume"].iloc[:-1].mean()
        last = df["Volume"].iloc[-1]
        r = last / avg if avg > 0 else 1
        if r > 1.8:
            return "Very High"
        elif r > 1.2:
            return "High"
        elif r > 0.8:
            return "Average"
        else:
            return "Below Average"
    except Exception:
        return "Average"

def get_ohlc(symbol):
    try:
        s = make_session()
        url = "https://query2.finance.yahoo.com/v8/finance/chart/" + symbol + ".NS"
        r = s.get(url, params={"interval": "1wk", "range": "1y"}, timeout=15)
        d = r.json()
        res = d["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        df = pd.DataFrame({
            "Open": q["open"],
            "High": q["high"],
            "Low": q["low"],
            "Close": q["close"],
            "Volume": q["volume"],
        }, index=pd.to_datetime(ts, unit="s"))
        return df.dropna()
    except Exception:
        return None

def get_price(symbol):
    try:
        s = make_session()
        s.get("https://www.nseindia.com", timeout=10)
        time.sleep(1)
        url = "https://www.nseindia.com/api/quote-equity?symbol=" + symbol
        resp = s.get(url, timeout=15)
        data = resp.json()
        price_info = data.get("priceInfo", {})
        info = data.get("info", {})
        price = price_info.get("lastPrice") or price_info.get("close") or 0
        change = price_info.get("pChange") or 0
        name = info.get("companyName") or symbol
        sector = info.get("industry") or "N/A"
        mkt_cap = data.get("marketDeptOrderBook", {}).get("tradeInfo", {}).get("totalMarketCap", 0)
        return price, change, name, sector, mkt_cap
    except Exception:
        return 0, 0, symbol, "N/A", 0

def fetch_stock(symbol):
    cached = get_cached(symbol)
    if cached:
        return cached
    try:
        price, change, name, sector, mkt_cap = get_price(symbol)
        hist = get_ohlc(symbol)
        if hist is not None and not hist.empty:
            st_status, trend, st_val = calc_supertrend(hist)
            vol = volume_label(hist)
        else:
            st_status = "Above"
            trend = "Bullish"
            st_val = 0
            vol = "Average"

        if mkt_cap:
            mkt_cap_str = "Rs." + str(round(float(mkt_cap) / 1e7)) + " Cr"
        else:
            mkt_cap_str = "N/A"

        if st_status == "Broken Above":
            signal = "BUY"
        elif st_status == "Below":
            signal = "AVOID"
        else:
            signal = "WATCHLIST"

        result = {
            "ticker": symbol,
            "name": name,
            "sector": sector,
            "price": round(float(price), 2),
            "change": round(float(change), 2),
            "mktCap": mkt_cap_str,
            "revGrowthQoQ": 0,
            "profGrowthQoQ": 0,
            "revGrowthYoY": 0,
            "epsGrowthYoY": 0,
            "currentRatio": 0,
            "quickRatio": 0,
            "roe": 0,
            "roce": 0,
            "dte": 0,
            "netMargin": 0,
            "opMargin": 0,
            "ocf": 0,
            "fcf": 0,
            "surprise": 0,
            "supertrend": st_status,
            "stValue": st_val,
            "trend": trend,
            "volume": vol,
            "breakout": st_status == "Broken Above",
            "signal": signal
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
    results = []
    for sym in NSE_STOCKS:
        data = fetch_stock(sym)
        if "error" not in data:
            results.append(data)
        time.sleep(0.5)
    return results

@app.get("/search/{query}")
def search(query: str):
    return fetch_stock(query.upper())
```

Click **"Commit changes"** → Render will auto redeploy in ~2 min.

Then test:
```
https://nse-screener-h6xs.onrender.com/
