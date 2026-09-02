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
MAX_ITEMS = 40
MIN_PRICE = 300
MAX_PRICE = 2_000_000
TIMEOUT = 20000


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def jpy_prices(text):
    out = []
    for p in (r"(?:¥|￥)\s*([0-9,]+)", r"([0-9]{1,3}(?:,[0-9]{3})+)円", r"(?:^|\s)([0-9]{3,7})円"):
        for x in re.findall(p, text):
            try:
                n = int(x.replace(",", ""))
                if MIN_PRICE <= n <= MAX_PRICE:
                    out.append(n)
            except ValueError:
                pass
    return list(dict.fromkeys(out))


def price_obj(v):
    if isinstance(v, (int, float)):
        n = int(v)
        return n if MIN_PRICE <= n <= MAX_PRICE else None
    if isinstance(v, str):
        # API may encode JPY amount as a string such as "96000" or "96,000".
        s = v.strip().replace(",", "")
        if s.isdigit():
            n = int(s)
            return n if MIN_PRICE <= n <= MAX_PRICE else None
        vals = jpy_prices(v)
        return vals[0] if vals else None
    if isinstance(v, dict):
        for k in ("amount", "value", "price", "amountJPY", "priceJpy", "priceJPY"):
            if k in v:
                n = price_obj(v[k])
                if n is not None:
                    return n
    return None


def tokens(s):
    return set(re.findall(r"[a-z0-9][a-z0-9._-]{1,}|[ぁ-んァ-ヶ一-龥々ー]{2,}", norm(s).lower()))


def similarity(a, b):
    x, y = tokens(a), tokens(b)
    return int(100 * len(x & y) / max(1, len(x))) if x and y else 0


def sold_status(v):
    s = norm(v).upper()
    return s in {"SOLD", "SOLD_OUT", "SOLDOUT", "ITEM_STATUS_SOLD_OUT"} or "SOLD_OUT" in s


def parse_payload(payload, assume_sold=True):
    rows, samples, seen = [], [], set()
    def walk(o):
        if isinstance(o, dict):
            status = o.get("status") or o.get("itemStatus") or ""
            sold_flag = o.get("sold") is True or o.get("soldOut") is True
            item_id = norm(o.get("id") or o.get("itemId") or o.get("item_id") or "")
            price = price_obj(o.get("price"))
            if item_id and price and len(samples) < 15:
                samples.append({"id": item_id, "status": str(status), "soldOut": o.get("soldOut"), "price": price})
            is_sold = sold_flag or sold_status(status) or (assume_sold and item_id and price)
            if item_id and price and is_sold:
                title = norm(o.get("name") or o.get("title") or o.get("productName") or o.get("itemName") or "")
                key = (item_id, price)
                if key not in seen:
                    seen.add(key)
                    rows.append({"url": f"https://jp.mercari.com/item/{item_id}", "title": title, "price": price, "sold": True, "status": str(status), "price_source": "live_search_api_jpy"})
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(payload)
    return rows, samples


def clean_query(item):
    raw = norm(item.get("market_query") or item.get("jmty_detail_title") or item.get("title") or "")
    if not raw:
        return ""
    if "の中古あげます・譲ります" in raw:
        raw = raw.split("の中古あげます・譲ります", 1)[0]
    raw = re.sub(r"\s*\([^()]{1,40}\)(?=\s|$)", "", raw).strip()
    raw = re.sub(r"\s+[^\s]+の[^\s]+《[^》]+》$", "", raw).strip()
    return raw[:120]


def collect_dom(page):
    try:
        return page.locator('a[href*="/item/"]').evaluate_all("""
            els => els.map(a => ({href:a.href, text:(a.closest('li')||a.closest('[role=article]')||a.parentElement||a).innerText||''}))
        """)
    except Exception:
        return []


def browser_lookup(page, query, debug=False):
    url = "https://jp.mercari.com/search?" + urllib.parse.urlencode({"keyword": query, "status": "sold_out"})
    payloads, response_urls, request_urls = [], [], []
    def on_response(r):
        u = r.url
        if "mercari" in u.lower() and ("search" in u.lower() or "/v1/api/" in u.lower() or "/v2/" in u.lower()):
            response_urls.append(f"{r.status()} {u}")
            try:
                ct = r.headers.get("content-type", "")
                if "json" in ct or "/v1/api/" in u or "/v2/" in u or "entities:search" in u:
                    payloads.append(r.json())
            except Exception:
                pass
    def on_request(r):
        u = r.url
        if "mercari" in u.lower() and ("search" in u.lower() or "/v1/api/" in u.lower() or "/v2/" in u.lower()):
            request_urls.append(u)
    page.on("response", on_response)
    page.on("request", on_request)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT)
        time.sleep(3)
        try:
            page.locator('a[href*="/item/"]').first.wait_for(timeout=8000)
        except Exception:
            pass
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1.2)
        rows, samples = [], []
        for payload in payloads:
            r, s = parse_payload(payload, assume_sold=True)
            rows.extend(r); samples.extend(s)
        unique = {}
        for r in rows: unique[r["url"]] = r
        rows = list(unique.values())[:MAX_ITEMS]
        dom = collect_dom(page)
        if not rows:
            for d in dom[:MAX_ITEMS]:
                text = norm(d.get("text", ""))
                if "US$" in text or "USD" in text or "オークション" in text: continue
                prices = jpy_prices(text)
                if prices and ("売り切れ" in text or "SOLD" in text.upper()):
                    rows.append({"url":d.get("href"), "title":text[:500], "price":prices[0], "sold":True,"price_source":"dom_jpy"})
        if debug:
            body = norm(page.locator("body").inner_text())
            DEBUG_TEXT.write_text("URL=" + page.url + "\n" + f"PAYLOADS={len(payloads)}\nROWS={len(rows)}\nDOM={len(dom)}\nREQUEST_URLS={request_urls[-30:]}\nRESPONSE_URLS={response_urls[-30:]}\nSAMPLES={samples[:15]}\nBODY={body[:20000]}", encoding="utf-8")
            page.screenshot(path=str(DEBUG_SCREENSHOT), full_page=False)
        prices = sorted(r["price"] for r in rows if r.get("price"))
        return {"query":query,"url":url,"count":len(prices),"prices":prices,"median":int(statistics.median(prices)) if prices else None,"robust_median":int(statistics.median(prices)) if prices else None,"low":min(prices) if prices else None,"high":max(prices) if prices else None,"items":rows,"dom_count":len(dom),"api_payloads":len(payloads),"best_similarity":max([similarity(query,r.get("title","")) for r in rows]+[0]),"price_source":rows[0].get("price_source") if rows else None,"status_samples":samples[:15],"request_urls":request_urls[-10:],"response_urls":response_urls[-10:],"sold_only_enforced":True}
    finally:
        page.remove_listener("response", on_response)
        page.remove_listener("request", on_request)


def main():
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    checked = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="ja-JP", timezone_id="Asia/Tokyo", extra_http_headers={"Accept-Language":"ja-JP,ja;q=0.9,en;q=0.8"}, viewport={"width":1440,"height":1000})
        page = context.new_page()
        for index, item in enumerate(data.get("candidates", [])[:MAX_CHECKS]):
            query = clean_query(item)
            if not query: continue
            try: result = browser_lookup(page, query, debug=(index == 0))
            except Exception as exc: result = {"query":query,"count":0,"prices":[],"items":[],"error":repr(exc),"best_similarity":0}
            result.update({"source_url":item.get("url"),"source_title":norm(item.get("jmty_detail_title") or item.get("title") or ""),"purchase_price":item.get("price",0),"source_item_index":index})
            checked.append(result)
            print("メルカリ検索", result["source_title"], "query=", query, "価格=", result.get("prices"), "中央値=", result.get("median"), "source=", result.get("price_source"))
            time.sleep(0.2)
        context.close(); browser.close()
    OUTPUT.write_text(json.dumps({"generated_at":datetime.now().isoformat(timespec="seconds"),"checked":checked,"note":"Mercari sold_out browser search. Live search API/DOM JPY only; USD excluded."}, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
