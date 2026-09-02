import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

TERM = os.environ.get("JIMOTY_SEARCH_TERM", "IKEA")
BASE = "https://jmty.jp/aichi/sale-fur-kw-"
OUT = Path("jimoty_live_snapshot.json")
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile Safari/604.1"


def fetch():
    url = BASE + urllib.parse.quote(TERM, safe="")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja,en-US;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", errors="ignore")
    matches = re.finditer(r'<a[^>]+href=["\']([^"\']*article-[^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S)
    seen = set()
    items = []
    for m in matches:
        href = m.group(1)
        url = href if href.startswith("http") else "https://jmty.jp" + href
        url = url.split("#", 1)[0]
        if url in seen:
            continue
        seen.add(url)
        title = re.sub(r"<[^>]+>", " ", m.group(2) or "")
        title = re.sub(r"\s+", " ", title).strip()
        if title:
            items.append({"title": title[:200], "url": url})
        if len(items) >= 50:
            break
    return items

items = fetch()
previous = {}
if OUT.exists():
    try:
        previous = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        previous = {}
old_urls = set(previous.get("urls", []))
new_items = [x for x in items if x["url"] not in old_urls]

payload = {"search_term": TERM, "urls": [x["url"] for x in items], "items": items, "new_items": new_items}
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Search: {TERM}")
print(f"Parsed: {len(items)}")
print(f"New since previous live check: {len(new_items)}")
for x in new_items[:5]:
    print(f"NEW: {x['title']} | {x['url']}")
