#!/usr/bin/env python
"""本地论文索引检索：按会议 / 年份 / 关键词 / 摘要内容过滤。

用法：
  python query.py --venue ICML --year 2025
  python query.py --keyword "expert merging"
  python query.py --keyword "quantization" --in-abstract    # 全文摘要搜索
  python query.py --venue NeurIPS --keyword MoE --json      # 输出 JSON
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.open(encoding="utf-8")]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--venue")
    ap.add_argument("--year", type=int)
    ap.add_argument("--keyword")
    ap.add_argument("--in-abstract", action="store_true")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--source", default="details,screened",
                    help="数据文件优先级（details 优先于 screened）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows: list[dict] = []
    seen: set[str] = set()
    for name in args.source.split(","):
        for row in load(DATA / f"{name.strip()}.jsonl"):
            key = row.get("url") or row["title"]
            if key not in seen:
                seen.add(key)
                rows.append(row)

    if args.venue:
        rows = [r for r in rows if r["venue"].lower() == args.venue.lower()]
    if args.year:
        rows = [r for r in rows if r.get("year") == args.year]
    if args.keyword:
        pat = re.compile(re.escape(args.keyword), re.I)
        if args.in_abstract:
            rows = [r for r in rows if pat.search(r.get("title", ""))
                    or pat.search(r.get("abstract", ""))]
        else:
            rows = [r for r in rows if pat.search(r.get("title", ""))]

    if not rows:
        sys.exit("无匹配结果（索引为空时先跑 crawl.py）")
    print(f"共 {len(rows)} 条，显示前 {min(args.limit, len(rows))}：\n")
    for r in rows[:args.limit]:
        if args.json:
            print(json.dumps(r, ensure_ascii=False))
        else:
            print(f"[{r['venue']} {r['year']}] {r['title']}")
            if r.get("abstract"):
                print(f"    摘要: {r['abstract'][:180]}…")
            if r.get("url"):
                print(f"    链接: {r['url']}")
            hits = r.get("keyword_hits")
            if hits:
                print(f"    命中: {', '.join(hits)}")
            print()


if __name__ == "__main__":
    main()
