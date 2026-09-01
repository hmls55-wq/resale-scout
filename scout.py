import json
import re
import time
import urllib.request
import urllib.parse
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

MAX_DISTANCE_KM = 25
MIN_PROFIT = 5_000
HIGH_PROFIT = 15_000
MARKET_CHECK_MAX_PRICE = 5_000
SEARCH_URLS = [
    "https://jmty.jp/aichi/sale-fur",
    "https://jmty.jp/aichi/sale-fur/g-all/a-459-nagoya",
]
MAX_LENGTH_CM = 180
MAX_WIDTH_CM = 100
MAX_HEIGHT_CM = 100

PRIORITY_BRANDS = {
    "最優先": ["アーコール", "ercol", "ルイスポールセン", "louis poulsen", "イームズ", "eames", "artek", "アルテック", "g-plan", "ジープラン", "カリモク", "karimoku", "飛騨産業", "hida sangyo", "ton", "thonet", "kartell", "flos", "artemide", "nathan", "ネイサン", "ヤマギワ", "ウェグナー", "wegner", "カイ・クリスチャンセン"],
    "照明": ["le klint", "leklint", "ヤコブソンランプ", "jakobsson lamp", "foscarini", "フォスカリーニ", "nemo", "luceplan", "インゴ・マウラー", "tom dixon", "verpan", "vibia", "marset", "&tradition", "muuto"],
    "高優先": ["マルニ", "maruni", "天童木工", "tendo", "無印良品", "muji", "cassina", "カッシーナ", "vitra", "ヴィトラ", "string", "ストリング", "magis", "マジス"],
}
MARKET_KEYWORDS = ["椅子", "イス", "チェア", "スツール", "ベンチ", "ソファ", "テーブル", "机", "デスク", "ダイニング", "食器棚", "キャビネット", "サイドボード", "チェスト", "タンス", "箪笥", "本棚", "書棚", "ラック", "シェルフ", "テレビ台", "収納家具", "収納", "ドレッサー", "鏡", "ミラー", "照明", "ライト", "ランプ", "ペンダント", "フロアライト", "木製", "無垢材", "無垢", "北欧", "ヴィンテージ", "ビンテージ", "アンティーク", "昭和レトロ", "レトロ", "デザイナーズ", "家具"]
KEYWORDS = MARKET_KEYWORDS + ["アーコール", "ercol", "ルイスポールセン", "louis poulsen", "イームズ", "eames", "カリモク", "karimoku", "飛騨産業", "hida sangyo", "ton", "thonet", "kartell", "flos", "artemide", "artek", "アルテック", "ジープラン", "g-plan", "nathan", "ネイサン", "ヤマギワ", "ウェグナー", "wegner", "モーエンセン", "クリスチャンセン", "スタルク", "le klint", "foscarini", "nemo", "luceplan", "tom dixon", "verpan", "vibia", "marset", "muuto"]


def fetch(url):
    uas = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.6 Safari/605.1.15"]
    last = None
    for i, ua in enumerate(uas, 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "ja,en-US;q=0.9,en;q=0.8", "Cache-Control": "no-cache", "Referer": "https://jmty.jp/"})
            with urllib.request.urlopen(req, timeout=30) as r:
                html = r.read().decode("utf-8", errors="ignore")
                print(f"  HTTP {r.status}, HTML {len(html):,} bytes")
                if len(html) < 5_000: raise RuntimeError(f"HTMLが短すぎます ({len(html)} bytes)")
                return html
        except Exception as e:
            last = e; print(f"  取得リトライ {i}: {e!r}"); time.sleep(2)
    raise RuntimeError(f"ジモティー取得失敗: {last!r}")


def normalize(text): return re.sub(r"\s+", " ", unescape(text or "")).strip()


def find_brands(text):
    low = text.lower(); out = []; seen = set()
    for priority, brands in PRIORITY_BRANDS.items():
        for brand in brands:
            if brand.lower() in low and brand.lower() not in seen:
                out.append({"name": brand, "priority": priority}); seen.add(brand.lower())
    return out


def keyword_match(text):
    low = text.lower(); return [k for k in KEYWORDS if k.lower() in low]


def extract_price(text):
    text = normalize(text); table = str.maketrans("０１２３４５６７８９", "0123456789")
    for pattern in [r"(?:¥|￥)\s*([0-9０-９][0-9０-９,，]*)", r"([0-9０-９][0-9０-９,，]*)\s*円", r"([0-9０-９]{1,3}(?:[,，][0-9０-９]{3})+)\s*円?"]:
        m = re.search(pattern, text)
        if m:
            try:
                p = int(m.group(1).translate(table).replace(",", "").replace("，", ""))
                if 0 <= p <= 2_000_000: return p
            except ValueError: pass
    if re.search(r"(?:^|\s)(?:無料|0円)(?:\s|$)", text): return 0
    return None


def extract_size(text):
    for pattern in [r"(\d{2,4}(?:\.\d+)?)\s*[×xX]\s*(\d{2,4}(?:\.\d+)?)\s*[×xX]\s*(\d{2,4}(?:\.\d+)?)", r"幅\s*(\d{2,4}).{0,20}?奥行(?:き)?\s*(\d{2,4}).{0,20}?高さ\s*(\d{2,4})"]:
        m = re.search(pattern, text, re.I)
        if m:
            a, b, c = map(float, m.groups()); return {"length": a, "width": b, "height": c}
    return None


def size_ok(size):
    if not size: return None
    v = sorted([size["length"], size["width"], size["height"]], reverse=True)
    return v[0] <= MAX_LENGTH_CM and v[1] <= MAX_WIDTH_CM and v[2] <= MAX_HEIGHT_CM


def estimate_sale_price(title, price, brands):
    t = title.lower()
    if any(x in t for x in ["アーコール", "ercol"]): return max(price * 5, 20_000)
    if any(x in t for x in ["flos", "artemide", "ルイスポールセン", "louis poulsen"]): return max(price * 4, 25_000)
    if any(x in t for x in ["カリモク", "karimoku"]): return max(price * 3, 12_000)
    if any(x in t for x in ["kartell", "artek", "イームズ", "eames"]): return max(price * 4, 15_000)
    if brands and brands[0]["priority"] in ["最優先", "照明"]: return max(price * 3, 10_000)
    return price * 2


def evaluate_item(title, price, text, url, image_urls=None):
    brands = find_brands(text); keywords = keyword_match(text); market_keywords = [k for k in keywords if k in MARKET_KEYWORDS]
    size = extract_size(text); size_result = size_ok(size)
    if size_result is False or (not brands and not keywords): return None
    estimated_sale = estimated_net = profit = None
    if brands:
        estimated_sale = estimate_sale_price(title, price, brands); estimated_net = int(estimated_sale * 0.90); profit = estimated_net - price
        if profit < MIN_PROFIT and price > MARKET_CHECK_MAX_PRICE: return None
        reason = "簡易相場推定で利益基準クリア" if profit >= MIN_PROFIT else "ブランド品・低仕入れ／メルカリ相場確認"
    else:
        if not market_keywords or price > MARKET_CHECK_MAX_PRICE: return None
        reason = "低価格家具／メルカリ相場確認"
    score = 0
    if brands: score += 60 if brands[0]["priority"] == "最優先" else 40 if brands[0]["priority"] == "照明" else 30
    score += min(len(keywords) * 5, 25); score += 20 if price == 0 else 15 if price <= 1000 else 10 if price <= MARKET_CHECK_MAX_PRICE else 0
    if isinstance(profit, int): score += 30 if profit >= HIGH_PROFIT else 15
    if size_result is None: score -= 5
    image_urls = image_urls or []
    return {"title": title[:120], "price": price, "estimated_sale_price": estimated_sale, "estimated_net_sale": estimated_net, "estimated_profit": profit, "brands": brands, "keywords": keywords, "size": size, "size_ok": size_result, "score": score, "urgency": "🔥 緊急" if isinstance(profit, int) and profit >= HIGH_PROFIT else "🔎 相場確認", "reason": reason, "url": url, "image_urls": image_urls, "mercari_search_url": "https://jp.mercari.com/search?keyword=" + urllib.parse.quote(title[:80]), "google_lens_url": "https://lens.google.com/uploadbyurl?url=" + urllib.parse.quote(image_urls[0], safe="") if image_urls else None}


class JmtyAnchorParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.items = []; self.current = None; self.in_anchor = False; self.anchor_depth = 0
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs); href = attrs.get("href", "")
        if tag.lower() == "a" and "article-" in href:
            self.current = {"href": href, "title_attr": attrs.get("aria-label") or attrs.get("title") or "", "text": [], "images": []}; self.in_anchor = True; self.anchor_depth = 1; return
        if self.in_anchor:
            self.anchor_depth += 1
            if tag.lower() == "img":
                src = attrs.get("src") or attrs.get("data-src") or attrs.get("data-lazy-src")
                if src: self.current["images"].append(src)
    def handle_endtag(self, tag):
        if self.in_anchor:
            if tag.lower() == "a":
                self.anchor_depth -= 1
                if self.anchor_depth <= 0:
                    self.current["text"] = normalize(" ".join(self.current["text"])); self.items.append(self.current); self.current = None; self.in_anchor = False
            else: self.anchor_depth = max(1, self.anchor_depth - 1)
    def handle_data(self, data):
        if self.in_anchor and self.current is not None:
            text = normalize(data)
            if text: self.current["text"].append(text)


def extract_items(html):
    html = unescape(html); parser = JmtyAnchorParser(); parser.feed(html); anchors = parser.items
    print("  商品リンク候補:", len(anchors)); items = []; seen = set()
    for anchor in anchors:
        href = anchor["href"]; url = "https://jmty.jp" + href if href.startswith("/") else href if href.startswith("http") else None
        if not url: continue
        url = url.split("#", 1)[0]
        if url in seen: continue
        seen.add(url); pos = html.find(href); start = max(0, pos - 700); end = min(len(html), pos + 3000); block = html[start:end]; clean = normalize(re.sub(r"<[^>]+>", " ", block))
        if re.search(r"受付終了|掲載終了|募集終了|取引終了", clean): continue
        price = extract_price(clean)
        if price is None: continue
        title = anchor["text"] or normalize(anchor["title_attr"])
        if not title or title.startswith("お気に入り"):
            title_candidates = re.findall(r"(?:^| )([^ ]{2,120}?)(?=\s+(?:[0-9０-９,，]+円|0円|無料))", clean); title = title_candidates[0].strip() if title_candidates else ""
        if not title: title = url.rsplit("/", 1)[-1]
        image_urls = []
        for src in anchor.get("images", []):
            if src.startswith("//"): src = "https:" + src
            elif src.startswith("/"): src = "https://jmty.jp" + src
            if src.startswith("http") and src not in image_urls: image_urls.append(src)
        items.append({"title": title, "price": price, "url": url, "text": clean, "image_urls": image_urls[:5]})
        if len(items) >= 300: break
    return items


def sort_key(item):
    profit = item.get("estimated_profit"); return (-item.get("score", 0), -(profit if isinstance(profit, int) else -1), item.get("price", 0))


def write_reports(candidates, total_items):
    candidates = sorted(candidates, key=sort_key); data = {"generated_at": datetime.now().isoformat(timespec="seconds"), "settings": {"max_distance_km": MAX_DISTANCE_KM, "min_profit": MIN_PROFIT, "high_profit": HIGH_PROFIT, "market_check_max_price": MARKET_CHECK_MAX_PRICE}, "source_items": total_items, "candidates": candidates}
    Path("resell_candidates.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Resell Scout 候補レポート", "", f"実行時刻: {data['generated_at']}", f"一覧から取得: {total_items}", f"候補数: {len(candidates)}", "", "> 🔎 相場確認候補は利益を断定せず、メルカリ確認が必要です。", ""]
    for i, item in enumerate(candidates[:30], 1):
        sale = item.get("estimated_sale_price"); profit = item.get("estimated_profit")
        lines += [f"## {i}. {item['urgency']} {item['title']}", f"- 仕入れ: {item['price']:,}円", f"- 売価推定: {sale:,}円" if isinstance(sale, int) else "- 売価推定: 要メルカリ相場確認", f"- 利益推定: {profit:,}円" if isinstance(profit, int) else "- 利益推定: 要メルカリ相場確認", f"- 判定理由: {item['reason']}", f"- スコア: {item['score']}", f"- メルカリ検索: {item.get('mercari_search_url')}", f"- Google Lens: {item.get('google_lens_url') or '画像URLなし'}", f"- 画像: {', '.join(item.get('image_urls', [])) or 'なし'}", f"- URL: {item['url']}", ""]
    Path("resell_report.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    print("========================================"); print("           Resell Scout"); print("========================================"); print("引き取り範囲:", MAX_DISTANCE_KM, "km"); print("最低利益:", f"{MIN_PROFIT:,}円"); print("相場確認対象の仕入れ上限:", f"{MARKET_CHECK_MAX_PRICE:,}円")
    candidates, total_items = [], 0
    for search_url in SEARCH_URLS:
        print("チェック:", search_url)
        try:
            html = fetch(search_url); items = extract_items(html); total_items += len(items); print("取得候補:", len(items))
            for item in items:
                result = evaluate_item(item["title"], item["price"], item["text"], item["url"], item.get("image_urls"))
                if result: candidates.append(result)
        except Exception as exc: print("取得失敗:", repr(exc))
    candidates = list({x["url"]: x for x in candidates}.values()); write_reports(candidates, total_items); print("一覧から取得:", total_items); print("利益/相場確認候補:", len(candidates))
    for item in sorted(candidates, key=sort_key)[:10]:
        p = item.get("estimated_profit"); print(item["urgency"], item["title"], f"仕入れ={item['price']:,}円", f"利益={p:,}円" if isinstance(p, int) else "利益=要相場確認", f"score={item['score']}")

if __name__ == "__main__": main()
