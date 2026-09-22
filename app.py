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
        # إضافة عمود claimed_at إذا لم يكن موجودًا (للإلغاء التلقائي الدقيق)
        await conn.execute("""
            ALTER TABLE shipment_requests 
            ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMP
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

# ===================== Helper: التحقق من الصلاحية =====================
def is_authorized(staff_id):
    return staff_id in config.WAREHOUSE_STAFF_IDS

# ===================== 1. جلب الطلبات =====================
@app.route('/get_requests', methods=['POST'])
def get_requests():
    try:
        data = request.get_json()
        staff_id = data.get('staff_id')
        tab = data.get('tab', 'new')  # 'new' | 'not_found' | 'found'

        if not is_authorized(staff_id):
            return jsonify({"error": "غير مصرح"}), 403

        async def fetch():
            conn = await asyncpg.connect(config.DATABASE_URL)
            try:
                # 1. إلغاء تلقائي للطلبات المتولاة التي تجاوزت المدة
                await conn.execute(
                    f"""
                    UPDATE shipment_requests
                    SET status = 'NEW', assigned_to = NULL, claimed_at = NULL
                    WHERE status = 'CLAIMED'
                    AND claimed_at IS NOT NULL
                    AND claimed_at < NOW() - INTERVAL '{config.AUTO_UNASSIGN_MINUTES} minutes'
                    """
                )

                # 2. تحديد الشرط حسب التبويب
                if tab == 'new':
                    where = "status IN ('NEW', 'CLAIMED')"
                    order = """
                        CASE 
                            WHEN status = 'NEW' THEN 1
                            WHEN status = 'CLAIMED' AND assigned_to = $1 THEN 2
                            WHEN status = 'CLAIMED' THEN 3
                            ELSE 4
                        END ASC, created_at DESC
                    """
                    params = [staff_id]

                elif tab == 'not_found':
                    where = "status = 'NOT_FOUND'"
                    order = "created_at DESC"
                    params = []

                elif tab == 'found':
                    where = "status = 'FOUND' AND (hide_after IS NULL OR hide_after > NOW())"
                    order = "hide_after DESC"
                    params = []

                else:
                    return {"error": "تبويب غير معروف"}

                # 3. جلب الطلبات + الملاحظات المرتبطة
                if params:
                    rows = await conn.fetch(
                        f"""
                        SELECT r.*, 
                            COALESCE(
                                (SELECT json_agg(json_build_object(
                                    'id', n.id,
                                    'sender_id', n.sender_id,
                                    'note', n.note,
                                    'created_at', n.created_at
                                ) ORDER BY n.created_at ASC)
                                FROM request_notes n WHERE n.request_id = r.id),
                                '[]'::json
                            ) as notes
                        FROM shipment_requests r
                        WHERE {where}
                        ORDER BY {order}
                        LIMIT {config.NOT_FOUND_LIMIT if tab == 'not_found' else 500}
                        """,
                        *params
                    )
                else:
                    rows = await conn.fetch(
                        f"""
                        SELECT r.*, 
                            COALESCE(
                                (SELECT json_agg(json_build_object(
                                    'id', n.id,
                                    'sender_id', n.sender_id,
                                    'note', n.note,
                                    'created_at', n.created_at
                                ) ORDER BY n.created_at ASC)
                                FROM request_notes n WHERE n.request_id = r.id),
                                '[]'::json
                            ) as notes
                        FROM shipment_requests r
                        WHERE {where}
                        ORDER BY {order}
                        LIMIT {config.NOT_FOUND_LIMIT if tab == 'not_found' else 500}
                        """
                    )
                return [dict(r) for r in rows]
            finally:
                await conn.close()

        result = run_async(fetch())
        if isinstance(result, dict) and result.get("error"):
            return jsonify(result), 400

        # تحويل التواريخ إلى ISO strings
        for r in result:
            for key in ('created_at', 'hide_after', 'claimed_at'):
                if r.get(key):
                    r[key] = r[key].isoformat()
            if r.get('notes'):
                for n in r['notes']:
                    if n.get('created_at'):
                        n['created_at'] = n['created_at']

        return jsonify(result), 200

    except Exception as e:
        logger.error(f"❌ /get_requests: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

# ===================== 2. تولي طلب =====================
@app.route('/claim_request', methods=['POST'])
def claim_request():
    try:
        data = request.get_json()
        staff_id = data.get('staff_id')
        request_id = data.get('request_id')

        if not is_authorized(staff_id):
            return jsonify({"error": "غير مصرح"}), 403

        async def do_claim():
            conn = await asyncpg.connect(config.DATABASE_URL)
            try:
                result = await conn.execute(
                    """
                    UPDATE shipment_requests
                    SET status = 'CLAIMED', assigned_to = $1, claimed_at = NOW()
                    WHERE id = $2 AND status = 'NEW'
                    """,
                    staff_id, request_id
                )
                updated = int(result.split()[1]) if result.startswith("UPDATE") else 0
                return {"success": updated == 1}
            finally:
                await conn.close()

        result = run_async(do_claim())
        if not result.get("success"):
            return jsonify({"error": "لا يمكن التولي - الطلب ليس جديدًا"}), 400
        return jsonify({"success": True}), 200

    except Exception as e:
        logger.error(f"❌ /claim_request: {e}")
        return jsonify({"error": str(e)}), 500

# ===================== 3. إلغاء التولي =====================
@app.route('/unclaim_request', methods=['POST'])
def unclaim_request():
    try:
        data = request.get_json()
        staff_id = data.get('staff_id')
        request_id = data.get('request_id')

        if not is_authorized(staff_id):
            return jsonify({"error": "غير مصرح"}), 403

        async def do_unclaim():
            conn = await asyncpg.connect(config.DATABASE_URL)
            try:
                result = await conn.execute(
                    """
                    UPDATE shipment_requests
                    SET status = 'NEW', assigned_to = NULL, claimed_at = NULL
                    WHERE id = $1 AND status = 'CLAIMED' AND assigned_to = $2
                    """,
                    request_id, staff_id
                )
                updated = int(result.split()[1]) if result.startswith("UPDATE") else 0
                return {"success": updated == 1}
            finally:
                await conn.close()

        result = run_async(do_unclaim())
        if not result.get("success"):
            return jsonify({"error": "لا يمكن الإلغاء - الطلب ليس متولى منك"}), 400
        return jsonify({"success": True}), 200

    except Exception as e:
        logger.error(f"❌ /unclaim_request: {e}")
        return jsonify({"error": str(e)}), 500

# ===================== 4. تم إيجاده =====================
@app.route('/mark_found', methods=['POST'])
def mark_found():
    try:
        data = request.get_json()
        staff_id = data.get('staff_id')
        request_id = data.get('request_id')

        if not is_authorized(staff_id):
            return jsonify({"error": "غير مصرح"}), 403

        async def do_found():
            conn = await asyncpg.connect(config.DATABASE_URL)
            try:
                result = await conn.execute(
                    f"""
                    UPDATE shipment_requests
                    SET status = 'FOUND',
                        hide_after = NOW() + INTERVAL '{config.HIDE_AFTER_MINUTES} minutes'
                    WHERE id = $1 AND status = 'CLAIMED' AND assigned_to = $2
                    """,
                    request_id, staff_id
                )
                updated = int(result.split()[1]) if result.startswith("UPDATE") else 0
                return {"success": updated == 1}
            finally:
                await conn.close()

        result = run_async(do_found())
        if not result.get("success"):
            return jsonify({"error": "لا يمكن التحديث - الطلب ليس متولى منك"}), 400
        return jsonify({"success": True}), 200

    except Exception as e:
        logger.error(f"❌ /mark_found: {e}")
        return jsonify({"error": str(e)}), 500

# ===================== 5. لم يتم إيجاده =====================
@app.route('/mark_not_found', methods=['POST'])
def mark_not_found():
    try:
        data = request.get_json()
        staff_id = data.get('staff_id')
        request_id = data.get('request_id')

        if not is_authorized(staff_id):
            return jsonify({"error": "غير مصرح"}), 403

        async def do_not_found():
            conn = await asyncpg.connect(config.DATABASE_URL)
            try:
                row = await conn.fetchrow(
                    """
                    SELECT id, last4, full_location, sender_id, status, assigned_to
                    FROM shipment_requests WHERE id = $1
                    """,
                    request_id
                )
                if not row:
                    return {"error": "الطلب غير موجود"}
                if row['status'] != 'CLAIMED':
                    return {"error": f"لا يمكن التحديث - الحالة {row['status']}"}
                if row['assigned_to'] != staff_id:
                    return {"error": "الطلب متولى من موظف آخر"}

                await conn.execute(
                    "UPDATE shipment_requests SET status = 'NOT_FOUND' WHERE id = $1",
                    request_id
                )

                # إشعار مرسل الطلب
                global bot_app
                if bot_app:
                    try:
                        import warehouse_bot
                        await warehouse_bot.notify_sender_not_found(
                            bot_app.bot,
                            row['id'],
                            row['sender_id'],
                            row['last4'],
                            row['full_location']
                        )
                    except Exception as e:
                        logger.error(f"❌ فشل إشعار المرسل: {e}")

                return {"success": True}
            finally:
                await conn.close()

        result = run_async(do_not_found())
        if result.get("error"):
            return jsonify(result), 400
        return jsonify({"success": True}), 200

    except Exception as e:
        logger.error(f"❌ /mark_not_found: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

# ===================== 6. إعادة فحص (من موظف) =====================
@app.route('/recheck_request', methods=['POST'])
def recheck_request():
    try:
        data = request.get_json()
        staff_id = data.get('staff_id')
        request_id = data.get('request_id')

        if not is_authorized(staff_id):
            return jsonify({"error": "غير مصرح"}), 403

        async def do_recheck():
            conn = await asyncpg.connect(config.DATABASE_URL)
            try:
                result = await conn.execute(
                    """
                    UPDATE shipment_requests
                    SET status = 'CLAIMED', assigned_to = $1, claimed_at = NOW()
                    WHERE id = $2 AND status = 'NOT_FOUND'
                    """,
                    staff_id, request_id
                )
                updated = int(result.split()[1]) if result.startswith("UPDATE") else 0
                return {"success": updated == 1}
            finally:
                await conn.close()

        result = run_async(do_recheck())
        if not result.get("success"):
            return jsonify({"error": "لا يمكن إعادة الفحص - الطلب ليس بحالة NOT_FOUND"}), 400
        return jsonify({"success": True}), 200

    except Exception as e:
        logger.error(f"❌ /recheck_request: {e}")
        return jsonify({"error": str(e)}), 500

# ===================== معالجات البوت =====================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /start"""
    import warehouse_bot
    await update.message.reply_text(
        "🌿 مرحبًا بك في بوت إدارة طلبات الشحنات.\n\n"
        "📦 اضغط 'طلب جديد' لإرسال طلب.",
        reply_markup=warehouse_bot.MAIN_KEYBOARD
    )

# ===================== تشغيل البوت =====================
def run_bot():
    global bot_app
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot_app = Application.builder().token(config.BOT_TOKEN).build()

    import warehouse_bot

    bot_app.add_handler(CommandHandler("start", start_command))
    warehouse_bot.register_handlers(bot_app)

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
