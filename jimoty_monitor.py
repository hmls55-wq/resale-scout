import html as html_lib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
STATE_PATH = Path(os.environ.get("JIMOTY_STATE_PATH", "jimoty_db.json"))
RULES_PATH = Path(os.environ.get("JIMOTY_RULES_PATH", "notification_rules.json"))
RESULT_PATH = Path(os.environ.get("JIMOTY_RESULT_PATH", "jimoty_monitor_result.json"))
DISCORD_RETRIES = 4
MAX_PAGES = int(os.environ.get("JIMOTY_MAX_PAGES", "1"))
MAX_ITEMS_PER_PAGE = 50
DETAIL_FETCH_LIMIT = int(os.environ.get("JIMOTY_DETAIL_FETCH_LIMIT", "50"))
DETAIL_FETCH_WORKERS = int(os.environ.get("JIMOTY_DETAIL_FETCH_WORKERS", "50"))
BASE_URL = os.environ.get("JIMOTY_BASE_URL", "https://jmty.jp/aichi/sale")
CENTER_LAT = os.environ.get("JIMOTY_CENTER_LAT", "35.1681")
CENTER_LNG = os.environ.get("JIMOTY_CENTER_LNG", "136.8734")
DISTANCE_KM = os.environ.get("JIMOTY_DISTANCE_KM", "50")
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile Safari/604.1"


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Referer": "https://jmty.jp/",
    })
    with urllib.request.urlopen(req, timeout=6) as r:
        body = r.read().decode("utf-8", errors="ignore")
        print(f"HTTP {r.status}, HTML {len(body):,} bytes")
        if len(body) < 5_000:
            raise RuntimeError(f"HTMLが短すぎます: {len(body)} bytes")
        return body


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize(text):
    text = html_lib.unescape(text or "").lower()
    text = text.replace("　", " ")
    return re.sub(r"\s+", " ", text).strip()


def extract_price(text):
    text = text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    for pattern in [r"([0-9][0-9,]*)\s*円", r"(?:¥|￥)\s*([0-9][0-9,]*)"]:
        m = re.search(pattern, text)
        if m:
            return int(m.group(1).replace(",", ""))
    if "無料" in text:
        return 0
    return None


def extract_items(page_html):
    matches = list(re.finditer(
        r'<a[^>]+href=["\']([^"\']*article-[^"\']+)["\'][^>]*>(.*?)</a>',
        page_html, re.I | re.S
    ))
    seen = set()
    items = []
    for m in matches:
        href = m.group(1)
        url = href if href.startswith("http") else "https://jmty.jp" + href
        url = url.split("#", 1)[0]
        if url in seen:
            continue
        seen.add(url)
        start = max(0, m.start() - 3000)
        end = min(len(page_html), m.start() + 15000)
        card_text = clean(page_html[start:end])
        title = clean(m.group(2))
        title = re.sub(r"お気に入り.*$", "", title).strip()
        price = extract_price(card_text)
        if not title:
            continue
        items.append({
            "title": title[:200],
            "price": price,
            "url": url,
            "description": card_text[:8000],
        })
        if len(items) >= MAX_ITEMS_PER_PAGE:
            break
    return items


def page_url(page):
    params = {"distance": DISTANCE_KM, "lat": CENTER_LAT, "lng": CENTER_LNG}
    if page > 1:
        params["page"] = str(page)
    return BASE_URL + "?" + urllib.parse.urlencode(params)


def load_state():
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def save_state(data):
    data["updated_at"] = datetime.now(JST).isoformat()
    STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_rules():
    data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return data.get("rules", [])


def keyword_match(text, keyword):
    haystack = normalize(text)
    needle = normalize(keyword)
    if not needle:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9 .&'’+\-]*", needle):
        pattern = r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])"
        return re.search(pattern, haystack) is not None
    return needle in haystack


def match_rules(item, rules):
    text = f"{item.get('title', '')}\n{item.get('description', '')}"
    matches = []
    for rule in rules:
        if rule.get("enabled", True) is False:
            continue
        for keyword in rule.get("keywords", []):
            if keyword_match(text, keyword):
                matches.append({"name": rule.get("name", keyword), "keyword": keyword})
                break
    return matches


def fetch_detail(item):
    try:
        page = fetch(item["url"])
        descriptions = []
        patterns = [
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:description["\']',
            r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
        ]
        for pat in patterns:
            descriptions.extend(clean(x) for x in re.findall(pat, page, re.I | re.S))
        if descriptions:
            item["description"] = max(descriptions, key=len)[:12000]
        else:
            item["description"] = clean(page)[:12000]
        item["price"] = item.get("price") if item.get("price") is not None else extract_price(item["description"])
    except Exception as e:
        print(f"Detail fetch failed: {item['url']} :: {e}")
    return item


def post_discord(webhook, item, matches):
    matched = ", ".join(m["name"] for m in matches)
    desc = item.get("description", "")
    if len(desc) > 900:
        desc = desc[:900] + "…"
    price_line = f"価格：{item.get('price'):,}円" if isinstance(item.get("price"), int) else "価格：不明"
    payload = {
        "content": "🚨 ジモティー新着・通知条件一致",
        "embeds": [{
            "title": item["title"],
            "url": item["url"],
            "description": f"通知条件：{matched}\n{price_line}\n\n商品説明：\n{desc}\n\nResell Scout / Jimoty"
        }],
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(1, DISCORD_RETRIES + 1):
        try:
            req = urllib.request.Request(webhook, data=data, headers={
                "Content-Type": "application/json",
                "User-Agent": "ResellScout/2.0",
            }, method="POST")
            with urllib.request.urlopen(req, timeout=6) as r:
                print(f"Discord HTTP {r.status}")
                if r.status in (200, 204):
                    return
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = max(float(e.headers.get("Retry-After", "2")), 2.0)
                print(f"Discord 429; wait {wait}s")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("Discord送信失敗")


def main():
    now = datetime.now(JST)
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        raise RuntimeError("DISCORD_WEBHOOK_URL secret が設定されていません")
    rules = load_rules()
    state = load_state()
    seen = set(state.get("seen_urls", []))
    initialized = bool(state.get("initialized"))

    all_items = []
    page_seen_urls = set()
    for page in range(1, MAX_PAGES + 1):
        url = page_url(page)
        print(f"===== collect page {page}/{MAX_PAGES}: {url} =====")
        html = fetch(url)
        items = extract_items(html)
        print(f"Parsed page {page}: {len(items)}")
        if not items:
            break
        page_new = 0
        for item in items:
            if item["url"] in page_seen_urls:
                continue
            page_seen_urls.add(item["url"])
            all_items.append(item)
            if item["url"] not in seen:
                page_new += 1
        print(f"Page {page}: unseen={page_new}")
        if len(items) < MAX_ITEMS_PER_PAGE:
            break

    if not initialized:
        state["seen_urls"] = list(page_seen_urls)[-20000:]
        state["items"] = {item["url"]: item for item in all_items[-20000:]}
        state["initialized"] = True
        state["last_checked_at"] = now.isoformat()
        state["last_new_count"] = 0
        save_state(state)
        print(f"Database initialized with {len(page_seen_urls)} URLs; no notifications.")
        RESULT_PATH.write_text(json.dumps({"checked_at": now.isoformat(), "initialized": True, "collected": len(all_items), "new": 0, "notified": 0}, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    new_items = [item for item in all_items if item["url"] not in seen]
    print(f"Total collected: {len(all_items)}, truly new: {len(new_items)}")

    notified = []
    db_items = state.get("items", {})
    detail_items = new_items[:DETAIL_FETCH_LIMIT]

    if detail_items:
        workers = max(1, min(DETAIL_FETCH_WORKERS, len(detail_items)))
        print(f"Fetching {len(detail_items)} detail pages with {workers} workers")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            detailed_items = list(executor.map(fetch_detail, detail_items))
    else:
        detailed_items = []

    for item in detailed_items:
        matches = match_rules(item, rules)
        print(f"MATCH CHECK: title={item['title']!r} matches={[m['keyword'] for m in matches]}")
        db_items[item["url"]] = item
        if not matches:
            continue
        post_discord(webhook, item, matches)
        notified.append({"url": item["url"], "title": item["title"], "matches": matches})

    for item in new_items[DETAIL_FETCH_LIMIT:]:
        db_items[item["url"]] = item

    seen.update(item["url"] for item in new_items)
    state["seen_urls"] = list(seen)[-20000:]
    state["items"] = dict(list(db_items.items())[-20000:])
    state["last_checked_at"] = now.isoformat()
    state["last_new_count"] = len(new_items)
    state["last_notified_count"] = len(notified)
    save_state(state)

    RESULT_PATH.write_text(json.dumps({
        "checked_at": now.isoformat(),
        "initialized": True,
        "collected": len(all_items),
        "new": len(new_items),
        "notified": len(notified),
        "notifications": notified,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Done. New={len(new_items)}, notified={len(notified)}")


if __name__ == "__main__":
    main()
