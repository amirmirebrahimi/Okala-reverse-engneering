import sqlite3
import json
import os
import shutil
from datetime import datetime

DB_NAME = "okala_profiles.db"

DATA_DIR = "data"
ACCOUNTS_DIR = os.path.join(DATA_DIR, "accounts")
ACCOUNTS_REGISTRY_PATH = os.path.join(DATA_DIR, "data", "accounts.json")
DISCOUNTS_DIR = "discounts"
DISCOUNTS_FILE_PATH = os.path.join(DISCOUNTS_DIR, "discounts.json")

# پوشه‌ی مخصوص فایل‌های خروجی
EXPORT_DIR = "exported_data"


def get_connection():
    return sqlite3.connect(DB_NAME)


def _ensure_column(cur, table_name, column_name, column_type):
    cur.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cur.fetchall()]
    if column_name not in columns:
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        phone TEXT PRIMARY KEY,
        access_token TEXT,
        refresh_token TEXT,
        user_info TEXT,
        address_info TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS discounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT,
        discount_id TEXT,
        code TEXT,
        name TEXT,
        checked_at TEXT
    )
    """)

    _ensure_column(cur, "accounts", "store_info", "TEXT")
    _ensure_column(cur, "accounts", "latitude", "REAL")
    _ensure_column(cur, "accounts", "longitude", "REAL")
    _ensure_column(cur, "accounts", "address_id", "TEXT")
    _ensure_column(cur, "accounts", "store_id", "TEXT")

    # ستون‌های اطلاعات ثبت‌کننده
    _ensure_column(cur, "accounts", "registered_by_id", "INTEGER")
    _ensure_column(cur, "accounts", "registered_by_name", "TEXT")
    _ensure_column(cur, "accounts", "registered_by_username", "TEXT")

    # ستون وضعیت آدرس
    _ensure_column(cur, "accounts", "has_address", "INTEGER DEFAULT 0")

    conn.commit()
    conn.close()


def save_account(
    phone,
    access_token,
    refresh_token,
    user_info=None,
    address_info=None,
    store_info=None,
    latitude=None,
    longitude=None,
    address_id=None,
    store_id=None
):
    existing = get_account(phone)

    if existing:
        if user_info is None:
            user_info = existing.get("user_info")
        if address_info is None:
            address_info = existing.get("address_info")
        if store_info is None:
            store_info = existing.get("store_info")
        if latitude is None:
            latitude = existing.get("latitude")
        if longitude is None:
            longitude = existing.get("longitude")
        if address_id is None:
            address_id = existing.get("address_id")
        if store_id is None:
            store_id = existing.get("store_id")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO accounts (
        phone, access_token, refresh_token, user_info, address_info,
        store_info, latitude, longitude, address_id, store_id
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(phone) DO UPDATE SET
        access_token=excluded.access_token,
        refresh_token=excluded.refresh_token,
        user_info=excluded.user_info,
        address_info=excluded.address_info,
        store_info=excluded.store_info,
        latitude=excluded.latitude,
        longitude=excluded.longitude,
        address_id=excluded.address_id,
        store_id=excluded.store_id
    """, (
        phone,
        access_token,
        refresh_token,
        json.dumps(user_info, ensure_ascii=False) if user_info is not None else None,
        json.dumps(address_info, ensure_ascii=False) if address_info is not None else None,
        json.dumps(store_info, ensure_ascii=False) if store_info is not None else None,
        latitude,
        longitude,
        str(address_id) if address_id is not None else None,
        str(store_id) if store_id is not None else None
    ))

    conn.commit()
    conn.close()


def set_account_has_address(phone, status: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE accounts SET has_address = ? WHERE phone = ?", (status, phone))
    conn.commit()
    conn.close()


def save_discounts(phone, discounts):
    if not isinstance(discounts, list):
        return

    conn = get_connection()
    cur = conn.cursor()
    checked_at = datetime.now().isoformat(timespec="seconds")

    for item in discounts:
        if not isinstance(item, dict):
            continue

        discount_id = (
            item.get("id")
            or item.get("Id")
            or item.get("discountId")
            or item.get("DiscountId")
        )
        code = (
            item.get("code")
            or item.get("Code")
            or item.get("discountCode")
            or item.get("DiscountCode")
            or item.get("couponCode")
            or item.get("CouponCode")
        )
        name = (
            item.get("name")
            or item.get("Name")
            or item.get("title")
            or item.get("Title")
            or item.get("discountName")
            or item.get("DiscountName")
        )

        cur.execute("""
        INSERT INTO discounts (phone, discount_id, code, name, checked_at)
        VALUES (?, ?, ?, ?, ?)
        """, (
            phone,
            str(discount_id) if discount_id is not None else None,
            str(code) if code is not None else None,
            str(name) if name is not None else None,
            checked_at
        ))

    conn.commit()
    conn.close()


def get_account(phone):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(accounts)")
    columns = [row[1] for row in cur.fetchall()]

    has_new_columns = all(col in columns for col in ["store_info", "latitude", "longitude", "address_id", "store_id"])

    if has_new_columns:
        cur.execute("""
        SELECT phone, access_token, refresh_token, user_info, address_info,
               store_info, latitude, longitude, address_id, store_id
        FROM accounts
        WHERE phone = ?
        """, (phone,))
    else:
        cur.execute("""
        SELECT phone, access_token, refresh_token, user_info, address_info
        FROM accounts
        WHERE phone = ?
        """, (phone,))

    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    if has_new_columns:
        return {
            "phone": row[0],
            "access_token": row[1],
            "refresh_token": row[2],
            "user_info": json.loads(row[3]) if row[3] else None,
            "address_info": json.loads(row[4]) if row[4] else None,
            "store_info": json.loads(row[5]) if row[5] else None,
            "latitude": row[6],
            "longitude": row[7],
            "address_id": row[8],
            "store_id": row[9],
        }

    return {
        "phone": row[0],
        "access_token": row[1],
        "refresh_token": row[2],
        "user_info": json.loads(row[3]) if row[3] else None,
        "address_info": json.loads(row[4]) if row[4] else None,
        "store_info": None,
        "latitude": None,
        "longitude": None,
        "address_id": None,
        "store_id": None,
    }


def get_all_phones():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT phone FROM accounts")
    phones = [row[0] for row in cur.fetchall()]
    conn.close()
    return phones


def get_phones_without_address():
    """شماره‌هایی که هنوز آدرس برایشان ثبت نشده است."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT phone FROM accounts WHERE has_address = 0 ORDER BY phone")
    phones = [row[0] for row in cur.fetchall()]
    conn.close()
    return phones


def set_account_registered_by(phone, registered_by_id, registered_by_name=None, registered_by_username=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE accounts
        SET registered_by_id = ?,
            registered_by_name = ?,
            registered_by_username = ?
        WHERE phone = ?
    """, (registered_by_id, registered_by_name, registered_by_username, phone))
    conn.commit()
    conn.close()


def get_all_registered_by_info():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT registered_by_id, registered_by_name, registered_by_username, COUNT(*)
        FROM accounts
        WHERE registered_by_id IS NOT NULL
        GROUP BY registered_by_id, registered_by_name, registered_by_username
        ORDER BY registered_by_name
    """)
    rows = cur.fetchall()
    conn.close()

    result = []
    for row in rows:
        result.append({
            "id": row[0],
            "name": row[1] or "",
            "username": row[2] or "",
            "count": row[3],
        })
    return result


def get_phones_by_registered_by(registered_by_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT phone
        FROM accounts
        WHERE registered_by_id = ?
        ORDER BY phone
    """, (registered_by_id,))
    phones = [row[0] for row in cur.fetchall()]
    conn.close()
    return phones


def export_accounts_by_phones(phones, prefix="exported_accounts"):
    """
    خروجی گرفتن از اکانت‌ها بر اساس شماره‌های داده‌شده.
    پوشه‌ی خروجی داخل exported_data ساخته می‌شود.
    """
    os.makedirs(EXPORT_DIR, exist_ok=True)
    base_folder = os.path.join(EXPORT_DIR, f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    target_accounts_folder = os.path.join(base_folder, "accounts")
    target_data_inner_folder = os.path.join(base_folder, "data")

    os.makedirs(target_accounts_folder, exist_ok=True)
    os.makedirs(target_data_inner_folder, exist_ok=True)

    # خواندن accounts.json اصلی از مسیر صحیح
    if os.path.exists(ACCOUNTS_REGISTRY_PATH):
        with open(ACCOUNTS_REGISTRY_PATH, 'r', encoding='utf-8') as f:
            registry_data = json.load(f)
    else:
        registry_data = {}

    new_accounts_data = {}

    for phone in phones:
        if phone in registry_data:
            new_accounts_data[phone] = registry_data[phone]

        src_file = os.path.join(ACCOUNTS_DIR, f"{phone}.json")
        dst_file = os.path.join(target_accounts_folder, f"{phone}.json")

        if os.path.exists(src_file):
            shutil.copy2(src_file, dst_file)
        else:
            print(f"هشدار: فایل {phone}.json یافت نشد.")

    with open(os.path.join(target_data_inner_folder, "accounts.json"), 'w', encoding='utf-8') as f:
        json.dump(new_accounts_data, f, indent=4, ensure_ascii=False)

    print(f"✅ {len(phones)} شماره استخراج شد.")
    print(f"📁 خروجی در پوشه '{base_folder}' ذخیره شد.")

    return base_folder


def extract_and_delete_discounts(n, db_path="okala_profiles.db"):
    os.makedirs(EXPORT_DIR, exist_ok=True)
    base_folder = os.path.join(EXPORT_DIR, f"extract_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    target_accounts_folder = os.path.join(base_folder, "accounts")
    target_data_inner_folder = os.path.join(base_folder, "data")

    os.makedirs(target_accounts_folder, exist_ok=True)
    os.makedirs(target_data_inner_folder, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, phone, discount_id, code, name, checked_at
        FROM discounts
        ORDER BY id ASC
        LIMIT ?
    """, (n,))

    records = cursor.fetchall()

    if not records:
        print("هیچ کد تخفیفی در دیتابیس یافت نشد.")
        conn.close()
        return base_folder, []

    ids_to_delete = [row[0] for row in records]
    phones = [row[1] for row in records]

    extracted_discounts = [
        {
            "phone": row[1],
            "discount_id": row[2],
            "code": row[3],
            "name": row[4],
            "checked_at": row[5],
        }
        for row in records
    ]

    if os.path.exists(ACCOUNTS_REGISTRY_PATH):
        with open(ACCOUNTS_REGISTRY_PATH, 'r', encoding='utf-8') as f:
            registry_data = json.load(f)
    else:
        registry_data = {}

    new_accounts_data = {}

    for phone in phones:
        if phone in registry_data:
            new_accounts_data[phone] = registry_data[phone]

        src_file = os.path.join(ACCOUNTS_DIR, f"{phone}.json")
        dst_file = os.path.join(target_accounts_folder, f"{phone}.json")

        if os.path.exists(src_file):
            shutil.copy2(src_file, dst_file)
        else:
            print(f"هشدار: فایل {phone}.json یافت نشد.")

    with open(os.path.join(target_data_inner_folder, "accounts.json"), 'w', encoding='utf-8') as f:
        json.dump(new_accounts_data, f, indent=4, ensure_ascii=False)

    placeholders = ','.join('?' * len(ids_to_delete))
    cursor.execute(f"DELETE FROM discounts WHERE id IN ({placeholders})", ids_to_delete)

    conn.commit()
    conn.close()

    print(f"✅ {len(records)} رکورد استخراج و حذف شد.")
    print(f"📁 خروجی در پوشه '{base_folder}' ذخیره شد.")

    return base_folder, extracted_discounts