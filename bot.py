import os
import ccxt
import telebot
import pandas as pd
import time
import threading
from datetime import datetime
from collections import deque

# ================== ⚙️ إعدادات البيئة ==================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("MEXC_API_KEY")
SECRET = os.getenv("MEXC_SECRET")
USER_ID = int(os.getenv("MY_USER_ID"))

if not all([TELEGRAM_TOKEN, API_KEY, SECRET, USER_ID]):
    raise Exception("❌ تأكد من ضبط متغيرات البيئة")

# ================== 📊 إعدادات التداول ==================
TIMEFRAME = '3m'           # ⏱ سكالب سريع
FIXED_TRADE_USDT = 5       # 💰 5$ لكل صفقة
MAX_POSITIONS = 10         # 🔢 أقصى 10 صفقات متزامنة
BATCH_SIZE = 10            # 🔍 يفحص 10 عملات في كل دفعة
MIN_BALANCE = 20           # 💳 الحد الأدنى للرصيد

# ================== 🪙 قائمة العملات ==================
COINS = [
    "BTC", "ETH", "SOL", "ADA", "AVAX", "MATIC", "NEAR", "INJ", "ARB", "OP",
    "SUI", "APT", "SEI", "TIA", "FET", "RNDR", "AGIX", "OCEAN", "IMX", "STX",
    "PEPE", "BONK", "WIF", "ORDI", "PYTH", "JUP", "ONDO", "PENDLE"
]

# ================== 🤖 تهيئة البوت ==================
bot = telebot.TeleBot(TELEGRAM_TOKEN)

exchange = ccxt.mexc({
    'apiKey': API_KEY,
    'secret': SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

exchange.load_markets()

# ================== 📁 إدارة البيانات ==================
positions = {}  # المراكز المفتوحة
bot_running = True
total_pnl = 0.0
trade_history = deque(maxlen=100)  # سجل آخر 100 صفقة
stats = {
    'total_trades': 0,
    'winning_trades': 0,
    'losing_trades': 0,
    'total_profit': 0.0
}

# ================== 💎 أدوات مساعدة ==================
def get_balance():
    """الحصول على الرصيد"""
    try:
        balance = exchange.fetch_balance()
        return float(balance['free'].get('USDT', 0))
    except Exception as e:
        print(f"Balance Error: {e}")
        return 0.0

def format_message(title, body, emoji="🚀"):
    """تنسيق رسالة حديثة"""
    return f"""
╔══════════════════════════════════╗
║  {emoji} *{title}* 
╠══════════════════════════════════╣
║
║  {body}
║
╚══════════════════════════════════╝
"""

def format_table(data):
    """تنسيق جدول"""
    if not data:
        return "📭 لا توجد بيانات"
    
    result = "```\n"
    result += f"{'العملة':<8} {'الدخول':<10} {'الآن':<10} {'الربح':<8}\n"
    result += "─" * 40 + "\n"
    
    for symbol, pos in data.items():
        try:
            ticker = exchange.fetch_ticker(f"{symbol}/USDT")
            current = ticker['last']
            profit = ((current - pos['entry']) / pos['entry']) * 100
            result += f"{symbol:<8} {pos['entry']:<10.4f} {current:<10.4f} {profit:>+6.2f}%\n"
        except:
            result += f"{symbol:<8} {'—':<10} {'—':<10} {'—':<8}\n"
    
    result += "```"
    return result

# ================== 🔍 فلتر السوق ==================
def market_safe():
    """التحقق من اتجاه BTC"""
    try:
        ohlcv = exchange.fetch_ohlcv("BTC/USDT", '5m', limit=50)
        df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        df['ema200'] = df['c'].ewm(span=200).mean()
        current_price = df['c'].iloc[-1]
        ema200 = df['ema200'].iloc[-1]
        return current_price > ema200
    except Exception as e:
        print(f"Market Safe Error: {e}")
        return False

# =================️ ⚡ حساب قوة الزخم ==================
def momentum_score(symbol):
    """حساب نقاط الزخم للعملة"""
    try:
        ohlcv = exchange.fetch_ohlcv(f"{symbol}/USDT", TIMEFRAME, limit=30)
        df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        
        if len(df) < 5:
            return 0
        
        # تغير السعر في آخر 3 شموع
        price_change = ((df['c'].iloc[-1] - df['c'].iloc[-3]) / df['c'].iloc[-3]) * 100
        
        # انفجار الحجم
        vol_avg = df['v'].rolling(10).mean().iloc[-1]
        current_vol = df['v'].iloc[-1]
        volume_spike = current_vol / vol_avg if vol_avg > 0 else 1
        
        # النقاط = التغير × الانفجار
        score = price_change * volume_spike
        return score
    except Exception as e:
        print(f"Momentum Score Error {symbol}: {e}")
        return 0

# ================== 💼 إدارة الصفقات ==================
def calculate_sl_tp(price):
    """حساب SL و TP"""
    sl = price * 0.97  # 3% stop loss
    tp = price * 1.06  # 6% take profit
    return sl, tp

def execute_buy(symbol, price, amount):
    """تنفيذ أمر شراء"""
    try:
        # التحقق من الحد الأدنى
        market = exchange.market(f"{symbol}/USDT")
        min_amount = market['limits']['amount']['min']
        if amount < min_amount:
            print(f"Amount too small for {symbol}: {amount} < {min_amount}")
            return False
        
        exchange.create_market_buy_order(f"{symbol}/USDT", amount)
        sl, tp = calculate_sl_tp(price)
        
        positions[symbol] = {
            "entry": price,
            "sl": sl,
            "tp": tp,
            "size": amount,
            "entry_time": datetime.now(),
            "trailing_level": None
        }
        
        # تحديث الإحصائيات
        stats['total_trades'] += 1
        
        return True
    except Exception as e:
        print(f"Buy Error {symbol}: {e}")
        return False

def execute_sell(symbol, price, size, reason="manual"):
    """تنفيذ أمر بيع"""
    try:
        exchange.create_market_sell_order(f"{symbol}/USDT", size)
        
        if symbol in positions:
            entry = positions[symbol]['entry']
            profit_pct = ((price - entry) / entry) * 100
            profit_usd = (price - entry) * size
            
            # تحديث الإحصائيات
            stats['total_profit'] += profit_usd
            if profit_pct > 0:
                stats['winning_trades'] += 1
            else:
                stats['losing_trades'] += 1
            
            # إضافة للسجل
            trade_history.append({
                'symbol': symbol,
                'side': 'SELL',
                'price': price,
                'size': size,
                'profit_pct': profit_pct,
                'profit_usd': profit_usd,
                'reason': reason,
                'timestamp': datetime.now()
            })
            
            positions.pop(symbol, None)
            return True, profit_pct, profit_usd
        
        return True, 0, 0
    except Exception as e:
        print(f"Sell Error {symbol}: {e}")
        return False, 0, 0

# ================== 👁‍🗨 مراقبة المراكز ==================
def monitor():
    """مراقبة المراكز وتطبيق SL/TP/Trailing"""
    global total_pnl
    
    while True:
        if not bot_running:
            time.sleep(5)
            continue
        
        try:
            for symbol in list(positions.keys()):
                try:
                    ticker = exchange.fetch_ticker(f"{symbol}/USDT")
                    price = ticker['last']
                    pos = positions[symbol]
                    
                    entry = pos['entry']
                    sl = pos['sl']
                    tp = pos['tp']
                    size = pos['size']
                    
                    profit_pct = ((price - entry) / entry) * 100
                    
                    # 🔄 Trailing Stop Logic
                    if profit_pct >= 2 and pos['trailing_level'] is None:
                        pos['trailing_level'] = entry * 1.01
                        pos['sl'] = pos['trailing_level']
                    
                    if profit_pct >= 4 and pos['trailing_level']:
                        new_sl = entry * 1.03
                        if new_sl > pos['trailing_level']:
                            pos['trailing_level'] = new_sl
                            pos['sl'] = new_sl
                    
                    # 🚪 شروط الخروج
                    if price <= pos['sl']:
                        success, pnl, _ = execute_sell(symbol, price, size, "SL")
                        if success:
                            total_pnl += pnl
                            bot.send_message(USER_ID, 
                                format_message("🛑 *Stop Loss*",
                                    f"`{symbol}`\n"
                                    f"💰 السعر: `{price:.4f}`\n"
                                    f"📉 الخسارة: `{pnl:.2f}%`\n"
                                    f"💸 المبلغ: `{pnl * size:.2f}$`"))
                    
                    elif price >= tp:
                        success, pnl, _ = execute_sell(symbol, price, size, "TP")
                        if success:
                            total_pnl += pnl
                            bot.send_message(USER_ID,
                                format_message("✅ *Take Profit*",
                                    f"`{symbol}`\n"
                                    f"💰 السعر: `{price:.4f}`\n"
                                    f"📈 الربح: `{pnl:.2f}%`\n"
                                    f"💸 المبلغ: `{pnl * size:.2f}$`"))
                            
                except Exception as e:
                    print(f"Monitor Error {symbol}: {e}")
                    
        except Exception as e:
            print(f"Monitor Loop Error: {e}")
        
        time.sleep(3)

# ================== 🔎 ماسح الإشارات ==================
def scanner():
    """البحث عن إشارات الشراء"""
    while True:
        if not bot_running:
            time.sleep(10)
            continue
        
        try:
            # 🔒 حد أقصى للمراكز
            if len(positions) >= MAX_POSITIONS:
                time.sleep(10)
                continue
            
            # 🌐 فلتر السوق (BTC)
            if not market_safe():
                time.sleep(30)
                continue
            
            # 💳 التحقق من الرصيد
            balance = get_balance()
            if balance < MIN_BALANCE:
                time.sleep(30)
                continue
            
            # 📊 جمع نقاط العملات
            scores = []
            
            for i in range(0, len(COINS), BATCH_SIZE):
                batch = COINS[i:i+BATCH_SIZE]
                
                for coin in batch:
                    if coin in positions:
                        continue
                    try:
                        score = momentum_score(coin)
                        if score > 0:  # فقط الإشارات الإيجابية
                            scores.append((coin, score))
                    except:
                        continue
                
                time.sleep(1)  # تجنب Rate Limit
            
            # 🏆 اختيار أقوى 3 عملات
            scores.sort(key=lambda x: x[1], reverse=True)
            top_coins = [c[0] for c in scores[:3]]
            
            # 🛒 محاولة الشراء
            for coin in top_coins:
                if len(positions) >= MAX_POSITIONS:
                    break
                
                try:
                    ticker = exchange.fetch_ticker(f"{coin}/USDT")
                    price = ticker['last']
                    amount = FIXED_TRADE_USDT / price
                    
                    # التحقق من الحد الأدنى
                    market = exchange.market(f"{coin}/USDT")
                    min_amount = market['limits']['amount']['min']
                    
                    if amount >= min_amount:
                        if execute_buy(coin, price, amount):
                            bot.send_message(USER_ID,
                                format_message("🟢 *شراء جديد*",
                                    f"`{coin}`\n"
                                    f"💵 السعر: `{price:.4f}`\n"
                                    f"🔢 الكمية: `{amount:.6f}`\n"
                                    f"📊 القيمة: `{FIXED_TRADE_USDT}$`"))
                            time.sleep(2)
                            
                except Exception as e:
                    print(f"Buy Error {coin}: {e}")
                    
        except Exception as e:
            print(f"Scanner Error: {e}")
        
        time.sleep(15)

# ================== 🤝 أوامر التليجرام ==================
@bot.message_handler(commands=['start', 'menu'])
def start(msg):
    """عرض القائمة الرئيسية"""
    if msg.chat.id != USER_ID:
        return
    
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        telebot.types.KeyboardButton("📊 *الحالة*"),
        telebot.types.KeyboardButton("💰 *المراكز*"),
        telebot.types.KeyboardButton("📈 *الإحصائيات*"),
        telebot.types.KeyboardButton("📜 *السجل*"),
        telebot.types.KeyboardButton("🚨 *بيع الكل*"),
        telebot.types.KeyboardButton("⏸ *إيقاف/تشغيل*")
    )
    
    bot.send_message(msg.chat.id,
        format_message("🤖 *ULTIMATE BOT 3M*",
            "✅ النظام يعمل بكفاءة\n"
            "⚡ سكالب سريع على 3 دقائق\n"
            f"💰 قيمة الصفقة: `{FIXED_TRADE_USDT}$`\n"
            f"🎯 أقصى مراكز: `{MAX_POSITIONS}`\n"
            f"📊 العملات: `{len(COINS)}` عملة\n"
            "🔄 فلتر BTC: `✅`\n"
            "📈 Trailing: `✅`"),
        reply_markup=markup,
        parse_mode='Markdown')

@bot.message_handler(func=lambda m: True)
def commands(msg):
    """معالجة الأوامر"""
    global bot_running
    
    if msg.chat.id != USER_ID:
        return
    
    text = msg.text.strip().replace('*', '')
    
    if text == "📊 الحالة":
        balance = get_balance()
        status = "✅ يعمل" if bot_running else "⏸ متوقف"
        market_status = "🟢 صاعد" if market_safe() else "🔴 هابط"
        
        bot.send_message(msg.chat.id,
            format_message("📊 *حالة البوت*",
                f"💳 الرصيد: `{balance:.2f} USDT`\n"
                f"📈 المراكز: `{len(positions)}/{MAX_POSITIONS}`\n"
                f"🚀 البوت: `{status}`\n"
                f"📉 اتجاه BTC: `{market_status}`\n"
                f"💰 الربح الكلي: `{total_pnl:.2f}$`"),
            parse_mode='Markdown')
    
    elif text == "💰 المراكز":
        if not positions:
            bot.send_message(msg.chat.id,
                format_message("💰 *المراكز*", "📭 لا توجد مراكز مفتوحة"))
            return
        
        table = format_table(positions)
        bot.send_message(msg.chat.id,
            format_message("💰 *المراكز المفتوحة*", table),
            parse_mode='Markdown')
    
    elif text == "🚨 بيع الكل":
        if not positions:
            bot.send_message(msg.chat.id,
                format_message("🚨 *بيع الكل*", "❌ لا توجد مراكز لبيعها"))
            return
        
        # تأكيد
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(
            telebot.types.InlineKeyboardButton("✅ نعم، بيع الكل", callback_data="sell_all_confirm"),
            telebot.types.InlineKeyboardButton("❌ إلغاء", callback_data="sell_all_cancel")
        )
        
        bot.send_message(msg.chat.id,
            format_message("🚨 *تأكيد بيع الكل*",
                f"⚠️ أنت على وشك بيع `{len(positions)}` مركز\n\n"
                f"هل أنت متأكد؟"),
            reply_markup=markup,
            parse_mode='Markdown')
    
    elif text == "📈 الإحصائيات":
        win_rate = (stats['winning_trades'] / stats['total_trades'] * 100) if stats['total_trades'] > 0 else 0
        
        bot.send_message(msg.chat.id,
            format_message("📈 *الإحصائيات*",
                f"📊 إجمالي الصفقات: `{stats['total_trades']}`\n"
                f"✅ صفقات رابحة: `{stats['winning_trades']}`\n"
                f"❌ صفقات خاسرة: `{stats['losing_trades']}`\n"
                f"📈 نسبة الفوز: `{win_rate:.1f}%`\n"
                f"💰 الربح الكلي: `{stats['total_profit']:.2f}$`\n"
                f"💵 الربح الحالي: `{total_pnl:.2f}$`"),
            parse_mode='Markdown')
    
    elif text == "📜 السجل":
        if not trade_history:
            bot.send_message(msg.chat.id,
                format_message("📜 *سجل الصفقات*", "📭 لا توجد صفقات سابقة"))
            return
        
        history_text = "```\n"
        history_text += f"{'#':<3} {'العملة':<8} {'الربح':<10} {'الوقت':<8}\n"
        history_text += "─" * 35 + "\n"
        
        for i, trade in enumerate(list(trade_history)[-10:], 1):
            time_str = trade['timestamp'].strftime("%H:%M")
            profit_str = f"{trade['profit_pct']:>+6.1f}%"
            history_text += f"{i:<3} {trade['symbol']:<8} {profit_str:<10} {time_str:<8}\n"
        
        history_text += "```"
        
        bot.send_message(msg.chat.id,
            format_message("📜 *آخر 10 صفقات*", history_text),
            parse_mode='Markdown')
    
    elif text == "⏸ إيقاف/تشغيل":
        bot_running = not bot_running
        status = "✅ يعمل" if bot_running else "⏸ متوقف"
        bot.send_message(msg.chat.id,
            format_message("⏸ *الحالة*", f"البوت الآن: `{status}`"),
            parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    """معالجة الأزرار"""
    if call.message.chat.id != USER_ID:
        return
    
    if call.data == "sell_all_confirm":
        count = 0
        for symbol in list(positions.keys()):
            try:
                ticker = exchange.fetch_ticker(f"{symbol}/USDT")
                size = positions[symbol]['size']
                success, _, _ = execute_sell(symbol, ticker['last'], size, "emergency")
                if success:
                    count += 1
            except Exception as e:
                print(f"Emergency Sell Error {symbol}: {e}")
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=format_message("✅ *تم البيع*",
                f"تم بيع `{count}` مركز من `{len(positions) + count}`\n"
                f"💰 الربح المتراكم: `{total_pnl:.2f}$`"),
            parse_mode='Markdown'
        )
    
    elif call.data == "sell_all_cancel":
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=format_message("❌ *إلغاء*", "تم إلغاء عملية البيع"),
            parse_mode='Markdown'
        )

# ================== 🚀 تشغيل البوت ==================
if __name__ == "__main__":
    print("=" * 60)
    print("🚀 ULTIMATE TRADING BOT 3M - MODERN EDITION")
    print("=" * 60)
    print("✅ البوت يعمل من خلال تليجرام فقط")
    print(f"💰 صفقة: {FIXED_TRADE_USDT}$")
    print(f"🎯 أقصى مراكز: {MAX_POSITIONS}")
    print(f"📊 العملات: {len(COINS)} عملة")
    print(f"⏱ الفريم: {TIMEFRAME}")
    print(f"🛡 الحد الأدنى: {MIN_BALANCE}$")
    print("=" * 60)
    print("👨‍💻 أرسل /start في تليجرام")
    print("=" * 60)
    
    # بدء الخيوط
    threading.Thread(target=monitor, daemon=True).start()
    threading.Thread(target=scanner, daemon=True).start()
    
    # تشغيل البوت
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except Exception as e:
        print(f"Bot Error: {e}")
        time.sleep(5)