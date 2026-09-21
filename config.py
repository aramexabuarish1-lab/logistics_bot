# config.py - الإعدادات والثوابت للمشروع
import os

# ===================== متغيرات البيئة =====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

# قراءة معرّفات موظفي المستودع من متغير البيئة
# الشكل: WAREHOUSE_STAFF_IDS=123,456,789
_staff_raw = os.environ.get("WAREHOUSE_STAFF_IDS", "")
WAREHOUSE_STAFF_IDS = [
    int(x.strip())
    for x in _staff_raw.split(",")
    if x.strip().isdigit()
]

# ===================== التحقق من المتغيرات الأساسية =====================
if not BOT_TOKEN:
    raise ValueError("❌ لم يتم تعيين متغير البيئة BOT_TOKEN")
if not DATABASE_URL:
    raise ValueError("❌ لم يتم تعيين متغير البيئة DATABASE_URL")
if not WAREHOUSE_STAFF_IDS:
    raise ValueError("❌ لم يتم تعيين WAREHOUSE_STAFF_IDS أو القيمة فارغة")

# ===================== مواقع الرفوف =====================
RACK_A = ["A1", "A2", "A3", "A4"]
RACK_S = ["S1", "S2", "S3", "S4", "S5"]
RACK_L = ["L1", "L2", "L3", "L4", "L5"]

def format_location(rack_a: str, rack_s: str, rack_l: str) -> str:
    """تنسيق موقع الرف بشكل موحّد: A2 - S3 - L4"""
    return f"{rack_a} - {rack_s} - {rack_l}"

# ===================== ثوابت الحالات =====================
STATUS_NEW = "NEW"
STATUS_CLAIMED = "CLAIMED"
STATUS_FOUND = "FOUND"
STATUS_NOT_FOUND = "NOT_FOUND"
STATUS_CANCELLED = "CANCELLED"

# ===================== المدد الزمنية =====================
AUTO_UNASSIGN_MINUTES = 10       # إلغاء تلقائي لتولي الطلب بعد 10 دقائق
HIDE_AFTER_MINUTES = 15          # إخفاء الطلب المكتمل بعد 15 دقيقة
NOT_FOUND_LIMIT = 50             # عدد الطلبات المعروضة في تبويب "لم يُعثر عليها"

# ===================== رابط Mini App =====================
MINI_APP_URL = "https://khcontrol41.github.io/logistics_admin/"
