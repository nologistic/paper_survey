#!/usr/bin/env python
"""顶会论文爬取与索引：NeurIPS / ICML(PMLR) / CVPR / ICLR(Semantic Scholar) / AAAI。

数据源（全部为官方站点或权威 API）：
  NeurIPS  proceedings.neurips.cc/paper_files/paper/{year}?page=N   分页 64/页
  ICML     proceedings.mlr.press/v{vol}/                            单页全列表
  CVPR     openaccess.thecvf.com/CVPR{year}?day=all                 单页全列表
  ICLR     api.semanticscholar.org bulk (venue=ICLR)                OpenReview 被反爬
  AAAI     ojs.aaai.org issue 页（archive 解析 AAAI-2x 期次）

用法：
  python crawl.py --stage list   [--venues ...] [--years ...]     # 抓全部标题
  python crawl.py --stage screen --keywords "mixture of experts,MoE,..."  # 关键词初筛
  python crawl.py --stage details                                  # 抓筛选命中论文摘要/PDF链接
  python crawl.py --stage details --pdfs --refs                    # 下载 PDF 并抽参考文献
  python crawl.py --stage all --keywords "..." --pdfs
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")
PMLR_VOLUMES = {2024: 235, 2025: 267, 2026: 306}          # ICML 卷号（官方核对过）
AAAI_TAG = {2024: "AAAI-24", 2025: "AAAI-25", 2026: "AAAI-26"}
S2_BULK = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"


def fetch(url: str, retries: int = 4, timeout: int = 30, **kw) -> requests.Response | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": UA}, **kw)
            if r.status_code == 200:
                return r
            if r.status_code == 429:                      # 限速退避
                time.sleep(5 + 5 * attempt)
                continue
            if r.status_code == 404:
                return None
            time.sleep(2 + attempt)
        except requests.RequestException:
            time.sleep(2 + attempt)
    return None


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  ✓ {path.relative_to(ROOT)}  {len(rows)} 条")


# ---------------------------------------------------------------- NeurIPS
def crawl_neurips(year: int) -> list[dict]:
    """proceedings.neurips.cc：根页直挂论文（部分年份）+ 卷页（如 vol38-main-conference）。
    实测 page 分页参数无效，全量在单页内，按 href 去重聚合。"""
    r = fetch(f"https://proceedings.neurips.cc/paper_files/paper/{year}")
    if r is None:
        print(f"    NeurIPS {year}: 抓取失败")
        return []
    s = soup_of(r.text)
    out, seen = [], set()

    def harvest(page_soup: BeautifulSoup, label: str) -> int:
        new = 0
        for a in page_soup.find_all("a", title="paper title"):
            href = a["href"]
            if href in seen:
                continue
            seen.add(href)
            out.append({"venue": "NeurIPS", "year": year,
                        "title": a.get_text(" ", strip=True),
                        "url": "https://proceedings.neurips.cc" + href})
            new += 1
        print(f"    NeurIPS {year} {label}: +{new}，累计 {len(out)}", flush=True)
        return new

    harvest(s, "root")
    vols = []
    for a in s.find_all("a", href=re.compile(rf"^/paper_files/paper/{year}/")):
        h = a["href"]
        if "/hash/" in h or "/file/" in h or h.endswith(".html"):
            continue                                  # 论文页/文件页，只留卷页
        if h not in vols:
            vols.append(h)
    for vh in vols:
        rv = fetch("https://proceedings.neurips.cc" + vh)
        if rv is None:
            continue
        harvest(soup_of(rv.text), vh.rsplit("/", 1)[-1])
        time.sleep(0.4)
    print(f"    NeurIPS {year}: {len(out)} 篇")
    return out


# ---------------------------------------------------------------- ICML / PMLR
def crawl_icml(year: int) -> list[dict]:
    vol = PMLR_VOLUMES.get(year)
    if vol is None:
        print(f"    ICML {year}: 无已知 PMLR 卷号，跳过")
        return []
    r = fetch(f"https://proceedings.mlr.press/v{vol}/")
    if r is None:
        print(f"    ICML {year} (v{vol}): 抓取失败")
        return []
    out = []
    for div in soup_of(r.text).find_all("div", class_="paper"):
        title_p = div.find("p", class_="title")
        if not title_p:
            continue
        authors = div.find("span", class_="authors")
        author_text = authors.get_text(" ", strip=True)[:200] if authors else ""
        abs_link = div.find("a", href=re.compile(rf"/v{vol}/"))
        out.append({"venue": "ICML", "year": year,
                    "title": title_p.get_text(" ", strip=True),
                    "authors": author_text,
                    "url": abs_link["href"] if abs_link else ""})
    print(f"    ICML {year} (v{vol}): {len(out)} 篇")
    return out


# ---------------------------------------------------------------- CVPR
def crawl_cvpr(year: int) -> list[dict]:
    r = fetch(f"https://openaccess.thecvf.com/CVPR{year}?day=all", timeout=120)
    if r is None:
        print(f"    CVPR {year}: 不存在或抓取失败")
        return []
    out, seen = [], set()
    for a in soup_of(r.text).find_all("a", href=re.compile(rf"/content/CVPR{year}/html/.+\.html")):
        href = a["href"]
        if href in seen:
            continue
        seen.add(href)
        title = a.get_text(" ", strip=True)
        if title:
            out.append({"venue": "CVPR", "year": year, "title": title,
                        "url": f"https://openaccess.thecvf.com{href}"})
    print(f"    CVPR {year}: {len(out)} 篇")
    return out


# ---------------------------------------------------------------- ICLR（iclr.cc 虚拟站；OpenReview API 403，S2 严重欠采样）
def crawl_iclr(year: int) -> list[dict]:
    """iclr.cc/virtual/{year}/papers.html：poster/oral/spotlight 全量单页列表。
    S2 对 ICLR 覆盖差（2025 仅 1777/实际 3827，2026 仅 27/实际 5468），弃用。"""
    r = fetch(f"https://iclr.cc/virtual/{year}/papers.html", timeout=60)
    if r is None:
        print(f"    ICLR {year}: 虚拟站抓取失败")
        return s2_bulk("ICLR", "ICLR", year)          # 兜底
    s = soup_of(r.text)
    uniq = {}
    for a in s.find_all("a", href=re.compile(rf"/virtual/{year}/(poster|oral|spotlight)/\d+")):
        href = a["href"]
        if href not in uniq:
            uniq[href] = a
    out = [{"venue": "ICLR", "year": year,
            "title": a.get_text(" ", strip=True),
            "url": f"https://iclr.cc{href}",
            "pdf_url": ""}
           for href, a in uniq.items() if a.get_text(" ", strip=True)]
    print(f"    ICLR {year} (virtual): {len(out)} 篇")
    return out
def s2_bulk(venue: str, s2_venue: str, year: int) -> list[dict]:
    out, token, total = [], None, None
    while True:
        params = {"venue": s2_venue, "year": str(year),
                  "fields": "title,abstract,year,venue,externalIds,authors,url,openAccessPdf",
                  "limit": "1000"}
        if token:
            params["token"] = token
        for attempt in range(6):
            r = requests.get(S2_BULK, params=params, timeout=40,
                             headers={"User-Agent": UA})
            if r.status_code == 200:
                break
            time.sleep(8 + 6 * attempt)                   # S2 未鉴权限速
        else:
            print(f"    {venue} {year}: S2 限速放弃于 {len(out)} 条")
            break
        payload = r.json()
        total = payload.get("total", total or 0)
        for p in payload.get("data", []):
            ext = p.get("externalIds") or {}
            if venue == "ICLR":
                url = f"https://openreview.net/forum?id={ext.get('OpenReview', ext.get('CorpusId', ''))}"
            elif ext.get("DOI"):
                url = f"https://doi.org/{ext['DOI']}"
            else:
                url = p.get("url") or ""
            pdf = (p.get("openAccessPdf") or {}).get("url", "")
            if venue == "ICLR" and not pdf and ext.get("OpenReview"):
                pdf = f"https://openreview.net/pdf?id={ext['OpenReview']}"
            out.append({"venue": venue, "year": year,
                        "title": p.get("title", ""),
                        "abstract": p.get("abstract") or "",
                        "authors": ", ".join(a["name"] for a in p.get("authors", [])[:8]),
                        "url": url, "pdf_url": pdf})
        token = payload.get("token")
        print(f"    {venue} {year} (S2): {len(out)}/{total}", end="\r", flush=True)
        if not token:
            break
        time.sleep(3)
    print(f"    {venue} {year} (S2): {len(out)} 篇")
    return out


def crawl_iclr_s2(year: int) -> list[dict]:
    return s2_bulk("ICLR", "ICLR", year)


# ---------------------------------------------------------------- AAAI
# OJS archive（ojs.aaai.org）现仅列出 Vol 40 且响应极慢（实测挂死 >30 分钟），
# 全年份改用 Semantic Scholar bulk：带摘要与 openAccessPdf，DOI 指回官方页。
def crawl_aaai(year: int) -> list[dict]:
    return s2_bulk("AAAI", "AAAI", year)


def crawl_aaai_ojs(year: int) -> list[dict]:
    r = fetch("https://ojs.aaai.org/index.php/AAAI/issue/archive", timeout=60)
    tag = AAAI_TAG[year]
    issue_ids = []
    if r is not None:
        for a in soup_of(r.text).find_all("a", href=re.compile(r"issue/view/\d+")):
            if tag in a.get_text(" ", strip=True):
                iid = a["href"].rstrip("/").rsplit("/", 1)[-1]
                if iid not in issue_ids:
                    issue_ids.append(iid)
    if not issue_ids:
        # archive 现仅列出最新卷（Vol 40）；旧年份回退 Semantic Scholar bulk（自带摘要）
        print(f"    AAAI {year}: archive 无期次，回退 S2 bulk")
        return s2_bulk("AAAI", "AAAI", year)
    out = []
    for iid in issue_ids:
        page, start = 1, len(out)
        while True:                                        # OJS 期次也分页
            rr = fetch(f"https://ojs.aaai.org/index.php/AAAI/issue/view/{iid}?page={page}"
                       f"&itemsPerPage=100", timeout=60)
            if rr is None:
                break
            arts = soup_of(rr.text).find_all("a", href=re.compile(r"AAAI/article/view/\d+$"))
            if not arts:
                break
            for a in arts:
                title = a.get_text(" ", strip=True)
                if title:
                    out.append({"venue": "AAAI", "year": year, "title": title,
                                "url": a["href"] if a["href"].startswith("http") else
                                       f"https://ojs.aaai.org{a['href']}"})
            if len(arts) < 100:
                break
            page += 1
            time.sleep(0.4)
        print(f"    AAAI {year} issue {iid}: +{len(out) - start}", end="\r", flush=True)
        time.sleep(0.4)
    print(f"    AAAI {year} ({len(issue_ids)} issues): {len(out)} 篇")
    return out


CRAWLERS = {"neurips": crawl_neurips, "icml": crawl_icml, "cvpr": crawl_cvpr,
            "iclr": crawl_iclr, "aaai": crawl_aaai}


# ---------------------------------------------------------------- 筛选 / 详情
DEFAULT_KEYWORDS = ("mixture of experts,MoE,mixture-of-experts,expert merging,"
                    "expert pruning,expert routing,model compression,LLM compression,"
                    "compress LLM,model pruning,weight pruning,quantization,quantized,"
                    "knowledge distillation,low-rank,sparsification,model merging")


def stage_list(venues: list[str], years: list[int]) -> None:
    for venue in venues:
        fn = CRAWLERS[venue]
        for year in years:
            if venue == "neurips" and year >= 2026:
                print(f"    NeurIPS {year}: 尚未发布，跳过")
                continue
            path = DATA / f"list_{venue}_{year}.jsonl"
            if path.exists():
                print(f"    已存在 {path.name}，跳过（删除后可重抓）")
                continue
            rows = fn(year)
            if rows:
                write_jsonl(path, rows)


def stage_screen(keywords: str, exclude: str = "") -> None:
    kws = [k.strip().lower() for k in keywords.split(",") if k.strip()]
    excl = [k.strip().lower() for k in exclude.split(",") if k.strip()]
    pattern = re.compile("|".join(re.escape(k) for k in kws), re.I) if kws else None
    excl_pat = re.compile("|".join(re.escape(k) for k in excl), re.I) if excl else None
    screened = []
    for path in sorted(DATA.glob("list_*.jsonl")):
        for line in path.open(encoding="utf-8"):
            row = json.loads(line)
            title = row["title"]
            if pattern and not pattern.search(title):
                continue
            if excl_pat and excl_pat.search(title):
                continue
            hits = [k for k in kws if re.search(re.escape(k), title, re.I)]
            screened.append({**row, "keyword_hits": hits})
    write_jsonl(DATA / "screened.jsonl", screened)


ABSTRACT_PATTERNS = {
    # NeurIPS hash 页实测：<section class="paper-section"> 文本为 "Abstract " + 摘要正文
    "NeurIPS": lambda s: (s.find("section", class_="paper-section") or
                          s.find("h4", string=re.compile("Abstract", re.I)) or
                          s.find(id="abstract")),
    "ICML":    lambda s: s.find("div", class_="abstract"),
    "CVPR":    lambda s: s.find(id="abstract"),
    "AAAI":    lambda s: s.find("div", class_="abstract"),
    # iclr.cc 虚拟站 poster 页：<div class="abstract-section">Abstract …</div>
    "ICLR":    lambda s: s.find("div", class_=re.compile("abstract", re.I)),
}


def extract_detail(row: dict) -> dict:
    if row.get("abstract"):
        return row                                            # S2 行自带摘要
    if row["venue"] == "AAAI":
        return row                                            # ojs.aaai.org 易挂死，缺摘要时跳过抓取
    r = fetch(row["url"], timeout=40)
    if r is None:
        return {**row, "abstract": ""}
    s = soup_of(r.text)
    finder = ABSTRACT_PATTERNS.get(row["venue"])
    abstract = ""
    if finder:
        node = finder(s)
        if node:
            parent = node.find_parent()
            abstract = (node.get_text(" ", strip=True) if node.name == "p"
                        else node.get_text(" ", strip=True))[:4000]
            if re.match(r"^abstract[:\s]*$", abstract, re.I):
                abstract = node.find_next_sibling().get_text(" ", strip=True)[:4000]
            if not abstract or re.fullmatch(r"abstract[:\s]*", abstract or "", re.I):
                p = node.find_next("p") if node.name != "p" else node
                abstract = p.get_text(" ", strip=True)[:4000] if p else ""
    pdf = ""
    for a in s.find_all("a", href=re.compile(r"\.pdf$", re.I)):
        href = a["href"]
        if href.startswith("/"):
            href = row["url"].split("/", 3)[0] + "//" + row["url"].split("/", 3)[2] + href
        pdf = href
        break
    abstract = re.sub(r"^\s*abstract[:\s]*", "", abstract or "", flags=re.I)
    return {**row, "abstract": abstract.strip(), "pdf_url": pdf}


def stage_details(pdfs: bool = False, refs: bool = False) -> None:
    src = DATA / "screened.jsonl"
    if not src.exists():
        sys.exit("先运行 --stage screen")
    rows = [json.loads(l) for l in src.open(encoding="utf-8")]
    out_path = DATA / "details.jsonl"
    done = {json.loads(l)["url"]: True for l in out_path.open(encoding="utf-8")} \
        if out_path.exists() else {}
    detailed = [json.loads(l) for l in out_path.open(encoding="utf-8")] \
        if out_path.exists() else []
    pdf_dir = DATA / "pdfs"
    if pdfs:
        pdf_dir.mkdir(exist_ok=True)
    for i, row in enumerate(rows):
        if row["url"] in done:
            continue
        d = extract_detail(row)
        detailed.append(d)
        done[row["url"]] = True
        if pdfs and d.get("pdf_url"):
            slug = re.sub(r"[^A-Za-z0-9]+", "_",
                          f"{d['venue']}_{d['year']}_{d['title'][:60]}")[:100]
            pdf_path = pdf_dir / f"{slug}.pdf"
            if not pdf_path.exists():
                pr = fetch(d["pdf_url"], timeout=120)
                if pr is not None:
                    pdf_path.write_bytes(pr.content)
                    if refs:
                        d["references"] = extract_references(pdf_path)
        print(f"    详情 {i + 1}/{len(rows)}: {d['title'][:60]}", end="\r", flush=True)
        time.sleep(0.5)
    print()
    write_jsonl(out_path, detailed)


def extract_references(pdf_path: Path) -> list[str]:
    """从 PDF 尾部 References 节抽条目（best-effort）。"""
    try:
        import fitz
        doc = fitz.open(pdf_path)
        text = "\n".join(doc[i].get_text() for i in range(len(doc)))
        doc.close()
        m = re.search(r"\n(?:References|REFERENCES|Bibliography)\s*\n(.*)$",
                      text, re.S)
        if not m:
            return []
        block = m.group(1)
        parts = re.split(r"\n\[\d+\]\s*|\n(?=\w[\w.,’'\- ]+,\s+[A-Z]\.\s)", block)
        return [p.strip().replace("\n", " ")[:300] for p in parts
                if len(p.strip()) > 30][:80]
    except Exception:
        return []


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True,
                    choices=("list", "screen", "details", "all"))
    ap.add_argument("--venues", default="neurips,icml,cvpr,iclr,aaai")
    ap.add_argument("--years", default="2024,2025,2026")
    ap.add_argument("--keywords", default=DEFAULT_KEYWORDS)
    ap.add_argument("--exclude", default="")
    ap.add_argument("--pdfs", action="store_true")
    ap.add_argument("--refs", action="store_true")
    args = ap.parse_args()
    venues = [v.strip() for v in args.venues.split(",")]
    years = [int(y) for y in args.years.split(",")]
    stages = ("list", "screen", "details") if args.stage == "all" else (args.stage,)
    for stage in stages:
        print(f"===== stage: {stage} =====")
        if stage == "list":
            stage_list(venues, years)
        elif stage == "screen":
            stage_screen(args.keywords, args.exclude)
        else:
            stage_details(pdfs=args.pdfs, refs=args.refs)


if __name__ == "__main__":
    main()
