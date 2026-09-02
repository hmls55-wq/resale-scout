import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import scout

WATCHLIST_PATH = Path("watchlist.json")
STATE_PATH = Path("watch_state.json")
MAX_NEW_ITEMS = 20
SCAN_PAGES = int(os.environ.get("SCAN_PAGES", "5"))
DISCORD_RETRIES = 4
DISCORD_MIN_INTERVAL = 1.25
AREA_PORTAL_BASE = "https://jmty.jp/s/area_portal/1005342?distance=50"
AREA_LABEL = "名古屋市中村区・50km圏内"
AREA_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
STATUS_RE = re.compile(r"受付終了|掲載終了|募集終了|取引終了|終了しました|終了済み")


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def norm(s):
    """Compare names while ignoring harmless typography differences."""
    import unicodedata
    s = unicodedata.normalize("NFKC", str(s or "")).lower()
    return re.sub(r"[^0-9a-zぁ-んァ-ヶ一-龯々ー]+", "", s)


def load_watchlist():
    data = load_json(WATCHLIST_PATH, {})
    return data.get("brands", []) + [{"name": x, "aliases": [x], "priority": "キーワード"} for x in data.get("extra_terms", [])]


def match_watchlist(item, entries):
    text = norm(" ".join([item.get("title", ""), item.get("text", "")]))
    hits, seen = [], set()
    for entry in entries:
        for alias in entry.get("aliases", []):
            a = norm(alias)
            name = entry.get("name", alias)
            if a and a in text and name not in seen:
                hits.append({"name": name, "matched": alias, "priority": entry.get("priority", "監視")})
                seen.add(name)
                break
    return hits


def load_state():
    data = load_json(STATE_PATH, {})
    return {
        "seen_urls": set(data.get("seen_urls", [])),
        "notified_match_urls": set(data.get("notified_match_urls", [])),
    }


def save_state(state):
    STATE_PATH.write_text(json.dumps({
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "seen_urls": list(state["seen_urls"])[-5000:],
        "notified_match_urls": list(state["notified_match_urls"])[-5000:],
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_area_page(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": AREA_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Referer": "https://jmty.jp/",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", errors="ignore")
        print(f"  HTTP {r.status}, HTML {len(html):,} bytes")
        if len(html) < 5_000:
            raise RuntimeError(f"HTMLが短すぎます ({len(html)} bytes)")
        return html


def detect_location(text):
    cities = ["名古屋市", "一宮市", "稲沢市", "清須市", "北名古屋市", "岩倉市", "江南市", "犬山市", "小牧市", "春日井市", "瀬戸市", "尾張旭市", "長久手市", "日進市", "豊明市", "東郷町", "みよし市", "豊田市", "岡崎市", "安城市", "刈谷市", "知立市", "高浜市", "碧南市", "西尾市", "大府市", "東海市", "知多市", "半田市", "常滑市", "弥富市", "津島市", "愛西市", "あま市", "大治町", "蟹江町", "豊山町", "豊川市"]
    for city in sorted(cities, key=len, reverse=True):
        if city in text: return city
    return None


def rescue_watchlist_items(html, entries, parsed_items):
    """Recover watchlist items that scout.extract_items() dropped during parsing.

    The normal parser intentionally requires a price. This rescue path only
    examines raw article anchors whose own text matches the watchlist, then
    searches a larger nearby HTML window for the price. This prevents a
    malformed/advert-heavy card from hiding a wanted listing.
    """
    existing = {item.get("url") for item in parsed_items}
    rescued = []
    try:
        parser = scout.JmtyAnchorParser()
        parser.feed(html)
    except Exception as e:
        print("  Rescue parser failed:", repr(e))
        return rescued

    for anchor in parser.items:
        href = anchor.get("href", "")
        url = "https://jmty.jp" + href if href.startswith("/") else href if href.startswith("http") else None
        if not url or url in existing:
            continue
        title = anchor.get("text") or anchor.get("title_attr") or ""
        probe = {"title": title, "text": title}
        hits = match_watchlist(probe, entries)
        if not hits:
            continue

        pos = html.find(href)
        block = ""
        if pos >= 0:
            block = re.sub(r"<[^>]+>", " ", html[max(0, pos - 1200):min(len(html), pos + 10000)])
        clean = re.sub(r"\s+", " ", block).strip()
        price = scout.extract_price(clean) if clean else None
        if price is None:
            price = scout.extract_price(title)
        if price is None:
            print(f"  WATCHLIST RAW HIT but price not found: {title[:120]} / {url}")
            continue

        image_urls = []
        for src in anchor.get("images", []):
            if src.startswith("//"): src = "https:" + src
            elif src.startswith("/"): src = "https://jmty.jp" + src
            if src.startswith("http") and src not in image_urls:
                image_urls.append(src)

        item = {
            "title": title[:240],
            "price": price,
            "url": url.split("#", 1)[0],
            "text": clean or title,
            "image_urls": image_urls[:5],
            "rescue": True,
        }
        item["watch_hits"] = match_watchlist(item, entries)
        if item["watch_hits"]:
            rescued.append(item)
            existing.add(item["url"])
            print(f"  RESCUED WATCHLIST ITEM: {item['title'][:120]} / {item['price']:,}円 / {item['url']}")
    return rescued


def discord_notify(items):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook: return False if items else True
    if not items:
        print("Discord: no matching items; notification skipped."); return True
    send_items = items[:MAX_NEW_ITEMS]; print(f"Discord: sending {len(send_items)} notification(s)..."); ok = True
    for index, item in enumerate(send_items):
        if index: time.sleep(DISCORD_MIN_INTERVAL)
        hits = ", ".join(h["name"] for h in item.get("watch_hits", [])[:4]) or "監視一致"
        priority = "🔥" if any(h.get("priority") == "最優先" for h in item.get("watch_hits", [])) else "🟡"
        image = (item.get("image_urls") or [None])[0]
        location = item.get("location") or "場所は商品ページで確認"
        rescue = " / パーサー救済" if item.get("rescue") else ""
        embed = {"title": f"{priority} {item.get('title', 'ジモティー商品')[:240]}", "url": item.get("url"), "description": f"監視一致：{hits}\n価格：{item.get('price', 0):,}円\n場所：{location}\n検索条件：{AREA_LABEL}\n\nジモティーの距離検索結果から全カテゴリーを監視 / 終了済み除外{rescue}", "footer": {"text": "Resell Scout"}}
        if image: embed["image"] = {"url": image}
        payload = json.dumps({"content": "🚨 ジモティー仕入れ候補", "embeds": [embed]}, ensure_ascii=False).encode("utf-8")
        delivered = False
        for attempt in range(1, DISCORD_RETRIES + 1):
            try:
                req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json", "User-Agent": "ResellScout/1.0"}, method="POST")
                with urllib.request.urlopen(req, timeout=15) as r:
                    print(f"Discord: HTTP {r.status} for {item.get('title', 'item')}")
                    if r.status in (200, 204): delivered = True; break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    try: wait = max(float(e.headers.get("Retry-After", "1.5")), 1.5) + 0.25
                    except ValueError: wait = 2.0
                    print(f"Discord: HTTP 429; retry {attempt}/{DISCORD_RETRIES} after {wait:.2f}s"); time.sleep(wait); continue
                print("Discord notification HTTP error:", e.code, repr(e)); break
            except Exception as e:
                print("Discord notification error:", repr(e)); break
        if not delivered: ok = False; print(f"Discord: delivery failed: {item.get('title', 'item')}")
    return ok


def main():
    entries = load_watchlist(); state = load_state(); all_items = []
    for page in range(1, SCAN_PAGES + 1):
        url = AREA_PORTAL_BASE if page == 1 else f"{AREA_PORTAL_BASE}&page={page}"
        print("Fetching:", url)
        try:
            html = fetch_area_page(url)
            parsed = scout.extract_items(html)
            rescued = rescue_watchlist_items(html, entries, parsed)
            print(f"  parsed={len(parsed)} all-categories / rescued={len(rescued)}")
            all_items.extend(parsed)
            all_items.extend(rescued)
        except Exception as e:
            print("Fetch failed:", repr(e))

    unique = {item["url"]: item for item in all_items}
    matches = []
    ended_excluded = 0
    for url, item in unique.items():
        text = " ".join([item.get("title", ""), item.get("text", "")])
        if STATUS_RE.search(text):
            ended_excluded += 1
            continue
        hits = match_watchlist(item, entries)
        if not hits:
            continue
        item["watch_hits"] = hits
        item["location"] = detect_location(text)
        item["distance_km"] = 50
        if url not in state["notified_match_urls"]:
            matches.append(item)

    state["seen_urls"].update(unique.keys())
    state["notified_match_urls"].update(item["url"] for item in matches)
    save_state(state)

    matches.sort(key=lambda x: (0 if any(h.get("priority") == "最優先" for h in x.get("watch_hits", [])) else 1, x.get("price", 0)))
    Path("new_matches.json").write_text(json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"), "mode": f"AREA-PORTAL-50KM-ALL-P{SCAN_PAGES}", "count": len(matches), "matches": matches[:MAX_NEW_ITEMS]}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Mode: AREA-PORTAL-50KM-ALL-P{SCAN_PAGES}")
    print(f"Observed all categories: {len(unique)} / 終了済み除外: {ended_excluded} / Watched matches: {len(matches)}")
    for item in matches[:MAX_NEW_ITEMS]:
        print(f"MATCH: {item['title']} / {item['price']:,}円 / {item.get('location') or '場所は商品ページで確認'} / 中村区から50km圏内 / {item['url']}")
    if not discord_notify(matches):
        raise RuntimeError("Discord notification failed")


if __name__ == "__main__": main()
