from pathlib import Path

# Patch the watcher matcher so it uses only the listing title, never the wide
# HTML neighborhood stored in item["text"].
watch_path = Path("watch_new_listings.py")
s = watch_path.read_text(encoding="utf-8")
old = '''def match_watchlist(item, entries):
    original_text = " ".join([item.get("title", ""), item.get("text", "")])
    compact_text = norm(original_text)
'''
new = '''def match_watchlist(item, entries):
    # IMPORTANT: item["text"] is a wide HTML neighborhood around the card and
    # can contain text from other listings/UI (e.g. Tendo/Carl Hansen). Match
    # watchlist terms against this listing's title only.
    original_text = str(item.get("title", ""))
    compact_text = norm(original_text)
'''
if old in s:
    s = s.replace(old, new, 1)
old2 = '''        text = " ".join([item.get("title", ""), item.get("text", "")])
        if STATUS_RE.search(text):
'''
new2 = '''        # Status must also be checked against the listing title only;
        # neighboring cards can contain an unrelated ended marker.
        text = str(item.get("title", ""))
        if STATUS_RE.search(text):
'''
if old2 in s:
    s = s.replace(old2, new2, 1)
watch_path.write_text(s, encoding="utf-8")
print("Patched watch_new_listings.py: watchlist/status matching now uses title only")

# The Jimoty article <a> can wrap the entire card. Its raw anchor text is
# therefore NOT necessarily the product title. Prefer heading text inside the
# article anchor (the actual card title), then aria-label/title, then raw text.
scout_path = Path("scout.py")
s = scout_path.read_text(encoding="utf-8")
old = '''class JmtyAnchorParser(HTMLParser):
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
new = '''class JmtyAnchorParser(HTMLParser):
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
if old not in s:
    raise SystemExit("JmtyAnchorParser target not found")
s = s.replace(old, new, 1)
old2 = '''        title = anchor["text"] or normalize(anchor["title_attr"])
'''
new2 = '''        title = anchor.get("title") or anchor.get("heading") or normalize(anchor["title_attr"]) or anchor["text"]
'''
if old2 not in s:
    raise SystemExit("extract_items title target not found")
s = s.replace(old2, new2, 1)
scout_path.write_text(s, encoding="utf-8")
print("Patched scout.py: prefer actual heading text as listing title")
