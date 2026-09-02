import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

import scout

WATCHLIST_PATH = Path("watchlist.json")
STATE_PATH = Path("watch_state.json")
MAX_NEW_ITEMS = 20
SCAN_PAGES = 30
MAX_DISTANCE_KM = 50
DISCORD_RETRIES = 4
DISCORD_MIN_INTERVAL = 1.25
HOME_COORDS = (35.1709, 136.8815)  # 名古屋市中村区付近

# 50km判定用の市区町村中心座標。未知の場所は安全側に除外する。
CITY_COORDS = {
    "名古屋市": (35.1815, 136.9066),
    "一宮市": (35.3039, 136.8031), "稲沢市": (35.2480, 136.8040), "清須市": (35.1990, 136.8520),
    "北名古屋市": (35.2450, 136.8700), "岩倉市": (35.2790, 136.8710), "江南市": (35.3320, 136.8710),
    "犬山市": (35.3780, 136.9440), "小牧市": (35.2910, 136.9120), "春日井市": (35.2470, 136.9722),
    "瀬戸市": (35.2240, 137.0840), "尾張旭市": (35.2160, 137.0350), "長久手市": (35.1840, 137.0480),
    "日進市": (35.1320, 137.0390), "豊明市": (35.0520, 137.0140), "東郷町": (35.0940, 137.0520),
    "みよし市": (35.0890, 137.0740), "豊田市": (35.0833, 137.1563), "岡崎市": (34.9547, 137.1749),
    "安城市": (34.9587, 137.0804), "刈谷市": (34.9893, 137.0021), "知立市": (35.0061, 137.0397),
    "高浜市": (34.9278, 136.9876), "碧南市": (34.8847, 136.9934), "西尾市": (34.8628, 137.0613),
    "大府市": (35.0079, 136.9627), "東海市": (35.0220, 136.9020), "知多市": (34.9960, 136.8640),
    "半田市": (34.8910, 136.9380), "常滑市": (34.8580, 136.8050), "弥富市": (35.1120, 136.7260),
    "津島市": (35.1770, 136.7410), "愛西市": (35.1570, 136.7300), "あま市": (35.1960, 136.8170),
    "大治町": (35.1840, 136.8250), "蟹江町": (35.1320, 136.7960), "豊山町": (35.2500, 136.9100),
    "豊川市": (34.8268, 137.3759),
}

STATUS_RE = re.compile(r"受付終了|掲載終了|募集終了|取引終了|終了しました|終了済み")


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def load_watchlist():
    data = load_json(WATCHLIST_PATH, {})
    entries = data.get("brands", []) + [
        {"name": x, "aliases": [x], "priority": "キーワード"}
        for x in data.get("extra_terms", [])
    ]
    return entries


def match_watchlist(item, entries):
    text = norm(" ".join([item.get("title", ""), item.get("text", "")]))
    hits = []
    seen = set()
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
    return set(data.get("seen_urls", []))


def save_state(seen):
    urls = list(seen)[-5000:]
    STATE_PATH.write_text(json.dumps({"updated_at": datetime.now().isoformat(timespec="seconds"), "seen_urls": urls}, ensure_ascii=False, indent=2), encoding="utf-8")


def haversine_km(a, b):
    lat1, lon1 = a
    lat2, lon2 = b
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 6371.0 * 2 * asin(sqrt(h))


def detect_location(text):
    # 市区町村名を先に拾う。名古屋市は区名まで含まれていても対応する。
    candidates = sorted(CITY_COORDS, key=len, reverse=True)
    for city in candidates:
        if city in text:
            return city
    return None


def apply_distance_filter(item):
    text = " ".join([item.get("title", ""), item.get("text", "")])
    city = detect_location(text)
    if not city:
        return False, None, None
    distance = haversine_km(HOME_COORDS, CITY_COORDS[city])
    return distance <= MAX_DISTANCE_KM, city, round(distance, 1)


def discord_notify(items):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        print("DISCORD_WEBHOOK_URL is not configured; notification skipped.")
        return False
    if not items:
        print("Discord: no matching items; notification skipped.")
        return True

    send_items = items[:MAX_NEW_ITEMS]
    print(f"Discord: sending {len(send_items)} notification(s)...")
    ok = True
    for index, item in enumerate(send_items):
        if index:
            time.sleep(DISCORD_MIN_INTERVAL)

        hits = ", ".join(h["name"] for h in item.get("watch_hits", [])[:4]) or "監視一致"
        priority = "🔥" if any(h.get("priority") == "最優先" for h in item.get("watch_hits", [])) else "🟡"
        image = (item.get("image_urls") or [None])[0]
        distance = item.get("distance_km")
        location = item.get("location") or "場所不明"
        distance_text = f"距離：約{distance}km" if distance is not None else "距離：判定不可"
        embed = {
            "title": f"{priority} {item.get('title', 'ジモティー商品')[:240]}",
            "url": item.get("url"),
            "description": f"監視一致：{hits}\n価格：{item.get('price', 0):,}円\n場所：{location}\n{distance_text}\n\n30ページスキャン / 終了済み除外",
            "footer": {"text": "Resell Scout"},
        }
        if image:
            embed["image"] = {"url": image}
        payload = json.dumps({"content": "🚨 ジモティー仕入れ候補", "embeds": [embed]}, ensure_ascii=False).encode("utf-8")

        delivered = False
        for attempt in range(1, DISCORD_RETRIES + 1):
            try:
                req = urllib.request.Request(
                    webhook,
                    data=payload,
                    headers={"Content-Type": "application/json", "User-Agent": "ResellScout/1.0"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as r:
                    body = r.read().decode("utf-8", errors="replace")
                    print(f"Discord: HTTP {r.status} for {item.get('title', 'item')}")
                    if r.status in (200, 204):
                        delivered = True
                        break
                    print("Discord notification failed:", r.status, body[:300])
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    retry_after = e.headers.get("Retry-After", "1.5")
                    try:
                        wait = max(float(retry_after), 1.5) + 0.25
                    except ValueError:
                        wait = 2.0
                    print(f"Discord: HTTP 429; retry {attempt}/{DISCORD_RETRIES} after {wait:.2f}s")
                    time.sleep(wait)
                    continue
                ok = False
                print("Discord notification HTTP error:", e.code, repr(e))
                break
            except Exception as e:
                ok = False
                print("Discord notification error:", repr(e))
                break

        if not delivered:
            ok = False
            print(f"Discord: delivery failed after {DISCORD_RETRIES} attempt(s): {item.get('title', 'item')}")

    return ok


def main():
    entries = load_watchlist()
    seen = load_state()
    week_scan = os.environ.get("WEEK_SCAN", "true").strip().lower() == "true"
    all_items = []

    for base_url in scout.SEARCH_URLS:
        for page in range(1, SCAN_PAGES + 1):
            url = base_url if page == 1 else f"{base_url}?page={page}"
            print("Fetching:", url)
            try:
                html = scout.fetch(url)
                all_items.extend(scout.extract_items(html))
            except Exception as e:
                print("Fetch failed:", repr(e))

    unique = {}
    for item in all_items:
        unique[item["url"]] = item

    matches = []
    distance_excluded = 0
    unknown_location = 0
    ended_excluded = 0
    for url, item in unique.items():
        if STATUS_RE.search(" ".join([item.get("title", ""), item.get("text", "")])):
            ended_excluded += 1
            continue
        if not week_scan and url in seen:
            continue
        in_range, location, distance = apply_distance_filter(item)
        if not in_range:
            if location is None:
                unknown_location += 1
            else:
                distance_excluded += 1
            continue
        hits = match_watchlist(item, entries)
        if hits:
            item["watch_hits"] = hits
            item["location"] = location
            item["distance_km"] = distance
            matches.append(item)

    if not week_scan:
        seen.update(unique.keys())
        save_state(seen)

    matches.sort(key=lambda x: (0 if any(h.get("priority") == "最優先" for h in x.get("watch_hits", [])) else 1, x.get("price", 0)))
    Path("new_matches.json").write_text(json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"), "mode": "30-PAGE-SCAN-50KM" if week_scan else "NEW-ONLY-50KM", "count": len(matches), "matches": matches[:MAX_NEW_ITEMS]}, ensure_ascii=False, indent=2), encoding="utf-8")

    mode = "30-PAGE-SCAN-50KM" if week_scan else "NEW-ONLY-50KM"
    print(f"Mode: {mode}")
    print(f"Observed: {len(unique)} / 50km内: {len(unique) - distance_excluded - unknown_location} / 終了済み除外: {ended_excluded} / 距離外: {distance_excluded} / 場所不明: {unknown_location} / Watched matches: {len(matches)}")
    for item in matches[:MAX_NEW_ITEMS]:
        print(f"MATCH: {item['title']} / {item['price']:,}円 / {item.get('location')} / 約{item.get('distance_km')}km / {item['url']}")

    if not discord_notify(matches):
        raise RuntimeError("Discord notification failed")


if __name__ == "__main__":
    main()
