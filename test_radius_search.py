import re
import urllib.request
from html import unescape

URLS = [
    "https://jmty.jp/s/area_portal/1005342?distance=30",
    "https://jmty.jp/s/area_portal/1005342?distance=50",
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
    for x in articles[:10]:
        print(" ", x)

    print("INTERESTING HREFS:")
    hrefs = re.findall(r'href=[\"\']([^\"\']+)', html)
    seen = set()
    for href in hrefs:
        if any(k in href for k in ("category", "sale-fur", "distance", "area_portal")) and href not in seen:
            seen.add(href)
            print(" ", unescape(href)[:300])
            if len(seen) >= 40:
                break
