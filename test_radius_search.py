import re
import urllib.request
from html import unescape

URLS = [
    "https://jmty.jp/s/area_portal/1005342?distance=30",
    "https://jmty.jp/s/area_portal/1005342?distance=50",
    "https://jmty.jp/aichi/sale-fur?distance=30",
    "https://jmty.jp/aichi/sale-fur?distance=50",
]

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"

for url in URLS:
    print("=" * 80)
    print("FETCH:", url)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", errors="replace")
        print("HTTP:", r.status)
        print("FINAL URL:", r.geturl())
        print("BYTES:", len(html))
        print("SET-COOKIE:", r.headers.get("Set-Cookie", ""))

    articles = re.findall(r"/aichi/sale-fur/article-[a-z0-9]+", html)
    articles = list(dict.fromkeys(articles))
    print("ARTICLE LINKS:", len(articles))
    print("SAMPLE LINKS:")
    for x in articles[:10]:
        print(" ", x)

    cities = sorted(set(re.findall(r"(?:愛知県|岐阜県|三重県|静岡県|長野県|滋賀県|奈良県|福井県|石川県)[^<]{0,30}", html)))
    print("REGION TEXT SAMPLES:")
    for x in cities[:20]:
        print(" ", unescape(x).strip())
