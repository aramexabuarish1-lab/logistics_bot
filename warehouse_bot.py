# warehouse_bot.py - معالج طلبات الشحنات
import logging
import re
import asyncpg
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import ContextTypes, MessageHandler, CallbackQueryHandler, filters

import config

logger = logging.getLogger(__name__)

# ===================== القائمة الرئيسية =====================
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("📦 طلب جديد")]],
    resize_keyboard=True,
    one_time_keyboard=False
)

# ===================== بناء لوحات المفاتيح =====================
def build_a_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("A1", callback_data="ord_a_A1"),
            InlineKeyboardButton("A2", callback_data="ord_a_A2"),
        ],
        [
            InlineKeyboardButton("A3", callback_data="ord_a_A3"),
            InlineKeyboardButton("A4", callback_data="ord_a_A4"),
        ],
        [InlineKeyboardButton("🔙 السابق", callback_data="ord_back_last4")],
    ])

def build_s_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("S1", callback_data="ord_s_S1"),
            InlineKeyboardButton("S2", callback_data="ord_s_S2"),
            InlineKeyboardButton("S3", callback_data="ord_s_S3"),
        ],
        [
            InlineKeyboardButton("S4", callback_data="ord_s_S4"),
            InlineKeyboardButton("S5", callback_data="ord_s_S5"),
        ],
        [InlineKeyboardButton("🔙 السابق", callback_data="ord_back_a")],
    ])

def build_l_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("L1", callback_data="ord_l_L1"),
            InlineKeyboardButton("L2", callback_data="ord_l_L2"),
            InlineKeyboardButton("L3", callback_data="ord_l_L3"),
        ],
        [
            InlineKeyboardButton("L4", callback_data="ord_l_L4"),
            InlineKeyboardButton("L5", callback_data="ord_l_L5"),
        ],
        [InlineKeyboardButton("🔙 السابق", callback_data="ord_back_s")],
    ])

def build_review_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأكيد وإرسال", callback_data="ord_confirm")],
        [
            InlineKeyboardButton("✏️ تعديل", callback_data="ord_edit"),
            InlineKeyboardButton("❌ إلغاء", callback_data="ord_cancel"),
        ],
    ])

def build_similar_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔁 قطعة أخرى", callback_data="ord_sim_other"),
            InlineKeyboardButton("🔍 التأكد في الرف", callback_data="ord_sim_verify"),
        ],
        [InlineKeyboardButton("↩️ رجوع وإرسال طلب جديد", callback_data="ord_sim_back")],
    ])

# ===================== دوال قاعدة البيانات =====================
async def find_similar_active(last4: str):
    """البحث عن طلب نشط بنفس آخر 4 أرقام"""
    conn = await asyncpg.connect(config.DATABASE_URL)
    try:
        row = await conn.fetchrow(
            """
            SELECT id, status, full_location
            FROM shipment_requests
            WHERE last4 = $1 AND status IN ('NEW', 'CLAIMED', 'NOT_FOUND')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            last4
        )
        return dict(row) if row else None
    finally:
        await conn.close()

# ===================== بدء الطلب =====================
async def start_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء تدفق طلب جديد"""
    context.user_data.clear()
    context.user_data['order_state'] = 'AWAITING_LAST4'
    await update.message.reply_text(
        "📦 *طلب جديد*\n\n"
        "أدخل آخر أربعة أرقام من الشحنة.\n"
        "مثال: `5832`",
        parse_mode="Markdown"
    )
    logger.info(f"🆕 بدء طلب جديد من {update.effective_user.id}")

# ===================== معالجة إدخال آخر 4 أرقام =====================
async def handle_last4_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة النص المُدخل كآخر 4 أرقام"""
    text = update.message.text.strip()

    if not re.match(r'^\d{4}$', text):
        await update.message.reply_text(
            "❌ يجب إدخال *4 أرقام بالضبط*.\n"
            "حاول مرة أخرى:",
            parse_mode="Markdown"
        )
        return

    context.user_data['order_last4'] = text
    logger.info(f"📝 last4 = {text}")

    # فحص التشابه
    try:
        similar = await find_similar_active(text)
    except Exception as e:
        logger.error(f"❌ خطأ في فحص التشابه: {e}")
        similar = None

    if similar:
        context.user_data['order_similar_to_id'] = similar['id']
        context.user_data['order_state'] = 'AWAITING_SIMILAR'
        await update.message.reply_text(
            f"⚠️ *تنبيه:* يوجد طلب سابق بنفس آخر أربعة أرقام.\n\n"
            f"الرقم: `{text}`\n"
            f"الطلب السابق #{similar['id']} — الحالة: `{similar['status']}`\n"
            f"الموقع: `{similar['full_location']}`\n\n"
            "كيف تريد المتابعة؟",
            parse_mode="Markdown",
            reply_markup=build_similar_keyboard()
        )
        return

    # لا يوجد تشابه → اختيار A
    context.user_data['order_state'] = 'AWAITING_A'
    await update.message.reply_text(
        f"✅ تم حفظ الرقم: `{text}`\n\n"
        "🔵 *الخطوة 1:* اختر المستوى الأول (A):",
        parse_mode="Markdown",
        reply_markup=build_a_keyboard()
    )

# ===================== معالج Callback الموحّد =====================
async def order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    state = context.user_data.get('order_state')

    # ===== اختيار A =====
    if data.startswith("ord_a_"):
        if state != 'AWAITING_A':
            return
        rack_a = data.split("_")[2]
        context.user_data['order_rack_a'] = rack_a
        context.user_data['order_state'] = 'AWAITING_S'
        await query.edit_message_text(
            f"✅ {rack_a}\n\n"
            "🔵 *الخطوة 2:* اختر المستوى الثاني (S):",
            parse_mode="Markdown",
            reply_markup=build_s_keyboard()
        )
        return

    # ===== اختيار S =====
    if data.startswith("ord_s_"):
        if state != 'AWAITING_S':
            return
        rack_s = data.split("_")[2]
        context.user_data['order_rack_s'] = rack_s
        context.user_data['order_state'] = 'AWAITING_L'
        await query.edit_message_text(
            f"✅ {context.user_data['order_rack_a']} - {rack_s}\n\n"
            "🔵 *الخطوة 3:* اختر المستوى الثالث (L):",
            parse_mode="Markdown",
            reply_markup=build_l_keyboard()
        )
        return

    # ===== اختيار L → مراجعة =====
    if data.startswith("ord_l_"):
        if state != 'AWAITING_L':
            return
        rack_l = data.split("_")[2]
        context.user_data['order_rack_l'] = rack_l
        context.user_data['order_state'] = 'AWAITING_CONFIRM'
        full_location = config.format_location(
            context.user_data['order_rack_a'],
            context.user_data['order_rack_s'],
            rack_l
        )
        await query.edit_message_text(
            f"📋 *مراجعة الطلب:*\n\n"
            f"آخر أربعة أرقام: `{context.user_data['order_last4']}`\n"
            f"الموقع: `{full_location}`\n\n"
            "هل تريد التأكيد والإرسال؟",
            parse_mode="Markdown",
            reply_markup=build_review_keyboard()
        )
        return

    # ===== أزرار "السابق" =====
    if data == "ord_back_last4":
        context.user_data['order_state'] = 'AWAITING_LAST4'
        context.user_data.pop('order_last4', None)
        context.user_data.pop('order_rack_a', None)
        await query.edit_message_text(
            "🔙 عدنا للبداية.\n\n"
            "أدخل آخر أربعة أرقام من الشحنة (4 أرقام):"
        )
        return

    if data == "ord_back_a":
        context.user_data['order_state'] = 'AWAITING_A'
        context.user_data.pop('order_rack_a', None)
        await query.edit_message_text(
            "🔵 *الخطوة 1:* اختر المستوى الأول (A):",
            parse_mode="Markdown",
            reply_markup=build_a_keyboard()
        )
        return

    if data == "ord_back_s":
        context.user_data['order_state'] = 'AWAITING_S'
        context.user_data.pop('order_rack_s', None)
        await query.edit_message_text(
            f"✅ {context.user_data['order_rack_a']}\n\n"
            "🔵 *الخطوة 2:* اختر المستوى الثاني (S):",
            parse_mode="Markdown",
            reply_markup=build_s_keyboard()
        )
        return

    # ===== أزرار التشابه =====
    if data == "ord_sim_other":
        context.user_data.pop('order_similar_to_id', None)
        context.user_data.pop('order_needs_verification', None)
        context.user_data['order_state'] = 'AWAITING_A'
        await query.edit_message_text(
            f"✅ تم حفظ الرقم: `{context.user_data['order_last4']}`\n\n"
            "🔵 *الخطوة 1:* اختر المستوى الأول (A):",
            parse_mode="Markdown",
            reply_markup=build_a_keyboard()
        )
        return

    if data == "ord_sim_verify":
        context.user_data['order_needs_verification'] = True
        context.user_data['order_state'] = 'AWAITING_A'
        await query.edit_message_text(
            f"🔍 سيتم تمييز هذا الطلب بعلامة *بحاجة لتأكيد الرف*.\n\n"
            f"✅ تم حفظ الرقم: `{context.user_data['order_last4']}`\n\n"
            "🔵 *الخطوة 1:* اختر المستوى الأول (A):",
            parse_mode="Markdown",
            reply_markup=build_a_keyboard()
        )
        return

    if data == "ord_sim_back":
        context.user_data.clear()
        await query.edit_message_text("↩️ تم الرجوع. اضغط 'طلب جديد' للبدء من جديد.")
        await query.message.reply_text(
            "اختر من القائمة:",
            reply_markup=MAIN_KEYBOARD
        )
        return

    # ===== تأكيد / تعديل / إلغاء =====
    if data == "ord_confirm":
        await confirm_order(update, context, query)
        return

    if data == "ord_edit":
        context.user_data.clear()
        context.user_data['order_state'] = 'AWAITING_LAST4'
        await query.edit_message_text(
            "✏️ سنعيد الإدخال من البداية.\n\n"
            "أدخل آخر أربعة أرقام من الشحنة (4 أرقام):"
        )
        return

    if data == "ord_cancel":
        context.user_data.clear()
        await query.edit_message_text("❌ تم إلغاء الطلب.")
        await query.message.reply_text(
            "اختر من القائمة:",
            reply_markup=MAIN_KEYBOARD
        )
        return

# ===================== تأكيد الطلب =====================
async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE, query):
    user = update.effective_user
    last4 = context.user_data.get('order_last4')
    rack_a = context.user_data.get('order_rack_a')
    rack_s = context.user_data.get('order_rack_s')
    rack_l = context.user_data.get('order_rack_l')
    needs_verification = context.user_data.get('order_needs_verification', False)
    similar_to_id = context.user_data.get('order_similar_to_id')
    replaced_from_id = context.user_data.get('order_replaced_from_id')

    if not all([last4, rack_a, rack_s, rack_l]):
        await query.edit_message_text("❌ بيانات ناقصة، أعد المحاولة من البداية.")
        context.user_data.clear()
        return

    full_location = config.format_location(rack_a, rack_s, rack_l)

    # حفظ في DB
    try:
        conn = await asyncpg.connect(config.DATABASE_URL)
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO shipment_requests
                    (last4, rack_a, rack_s, rack_l, full_location,
                     sender_id, needs_verification, similar_to_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                last4, rack_a, rack_s, rack_l, full_location,
                user.id, needs_verification, similar_to_id
            )
            request_id = row['id']

            # إذا كان الطلب الجديد بديلًا لطلب قديم (من زر "تعديل")
            if replaced_from_id:
                await conn.execute(
                    """
                    UPDATE shipment_requests
                    SET status = 'CANCELLED', replaced_by_id = $1
                    WHERE id = $2
                    """,
                    request_id, replaced_from_id
                )
                logger.info(f"🔗 ربط الطلب #{request_id} بالقديم #{replaced_from_id}")
        finally:
            await conn.close()
    except Exception as e:
        logger.error(f"❌ فشل حفظ الطلب: {e}")
        await query.edit_message_text(f"❌ حدث خطأ تقني أثناء الحفظ: {str(e)[:100]}")
        context.user_data.clear()
        return

    logger.info(f"✅ تم حفظ الطلب #{request_id}")

    # تحديث رسالة المراجعة
    success_text = (
        f"✅ *تم إرسال طلبك بنجاح!*\n\n"
        f"📦 رقم الطلب: #{request_id}\n"
        f"آخر 4 أرقام: `{last4}`\n"
        f"الموقع: `{full_location}`"
    )
    if needs_verification:
        success_text += "\n\n⚠️ _بحاجة لتأكيد الرف_"

    await query.edit_message_text(success_text, parse_mode="Markdown")

    # استعادة القائمة الرئيسية
    await query.message.reply_text(
        "يمكنك إرسال طلب جديد:",
        reply_markup=MAIN_KEYBOARD
    )

    # إشعار موظفي المستودع
    await notify_staff(
        context.bot, request_id, last4, full_location,
        needs_verification, user.username
    )

    # تفريغ الحالة
    context.user_data.clear()

# ===================== إشعار موظفي المستودع (طلب جديد) =====================
async def notify_staff(bot, request_id, last4, full_location,
                       needs_verification, sender_username):
    text = (
        f"🔔 *طلب شحنة جديد*\n\n"
        f"📦 رقم الطلب: #{request_id}\n"
        f"آخر 4 أرقام: `{last4}`\n"
        f"الموقع: `{full_location}`"
    )
    if needs_verification:
        text += "\n\n⚠️ *بحاجة لتأكيد الرف*"
    if sender_username:
        text += f"\n\n👤 من: @{sender_username}"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📊 فتح لوحة الطلبات",
            web_app={"url": config.MINI_APP_URL}
        )]
    ])

    for staff_id in config.WAREHOUSE_STAFF_IDS:
        try:
            await bot.send_message(
                chat_id=staff_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            logger.info(f"✅ إشعار الموظف {staff_id} بالطلب #{request_id}")
        except Exception as e:
            logger.error(f"❌ فشل إشعار الموظف {staff_id}: {e}")

# ===================== إشعارات لمرسل الطلب =====================
async def notify_sender_not_found(bot, request_id, sender_id, last4, full_location):
    """يُرسل إشعار NOT_FOUND لمرسل الطلب مع 3 أزرار"""
    text = (
        f"⚠️ *لم يتم العثور على الشحنة*\n\n"
        f"📦 رقم الطلب: #{request_id}\n"
        f"آخر 4 أرقام: `{last4}`\n"
        f"الموقع: `{full_location}`\n\n"
        "ماذا تريد أن تفعل؟"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📝 إرسال ملاحظة", callback_data=f"nf_note_{request_id}"),
            InlineKeyboardButton("🔄 إعادة بحث", callback_data=f"nf_resend_{request_id}"),
        ],
        [InlineKeyboardButton("✏️ تعديل الطلب", callback_data=f"nf_edit_{request_id}")],
    ])
    try:
        await bot.send_message(
            chat_id=sender_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        logger.info(f"✅ إشعار NOT_FOUND لمرسل الطلب {sender_id} بالطلب #{request_id}")
    except Exception as e:
        logger.error(f"❌ فشل إشعار مرسل الطلب {sender_id}: {e}")

# ===================== إشعار الموظفين بالملاحظة =====================
async def notify_staff_note(bot, request_id, sender_username, note, last4, full_location):
    """يُرسل إشعار لموظفي المستودع عند إضافة ملاحظة على طلب"""
    text = (
        f"📝 *ملاحظة جديدة على الطلب #{request_id}*\n\n"
        f"آخر 4 أرقام: `{last4}`\n"
        f"الموقع: `{full_location}`\n"
    )
    if sender_username:
        text += f"\n👤 من: @{sender_username}\n"
    text += f"\n💬 {note}"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 فتح لوحة الطلبات",
                              web_app={"url": config.MINI_APP_URL})]
    ])

    for staff_id in config.WAREHOUSE_STAFF_IDS:
        try:
            await bot.send_message(
                chat_id=staff_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"❌ فشل إشعار الموظف {staff_id}: {e}")

# ===================== إشعار الموظفين بإعادة البحث =====================
async def notify_staff_resubmit(bot, request_id, last4, full_location):
    """يُرسل إشعار لموظفي المستودع عند إعادة بحث طلب"""
    text = (
        f"🔁 *طلب أُعيد بحثه*\n\n"
        f"📦 رقم الطلب: #{request_id}\n"
        f"آخر 4 أرقام: `{last4}`\n"
        f"الموقع: `{full_location}`"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 فتح لوحة الطلبات",
                              web_app={"url": config.MINI_APP_URL})]
    ])

    for staff_id in config.WAREHOUSE_STAFF_IDS:
        try:
            await bot.send_message(
                chat_id=staff_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"❌ فشل إشعار الموظف {staff_id}: {e}")

# ===================== معالج أزرار إشعار NOT_FOUND =====================
async def nf_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # ===== 📝 إرسال ملاحظة =====
    if data.startswith("nf_note_"):
        request_id = int(data.split("_")[2])
        context.user_data.clear()
        context.user_data['note_request_id'] = request_id
        context.user_data['order_state'] = 'AWAITING_NOTE'
        await query.edit_message_text(
            f"📝 *إرسال ملاحظة على الطلب #{request_id}*\n\n"
            "اكتب ملاحظتك الآن:",
            parse_mode="Markdown"
        )
        return

    # ===== 🔄 إعادة بحث =====
    if data.startswith("nf_resend_"):
        request_id = int(data.split("_")[2])
        try:
            conn = await asyncpg.connect(config.DATABASE_URL)
            try:
                row = await conn.fetchrow(
                    "SELECT last4, full_location, status FROM shipment_requests WHERE id = $1",
                    request_id
                )
                if not row:
                    await query.edit_message_text("❌ الطلب غير موجود.")
                    return
                if row['status'] != 'NOT_FOUND':
                    await query.edit_message_text(
                        f"⚠️ لا يمكن إعادة البحث — الطلب بحالة `{row['status']}`.",
                        parse_mode="Markdown"
                    )
                    return
                await conn.execute(
                    """
                    UPDATE shipment_requests
                    SET status = 'NEW', is_resubmitted = TRUE, assigned_to = NULL
                    WHERE id = $1
                    """,
                    request_id
                )
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"❌ فشل إعادة البحث: {e}")
            await query.edit_message_text(f"❌ خطأ تقني: {str(e)[:100]}")
            return

        await query.edit_message_text(
            f"✅ *تم إعادة إرسال الطلب #{request_id} للبحث.*\n\n"
            "سيقوم فريق المستودع بالبحث عنه مجددًا.",
            parse_mode="Markdown"
        )
        await notify_staff_resubmit(
            context.bot, request_id, row['last4'], row['full_location']
        )
        logger.info(f"🔁 إعادة بحث الطلب #{request_id} بواسطة {update.effective_user.id}")
        return

    # ===== ✏️ تعديل الطلب =====
    if data.startswith("nf_edit_"):
        request_id = int(data.split("_")[2])
        context.user_data.clear()
        context.user_data['order_replaced_from_id'] = request_id
        context.user_data['order_state'] = 'AWAITING_LAST4'
        await query.edit_message_text(
            f"✏️ *تعديل الطلب #{request_id}*\n\n"
            "سنعيد إنشاء الطلب من البداية.\n\n"
            "أدخل آخر أربعة أرقام من الشحنة (4 أرقام):",
            parse_mode="Markdown"
        )
        logger.info(f"✏️ بدء تعديل الطلب #{request_id}")
        return

# ===================== معالج نص الملاحظة =====================
async def handle_note_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    request_id = context.user_data.get('note_request_id')
    if not request_id:
        return

    note_text = update.message.text.strip()
    if not note_text:
        await update.message.reply_text("❌ الملاحظة فارغة، حاول مرة أخرى:")
        return
    if len(note_text) > 1000:
        await update.message.reply_text("❌ الملاحظة طويلة جدًا (الحد 1000 حرف).")
        return

    user = update.effective_user

    try:
        conn = await asyncpg.connect(config.DATABASE_URL)
        try:
            await conn.execute(
                "INSERT INTO request_notes (request_id, sender_id, note) VALUES ($1, $2, $3)",
                request_id, user.id, note_text
            )
            row = await conn.fetchrow(
                "SELECT last4, full_location FROM shipment_requests WHERE id = $1",
                request_id
            )
        finally:
            await conn.close()
    except Exception as e:
        logger.error(f"❌ فشل حفظ الملاحظة: {e}")
        await update.message.reply_text(f"❌ خطأ تقني: {str(e)[:100]}")
        return

    await update.message.reply_text(
        f"✅ *تم إرسال ملاحظتك للطلب #{request_id}*\n\n"
        "سيقوم فريق المستودع بمراجعتها.",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD
    )

    if row:
        await notify_staff_note(
            context.bot, request_id, user.username, note_text,
            row['last4'], row['full_location']
        )

    logger.info(f"📝 ملاحظة على الطلب #{request_id} من {user.id}")
    context.user_data.clear()

# ===================== موجّه النصوص =====================
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """موجّه النصوص: يعالج last4 والملاحظات"""
    state = context.user_data.get('order_state')
    if state == 'AWAITING_LAST4':
        await handle_last4_input(update, context)
    elif state == 'AWAITING_NOTE':
        await handle_note_input(update, context)
    # وإلا: تجاهل بصمت

# ===================== تسجيل المعالجات =====================
def register_handlers(application):
    application.add_handler(MessageHandler(
        filters.Text("📦 طلب جديد"),
        start_order
    ))
    application.add_handler(CallbackQueryHandler(
        order_callback, pattern="^ord_"
    ))
    application.add_handler(CallbackQueryHandler(
        nf_callback, pattern="^nf_"
    ))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_text_input
    ))
