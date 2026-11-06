#!/usr/bin/env python
"""对 details.jsonl 中摘要为空的 NeurIPS 行原位补抽（使用修复后的 extract_detail）。"""
import json
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from crawl import extract_detail  # noqa: E402

ROOT = Path(__file__).resolve().parent
p = ROOT / "data" / "details.jsonl"
rows = [json.loads(l) for l in p.open(encoding="utf-8")]
todo = [i for i, r in enumerate(rows)
        if r["venue"] == "NeurIPS" and not (r.get("abstract") or "").strip()]
print(f"待补抽 {len(todo)} 条", flush=True)
fixed = 0
for n, i in enumerate(todo, 1):
    d = extract_detail({**rows[i], "abstract": ""})
    rows[i] = d
    if (d.get("abstract") or "").strip():
        fixed += 1
    if n % 100 == 0:
        print(f"  {n}/{len(todo)}，已获得摘要 {fixed}", flush=True)
    time.sleep(0.2)
with p.open("w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"完成：补抽成功 {fixed}/{len(todo)}，已回写 details.jsonl")
