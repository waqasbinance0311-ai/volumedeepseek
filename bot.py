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

print("✅ Bot starting...")

# ============================
# CONFIGURATION
# ============================
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8135935569:AAGuanbMk58ge6xez0T014a5FkOqv2RkfKA')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '8410854765')
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY', 'GOUALe8V6LPbq75eC9Sv2IWreCmolBw5r0B5mWnHI5X5NGiIfDtEn6mXtbmCNCAu')
BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET', 'WDnTUHasXwiW4JXRVY6UZMvfrOTIgyvSgVhRF2bFlCng5dnll2sCmnH7v1JmDAIH')

print(f"Telegram Token: {TELEGRAM_BOT_TOKEN[:10]}...")
print(f"Chat ID: {TELEGRAM_CHAT_ID}")

# ============================
# INITIALIZE
# ============================
try:
    bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
    client = Client(BINANCE_API_KEY, BINANCE_API_SECRET, testnet=True)
    print("✅ Clients initialized successfully")
except Exception as e:
    print(f"❌ Client initialization failed: {e}")

# ============================
# TELEGRAM FUNCTIONS
# ============================
async def send_telegram_message(message):
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        print(f"📤 Message sent: {message}")
    except Exception as e:
        print(f"❌ Telegram error: {e}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('🚀 Hello! Trading Bot is active and running!')

# ============================
# TRADING FUNCTIONS
# ============================
def get_technical_indicators(df):
    try:
        # RSI
        df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
        
        # MACD
        macd = ta.trend.MACD(df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        
        # Bollinger Bands
        bollinger = ta.volatility.BollingerBands(df['close'], window=20)
        df['bb_upper'] = bollinger.bollinger_hband()
        df['bb_lower'] = bollinger.bollinger_lband()
        
        return df
    except Exception as e:
        print(f"❌ Technical indicators error: {e}")
        return df

def check_signal(df):
    try:
        latest = df.iloc[-1]
        
        # Buy signal conditions
        if latest['rsi'] > 50 and latest['close'] > latest['bb_upper']:
            return 'BUY'
        
        # Sell signal conditions
        elif latest['rsi'] < 50 and latest['close'] < latest['bb_lower']:
            return 'SELL'
        
        return None
    except Exception as e:
        print(f"❌ Signal check error: {e}")
        return None

async def trading_loop():
    print("🔄 Starting trading loop...")
    while True:
        try:
            # Get market data
            klines = client.get_klines(
                symbol='BTCUSDT',
                interval=Client.KLINE_INTERVAL_15MINUTE,
                limit=50
            )
            
            # Create DataFrame
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'trades',
                'taker_buy_base', 'taker_buy_quote', 'ignore'
            ])
            
            # Convert to numeric
            numeric_cols = ['open', 'high', 'low', 'close', 'volume']
            for col in numeric_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Calculate indicators
            df = get_technical_indicators(df)
            
            # Check for signal
            signal = check_signal(df)
            
            if signal:
                message = f"🚀 {signal} Signal detected!\nPrice: ${df['close'].iloc[-1]:.2f}\nRSI: {df['rsi'].iloc[-1]:.2f}"
                print(message)
                await send_telegram_message(message)
            else:
                print(f"📊 No signal. Price: ${df['close'].iloc[-1]:.2f}, RSI: {df['rsi'].iloc[-1]:.2f}")
            
            # Wait for next check
            await asyncio.sleep(300)  # 5 minutes
            
        except Exception as e:
            error_msg = f"❌ Trading error: {str(e)}"
            print(error_msg)
            await send_telegram_message(error_msg)
            await asyncio.sleep(60)

# ============================
# MAIN APPLICATION
# ============================
async def main():
    print("🚀 Starting Trading Bot...")
    
    # Send startup message
    startup_msg = "🤖 Trading Bot Started Successfully!\n📍 Running on Render.com\n⏰ Monitoring BTCUSDT"
    await send_telegram_message(startup_msg)
    
    # Start trading loop
    await trading_loop()

if __name__ == '__main__':
    print("📦 Starting application...")
    asyncio.run(main())
