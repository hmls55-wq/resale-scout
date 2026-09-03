import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SEARCH_TERM = os.environ.get("JIMOTY_SEARCH_TERM", "IKEA")
STATE_PATH = Path(os.environ.get("JIMOTY_STATE_PATH", "jimoty_one_search_state.json"))
RESULT_PATH = Path(os.environ.get("JIMOTY_RESULT_PATH", "jimoty_one_search_result.json"))
MAX_NEW_ITEMS = 5
MAX_PARSED_ITEMS = 100
DISCORD_RETRIES = 4
JST = ZoneInfo("Asia/Tokyo")
BASE_URL = "https://jmty.jp/aichi/sale-fur-kw-"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile Safari/604.1"


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Referer": "https://jmty.jp/",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", errors="ignore")
        print(f"HTTP {r.status}, HTML {len(html):,} bytes")
        if len(html) < 5_000:
            raise RuntimeError(f"HTMLが短すぎます: {len(html)} bytes")
        return html


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
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


def extract_items(html):
    matches = list(re.finditer(
        r'<a[^>]+href=["\']([^"\']*article-[^"\']+)["\'][^>]*>(.*?)</a>',
        html, re.I | re.S
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
        end = min(len(html), m.start() + 15000)
        text = clean(html[start:end])

        title = clean(m.group(2))
        title = re.sub(r"お気に入り.*$", "", title).strip()
        price = extract_price(text)
        if not title or price is None:
            continue

        items.append({"title": title[:200], "price": price, "url": url, "text": text})
        if len(items) >= MAX_PARSED_ITEMS:
            break
    return items


def load_state():
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return set(data.get("notified_urls", [])), bool(data.get("initialized"))


def save_state(urls, initialized=True):
    STATE_PATH.write_text(json.dumps({
        "updated_at": datetime.now(JST).isoformat(),
        "search_term": SEARCH_TERM,
        "initialized": initialized,
        "notified_urls": list(urls)[-5000:]
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def post_discord(webhook, payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(1, DISCORD_RETRIES + 1):
        try:
            req = urllib.request.Request(webhook, data=data, headers={"Content-Type": "application/json", "User-Agent": "ResellScout/1.0"}, method="POST")
            with urllib.request.urlopen(req, timeout=15) as r:
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


def discord_notify(items):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        raise RuntimeError("DISCORD_WEBHOOK_URL secret が設定されていません")
    for i, item in enumerate(items[:MAX_NEW_ITEMS]):
        if i:
            time.sleep(1.25)
        post_discord(webhook, {
            "content": "🚨 ジモティー新着",
            "embeds": [{
                "title": item["title"],
                "url": item["url"],
                "description": f"検索：{SEARCH_TERM}\n価格：{item['price']:,}円\n掲載：検索結果の新着\n\nジモティーの検索結果から検出",
                "footer": {"text": "Resell Scout / Jimoty"},
            }],
        })


def discord_diagnostic(parsed, latest, new_items, initialized):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        raise RuntimeError("DISCORD_WEBHOOK_URL secret が設定されていません")
    post_discord(webhook, {
        "content": "🧪 ジモティー監視テスト接続OK",
        "embeds": [{
            "title": f"{SEARCH_TERM}検索の診断結果",
            "description": f"検索ページ取得：OK\n取得商品数：{parsed}件\n今回見る最新：{latest}件\nDiscord通知対象：{new_items}件\n状態初期化済み：{'はい' if initialized else 'いいえ'}",
            "footer": {"text": "Resell Scout / Jimoty diagnostic"},
        }],
    })


def main():
    now = datetime.now(JST)
    encoded = urllib.parse.quote(SEARCH_TERM, safe="")
    url = BASE_URL + encoded
    print(f"Search: {SEARCH_TERM}")
    print(f"URL: {url}")
    html = fetch(url)
    items = extract_items(html)
    latest_items = items[:MAX_NEW_ITEMS]
    print(f"Parsed: {len(items)}, latest: {len(latest_items)}")

    state, initialized = load_state()
    current_urls = {x["url"] for x in items}

    test_notify = os.environ.get("JIMOTY_TEST_NOTIFY", "0") == "1"
    if test_notify:
        new_items = items[:1]
        if new_items:
            discord_notify(new_items)
            print("TEST: Discord notification sent for the current latest item; state was not changed.")
        else:
            raise RuntimeError("TEST: 通知対象の商品を取得できませんでした")
        save_state(state, initialized=initialized)
    elif not initialized:
        state.update(current_urls)
        save_state(state, initialized=True)
        new_items = []
        print(f"State initialized with {len(current_urls)} URLs; no old items notified.")
    else:
        new_items = [x for x in items if x["url"] not in state][:MAX_NEW_ITEMS]
        print(f"New in latest {MAX_PARSED_ITEMS}: {len(new_items)}")
        if new_items:
            discord_notify(new_items)
            state.update(x["url"] for x in new_items)
        save_state(state, initialized=True)

    if os.environ.get("JIMOTY_DIAGNOSTIC", "0") == "1":
        discord_diagnostic(len(items), len(latest_items), len(new_items), True)

    print("No new items; Discord notification skipped." if not new_items else f"Discord notified: {len(new_items)}")

    RESULT_PATH.write_text(json.dumps({
        "checked_at": now.isoformat(),
        "search_term": SEARCH_TERM,
        "search_url": url,
        "parsed_items": len(items),
        "latest_items": len(latest_items),
        "new_items": len(new_items),
        "items": new_items[:MAX_NEW_ITEMS],
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
