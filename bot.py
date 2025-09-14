# bot.py
import os
import pandas as pd
import numpy as np
import time
import requests
import ta
import telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import asyncio
from datetime import datetime, timezone

# ---------------- CONFIG ----------------
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
SYMBOL = os.getenv('SYMBOL', 'BTCUSDT')
INTERVAL = os.getenv('INTERVAL', '15m')  # e.g. 1m,5m,15m
KLIMIT = int(os.getenv('KLIMIT', '100'))
CHECK_SECONDS = int(os.getenv('CHECK_SECONDS', '300'))  # default 5 minutes
HEADERS = {"User-Agent": "pro-scalper-bot/1.0"}
# ----------------------------------------

bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)

# ---------------- Helpers ----------------
def send_telegram_sync(message: str):
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='HTML')
        print("Telegram message sent.")
    except Exception as e:
        print("Telegram send error:", e)

async def send_telegram(message: str):
    # async wrapper for consistency with main loop
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, send_telegram_sync, message)

def fetch_klines_public(symbol: str, interval: str = "15m", limit: int = 100):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(url, params=params, headers=HEADERS, timeout=8)
    r.raise_for_status()
    data = r.json()
    df = pd.DataFrame(data, columns=[
        "open_time","open","high","low","close","volume","close_time",
        "quote_asset_volume","num_trades","taker_buy_base","taker_buy_quote","ignore"
    ])
    numeric_cols = ["open","high","low","close","volume"]
    df[numeric_cols] = df[numeric_cols].astype(float)
    df['datetime'] = pd.to_datetime(df['close_time'], unit='ms', utc=True)
    return df

def fetch_orderbook_public(symbol: str, limit: int = 50):
    url = "https://api.binance.com/api/v3/depth"
    params = {"symbol": symbol, "limit": limit}
    r = requests.get(url, params=params, headers=HEADERS, timeout=6)
    r.raise_for_status()
    return r.json()

# ---------------- Indicators ----------------
def compute_indicators(df: pd.DataFrame):
    # ensure 'close' exists as float
    df = df.copy()
    df['close_f'] = df['close'].astype(float)
    df['volume_f'] = df['volume'].astype(float)
    df['EMA9'] = df['close_f'].ewm(span=9, adjust=False).mean()
    df['EMA21'] = df['close_f'].ewm(span=21, adjust=False).mean()
    # RSI 14
    delta = df['close_f'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(alpha=1/14, adjust=False).mean()
    ma_down = down.ewm(alpha=1/14, adjust=False).mean()
    rs = ma_up / (ma_down + 1e-9)
    df['RSI14'] = 100 - (100 / (1 + rs))
    # VWAP
    pv = (df['close_f'] * df['volume_f'])
    df['VWAP'] = pv.cumsum() / df['volume_f'].cumsum()
    # ATR (simple EMA method)
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['ATR14'] = tr.ewm(span=14, adjust=False).mean()
    return df

def analyze_and_signal(df: pd.DataFrame, symbol: str):
    df = compute_indicators(df)
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest

    price = float(latest['close_f'])
    ema9 = float(latest['EMA9'])
    ema21 = float(latest['EMA21'])
    rsi = float(latest['RSI14'])
    vwap_now = float(latest['VWAP'])
    atr = float(latest['ATR14'])
    last_vol = float(latest['volume_f'])
    avg_vol = float(df['volume_f'][-30:].mean()) if len(df) >= 30 else float(df['volume_f'].mean())

    vol_spike = last_vol > (avg_vol * 1.6)

    # EMA crossover detection
    prev_ema9 = float(prev['EMA9']) if 'EMA9' in prev else ema9
    prev_ema21 = float(prev['EMA21']) if 'EMA21' in prev else ema21
    crossover = None
    if prev_ema9 <= prev_ema21 and ema9 > ema21:
        crossover = "bullish"
    elif prev_ema9 >= prev_ema21 and ema9 < ema21:
        crossover = "bearish"

    # orderbook imbalance (public)
    try:
        ob = fetch_orderbook_public(symbol, limit=20)
        bids = ob.get('bids', [])[:20]
        asks = ob.get('asks', [])[:20]
        sum_bids = sum([float(b[1]) for b in bids]) if bids else 0.0
        sum_asks = sum([float(a[1]) for a in asks]) if asks else 0.0
        imbalance = (sum_bids - sum_asks) / (sum_bids + sum_asks + 1e-9)
    except Exception:
        imbalance = 0.0

    # score
    score = 50
    reasons = []
    if crossover == "bullish":
        score += 15; reasons.append("EMA bullish crossover")
    elif crossover == "bearish":
        score -= 15; reasons.append("EMA bearish crossover")
    else:
        score += 5 if ema9 > ema21 else -5

    if rsi < 40:
        score += 12; reasons.append("RSI low (buy)")
    if rsi > 60:
        score -= 12; reasons.append("RSI high (sell)")

    if vol_spike:
        score += 18; reasons.append("Volume spike")

    if imbalance > 0.12:
        score += 10; reasons.append("Orderbook bid-heavy")
    elif imbalance < -0.12:
        score -= 10; reasons.append("Orderbook ask-heavy")

    if price > vwap_now:
        score += 4
    else:
        score -= 4

    # Normalize
    confidence = max(0, min(100, int(score)))

    action = None
    if confidence >= 55:
        action = "BUY" if score >= 60 else None
    if confidence >= 55 and score <= 40:
        action = "SELL"

    # SL/TP using ATR (scalper style)
    sl = tp = None
    if action:
        sl_distance = max(atr, 1e-8) * 1.0
        if action == "BUY":
            sl = price - sl_distance
            tp = price + sl_distance * 1.8
        else:
            sl = price + sl_distance
            tp = price - sl_distance * 1.8

    return {
        "symbol": symbol,
        "price": price,
        "action": action,
        "confidence": confidence,
        "reasons": reasons,
        "sl": sl,
        "tp": tp,
        "volume": last_vol,
        "avg_volume": avg_vol,
        "imbalance": imbalance,
        "rsi": rsi,
        "ema9": ema9,
        "ema21": ema21
    }

# ---------------- Main trading loop ----------------
async def trading_loop():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing in env. Exiting trading loop.")
        return

    print("🤖 Trading loop started. Using public Binance market endpoints (no API key needed).")
    while True:
        try:
            df = fetch_klines_public(SYMBOL, INTERVAL, KLIMIT)
            res = analyze_and_signal(df, SYMBOL)

            if res['action']:
                message = (
                    f"🚨 <b>{res['symbol']} {res['action']} Signal</b>\n"
                    f"🕜 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                    f"💰 Price: {res['price']}\n"
                    f"🔎 Reasons: {', '.join(res['reasons'])}\n"
                    f"🎯 TP: {res['tp']}\n"
                    f"🛑 SL: {res['sl']}\n"
                    f"✅ Confidence: {res['confidence']}%\n"
                )
                await send_telegram(message)
                print("Signal sent:", res['action'], res['confidence'])
            else:
                print(f"No strong signal. Confidence={res['confidence']} | {datetime.now(timezone.utc)}")

        except requests.HTTPError as he:
            print("HTTP error while fetching market data:", he)
            await send_telegram(f"❌ Market data HTTP error: {he}")
        except Exception as e:
            print("Unexpected error in trading loop:", e)
            await send_telegram(f"❌ Trading loop error: {e}")

        await asyncio.sleep(CHECK_SECONDS)

# ---------------- Telegram bot handlers & main ----------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello — public-data scalper bot is running.")

async def unknown_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Unknown command.")

async def main():
    print("🤖 Bot starting (Render-friendly, public endpoints).")
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT, unknown_handler))

    await asyncio.gather(
        application.run_polling(),
        trading_loop()
    )

if __name__ == "__main__":
    asyncio.run(main())

