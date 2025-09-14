import os
import pandas as pd
import numpy as np
import time
import requests
from binance.client import Client
from binance.enums import *
from binance.exceptions import BinanceAPIException
import ta
import telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import asyncio
from datetime import datetime
import logging

# ============================
# CONFIGURATION
# ============================
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET')

# ============================
# INITIALIZE
# ============================
bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)

client = None
if BINANCE_API_KEY and BINANCE_API_SECRET:
    client = Client(BINANCE_API_KEY, BINANCE_API_SECRET, testnet=True)
    print("✅ Binance client initialized")
else:
    print("⚠️ Binance keys missing! Market data may not work.")

# ============================
# TELEGRAM FUNCTIONS
# ============================
async def send_telegram_message(message):
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        print(f"Message sent: {message}")
    except Exception as e:
        print(f"Telegram error: {e}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Hello! Trading Bot is active!')

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f'Update {update} caused error {context.error}')

# ============================
# TRADING FUNCTIONS
# ============================
def get_technical_indicators(df):
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
    macd = ta.trend.MACD(df['close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    bollinger = ta.volatility.BollingerBands(df['close'], window=20)
    df['bb_upper'] = bollinger.bollinger_hband()
    df['bb_lower'] = bollinger.bollinger_lband()
    return df

def check_signal(df):
    latest = df.iloc[-1]
    if latest['rsi'] > 50 and latest['close'] > latest['bb_upper']:
        return 'BUY'
    elif latest['rsi'] < 50 and latest['close'] < latest['bb_lower']:
        return 'SELL'
    return None

async def trading_loop():
    global client
    if not client:
        print("❌ Binance client not initialized. Exiting trading loop.")
        return

    while True:
        try:
            klines = client.get_klines(
                symbol='BTCUSDT',
                interval=Client.KLINE_INTERVAL_15MINUTE,
                limit=50
            )
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'trades',
                'taker_buy_base', 'taker_buy_quote', 'ignore'
            ])
            numeric_cols = ['open', 'high', 'low', 'close', 'volume']
            df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric)

            df = get_technical_indicators(df)
            signal = check_signal(df)

            if signal:
                message = f"🚀 {signal} Signal detected!\nPrice: {df['close'].iloc[-1]}\nRSI: {df['rsi'].iloc[-1]:.2f}"
                await send_telegram_message(message)

            await asyncio.sleep(300)  # Check every 5 min

        except Exception as e:
            error_msg = f"❌ Trading error: {str(e)}"
            await send_telegram_message(error_msg)
            await asyncio.sleep(60)

# ============================
# MAIN APPLICATION
# ============================
async def main():
    print("🤖 Trading Bot Started Successfully!")
    print("📍 Running on Render.com")
    print("⏰ Monitoring BTCUSDT")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT, error_handler))

    await asyncio.gather(
        application.run_polling(),
        trading_loop()
    )

if __name__ == '__main__':
    asyncio.run(main())
