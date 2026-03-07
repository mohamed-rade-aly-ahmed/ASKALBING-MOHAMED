import os
import ccxt
import telebot
import pandas as pd
import numpy as np
import time
import json
import threading
import csv
from datetime import datetime

# ================== ENV ==================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MEXC_API_KEY = os.getenv("MEXC_API_KEY")
MEXC_SECRET = os.getenv("MEXC_SECRET")
MY_USER_ID = int(os.getenv("MY_USER_ID"))

if not all([TELEGRAM_TOKEN, MEXC_API_KEY, MEXC_SECRET, MY_USER_ID]):
    raise ValueError("تأكد من ضبط GitHub Secrets")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

exchange = ccxt.mexc({
    'apiKey': MEXC_API_KEY,
    'secret': MEXC_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

exchange.load_markets()

# ================== SETTINGS ==================
RISK_PER_TRADE = 0.01
STOP_LOSS_PERCENT = 10
MAX_OPEN_POSITIONS = 5
COOLDOWN = 1800
TARGETS = [1,2,3,5]
TIMEFRAME = '5m'
KILL_SWITCH_DAILY_LOSS = -5
MIN_BALANCE = 20

halal_coins = [
    'BTC','ETH','XRP','ADA','SOL','DOT','LINK','MATIC','AVAX','UNI',
    'ATOM','ALGO','VET','FIL','ICP','NEAR','APT','ARB','OP','SUI'
]

positions_file = "positions.json"
trades_file = "trades.csv"
lock = threading.Lock()
last_trade_time = {}
daily_pnl = 0

# ================== STORAGE ==================
def load_positions():
    if os.path.exists(positions_file):
        with open(positions_file,'r') as f:
            return json.load(f)
    return {}

def save_positions(data):
    with open(positions_file,'w') as f:
        json.dump(data,f,indent=2)

active_positions = load_positions()

# ================== LOGGER ==================
def log_trade(symbol, side, price, amount, profit=0):
    file_exists = os.path.isfile(trades_file)
    with open(trades_file,'a',newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["date","symbol","side","price","amount","profit"])
        writer.writerow([datetime.now(),symbol,side,price,amount,profit])

# ================== INDICATORS ==================
def indicators(ohlcv):
    df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])

    df['ema_fast'] = df['c'].ewm(span=3).mean()
    df['ema_slow'] = df['c'].ewm(span=8).mean()
    df['macd'] = df['ema_fast'] - df['ema_slow']
    df['signal'] = df['macd'].ewm(span=3).mean()

    delta = df['c'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    df['rsi'] = 100 - (100 / (1 + rs))

    df['vol_avg'] = df['v'].rolling(20).mean()
    return df

def btc_trend():
    ohlcv = exchange.fetch_ohlcv("BTC/USDT", TIMEFRAME, limit=50)
    df = indicators(ohlcv)
    return df.iloc[-1].macd > df.iloc[-1].signal

def check_signal(symbol):
    ohlcv = exchange.fetch_ohlcv(f"{symbol}/USDT", TIMEFRAME, limit=50)
    df = indicators(ohlcv)
    last = df.iloc[-1]
    prev = df.iloc[-2]

    macd_cross = prev.macd <= prev.signal and last.macd > last.signal
    rsi_ok = last.rsi > 50
    volume_ok = last.v > last.vol_avg

    return macd_cross and rsi_ok and volume_ok

# ================== RISK ==================
def position_size(usdt_balance):
    risk_amount = usdt_balance * RISK_PER_TRADE
    value = risk_amount / (STOP_LOSS_PERCENT/100)
    return value

def min_amount(symbol):
    return exchange.market(f"{symbol}/USDT")['limits']['amount']['min']

# ================== MONITOR ==================
def monitor():
    global daily_pnl
    while True:
        try:
            with lock:
                for symbol,pos in list(active_positions.items()):
                    ticker = exchange.fetch_ticker(f"{symbol}/USDT")
                    price = ticker['last']
                    entry = pos['entry']
                    size = pos['size']
                    profit = ((price-entry)/entry)*100

                    if profit <= -STOP_LOSS_PERCENT:
                        exchange.create_market_sell_order(f"{symbol}/USDT", size)
                        pnl = (price-entry)*size
                        daily_pnl += pnl
                        log_trade(symbol,"SELL",price,size,pnl)
                        del active_positions[symbol]
                        save_positions(active_positions)
                        bot.send_message(MY_USER_ID,f"🛑 SL {symbol} {profit:.2f}%")
                        continue

                    for target in TARGETS:
                        if target not in pos['targets'] and profit >= target:
                            sell_size = pos['size']*0.25
                            if sell_size < min_amount(symbol):
                                continue
                            exchange.create_market_sell_order(f"{symbol}/USDT", sell_size)
                            pos['size'] -= sell_size
                            pos['targets'].append(target)
                            save_positions(active_positions)
                            bot.send_message(MY_USER_ID,f"🎯 {symbol} {target}%")
                    
                    if len(pos['targets'])==4 and profit<2:
                        exchange.create_market_sell_order(f"{symbol}/USDT", pos['size'])
                        pnl = (price-entry)*pos['size']
                        daily_pnl += pnl
                        log_trade(symbol,"SELL",price,pos['size'],pnl)
                        del active_positions[symbol]
                        save_positions(active_positions)
                        bot.send_message(MY_USER_ID,f"🔒 Trailing Exit {symbol}")

        except Exception as e:
            print("Monitor Error:",e)

        time.sleep(10)

# ================== SCANNER ==================
def scanner():
    global daily_pnl
    while True:
        try:
            if daily_pnl <= KILL_SWITCH_DAILY_LOSS:
                time.sleep(60)
                continue

            if not btc_trend():
                time.sleep(60)
                continue

            if len(active_positions) >= MAX_OPEN_POSITIONS:
                time.sleep(60)
                continue

            balance = exchange.fetch_balance()
            usdt = balance['free'].get('USDT',0)
            if usdt < MIN_BALANCE:
                time.sleep(60)
                continue

            for coin in halal_coins:
                if coin in active_positions:
                    continue

                now = time.time()
                if coin in last_trade_time and now-last_trade_time[coin]<COOLDOWN:
                    continue

                if check_signal(coin):
                    value = position_size(usdt)
                    ticker = exchange.fetch_ticker(f"{coin}/USDT")
                    price = ticker['last']
                    amount = value/price

                    if amount < min_amount(coin):
                        continue

                    exchange.create_market_buy_order(f"{coin}/USDT", amount)

                    active_positions[coin]={
                        "entry":price,
                        "size":amount,
                        "targets":[]
                    }
                    save_positions(active_positions)
                    log_trade(coin,"BUY",price,amount)
                    last_trade_time[coin]=time.time()

                    bot.send_message(MY_USER_ID,f"🟢 BUY {coin} @ {price}")

        except Exception as e:
            print("Scanner Error:",e)

        time.sleep(60)

# ================== TELEGRAM ==================
@bot.message_handler(commands=['start'])
def start(msg):
    if msg.chat.id!=MY_USER_ID: return
    bot.send_message(msg.chat.id,"✅ Elite Bot Running")

@bot.message_handler(commands=['status'])
def status(msg):
    if msg.chat.id!=MY_USER_ID: return
    balance = exchange.fetch_balance()['free'].get('USDT',0)
    bot.send_message(msg.chat.id,
        f"💰 {balance:.2f} USDT\n📈 Positions: {len(active_positions)}\n📊 Daily PnL: {daily_pnl:.2f}")

# ================== START ==================
if __name__=="__main__":
    print("🚀 Elite Trading Bot Running...")
    threading.Thread(target=monitor,daemon=True).start()
    threading.Thread(target=scanner,daemon=True).start()
    bot.infinity_polling()