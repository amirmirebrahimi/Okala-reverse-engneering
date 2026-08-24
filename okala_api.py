import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import uuid
import random
import time


class OkalaAPI:
    OTP_REGISTER_URL = "https://apigateway.okala.com/api/voyager/C/CustomerAccount/OTPRegister"
    TOKENS_URL = "https://apigateway.okala.com/api/v1/accounts/tokens"
    UPDATE_CUSTOMER_URL = "https://apigateway.okala.com/api/voyager/C/CustomerAccount/UpdateCustomer"
    GET_CUSTOMER_ADDRESSES_URL = "https://apigateway.okala.com/api/v1/accounts/userprofile/getcustomeraddresseswithpaging"
    ADD_CUSTOMER_ADDRESS_URL = "https://apigateway.okala.com/api/voyager/C/CustomerAccount/AddAddress/"
    GET_ALL_STORES_URL = "https://apigateway.okala.com/api/opex/v4/stores/nearby"
    GET_PRODUCTS_BY_STORE_URL = "https://apigateway.okala.com/api/Unicorn/v1/Product/GetCarouselByStoreId"
    ADD_TO_SHOPPING_CART_URL = "https://apigateway.okala.com/api/Basket/v2/ShoppingCart/AddToShoppingCart"
    GET_CUSTOMER_DISCOUNTS_URL_TEMPLATE = "https://apigateway.okala.com/api/discount/v1/discounts/customer/{customer_id}"

    CLIENT_ID = "customer_client_id"
    CLIENT_SECRET = "u_M{'57j!%LI21#"
    GRANT_TYPE = "customer_grant_type"
    SCOPE = "offline_access email openid phone profile"

    # پروفایل‌های مرورگر برای تغییر User-Agent و هدرهای مرتبط
    BROWSER_PROFILES = [
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="120", "Chromium";v="120"',
            "sec-ch-ua-platform": '"Windows"',
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
        },
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="119", "Chromium";v="119"',
            "sec-ch-ua-platform": '"macOS"',
            "Accept-Language": "en-US,en;q=0.9",
        },
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
            "sec-ch-ua": '"Not=A?Brand";v="99", "Firefox";v="121", "Gecko";v="121"',
            "sec-ch-ua-platform": '"Windows"',
            "Accept-Language": "fa-IR,fa;q=0.9",
        },
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
            "sec-ch-ua": '"Not=A?Brand";v="99", "Safari";v="17.1", "WebKit";v="605.1.15"',
            "sec-ch-ua-platform": '"macOS"',
            "Accept-Language": "fa-IR,fa;q=0.9",
        },
    ]

    def __init__(self, proxy=None, min_delay=0.3, max_delay=0.1):
        self.min_delay = min_delay
        self.max_delay = max_delay

        self.session = requests.Session()
        # هدرهای ثابت در همه‌ی درخواست‌ها
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Connection": "keep-alive",
            "Origin": "https://www.okala.com",
            "Referer": "https://www.okala.com/",
            "sec-ch-ua-mobile": "?0",
            "source": "okala",
            "ui-version": "2.0",
            "x-skip-authorization": "false",
        })

        # انتخاب یک پروفایل تصادفی برای این نمونه
        self.browser_profile = random.choice(self.BROWSER_PROFILES)
        self._apply_browser_profile()

        retry = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )

        adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.proxy = proxy
        if proxy:
            self.session.proxies.update({
                "http": proxy,
                "https": proxy,
            })

    def _apply_browser_profile(self):
        """اعمال پروفایل مرورگر روی هدرهای سشن"""
        for key, value in self.browser_profile.items():
            self.session.headers[key] = value

    def _update_dynamic_headers(self):
        """به‌روزرسانی هدرهای پویا (شناسه‌های یکتا) برای هر درخواست"""
        self.session.headers.update({
            "x-user-unique-id": str(uuid.uuid4()),
            "session-id": str(uuid.uuid4()),
            "x-correlation-id": str(uuid.uuid4()),
            "advertising_id": "null",
            "idfa": "null",
            "metrix_user_id": "null",
        })

    def _random_delay(self):
        """تأخیر تصادفی برای شبیه‌سازی رفتار انسانی"""
        delay = random.uniform(self.min_delay, self.max_delay)
        time.sleep(delay)

    def _build_auth_headers(self, access_token: str):
        """ساخت هدرهای احراز هویت با هدرهای پویا"""
        self._update_dynamic_headers()
        headers = self.session.headers.copy()
        headers.update({
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        })
        return headers

    def _build_headers_no_auth(self):
        """ساخت هدرها برای درخواست‌های بدون توکن"""
        self._update_dynamic_headers()
        return self.session.headers.copy()

    # ---------- متدهای عمومی ----------

    def send_otp(self, mobile_number: str):
        self._random_delay()
        payload = {"Mobile": mobile_number}
        headers = self._build_headers_no_auth()
        headers["Content-Type"] = "application/json"
        response = self.session.post(
            self.OTP_REGISTER_URL,
            json=payload,
            headers=headers,
            timeout=(3, 8)
        )
        return self._handle_response(response)

    def verify_otp_and_get_tokens(
        self,
        mobile_number: str,
        otp_code: str,
        device_type_code: str = "Web",
        login_duration: str = "30"
    ):
        self._random_delay()
        payload = {
            "mobile_number": mobile_number,
            "otp_code": otp_code,
            "grant_type": self.GRANT_TYPE,
            "client_id": self.CLIENT_ID,
            "client_secret": self.CLIENT_SECRET,
            "scope": self.SCOPE,
            "device_type_code": device_type_code,
            "loginDuration": login_duration
        }

        headers = self._build_headers_no_auth()
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        response = self.session.post(
            self.TOKENS_URL,
            data=payload,
            headers=headers,
            timeout=(5, 12)
        )
        return self._handle_response(response)

    def refresh_token(self, refresh_token: str, device_type_code: str = "Web", login_duration: str = "30"):
        self._random_delay()
        payload = {
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "client_id": self.CLIENT_ID,
            "client_secret": self.CLIENT_SECRET,
            "scope": self.SCOPE,
            "device_type_code": device_type_code,
            "loginDuration": login_duration,
        }

        headers = self._build_headers_no_auth()
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        response = self.session.post(
            self.TOKENS_URL,
            data=payload,
            headers=headers,
            timeout=(5, 12)
        )
        return self._handle_response(response)

    def update_customer(self, access_token: str, payload: dict):
        self._random_delay()
        response = self.session.post(
            self.UPDATE_CUSTOMER_URL,
            headers=self._build_auth_headers(access_token),
            json=payload,
            timeout=(5, 15)
        )
        return self._handle_response(response)

    def get_customer_addresses(self, access_token: str, page_index: int = 1, page_size: int = 10):
        self._random_delay()
        response = self.session.get(
            self.GET_CUSTOMER_ADDRESSES_URL,
            headers=self._build_auth_headers(access_token),
            params={"pageIndex": page_index, "pageSize": page_size},
            timeout=(5, 15)
        )
        return self._handle_response(response)

    def add_customer_address(self, access_token: str, payload: dict):
        self._random_delay()
        response = self.session.post(
            self.ADD_CUSTOMER_ADDRESS_URL,
            headers=self._build_auth_headers(access_token),
            json=payload,
            timeout=(5, 15)
        )
        return self._handle_response(response)

    def get_all_stores(self, access_token: str, latitude: float, longitude: float):
        self._random_delay()
        headers = self._build_auth_headers(access_token)
        headers.update({
            "source": "okala",
            "ui-version": "2.0",
            "x-skip-authorization": "false",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.okala.com/",
        })
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "customerSegments": "Buy_Again_Store_Filter",
        }
        response = self.session.get(
            self.GET_ALL_STORES_URL,
            headers=headers,
            params=params,
            timeout=(5, 15)
        )
        return self._handle_response(response)

    def get_products_by_store(self, access_token: str, store_id, page: int = 1, page_size: int = 12, carousel_type: int = 0):
        self._random_delay()
        response = self.session.get(
            self.GET_PRODUCTS_BY_STORE_URL,
            headers=self._build_auth_headers(access_token),
            params={
                "StoreId": store_id,
                "CarouselType": carousel_type,
                "Take": page_size,
                "Page": page,
            },
            timeout=(5, 15)
        )
        return self._handle_response(response)

    def add_to_shopping_cart(
        self,
        access_token: str,
        store_id,
        product_id,
        quantity: int = 1,
        product_store_id: str = "0",
        sector_id: str = "0",
        sector_part_id: str = "0",
    ):
        self._random_delay()
        payload = {
            "deliveryMethod": "Delivery",
            "isMultiStore": True,
            "isSupplier": False,
            "productId": int(product_id),
            "productStoreId": str(product_store_id),
            "quantity": int(quantity),
            "replaceItemMethodCode": -1,
            "sectorId": str(sector_id),
            "sectorPartId": str(sector_part_id),
            "storeId": int(store_id),
        }

        response = self.session.post(
            self.ADD_TO_SHOPPING_CART_URL,
            headers=self._build_auth_headers(access_token),
            json=payload,
            timeout=(5, 15)
        )

        result = self._handle_response(response)
        if isinstance(result, dict):
            result["payload"] = payload
        return result

    def get_customer_discounts(self, access_token: str, customer_id):
        self._random_delay()
        url = self.GET_CUSTOMER_DISCOUNTS_URL_TEMPLATE.format(customer_id=customer_id)
        response = self.session.get(
            url,
            headers=self._build_auth_headers(access_token),
            timeout=(5, 15)
        )
        return self._handle_response(response)

    @staticmethod
    def _handle_response(response: requests.Response):
        try:
            data = response.json()
        except Exception:
            return {
                "status_code": response.status_code,
                "ok": response.ok,
                "raw_text": response.text
            }

        if not response.ok:
            return {
                "status_code": response.status_code,
                "ok": False,
                "error": data
            }

        if isinstance(data, dict):
            data.setdefault("status_code", response.status_code)
            data.setdefault("ok", True)

        return data

    # ---------- متد login_with_token (بدون تغییر) ----------
    def login_with_token(
        self,
        access_token: str | None = None,
        refresh_token: str | None = None,
        device_type_code: str = "Web",
        login_duration: str = "30",
        validate_with_profile: bool = True,
        validation_page_index: int = 1,
        validation_page_size: int = 1,
    ):
        if not access_token and not refresh_token:
            return {
                "ok": False,
                "status_code": 400,
                "error": "either access_token or refresh_token must be provided"
            }

        if refresh_token:
            refreshed = self.refresh_token(
                refresh_token=refresh_token,
                device_type_code=device_type_code,
                login_duration=login_duration,
            )

            if not isinstance(refreshed, dict) or not refreshed.get("ok", False):
                return {
                    "ok": False,
                    "status_code": refreshed.get("status_code", 0) if isinstance(refreshed, dict) else 0,
                    "error": refreshed,
                }

            new_access_token = refreshed.get("access_token")
            new_refresh_token = refreshed.get("refresh_token", refresh_token)

            if not new_access_token:
                return {
                    "ok": False,
                    "status_code": refreshed.get("status_code", 0),
                    "error": "no access_token returned from refresh_token endpoint",
                    "raw": refreshed,
                }

            return {
                "ok": True,
                "status_code": refreshed.get("status_code", 200),
                "access_token": new_access_token,
                "refresh_token": new_refresh_token,
                "raw": refreshed,
            }

        if access_token and not refresh_token:
            if not validate_with_profile:
                return {
                    "ok": True,
                    "status_code": 200,
                    "access_token": access_token,
                    "refresh_token": None,
                    "raw": {"message": "access_token accepted without remote validation"},
                }

            test_resp = self.get_customer_addresses(
                access_token=access_token,
                page_index=validation_page_index,
                page_size=validation_page_size,
            )

            if not isinstance(test_resp, dict) or not test_resp.get("ok", False):
                return {
                    "ok": False,
                    "status_code": test_resp.get("status_code", 0) if isinstance(test_resp, dict) else 0,
                    "error": "access_token seems invalid or expired",
                    "raw": test_resp,
                }

            return {
                "ok": True,
                "status_code": test_resp.get("status_code", 200),
                "access_token": access_token,
                "refresh_token": None,
                "raw": test_resp,
            }