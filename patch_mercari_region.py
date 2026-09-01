from pathlib import Path

p = Path("mercari_market.py")
s = p.read_text(encoding="utf-8")

old = '''def ensure_japan_region(page):
    body = normalize(page.locator("body").inner_text())
    if "別の地域の商品を閲覧しています" not in body:
        return False
    try:
        selects = page.locator("select")
        for i in range(selects.count()):
            sel = selects.nth(i)
            try:
                if sel.locator('option[value="jp"]').count() == 0:
                    continue
                result = sel.evaluate("""
                    el => {
                        el.value='jp';
                        el.dispatchEvent(new Event('input',{bubbles:true}));
                        el.dispatchEvent(new Event('change',{bubbles:true}));
                        return el.value;
                    }
                """)
                if result == "jp":
                    page.wait_for_timeout(1000)
                    return True
            except Exception:
                continue
    except Exception as exc:
        print("region select error:", repr(exc))
    return False
'''

new = '''def ensure_japan_region(page):
    body = normalize(page.locator("body").inner_text())
    if "別の地域の商品を閲覧しています" not in body:
        return False

    # The previous implementation only changed the select value in the DOM.
    # Mercari's region modal requires the actual UI interaction to persist the
    # selection; otherwise search results can be rendered with US$ prices.
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

        for label in ["日本"]:
            try:
                loc = page.get_by_text(label, exact=True)
                if loc.count() > 0:
                    loc.last.click(timeout=1500)
                    break
            except Exception:
                pass

        try:
            cont = page.get_by_text("続ける", exact=True)
            if cont.count() > 0:
                cont.last.click(timeout=1500)
        except Exception:
            pass

        page.wait_for_timeout(1500)
        body_after = normalize(page.locator("body").inner_text())
        changed = "別の地域の商品を閲覧しています" not in body_after
        print("Mercari region dialog resolved:", changed)
        return changed
    except Exception as exc:
        print("region select error:", repr(exc))
    return False
'''

if old not in s:
    raise SystemExit("target region function not found")
s = s.replace(old, new, 1)
s = s.replace('"status": "sold_out",', '"status": "sold_out|trading",', 1)
p.write_text(s, encoding="utf-8")
print("patched mercari_market.py")
