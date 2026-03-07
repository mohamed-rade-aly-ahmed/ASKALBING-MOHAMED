import os
import ccxt
import telebot
import pandas as pd
import time
import threading

# ================== ENV ==================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("MEXC_API_KEY")
SECRET = os.getenv("MEXC_SECRET")
USER_ID = int(os.getenv("MY_USER_ID"))

if not all([TELEGRAM_TOKEN, API_KEY, SECRET, USER_ID]):
    raise Exception("❌ تأكد من ضبط متغيرات البيئة")

# ================== SETTINGS ==================
TIMEFRAME = '3m'
FIXED_TRADE_USDT = 5
MAX_POSITIONS = 10

COINS = [   # مختصرة لتجنب Rate Limit
"BTC","ETH","SOL","ADA","AVAX","MATIC","NEAR","INJ","ARB","OP",
"SUI","APT","SEI","TIA","FET","RNDR","AGIX","OCEAN","IMX","STX",
"PEPE","BONK","WIF","ORDI","PYTH","JUP","ONDO","PENDLE"
]

# ================== TELEGRAM ==================
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ================== EXCHANGE ==================
exchange = ccxt.mexc({
    'apiKey': API_KEY,
    'secret': SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

exchange.load_markets()

positions = {}

# ================== UI ==================
def box(title, body):
    return f"""
╔══════════════════════╗
║   🚀 {title}
╠══════════════════════╣
{body}
╚══════════════════════╝
"""

# ================== MARKET FILTER ==================
def market_safe():
    try:
        ohlcv = exchange.fetch_ohlcv("BTC/USDT", '5m', limit=50)
        df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        df['ema200'] = df['c'].ewm(span=200).mean()
        return df.iloc[-1].c > df.iloc[-1].ema200
    except:
        return False

# ================== MOMENTUM SCORE ==================
def momentum_score(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(f"{symbol}/USDT", TIMEFRAME, limit=30)
        df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])

        change = ((df['c'].iloc[-1] - df['c'].iloc[-3]) / df['c'].iloc[-3]) * 100
        vol_spike = df['v'].iloc[-1] / df['v'].rolling(20).mean().iloc[-1]

        score = change * vol_spike
        return score
    except:
        return 0

# ================== ENTRY ==================
def try_enter(symbol):
    try:
        ticker = exchange.fetch_ticker(f"{symbol}/USDT")
        price = ticker['last']

        amount = FIXED_TRADE_USDT / price
        market = exchange.market(f"{symbol}/USDT")
        min_amount = market['limits']['amount']['min']

        if amount < min_amount:
            return

        exchange.create_market_buy_order(f"{symbol}/USDT", amount)

        sl = price * 0.97
        tp = price * 1.06

        positions[symbol] = {
            "entry": price,
            "sl": sl,
            "tp": tp,
            "size": amount
        }

        bot.send_message(USER_ID,
            box("BUY ✅",
                f"{symbol}\nEntry: {price:.4f}\nSL: {sl:.4f}\nTP: {tp:.4f}"))

    except Exception as e:
        print("Entry Error:", e)

# ================== MONITOR ==================
def monitor():
    while True:
        try:
            for symbol in list(positions.keys()):
                ticker = exchange.fetch_ticker(f"{symbol}/USDT")
                price = ticker['last']

                entry = positions[symbol]['entry']
                sl = positions[symbol]['sl']
                tp = positions[symbol]['tp']
                size = positions[symbol]['size']

                profit = ((price - entry) / entry) * 100

                # Trailing
                if profit >= 2:
                    positions[symbol]['sl'] = entry * 1.01
                if profit >= 4:
                    positions[symbol]['sl'] = entry * 1.03

                # Exit
                if price <= positions[symbol]['sl'] or price >= tp:
                    exchange.create_market_sell_order(f"{symbol}/USDT", size)
                    del positions[symbol]

                    bot.send_message(USER_ID,
                        box("EXIT ✅",
                            f"{symbol}\nExit: {price:.4f}\nProfit: {profit:.2f}%"))

        except Exception as e:
            print("Monitor Error:", e)

        time.sleep(5)

# ================== SCANNER ==================
def scanner():
    while True:
        try:
            if len(positions) >= MAX_POSITIONS:
                time.sleep(10)
                continue

            if not market_safe():
                time.sleep(10)
                continue

            scores = []

            for coin in COINS:
                if coin in positions:
                    continue
                score = momentum_score(coin)
                scores.append((coin, score))

            scores.sort(key=lambda x: x[1], reverse=True)
            top_coins = [c[0] for c in scores[:3]]

            for coin in top_coins:
                if len(positions) >= MAX_POSITIONS:
                    break
                try_enter(coin)

        except Exception as e:
            print("Scanner Error:", e)

        time.sleep(15)

# ================== TELEGRAM COMMANDS ==================
@bot.message_handler(commands=['start'])
def start(msg):
    if msg.chat.id != USER_ID:
        return

    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📊 الحالة", "🚨 بيع الكل")

    bot.send_message(USER_ID,
        box("ULTRA MOMENTUM 3M",
            "✅ النظام يعمل\n⚡ سكالب هجومي"),
        reply_markup=markup)

@bot.message_handler(func=lambda m: True)
def commands(msg):
    if msg.chat.id != USER_ID:
        return

    if msg.text == "📊 الحالة":
        bot.send_message(USER_ID,
            box("الحالة",
                f"المراكز المفتوحة: {len(positions)}"))

    if msg.text == "🚨 بيع الكل":
        for symbol in list(positions.keys()):
            size = positions[symbol]['size']
            exchange.create_market_sell_order(f"{symbol}/USDT", size)
            del positions[symbol]

        bot.send_message(USER_ID,
            box("🚨 طوارئ",
                "تم بيع جميع المراكز"))

# ================== RUN ==================
if __name__ == "__main__":
    print("🚀 ULTRA BOT RUNNING...")
    threading.Thread(target=monitor, daemon=True).start()
    threading.Thread(target=scanner, daemon=True).start()
    bot.infinity_polling()