from pathlib import Path
import random
import json
import time
from typing import Optional, Any
from datetime import datetime
from urllib.parse import quote
from db import init_db, save_account, save_discounts , get_account, extract_and_delete_discounts, get_all_phones, set_account_has_address
from okala_api import OkalaAPI
import itertools
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import threading

otp_events = {}
otp_values = {}

import threading

otp_events = {}
otp_values = {}

def wait_for_otp(phone: str, timeout: float = None) -> str:

    event = threading.Event()
    otp_events[phone] = event

    if phone in otp_values:
        value = otp_values.pop(phone)
        otp_events.pop(phone, None)
        return value

    event.wait(timeout=timeout)
    value = otp_values.pop(phone, None)
    otp_events.pop(phone, None)
    return value

def set_otp(phone: str, otp: str) -> None:
   
    otp_values[phone] = otp
    event = otp_events.get(phone)
    if event:
        event.set()
PROXIES = []



def is_proxy_working(proxy_url, test_url="https://apigateway.okala.com", timeout=(3, 5)):
    if not proxy_url:
        return True

    proxies = {
        "http": proxy_url,
        "https": proxy_url,
    }

    try:
        response = requests.get(
            test_url,
            proxies=proxies,
            timeout=timeout
        )
        return True
    except requests.RequestException:
        return False


DEBUG_LOGS = False

DATA_DIR = Path("data")
ACCOUNTS_DIR = DATA_DIR / "accounts"
ACCOUNTS_REGISTRY_PATH = DATA_DIR / "data" / "accounts.json"
DISCOUNTS_DIR = Path("discounts") # مسیر دایرکتوری تخفیف‌ها
DISCOUNTS_FILE_PATH = DISCOUNTS_DIR / "discounts.json" # مسیر کامل فایل JSON

SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "token",
    "authorization",
    "Authorization",
    "mobilePhone",
    "phone",
    "Phone",
    "mobile",
    "Mobile",
    "UserName",
    "userName",
    "AlternativeId",
    "alternativeId",
    "customerGuid",
    "CustomerGuid",
    "cerberusId",
    "CerberusId",
}


class Terminal:
    step_counter = 0
    total_steps = 10

    @staticmethod
    def line():
        print("=" * 60)

    @staticmethod
    def header(title: str):
        Terminal.line()
        print(f" {title}")
        Terminal.line()
        print()

    @staticmethod
    def step(message: str):
        Terminal.step_counter += 1
        print(f"[{Terminal.step_counter:02d}/{Terminal.total_steps:02d}] {message}")

    @staticmethod
    def ok(message: str):
        print(f"[OK] {message}")

    @staticmethod
    def info(message: str):
        print(f"[INFO] {message}")

    @staticmethod
    def warn(message: str):
        print(f"[WARN] {message}")

    @staticmethod
    def error(message: str):
        print(f"[ERROR] {message}")

    @staticmethod
    def detail(label: str, value: Any):
        print(f"     {label:<16}: {value}")

    @staticmethod
    def blank():
        print()


def mask_value(value: Any, visible_start: int = 8, visible_end: int = 4) -> Any:
    if not isinstance(value, str):
        return value

    if len(value) <= visible_start + visible_end:
        return "***"

    return value[:visible_start] + "..." + value[-visible_end:]


def mask_phone(phone: str) -> str:
    if not isinstance(phone, str) or len(phone) < 7:
        return "***"
    return phone[:4] + "***" + phone[-4:]


def sanitize_for_log(data: Any) -> Any:
    if isinstance(data, dict):
        sanitized = {}
        for key, value in data.items():
            if key in SENSITIVE_KEYS:
                sanitized[key] = mask_value(value)
            else:
                sanitized[key] = sanitize_for_log(value)
        return sanitized

    if isinstance(data, list):
        return [sanitize_for_log(item) for item in data]

    return data


def debug_json(title: str, data: Any, sanitize: bool = True) -> None:
    if not DEBUG_LOGS:
        return

    print()
    print(f"[DEBUG] {title}")

    output_data = sanitize_for_log(data) if sanitize else data

    try:
        print(json.dumps(output_data, ensure_ascii=False, indent=2))
    except Exception:
        print(output_data)

    print()


def read_json_file(path: Path, default_value):
    if not path.exists():
        return default_value

    try:
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return default_value
        return json.loads(content)
    except Exception as e:
        Terminal.warn(f"Failed to read JSON file: {path}")
        Terminal.detail("Error", str(e))
        return default_value


def write_json_file(path: Path, data: Any) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        temp_path.replace(path)
        return True

    except Exception as e:
        Terminal.warn(f"Failed to write JSON file: {path}")
        Terminal.detail("Error", str(e))
        return False

def get_accounts_registry_path():
    return ACCOUNTS_REGISTRY_PATH


def get_now_created_at() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_now_last_used() -> str:
    return datetime.now().isoformat()


def build_storage_state_path(phone: str) -> Path:
    return ACCOUNTS_DIR / f"{phone}.json"


def get_unix_expiry_after_days(days: int) -> int:
    return int(time.time()) + (days * 24 * 60 * 60)


def build_user_cookie_value(user_info: Optional[dict]) -> str:
    if not isinstance(user_info, dict):
        return ""

    user_payload = {
        "id": user_info.get("Id") or user_info.get("id") or user_info.get("CustomerId") or user_info.get("customerId"),
        "alternativeId": user_info.get("AlternativeId") or user_info.get("alternativeId"),
        "alternativeCustomerId": user_info.get("AlternativeCustomerId") or user_info.get("alternativeCustomerId"),
        "firstName": user_info.get("FirstName") or user_info.get("firstName"),
        "lastName": user_info.get("LastName") or user_info.get("lastName"),
        "birthDate": user_info.get("BirthDate") or user_info.get("birthDate") or "",
        "genderCode": user_info.get("GenderCode") or user_info.get("genderCode"),
        "emailAddress": user_info.get("EmailAddress") or user_info.get("emailAddress"),
        "userName": user_info.get("UserName") or user_info.get("userName"),
        "mobilePhone": user_info.get("MobilePhone") or user_info.get("mobilePhone") or user_info.get("UserName") or user_info.get("userName"),
        "stateCode": user_info.get("StateCode") or user_info.get("stateCode"),
        "customerIsLoggedInForFirstTime": user_info.get("CustomerIsLoggedInForFirstTime") or user_info.get("customerIsLoggedInForFirstTime"),
        "firstLoginDateTime": user_info.get("FirstLoginDateTime") or user_info.get("firstLoginDateTime"),
        "state": user_info.get("State") if "State" in user_info else user_info.get("state"),
        "hasAddress": user_info.get("HasAddress") if "HasAddress" in user_info else user_info.get("hasAddress"),
        "birthDateEpoch": user_info.get("BirthDateEpoch") or user_info.get("birthDateEpoch"),
    }

    user_payload = {k: v for k, v in user_payload.items() if v is not None}
    return quote(json.dumps(user_payload, ensure_ascii=False))



def normalize_mobile(phone: str) -> str | None:
    if phone is None:
        return None

    phone = str(phone).strip()
    phone = phone.replace(" ", "").replace("-", "")

    # تبدیل +98xxxxxxxxxx -> 09xxxxxxxxx
    if phone.startswith("+98"):
        phone = "0" + phone[3:]

    # تبدیل 98xxxxxxxxxx -> 09xxxxxxxxx
    elif phone.startswith("98") and len(phone) == 12:
        phone = "0" + phone[2:]

    # تبدیل 9xxxxxxxxx -> 09xxxxxxxxx
    elif phone.startswith("9") and len(phone) == 10:
        phone = "0" + phone

    # اعتبارسنجی نهایی
    if len(phone) == 11 and phone.startswith("09") and phone.isdigit():
        return phone

    return None


def build_persist_root_value(
    user_info: Optional[dict],
    access_token: Optional[str],
    address_info: Optional[Any] = None,
    store_info: Optional[Any] = None,
    latitude: Optional[Any] = None,
    longitude: Optional[Any] = None,
    address_id: Optional[Any] = None,
    store_id: Optional[Any] = None,
    city_name: str = "تهران",
    city_id: str = "129",
) -> str:
    user_info = _safe_dict(user_info)
    address_info = _safe_dict(address_info)
    store_info = _safe_dict(store_info)

    user_obj = {
        "id": user_info.get("Id") or user_info.get("id") or user_info.get("CustomerId") or user_info.get("customerId"),
        "alternativeId": user_info.get("AlternativeId") or user_info.get("alternativeId"),
        "alternativeCustomerId": user_info.get("AlternativeCustomerId") or user_info.get("alternativeCustomerId"),
        "firstName": user_info.get("FirstName") or user_info.get("firstName"),
        "lastName": user_info.get("LastName") or user_info.get("lastName"),
        "birthDate": user_info.get("BirthDate") or user_info.get("birthDate") or "",
        "genderCode": user_info.get("GenderCode") or user_info.get("genderCode"),
        "emailAddress": user_info.get("EmailAddress") or user_info.get("emailAddress"),
        "userName": user_info.get("UserName") or user_info.get("userName"),
        "mobilePhone": user_info.get("MobilePhone") or user_info.get("mobilePhone") or user_info.get("UserName") or user_info.get("userName"),
        "stateCode": user_info.get("StateCode") or user_info.get("stateCode"),
        "customerIsLoggedInForFirstTime": user_info.get("CustomerIsLoggedInForFirstTime") or user_info.get("customerIsLoggedInForFirstTime"),
        "firstLoginDateTime": user_info.get("FirstLoginDateTime") or user_info.get("firstLoginDateTime"),
        "state": user_info.get("State") if "State" in user_info else user_info.get("state"),
        "hasAddress": user_info.get("HasAddress") if "HasAddress" in user_info else user_info.get("hasAddress"),
        "birthDateEpoch": user_info.get("BirthDateEpoch") or user_info.get("birthDateEpoch"),
        "token": access_token,
    }
    user_obj = {k: v for k, v in user_obj.items() if v is not None}

    map_lat = latitude if latitude is not None else address_info.get("lat", 35.69976003841564)
    map_lng = longitude if longitude is not None else address_info.get("lng", 51.33808390275898)

    persist_root = {
        "user": json.dumps({
            "user": user_obj,
            "discountCode": None
        }, ensure_ascii=False),
        "cart": json.dumps({
            "cartData": [],
            "totalCartsCount": 0,
            "showDrawer": False,
            "cartTotalPrice": 0
        }, ensure_ascii=False),
        "mapInfo": json.dumps({
            "defaultViewPort": {
                "latitude": map_lat,
                "longitude": map_lng,
                "id": int(city_id),
                "name": city_name
            },
            "viewport": {
                "latitude": map_lat,
                "longitude": map_lng
            },
            "discovery": {},
            "searchCity": "",
            "searchLocation": "",
            "filteredCities": [],
            "searchLocationResult": [],
            "selectedCity": {
                "id": int(city_id),
                "name": city_name,
                "lat": 35.6997548,
                "lng": 51.3355162
            },
            "mapCityName": city_name,
            "showSearchCityResult": False,
            "showSearchLocationResult": False,
            "mapIsTouched": False,
            "eventStartTime": 0,
            "eventStartTimeForEditAddress": 0,
            "zoomMeasure": 15,
            "mapPlatform": "ParsiMap"
        }, ensure_ascii=False),
        "wallet": json.dumps({
            "selectedPriceState": None
        }, ensure_ascii=False),
        "route": json.dumps({
            "fromRoute": "",
            "data": None
        }, ensure_ascii=False),
        "eventData": json.dumps({
            "isLoggedIn": True,
            "platform": "web",
            "viewedLayersCount": 0,
            "activeDiscountCodesCount": 0,
            "sessionLayersViewedCount": 0
        }, ensure_ascii=False),
        "selectedAddress": json.dumps(address_info, ensure_ascii=False),
        "selectedStore": json.dumps(store_info, ensure_ascii=False),
        "selectedAddressId": json.dumps(address_id, ensure_ascii=False),
        "selectedStoreId": json.dumps(store_id, ensure_ascii=False),
        "_persist": json.dumps({
            "version": -1,
            "rehydrated": True
        }, ensure_ascii=False),
    }

    return json.dumps(persist_root, ensure_ascii=False)

def load_accounts_registry_for_refresh():
    registry_path = get_accounts_registry_path()
    registry_data = read_json_file(registry_path, {})

    if not isinstance(registry_data, dict):
        Terminal.warn("Accounts registry is invalid. Expected a JSON object.")
        return {}

    return registry_data



def _cookie_key(cookie: dict):
    return (
        cookie.get("name"),
        cookie.get("domain"),
        cookie.get("path"),
    )


def _merge_cookies(old_cookies: list, new_cookies: list) -> list:
    merged = {}

    for item in old_cookies:
        if isinstance(item, dict) and item.get("name"):
            merged[_cookie_key(item)] = dict(item)

    for item in new_cookies:
        if not isinstance(item, dict) or not item.get("name"):
            continue

        key = _cookie_key(item)
        new_value = item.get("value")

        if key in merged:
            old_value = merged[key].get("value")
            if not _is_non_empty(new_value) and _is_non_empty(old_value):
                continue

        merged[key] = dict(item)

    return list(merged.values())



def _merge_local_storage(old_items: list, new_items: list) -> list:
    merged = {}

    for item in old_items:
        if isinstance(item, dict) and item.get("name") is not None:
            merged[item["name"]] = dict(item)

    for item in new_items:
        if not isinstance(item, dict) or item.get("name") is None:
            continue

        key = item["name"]
        new_value = item.get("value")

        if key in merged:
            old_value = merged[key].get("value")
            if not _is_non_empty(new_value) and _is_non_empty(old_value):
                continue

        merged[key] = dict(item)

    return list(merged.values())


def _merge_origins(old_origins: list, new_origins: list) -> list:
    merged = {}

    for origin_item in old_origins:
        if isinstance(origin_item, dict) and origin_item.get("origin"):
            merged[origin_item["origin"]] = {
                "origin": origin_item["origin"],
                "localStorage": origin_item.get("localStorage", []),
            }

    for origin_item in new_origins:
        if not isinstance(origin_item, dict) or not origin_item.get("origin"):
            continue

        origin = origin_item["origin"]
        old_ls = merged.get(origin, {}).get("localStorage", [])
        new_ls = origin_item.get("localStorage", [])

        merged[origin] = {
            "origin": origin,
            "localStorage": _merge_local_storage(old_ls, new_ls),
        }

    return list(merged.values())


def update_accounts_registry(
    phone: str,
    user_info: Optional[dict] = None,
    access_token: Optional[str] = None,
    refresh_token: Optional[str] = None,
) -> dict:
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)

    registry = read_json_file(ACCOUNTS_REGISTRY_PATH, {})

    if not isinstance(registry, dict):
        registry = {}

    storage_state_path = build_storage_state_path(phone)
    now_last_used = get_now_last_used()
    existing_item = registry.get(phone)

    if isinstance(existing_item, dict):
        created_at = existing_item.get("created_at") or get_now_created_at()
    else:
        created_at = get_now_created_at()

    registry_item = {
        "phone": phone,
        "storage_state_path": str(storage_state_path),
        "created_at": created_at,
        "last_used": now_last_used,
    }

    if isinstance(user_info, dict):
        registry_item["customer_id"] = (
            user_info.get("AlternativeId")
            or user_info.get("alternativeId")
            or user_info.get("AlternativeCustomerId")
            or user_info.get("alternativeCustomerId")
            or user_info.get("CustomerId")
            or user_info.get("customerId")
            or user_info.get("Id")
            or user_info.get("id")
        )
        registry_item["user_id"] = user_info.get("Id") or user_info.get("id")
        registry_item["phone_from_user"] = (
            user_info.get("MobilePhone")
            or user_info.get("mobilePhone")
            or user_info.get("UserName")
            or user_info.get("userName")
        )

    if access_token:
        registry_item["has_access_token"] = True

    if refresh_token:
        registry_item["has_refresh_token"] = True

    registry[phone] = registry_item
    write_json_file(ACCOUNTS_REGISTRY_PATH, registry)

    return registry_item


def _is_non_empty(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _safe_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _find_cookie_value(cookies: list, name: str, domain: str | None = None):
    for c in cookies:
        if not isinstance(c, dict):
            continue
        if c.get("name") != name:
            continue
        if domain is not None and c.get("domain") != domain:
            continue
        value = c.get("value")
        if _is_non_empty(value):
            return value
    return None


def _find_local_storage_value(origins: list, origin_url: str, key: str):
    for origin in origins:
        if not isinstance(origin, dict):
            continue
        if origin.get("origin") != origin_url:
            continue
        for item in origin.get("localStorage", []):
            if isinstance(item, dict) and item.get("name") == key:
                value = item.get("value")
                if value is not None:
                    return value
    return None




def save_account_storage_state(
    phone: str,
    access_token: Optional[str] = None,
    refresh_token: Optional[str] = None,
    user_info: Optional[dict] = None,
    address_info: Optional[Any] = None,
    store_info: Optional[Any] = None,
    latitude: Optional[Any] = None,
    longitude: Optional[Any] = None,
    address_id: Optional[Any] = None,
    store_id: Optional[Any] = None,
    cart_results: Optional[list] = None,
    operation: Optional[str] = None,
) -> dict:
    del cart_results, operation

    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)

    registry_item = update_accounts_registry(
        phone=phone,
        user_info=user_info,
        access_token=access_token,
        refresh_token=refresh_token,
    )

    storage_state_path = Path(registry_item["storage_state_path"])
    old_state = read_json_file(storage_state_path, {})

    if not isinstance(old_state, dict):
        old_state = {}

    old_cookies = old_state.get("cookies", []) if isinstance(old_state.get("cookies"), list) else []
    old_origins = old_state.get("origins", []) if isinstance(old_state.get("origins"), list) else []

    old_access_token = _find_local_storage_value(old_origins, "https://www.okala.com", "token")
    if not old_access_token:
        old_access_token = _find_local_storage_value(old_origins, "https://www.okala.com", "tokenMS")

    final_access_token = access_token or old_access_token
    final_refresh_token = refresh_token or _find_cookie_value(old_cookies, "refresh_token", ".okala.com")

    user_cookie_value = build_user_cookie_value(user_info) if isinstance(user_info, dict) else (
        _find_local_storage_value(old_origins, "https://www.okala.com", "user") or ""
    )

    persist_root_value = build_persist_root_value(
        user_info=user_info,
        access_token=final_access_token,
        address_info=address_info,
        store_info=store_info,
        latitude=latitude,
        longitude=longitude,
        address_id=address_id,
        store_id=store_id,
    )

    token_expiry = -1
    if isinstance(final_access_token, str) and final_access_token:
        token_expiry = get_unix_expiry_after_days(1)

    refresh_expiry = -1
    if isinstance(final_refresh_token, str) and final_refresh_token:
        refresh_expiry = get_unix_expiry_after_days(180)

    new_cookies = []

    ts1 = _find_cookie_value(old_cookies, "TS01ac68a0", ".apigateway.okala.com")
    if ts1:
        new_cookies.append({
            "name": "TS01ac68a0",
            "value": ts1,
            "domain": ".apigateway.okala.com",
            "path": "/",
            "expires": -1,
            "httpOnly": False,
            "secure": False,
            "sameSite": "Lax"
        })

    ts2 = _find_cookie_value(old_cookies, "TS0163d06f", ".okala.com")
    if ts2:
        new_cookies.append({
            "name": "TS0163d06f",
            "value": ts2,
            "domain": ".okala.com",
            "path": "/",
            "expires": -1,
            "httpOnly": False,
            "secure": False,
            "sameSite": "Lax"
        })

    if final_refresh_token:
        new_cookies.append({
            "name": "refresh_token",
            "value": final_refresh_token,
            "domain": ".okala.com",
            "path": "/",
            "expires": refresh_expiry,
            "httpOnly": True,
            "secure": True,
            "sameSite": "None"
        })

    if final_access_token:
        new_cookies.append({
            "name": "tokenMS",
            "value": final_access_token,
            "domain": "www.okala.com",
            "path": "/",
            "expires": token_expiry,
            "httpOnly": False,
            "secure": False,
            "sameSite": "Lax"
        })
        new_cookies.append({
            "name": "token",
            "value": final_access_token,
            "domain": "www.okala.com",
            "path": "/",
            "expires": token_expiry,
            "httpOnly": False,
            "secure": False,
            "sameSite": "Lax"
        })

    if user_cookie_value:
        new_cookies.append({
            "name": "user",
            "value": user_cookie_value,
            "domain": "www.okala.com",
            "path": "/",
            "expires": -1,
            "httpOnly": False,
            "secure": False,
            "sameSite": "Lax"
        })

    new_origins = [
        {
            "origin": "https://www.okala.com",
            "localStorage": [
                {
                    "name": "tokenMS",
                    "value": final_access_token or ""
                },
                {
                    "name": "token",
                    "value": final_access_token or ""
                },
                {
                    "name": "user",
                    "value": user_cookie_value or ""
                },
                {
                    "name": "city_name",
                    "value": "تهران"
                },
                {
                    "name": "city_id",
                    "value": "129"
                },
                {
                    "name": "persist:root",
                    "value": persist_root_value
                }
            ]
        }
    ]

    merged_state = {
        "cookies": _merge_cookies(old_cookies, new_cookies),
        "origins": _merge_origins(old_origins, new_origins),
    }

    write_json_file(storage_state_path, merged_state)
    return registry_item

def is_valid_lat_lng(lat: Any, lng: Any) -> bool:
    try:
        lat = float(lat)
        lng = float(lng)
    except Exception:
        return False

    return -90 <= lat <= 90 and -180 <= lng <= 180


def normalize_text(value: str) -> str:
    if not value:
        return ""

    value = value.strip()
    value = value.replace("ي", "ی").replace("ك", "ک")
    value = " ".join(value.split())

    return value


def normalize_province_name(province_name: str) -> str:
    province_name = normalize_text(province_name)

    aliases = {
        "تهران": "تهران",
        "خراسان رضوی": "خراسان رضوی",
        "رضوی": "خراسان رضوی",
        "مشهد": "خراسان رضوی",
        "آذربایجان غربی": "آذربایجان غربی",
        "اذربایجان غربی": "آذربایجان غربی",
        "آذربايجان غربی": "آذربایجان غربی",
        "ارومیه": "آذربایجان غربی",
        "آذربایجان شرقی": "آذربایجان شرقی",
        "اذربایجان شرقی": "آذربایجان شرقی",
        "آذربايجان شرقی": "آذربایجان شرقی",
        "تبریز": "آذربایجان شرقی",
        "اصفهان": "اصفهان",
        "اصفهان": "اصفهان",
        "فارس": "فارس",
        "شیراز": "فارس",
        "تهران": "تهران",
        "خراسان رضوی": "خراسان رضوی",
        "مشهد": "خراسان رضوی",
        "آذربایجان شرقی": "آذربایجان شرقی",
        "اذربایجان شرقی": "آذربایجان شرقی",
        "تبریز": "آذربایجان شرقی"


    }

    return aliases.get(province_name, province_name)


def extract_store_id(store_obj: dict):
    if not isinstance(store_obj, dict):
        return None

    for key in ["storeId", "StoreId", "id", "Id"]:
        if key in store_obj and store_obj[key] is not None:
            return store_obj[key]

    return None


def is_supermarket_store(store: dict) -> bool:
    if not isinstance(store, dict):
        return False

    store_category_name = normalize_text(
        str(
            store.get("storeCategoryName")
            or store.get("StoreCategoryName")
            or store.get("categoryName")
            or store.get("CategoryName")
            or ""
        )
    )

    store_category_id = store.get("storeCategoryId") or store.get("StoreCategoryId")

    return store_category_name == "سوپرمارکت" or store_category_id == 3


def select_random_store(store_list):
    if not store_list:
        return None

    valid_stores = []

    for store in store_list:
        if not isinstance(store, dict):
            continue

        store_id = extract_store_id(store)
        if store_id is None:
            continue

        if not is_supermarket_store(store):
            continue

        valid_stores.append(store)

    if not valid_stores:
        return None

    return random.choice(valid_stores)


def pick_random_name(file_path: str = "Profile_name.txt") -> Optional[str]:
    path = Path(file_path)

    if not path.exists():
        Terminal.error(f"Names file not found: {file_path}")
        return None

    try:
        names = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except Exception as e:
        Terminal.error(f"Failed to read names file: {e}")
        return None

    if not names:
        Terminal.error("Profile_name.txt is empty.")
        return None

    return random.choice(names)

def extract_accounts_from_registry(registry_data):
    if not isinstance(registry_data, dict):
        return []

    accounts = []

    for phone, account_data in registry_data.items():
        if not isinstance(account_data, dict):
            continue

        item = dict(account_data)
        item.setdefault("phone", phone)
        accounts.append(item)

    return accounts


def build_update_customer_payload(first_name: str) -> dict:
    return {
        "birthDate": "",
        "birthDateEpoch": 0,
        "customerType": 0,
        "emailAddress": None,
        "firstName": first_name,
        "gender": "female",
        "genderCode": 0,
        "genderTitle": "مونث",
        "lastName": first_name + "ی",
    }


def extract_customer_id(user_info: dict):
    if not isinstance(user_info, dict):
        return None

    preferred_keys = [
        "customerId",
        "CustomerId",
        "alternativeCustomerId",
        "AlternativeCustomerId",
        "id",
        "Id",
    ]

    for key in preferred_keys:
        value = user_info.get(key)
        if value is None or value == "":
            continue

        try:
            return int(value)
        except (TypeError, ValueError):
            continue

    return None


def extract_address_list(addresses_result):
    if isinstance(addresses_result, list):
        return addresses_result

    if not isinstance(addresses_result, dict):
        return []

    data = addresses_result.get("data")

    if isinstance(data, dict):
        if isinstance(data.get("customerAddressResponseItems"), list):
            return data.get("customerAddressResponseItems")

        for key in ["items", "result", "addresses", "data", "value", "results"]:
            value = data.get(key)
            if isinstance(value, list):
                return value

    for key in ["items", "result", "addresses", "data", "value", "results"]:
        value = addresses_result.get(key)
        if isinstance(value, list):
            return value

    return []

def get_user_info_from_account(account_data):
    if not isinstance(account_data, dict):
        return None

    user_info = account_data.get("user_info")
    if isinstance(user_info, dict):
        return user_info

    return None



def get_refresh_token_from_account(account_data):
    if not account_data:
        return None

    # direct field on account
    direct_refresh = account_data.get("refresh_token")
    if direct_refresh:
        return direct_refresh

    storage_path = (
        account_data.get("storage_state_path")
        or account_data.get("storagePath")
        or account_data.get("storage_state")
    )

    if not storage_path:
        return None

    storage_data = load_account_storage_state_by_path(storage_path)
    if not storage_data:
        return None

    # اگر refresh token داخل origins/localStorage ذخیره شده باشد
    origins = storage_data.get("origins", [])
    for origin in origins:
        local_storage = origin.get("localStorage", [])
        for item in local_storage:
            name = item.get("name", "")
            value = item.get("value")
            if name in ("refresh_token", "refreshToken", "okala_refresh_token") and value:
                return value

    # اگر داخل cookies ذخیره شده باشد
    cookies = storage_data.get("cookies", [])
    for cookie in cookies:
        name = cookie.get("name", "")
        value = cookie.get("value")
        if name in ("refresh_token", "refreshToken", "okala_refresh_token") and value:
            return value

    return None


def get_user_info_for_refresh(account_data):
    if not isinstance(account_data, dict):
        return None

    user_info = account_data.get("user_info")
    if isinstance(user_info, dict):
        return user_info

    storage_state_path = account_data.get("storage_state_path")
    storage_data = load_account_storage_state_by_path(storage_state_path)

    user_info = storage_data.get("user_info")
    if isinstance(user_info, dict):
        return user_info

    return None


def refresh_all_users_tokens():
    Terminal.header("Refresh All Users Tokens")

    registry_data = load_accounts_registry_for_refresh()
    accounts = extract_accounts_from_registry(registry_data)

    if not accounts:
        Terminal.warn("No accounts found in registry.")
        return

    api = OkalaAPI()

    total_count = len(accounts)
    success_count = 0
    failed_count = 0
    skipped_count = 0

    Terminal.detail("Total accounts found", str(total_count))
    Terminal.blank()

    for index, account_data in enumerate(accounts, start=1):
        phone = str(account_data.get("phone", "")).strip()
        masked_phone = mask_phone(phone) if phone else "Unknown"

        Terminal.step(f"[{index}/{total_count}] Refreshing tokens for {masked_phone}")

        storage_state_path = account_data.get("storage_state_path")
        if not storage_state_path:
            Terminal.warn("Skipped: storage_state_path not found in registry.")
            skipped_count += 1
            Terminal.blank()
            continue

        refresh_token_value = get_refresh_token_from_account(account_data)
        if not refresh_token_value:
            Terminal.warn("Skipped: refresh_token not found in storage state.")
            skipped_count += 1
            Terminal.blank()
            continue

        user_info = get_user_info_for_refresh(account_data)
        if not isinstance(user_info, dict):
            Terminal.warn("Skipped: user_info not found in storage state.")
            skipped_count += 1
            Terminal.blank()
            continue

        try:
            result = api.refresh_token(refresh_token_value)
        except Exception as e:
            Terminal.error(f"Refresh request failed: {e}")
            failed_count += 1
            Terminal.blank()
            continue

        debug_json(f"Refresh token response for {masked_phone}", result)

        if not isinstance(result, dict):
            Terminal.error("Invalid refresh response format.")
            failed_count += 1
            Terminal.blank()
            continue

        new_access_token = result.get("access_token")
        new_refresh_token = result.get("refresh_token") or refresh_token_value

        if not new_access_token:
            Terminal.error("Refresh failed: access_token not found in response.")
            if result.get("message"):
                Terminal.detail("Server message", str(result.get("message")))
            if result.get("error"):
                Terminal.detail("Server error", str(result.get("error")))
            failed_count += 1
            Terminal.blank()
            continue

        try:
            save_account_storage_state(
                phone=phone,
                access_token=new_access_token,
                refresh_token=new_refresh_token,
                user_info=user_info,
            )

            update_accounts_registry(
                phone=phone,
                user_info=user_info,
                access_token=new_access_token,
                refresh_token=new_refresh_token,
            )

            Terminal.ok(f"Tokens refreshed successfully for {masked_phone}")
            success_count += 1

        except Exception as e:
            Terminal.error(f"Failed to save refreshed tokens: {e}")
            failed_count += 1

        Terminal.blank()

    Terminal.header("Refresh Summary")
    Terminal.detail("Total", str(total_count))
    Terminal.detail("Success", str(success_count))
    Terminal.detail("Failed", str(failed_count))
    Terminal.detail("Skipped", str(skipped_count))



def load_account_storage_state_by_path(storage_state_path):
    if not storage_state_path:
        return {}

    storage_data = read_json_file(storage_state_path, {})
    if not isinstance(storage_data, dict):
        return {}

    return storage_data


def extract_product_id(product):
    if not isinstance(product, dict):
        return None

    keys = [
        "productId",
        "ProductId",
        "id",
        "Id",
        "productID",
        "ProductID",
    ]

    for key in keys:
        value = product.get(key)

        if value is None:
            continue

        try:
            return int(value)
        except Exception:
            continue

    return None


def extract_product_store_id(product):
    if not isinstance(product, dict):
        return "0"

    keys = [
        "productStoreId",
        "ProductStoreId",
        "storeProductId",
        "StoreProductId",
    ]

    for key in keys:
        value = product.get(key)

        if value is not None:
            return str(value)

    return "0"


def is_product_available(product):
    if not isinstance(product, dict):
        return False

    availability_true_keys = [
        "isAvailable",
        "IsAvailable",
        "available",
        "Available",
        "isExist",
        "IsExist",
        "hasStock",
        "HasStock",
    ]

    for key in availability_true_keys:
        if key in product:
            return bool(product.get(key))

    stock_keys = [
        "stock",
        "Stock",
        "quantity",
        "Quantity",
        "availableQuantity",
        "AvailableQuantity",
    ]

    for key in stock_keys:
        if key in product:
            try:
                return int(product.get(key)) > 0
            except Exception:
                pass

    return True


def select_random_products(product_list, count=3):
    valid_products = []

    for product in product_list:
        product_id = extract_product_id(product)

        if product_id is None:
            continue

        if not is_product_available(product):
            continue

        valid_products.append(product)

    if not valid_products:
        return []

    if len(valid_products) <= count:
        return valid_products

    return random.sample(valid_products, count)


def select_best_address(address_list):
    if not address_list:
        return None

    for item in address_list:
        if isinstance(item, dict) and item.get("isDefault") is True:
            return item

    for item in address_list:
        if isinstance(item, dict):
            lat, lng = extract_lat_lng(item)
            if is_valid_lat_lng(lat, lng):
                return item

    return address_list[0]


def extract_lat_lng(address_obj: dict):
    if not isinstance(address_obj, dict):
        return None, None

    lat = None
    lng = None

    for key in ["lat", "latitude", "Latitude", "Lat"]:
        if key in address_obj:
            lat = address_obj[key]
            break

    for key in ["lng", "longitude", "Longitude", "Lng"]:
        if key in address_obj:
            lng = address_obj[key]
            break

    try:
        lat = float(lat) if lat is not None else None
    except Exception:
        lat = None

    try:
        lng = float(lng) if lng is not None else None
    except Exception:
        lng = None

    if not is_valid_lat_lng(lat, lng):
        return None, None

    return lat, lng


def extract_address_id(address_obj: dict):
    if not isinstance(address_obj, dict):
        return None

    for key in ["id", "Id", "addressId", "AddressId"]:
        if key in address_obj and address_obj[key] is not None:
            return address_obj[key]

    return None


def extract_store_list(stores_result):
    if isinstance(stores_result, list):
        return stores_result

    if not isinstance(stores_result, dict):
        return []

    # ابتدا کلیدهای اصلی را بررسی کن
    for key in ["data", "result", "items", "stores", "value", "results"]:
        value = stores_result.get(key)
        if isinstance(value, list):
            return value

    # اگر داخل data یا result یک شیء دیگر بود که خودش دارای لیست است
    data = stores_result.get("data")
    if isinstance(data, dict):
        for key in ["stores", "items", "result", "value", "results"]:
            value = data.get(key)
            if isinstance(value, list):
                return value

    result = stores_result.get("result")
    if isinstance(result, dict):
        for key in ["stores", "items", "data", "value", "results"]:
            value = result.get(key)
            if isinstance(value, list):
                return value

    return []


def extract_product_list(products_response):
    if isinstance(products_response, list):
        return products_response

    if not isinstance(products_response, dict):
        return []

    possible_paths = [
        ("entities",),
        ("Entities",),
        ("data",),
        ("Data",),
        ("result",),
        ("Result",),
        ("items",),
        ("Items",),
        ("products",),
        ("Products",),
        ("data", "entities"),
        ("data", "Entities"),
        ("Data", "entities"),
        ("Data", "Entities"),
        ("data", "items"),
        ("data", "Items"),
        ("Data", "items"),
        ("Data", "Items"),
        ("data", "products"),
        ("data", "Products"),
        ("Data", "products"),
        ("Data", "Products"),
        ("result", "entities"),
        ("result", "Entities"),
        ("Result", "entities"),
        ("Result", "Entities"),
        ("result", "items"),
        ("result", "Items"),
        ("Result", "items"),
        ("Result", "Items"),
        ("result", "products"),
        ("result", "Products"),
        ("Result", "products"),
        ("Result", "Products"),
    ]

    for path in possible_paths:
        current = products_response

        for key in path:
            if isinstance(current, dict):
                current = current.get(key)
            else:
                current = None
                break

        if isinstance(current, list):
            return current

    return []


def load_addresses_data(file_path: str = "addresses.json") -> dict:
    path = Path(file_path)

    if not path.exists():
        Terminal.error(f"Addresses file not found: {file_path}")
        return {}

    try:
        raw_text = path.read_text(encoding="utf-8")
    except Exception as e:
        Terminal.error(f"Failed to read addresses file: {e}")
        return {}

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        Terminal.error(f"Invalid JSON in addresses file: {e}")
        return {}

    if not isinstance(data, dict):
        Terminal.error("Invalid addresses.json structure. Root value must be an object.")
        return {}

    return data


def pick_random_address_for_province(
    province_name: str,
    file_path: str = "addresses.json"
) -> Optional[dict]:
    data = load_addresses_data(file_path)
    if not data:
        return None

    normalized_name = normalize_province_name(province_name)
    province_addresses = data.get(normalized_name)

    if not isinstance(province_addresses, list) or not province_addresses:
        Terminal.error(f"No addresses found for province: {province_name}")
        Terminal.info(f"Available provinces: {', '.join(data.keys())}")
        return None

    valid_addresses = []

    for item in province_addresses:
        if not isinstance(item, dict):
            continue

        lat = item.get("latitude")
        lng = item.get("longitude")
        address = str(item.get("addressLine") or "").strip()

        if not address:
            continue

        if not is_valid_lat_lng(lat, lng):
            continue

        valid_addresses.append({
            "title": str(item.get("title", "Home")).strip() or "Home",
            "address": address,
            "lat": float(lat),
            "lng": float(lng),
            "plaque": str(item.get("plaque", "1")).strip() or "1",
            "unit": str(item.get("unit", "1")).strip() or "1",
        })

    if not valid_addresses:
        Terminal.error(f"No valid address found for province: {normalized_name}")
        return None

    selected = random.choice(valid_addresses)
    Terminal.detail("Random address selected", selected["address"])
    Terminal.detail("Latitude", selected["lat"])
    Terminal.detail("Longitude", selected["lng"])
    return selected

def build_add_address_payload(customer_id: Any, address_data: dict) -> dict:
    address_text = str(address_data.get("address") or "").strip()

    if not address_text:
        raise ValueError("address_data['address'] is empty.")

    try:
        customer_id_int = int(customer_id)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid customer_id for add address: {customer_id!r}")

    return {
        "ShoppingSectorPartId": 0,
        "address": address_text,
        "addressTypeId": 3,
        "customerId": customer_id_int,
        "id": 0,
        "lat": float(address_data["lat"]),
        "lng": float(address_data["lng"]),
        "mapPlatform": "ParsiMap",
        "mobilePhone": "",
        "plaque": str(address_data.get("plaque", "1")).strip() or "1",
        "shoppingSectorId": 0,
        "title": str(address_data.get("title", "Home")).strip() or "Home",
        "unit": str(address_data.get("unit", "1")).strip() or "1",
    }




    

def save_discounts_json(phone: str, discount_list: list) -> None:
    DISCOUNTS_DIR.mkdir(parents=True, exist_ok=True) # ایجاد دایرکتوری در صورت عدم وجود

        # خواندن داده‌های موجود از فایل discounts.json
        # اگر فایل وجود نداشته باشد یا خالی باشد، مقدار پیش‌فرض {} برگردانده می‌شود
    discounts_data = read_json_file(DISCOUNTS_FILE_PATH, default_value={})

        # آپدیت لیست تخفیف‌ها برای شماره تلفن فعلی
        # ساختار داده برای هر شماره تلفن شامل لیست تخفیف‌ها و زمان آخرین به‌روزرسانی است
    discounts_data[phone] = {
            "discounts": discount_list,
            "last_updated": datetime.now().isoformat() # ثبت زمان به‌روزرسانی
        }

        # ذخیره کل داده‌ها در فایل discounts.json
    if write_json_file(DISCOUNTS_FILE_PATH, discounts_data):
        Terminal.ok(f"Discounts for {mask_phone(phone)} saved/updated successfully in {DISCOUNTS_FILE_PATH}.")
    else:
        Terminal.error(f"Failed to save discounts for {mask_phone(phone)} to {DISCOUNTS_FILE_PATH}.")

    # اطمینان حاصل کنید که توابع کمکی مانند mask_phone، read_json_file و write_json_file در فایل شما تعریف شده‌اند.

def is_success_response(result: Any) -> bool:
    if not isinstance(result, dict):
        return False

    if result.get("success") is False:
        return False

    status_code = result.get("status_code")

    if isinstance(status_code, int) and status_code >= 400:
        return False

    return True


def get_store_name(store: dict) -> str:
    if not isinstance(store, dict):
        return "Unknown Store"

    return (
        store.get("name")
        or store.get("storeName")
        or store.get("title")
        or store.get("StoreName")
        or "Unknown Store"
    )


def get_product_name(product: dict) -> str:
    if not isinstance(product, dict):
        return "Unknown Product"

    return (
        product.get("name")
        or product.get("Name")
        or product.get("title")
        or product.get("Title")
        or "Unknown Product"
    )


def count_eligible_stores(store_list) -> int:
    if not store_list:
        return 0

    count = 0
    for store in store_list:
        if isinstance(store, dict) and extract_store_id(store) is not None and is_supermarket_store(store):
            count += 1
    return count


def add_random_items_to_cart(api, access_token, store_id, product_list, count=3):
    selected_products = select_random_products(product_list, count=count)

    if not selected_products:
        Terminal.warn("No valid products available for cart insertion.")
        return []

    results = []

    for index, product in enumerate(selected_products, start=1):
        product_id = extract_product_id(product)
        product_store_id = extract_product_store_id(product)
        product_name = get_product_name(product)

        result = api.add_to_shopping_cart(
            access_token=access_token,
            store_id=store_id,
            product_id=product_id,
            product_store_id=product_store_id,
            quantity=1,
        )

        results.append({
            "product_id": product_id,
            "product_store_id": product_store_id,
            "product_name": product_name,
            "result": result,
        })

        if isinstance(result, dict) and result.get("ok") and result.get("success", True):
            Terminal.ok(f"Product added to cart. {index}/{len(selected_products)}")
            Terminal.detail("Product", product_name)
        else:
            Terminal.error(f"Failed to add product to cart. {index}/{len(selected_products)}")
            Terminal.detail("Product", product_name)
            if isinstance(result, dict):
                Terminal.detail("Status code", result.get("status_code"))

        
        time.sleep(random.uniform(0.5, 1.5))
    
    return results


def extract_discount_list(discounts_response):
    if isinstance(discounts_response, list):
        return discounts_response

    if not isinstance(discounts_response, dict):
        return []

    possible_paths = [
        ("data",),
        ("result",),
        ("items",),
        ("discounts",),
        ("value",),
        ("results",),
        ("data", "items"),
        ("data", "discounts"),
        ("result", "items"),
        ("result", "discounts"),
    ]

    for path in possible_paths:
        current = discounts_response

        for key in path:
            if isinstance(current, dict):
                current = current.get(key)
            else:
                current = None
                break

        if isinstance(current, list):
            return current

    return []




MAX_WORKERS = 31


def process_phone_task(args):
    i, phone, province, choose_operation, current_proxy, total = args

    Terminal.detail(
        f"Processing phone {i+1}/{total} with proxy",
        f"{current_proxy if current_proxy else 'No Proxy'}"
    )
    Terminal.detail("Doing Operation for this Phone Number", mask_phone(phone))

    try:
        result = operaton(
            phone_number=phone,
            province_name=province,
            operation=choose_operation,
            proxy_url=current_proxy
        )

        return {
            "phone": phone,
            "success": bool(result),
            "error": None if result else "Operation failed"
        }

    except Exception as e:
        Terminal.error(f"An error occurred for phone {mask_phone(phone)}: {e}")
        return {"phone": phone, "success": False, "error": str(e)}


def get_discount_name(discount: dict) -> str:
    if not isinstance(discount, dict):
        return "Unknown Discount"

    return (
        discount.get("name")
        or discount.get("Name")
        or discount.get("title")
        or discount.get("Title")
        or discount.get("discountName")
        or discount.get("DiscountName")
        or "Unknown Discount"
    )


def get_discount_code(discount: dict):
    if not isinstance(discount, dict):
        return None

    return (
        discount.get("code")
        or discount.get("Code")
        or discount.get("discountCode")
        or discount.get("DiscountCode")
        or discount.get("couponCode")
        or discount.get("CouponCode")
    )


def get_discount_id(discount: dict):
    if not isinstance(discount, dict):
        return None

    return (
        discount.get("id")
        or discount.get("Id")
        or discount.get("discountId")
        or discount.get("DiscountId")
    )


def find_discounts(api, access_token, customer_id, phone):
    Terminal.blank()
    Terminal.step("Loading customer discounts...")

    if not customer_id:
        Terminal.error("Customer ID not found. Cannot fetch discounts.")
        return

    discounts_result = api.get_customer_discounts(
        access_token=access_token,
        customer_id=customer_id,
    )
    debug_json("Customer discounts response", discounts_result)

    if not isinstance(discounts_result, dict) and not isinstance(discounts_result, list):
        Terminal.error("Invalid discounts response.")
        return

    if isinstance(discounts_result, dict):
        status_code = discounts_result.get("status_code")
        if status_code is not None and int(status_code) >= 400:
            Terminal.error("Failed to load discounts.")
            Terminal.detail("Status code", status_code)
            if discounts_result.get("error") is not None:
                Terminal.detail("Error", discounts_result.get("error"))
            return
        if discounts_result.get("ok") is False:
            Terminal.error("Failed to load discounts.")
            Terminal.detail("Status code", discounts_result.get("status_code"))
            if discounts_result.get("error") is not None:
                Terminal.detail("Error", discounts_result.get("error"))
            return

    discount_list = extract_discount_list(discounts_result)

    Terminal.ok("Discounts loaded.")
    Terminal.detail("Discount count", len(discount_list))

    if not discount_list:
        Terminal.warn("No discounts found for this customer.")
        return

    save_discounts(phone, discount_list)
    Terminal.ok("Discounts saved to database.")

    save_discounts_json(phone, discount_list)
    Terminal.ok("Discounts saved to discounts.json")


    save_account_storage_state(
        phone=phone,
        access_token=access_token,
        operation="1",
    )

    Terminal.blank()
    Terminal.line()
    print(" Discount List")
    Terminal.line()

    for index, discount in enumerate(discount_list, start=1):
        discount_id = get_discount_id(discount)
        discount_name = get_discount_name(discount)
        discount_code = get_discount_code(discount)

        print(f"{index:02d}.")
        Terminal.detail("Discount ID", discount_id)
        Terminal.detail("Name", discount_name)
        Terminal.detail("Code", discount_code if discount_code else "-")
        Terminal.line()

def find_key_deep(data, keys):
    """
    جستجوی بازگشتی در تمام سطوح دیکشنری/لیست
    برای پیدا کردن اولین کلید از بین keys
    """
    if isinstance(data, dict):
        for key in keys:
            if key in data and data[key] not in (None, "", [], {}):
                return data[key]
        for value in data.values():
            found = find_key_deep(value, keys)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_key_deep(item, keys)
            if found not in (None, "", [], {}):
                return found
    return None


def extract_token_info(token_result):
    if not isinstance(token_result, dict):
        return None, None, None

    access = find_key_deep(token_result, ["access_token", "accessToken", "token"])
    refresh = find_key_deep(token_result, ["refresh_token", "refreshToken"])
    user_info = find_key_deep(token_result, ["UserInfo", "user_info", "user", "profile", "customer"])

    return access, refresh, user_info




def operaton(phone_number, province_name, operation, proxy_url=None, allow_otp=True):
    
    proxy_url = None
    
    Terminal.header("Okala Automation Client")

    Terminal.step_counter = 0

    phone = normalize_mobile(phone_number)
    province = province_name

    if province == "1":
        province = "اصفهان"
    if province == "2":
        province = "فارس"
    if province == "3":
        province = "تهران"
    if province == "4":
        province = "خراسان رضوی"
    if province == "5":
        province = "آذربایجان شرقی"

    if not phone:
        Terminal.error("Mobile number is required.")
        return False

    if not province:
        Terminal.error("Province name is required.")
        return False

    Terminal.blank()
    Terminal.step("Initializing application...")
    api = OkalaAPI(proxy=proxy_url)
    Terminal.ok("Application initialized.")

    # =========================
    # operation == 3 : refresh token only
    # =========================
    if operation == "3":
        Terminal.step("Refreshing token using saved refresh token...")

        account_data = get_account(phone)

        if not account_data:
            Terminal.error("No saved account found for this phone.")
            return False

        old_refresh_token = account_data.get("refresh_token")

        if not old_refresh_token:
            Terminal.error("No refresh token found for this account.")
            return False

        refresh_result = api.refresh_token(old_refresh_token)
        debug_json("Refresh token response", refresh_result)

        if not isinstance(refresh_result, dict):
            Terminal.error("Invalid refresh response.")
            return False

        new_access_token = refresh_result.get("access_token")
        new_refresh_token = refresh_result.get("refresh_token") or old_refresh_token

        if not new_access_token:
            Terminal.error("Failed to refresh access token.")
            return False

        save_account(
            phone=phone,
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            user_info=account_data.get("user_info"),
        )

        save_account_storage_state(
            phone=phone,
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            user_info=account_data.get("user_info"),
        )

        Terminal.ok("Token refreshed successfully.")
        return True

    # =========================
    # operation == 1, 2, 5 : OTP flow
    # =========================

    account_data = get_account(phone) or {}

    if not account_data:
        Terminal.warn("No saved account found, proceeding with OTP registration.")

    refresh_token_1 = account_data.get("refresh_token")
    access_token_1  = account_data.get("access_token")

    access_token = None
    refresh_token = None
    user_info = account_data.get("user_info") or None

    if not refresh_token_1 and not access_token_1:
        RESULT = {"ok": False}
    else:
        RESULT = api.login_with_token(
            refresh_token=refresh_token_1,
            access_token=access_token_1,
            device_type_code="Web",
            login_duration="30",
        )

    if RESULT.get("ok"):
        access_token = RESULT.get("access_token")
        refresh_token = RESULT.get("refresh_token") or refresh_token_1
        user_info = account_data.get("user_info")
    else:
        if not allow_otp:
            Terminal.error("No valid token and OTP not allowed.")
            return False

        Terminal.blank()
        Terminal.step("Sending OTP...")

        otp_code = None
        max_attempts = 20  # ۲۰ بار تلاش → ۲۰ * ۳ دقیقه = ۶۰ دقیقه

        for attempt in range(max_attempts):
            otp_result = api.send_otp(phone)
            debug_json("OTPRegister response", otp_result)

            if not is_success_response(otp_result):
                Terminal.error("OTP request failed.")
                if isinstance(otp_result, dict) and otp_result.get("message"):
                    Terminal.detail("Server message", otp_result.get("message"))
                return False

            Terminal.ok("OTP sent successfully.")
            Terminal.step(f"Waiting for OTP (attempt {attempt+1}) - up to 3 minutes...")

            otp_code = wait_for_otp(phone, timeout=180)

            if otp_code:
                Terminal.ok(f"OTP received: {otp_code}")
                break

            Terminal.warn("No OTP received in 3 minutes. Resending OTP...")

        if not otp_code:
            Terminal.error("OTP code is required.")
            return False

        Terminal.blank()
        Terminal.step("Verifying OTP and receiving tokens...")
        token_result = api.verify_otp_and_get_tokens(phone, otp_code)
        debug_json("Tokens response", token_result)
        Terminal.detail("Verify OTP response", json.dumps(token_result, ensure_ascii=False))
        if not isinstance(token_result, dict):
            Terminal.error("Invalid token response.")
            return False

        access_token, refresh_token, user_info = extract_token_info(token_result)

    if not access_token:
        Terminal.error("Failed to receive access token or refresh token.")
        return False

    save_account(phone, access_token, refresh_token, user_info=user_info)

    save_account_storage_state(
        phone=phone,
        access_token=access_token,
        refresh_token=refresh_token,
        user_info=user_info,
    )

    Terminal.ok("Authentication completed.")
    Terminal.ok("Account tokens saved.")
    Terminal.ok("Account storage state saved.")

    Terminal.blank()

    # =========================
    # operation == 5 : فقط ثبت‌نام و به‌روزرسانی پروفایل
    # =========================
    if operation == "5":
        Terminal.step("Updating customer profile...")
        random_name = pick_random_name("Profile_name.txt")
        if not random_name:
            Terminal.warn("Profile update skipped because no valid name was found.")
            return False
        payload = build_update_customer_payload(random_name)
        debug_json("Prepared UpdateCustomer payload", payload, sanitize=False)
        update_result = api.update_customer(access_token, payload)
        debug_json("UpdateCustomer response", update_result)
        if is_success_response(update_result):
            Terminal.ok("Profile updated.")

            # استخراج داده جدید از پاسخ
            updated_data = update_result.get("data") or {}
            if isinstance(updated_data, dict):
                # اگر user_info قبلاً None بود، یک دیکشنری خالی بساز
                if not isinstance(user_info, dict):
                    user_info = {}
                # ادغام داده جدید در user_info
                user_info.update(updated_data)
                # ذخیره مجدد با نام جدید
                save_account(phone, access_token, refresh_token, user_info=user_info)
                save_account_storage_state(
                    phone=phone,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    user_info=user_info,
                )
                Terminal.ok("Local user info updated with new name.")
        else:
            Terminal.warn("Profile update may have failed.")
        set_account_has_address(phone, 0)
        time.sleep(random.uniform(1, 3))
        return True
    # ======================    ===
    # operation == 1 : دریافت کد تخفیف
    # =========================
    if operation == "1":
        customer_id = extract_customer_id(user_info)
        if not customer_id:
            Terminal.error("Customer ID not found in user_info. Run OTP login at least once")
            return False

        find_discounts(
            api=api,
            access_token=access_token,
            customer_id=customer_id,
            phone=phone,
        )
        return True

    # =========================
    # operation == 2 : تکمیل پروفایل / افزودن آدرس / افزودن به سبد خرید
    # =========================
    Terminal.step("Updating customer profile...")
    random_name = pick_random_name("Profile_name.txt")

    if not random_name:
        Terminal.warn("Profile update skipped because no valid name was found.")
        return False

    payload = build_update_customer_payload(random_name)
    debug_json("Prepared UpdateCustomer payload", payload, sanitize=False)

    update_result = api.update_customer(access_token, payload)
    debug_json("UpdateCustomer response", update_result)

    if is_success_response(update_result):
        Terminal.ok("Profile updated.")
    else:
        Terminal.warn("Profile update may have failed.")

    Terminal.blank()
    Terminal.step("Loading customer addresses...")

    customer_id = extract_customer_id(user_info)
    addresses_result = api.get_customer_addresses(access_token, page_index=1, page_size=10)
    debug_json("GetCustomerAddresses response", addresses_result)

    address_list = extract_address_list(addresses_result)

    selected_lat = None
    selected_lng = None
    selected_address_id = None

    if address_list:
        selected_address_obj = select_best_address(address_list)
        selected_lat, selected_lng = extract_lat_lng(selected_address_obj)
        selected_address_id = extract_address_id(selected_address_obj)

        if selected_lat is None or selected_lng is None:
            Terminal.error("An address was found, but coordinates are invalid.")
            return False

        save_account(
            phone=phone,
            access_token=access_token,
            refresh_token=refresh_token,
            user_info=user_info,
            address_info=addresses_result,
            latitude=selected_lat,
            longitude=selected_lng,
            address_id=selected_address_id,
        )

        save_account_storage_state(
            phone=phone,
            access_token=access_token,
            refresh_token=refresh_token,
            user_info=user_info,
            address_info=addresses_result,
            latitude=selected_lat,
            longitude=selected_lng,
            address_id=selected_address_id,
        )

        Terminal.ok("Existing address selected.")
        Terminal.detail("Address ID", selected_address_id)
        Terminal.detail("Latitude", selected_lat)
        Terminal.detail("Longitude", selected_lng)

    else:
        Terminal.warn("No existing address found. A new address will be created.")

        if not customer_id:
            Terminal.error("Customer ID not found. Cannot create address.")
            return False

        selected_random_address = pick_random_address_for_province(province, "addresses.json")

        if not selected_random_address:
            Terminal.error("No valid random address found for the selected province.")
            return False

        debug_json("Selected random address", selected_random_address, sanitize=False)

        try:
            add_address_payload = build_add_address_payload(
                customer_id=customer_id,
                address_data=selected_random_address,
            )
        except ValueError as e:
            Terminal.error(f"Invalid add address payload: {e}")
            Terminal.detail("customer_id", customer_id)
            Terminal.detail("selected_random_address", selected_random_address)
            return False
        debug_json("AddAddress payload", add_address_payload, sanitize=False)

        add_address_result = api.add_customer_address(access_token, add_address_payload)
        debug_json("AddAddress response", add_address_result)
        time.sleep(2)
        
        if not is_success_response(add_address_result):
            Terminal.error("Add address request failed.")
            if isinstance(add_address_result, dict):
                Terminal.detail("Status code", add_address_result.get("status_code"))
                Terminal.detail("Message", add_address_result.get("message"))
                Terminal.detail("Error", add_address_result.get("error"))
            return False

        addresses_result = api.get_customer_addresses(access_token, page_index=1, page_size=10)
        debug_json("Addresses after AddAddress", addresses_result)

        address_list = extract_address_list(addresses_result)
        if not address_list:
            Terminal.error("No address returned after address creation.")
            return False

        selected_address_obj = select_best_address(address_list)
        selected_address_id = extract_address_id(selected_address_obj)
        selected_lat, selected_lng = extract_lat_lng(selected_address_obj)

        if selected_lat is None or selected_lng is None:
            Terminal.error("Created address does not contain valid coordinates.")
            return False

        save_account(
            phone=phone,
            access_token=access_token,
            refresh_token=refresh_token,
            user_info=user_info,
            address_info=addresses_result,
            latitude=selected_lat,
            longitude=selected_lng,
            address_id=selected_address_id,
        )

        save_account_storage_state(
            phone=phone,
            access_token=access_token,
            refresh_token=refresh_token,
            user_info=user_info,
            address_info=addresses_result,
            latitude=selected_lat,
            longitude=selected_lng,
            address_id=selected_address_id,
        )

        Terminal.ok("New address created and selected.")
        Terminal.detail("Address ID", selected_address_id)
        Terminal.detail("Latitude", selected_lat)
        Terminal.detail("Longitude", selected_lng)

    if selected_lat is None or selected_lng is None:
        Terminal.error("Valid coordinates were not found. Store lookup skipped.")
        return False

    Terminal.blank()
    Terminal.step("Loading available stores...")
    stores_result = api.get_all_stores(access_token, selected_lat, selected_lng)
    
    print("VAL : \n", stores_result, "\n ------------------------------------------------------------------------------------------------------")
    print("TYPE : \n", type(stores_result), "\n ------------------------------------------------------------------------------------------------------")

    debug_json("GetAllStores response", stores_result)

    store_list = extract_store_list(stores_result)
    selected_store_id = None
    cart_results = []
    product_list = []

    if not store_list:
        Terminal.error("No stores were returned for the selected coordinates.")
        Terminal.info("The location may be خارج از service area or the endpoint may require more context.")
        return False

    eligible_store_count = count_eligible_stores(store_list)
    Terminal.ok("Stores loaded.")
    Terminal.detail("Total stores", len(store_list))
    Terminal.detail("Eligible stores", eligible_store_count)

    Terminal.blank()
    Terminal.step("Selecting supermarket store...")
    selected_store_obj = select_random_store(store_list)

    if not selected_store_obj:
        Terminal.error("No eligible supermarket store was found.")
        return False

    selected_store_id = extract_store_id(selected_store_obj)
    store_name = get_store_name(selected_store_obj)

    Terminal.ok("Store selected.")
    Terminal.detail("Store ID", selected_store_id)
    Terminal.detail("Store Name", store_name)

    Terminal.blank()
    Terminal.step("Loading products...")

    products_result = api.get_products_by_store(
        access_token=access_token,
        store_id=selected_store_id,
    )

    debug_json("Products response", products_result)

    if not isinstance(products_result, dict) or not products_result.get("ok", False):
        Terminal.error("Failed to load store products.")
        if isinstance(products_result, dict):
            Terminal.detail("Status code", products_result.get("status_code"))
            Terminal.detail("Error", products_result.get("error"))
        return False

    product_list = extract_product_list(products_result)
    Terminal.ok("Products loaded.")
    Terminal.detail("Products found", len(product_list))

    Terminal.blank()
    Terminal.step("Adding products to cart...")

    if product_list:
        cart_results = add_random_items_to_cart(
            api=api,
            access_token=access_token,
            store_id=selected_store_id,
            product_list=product_list,
            count=3,
        )
        debug_json("Add to cart results", cart_results)
    else:
        Terminal.warn("No products found for the selected store.")

    save_account(
        phone=phone,
        access_token=access_token,
        refresh_token=refresh_token,
        user_info=user_info,
        address_info=addresses_result,
        store_info=stores_result,
        latitude=selected_lat,
        longitude=selected_lng,
        address_id=selected_address_id,
        store_id=selected_store_id,
    )

    save_account_storage_state(
        phone=phone,
        access_token=access_token,
        refresh_token=refresh_token,
        user_info=user_info,
        address_info=addresses_result,
        store_info=stores_result,
        latitude=selected_lat,
        longitude=selected_lng,
        address_id=selected_address_id,
        store_id=selected_store_id,
        cart_results=cart_results,
    )

    # ثبت وضعیت دارای آدرس
    set_account_has_address(phone, 1)

    added_count = 0
    for item in cart_results:
        result = item.get("result", {})
        if isinstance(result, dict) and result.get("ok") and result.get("success", True):
            added_count += 1

    Terminal.blank()
    Terminal.line()
    print(" Final Summary")
    Terminal.line()
    Terminal.detail("Status", "SUCCESS")
    Terminal.detail("Mobile", mask_phone(phone))
    Terminal.detail("Address ID", selected_address_id)
    Terminal.detail("Store ID", selected_store_id)
    Terminal.detail("Products Added", added_count)
    Terminal.line()
    time.sleep(random.uniform(1, 3))
    return True

if __name__ == "__main__":
    Terminal.step("Initializing database...")
    init_db()
    Terminal.ok("Database initialized.")

    phone_list = ["09335132745"] 
    if isinstance(phone_list, str):
        phone_list = [phone_list]

    if not phone_list:
        Terminal.error("No phone numbers were returned.")
        exit(0)

    province = input(
        "Enter province name (1.Esfahan / 2.Fars / 3.Tehran / 4.Khorasan Razavi / 5.East Azerbaijan - Persian names supported): "
    ).strip()

    choose_operation = input(
        "Enter the number of the operation, "
        "1-find discount codes, "
        "2-complete profile / add to cart, "
        "3-refresh all users tokens: ,"
        "4-get discounts,"
    ).strip()

    if choose_operation not in ["1", "2", "3", "4", "5"]:
        print("Invalid entry, pick between 1, 2, 3, 4 or 5 for the operation.")
        exit(0)

    if choose_operation == "4":
        number = input("How many Codes do You want?")
        extract_and_delete_discounts(number)
        print("Check extracted_discounts.json")
        exit()

    results = []
    for i, phone in enumerate(phone_list):
        Terminal.blank()
        Terminal.detail(f"Processing phone {i+1}/{len(phone_list)}", mask_phone(phone))

        if i > 0:
            delay = random.uniform(1, 2)
            Terminal.info(f"Waiting {delay:.1f} seconds before next phone...")
            time.sleep(delay)

        try:
            result = operaton(
                phone_number=phone,
                province_name=province,
                operation=choose_operation,
                proxy_url=None  
            )
            results.append({
                "phone": phone,
                "success": bool(result),
                "error": None if result else "Operation failed"
            })
        except Exception as e:
            Terminal.error(f"An error occurred for phone {mask_phone(phone)}: {e}")
            results.append({"phone": phone, "success": False, "error": str(e)})

    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count

    Terminal.line()
    print(" Batch Final Summary")
    Terminal.line()
    Terminal.detail("Total", len(results))
    Terminal.detail("Success", success_count)
    Terminal.detail("Failed", fail_count)
    Terminal.line()
    Terminal.ok("All operations completed.")