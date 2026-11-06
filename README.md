# paper_survey

从 NeurIPS / ICML / CVPR / ICLR / AAAI 五个顶会官网抓取 2024–2026 年论文元数据，构建本地可按**会议 / 年份 / 关键词 / 摘要**检索的离线索引。

无登录、无 API Key、全部只访问会议官方公开页面（ICLR/AAAI 走 Semantic Scholar 公开 bulk 接口）。

> A dependency-light crawler + offline index for NeurIPS / ICML / CVPR / ICLR / AAAI papers (2024–2026).
> Fetches titles, abstracts, PDFs and references directly from official proceedings pages, then lets you query them locally with a CLI.

## 数据规模

| Venue | 2024 | 2025 | 2026 | 小计 |
|---|---:|---:|---:|---:|
| NeurIPS | 4,493 | 5,887 | — (未发布) | 10,380 |
| ICML | 2,610 | 3,330 | 6,552 | 12,492 |
| CVPR | 2,716 | 2,871 | 4,042 | 9,629 |
| ICLR | 2,297 | 3,827 | 5,469 | 11,593 |
| AAAI | 2,988 | 4,227 | 2,659 | 9,874 |
| **合计** | **15,104** | **20,142** | **18,722** | **53,968** |

流水线累计产出：

- `data/list_*.jsonl` — 53,968 条标题索引（含作者/链接，AAAI 与 ICLR 附带摘要）
- `data/screened.jsonl` — 关键词初筛命中 **5,458** 条（命中率 10.1%）
- `data/details.jsonl` — 上述 5,458 条的完整摘要（**100%** 抓取成功）
- `data/high.jsonl` — 人工/LLM 复筛分级为 HIGH 的 **623** 条
- `data/pdfs/` + `data/texts/` — **597** 篇 PDF 及其全文纯文本（PDF 下载成功率 95.8%，不入库）

## 安装

```bash
python -m venv .venv && source .venv/bin/activate   # Python 3.10+
pip install -r requirements.txt
```

依赖：`requests`、`beautifulsoup4`、`lxml`、`PyMuPDF`（`fitz`，用于抽取参考文献与全文；缺失时会静默降级为不抽取）。

## 使用

### 三阶段流水线

```bash
# 1) list：抓全量标题 → data/list_{venue}_{year}.jsonl（已存在则跳过，可断点续跑）
python crawl.py --stage list --venues neurips,icml,cvpr,iclr,aaai --years 2024,2025,2026

# 2) screen：标题关键词初筛 → data/screened.jsonl
python crawl.py --stage screen \
  --keywords "mixture of experts,expert merging,pruning,quantization,distillation,low-rank" \
  --exclude "survey"

# 3) details：抓摘要 + 可选 PDF／参考文献 → data/details.jsonl
python crawl.py --stage details --pdfs --refs
```

`--stage all` 按 list → screen → details 顺序执行。默认关键词面向 **MoE / 模型压缩**方向，可用 `--keywords` 换成任意领域。

### 检索

```bash
python query.py --keyword "expert merging"
python query.py --venue ICML --year 2025 --keyword "low-rank" --in-abstract
python query.py --venue CVPR --year 2026 --limit 20 --json
```

参数：`--venue` `--year` `--keyword` `--in-abstract` `--limit` `--source`（默认 `details,screened`）`--json`。

### 可选的二次复筛链（人工 / LLM 打分）

`crawl.py --stage screen` 基于纯字符串匹配，召回高但噪声也高。仓库内另有一组脚本支持「LLM 复筛 + 分级 + 定向下载」，彼此通过 `data/` 下的文件松耦合：

```
list 产出的 titles_{venue}_{year}.txt
  → [外部 LLM/人工给 A/B 判定] verdicts_*.txt
  → merge_verdicts.py    → data/screened.jsonl   （替代 --stage screen）
  → crawl.py --stage details
  → abstracts_*.txt
  → [外部 LLM/人工给 HIGH 分级] grades_*.txt
  → merge_grades.py      → data/high.jsonl
  → download_high.py     → data/pdfs/*.pdf + data/texts/*.txt（回写 pdf_file / references / text_chars）
```

> 注意：这组脚本（`merge_*.py`、`download_high.py`、`repair_neurips.py`）目前是**脚本体**，无 CLI 参数，且依赖 `data/screen/` 下的固定命名与「列表行号对齐」约定，改造后再复用请先读源码。

`download_high.py` 支持通过环境变量走代理：

```bash
PAPER_PROXY=http://127.0.0.1:7890 python download_high.py
```

## 输出格式（运行后生成）

`data/list_*.jsonl` 每行一条：

```json
{"venue": "ICML", "year": 2025, "title": "...", "authors": "...", "url": "https://..."}
```

`data/details.jsonl` 在 list 字段基础上追加：

```json
{"abstract": "...", "pdf_url": "https://...", "tier": "A", "keyword_hits": ["..."]}
```

`data/high.jsonl` 追加后续阶段字段：

```json
{"final_tier": "HIGH", "pdf_file": "...", "pdf_source": "pdf_url|arxiv_or_cache|s2_title_match|http_<code>", "references": ["..."]}
```

## 目录结构

```
crawl.py             主爬虫：5 个 venue 适配器 + list/screen/details 三阶段
query.py             本地索引检索 CLI
download_high.py     下载 HIGH 论文 PDF + 抽参考文献 + 转纯文本
merge_verdicts.py    合并 LLM/人工 A/B 判定 → screened.jsonl
merge_grades.py      合并 HIGH 分级 → high.jsonl
repair_neurips.py    一次性补丁：重抽摘要为空的 NeurIPS 条目
HANDOFF.md           各数据源的实测技术细节与踩坑记录
data/                运行时产物目录（整个目录不入库，需自行生成）
```

## 各数据源实现要点

| Venue | 列表来源 | 备注 |
|---|---|---|
| NeurIPS | `proceedings.neurips.cc/paper_files/paper/{year}?page={n}` | 每页 64 条，分页抓取；摘要取 Abstract 页 |
| ICML | `proceedings.mlr.press/v{vol}/` | 卷号映射 2024=v235 / 2025=v267 / 2026=v306 |
| CVPR | `openaccess.thecvf.com/CVPR{year}?day=all` | 单页约 7MB |
| ICLR | Semantic Scholar bulk API | OpenReview API 已被反爬（403），故改走 S2 |
| AAAI | Semantic Scholar bulk API | OJS 归档页易挂死；列表已带摘要 |

## 已知限制

- **站点结构强耦合**：摘要抽取依赖各站 HTML 选择器（`h4#Abstract` / `div.abstract` / `#abstract` 等），站点改版即失效。
- **S2 限速**：无鉴权时 429 常见，需 8–30s 退避；建议自备 API Key 后改造 `fetch()`。
- **PDF 覆盖率**：623 篇 HIGH 中 597 篇下载成功（失败 26 篇，无 references / 全文）。
- **文本层缺失**：少数 PDF（约 2–3%）为扫描件或矢量图，`fitz` 抽不出正文，导致 references 为空。
- **NeurIPS 2026** 尚未发布，数据缺该年份。
- `--stage details` 的摘要截断上限为 4000 字符，`extract_references` 最多保留 80 条、每条 300 字符。

## 合规与礼貌抓取

- 仅访问会议官方公开页面与 Semantic Scholar 公开接口，不绕过任何登录或付费墙。
- 请求间隔 0.4–1s；遇 429 指数退避；不并发轰炸。
- 数据库中的标题/摘要/参考文献版权归原作者与出版方所有，本仓库仅用于学术检索与研究目的。PDF 文件因体积与版权原因**不纳入版本控制**。
- 若你是版权方并希望移除某些内容，请提 issue，会尽快处理。

## License

代码以 [MIT](LICENSE) 发布。数据与论文内容遵循其原始许可。
