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
MAX_CHECKS = 5
MAX_DETAIL_ITEMS = 5
MIN_PRICE = 300
MAX_PRICE = 2_000_000
PAGE_TIMEOUT_MS = 25000
WAIT_AFTER_LOAD_MS = 1200
WAIT_AFTER_SCROLL_MS = 500

def normalize(s): return re.sub(r"\s+", " ", str(s or "")).strip()

def money_values(text):
    values=[]
    for pattern in [r"(?:¥|￥)\s*([0-9,]+)",r"([0-9]{1,3}(?:,[0-9]{3})+)円",r"(?:^|\s)([0-9]{3,7})円"]:
        for value in re.findall(pattern,text):
            try:
                v=int(value.replace(",",""))
                if MIN_PRICE<=v<=MAX_PRICE: values.append(v)
            except ValueError: pass
    return values

def structured_jpy_prices(text):
    values=[]
    for pattern in [r'"priceCurrency"\s*:\s*"JPY".{0,1500}?"price"\s*:\s*([0-9]+(?:\.[0-9]+)?)',r'"price"\s*:\s*([0-9]+(?:\.[0-9]+)?).{0,1500}?"priceCurrency"\s*:\s*"JPY"',r'"currency"\s*:\s*"JPY".{0,1500}?"(?:amount|price|value)"\s*:\s*([0-9]+(?:\.[0-9]+)?)',r'"(?:amount|price|value)"\s*:\s*([0-9]+(?:\.[0-9]+)?).{0,1500}?"currency"\s*:\s*"JPY"']:
        for match in re.finditer(pattern,text,re.S):
            try:
                v=int(float(match.group(1)))
                if MIN_PRICE<=v<=MAX_PRICE: values.append(v)
            except ValueError: pass
    return list(dict.fromkeys(values))

def tokens(s):
    s=normalize(s).lower(); out=re.findall(r"[a-z0-9][a-z0-9._-]{1,}|[ぁ-んァ-ヶ一-龥々ー]{2,}",s)
    return {x for x in out if x not in {"中古","美品","送料無料","即購入","匿名配送","送料込み","ジャンク","セット","商品"}}

def score_similarity(source_title,candidate_title):
    a=tokens(source_title); b=tokens(candidate_title)
    if not a or not b:return 0
    overlap=len(a&b)/max(1,len(a)); model_hits=sum(1 for x in a&b if re.search(r"[a-z0-9]",x))
    return min(100,int(overlap*75+min(model_hits,5)*5))

def looks_like_auction(text):
    t=normalize(text).lower()
    return any(x in t for x in ["オークション","入札","入札件数","入札履歴","開始価格","現在価格","最高額","落札","auction","bid","bids"])

def looks_sold(text):
    t=normalize(text).lower(); return any(x in t for x in ["売り切れ","sold out","soldout","取引完了","sold"])

def ensure_japan_region(page):
    body=normalize(page.locator("body").inner_text())
    if "別の地域の商品を閲覧しています" not in body:return False
    try:
        selects=page.locator("select")
        for i in range(selects.count()):
            sel=selects.nth(i)
            if sel.locator('option[value="jp"]').count()>0:
                sel.select_option("jp"); page.wait_for_timeout(600); page.reload(wait_until="domcontentloaded",timeout=PAGE_TIMEOUT_MS); page.wait_for_timeout(700); return True
    except Exception as exc: print("region select error:",repr(exc))
    return False

def collect_dom_items(page):
    return page.locator('a[href*="/item/"]').evaluate_all("""els => els.map(a => ({href:a.href,text:(a.closest('li')||a.closest('[role=\"article\"]')||a.parentElement||a).innerText||''}))""")

def detail_jpy_price(page,href):
    try:
        page.goto(href,wait_until="domcontentloaded",timeout=PAGE_TIMEOUT_MS); page.wait_for_timeout(500); ensure_japan_region(page)
        body=normalize(page.locator("body").inner_text())
        if looks_like_auction(body):return None
        for script in page.locator("script").all_inner_texts():
            values=structured_jpy_prices(script)
            if values and (looks_sold(body) or not any(x in body for x in ["購入手続きへ","購入する","販売中"])):return values[0]
        values=money_values(body)
        if values and (looks_sold(body) or not any(x in body for x in ["購入手続きへ","購入する","販売中"])):return values[0]
    except Exception as exc: print("detail price error:",repr(exc))
    return None

def browser_lookup(page,query,debug=False):
    url="https://jp.mercari.com/search?"+urllib.parse.urlencode({"keyword":query,"status":"sold_out"})
    page.goto(url,wait_until="domcontentloaded",timeout=PAGE_TIMEOUT_MS); page.wait_for_timeout(WAIT_AFTER_LOAD_MS); region_changed=ensure_japan_region(page)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)"); page.wait_for_timeout(WAIT_AFTER_SCROLL_MS); anchor_count=page.locator('a[href*="/item/"]').count()
    if debug:
        body=normalize(page.locator("body").inner_text()); DEBUG_TEXT.write_text(f"URL={page.url}\nREGION_CHANGED={region_changed}\nITEM_ANCHORS={anchor_count}\nBODY={body[:12000]}",encoding="utf-8"); page.screenshot(path=str(DEBUG_SCREENSHOT),full_page=False)
    rows=[]; seen=set()
    for raw in collect_dom_items(page)[:MAX_DETAIL_ITEMS]:
        href=raw.get("href",""); text=normalize(raw.get("text",""))
        if not href or href in seen or not text or looks_like_auction(text):continue
        seen.add(href); price=detail_jpy_price(page,href)
        if price:
            rows.append({"url":href,"title":text[:500],"price":price,"auction":False,"sold":True}); break
    prices=sorted(x["price"] for x in rows)
    if not prices:return {"query":query,"url":url,"count":0,"prices":[],"items":[],"anchor_count":anchor_count,"auction_excluded":True,"sold_only_enforced":True,"region_changed":region_changed}
    return {"query":query,"url":url,"count":1,"prices":prices,"median":prices[0],"robust_median":prices[0],"low":prices[0],"high":prices[0],"items":rows,"anchor_count":anchor_count,"auction_excluded":True,"sold_only_enforced":True,"region_changed":region_changed}

def main():
    from playwright.sync_api import sync_playwright
    data=json.loads(INPUT.read_text(encoding="utf-8")); candidates=data.get("candidates",[]); checked=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True); ctx=browser.new_context(locale="ja-JP",timezone_id="Asia/Tokyo",geolocation={"latitude":35.6895,"longitude":139.6917},permissions=["geolocation"],extra_http_headers={"Accept-Language":"ja-JP,ja;q=0.9,en;q=0.8"},viewport={"width":1440,"height":1000}); page=ctx.new_page()
        for index,item in enumerate(candidates[:MAX_CHECKS]):
            title=normalize(item.get("title",""));
            if not title:continue
            brands=item.get("brands") or []; brand=brands[0].get("name","") if brands else ""; query=" ".join(x for x in [brand,title] if x)
            try:result=browser_lookup(page,query,debug=(index==0))
            except Exception as exc:result={"query":query,"url":"","count":0,"prices":[],"items":[],"error":repr(exc)}
            best_similarity=max([score_similarity(title,row.get("title","")) for row in result.get("items",[])]+[0])
            result.update({"best_similarity":best_similarity,"source_url":item.get("url"),"source_title":title,"purchase_price":item.get("price",0)}); checked.append(result)
            print("メルカリ相場",title,"件数=",result.get("count",0),"中央値=",result.get("robust_median"),"一致度=",best_similarity); time.sleep(0.2)
        ctx.close(); browser.close()
    OUTPUT.write_text(json.dumps({"generated_at":datetime.now().isoformat(timespec="seconds"),"checked":checked,"note":"5候補を確認。各候補はメルカリ検索結果の最大5商品だけ詳細確認し、JPY価格を1件取得できた時点で終了。オークション除外、USDは円として扱わない。"},ensure_ascii=False,indent=2),encoding="utf-8")

if __name__ == "__main__":main()
