#!/usr/bin/env python
"""合并子agent判定（verdicts_*.txt）与列表文件（list_*.jsonl）→ data/screened.jsonl。
行格式：tag|line|tier|reason。去重规则：同一 (tag,line) 多次判定时 A 优先。"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SCREEN = DATA / "screen"

# 1) 读全部判定
verdicts = {}          # (tag, line) -> (tier, reason)
bad = 0
for vf in sorted(SCREEN.glob("verdicts_*.txt")):
    for raw in vf.open(encoding="utf-8"):
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"([a-z]+_\d{4})\|(\d+)\|([AB])\|(.*)$", line)
        if not m:
            bad += 1
            continue
        tag, ln, tier, reason = m.group(1), int(m.group(2)), m.group(3), m.group(4)
        key = (tag, ln)
        if key in verdicts:
            if tier == "A":                     # A 优先（宁宽勿漏，摘要阶段再收紧）
                verdicts[key] = (tier, reason)
        else:
            verdicts[key] = (tier, reason)
if bad:
    print(f"警告：{bad} 行无法解析", file=sys.stderr)

# 2) 读列表文件
lists = {}              # tag -> [row, ...]
for lf in sorted(DATA.glob("list_*.jsonl")):
    tag = lf.stem.removeprefix("list_")
    lists[tag] = [json.loads(l) for l in lf.open(encoding="utf-8")]

# 3) 合并
out, skipped = [], 0
for (tag, ln), (tier, reason) in sorted(verdicts.items()):
    rows = lists.get(tag)
    if not rows or ln < 1 or ln > len(rows):
        skipped += 1
        continue
    row = dict(rows[ln - 1])
    row["tier"] = tier
    row["keyword_hits"] = [reason]
    out.append(row)

with (DATA / "screened.jsonl").open("w", encoding="utf-8") as fh:
    for row in out:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

na = sum(1 for r in out if r["tier"] == "A")
print(f"screened.jsonl: {len(out)} 条（A={na}, B={len(out)-na}）；越界跳过 {skipped}，解析失败 {bad}")
