# app.py - الملف الرئيسي: Flask + تشغيل البوت
import os
import logging
import asyncio
import threading
import traceback
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import asyncpg

import config

# ===================== السجلات =====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===================== دالة run_async (من المشروع السابق) =====================
def run_async(coro):
    """
    تشغيل دالة غير متزامنة في حلقة جديدة باستخدام asyncio.run().
    هذه الطريقة مستقرة ولا تتداخل مع حلقة البوت الرئيسية.
    """
    try:
        return asyncio.run(coro)
    except RuntimeError as e:
        if "cannot be called from a running event loop" in str(e):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()
        else:
            raise

# ===================== تهيئة Flask =====================
app = Flask(__name__)
CORS(app)
bot_app = None

# ===================== Routes الأساسية =====================
@app.route('/')
def home():
    return "🚚 بوت اللوجستيات يعمل! ✅"

@app.route('/health')
def health():
    return "OK"

# ===================== تهيئة قاعدة البيانات =====================
async def init_db():
    """إنشاء الجداول إذا لم تكن موجودة"""
    conn = await asyncpg.connect(config.DATABASE_URL)
    try:
        # جدول طلبات الشحنات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS shipment_requests (
                id SERIAL PRIMARY KEY,
                last4 TEXT NOT NULL,
                rack_a TEXT NOT NULL,
                rack_s TEXT NOT NULL,
                rack_l TEXT NOT NULL,
                full_location TEXT NOT NULL,
                sender_id BIGINT NOT NULL,
                status TEXT DEFAULT 'NEW',
                assigned_to BIGINT,
                is_resubmitted BOOLEAN DEFAULT FALSE,
                needs_verification BOOLEAN DEFAULT FALSE,
                similar_to_id INTEGER,
                replaced_by_id INTEGER,
                hide_after TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # جدول الملاحظات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS request_notes (
                id SERIAL PRIMARY KEY,
                request_id INTEGER NOT NULL,
                sender_id BIGINT NOT NULL,
                note TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # فهارس للأداء
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_requests_status 
            ON shipment_requests(status)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_requests_last4 
            ON shipment_requests(last4)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_notes_request_id 
            ON request_notes(request_id)
        """)
        logger.info("✅ تم التحقق من جداول قاعدة البيانات والفهارس")
    except Exception as e:
        logger.error(f"❌ خطأ في init_db: {e}")
        logger.error(traceback.format_exc())
        raise
    finally:
        await conn.close()

# ===================== معالجات البوت =====================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /start - سيتم توسيعه في المرحلة التالية"""
    await update.message.reply_text(
        "🌿 مرحبًا بك في بوت إدارة طلبات الشحنات.\n\n"
        "📦 هذه النسخة قيد التطوير. سيتم إضافة زر 'طلب جديد' قريبًا."
    )

# ===================== تشغيل البوت =====================
def run_bot():
    global bot_app
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot_app = Application.builder().token(config.BOT_TOKEN).build()

    # (سيتم إضافة معالجات أخرى في المراحل التالية)
    bot_app.add_handler(CommandHandler("start", start_command))

    logger.info("✅ البوت يعمل...")
    bot_app.run_polling(allowed_updates=Update.ALL_TYPES, stop_signals=None)

# ===================== نقطة البداية =====================
if __name__ == "__main__":
    # 1. تهيئة قاعدة البيانات
    try:
        run_async(init_db())
        logger.info("✅ قاعدة البيانات جاهزة")
    except Exception as e:
        logger.error(f"❌ فشل تهيئة قاعدة البيانات: {e}")
        # لا نوقف التطبيق، بل نتركه يعمل حتى نرى الخطأ
        # (يمكن تغيير هذا السلوك لاحقًا)

    # 2. تشغيل البوت في thread منفصل
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    # 3. تشغيل Flask
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"✅ Flask يعمل على المنفذ {port}")
    app.run(host="0.0.0.0", port=port)
