#!/usr/bin/env python
"""下载 HIGH 论文 PDF：
  1) row.pdf_url 直接下载（AAAI/ojs 用短超时防挂死）
  2) 无 pdf_url（ICLR）→ S2 title-match 查 openAccessPdf 兜底
  3) 每篇 PDF：fitz 抽参考文献 + 全文转存 data/texts/*.txt
断点续跑：pdf 已存在则跳过下载，仅补字段。"""
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crawl import fetch, extract_references, UA  # noqa: E402

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PDFS = DATA / "pdfs"
TEXTS = DATA / "texts"
PDFS.mkdir(exist_ok=True)
TEXTS.mkdir(exist_ok=True)

rows = [json.loads(l) for l in (DATA / "high.jsonl").open(encoding="utf-8")]


def slug_of(r, i):
    s = re.sub(r"[^A-Za-z0-9]+", "_", f"{r['venue']}_{r['year']}_{i:03d}_{r['title'][:50]}")
    return s[:110]


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def build_s2_bulk_cache():
    """S2 bulk：venue=ICLR 按年拉全量（含 openAccessPdf / ArXiv id），建 title->pdf 缓存。
    3 个年份共 ~9 次请求，替代 188 次逐题查询。缓存落盘可续用。"""
    cache_path = DATA / "screen" / "s2_iclr_cache.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    cache = {}
    for year in (2024, 2025, 2026):
        token, total = None, None
        while True:
            params = {"venue": "ICLR", "year": str(year),
                      "fields": "title,openAccessPdf,externalIds", "limit": "1000"}
            if token:
                params["token"] = token
            got = False
            for attempt in range(6):
                try:
                    r = requests.get("https://api.semanticscholar.org/graph/v1/paper/search/bulk",
                                     params=params, timeout=40, headers={"User-Agent": UA})
                    if r.status_code == 200:
                        got = True
                        break
                    time.sleep(10 + 8 * attempt)
                except requests.RequestException:
                    time.sleep(5)
            if not got:
                print(f"    bulk ICLR {year} 放弃", flush=True)
                break
            payload = r.json()
            for p in payload.get("data", []):
                pdf = (p.get("openAccessPdf") or {}).get("url", "")
                if not pdf:
                    arx = (p.get("externalIds") or {}).get("ArXiv", "")
                    if arx:
                        pdf = f"https://arxiv.org/pdf/{arx}"
                if pdf:
                    cache[_norm(p.get("title", ""))] = pdf
            token = payload.get("token")
            total = payload.get("total", total or 0)
            print(f"    bulk ICLR {year}: {len(cache)} 累计/{total}", flush=True)
            if not token:
                break
            time.sleep(3)
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    return cache


S2_CACHE = None


def arxiv_match(title: str):
    """arXiv API 按标题查 PDF。两级：ti 精确短语 → 宽松词组，取标题最相似条目。"""
    try:
        import urllib.parse
        import difflib
        want = _norm(title)

        def query(q):
            url = f"http://export.arxiv.org/api/query?search_query={urllib.parse.quote(q)}&max_results=8"
            rr = requests.get(url, timeout=30, headers={"User-Agent": UA}, proxies=dl_proxies(url))
            if rr.status_code != 200:
                return []
            return re.findall(r"<entry>(.*?)</entry>", rr.text, re.S)

        def pick(entries):
            scored = []
            for e in entries[:8]:
                m_t = re.search(r"<title>(.*?)</title>", e, re.S)
                m_id = re.search(r"<id>http://arxiv.org/abs/([^<]+)</id>", e)
                if not (m_t and m_id):
                    continue
                t = re.sub(r"\s+", " ", m_t.group(1)).strip()
                sim = difflib.SequenceMatcher(None, want, _norm(t)).ratio()
                scored.append((sim, m_id.group(1), t))
            if not scored:
                return ""
            scored.sort(reverse=True)
            best = scored[0]
            if best[0] >= 0.75:                      # 标题变体容忍（Wanda/SVD-LLM 实测 0.76-0.88，负样本 ~0.3）
                return f"https://arxiv.org/pdf/{best[1]}"
            return ""

        e1 = query(f'ti:"{title[:150]}"')
        u = pick(e1)
        if u:
            return u
        time.sleep(2.5)
        e2 = query(f"all:{title[:120]}")             # 宽松：词 AND
        u = pick(e2)
        time.sleep(2.5)                              # arXiv 礼貌间隔
        return u
    except Exception:
        return ""


def s2_match(title: str):
    """找 openAccessPdf：先查 bulk 缓存，再逐题 match（含 ArXiv 兜底）。"""
    global S2_CACHE
    if S2_CACHE is None:
        S2_CACHE = build_s2_bulk_cache()
    hit = S2_CACHE.get(_norm(title))
    if hit:
        return hit
    for attempt in range(5):
        try:
            r = requests.get("https://api.semanticscholar.org/graph/v1/paper/search/match",
                             params={"query": title[:200], "fields": "title,openAccessPdf,externalIds"},
                             timeout=30, headers={"User-Agent": UA})
            if r.status_code == 200:
                data = r.json().get("data", [])
                if data:
                    d0 = data[0]
                    pdf = (d0.get("openAccessPdf") or {}).get("url", "")
                    if not pdf:
                        arx = (d0.get("externalIds") or {}).get("ArXiv", "")
                        if arx:
                            pdf = f"https://arxiv.org/pdf/{arx}"
                    return pdf
                return ""
            time.sleep(10 + 10 * attempt)
        except requests.RequestException:
            time.sleep(4)
    return ""


def pdf_text_dump(pdf_path: Path, txt_path: Path):
    try:
        import fitz
        doc = fitz.open(pdf_path)
        text = "\n".join(doc[i].get_text() for i in range(len(doc)))
        doc.close()
        txt_path.write_text(text, encoding="utf-8")
        return len(text)
    except Exception:
        return 0


ok = fail = s2hit = s2miss = 0
# 可选：设置环境变量 PAPER_PROXY=http://host:port 走代理（如国内网络环境）
PROXY = os.environ.get("PAPER_PROXY", "")


def dl_proxies(url: str):
    """ojs.aaai 在部分网络下直连更快，故对其跳过代理。"""
    if not PROXY or "ojs.aaai" in url:
        return None
    return {"http": PROXY, "https": PROXY}


if S2_CACHE is None:
    S2_CACHE = build_s2_bulk_cache()

for i, r in enumerate(rows):
    slug = slug_of(r, i)
    pdf_path = PDFS / f"{slug}.pdf"
    txt_path = TEXTS / f"{slug}.txt"
    url = r.get("pdf_url") or ""
    if not url and not pdf_path.exists():
        url = arxiv_match(r["title"]) or S2_CACHE.get(_norm(r["title"]), "")
        if url:
            r["pdf_source"] = "arxiv_or_cache"
        else:
            url2 = s2_match(r["title"])      # 末位兜底（429 风险）
            if url2:
                url = url2
                r["pdf_source"] = "s2_title_match"
            else:
                r["pdf_source"] = "unavailable"
    if url and not pdf_path.exists():
        # AAAI/ojs 易慢：连接10s、读60s；其余 30/90
        t = (10, 60) if "ojs.aaai" in url else (30, 90)
        try:
            pr = requests.get(url, timeout=t, headers={"User-Agent": UA}, proxies=dl_proxies(url))
            if pr.status_code == 200 and pr.content[:4] == b"%PDF":
                pdf_path.write_bytes(pr.content)
            else:
                r["pdf_source"] = f"http_{pr.status_code}"
        except requests.RequestException as e:
            r["pdf_source"] = f"err_{type(e).__name__}"
    if not pdf_path.exists() and not url.startswith("https://arxiv"):
        # 直链失败 → S2 兜底（常给 arXiv 链接）
        url2 = s2_match(r["title"])
        if url2:
            try:
                t2 = (10, 60) if "ojs.aaai" in url2 else (30, 90)
                pr = requests.get(url2, timeout=t2, headers={"User-Agent": UA}, proxies=dl_proxies(url2))
                if pr.status_code == 200 and pr.content[:4] == b"%PDF":
                    pdf_path.write_bytes(pr.content)
                    r["pdf_source"] = "s2_fallback"
                    s2hit += 1
            except requests.RequestException:
                pass
    if pdf_path.exists():
        r["pdf_file"] = pdf_path.name
        if not r.get("references"):
            r["references"] = extract_references(pdf_path)
        if not txt_path.exists():
            n = pdf_text_dump(pdf_path, txt_path)
            r["text_chars"] = n
        r.setdefault("pdf_source", "pdf_url")
        ok += 1
    else:
        fail += 1
    if (i + 1) % 50 == 0:
        print(f"  {i + 1}/{len(rows)}：成功 {ok}，失败 {fail}，S2命中 {s2hit}/{s2hit + s2miss}", flush=True)

with (DATA / "high.jsonl").open("w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"完成：PDF {ok}/{len(rows)}（失败 {fail}；S2 兜底命中 {s2hit}、未得 {s2miss}）")
