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

SEARCH_TERM = os.environ.get("JIMOTY_SEARCH_TERM", "カリモク")
STATE_PATH = Path("jimoty_one_search_state.json")
MAX_NEW_ITEMS = 20
DISCORD_RETRIES = 4
JST = ZoneInfo("Asia/Tokyo")
BASE_URL = "https://jmty.jp/aichi/sale-fur-kw-"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"


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
    links = re.findall(r'<a[^>]+href=["\']([^"\']*article-[^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S)
    seen = set()
    items = []
    for href, inner in links:
        url = href if href.startswith("http") else "https://jmty.jp" + href
        url = url.split("#", 1)[0]
        if url in seen:
            continue
        seen.add(url)
        pos = html.find(href)
        if pos < 0:
            continue
        block = html[max(0, pos - 800):min(len(html), pos + 5000)]
        text = clean(block)
        title = clean(inner)
        title = re.sub(r"お気に入り.*$", "", title).strip()
        price = extract_price(text)
        if not title or price is None:
            continue
        items.append({"title": title[:200], "price": price, "url": url, "text": text})
        if len(items) >= 100:
            break
    return items


def today_created(text, now):
    return re.search(rf"作成\s*{now.month}月\s*{now.day}日", text) is not None


def load_state():
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return set(data.get("notified_urls", []))


def save_state(urls):
    STATE_PATH.write_text(json.dumps({"updated_at": datetime.now(JST).isoformat(), "notified_urls": list(urls)[-5000:]}, ensure_ascii=False, indent=2), encoding="utf-8")


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
            "content": "🚨 ジモティー新着テスト",
            "embeds": [{
                "title": item["title"],
                "url": item["url"],
                "description": f"検索：{SEARCH_TERM}\n価格：{item['price']:,}円\n掲載：本日\n\nジモティーの検索結果から検出",
                "footer": {"text": "Resell Scout / Jimoty one-search test"},
            }],
        })


def discord_diagnostic(parsed, today, new_items):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        raise RuntimeError("DISCORD_WEBHOOK_URL secret が設定されていません")
    post_discord(webhook, {
        "content": "🧪 ジモティー監視テスト接続OK",
        "embeds": [{
            "title": "カリモク検索の診断結果",
            "description": f"検索ページ取得：OK\n取得商品数：{parsed}件\n今日判定：{today}件\nDiscord通知対象：{new_items}件\n\nこのメッセージが届けばDiscord接続は正常です。",
            "footer": {"text": "Resell Scout / Jimoty one-search diagnostic"},
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
    today_items = [x for x in items if today_created(x["text"], now)]
    print(f"Parsed: {len(items)}, today: {len(today_items)}")

    state = load_state()
    new_items = [x for x in today_items if x["url"] not in state]
    print(f"New to Discord: {len(new_items)}")

    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        discord_diagnostic(len(items), len(today_items), len(new_items))

    if new_items:
        discord_notify(new_items)
        state.update(x["url"] for x in new_items)
        save_state(state)
    else:
        save_state(state)
        print("No new items; Discord notification skipped.")

    Path("jimoty_one_search_result.json").write_text(json.dumps({
        "checked_at": now.isoformat(),
        "search_term": SEARCH_TERM,
        "search_url": url,
        "parsed_items": len(items),
        "today_items": len(today_items),
        "new_items": len(new_items),
        "items": new_items[:MAX_NEW_ITEMS],
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
