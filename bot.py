import os
import telebot
import ccxt
from telebot import types
import time
import json
import threading
from datetime import datetime
import pandas as pd
import numpy as np

# ===== قراءة البيانات من GitHub Secrets =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MEXC_API_KEY = os.getenv("MEXC_API_KEY")
MEXC_SECRET = os.getenv("MEXC_SECRET")
MY_USER_ID = int(os.getenv("MY_USER_ID"))

# التأكد من وجود المتغيرات
if not all([TELEGRAM_TOKEN, MEXC_API_KEY, MEXC_SECRET, MY_USER_ID]):
    raise ValueError("❌ تأكد من ضبط جميع المتغيرات في GitHub Secrets")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ===== اتصال MEXC =====
exchange = ccxt.mexc({
    'apiKey': MEXC_API_KEY,
    'secret': MEXC_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

# ===== العملات الحلال فقط =====
halal_coins = [
    'BTC', 'ETH', 'XRP', 'ADA', 'SOL', 'DOT', 'LINK', 'MATIC', 'AVAX', 'UNI',
    'ATOM', 'ALGO', 'VET', 'FIL', 'ICP', 'NEAR', 'APT', 'ARB', 'OP', 'SUI',
    'FET', 'GRT', 'EOS', 'STX', 'IMX', 'RNDR', 'MKR', 'AAVE', 'EGLD'
]

# ===== تخزين المراكز =====
positions_file = 'positions.json'
positions_lock = threading.Lock()

def load_positions():
    if os.path.exists(positions_file):
        with open(positions_file, 'r') as f:
            return json.load(f)
    return {}

def save_positions(data):
    with open(positions_file, 'w') as f:
        json.dump(data, f, indent=2)

active_positions = load_positions()

# ===== صورة الشعار =====
LOGO_URL = "https://i.imgur.com/6m0rXqT.png"

# ===== القائمة الرئيسية =====
def send_main_menu(chat_id):
    welcome_msg = (
        "╔══════════════════╗\n"
        "   👑 *ابوراضي الأسطوره* 👑\n"
        "╚══════════════════╝\n\n"
        "🤖 *بوت التداول الذكي*\n"
        "┈─────────────────┈\n"
        "✅ استراتيجية MACD (3,8,3)\n"
        "🎯 أهداف: 1%، 2%، 3%، 5%\n"
        "🛑 وقف خسارة: -10%\n\n"
        "اختر من الأزرار:"
    )
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("📊│ حالة التداول"),
        types.KeyboardButton("💰│ المراكز المفتوحة"),
        types.KeyboardButton("🟢│ شراء يدوي"),
        types.KeyboardButton("🔴│ بيع يدوي"),
        types.KeyboardButton("📜│ سجل الصفقات"),
        types.KeyboardButton("⚙️│ الإعدادات")
    )
    
    try:
        bot.send_photo(chat_id, photo=LOGO_URL, caption=welcome_msg,
                       parse_mode='Markdown', reply_markup=markup)
    except:
        bot.send_message(chat_id, welcome_msg, parse_mode='Markdown',
                         reply_markup=markup)

# ===== حساب MACD =====
def calculate_macd(prices, fast=3, slow=8, signal=3):
    df = pd.DataFrame(prices, columns=['close'])
    exp1 = df['close'].ewm(span=fast, adjust=False).mean()
    exp2 = df['close'].ewm(span=slow, adjust=False).mean()
    macd = exp1 - exp2
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd.iloc[-1], signal_line.iloc[-1]

# ===== فحص إشارات الدخول =====
def check_entry_signal(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(f"{symbol}/USDT", '5m', limit=50)
        closes = [c[4] for c in ohlcv]
        
        macd, signal = calculate_macd(closes, 3, 8, 3)
        prev_macd, prev_signal = calculate_macd(closes[:-1], 3, 8, 3)
        
        # إشارة شراء: تقاطع MACD فوق Signal Line
        if prev_macd <= prev_signal and macd > signal:
            return True, macd, signal
        return False, macd, signal
    except:
        return False, 0, 0

# ===== مراقبة المراكز =====
def monitor_positions():
    while True:
        try:
            with positions_lock:
                if not active_positions:
                    time.sleep(10)
                    continue
                
                for symbol, position in list(active_positions.items()):
                    try:
                        ticker = exchange.fetch_ticker(f"{symbol}/USDT")
                        current = ticker['last']
                        entry = position['entry_price']
                        profit = ((current - entry) / entry) * 100
                        size = position['position_size']
                        
                        # وقف خسارة -10%
                        if profit <= -10:
                            exchange.create_market_sell_order(f"{symbol}/USDT", size)
                            bot.send_message(
                                MY_USER_ID,
                                f"🛑 *وقف خسارة*\n{symbol}: {profit:.2f}%",
                                parse_mode='Markdown'
                            )
                            del active_positions[symbol]
                            save_positions(active_positions)
                            continue
                        
                        # الأهداف
                        targets = [1, 2, 3, 5]
                        targets_hit = position.get('targets_hit', [])
                        
                        for target in targets:
                            if target not in targets_hit and profit >= target:
                                sell_amount = size * 0.25
                                exchange.create_market_sell_order(f"{symbol}/USDT", sell_amount)
                                targets_hit.append(target)
                                position['targets_hit'] = targets_hit
                                position['position_size'] -= sell_amount
                                
                                bot.send_message(
                                    MY_USER_ID,
                                    f"🎯 *هدف {target}%*\n{symbol} @ {profit:.2f}%",
                                    parse_mode='Markdown'
                                )
                                save_positions(active_positions)
                    
                    except Exception as e:
                        print(f"Error: {e}")
                        continue
        except:
            pass
        time.sleep(10)

# ===== فحص الإشارات =====
def scan_for_signals():
    while True:
        try:
            for coin in halal_coins:
                if coin in active_positions:
                    continue
                
                signal, _, _ = check_entry_signal(coin)
                if signal:
                    balance = exchange.fetch_balance()
                    usdt = balance['free'].get('USDT', 0)
                    
                    if usdt >= 20:  # حد أدنى 20 USDT
                        buy_amount = usdt * 0.02  # 2% من الرصيد
                        ticker = exchange.fetch_ticker(f"{coin}/USDT")
                        price = ticker['last']
                        coin_amount = buy_amount / price
                        
                        exchange.create_market_buy_order(f"{coin}/USDT", coin_amount)
                        
                        with positions_lock:
                            active_positions[coin] = {
                                'entry_price': price,
                                'position_size': coin_amount,
                                'targets_hit': [],
                                'entry_time': datetime.now().isoformat()
                            }
                            save_positions(active_positions)
                        
                        bot.send_message(
                            MY_USER_ID,
                            f"🟢 *شراء {coin}*\nالسعر: {price:.4f}\nالكمية: {coin_amount:.6f}",
                            parse_mode='Markdown'
                        )
                        time.sleep(1)
        except:
            pass
        time.sleep(300)  # 5 دقائق

# ===== تشغيل الخيوط =====
threading.Thread(target=monitor_positions, daemon=True).start()
threading.Thread(target=scan_for_signals, daemon=True).start()

# ===== أوامر البوت =====
@bot.message_handler(commands=['start'])
def start(message):
    if message.chat.id != MY_USER_ID:
        return
    send_main_menu(message.chat.id)

@bot.message_handler(func=lambda msg: True)
def handle_message(message):
    if message.chat.id != MY_USER_ID:
        return
    
    text = message.text
    
    if text == "📊│ حالة التداول":
        balance = exchange.fetch_balance()['total'].get('USDT', 0)
        msg = f"💰 الرصيد: {balance:.2f} USDT\n📈 المراكز: {len(active_positions)}"
        bot.send_message(message.chat.id, msg)
    
    elif text == "💰│ المراكز المفتوحة":
        if not active_positions:
            bot.send_message(message.chat.id, "لا توجد مراكز")
            return
        msg = ""
        for symbol, pos in active_positions.items():
            msg += f"{symbol}: {pos['position_size']:.6f}\n"
        bot.send_message(message.chat.id, msg)
    
    elif text == "🟢│ شراء يدوي":
        msg = bot.send_message(message.chat.id, "أدخل: رمز_العملة نسبة_الرصيد\nمثال: BTC 5")
        bot.register_next_step_handler(msg, manual_buy)
    
    elif text == "🔴│ بيع يدوي":
        msg = bot.send_message(message.chat.id, "أدخل: رمز_العملة\nمثال: BTC")
        bot.register_next_step_handler(msg, manual_sell)

def manual_buy(message):
    try:
        parts = message.text.split()
        symbol = parts[0].upper()
        percent = float(parts[1])
        
        balance = exchange.fetch_balance()
        usdt = balance['free'].get('USDT', 0)
        amount_usdt = usdt * percent / 100
        
        ticker = exchange.fetch_ticker(f"{symbol}/USDT")
        price = ticker['last']
        coin_amount = amount_usdt / price
        
        exchange.create_market_buy_order(f"{symbol}/USDT", coin_amount)
        
        with positions_lock:
            active_positions[symbol] = {
                'entry_price': price,
                'position_size': coin_amount,
                'targets_hit': [],
                'entry_time': datetime.now().isoformat()
            }
            save_positions(active_positions)
        
        bot.send_message(message.chat.id, f"✅ تم شراء {symbol}")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ خطأ: {e}")

def manual_sell(message):
    try:
        symbol = message.text.upper()
        
        if symbol not in active_positions:
            bot.send_message(message.chat.id, "لا يوجد مركز")
            return
        
        size = active_positions[symbol]['position_size']
        exchange.create_market_sell_order(f"{symbol}/USDT", size)
        
        with positions_lock:
            del active_positions[symbol]
            save_positions(active_positions)
        
        bot.send_message(message.chat.id, f"✅ تم بيع {symbol}")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ خطأ: {e}")

# ===== تشغيل البوت =====
if __name__ == "__main__":
    print("🚀 البوت يعمل...")
    bot.infinity_polling()
