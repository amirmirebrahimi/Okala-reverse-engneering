import os
import re
import asyncio
import logging
import sys
import zipfile
import shutil
from datetime import datetime
from io import StringIO
from dotenv import load_dotenv
from balethon.client import Client
from balethon.conditions import private
from balethon.objects import InlineKeyboard
from db import (
    init_db,
    set_account_registered_by,
    get_all_registered_by_info,
    get_phones_by_registered_by,
)

load_dotenv()

TOKEN = os.getenv("TOKEN")
PROGRAMMER_IDS = [1816844663]          # برنامه‌نویس
EMPLOYER_IDS = [712719804]             # کارفرما
ADMIN_IDS = PROGRAMMER_IDS + EMPLOYER_IDS

LOG_CHANNEL = os.getenv("LOG_CHANNEL")

import operation as okala_api

bot = Client(TOKEN)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()   # بدون فایل bot.log
    ]
)

# ------------- state management -------------
user_states = {}
user_last_phone = {}
batch_state = {}
user_processing = {}   # مدیریت همزمانی

# ------------- توابع پشتیبان‌گیری -------------
def backup_database():
    """تهیه نسخه پشتیبان از فایل دیتابیس"""
    db_file = "okala_profiles.db"
    if not os.path.exists(db_file):
        return

    backup_dir = "backups"
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"okala_profiles_{timestamp}.db")

    try:
        shutil.copy2(db_file, backup_path)
        logging.info(f"✅ نسخه پشتیبان از دیتابیس در {backup_path} ساخته شد.")
    except Exception as e:
        logging.error(f"❌ خطا در تهیه پشتیبان: {e}")

# ------------- کیبوردها -------------
# منوی اولیه سرویس
service_keyboard = InlineKeyboard(
    [("🎁 اوکالا", "service_okala")],
    [("🛒 دیجی‌کالا", "service_digikala")]
)

# منوی کاربر عادی
user_keyboard = InlineKeyboard(
    [("🛒 ثبت‌نام شماره و افزودن به سبد خرید", "okala_operation2")]
)

# منوی کارفرما (۴ گزینه)
employer_keyboard = InlineKeyboard(
    [("🛒 ثبت‌نام شماره و افزودن به سبد خرید", "okala_operation2")],
    [("🔍 جست‌وجو در سایت اوکالا برای کد تخفیف", "admin_operation1")],
    [("📦 دریافت کدهای تخفیف با فرمت زیپ", "admin_operation4")],
    [("👥 دریافت کدهای تخفیف بر اساس ثبت‌کننده شماره", "admin_view_by_registered")]
)

# منوی برنامه‌نویس (۵ گزینه)
programmer_keyboard = InlineKeyboard(
    [("🛒 ثبت‌نام شماره و افزودن به سبد خرید", "okala_operation2")],
    [("🔍 جست‌وجو در سایت اوکالا برای کد تخفیف", "admin_operation1")],
    [("📦 دریافت کدهای تخفیف با فرمت زیپ", "admin_operation4")],
    [("👥 دریافت کدهای تخفیف بر اساس ثبت‌کننده شماره", "admin_view_by_registered")],
    [("🔄 رفرش توکن همه کاربران", "admin_operation3")]
)

# کیبورد انصراف + بازگشت
cancel_keyboard = InlineKeyboard(
    [("❌ انصراف", "cancel")],
    [("🏠 بازگشت به منوی اصلی", "menu")]
)

def get_admin_keyboard(user_id: int) -> InlineKeyboard:
    """بازگرداندن کیبورد مناسب بر اساس نقش کاربر"""
    if user_id in PROGRAMMER_IDS:
        return programmer_keyboard
    else:
        return employer_keyboard

def operation_done_keyboard(service):
    return InlineKeyboard(
        [("📱 ارسال شماره بعدی", f"next_number:{service}")],
        [("🏠 بازگشت به منوی اصلی", "menu")]
    )

def operation_failed_keyboard(service):
    return InlineKeyboard(
        [("🔄 تلاش مجدد", f"retry:{service}")],
        [("📱 شماره جدید", f"next_number:{service}")],
        [("🏠 بازگشت به منوی اصلی", "menu")]
    )

# ------------- توابع کمکی -------------
PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ENGLISH_DIGITS = "0123456789"
TRANS = str.maketrans(PERSIAN_DIGITS, ENGLISH_DIGITS)

def normalize_text(text: str) -> str:
    return text.translate(TRANS).strip()

def validate_phone(text: str):
    digits = re.sub(r"\D", "", normalize_text(text))
    if digits.startswith("98"):
        digits = "0" + digits[2:]
    elif digits.startswith("+98"):
        digits = "0" + digits[3:]
    elif digits.startswith("0098"):
        digits = "0" + digits[4:]
    if re.fullmatch(r"09\d{9}", digits):
        return digits
    return None

def extract_otp(text: str):
    normalized = normalize_text(text)
    match = re.search(r"\b\d{4,6}\b", normalized)
    if match:
        return match.group(0)
    return None

def get_user_display_name(author):
    first = getattr(author, 'first_name', '') or ''
    last = getattr(author, 'last_name', '') or ''
    full = (first + ' ' + last).strip()
    return full or getattr(author, 'username', '') or str(author.id)

async def safe_answer(callback_query, text, show_alert=False):
    try:
        await callback_query.answer(text, show_alert=show_alert)
    except Exception as e:
        logging.warning(f"Error answering callback: {e}")

async def send_log(text: str):
    logging.info(text)
    try:
        if LOG_CHANNEL:
            await bot.send_message(LOG_CHANNEL, text)
        else:
            for admin_id in ADMIN_IDS:
                await bot.send_message(admin_id, text)
    except Exception as e:
        logging.error(f"Error sending log: {e}")

# ------------- مدیریت همزمانی -------------
def is_user_processing(user_id: int) -> bool:
    return user_processing.get(user_id, False)

def set_user_processing(user_id: int, value: bool):
    user_processing[user_id] = value

# ------------- توابع اجرای عملیات -------------
def run_single_okala_operation(phone: str, province: str, operation_type: str):
    log_capture = StringIO()
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = log_capture
    sys.stderr = log_capture
    try:
        result = okala_api.operaton(
            phone_number=phone,
            province_name=province,
            operation=operation_type,
            proxy_url=None
        )
        logs = log_capture.getvalue()
        return {"success": bool(result), "error": None, "logs": logs}
    except Exception as e:
        logs = log_capture.getvalue()
        return {"success": False, "error": str(e), "logs": logs}
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

def run_refresh_all_tokens():
    log_capture = StringIO()
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = log_capture
    sys.stderr = log_capture
    try:
        okala_api.refresh_all_users_tokens()
        logs = log_capture.getvalue()
        return {"success": True, "logs": logs}
    except Exception as e:
        logs = log_capture.getvalue()
        return {"success": False, "error": str(e), "logs": logs}
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

def run_extract_discounts(count: int):
    log_capture = StringIO()
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = log_capture
    sys.stderr = log_capture
    try:
        folder = okala_api.extract_and_delete_discounts(count)
        logs = log_capture.getvalue()
        return {"success": True, "logs": logs, "folder": folder}
    except Exception as e:
        logs = log_capture.getvalue()
        return {"success": False, "error": str(e), "logs": logs}
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

async def start_single_operation(message, phone: str, operation_type: str, success_text: str):
    user_id = message.author.id

    # بررسی همزمانی
    if is_user_processing(user_id):
        await message.reply("⏳ شما در حال انجام عملیات دیگری هستید. لطفاً صبر کنید.")
        return

    set_user_processing(user_id, True)
    user_last_phone[user_id] = phone
    province = "3"  # تهران

    loop = asyncio.get_event_loop()
    future = loop.run_in_executor(None, run_single_okala_operation, phone, province, operation_type)

    try:
        result = await future
        if result.get("logs"):
            await send_log(f"📋 لاگ‌های عملیات {phone}:\n{result['logs'][-1500:]}")

        if result["success"]:
            # ثبت‌کننده برای همه (حتی ادمین) ذخیره شود
            if operation_type == "2":
                try:
                    author = message.author
                    full_name = get_user_display_name(author)
                    username = getattr(author, 'username', None)
                    set_account_registered_by(phone, author.id, full_name, username)
                    await send_log(f"👤 ثبت‌کننده {full_name} (@{username}) برای شماره {phone} ذخیره شد.")
                except Exception as e:
                    logging.warning(f"Error saving registered_by for {phone}: {e}")

            await send_log(f"✅ عملیات {operation_type} برای {phone} موفق بود.")
            await message.reply(
                f"✅ {success_text}",
                reply_markup=operation_done_keyboard("okala")
            )
        else:
            await send_log(f"❌ عملیات {operation_type} برای {phone} ناموفق بود: {result.get('error')}")
            await message.reply(
                f"❌ عملیات ناموفق بود.\n{result.get('error', 'خطای ناشناخته')}",
                reply_markup=operation_failed_keyboard("okala")
            )
    except Exception as e:
        await send_log(f"❌ خطا در اجرای عملیات {operation_type} برای {phone}: {e}")
        await message.reply(f"❌ خطا: {e}", reply_markup=operation_failed_keyboard("okala"))
    finally:
        set_user_processing(user_id, False)

async def start_batch_okala_operation(message, phones: list):
    user_id = message.author.id

    # بررسی همزمانی
    if is_user_processing(user_id):
        await message.reply("⏳ شما در حال انجام عملیات دیگری هستید. لطفاً صبر کنید.")
        return

    set_user_processing(user_id, True)
    batch_state[user_id] = {
        "phones": phones,
        "index": 0,
        "current_phone": None,
        "cancel": False
    }

    try:
        for idx, phone in enumerate(phones):
            if batch_state.get(user_id, {}).get("cancel"):
                break
            batch_state[user_id]["index"] = idx
            batch_state[user_id]["current_phone"] = phone
            user_states[user_id] = "awaiting_batch_otp"

            await send_log(f"🔄 شروع پردازش شماره {phone} ({idx+1}/{len(phones)})")
            await message.reply(
                f"⏳ در حال پردازش شماره {phone}...\n"
                f"📩 اگر کد OTP برای این شماره ارسال شد، لطفاً کد را همینجا وارد کنید.",
                reply_markup=cancel_keyboard
            )

            loop = asyncio.get_event_loop()
            future = loop.run_in_executor(None, run_single_okala_operation, phone, "3", "1")
            result = await future

            if result.get("logs"):
                await send_log(f"📋 لاگ‌های شماره {phone}:\n{result['logs'][-1000:]}")

            if result["success"]:
                await send_log(f"✅ شماره {phone} با موفقیت پردازش شد.")
                await message.reply(f"✅ شماره {phone} با موفقیت پردازش شد.")
            else:
                await send_log(f"❌ شماره {phone} ناموفق بود: {result.get('error')}")
                await message.reply(f"❌ شماره {phone} ناموفق بود.\n{result.get('error', '')}")

            await asyncio.sleep(1)

        user_states[user_id] = None
        await message.reply("🏁 پردازش بازه به پایان رسید.", reply_markup=get_admin_keyboard(user_id))
    except Exception as e:
        await send_log(f"❌ خطا در پردازش بازه: {e}")
        await message.reply(f"❌ خطا: {e}", reply_markup=get_admin_keyboard(user_id))
    finally:
        batch_state[user_id] = {}
        set_user_processing(user_id, False)

# ------------- هندلر پیام‌ها -------------
@bot.on_message(private)
async def handle_message(message):
    user_id = message.author.id
    text = message.text.strip()

    if text in ["/start", "/menu", "🏠 منوی اصلی"]:
        user_states[user_id] = None
        batch_state[user_id] = {}
        user_last_phone.pop(user_id, None)
        set_user_processing(user_id, False)  # آزادسازی در صورت ورود به منو
        await message.reply(
            "سلام! 👋\nلطفاً سرویس موردنظر را انتخاب کنید:",
            reply_markup=service_keyboard
        )
        return

    if user_id not in ADMIN_IDS:
        # کاربر عادی
        state = user_states.get(user_id)
        if state == "awaiting_okala_number":
            phone = validate_phone(text)
            if not phone:
                await message.reply("❌ شماره نامعتبر است.", reply_markup=cancel_keyboard)
                return
            user_states[user_id] = "awaiting_okala_otp"
            user_last_phone[user_id] = phone
            await message.reply(
                "⏳ درخواست ارسال شد.\n"
                "لطفاً منتظر پیامک OTP باشید.\n"
                "بعد از دریافت پیامک، کد را همینجا ارسال کنید.",
                reply_markup=cancel_keyboard
            )
            asyncio.create_task(start_single_operation(message, phone, "2", "عملیات ثبت‌نام و افزودن به سبد خرید با موفقیت انجام شد."))
            return
        elif state == "awaiting_okala_otp":
            otp = extract_otp(text)
            if not otp:
                await message.reply("❌ کد نامعتبر است.", reply_markup=cancel_keyboard)
                return
            phone = user_last_phone.get(user_id)
            if phone:
                okala_api.set_otp(phone, otp)
            user_states[user_id] = None
            return
        else:
            await message.reply("لطفاً سرویس موردنظر را انتخاب کنید:", reply_markup=service_keyboard)
            return

    # ادامه برای ادمین‌ها
    state = user_states.get(user_id)

    if state == "awaiting_okala_number":
        phone = validate_phone(text)
        if not phone:
            await message.reply("❌ شماره نامعتبر است.", reply_markup=cancel_keyboard)
            return
        user_states[user_id] = "awaiting_okala_otp"
        user_last_phone[user_id] = phone
        await message.reply(
            "⏳ درخواست ارسال شد.\n"
            "لطفاً منتظر پیامک OTP باشید.\n"
            "بعد از دریافت پیامک، کد را همینجا ارسال کنید.",
            reply_markup=cancel_keyboard
        )
        asyncio.create_task(start_single_operation(message, phone, "2", "عملیات ثبت‌نام و افزودن به سبد خرید با موفقیت انجام شد."))
        return

    elif state == "awaiting_okala_otp":
        otp = extract_otp(text)
        if not otp:
            await message.reply("❌ کد نامعتبر است.", reply_markup=cancel_keyboard)
            return
        phone = user_last_phone.get(user_id)
        if phone:
            okala_api.set_otp(phone, otp)
        user_states[user_id] = None
        return

    elif state == "awaiting_batch_otp":
        otp = extract_otp(text)
        if not otp:
            await message.reply("❌ کد نامعتبر است.", reply_markup=cancel_keyboard)
            return
        current_phone = batch_state.get(user_id, {}).get("current_phone")
        if current_phone:
            okala_api.set_otp(current_phone, otp)
        return

    elif state == "awaiting_row_range":
        parts = text.split()
        if len(parts) != 2:
            await message.reply("❌ لطفاً دو عدد (شروع و پایان) را با فاصله وارد کنید.", reply_markup=cancel_keyboard)
            return
        try:
            start_row = int(parts[0])
            end_row = int(parts[1])
        except ValueError:
            await message.reply("❌ اعداد نامعتبر هستند.", reply_markup=cancel_keyboard)
            return

        if start_row < 1 or end_row < start_row:
            await message.reply("❌ بازه نامعتبر است.", reply_markup=cancel_keyboard)
            return

        try:
            all_phones = okala_api.get_all_phones()
        except Exception as e:
            await send_log(f"❌ خطا در دریافت لیست شماره‌ها: {e}")
            await message.reply("❌ خطا در دریافت لیست شماره‌ها.", reply_markup=get_admin_keyboard(user_id))
            return

        if not all_phones:
            await message.reply("ℹ️ هیچ شماره‌ای در دیتابیس وجود ندارد.", reply_markup=get_admin_keyboard(user_id))
            return

        phones_in_range = all_phones[start_row-1:end_row]
        if not phones_in_range:
            await message.reply("ℹ️ هیچ شماره‌ای در این بازه ردیف یافت نشد.", reply_markup=get_admin_keyboard(user_id))
            return

        await message.reply(f"🔍 {len(phones_in_range)} شماره در بازه ردیف {start_row} تا {end_row} یافت شد.\nشروع پردازش...")
        user_states[user_id] = None
        asyncio.create_task(start_batch_okala_operation(message, phones_in_range))
        return

    elif state == "awaiting_extract_count":
        try:
            count = int(text)
        except ValueError:
            await message.reply("❌ لطفاً یک عدد صحیح وارد کنید.", reply_markup=cancel_keyboard)
            return
        user_states[user_id] = None
        await message.reply("⏳ در حال استخراج کدها...")

        # بررسی همزمانی
        if is_user_processing(user_id):
            await message.reply("⏳ شما در حال انجام عملیات دیگری هستید.")
            return

        set_user_processing(user_id, True)
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, run_extract_discounts, count)
            if result.get("logs"):
                await send_log(f"📋 لاگ استخراج:\n{result['logs'][-1000:]}")
            if result["success"]:
                await message.reply("✅ کدها با موفقیت استخراج شدند.", reply_markup=get_admin_keyboard(user_id))

                # ارسال فایل ZIP
                folder = result.get("folder")
                if folder and os.path.isdir(folder):
                    zip_path = folder + ".zip"
                    try:
                        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                            for root, _, files in os.walk(folder):
                                for file in files:
                                    full_path = os.path.join(root, file)
                                    arcname = os.path.relpath(full_path, folder)
                                    zf.write(full_path, arcname)
                        await bot.send_document(message.chat.id, document=zip_path)
                        await message.reply("📁 فایل استخراج‌شده ارسال شد.")
                    except Exception as e:
                        await message.reply(f"❌ خطا در ساخت یا ارسال ZIP: {e}")
            else:
                await message.reply(f"❌ خطا: {result.get('error')}", reply_markup=get_admin_keyboard(user_id))
        finally:
            set_user_processing(user_id, False)
        return

    else:
        await message.reply("لطفاً سرویس موردنظر را انتخاب کنید:", reply_markup=service_keyboard)

# ------------- هندلر callback -------------
@bot.on_callback_query()
async def handle_callback(callback_query):
    user_id = callback_query.author.id
    data = callback_query.data

    if data == "service_okala":
        if user_id in PROGRAMMER_IDS:
            await callback_query.message.reply("منوی برنامه‌نویس اوکالا:", reply_markup=programmer_keyboard)
        elif user_id in EMPLOYER_IDS:
            await callback_query.message.reply("منوی کارفرما اوکالا:", reply_markup=employer_keyboard)
        else:
            await callback_query.message.reply("منوی کاربر اوکالا:", reply_markup=user_keyboard)
        await safe_answer(callback_query)
        return

    elif data == "service_digikala":
        await callback_query.message.reply("بخش دیجی‌کالا هنوز آماده نیست.", reply_markup=service_keyboard)
        await safe_answer(callback_query)
        return

    if user_id not in ADMIN_IDS:
        # کاربر عادی
        if data == "okala_operation2":
            if is_user_processing(user_id):
                await safe_answer(callback_query, "⏳ شما در حال انجام عملیات هستید", show_alert=True)
                return
            user_states[user_id] = "awaiting_okala_number"
            await callback_query.message.reply(
                "لطفاً شماره موبایل خود را ارسال کنید (مثلاً 09123456789):",
                reply_markup=cancel_keyboard
            )
        elif data == "cancel":
            user_states[user_id] = None
            user_last_phone.pop(user_id, None)
            set_user_processing(user_id, False)
            await callback_query.message.reply("❌ عملیات لغو شد.", reply_markup=service_keyboard)
        elif data == "menu":
            user_states[user_id] = None
            set_user_processing(user_id, False)
            await callback_query.message.reply("منوی اصلی:", reply_markup=service_keyboard)
        else:
            await safe_answer(callback_query, "⚠️ شما دسترسی ندارید", show_alert=True)
        return

    # ادمین‌ها
    if data == "admin_operation1":
        if is_user_processing(user_id):
            await safe_answer(callback_query, "⏳ شما در حال انجام عملیات هستید", show_alert=True)
            return
        user_states[user_id] = "awaiting_row_range"
        await callback_query.message.reply(
            "لطفاً ردیف شروع و پایان دیتابیس را وارد کنید:\n"
            "مثال: 10 20",
            reply_markup=cancel_keyboard
        )

    elif data == "okala_operation2":
        if is_user_processing(user_id):
            await safe_answer(callback_query, "⏳ شما در حال انجام عملیات هستید", show_alert=True)
            return
        user_states[user_id] = "awaiting_okala_number"
        await callback_query.message.reply(
            "لطفاً شماره موبایل را ارسال کنید:",
            reply_markup=cancel_keyboard
        )

    elif data == "admin_operation3":
        if user_id not in PROGRAMMER_IDS:
            await safe_answer(callback_query, "⛔ دسترسی غیرمجاز", show_alert=True)
            return
        if is_user_processing(user_id):
            await safe_answer(callback_query, "⏳ شما در حال انجام عملیات هستید", show_alert=True)
            return

        set_user_processing(user_id, True)
        await callback_query.message.reply("⏳ در حال رفرش توکن‌ها...")
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, run_refresh_all_tokens)
            if result.get("logs"):
                await send_log(f"📋 لاگ رفرش:\n{result['logs'][-1500:]}")
            await callback_query.message.reply("✅ رفرش توکن‌ها انجام شد.", reply_markup=programmer_keyboard)
        finally:
            set_user_processing(user_id, False)

    elif data == "admin_operation4":
        if is_user_processing(user_id):
            await safe_answer(callback_query, "⏳ شما در حال انجام عملیات هستید", show_alert=True)
            return
        user_states[user_id] = "awaiting_extract_count"
        await callback_query.message.reply(
            "چند کد تخفیف می‌خواهید استخراج کنید؟",
            reply_markup=cancel_keyboard
        )

    elif data == "admin_view_by_registered":
        if is_user_processing(user_id):
            await safe_answer(callback_query, "⏳ شما در حال انجام عملیات هستید", show_alert=True)
            return
        infos = get_all_registered_by_info()
        if not infos:
            await callback_query.message.reply("ℹ️ هیچ ثبت‌کننده‌ای یافت نشد.", reply_markup=get_admin_keyboard(user_id))
            await safe_answer(callback_query)
            return

        rows = []
        for info in infos:
            name = info.get("name") or "بدون نام"
            username = info.get("username")
            label = name
            if username:
                label += f" (@{username})"
            label += f" - {info.get('count', 0)} شماره"
            rows.append([(label, f"select_registered:{info['id']}")])
        rows.append([("🏠 بازگشت", "menu")])

        keyboard = InlineKeyboard(*rows)
        await callback_query.message.reply("👥 یک ثبت‌کننده را انتخاب کنید:", reply_markup=keyboard)
        await safe_answer(callback_query)

    elif data.startswith("select_registered:"):
        if is_user_processing(user_id):
            await safe_answer(callback_query, "⏳ شما در حال انجام عملیات هستید", show_alert=True)
            return
        reg_id = int(data.split(":")[1])
        phones = get_phones_by_registered_by(reg_id)
        if not phones:
            await callback_query.message.reply("ℹ️ شماره‌ای برای این شخص یافت نشد.", reply_markup=get_admin_keyboard(user_id))
            await safe_answer(callback_query)
            return

        batch_state[user_id] = {"selected_phones": phones}
        user_states[user_id] = "awaiting_confirm_selected"

        await callback_query.message.reply(
            f"🔍 {len(phones)} شماره ثبت‌شده توسط این شخص:\n"
            + "\n".join(phones)
            + "\n\nآیا مایل به انجام عملیات روی این شماره‌ها هستید؟",
            reply_markup=InlineKeyboard(
                [("✅ تایید و شروع عملیات", "confirm_selected")],
                [("❌ انصراف", "cancel")],
                [("🏠 بازگشت", "menu")]
            )
        )
        await safe_answer(callback_query)

    elif data == "confirm_selected":
        if is_user_processing(user_id):
            await safe_answer(callback_query, "⏳ شما در حال انجام عملیات هستید", show_alert=True)
            return
        phones = batch_state.get(user_id, {}).get("selected_phones", [])
        if not phones:
            await callback_query.message.reply("خطا: لیست شماره‌ها موجود نیست.", reply_markup=get_admin_keyboard(user_id))
            await safe_answer(callback_query)
            return

        user_states[user_id] = None
        batch_state[user_id] = {}
        await callback_query.message.reply(f"🚀 شروع پردازش {len(phones)} شماره...")
        asyncio.create_task(start_batch_okala_operation(callback_query.message, phones))
        await safe_answer(callback_query)

    elif data == "cancel":
        if user_id in batch_state:
            batch_state[user_id]["cancel"] = True
        user_states[user_id] = None
        user_last_phone.pop(user_id, None)
        set_user_processing(user_id, False)
        await callback_query.message.reply("❌ عملیات لغو شد.", reply_markup=service_keyboard)

    elif data.startswith("next_number:") or data.startswith("retry:"):
        service = data.split(":")[1]
        user_states[user_id] = f"awaiting_{service}_number"
        await callback_query.message.reply("لطفاً شماره موبایل جدید را ارسال کنید:", reply_markup=cancel_keyboard)

    elif data == "menu":
        user_states[user_id] = None
        batch_state[user_id] = {}
        user_last_phone.pop(user_id, None)
        set_user_processing(user_id, False)
        await callback_query.message.reply("منوی اصلی:", reply_markup=service_keyboard)

    else:
        await safe_answer(callback_query, "گزینه نامشخص")

if __name__ == "__main__":
    init_db()
    backup_database()  
    bot.run()