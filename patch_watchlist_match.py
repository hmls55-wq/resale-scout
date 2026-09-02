from pathlib import Path

watch_path = Path("watch_new_listings.py")
s = watch_path.read_text(encoding="utf-8")

# 1) Match only the listing title.
old = '''def match_watchlist(item, entries):
    original_text = " ".join([item.get("title", ""), item.get("text", "")])
    compact_text = norm(original_text)
'''
new = '''def match_watchlist(item, entries):
    # IMPORTANT: item["text"] is a wide HTML neighborhood around the card and
    # can contain text from other listings/UI. Match watchlist terms against
    # this listing's title only.
    original_text = str(item.get("title", ""))
    compact_text = norm(original_text)
'''
if old in s:
    s = s.replace(old, new, 1)

# 2) Status only from the listing title.
old2 = '''        text = " ".join([item.get("title", ""), item.get("text", "")])
        if STATUS_RE.search(text):
'''
new2 = '''        # Status must also be checked against the listing title only.
        text = str(item.get("title", ""))
        if STATUS_RE.search(text):
'''
if old2 in s:
    s = s.replace(old2, new2, 1)

# 3) Prefer the actual heading inside a Jimoty article card as its title.
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
old4 = '''        title = anchor["text"] or normalize(anchor["title_attr"])
'''
new4 = '''        title = anchor.get("title") or anchor.get("heading") or normalize(anchor["title_attr"]) or anchor["text"]
'''
if old4 in sc:
    sc = sc.replace(old4, new4, 1)
scout_path.write_text(sc, encoding="utf-8")

# 4) Temporary source-coverage probe: Jimoty's normal keyword result pages are
# visibly different from the radius portal. Probe the two listings we already
# know should be discoverable, using the same 100km parameter, and feed any
# genuine title matches into the normal notification pipeline.
probe = r'''

def probe_keyword_pages(entries):
    probe_terms = ["CarlHansen", "Panton Chair", "パントンチェア"]
    out = []
    for term in probe_terms:
        slug = urllib.parse.quote(term, safe="")
        url = f"https://jmty.jp/aichi/sale-kw-{slug}?distance=100"
        print("Keyword probe:", url)
        try:
            html = fetch_area_page(url)
            parsed = scout.extract_items(html)
            print(f"  keyword parsed={len(parsed)}")
            for item in parsed:
                hits = match_watchlist(item, entries)
                if not hits:
                    continue
                title = str(item.get("title", ""))
                if STATUS_RE.search(title):
                    continue
                item["watch_hits"] = hits
                item["location"] = detect_location(item.get("text", ""))
                item["distance_km"] = 100
                item["keyword_probe"] = term
                out.append(item)
                print(f"  KEYWORD MATCH: {title[:120]} / {item.get('price', 0):,}円 / {item.get('url')}")
        except Exception as e:
            print("Keyword probe failed:", repr(e))
    return out
'''
marker = '\ndef main():\n'
if 'def probe_keyword_pages(entries):' not in s:
    if marker not in s:
        raise SystemExit("main marker not found")
    s = s.replace(marker, probe + marker, 1)
old5 = '''            all_items.extend(parsed)
            all_items.extend(rescued)
        except Exception as e:
'''
new5 = '''            all_items.extend(parsed)
            all_items.extend(rescued)
        except Exception as e:
'''
# Keep the existing page loop unchanged; inject the probe after the loop.
needle = '''            print("Fetch failed:", repr(e))

    unique = {item["url"]: item for item in all_items}
'''
replacement = '''            print("Fetch failed:", repr(e))

    all_items.extend(probe_keyword_pages(entries))
    unique = {item["url"]: item for item in all_items}
'''
if needle not in s:
    raise SystemExit("post-loop injection target not found")
s = s.replace(needle, replacement, 1)
watch_path.write_text(s, encoding="utf-8")
print("Patched watcher: title-only matching + keyword source probe enabled")
