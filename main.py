from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import pandas as pd
import numpy as np
import time
import io

app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

NSE_STOCKS = ["RELIANCE","TCS","INFY","HDFCBANK","ICICIBANK","BAJFINANCE","LT","SUNPHARMA","MARUTI","WIPRO","KOTAKBANK","ADANIENT","POWERGRID","ASIANPAINT","TATAMOTORS"]

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

def get_ohlc(symbol):
    try:
        url = "https://stooq.com/q/d/l/?s=" + symbol.lower() + ".ns&i=w"
        r = requests.get(url, timeout=15)
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = [c.strip() for c in df.columns]
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        df = df[["Open","High","Low","Close","Volume"]].dropna()
        return df
    except Exception:
        return None

def calc_supertrend(df, period=10, multiplier=3):
    try:
        high = df["High"]
        low = df["Low"]
        close = df["Close"]
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        atr = tr.ewm(span=period, adjust=False).mean()
        hl2 = (high + low) / 2
        upper_band = (hl2 + multiplier * atr).copy()
        lower_band = (hl2 - multiplier * atr).copy()
        direction = [1] * len(df)
        for i in range(1, len(df)):
            if upper_band.iloc[i] >= upper_band.iloc[i-1] and close.iloc[i-1] <= upper_band.iloc[i-1]:
                upper_band.iloc[i] = upper_band.iloc[i-1]
            if lower_band.iloc[i] <= lower_band.iloc[i-1] and close.iloc[i-1] >= lower_band.iloc[i-1]:
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
        st_val = round(lower_band.iloc[-1] if curr == 1 else upper_band.iloc[-1], 2)
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

def fetch_stock(symbol):
    cached = get_cached(symbol)
    if cached:
        return cached
    try:
        df = get_ohlc(symbol)
        if df is None or df.empty:
            return {"error": "No data", "ticker": symbol}
        price = round(float(df["Close"].iloc[-1]), 2)
        prev_price = round(float(df["Close"].iloc[-2]), 2)
        change = round(((price - prev_price) / prev_price) * 100, 2) if prev_price else 0
        st_status, trend, st_val = calc_supertrend(df)
        vol = volume_label(df)
        if st_status == "Broken Above":
            signal = "BUY"
        elif st_status == "Below":
            signal = "AVOID"
        else:
            signal = "WATCHLIST"
        result = {
            "ticker": symbol, "name": symbol, "sector": "NSE",
            "price": price, "change": change, "mktCap": "N/A",
            "revGrowthQoQ": 0, "profGrowthQoQ": 0, "revGrowthYoY": 0,
            "epsGrowthYoY": 0, "currentRatio": 0, "quickRatio": 0,
            "roe": 0, "roce": 0, "dte": 0, "netMargin": 0, "opMargin": 0,
            "ocf": 0, "fcf": 0, "surprise": 0,
            "supertrend": st_status, "stValue": st_val, "trend": trend,
            "volume": vol, "breakout": st_status == "Broken Above", "signal": signal
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
        time.sleep(0.3)
    return results

@app.get("/search/{query}")
def search(query: str):
    return fetch_stock(query.upper())
