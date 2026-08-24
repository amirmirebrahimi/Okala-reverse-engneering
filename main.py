import os
import re
import asyncio
import logging
import sys
import zipfile
import shutil
import random
import threading
import time
from datetime import datetime, timedelta
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
    get_phones_without_address,
    export_accounts_by_phones,
)

load_dotenv()

TOKEN = os.getenv("TOKEN")
PROGRAMMER_IDS = [1816844663]
EMPLOYER_IDS = [712719804]
ADMIN_IDS = PROGRAMMER_IDS + EMPLOYER_IDS
LOG_CHANNEL = os.getenv("LOG_CHANNEL")

import operation as okala_api

bot = Client(TOKEN)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

# ------------- state management -------------
user_states = {}
user_last_phone = {}
batch_state = {}
user_processing = {}
user_selected_province = {}

BACKUP_DIR = "backups"
LAST_BACKUP_FILE = os.path.join(BACKUP_DIR, "last_backup.txt")

def get_last_backup_time():
    """بازگرداندن زمان آخرین بک‌آپ از فایل"""
    try:
        if os.path.exists(LAST_BACKUP_FILE):
            with open(LAST_BACKUP_FILE, "r", encoding="utf-8") as f:
                timestamp = f.read().strip()
                if timestamp:
                    return datetime.fromisoformat(timestamp)
    except Exception as e:
        logging.warning(f"Error reading last backup time: {e}")
    return None

def set_last_backup_time(dt):
    """ذخیره زمان آخرین بک‌آپ در فایل"""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        with open(LAST_BACKUP_FILE, "w", encoding="utf-8") as f:
            f.write(dt.isoformat())
    except Exception as e:
        logging.warning(f"Error writing last backup time: {e}")

def backup_database():
    """تهیه نسخه پشتیبان از فایل دیتابیس و ذخیره زمان آن"""
    db_file = "okala_profiles.db"
    if not os.path.exists(db_file):
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"okala_profiles_{timestamp}.db")
    try:
        shutil.copy2(db_file, backup_path)
        set_last_backup_time(datetime.now())
        logging.info(f"✅ نسخه پشتیبان ساخته شد: {backup_path}")
    except Exception as e:
        logging.error(f"❌ خطا در تهیه نسخه پشتیبان: {e}")

def backup_thread():
    """
    بررسی دوره‌ای برای بک‌آپ هر ۳ هفته.
    با هر بار ری‌استارت سرویس، تایمر از ابتدا شروع نمی‌شود،
    بلکه هر ساعت بررسی می‌کند که آیا ۲۱ روز از آخرین بک‌آپ گذشته است یا خیر.
    """
    while True:
        time.sleep(3600)  # هر ۱ ساعت
        last_backup = get_last_backup_time()
        if last_backup is None or (datetime.now() - last_backup) >= timedelta(days=21):
            backup_database()

def cleanup_export(folder, zip_path):
    """حذف پوشه و فایل ZIP بعد از ارسال"""
    try:
        if folder and os.path.isdir(folder):
            shutil.rmtree(folder, ignore_errors=True)
        if zip_path and os.path.exists(zip_path):
            os.remove(zip_path)
    except Exception as e:
        logging.warning(f"Error cleaning export: {e}")

# ------------- کیبوردها -------------
service_keyboard = InlineKeyboard(
    [("🎁 اوکالا", "service_okala")],
    [("🛒 دیجی‌کالا", "service_digikala")]
)

user_keyboard = InlineKeyboard(
    [("➕ افزودن شماره", "user_register_phone")]
)

employer_keyboard = InlineKeyboard(
    [("🛒 افزودن آدرس و سبد خرید (بازه‌ای)", "admin_cart_batch")],
    [("🔍 جست‌وجوی کد تخفیف (بازه‌ای)", "admin_operation1")],
    [("📦 دریافت شماره‌های تخفیف‌دار", "admin_operation4")],
    [("👥 دریافت شماره بر اساس ثبت‌کننده", "admin_view_by_registered")],
    [("📤 خروجی شماره‌های خام", "admin_export_raw")],
    [("📊 دریافت شماره بازه‌ای", "admin_export_range")]
)

programmer_keyboard = InlineKeyboard(
    [("🛒 افزودن آدرس و سبد خرید (بازه‌ای)", "admin_cart_batch")],
    [("🔍 جست‌وجوی کد تخفیف (بازه‌ای)", "admin_operation1")],
    [("📦 دریافت شماره‌های تخفیف‌دار", "admin_operation4")],
    [("👥 دریافت شماره بر اساس ثبت‌کننده", "admin_view_by_registered")],
    [("📤 خروجی شماره‌های خام", "admin_export_raw")],
    [("📊 دریافت شماره بازه‌ای", "admin_export_range")],
    [("🔄 رفرش توکن همه کاربران", "admin_operation3")]
)

cancel_keyboard = InlineKeyboard(
    [("❌ انصراف", "cancel")],
    [("🏠 بازگشت به منوی اصلی", "menu")]
)

city_keyboard = InlineKeyboard(
    [("تهران", "city_3")],
    [("اصفهان", "city_1")],
    [("فارس", "city_2")],
    [("خراسان رضوی", "city_4")],
    [("آذربایجان شرقی", "city_5")],
    [("🏠 بازگشت", "menu")]
)

def get_admin_keyboard(user_id: int) -> InlineKeyboard:
    return programmer_keyboard if user_id in PROGRAMMER_IDS else employer_keyboard

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
    return match.group(0) if match else None

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

def is_user_processing(user_id: int) -> bool:
    return user_processing.get(user_id, False)

def set_user_processing(user_id: int, value: bool):
    user_processing[user_id] = value

def extract_error_from_logs(logs: str) -> str:
    if not logs:
        return "عملیات ناموفق بود"
    for line in logs.splitlines():
        if "[ERROR]" in line:
            return line.replace("[ERROR]", "").strip()
    return "عملیات ناموفق بود"

def run_single_okala_operation(phone: str, province: str, operation_type: str, allow_otp: bool = True):
    log_capture = StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = log_capture, log_capture
    try:
        result = okala_api.operaton(
            phone_number=phone,
            province_name=province,
            operation=operation_type,
            proxy_url=None,
            allow_otp=allow_otp
        )
        logs = log_capture.getvalue()
        if result:
            return {"success": True, "error": None, "logs": logs}
        else:
            error = extract_error_from_logs(logs)
            return {"success": False, "error": error, "logs": logs}
    except Exception as e:
        logs = log_capture.getvalue()
        return {"success": False, "error": str(e), "logs": logs}
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr

def run_export_operation(phones):
    log_capture = StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = log_capture, log_capture
    try:
        folder = export_accounts_by_phones(phones)
        logs = log_capture.getvalue()
        return {"success": True, "logs": logs, "folder": folder}
    except Exception as e:
        logs = log_capture.getvalue()
        return {"success": False, "error": str(e), "logs": logs}
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr

async def start_single_operation(message, phone: str, operation_type: str, success_text: str):
    user_id = message.author.id
    if is_user_processing(user_id):
        await message.reply("⏳ شما در حال انجام عملیات دیگری هستید.")
        return
    set_user_processing(user_id, True)
    user_last_phone[user_id] = phone
    province = "3"
    loop = asyncio.get_event_loop()
    future = loop.run_in_executor(None, run_single_okala_operation, phone, province, operation_type, True)
    try:
        result = await future
        if result.get("logs"):
            await send_log(f"📋 لاگ‌های عملیات {phone}:\n{result['logs'][-1500:]}")
        if result["success"]:
            if operation_type in ("2", "5"):
                author = message.author
                full_name = get_user_display_name(author)
                username = getattr(author, 'username', None)
                set_account_registered_by(phone, author.id, full_name, username)
                await send_log(f"👤 ثبت‌کننده {full_name} (@{username}) برای {phone} ذخیره شد.")
            await send_log(f"✅ عملیات {operation_type} برای {phone} موفق بود.")
            await message.reply(f"✅ {success_text}", reply_markup=operation_done_keyboard("okala"))
        else:
            await send_log(f"❌ عملیات {operation_type} برای {phone} ناموفق بود: {result.get('error')}")
            await message.reply(f"❌ عملیات ناموفق بود.\n{result.get('error', 'خطای ناشناخته')}", reply_markup=operation_failed_keyboard("okala"))
    except Exception as e:
        await send_log(f"❌ خطا: {e}")
        await message.reply(f"❌ خطا: {e}", reply_markup=operation_failed_keyboard("okala"))
    finally:
        set_user_processing(user_id, False)

async def start_batch_okala_operation(message, phones: list, operation_type: str = "1", province: str = "3", allow_otp: bool = True):
    user_id = message.author.id
    if is_user_processing(user_id):
        await message.reply("⏳ شما در حال انجام عملیات دیگری هستید.")
        return
    set_user_processing(user_id, True)
    batch_state[user_id] = {"phones": phones, "index": 0, "current_phone": None, "cancel": False}
    try:
        for idx, phone in enumerate(phones):
            if batch_state[user_id]["cancel"]:
                break
            batch_state[user_id]["index"] = idx
            batch_state[user_id]["current_phone"] = phone
            if allow_otp:
                user_states[user_id] = "awaiting_batch_otp"
            await send_log(f"🔄 شروع پردازش شماره {phone} ({idx+1}/{len(phones)})")
            await message.reply(
                f"⏳ در حال پردازش شماره {phone}...\n"
                + ("📩 اگر کد OTP ارسال شد، لطفاً کد را همینجا وارد کنید." if allow_otp else ""),
                reply_markup=cancel_keyboard
            )
            loop = asyncio.get_event_loop()
            future = loop.run_in_executor(None, run_single_okala_operation, phone, province, operation_type, allow_otp)
            result = await future
            if result.get("logs"):
                await send_log(f"📋 لاگ‌های شماره {phone}:\n{result['logs'][-1000:]}")
            if result["success"]:
                await message.reply(f"✅ شماره {phone} با موفقیت پردازش شد.")
            else:
                await message.reply(f"❌ شماره {phone} ناموفق بود.\n{result.get('error', '')}")
            await asyncio.sleep(random.uniform(2, 4))
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
        set_user_processing(user_id, False)
        await message.reply("سلام! 👋\nلطفاً سرویس موردنظر را انتخاب کنید:", reply_markup=service_keyboard)
        return

    if user_id not in ADMIN_IDS:
        state = user_states.get(user_id)
        if state == "awaiting_user_phone":
            phone = validate_phone(text)
            if not phone:
                await message.reply("❌ شماره نامعتبر است.", reply_markup=cancel_keyboard)
                return
            user_states[user_id] = "awaiting_user_otp"
            user_last_phone[user_id] = phone
            await message.reply(
                "⏳ درخواست ارسال شد.\n"
                "لطفاً منتظر پیامک OTP باشید.\n"
                "بعد از دریافت پیامک، کد را همینجا ارسال کنید.",
                reply_markup=cancel_keyboard
            )
            asyncio.create_task(start_single_operation(message, phone, "5", "ثبت‌نام انجام شد و پروفایل به‌روزرسانی شد."))
            return
        elif state == "awaiting_user_otp":
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

    state = user_states.get(user_id)

    if state == "awaiting_row_range":   # کد تخفیف
        parts = text.split()
        if len(parts) != 2:
            await message.reply("❌ لطفاً دو عدد (شروع و پایان) را با فاصله وارد کنید.", reply_markup=cancel_keyboard)
            return
        try:
            start_row, end_row = int(parts[0]), int(parts[1])
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
        asyncio.create_task(start_batch_okala_operation(message, phones_in_range, operation_type="1", province="3", allow_otp=True))
        return

    elif state == "awaiting_row_range_cart":   # آدرس و سبد خرید
        parts = text.split()
        if len(parts) != 2:
            await message.reply("❌ لطفاً دو عدد (شروع و پایان) را با فاصله وارد کنید.", reply_markup=cancel_keyboard)
            return
        try:
            start_row, end_row = int(parts[0]), int(parts[1])
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
        selected_province = user_selected_province.get(user_id, "3")
        await message.reply(f"🔍 {len(phones_in_range)} شماره در بازه ردیف {start_row} تا {end_row} یافت شد.\nشروع پردازش بدون OTP...")
        user_states[user_id] = None
        asyncio.create_task(start_batch_okala_operation(message, phones_in_range, operation_type="2", province=selected_province, allow_otp=False))
        return

    elif state == "awaiting_raw_range":   # خروجی خام
        parts = text.split()
        if len(parts) != 2:
            await message.reply("❌ لطفاً دو عدد (شروع و پایان) را با فاصله وارد کنید.", reply_markup=cancel_keyboard)
            return
        try:
            start_row, end_row = int(parts[0]), int(parts[1])
        except ValueError:
            await message.reply("❌ اعداد نامعتبر هستند.", reply_markup=cancel_keyboard)
            return
        if start_row < 1 or end_row < start_row:
            await message.reply("❌ بازه نامعتبر است.", reply_markup=cancel_keyboard)
            return
        raw_phones = get_phones_without_address()
        phones_in_range = raw_phones[start_row-1:end_row]
        if not phones_in_range:
            await message.reply("ℹ️ شماره خامی در این بازه یافت نشد.", reply_markup=get_admin_keyboard(user_id))
            return
        await message.reply(f"🔍 {len(phones_in_range)} شماره خام یافت شد. در حال ساخت فایل...")
        user_states[user_id] = None
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_export_operation, phones_in_range)
        folder = None
        zip_path = None
        try:
            if result["success"]:
                folder = result.get("folder")
                if folder and os.path.isdir(folder):
                    zip_path = folder + ".zip"
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for root, _, files in os.walk(folder):
                            for file in files:
                                full_path = os.path.join(root, file)
                                arcname = os.path.relpath(full_path, folder)
                                zf.write(full_path, arcname)
                    await bot.send_document(message.chat.id, document=zip_path)
                    await message.reply("📁 فایل خروجی ارسال شد.")
                else:
                    await message.reply("❌ خطا در ساخت پوشه خروجی.")
            else:
                await message.reply(f"❌ خطا: {result.get('error')}")
        finally:
            cleanup_export(folder, zip_path)
        return

    elif state == "awaiting_export_range":   # دریافت شماره بازه‌ای
        parts = text.split()
        if len(parts) != 2:
            await message.reply("❌ لطفاً دو عدد (شروع و پایان) را با فاصله وارد کنید.", reply_markup=cancel_keyboard)
            return
        try:
            start_row, end_row = int(parts[0]), int(parts[1])
        except ValueError:
            await message.reply("❌ اعداد نامعتبر هستند.", reply_markup=cancel_keyboard)
            return
        if start_row < 1 or end_row < start_row:
            await message.reply("❌ بازه نامعتبر است.", reply_markup=cancel_keyboard)
            return
        all_phones = okala_api.get_all_phones()
        if not all_phones:
            await message.reply("ℹ️ هیچ شماره‌ای در دیتابیس وجود ندارد.", reply_markup=get_admin_keyboard(user_id))
            return
        phones_in_range = all_phones[start_row-1:end_row]
        if not phones_in_range:
            await message.reply("ℹ️ هیچ شماره‌ای در این بازه ردیف یافت نشد.", reply_markup=get_admin_keyboard(user_id))
            return
        await message.reply(f"🔍 {len(phones_in_range)} شماره در بازه ردیف {start_row} تا {end_row} یافت شد. در حال ساخت فایل...")
        user_states[user_id] = None
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_export_operation, phones_in_range)
        folder = None
        zip_path = None
        try:
            if result["success"]:
                folder = result.get("folder")
                if folder and os.path.isdir(folder):
                    zip_path = folder + ".zip"
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for root, _, files in os.walk(folder):
                            for file in files:
                                full_path = os.path.join(root, file)
                                arcname = os.path.relpath(full_path, folder)
                                zf.write(full_path, arcname)
                    await bot.send_document(message.chat.id, document=zip_path)
                    await message.reply("📁 فایل خروجی ارسال شد.")
                else:
                    await message.reply("❌ خطا در ساخت پوشه خروجی.")
            else:
                await message.reply(f"❌ خطا: {result.get('error')}")
        finally:
            cleanup_export(folder, zip_path)
        return

    elif state == "awaiting_extract_count":
        try:
            count = int(text)
        except ValueError:
            await message.reply("❌ لطفاً یک عدد صحیح وارد کنید.", reply_markup=cancel_keyboard)
            return
        user_states[user_id] = None
        await message.reply("⏳ در حال استخراج کدها...")

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, okala_api.extract_and_delete_discounts, count)

        folder = None
        zip_path = None
        try:
            if result:
                folder, discounts = result

                if discounts:
                    codes_text = "📋 کدهای تخفیف استخراج‌شده:\n\n"
                    for item in discounts:
                        phone = item.get("phone", "نامشخص")
                        code = item.get("code") or "-"
                        name = item.get("name") or "-"
                        codes_text += f"📱 {phone}\n🔖 کد: {code}\n📝 نام: {name}\n\n"
                    await message.reply(codes_text)

                if folder and os.path.isdir(folder):
                    zip_path = folder + ".zip"
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for root, _, files in os.walk(folder):
                            for file in files:
                                full_path = os.path.join(root, file)
                                arcname = os.path.relpath(full_path, folder)
                                zf.write(full_path, arcname)
                    await bot.send_document(message.chat.id, document=zip_path)
                    await message.reply("📁 فایل اکانت‌ها ارسال شد.")
                else:
                    await message.reply("❌ خطا در ساخت پوشه خروجی.")
            else:
                await message.reply("❌ خطا در استخراج کدها.")
        finally:
            cleanup_export(folder, zip_path)
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
        await safe_answer(callback_query, "✅")
        return

    elif data == "service_digikala":
        await callback_query.message.reply("بخش دیجی‌کالا هنوز آماده نیست.", reply_markup=service_keyboard)
        await safe_answer(callback_query, "✅")
        return

    if user_id not in ADMIN_IDS:
        # کاربر عادی
        if data == "user_register_phone":
            if is_user_processing(user_id):
                await safe_answer(callback_query, "⏳ شما در حال انجام عملیات هستید", show_alert=True)
                return
            user_states[user_id] = "awaiting_user_phone"
            await callback_query.message.reply("لطفاً شماره موبایل خود را ارسال کنید (مثلاً 09123456789):", reply_markup=cancel_keyboard)
            await safe_answer(callback_query, "✅")

        elif data in ["next_number:okala", "retry:okala"]:
            if is_user_processing(user_id):
                await safe_answer(callback_query, "⏳ شما در حال انجام عملیات هستید", show_alert=True)
                return
            user_states[user_id] = "awaiting_user_phone"
            await callback_query.message.reply("لطفاً شماره موبایل جدید را ارسال کنید:", reply_markup=cancel_keyboard)
            await safe_answer(callback_query, "✅")

        elif data == "cancel":
            user_states[user_id] = None
            set_user_processing(user_id, False)
            await callback_query.message.reply("❌ عملیات لغو شد.", reply_markup=service_keyboard)
            await safe_answer(callback_query, "✅")

        elif data == "menu":
            user_states[user_id] = None
            set_user_processing(user_id, False)
            await callback_query.message.reply("منوی اصلی:", reply_markup=service_keyboard)
            await safe_answer(callback_query, "✅")

        else:
            await safe_answer(callback_query, "⚠️ شما دسترسی ندارید", show_alert=True)
        return

    # ادامه برای ادمین‌ها
    if data == "admin_cart_batch":
        if is_user_processing(user_id):
            await safe_answer(callback_query, "⏳ شما در حال انجام عملیات هستید", show_alert=True)
            return
        await callback_query.message.reply("🏙 ابتدا شهر موردنظر را انتخاب کنید:", reply_markup=city_keyboard)
        await safe_answer(callback_query, "✅")

    elif data.startswith("city_"):
        city_code = data.split("_")[1]
        user_selected_province[user_id] = city_code
        user_states[user_id] = "awaiting_row_range_cart"
        await callback_query.message.reply("✅ شهر انتخاب شد.\nلطفاً بازه ردیف را وارد کنید (مثال: 1 100):", reply_markup=cancel_keyboard)
        await safe_answer(callback_query, "✅")

    elif data == "admin_operation1":
        if is_user_processing(user_id):
            await safe_answer(callback_query, "⏳ شما در حال انجام عملیات هستید", show_alert=True)
            return
        user_states[user_id] = "awaiting_row_range"
        await callback_query.message.reply("لطفاً بازه ردیف را وارد کنید (مثال: 10 20):", reply_markup=cancel_keyboard)
        await safe_answer(callback_query, "✅")

    elif data == "admin_export_raw":
        if is_user_processing(user_id):
            await safe_answer(callback_query, "⏳ شما در حال انجام عملیات هستید", show_alert=True)
            return
        user_states[user_id] = "awaiting_raw_range"
        await callback_query.message.reply("لطفاً بازه ردیف شماره‌های خام را وارد کنید (مثال: 1 50):", reply_markup=cancel_keyboard)
        await safe_answer(callback_query, "✅")

    elif data == "admin_export_range":
        if is_user_processing(user_id):
            await safe_answer(callback_query, "⏳ شما در حال انجام عملیات هستید", show_alert=True)
            return
        user_states[user_id] = "awaiting_export_range"
        await callback_query.message.reply("لطفاً بازه ردیف را وارد کنید (مثال: 1 100):", reply_markup=cancel_keyboard)
        await safe_answer(callback_query, "✅")

    elif data == "admin_operation4":
        if is_user_processing(user_id):
            await safe_answer(callback_query, "⏳ شما در حال انجام عملیات هستید", show_alert=True)
            return
        user_states[user_id] = "awaiting_extract_count"
        await callback_query.message.reply("چند کد تخفیف می‌خواهید استخراج کنید؟", reply_markup=cancel_keyboard)
        await safe_answer(callback_query, "✅")

    elif data == "admin_view_by_registered":
        if is_user_processing(user_id):
            await safe_answer(callback_query, "⏳ شما در حال انجام عملیات هستید", show_alert=True)
            return
        infos = get_all_registered_by_info()
        if not infos:
            await callback_query.message.reply("ℹ️ هیچ ثبت‌کننده‌ای یافت نشد.", reply_markup=get_admin_keyboard(user_id))
            await safe_answer(callback_query, "✅")
            return
        rows = []
        for info in infos:
            name = info.get("name") or "بدون نام"
            username = info.get("username")
            label = name + (f" (@{username})" if username else "") + f" - {info.get('count', 0)} شماره"
            rows.append([(label, f"select_registered:{info['id']}")])
        rows.append([("🏠 بازگشت", "menu")])
        await callback_query.message.reply("👥 یک ثبت‌کننده را انتخاب کنید تا شماره‌های او با فرمت ZIP استخراج شوند:", reply_markup=InlineKeyboard(*rows))
        await safe_answer(callback_query, "✅")

    elif data.startswith("select_registered:"):
        if is_user_processing(user_id):
            await safe_answer(callback_query, "⏳ شما در حال انجام عملیات هستید", show_alert=True)
            return
        reg_id = int(data.split(":")[1])
        phones = get_phones_by_registered_by(reg_id)
        if not phones:
            await callback_query.message.reply("ℹ️ شماره‌ای برای این شخص یافت نشد.", reply_markup=get_admin_keyboard(user_id))
            await safe_answer(callback_query, "✅")
            return

        await callback_query.message.reply(f"🔍 {len(phones)} شماره یافت شد. در حال ساخت فایل ZIP با فرمت مخصوص...")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_export_operation, phones)
        folder = None
        zip_path = None
        try:
            if result["success"]:
                folder = result.get("folder")
                if folder and os.path.isdir(folder):
                    zip_path = folder + ".zip"
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for root, _, files in os.walk(folder):
                            for file in files:
                                full_path = os.path.join(root, file)
                                arcname = os.path.relpath(full_path, folder)
                                zf.write(full_path, arcname)
                    await bot.send_document(callback_query.message.chat.id, document=zip_path)
                    await callback_query.message.reply("📁 فایل ZIP شماره‌های ثبت‌کننده ارسال شد.")
                else:
                    await callback_query.message.reply("❌ خطا در ساخت پوشه خروجی.")
            else:
                await callback_query.message.reply(f"❌ خطا: {result.get('error')}")
        finally:
            cleanup_export(folder, zip_path)
        await safe_answer(callback_query, "✅")

    elif data == "cancel":
        if user_id in batch_state:
            batch_state[user_id]["cancel"] = True
        user_states[user_id] = None
        set_user_processing(user_id, False)
        await callback_query.message.reply("❌ عملیات لغو شد.", reply_markup=service_keyboard)
        await safe_answer(callback_query, "✅")

    elif data == "menu":
        user_states[user_id] = None
        batch_state[user_id] = {}
        user_last_phone.pop(user_id, None)
        set_user_processing(user_id, False)
        await callback_query.message.reply("منوی اصلی:", reply_markup=service_keyboard)
        await safe_answer(callback_query, "✅")

    else:
        await safe_answer(callback_query, "گزینه نامشخص")

if __name__ == "__main__":
    init_db()
    # شروع ترد بک‌آپ‌گیری دوره‌ای؛ اگر سرویس ری‌استارت شود، تایمر از ابتدا شروع نمی‌شود
    threading.Thread(target=backup_thread, daemon=True).start()
    bot.run()