import json
import re
import time
import urllib.request
from html import unescape
from pathlib import Path

INPUT = Path('resell_candidates.json')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36',
    'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Cache-Control': 'no-cache',
    'Referer': 'https://jmty.jp/',
}


def clean_html(s):
    s = re.sub(r'<script[^>]*>.*?</script>', ' ', s, flags=re.I | re.S)
    s = re.sub(r'<style[^>]*>.*?</style>', ' ', s, flags=re.I | re.S)
    s = re.sub(r'<[^>]+>', ' ', s)
    return re.sub(r'\s+', ' ', unescape(s)).strip()


def meta(html, prop):
    m = re.search(r'<meta[^>]+(?:property|name)=["\']' + re.escape(prop) + r'["\'][^>]+content=["\']([^"\']*)', html, re.I)
    if m:
        return unescape(m.group(1)).strip()
    m = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']' + re.escape(prop) + r'["\']', html, re.I)
    return unescape(m.group(1)).strip() if m else ''


def clean_listing_title(raw, fallback):
    t = re.sub(r'\s+', ' ', raw or '').strip()
    t = re.sub(r'\s*[-|｜]\s*ジモティー.*$', '', t, flags=re.I).strip()
    t = re.split(r'\s*[（(][^）)]*[）)]', t, maxsplit=1)[0].strip()
    t = re.split(r'\s+[^\s]+の(?:収納家具|家具|寝具|家電|インテリア|雑貨|その他)《', t, maxsplit=1)[0].strip()
    t = re.sub(r'\s+中古あげます・譲ります.*$', '', t).strip()
    return (t or fallback or '').strip()[:160]


def title_from(html, fallback):
    og = meta(html, 'og:title')
    if og:
        title = clean_listing_title(og, fallback)
        if len(title) >= 3:
            return title
    m = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.S)
    if m:
        title = clean_listing_title(clean_html(m.group(1)), fallback)
        if len(title) >= 3:
            return title
    return fallback


def _num(s):
    return float(s.replace(',', ''))


def find_size(text):
    """Extract dimensions from Japanese prose in any label order.

    Handles forms such as:
      横幅:91cm 縦幅:90cm 奥行:40cm
      幅約46.5cm×奥行き約30cm×高さ約70cm
      91×40×90cm
    """
    text = text.replace('　', ' ')

    # 1) Explicit labels. Order is intentionally irrelevant.
    labels = {
        'length': r'(?:幅|横幅)',
        'width': r'(?:奥行(?:き)?)',
        'height': r'(?:高さ|縦幅)',
    }
    values = {}
    for name, label in labels.items():
        m = re.search(
            label + r'\s*(?:[:：=]|は)?\s*約?\s*(\d{1,4}(?:\.\d+)?)\s*(?:cm|センチ)?',
            text,
            re.I,
        )
        if m:
            values[name] = _num(m.group(1))
    if len(values) == 3:
        return values

    # 2) Three labeled values separated by ×, allowing labels on each value.
    m = re.search(
        r'(?:幅|横幅)\s*(?:[:：=]|は)?\s*約?\s*(\d{1,4}(?:\.\d+)?)\s*(?:cm|センチ)?\s*[×xX]\s*'
        r'(?:奥行(?:き)?)\s*(?:[:：=]|は)?\s*約?\s*(\d{1,4}(?:\.\d+)?)\s*(?:cm|センチ)?\s*[×xX]\s*'
        r'(?:高さ|縦幅)\s*(?:[:：=]|は)?\s*約?\s*(\d{1,4}(?:\.\d+)?)',
        text,
        re.I,
    )
    if m:
        return {'length': _num(m.group(1)), 'width': _num(m.group(2)), 'height': _num(m.group(3))}

    # 3) Unlabeled dimensions such as 91×40×90cm.
    m = re.search(
        r'(\d{2,4}(?:\.\d+)?)\s*[×xX]\s*(\d{2,4}(?:\.\d+)?)\s*[×xX]\s*(\d{2,4}(?:\.\d+)?)\s*(?:cm|センチ)?',
        text,
        re.I,
    )
    if m:
        a, b, c = map(_num, m.groups())
        return {'length': a, 'width': b, 'height': c}
    return None


def main():
    data = json.loads(INPUT.read_text(encoding='utf-8'))
    candidates = data.get('candidates', [])
    enriched = 0
    sizes_found = 0
    for item in candidates:
        url = item.get('url')
        if not url:
            continue
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                html = r.read().decode('utf-8', errors='ignore')
            title = title_from(html, item.get('title', ''))
            body = clean_html(html)
            size = find_size(body)
            image = meta(html, 'og:image')
            if title and len(title) >= 3:
                item['title'] = title
            item['jmty_detail_title'] = title
            item['jmty_description_excerpt'] = body[:1200]
            if size:
                item['size'] = size
                sizes_found += 1
            if image and image.startswith('http'):
                urls = item.get('image_urls') or []
                item['image_urls'] = list(dict.fromkeys([image] + urls))[:5]
            enriched += 1
        except Exception as exc:
            print('enrich error', url, repr(exc))
        time.sleep(0.15)
    data['enriched_jmty_details'] = enriched
    data['sizes_found'] = sizes_found
    INPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print('enriched Jimoty detail pages:', enriched, 'sizes found:', sizes_found)


if __name__ == '__main__':
    main()
