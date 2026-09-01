import json
from pathlib import Path

PATH = Path("resell_candidates.json")

data = json.loads(PATH.read_text(encoding="utf-8"))
changed = 0

for item in data.get("candidates", []):
    detail_title = str(item.get("jmty_detail_title") or "").strip()
    current_title = str(item.get("title") or "").strip()
    if detail_title and detail_title != current_title:
        item["title_before_detail_enrichment"] = current_title
        item["title"] = detail_title
        changed += 1

PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"market query titles normalized: {changed}")
