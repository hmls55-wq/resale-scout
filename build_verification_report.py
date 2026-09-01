import json
from pathlib import Path
from urllib.parse import quote

INPUT = Path("resell_candidates.json")
OUTPUT = Path("verification_report.md")


def mercari_search_url(query: str) -> str:
    return "https://jp.mercari.com/search?keyword=" + quote(query)


def money(value):
    return f"{value:,}円" if isinstance(value, int) else "要メルカリ相場確認"


def main():
    if not INPUT.exists():
        raise SystemExit("resell_candidates.json がありません")

    data = json.loads(INPUT.read_text(encoding="utf-8"))
    candidates = data.get("candidates", [])

    lines = [
        "# Resell Scout 仕入れ判定用レポート",
        "",
        f"実行時刻: {data.get('generated_at', '-')}",
        f"候補数: {len(candidates)}",
        "",
        "> 🔎 相場確認候補は、メルカリの検索結果を確認してから仕入れ判断します。",
        "> 現段階ではメルカリの売却済み履歴を自動取得して利益を断定していません。",
        "",
    ]

    for i, item in enumerate(candidates[:30], 1):
        title = item.get("title", "-")
        brands = ", ".join(x.get("name", "") for x in item.get("brands", []))
        keywords = item.get("keywords", [])
        query_parts = []
        if brands:
            query_parts.append(brands.split(",")[0])
        # ブランドがない一般家具はタイトルを優先して検索
        query_parts.append(title)
        if keywords and len(query_parts) < 2:
            query_parts.append(keywords[0])
        query = " ".join(dict.fromkeys(x for x in query_parts if x))

        lines += [
            f"## {i}. {item.get('urgency', '')} {title}",
            f"- 仕入れ価格: {item.get('price', 0):,}円",
            f"- 利益推定: {money(item.get('estimated_profit'))}",
            f"- 判定理由: {item.get('reason', '-')}",
            f"- スコア: {item.get('score', 0)}",
            f"- 検索キーワード: `{query}`",
            f"- [メルカリで検索]({mercari_search_url(query)})",
            f"- [ジモティー商品]({item.get('url', '#')})",
            "- 判定: **メルカリ相場・送料・状態を確認 → 仕入れ判断**",
            "",
        ]

    OUTPUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
