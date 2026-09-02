import json
import re
from pathlib import Path

PATH = Path("resell_candidates.json")


def clean_market_query(title):
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    # Remove seller names in parentheses.
    title = re.sub(r"\s*\([^)]*\)\s*", " ", title)
    # Remove Jimoty area/category suffix such as: 平針のカメラ《デジタル一眼》...
    title = re.split(r"\s+の[^\n]{0,40}?《", title, maxsplit=1)[0]
    title = re.sub(r"(?:の中古あげます・譲ります|中古あげます・譲ります).*$", "", title)
    title = re.sub(r"\s+", " ", title).strip(" /|-")
    title = re.sub(r"^(?:無料で譲ります|【無料・引き取り限定】)\s*", "", title)
    return title[:120]


data = json.loads(PATH.read_text(encoding="utf-8"))
changed = 0
prepared = 0

for item in data.get("candidates", []):
    detail_title = str(item.get("jmty_detail_title") or "").strip()
    current_title = str(item.get("title") or "").strip()
    if detail_title and detail_title != current_title:
        item["title_before_detail_enrichment"] = current_title
        item["title"] = detail_title
        changed += 1
    query = clean_market_query(detail_title or current_title)
    if query:
        item["market_query"] = query
        prepared += 1

PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"market query titles normalized: {changed}")
print(f"market queries prepared: {prepared}")
