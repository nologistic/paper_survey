#!/usr/bin/env python
"""合并 HIGH 分级（grades_*.txt）与 details.jsonl → data/high.jsonl。
行格式：tag|line|HIGH|reason（多文件共享 tag，行号在各自 abstracts_{tag}.txt 内）。"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SCREEN = DATA / "screen"

# 判定索引：tag -> set(line)
high = {}
for gf in sorted(SCREEN.glob("grades_*.txt")):
    for raw in gf.open(encoding="utf-8"):
        m = re.match(r"([a-z]+_\d{4})\|(\d+)\|HIGH\|(.*)$", raw.strip())
        if not m:
            continue
        tag, ln = m.group(1), int(m.group(2))
        high.setdefault(tag, set()).add(ln)

# abstracts_{tag}.txt 的行号 -> details.jsonl 行的映射：逐 tag 顺序一致
details = [json.loads(l) for l in (DATA / "details.jsonl").open(encoding="utf-8")]
by_tag_rows = {}
for r in details:
    by_tag_rows.setdefault(f"{r['venue'].lower()}_{r['year']}", []).append(r)

out = []
for tag, lines in sorted(high.items()):
    rows = by_tag_rows.get(tag, [])
    for ln in sorted(lines):
        if 1 <= ln <= len(rows):
            row = dict(rows[ln - 1])
            row["final_tier"] = "HIGH"
            out.append(row)

with (DATA / "high.jsonl").open("w", encoding="utf-8") as fh:
    for row in out:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

import collections
per = collections.Counter(r["venue"] for r in out)
withpdf = sum(1 for r in out if r.get("pdf_url"))
print(f"high.jsonl: {len(out)} 条（HIGH）；有 pdf_url: {withpdf}")
for v, c in sorted(per.items()):
    print(f"  {v}: {c}")
