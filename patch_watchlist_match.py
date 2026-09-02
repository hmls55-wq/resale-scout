from pathlib import Path

path = Path("watch_new_listings.py")
s = path.read_text(encoding="utf-8")
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
if old not in s:
    raise SystemExit("match_watchlist target not found")
s = s.replace(old, new, 1)
old2 = '''        text = " ".join([item.get("title", ""), item.get("text", "")])
        if STATUS_RE.search(text):
'''
new2 = '''        # Status must also be checked against the listing title only;
        # neighboring cards can contain an unrelated ended marker.
        text = str(item.get("title", ""))
        if STATUS_RE.search(text):
'''
if old2 not in s:
    raise SystemExit("main text target not found")
s = s.replace(old2, new2, 1)
path.write_text(s, encoding="utf-8")
print("Patched watch_new_listings.py: watchlist/status matching now uses title only")
