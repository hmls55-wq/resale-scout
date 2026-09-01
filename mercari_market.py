import json
import re
import statistics
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

INPUT = Path("resell_candidates.json")
OUTPUT = Path("mercari_market.json")
DEBUG_SCREENSHOT = Path("mercari_debug.png")
DEBUG_TEXT = Path("mercari_debug.txt")
MAX_CHECKS = 1  # まず1件で疎通確認。成功後に5件→15件へ増やす。
MIN_PRICE = 300
MAX_PRICE = 2_000_000
PAGE_TIMEOUT_MS = 25000
WAIT_AFTER_LOAD_MS = 2000
WAIT_AFTER_SCROLL_MS = 1000


def normalize(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def money_values(text):
    values = []
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
    return values


def structured_jpy_prices(text):
    """Extract JPY prices from embedded JSON/JSON-LD without treating USD as JPY."""
    values = []
    if not text:
        return values
    for match in re.finditer(r'"priceCurrency"\s*:\s*"JPY".{0,300}?"price"\s*:\s*([0-9]+(?:\.[0-9]+)?)', text, re.S):
        try:
            v = int(float(match.group(1)))
            if MIN_PRICE <= v <= MAX_PRICE:
                values.append(v)
        except ValueError:
            pass
    return values


def tokens(s):
    s = normalize(s).lower()
    out = re.findall(r"[a-z0-9][a-z0-9._-]{1,}|[ぁ-んァ-ヶ一-龥々ー]{2,}", s)
    stop = {"中古", "美品", "送料無料", "即購入", "匿名配送", "送料込み", "ジャンク", "セット", "商品"}
    return {x for x in out if x not in stop}


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
    auction_terms = [
        "オークション", "入札", "入札件数", "入札履歴", "開始価格",
        "現在価格", "最高額", "落札", "auction", "bid", "bids"
    ]
    return any(term in t for term in auction_terms)


def looks_sold(text):
    t = normalize(text).lower()
    sold_terms = ["売り切れ", "sold out", "soldout", "取引完了"]
    return any(term in t for term in sold_terms)


def ensure_japan_region(page):
    """Mercari can open a region-selection overlay and default to overseas USD.
    Explicitly choose Japan before reading prices so the scraper never treats USD as JPY.
    """
    body = normalize(page.locator("body").inner_text())
    if "別の地域の商品を閲覧しています" not in body:
        return False

    # The region dialog currently exposes a visible exact-text 日本 option.
    try:
        japan = page.get_by_text("日本", exact=True)
        if japan.count() > 0:
            japan.first.click(timeout=3000)
            page.wait_for_timeout(1200)
            return True
    except Exception as exc:
        print("region selection error:", repr(exc))

    # Fallback: click a button/link whose accessible text is exactly 日本.
    try:
        loc = page.locator('button, a').filter(has_text=re.compile(r"^日本$"))
        if loc.count() > 0:
            loc.first.click(timeout=3000)
            page.wait_for_timeout(1200)
            return True
    except Exception as exc:
        print("region fallback error:", repr(exc))
    return False


def collect_dom_items(page):
    return page.locator('a[href*="/item/"]').evaluate_all(
        """els => els.map(a => ({
            href: a.href,
            text: (a.closest('li') || a.closest('[role="article"]') || a.parentElement || a).innerText || ''
        }))"""
    )


def detail_jpy_price(page, href):
    """Open an item detail page and prefer structured JPY price data."""
    try:
        page.goto(href, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        page.wait_for_timeout(800)
        ensure_japan_region(page)
        scripts = page.locator('script').all_inner_texts()
        for script in scripts:
            values = structured_jpy_prices(script)
            if values:
                return values[0]
        body = normalize(page.locator("body").inner_text())
        values = money_values(body)
        return values[0] if values else None
    except Exception as exc:
        print("detail price error:", repr(exc))
        return None


def browser_lookup(page, query, debug=False):
    url = "https://jp.mercari.com/search?" + urllib.parse.urlencode({
        "keyword": query,
        "status": "sold_out|trading",
    })
    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
    page.wait_for_timeout(WAIT_AFTER_LOAD_MS)

    region_changed = ensure_japan_region(page)
    if region_changed:
        # Region selection can redraw the search page, so wait before collecting DOM.
        page.wait_for_timeout(1000)

    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(WAIT_AFTER_SCROLL_MS)

    anchor_count = page.locator('a[href*="/item/"]').count()
    if debug:
        body = normalize(page.locator("body").inner_text())
        DEBUG_TEXT.write_text(
            f"URL={page.url}\nTITLE={page.title()}\nREGION_CHANGED={region_changed}\nITEM_ANCHORS={anchor_count}\nBODY={body[:12000]}",
            encoding="utf-8",
        )
        page.screenshot(path=str(DEBUG_SCREENSHOT), full_page=False)
        print("Mercari debug:", page.url, page.title(), "item anchors=", anchor_count, "region_changed=", region_changed)
        print("Mercari body preview:", body[:1000])

    raw_items = collect_dom_items(page)
    rows = []
    seen = set()
    for raw in raw_items[:120]:
        href = raw.get("href", "")
        if not href or href in seen:
            continue
        text = normalize(raw.get("text", ""))
        if not text or looks_like_auction(text) or not looks_sold(text):
            continue
        seen.add(href)
        prices = money_values(text)
        if not prices:
            try:
                anchor_text = normalize(page.locator(f'a[href="{href}"]').first.inner_text())
                if not looks_like_auction(anchor_text):
                    prices = money_values(anchor_text)
            except Exception:
                pass
        if not prices:
            price = detail_jpy_price(page, href)
            if price:
                prices = [price]
        if prices:
            rows.append({"url": href, "title": text[:500], "price": prices[0], "auction": False, "sold": True})
        if len(rows) >= 20:
            break

    prices = sorted(x["price"] for x in rows)
    if not prices:
        return {
            "query": query, "url": url, "count": 0, "prices": [], "items": [],
            "anchor_count": anchor_count, "auction_excluded": True, "sold_only_enforced": True,
            "region_changed": region_changed,
        }
    trimmed = prices[1:-1] if len(prices) >= 5 else prices
    return {
        "query": query, "url": url, "count": len(prices), "prices": prices,
        "median": int(statistics.median(prices)), "robust_median": int(statistics.median(trimmed)),
        "low": min(prices), "high": max(prices), "items": rows[:10],
        "anchor_count": anchor_count, "auction_excluded": True, "sold_only_enforced": True,
        "region_changed": region_changed,
    }


def fallback_sold_keyword_lookup(page, query):
    all_rows = []
    for extra in ["売り切れ", "sold out"]:
        q = f"{query} {extra}"
        url = "https://jp.mercari.com/search?" + urllib.parse.urlencode({"keyword": q})
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            page.wait_for_timeout(WAIT_AFTER_LOAD_MS)
            ensure_japan_region(page)
            raw_items = collect_dom_items(page)
            for raw in raw_items[:80]:
                text = normalize(raw.get("text", ""))
                if not text or looks_like_auction(text) or not looks_sold(text):
                    continue
                prices = money_values(text)
                if prices:
                    all_rows.append({"url": raw.get("href", ""), "title": text[:500], "price": prices[0], "auction": False, "sold": True})
        except Exception as exc:
            print("fallback error:", repr(exc))
            continue
    unique = {row["url"]: row for row in all_rows if row.get("url")}
    rows = list(unique.values())[:20]
    prices = sorted(x["price"] for x in rows)
    if not prices:
        return {"count": 0, "prices": [], "items": [], "fallback": True, "auction_excluded": True, "sold_only_enforced": True}
    trimmed = prices[1:-1] if len(prices) >= 5 else prices
    return {
        "count": len(prices), "prices": prices,
        "median": int(statistics.median(prices)), "robust_median": int(statistics.median(trimmed)),
        "low": min(prices), "high": max(prices), "items": rows[:10],
        "fallback": True, "auction_excluded": True, "sold_only_enforced": True,
    }


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("playwright is required")

    data = json.loads(INPUT.read_text(encoding="utf-8"))
    candidates = data.get("candidates", [])
    checked = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            geolocation={"latitude": 35.6895, "longitude": 139.6917},
            permissions=["geolocation"],
            extra_http_headers={"Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8"},
            viewport={"width": 1440, "height": 1000},
        )
        page = context.new_page()
        for index, item in enumerate(candidates[:MAX_CHECKS]):
            title = normalize(item.get("title", ""))
            if not title:
                continue
            brands = item.get("brands") or []
            brand = brands[0].get("name", "") if brands else ""
            query = " ".join(x for x in [brand, title] if x)
            try:
                result = browser_lookup(page, query, debug=(index == 0))
                if result.get("count", 0) == 0:
                    fallback = fallback_sold_keyword_lookup(page, query)
                    if fallback.get("count", 0) > 0:
                        result.update(fallback)
                        result["fallback_used"] = True
            except Exception as exc:
                result = {"query": query, "url": "", "count": 0, "prices": [], "items": [], "error": repr(exc)}
            best_similarity = 0
            for row in result.get("items", []):
                row["similarity"] = score_similarity(title, row.get("title", ""))
                best_similarity = max(best_similarity, row["similarity"])
            result.update({
                "best_similarity": best_similarity,
                "source_url": item.get("url"),
                "source_title": title,
                "purchase_price": item.get("price", 0),
            })
            checked.append(result)
            print("メルカリ相場", title, "件数=", result.get("count", 0), "中央値=", result.get("robust_median"), "一致度=", best_similarity, "fallback=", result.get("fallback_used", False))
            time.sleep(0.5)
        context.close()
        browser.close()

    OUTPUT.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "checked": checked,
        "note": "メルカリの地域選択が出た場合は日本を明示選択。売り切れバッジをDOM上で確認してsold-onlyを強制。オークション・入札系表示を除外。価格は日本円表示または商品詳細のJPY構造化データを優先し、USDを円として誤認しない。まず1件で疎通確認。",
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
