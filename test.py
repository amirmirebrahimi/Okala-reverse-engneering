import requests

proxies_list = [
    "http://bepinufz:zwdy9b72ct00@198.105.121.200:6462",
    "http://bepinufz:zwdy9b72ct00@64.137.96.74:6641",
    "http://bepinufz:zwdy9b72ct00@38.154.185.97:6370",
    "http://bepinufz:zwdy9b72ct00@84.247.60.125:6095",
    "http://bepinufz:zwdy9b72ct00@142.111.67.146:5611",
]

for proxy in proxies_list:
    try:
        r = requests.get("https://ipv4.webshare.io/", proxies={"http": proxy, "https": proxy}, timeout=8)
        if r.status_code == 200:
            print(f"✅ {proxy} -> {r.text.strip()}")
        else:
            print(f"⚠️ {proxy} -> status {r.status_code}")
    except Exception as e:
        print(f"❌ {proxy} -> {e}")