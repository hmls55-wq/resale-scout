from pathlib import Path

p = Path('mercari_market.py')
s = p.read_text(encoding='utf-8')
needle = '''    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)\n    page.wait_for_timeout(WAIT_AFTER_LOAD_MS)\n'''
replacement = '''    api_responses = []\n\n    def capture_response(response):\n        if "api.mercari.jp/v2/entities:search" in response.url:\n            api_responses.append(response)\n\n    page.on("response", capture_response)\n    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)\n    page.wait_for_timeout(WAIT_AFTER_LOAD_MS)\n'''
if needle not in s:
    raise SystemExit('browser load block not found')
s = s.replace(needle, replacement, 1)
needle2 = '''    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")\n    page.wait_for_timeout(WAIT_AFTER_SCROLL_MS)\n\n    dom_items = collect_dom_items(page)\n'''
replacement2 = '''    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")\n    page.wait_for_timeout(WAIT_AFTER_SCROLL_MS)\n\n    if api_responses:\n        try:\n            payload = api_responses[-1].json()\n            print("MERCARI_API_RESPONSE_COUNT=", len(api_responses))\n            print("MERCARI_API_KEYS=", list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__)\n            print("MERCARI_API_SAMPLE=", json.dumps(payload, ensure_ascii=False)[:5000])\n        except Exception as exc:\n            print("MERCARI_API_CAPTURE_ERROR=", repr(exc))\n    else:\n        print("MERCARI_API_RESPONSE_COUNT= 0")\n\n    dom_items = collect_dom_items(page)\n'''
if needle2 not in s:
    raise SystemExit('scroll block not found')
s = s.replace(needle2, replacement2, 1)
p.write_text(s, encoding='utf-8')
print('patched mercari_market.py for API debug')
