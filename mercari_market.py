import json
import re
import statistics
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

INPUT = Path("resell_candidates.json")
OUTPUT = Path("mercari_market.json")
DEBUG_SCREENSHOT = Path("mercari_debug.png")
DEBUG_TEXT = Path("mercari_debug.txt")
MAX_CHECKS = 20
MAX_CARD_ITEMS = 30
MIN_PRICE = 300
MAX_PRICE = 2_000_000
PAGE_TIMEOUT_MS = 20000
WAIT_AFTER_LOAD_MS = 2200
WAIT_AFTER_SCROLL_MS = 900


def normalize(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def money_values(text):
    values = []
    # Never parse US$/$/€ values as Japanese yen.
    patterns = [
        r"(?:¥|￥)\s*([0-9,]+)",
        r"([0-9]{1,3}(?:,[0-9]{3})+)円",
        r"(?:^|\s)([0-9]{3,7})円",
    ]
    for pattern in patterns:
        for value in re.findall(pattern, text):
            try:
                v = int(value.replace(",", ""))
                if MIN_PRICE <= v <= MAX_PRICE:
                    values.append(v)
            except ValueError:
                pass
    return list(dict.fromkeys(values))


def structured_jpy_prices(text):
    values = []
    patterns = [
        r'"priceCurrency"\s*:\s*"JPY".{0,2000}?"price"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"price"\s*:\s*([0-9]+(?:\.[0-9]+)?).{0,2000}?"priceCurrency"\s*:\s*"JPY"',
        r'"currency"\s*:\s*"JPY".{0,2000}?"(?:amount|price|value)"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"(?:amount|price|value)"\s*:\s*([0-9]+(?:\.[0-9]+)?).{0,2000}?"currency"\s*:\s*"JPY"',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.S):
            try:
                v = int(float(match.group(1)))
                if MIN_PRICE <= v <= MAX_PRICE:
                    values.append(v)
            except ValueError:
                pass
    return list(dict.fromkeys(values))


def tokens(s):
    s = normalize(s).lower()
    out = re.findall(r"[a-z0-9][a-z0-9._-]{1,}|[ぁ-んァ-ヶ一-龥々ー]{2,}", s)
    return {x for x in out if x not in {"中古", "美品", "送料無料", "即購入", "匿名配送", "送料込み", "ジャンク", "セット", "商品"}}


def score_similarity(source_title, candidate_title):
    a = tokens(source_title)
    b = tokens(candidate_title)
    if not a or not b:
        return 0
    overlap = len(a & b) / max(1, len(a))
    model_hits = sum(1 for x in a & b if re.search(r"[a-z0-9]", x))
    return min(100, int(overlap * 75 + min(model_hits, 5) * 5))


def looks_like_auction(text):
    t = normalize(text).lower()
    return any(x in t for x in ["オークション", "入札", "入札件数", "入札履歴", "開始価格", "現在価格", "最高額", "落札", "auction", "bid", "bids"])


def looks_sold(text):
    t = normalize(text).lower()
    return any(x in t for x in ["売り切れ", "sold out", "soldout", "取引完了", "sold", "購入済み"])


def ensure_japan_region(page):
    body = normalize(page.locator("body").inner_text())
    if "別の地域の商品を閲覧しています" not in body:
        return True
    try:
        selects = page.locator("select")
        for i in range(selects.count()):
            sel = selects.nth(i)
            try:
                if sel.locator('option[value="jp"]').count() > 0:
                    sel.select_option("jp")
                    break
            except Exception:
                continue
        try:
            loc = page.get_by_text("日本", exact=True)
            if loc.count() > 0:
                loc.last.click(timeout=1500)
        except Exception:
            pass
        try:
            cont = page.get_by_text("続ける", exact=True)
            if cont.count() > 0:
                cont.last.click(timeout=1500)
        except Exception:
            pass
        page.wait_for_timeout(1200)
        body_after = normalize(page.locator("body").inner_text())
        return "別の地域の商品を閲覧しています" not in body_after
    except Exception as exc:
        print("region select error:", repr(exc))
        return False


def collect_dom_items(page):
    return page.locator('a[href*="/item/"]').evaluate_all("""
        els => els.map(a => ({href: a.href, text: (a.closest('li') || a.closest('[role="article"]') || a.parentElement || a).innerText || ''}))
    """)


def collect_item_urls_from_html(page):
    html = page.locator("html").inner_html()
    found = []
    for pattern in [r'href=["\']([^"\']*/item/[0-9A-Za-z_-]+[^"\']*)', r'(https://jp\.mercari\.com/item/[0-9A-Za-z_-]+)']:
        for match in re.findall(pattern, html, re.I):
            href = match if match.startswith("http") else urllib.parse.urljoin(page.url, match)
            href = href.split("?")[0]
            if href not in found:
                found.append(href)
    return found


def item_text_for_url(page, href):
    try:
        return normalize(page.locator(f'a[href*="{href.split("/item/")[-1]}"]').first.inner_text())
    except Exception:
        return ""


def detail_jpy_price(page, href):
    try:
        page.goto(href, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        page.wait_for_timeout(1200)
        body = normalize(page.locator("body").inner_text())
        html = page.locator("html").inner_html()
        if looks_like_auction(body) or "US$" in body or "USD" in body:
            return None
        blobs = page.locator("script").all_inner_texts() + [html]
        for blob in blobs:
            values = structured_jpy_prices(blob)
            if values:
                return values[0]
        values = money_values(body)
        if values and (looks_sold(body) or not any(x in body for x in ["購入手続きへ", "購入する", "販売中"])):
            return values[0]
    except Exception as exc:
        print("detail price error:", repr(exc))
    return None


def _price_from_obj(value):
    if isinstance(value, (int, float)):
        v = int(value)
        return v if MIN_PRICE <= v <= MAX_PRICE else None
    if isinstance(value, dict):
        for k in ("amount", "value", "price", "amountJPY"):
            if k in value:
                p = _price_from_obj(value[k])
                if p is not None:
                    return p
    return None


def mercari_api_rows(payload):
    rows = []
    seen = set()

    def walk(obj):
        if isinstance(obj, dict):
            status = str(obj.get("status") or "")
            item_type = str(obj.get("itemType") or "")
            auction = bool(obj.get("auction"))
            item_id = str(obj.get("id") or obj.get("itemId") or "").strip()
            price = _price_from_obj(obj.get("price"))
            if status == "ITEM_STATUS_SOLD_OUT" and item_type in ("ITEM_TYPE_MERCARI", "", "ITEM_TYPE_MERCARI_V2") and not auction and item_id and price:
                title = normalize(obj.get("name") or obj.get("title") or "")
                key = (item_id, price)
                if key not in seen:
                    seen.add(key)
                    rows.append({"url": f"https://jp.mercari.com/item/{item_id}", "title": title, "price": price, "auction": False, "sold": True, "price_source": "search_api_jpy"})
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    walk(payload)
    return rows


def browser_lookup(page, query, debug=False):
    url = "https://jp.mercari.com/search?" + urllib.parse.urlencode({"keyword": query, "status": "sold_out"})
    api_payloads = []
    def capture_response(response):
        if "api.mercari.jp/v2/entities:search" in response.url:
            try:
                api_payloads.append(response.json())
            except Exception:
                pass
    page.on("response", capture_response)
    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
    page.wait_for_timeout(WAIT_AFTER_LOAD_MS)
    region_ok = ensure_japan_region(page)
    page.wait_for_timeout(500)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(WAIT_AFTER_SCROLL_MS)

    api_rows = []
    for payload in reversed(api_payloads):
        api_rows.extend(mercari_api_rows(payload))
    unique = {}
    for row in api_rows:
        unique[row["url"]] = row
    api_rows = list(unique.values())
    print("MERCARI_API_SOLD_JPY_ROWS=", len(api_rows))

    dom_items = collect_dom_items(page)
    html_urls = collect_item_urls_from_html(page)
    if debug:
        body = normalize(page.locator("body").inner_text())
        DEBUG_TEXT.write_text(f"URL={page.url}\nREGION_OK={region_ok}\nAPI_PAYLOADS={len(api_payloads)}\nAPI_JPY_ROWS={len(api_rows)}\nDOM_ITEM_ANCHORS={len(dom_items)}\nHTML_ITEM_URLS={len(html_urls)}\nHTML_URL_SAMPLE={html_urls[:10]}\nBODY={body[:20000]}", encoding="utf-8")
        page.screenshot(path=str(DEBUG_SCREENSHOT), full_page=False)

    candidates, seen = [], set()
    for raw in dom_items:
        href, text = raw.get("href", ""), normalize(raw.get("text", ""))
        if not href or href in seen or not text or looks_like_auction(text):
            continue
        seen.add(href)
        candidates.append((href, text))
    for href in html_urls:
        if href not in seen:
            seen.add(href)
            candidates.append((href, ""))

    rows = api_rows[:MAX_CARD_ITEMS]
    if not rows and region_ok:
        for href, text in candidates[:MAX_CARD_ITEMS]:
            if "US$" in text or "USD" in text:
                continue
            card_prices = money_values(text)
            if card_prices:
                rows.append({"url": href, "title": text[:500], "price": card_prices[0], "auction": False, "sold": True, "price_source": "search_card"})

    detail_checked = 0
    if not rows and candidates:
        href, text = candidates[0]
        detail_checked = 1
        price = detail_jpy_price(page, href)
        if price is not None:
            rows = [{"url": href, "title": text[:500], "price": price, "auction": False, "sold": True, "price_source": "detail_page_fallback"}]

    prices = sorted(x["price"] for x in rows if x.get("price"))
    return {"query": query, "url": url, "count": len(prices), "prices": prices, "median": int(statistics.median(prices)) if prices else None, "robust_median": int(statistics.median(prices)) if prices else None, "low": min(prices) if prices else None, "high": max(prices) if prices else None, "items": rows, "anchor_count": len(dom_items), "html_url_count": len(html_urls), "checked_card_items": min(len(candidates), MAX_CARD_ITEMS), "checked_links": detail_checked, "auction_excluded": True, "sold_only_enforced": True, "region_ok": region_ok, "best_similarity": max([score_similarity(query, row.get("title", "")) for row in rows] + [0]), "price_source": (rows[0].get("price_source") if rows else None)}


def make_query(item):
    title = normalize(item.get("jmty_detail_title") or item.get("title") or "")
    brands = item.get("brands") or []
    brand = normalize(brands[0].get("name", "")) if brands else ""
    # Prefer concrete detail title; append brand only when it is not already present.
    if brand and brand.lower() not in title.lower():
        return f"{brand} {title}".strip()
    return title


def main():
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    checked = []
    candidates = data.get("candidates", [])
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="ja-JP", timezone_id="Asia/Tokyo", geolocation={"latitude": 35.6895, "longitude": 139.6917}, permissions=["geolocation"], extra_http_headers={"Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8"}, viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        for index, item in enumerate(candidates[:MAX_CHECKS]):
            query = make_query(item)
            if not query:
                continue
            try:
                result = browser_lookup(page, query, debug=(index == 0))
            except Exception as exc:
                result = {"query": query, "url": "", "count": 0, "prices": [], "items": [], "error": repr(exc), "best_similarity": 0}
            result.update({"source_url": item.get("url"), "source_title": normalize(item.get("jmty_detail_title") or item.get("title") or ""), "purchase_price": item.get("price", 0), "source_item_index": index})
            checked.append(result)
            print("メルカリ検索結果", result["source_title"], "query=", query, "価格=", result.get("prices"), "中央値=", result.get("robust_median"), "価格取得元=", result.get("price_source"))
            time.sleep(0.2)
        context.close()
        browser.close()
    OUTPUT.write_text(json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"), "checked": checked, "note": "メルカリ売り切れ検索。JPY価格をAPI→日本円DOM→詳細の順で取得し、USD表示は除外。"}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
