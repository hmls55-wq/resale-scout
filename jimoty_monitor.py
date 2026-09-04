import html as html_lib
import json
import os
import re
import subprocess
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
MAX_PAGES = int(os.environ.get("JIMOTY_MAX_PAGES", "2"))
MAX_ITEMS_PER_PAGE = 50
DETAIL_FETCH_LIMIT = int(os.environ.get("JIMOTY_DETAIL_FETCH_LIMIT", "60"))
DETAIL_FETCH_WORKERS = int(os.environ.get("JIMOTY_DETAIL_FETCH_WORKERS", "10"))
HTTP_TIMEOUT = int(os.environ.get("JIMOTY_HTTP_TIMEOUT", "15"))
BASE_URL = os.environ.get("JIMOTY_BASE_URL", "https://jmty.jp/aichi/sale")
BASE_URLS = [u.strip().rstrip("/") for u in os.environ.get("JIMOTY_BASE_URLS", BASE_URL).split(",") if u.strip()]
CENTER_LAT = os.environ.get("JIMOTY_CENTER_LAT", "35.1681")
CENTER_LNG = os.environ.get("JIMOTY_CENTER_LNG", "136.8734")
DISTANCE_KM = os.environ.get("JIMOTY_DISTANCE_KM", "50")
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile Safari/604.1"


def fetch(url):
    started = time.monotonic()
    try:
        cmd = [
            "curl", "-fsSL", "--max-time", str(HTTP_TIMEOUT),
            "-A", UA,
            "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "-H", "Accept-Language: ja,en-US;q=0.9,en;q=0.8",
            "-H", "Cache-Control: no-cache",
            "-H", "Referer: https://jmty.jp/",
            "-H", "Connection: close",
            url,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=HTTP_TIMEOUT + 2)
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="ignore").strip()
            raise RuntimeError(detail or f"curl exit {result.returncode}")
        body = result.stdout.decode("utf-8", errors="ignore")
        elapsed = time.monotonic() - started
        print(f"HTTP 200, HTML {len(body):,} bytes, {elapsed:.2f}s")
        if len(body) < 5_000:
            raise RuntimeError(f"HTMLが短すぎます: {len(body)} bytes")
        return body
    except Exception as e:
        print(f"HTTP failed after {time.monotonic() - started:.2f}s: {url} :: {e}")
        raise


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


def extract_detail_price(page_html):
    patterns = [
        r"商品価格\s*(?:\||｜|:|：)?\s*([0-9][0-9,]*)\s*円",
        r'<[^>]+itemprop=["\']price["\'][^>]+content=["\']([0-9][0-9,]*)["\']',
        r'<[^>]+content=["\']([0-9][0-9,]*)["\'][^>]+itemprop=["\']price["\']',
        r'<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\']([0-9][0-9,]*)["\']',
        r'<meta[^>]+content=["\']([0-9][0-9,]*)["\'][^>]+property=["\']product:price:amount["\']',
        r'"price"\s*:\s*"?([0-9][0-9,]*)"?',
    ]
    for pattern in patterns:
        m = re.search(pattern, page_html, re.I | re.S)
        if m:
            return int(m.group(1).replace(",", ""))
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
        items.append({"title": title[:200], "price": price, "url": url, "description": card_text[:8000]})
        if len(items) >= MAX_ITEMS_PER_PAGE:
            break
    return items


def page_url(base_url, page):
    params = {"distance": DISTANCE_KM, "lat": CENTER_LAT, "lng": CENTER_LNG}
    if page > 1:
        params["page"] = str(page)
    return base_url + "?" + urllib.parse.urlencode(params)


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
    rules = data.get("rules", [])
    rules = [{"name": "ITOKI", "keywords": ["ITOKI", "イトーキ", "ITOKI家具", "イトーキ家具"]}] + rules
    return rules


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
        detail_price = extract_detail_price(page)
        if detail_price is not None:
            item["price"] = detail_price
            print(f"DETAIL PRICE: {detail_price:,}円 for {item['url']}")

        descriptions = []
        patterns = [
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
            r'<meta[^>]+content=["\'](.*?)["\']\s+property=["\']og:description["\']',
            r'<meta[^>]+content=["\'](.*?)["\']\s+name=["\']description["\']',
        ]
        for pat in patterns:
            descriptions.extend(clean(x) for x in re.findall(pat, page, re.I | re.S))
        item["description"] = (max(descriptions, key=len) if descriptions else clean(page))[:12000]
        if item.get("price") is None:
            item["price"] = extract_price(item["description"])
        item["detail_ok"] = True
    except Exception as e:
        print(f"Detail fetch failed: {item['url']} :: {e}")
        item["detail_ok"] = False
    return item


def post_discord(webhook, item, matches):
    matched = ", ".join(m["name"] for m in matches)
    desc = item.get("description", "")
    if len(desc) > 900:
        desc = desc[:900] + "…"
    price_line = f"価格：{item.get('price'):,}円" if isinstance(item.get("price"), int) else "価格：不明"
    payload = {"content": "🚨 ジモティー新着・通知条件一致", "embeds": [{"title": item["title"], "url": item["url"], "description": f"通知条件：{matched}\n{price_line}\n\n商品説明：\n{desc}\n\nResell Scout / Jimoty"}]}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(1, DISCORD_RETRIES + 1):
        try:
            req = urllib.request.Request(webhook, data=data, headers={"Content-Type": "application/json", "User-Agent": "ResellScout/2.0"}, method="POST")
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
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
    overall_started = time.monotonic()
    now = datetime.now(JST)
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        raise RuntimeError("DISCORD_WEBHOOK_URL secret が設定されていません")
    rules = load_rules()
    state = load_state()
    seen = set(state.get("seen_urls", []))
    initialized = bool(state.get("initialized"))
    db_items = state.get("items", {})
    pending = state.get("pending_items", {})
    if not isinstance(pending, dict):
        pending = {}
    pending_before = set(pending)
    fresh_new_urls = []

    all_items = []
    page_seen_urls = set()
    for base_url in BASE_URLS:
        for page in range(1, MAX_PAGES + 1):
            url = page_url(base_url, page)
            print(f"===== collect {base_url} page {page}/{MAX_PAGES}: {url} =====")
            started = time.monotonic()
            html = fetch(url)
            print(f"LIST FETCH SECONDS: {time.monotonic() - started:.2f}")
            items = extract_items(html)
            print(f"Parsed {base_url} page {page}: {len(items)}")
            if not items:
                break
            page_new = 0
            for item in items:
                item_url = item["url"]
                if item_url in page_seen_urls:
                    continue
                page_seen_urls.add(item_url)
                all_items.append(item)
                if item_url not in seen and item_url not in pending:
                    page_new += 1
                    pending[item_url] = item
                    fresh_new_urls.append(item_url)
            print(f"Page {page}: genuinely_new={page_new}")
            if len(items) < MAX_ITEMS_PER_PAGE:
                break

    if not initialized:
        state["seen_urls"] = list(page_seen_urls)[-20000:]
        state["items"] = {item["url"]: item for item in all_items[-20000:]}
        state["pending_items"] = {}
        state["initialized"] = True
        state["last_checked_at"] = now.isoformat()
        state["last_new_count"] = 0
        save_state(state)
        RESULT_PATH.write_text(json.dumps({"checked_at": now.isoformat(), "initialized": True, "collected": len(all_items), "new": 0, "pending": 0, "notified": 0, "elapsed_seconds": round(time.monotonic() - overall_started, 2)}, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    fresh_set = set(fresh_new_urls)
    already_pending_seen = len(pending_before.intersection(page_seen_urls - seen))
    print(
        f"Total collected: {len(all_items)}, genuinely new URLs: {len(fresh_new_urls)}, "
        f"already-pending seen again: {already_pending_seen}, pending backlog: {len(pending)}"
    )

    # Newly discovered listings always go first. Older failed/pending details follow.
    old_pending_urls = [url for url in pending.keys() if url not in fresh_set]
    pending_urls = (fresh_new_urls + old_pending_urls)[:DETAIL_FETCH_LIMIT]
    detail_items = [pending[url] for url in pending_urls]
    print(f"Detail priority: fresh={min(len(fresh_new_urls), DETAIL_FETCH_LIMIT)}, old_pending={max(0, len(pending_urls) - min(len(fresh_new_urls, DETAIL_FETCH_LIMIT)))}")

    notified = []
    failed_details = 0
    detail_started = time.monotonic()
    if detail_items:
        workers = max(1, min(DETAIL_FETCH_WORKERS, len(detail_items)))
        print(f"Fetching {len(detail_items)} detail pages with {workers} workers")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            detailed_items = list(executor.map(fetch_detail, detail_items))
    else:
        detailed_items = []
    print(f"DETAIL FETCH SECONDS: {time.monotonic() - detail_started:.2f}s")

    for item in detailed_items:
        url = item["url"]
        if not item.get("detail_ok"):
            failed_details += 1
            continue
        matches = match_rules(item, rules)
        print(f"MATCH CHECK: title={item['title']!r} matches={[m['keyword'] for m in matches]}")
        db_items[url] = item
        if matches:
            post_discord(webhook, item, matches)
            notified.append({"url": url, "title": item["title"], "matches": matches})
        seen.add(url)
        pending.pop(url, None)

    for item in all_items:
        if item["url"] not in seen:
            pending.setdefault(item["url"], item)
        else:
            db_items.setdefault(item["url"], item)

    state["seen_urls"] = list(seen)[-20000:]
    state["items"] = dict(list(db_items.items())[-20000:])
    state["pending_items"] = dict(list(pending.items())[-20000:])
    state["last_checked_at"] = now.isoformat()
    state["last_new_count"] = len(fresh_new_urls)
    state["last_pending_count"] = len(pending)
    state["last_notified_count"] = len(notified)
    state["last_detail_failed_count"] = failed_details
    save_state(state)

    elapsed = time.monotonic() - overall_started
    RESULT_PATH.write_text(json.dumps({
        "checked_at": now.isoformat(),
        "initialized": True,
        "collected": len(all_items),
        "new": len(fresh_new_urls),
        "already_pending_seen": already_pending_seen,
        "processed_details": len(detailed_items) - failed_details,
        "detail_failed": failed_details,
        "pending": len(pending),
        "notified": len(notified),
        "elapsed_seconds": round(elapsed, 2),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"RESULT: collected={len(all_items)} new={len(fresh_new_urls)} already_pending_seen={already_pending_seen} processed={len(detailed_items) - failed_details} failed={failed_details} pending={len(pending)} notified={len(notified)} elapsed={elapsed:.2f}s")


if __name__ == "__main__":
    main()
