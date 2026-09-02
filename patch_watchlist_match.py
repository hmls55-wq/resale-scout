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

if 'def probe_keyword_pages(entries):' not in s:
    probe = r'''

def probe_keyword_pages(entries):
    probe_terms = ["カールハンセン", "パントンチェア"]
    today = datetime.now().date()
    cutoff = today - __import__("datetime").timedelta(days=7)
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
            for anchor in parser.items:
                href = anchor.get("href", "")
                item_url = "https://jmty.jp" + href if href.startswith("/") else href
                if not item_url:
                    continue
                pos = html.find(href)
                if pos < 0:
                    continue
                # Jimoty places the status label just before the listing title.
                # Keep this window tight so a neighboring card cannot poison the result.
                status_block = html[max(0, pos - 1600):min(len(html), pos + 900)]
                status_text = re.sub(r"<[^>]+>", " ", status_block)
                status_text = re.sub(r"\s+", " ", status_text).strip()
                if STATUS_RE.search(status_text):
                    print(f"  KEYWORD ENDED SKIP: {anchor.get('title') or anchor.get('text','')[:100]}")
                    continue
                title = anchor.get("title") or anchor.get("heading") or anchor.get("title_attr") or anchor.get("text") or ""
                if not title or STATUS_RE.search(title):
                    continue
                hits = match_watchlist({"title": title}, entries)
                if not hits:
                    continue
                m = re.search(r"(\d{1,2})月(\d{1,2})日", status_text)
                if not m:
                    continue
                try:
                    md = datetime.strptime(f"{today.year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}", "%Y-%m-%d").date()
                except ValueError:
                    continue
                if md > today:
                    md = datetime.strptime(f"{today.year-1}-{int(m.group(1)):02d}-{int(m.group(2)):02d}", "%Y-%m-%d").date()
                if md < cutoff:
                    continue
                price = scout.extract_price(status_text)
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
                    "title": title[:240], "price": price, "url": item_url.split("#", 1)[0],
                    "text": status_text, "image_urls": image_urls[:5], "watch_hits": hits,
                    "location": detect_location(status_text), "distance_km": 100, "keyword_probe": term,
                }
                out.append(item)
                print(f"  KEYWORD RECENT MATCH: {title[:120]} / {price:,}円 / {item_url}")
        except Exception as e:
            print("Keyword probe failed:", repr(e))
    return out
'''
    marker = '\ndef main():\n'
    if marker not in s:
        raise SystemExit("main marker not found")
    s = s.replace(marker, probe + marker, 1)
needle = '''            print("Fetch failed:", repr(e))

    unique = {item["url"]: item for item in all_items}
'''
replacement = '''            print("Fetch failed:", repr(e))

    all_items.extend(probe_keyword_pages(entries))
    unique = {item["url"]: item for item in all_items}
'''
if needle in s:
    s = s.replace(needle, replacement, 1)
watch_path.write_text(s, encoding="utf-8")
print("Patched watcher: title-only matching, card-local status/price, recent keyword probe with ended-card exclusion")
