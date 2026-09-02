from pathlib import Path

watch_path = Path("watch_new_listings.py")
s = watch_path.read_text(encoding="utf-8")
old = '''def match_watchlist(item, entries):
    original_text = " ".join([item.get("title", ""), item.get("text", "")])
    compact_text = norm(original_text)
'''
new = '''def match_watchlist(item, entries):
    original_text = str(item.get("title", ""))
    compact_text = norm(original_text)
'''
if old in s:
    s = s.replace(old, new, 1)
old2 = '''        text = " ".join([item.get("title", ""), item.get("text", "")])
        if STATUS_RE.search(text):
'''
new2 = '''        text = str(item.get("title", ""))
        if STATUS_RE.search(text):
'''
if old2 in s:
    s = s.replace(old2, new2, 1)

scout_path = Path("scout.py")
sc = scout_path.read_text(encoding="utf-8")
old3 = '''class JmtyAnchorParser(HTMLParser):
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
'''
new3 = '''class JmtyAnchorParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.items = []; self.current = None; self.in_anchor = False; self.anchor_depth = 0; self.in_heading = False
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs); href = attrs.get("href", ""); tag = tag.lower()
        if tag == "a" and "article-" in href:
            self.current = {"href": href, "title_attr": attrs.get("aria-label") or attrs.get("title") or "", "text": [], "heading": [], "images": []}; self.in_anchor = True; self.anchor_depth = 1; self.in_heading = False; return
        if self.in_anchor:
            self.anchor_depth += 1
            if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                self.in_heading = True
            if tag == "img":
                src = attrs.get("src") or attrs.get("data-src") or attrs.get("data-lazy-src")
                if src: self.current["images"].append(src)
    def handle_endtag(self, tag):
        if self.in_anchor:
            tag = tag.lower()
            if tag == "a":
                self.anchor_depth -= 1
                if self.anchor_depth <= 0:
                    self.current["text"] = normalize(" ".join(self.current["text"]))
                    self.current["heading"] = normalize(" ".join(self.current["heading"]))
                    self.current["title"] = self.current["heading"] or normalize(self.current["title_attr"]) or self.current["text"]
                    self.items.append(self.current); self.current = None; self.in_anchor = False; self.in_heading = False
            else:
                if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                    self.in_heading = False
                self.anchor_depth = max(1, self.anchor_depth - 1)
    def handle_data(self, data):
        if self.in_anchor and self.current is not None:
            text = normalize(data)
            if text:
                self.current["text"].append(text)
                if self.in_heading:
                    self.current["heading"].append(text)
'''
if old3 in sc:
    sc = sc.replace(old3, new3, 1)
old_init = '''        seen.add(url); pos = html.find(href); start = max(0, pos - 700); end = min(len(html), pos + 3000); block = html[start:end]; clean = normalize(re.sub(r"<[^>]+>", " ", block))
'''
new_init = '''        seen.add(url); pos = html.find(href); start = max(0, pos - 700); end = min(len(html), pos + 3000); block = html[start:end]; clean = normalize(re.sub(r"<[^>]+>", " ", block)); card_text = anchor.get("text") or normalize(anchor.get("title_attr"))
'''
if old_init in sc:
    sc = sc.replace(old_init, new_init, 1)
old5 = '''        if re.search(r"受付終了|掲載終了|募集終了|取引終了", clean): continue
        price = extract_price(clean)
'''
new5 = '''        if re.search(r"受付終了|掲載終了|募集終了|取引終了|終了しました|終了済み", card_text): continue
        price = extract_price(card_text)
        if price is None:
            price = extract_price(clean)
'''
if old5 in sc:
    sc = sc.replace(old5, new5, 1)
old4 = '''        title = anchor["text"] or normalize(anchor["title_attr"])
'''
new4 = '''        title = anchor.get("title") or anchor.get("heading") or normalize(anchor.get("title_attr")) or anchor.get("text") or url.rsplit("/", 1)[-1]
'''
if old4 in sc:
    sc = sc.replace(old4, new4, 1)
scout_path.write_text(sc, encoding="utf-8")

probe = r'''

def probe_keyword_pages(entries):
    """Probe Jimoty keyword pages and keep only recent, active, clean cards."""
    probe_terms = ["カールハンセン", "パントンチェア"]
    today = datetime.now().date()
    cutoff = today - __import__("datetime").timedelta(days=1)
    out = []
    for term in probe_terms:
        slug = urllib.parse.quote(term, safe="")
        url = f"https://jmty.jp/aichi/sale-kw-{slug}?distance=100"
        print("Keyword probe:", url)
        try:
            html = fetch_area_page(url)
            parser = scout.JmtyAnchorParser()
            parser.feed(html)
            print(f"  商品リンク候補: {len(parser.items)}")

            candidates = {}
            for anchor in parser.items:
                href = anchor.get("href", "")
                item_url = "https://jmty.jp" + href if href.startswith("/") else href
                item_url = item_url.split("#", 1)[0]
                if not item_url:
                    continue
                title = anchor.get("title") or anchor.get("heading") or normalize(anchor.get("title_attr")) or anchor.get("text") or ""
                # Strip Jimoty's UI text that sometimes sits inside the same
                # anchor after the actual listing title.
                title = re.split(r"お気に入りに登録しました|お気に入り一覧|ログインが必要です", title)[0].strip()
                if not title:
                    continue
                hits = match_watchlist({"title": title}, entries)
                if not hits:
                    continue
                score = 0
                if re.search(r"\d{1,2}月\d{1,2}日", title):
                    score += 4
                if scout.extract_price(title) is not None:
                    score += 3
                if any(norm(h.get("matched", "")) in norm(title) for h in hits):
                    score += 2
                score -= len(title) / 10000.0
                old = candidates.get(item_url)
                if old is None or score > old[0]:
                    candidates[item_url] = (score, anchor, title, hits, href)

            all_positions = []
            for anchor in parser.items:
                href = anchor.get("href", "")
                p = html.find(href)
                if p >= 0:
                    all_positions.append((p, href))
            all_positions.sort()
            first_pos_by_href = {}
            for p, href in all_positions:
                first_pos_by_href.setdefault(href, p)

            for item_url, (_score, anchor, title, hits, href) in candidates.items():
                pos = first_pos_by_href.get(href, html.find(href))
                if pos < 0:
                    continue
                prev_positions = [p for p, _ in all_positions if p < pos]
                start = prev_positions[-1] if prev_positions else max(0, pos - 1000)
                local_block = html[start:min(len(html), pos + 700)]
                local_text = re.sub(r"<[^>]+>", " ", local_block)
                local_text = re.sub(r"\s+", " ", local_text).strip()

                if STATUS_RE.search(title) or STATUS_RE.search(local_text):
                    print(f"  KEYWORD ENDED SKIP: {title[:120]}")
                    continue

                date_match = re.search(r"(\d{1,2})月(\d{1,2})日", title)
                if not date_match:
                    date_match = re.search(r"(\d{1,2})月(\d{1,2})日", local_text)
                if not date_match:
                    continue
                try:
                    md = datetime.strptime(f"{today.year}-{int(date_match.group(1)):02d}-{int(date_match.group(2)):02d}", "%Y-%m-%d").date()
                except ValueError:
                    continue
                if md > today:
                    md = datetime.strptime(f"{today.year-1}-{int(date_match.group(1)):02d}-{int(date_match.group(2)):02d}", "%Y-%m-%d").date()
                if md < cutoff:
                    continue

                price = scout.extract_price(title)
                if price is None:
                    price = scout.extract_price(local_text)
                if price is None:
                    continue

                image_urls = []
                for src in anchor.get("images", []):
                    if src.startswith("//"):
                        src = "https:" + src
                    elif src.startswith("/"):
                        src = "https://jmty.jp" + src
                    if src.startswith("http") and src not in image_urls:
                        image_urls.append(src)
                item = {
                    "title": title[:240], "price": price, "url": item_url,
                    "text": local_text or title, "image_urls": image_urls[:5],
                    "watch_hits": hits, "location": detect_location(title),
                    "distance_km": 100, "keyword_probe": term,
                }
                out.append(item)
                print(f"  KEYWORD RECENT MATCH: {title[:120]} / {price:,}円 / {item_url}")
        except Exception as e:
            print("Keyword probe failed:", repr(e))
    return out
'''
start = s.find("\ndef probe_keyword_pages(entries):")
if start >= 0:
    end = s.find("\ndef main():", start)
    if end < 0:
        raise SystemExit("existing probe main marker not found")
    s = s[:start] + probe + s[end:]
else:
    marker = "\ndef main():\n"
    if marker not in s:
        raise SystemExit("main marker not found")
    s = s.replace(marker, probe + marker, 1)

needle = '''            print("Fetch failed:", repr(e))\n\n    unique = {item["url"]: item for item in all_items}\n'''
replacement = '''            print("Fetch failed:", repr(e))\n\n    all_items.extend(probe_keyword_pages(entries))\n    unique = {item["url"]: item for item in all_items}\n'''
if needle in s:
    s = s.replace(needle, replacement, 1)

watch_path.write_text(s, encoding="utf-8")
print("Patched watcher: clean keyword titles, title-only matching, card-local status, 2-day probe")
