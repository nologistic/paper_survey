# 任务交接：顶会论文爬取与索引（NeurIPS/ICML/CVPR/ICLR/AAAI 2024-2026）

## 目标
直接从各会议官网目录抓取近三年论文的标题、摘要、PDF 链接、参考文献，建立本地可按会议/年份/关键词检索的索引。流程为：list（全量标题）→ screen（关键词初筛）→ details（命中论文抓摘要/PDF/参考文献）。

## 已有资产（在 /storage/dzj/paper_survey/）
- `crawl.py`：完整爬虫（5 个数据源适配器 + 三阶段流水线 + PDF 下载 + 参考文献抽取），可直接运行
- `query.py`：本地索引检索 CLI（--venue/--year/--keyword/--in-abstract/--json）
- `data/list_icml_2025.jsonl`：3330 条（标题+作者+URL，已验证正确）
- `data/list_cvpr_2025.jsonl`：2871 条（标题+URL，已验证正确）
- 运行环境：`/home/dzj/ENTER/envs/fedllm/bin/python`（requests/bs4/lxml/fitz 齐全）

## 数据源与已验证的技术细节（全部实测通过）

### NeurIPS
- 列表：`https://proceedings.neurips.cc/paper_files/paper/{year}?page={n}`，每页 64 条，`<a title="paper title" href="...">标题</a>`
- 摘要页：href 指向的 Abstract 页；PDF 链接在该页
- 年份：2024、2025 可用；**2026 尚未发布（12 月开会），跳过**
- 预计 ~4500 篇/年 ≈ 70 页/年

### ICML（PMLR）
- 卷号映射（已实测确认）：**2024=v235, 2025=v267, 2026=v306**（v306=首尔 ICML 2026, 6552 篇）
- 列表：`https://proceedings.mlr.press/v{vol}/` 单页全列表
- 结构：`<div class="paper"><p class="title">标题</p><p class="details"><span class="authors">作者</span>...<a href="绝对URL">abs</a>`
- 注意：abs 链接是绝对 URL（含域名），用 `re.compile(rf"/v{vol}/")` 匹配

### CVPR（CVF Open Access）
- 列表：`https://openaccess.thecvf.com/CVPR{year}?day=all` 单页（约 7.4MB）
- 结构：`<a href="/content/CVPR{year}/html/..._paper.html">标题</a>`
- CVPR2024/2025 已确认存在；CVPR2026（6 月已开）应存在，404 则跳过

### ICLR（Semantic Scholar bulk API）
- **OpenReview API（v1 和 v2）均被反爬 403 ChallengeRequired，不可用**
- 备选已验证：`https://api.semanticscholar.org/graph/v1/paper/search/bulk?venue=ICLR&year={year}&fields=title,abstract,year,venue,externalIds,authors,url&limit=1000`（带 continuation token 翻页）
- 已实测：ICLR 2025 = 1777 篇；**未鉴权限速严格，429 常见，需 8-30 秒退避重试**
- 好处：bulk 一次返回 abstract，无需二次抓详情页

### AAAI（OJS）
- 归档：`https://ojs.aaai.org/index.php/AAAI/issue/archive`（**必须 requests 或 curl --compressed，直接 -o 保存得到 gzip 乱码**）
- 期次映射（已实测）：issue 页标题含 "AAAI-26 Technical Tracks N" + "Vol. 40 No. N"；**AAAI-24=Vol 38, AAAI-25=Vol 39, AAAI-26=Vol 40**；每年 ~14-19 个 issue
- 期次页文章列表分页：`.../issue/view/{iid}?page={n}&itemsPerPage=100`，文章链接 `AAAI/article/view/{id}`

## 剩余工作清单
1. `python crawl.py --stage list --venues neurips,icml,cvpr,aaai,iclr --years 2024,2025,2026`（后台 nohup 跑；NeurIPS 两年 ~140 页最耗时 ~10 分钟；ICLR 受 S2 限速 ~10 分钟；已完成的 icml_2025/cvpr_2025 会自动跳过）
2. `python crawl.py --stage screen`（默认关键词集：mixture of experts/MoE/expert merging/pruning/quantization/distillation/compression/low-rank/...，可 --keywords 覆盖）
3. `python crawl.py --stage details --pdfs --refs`（命中论文抓摘要+PDF+参考文献；预计 100-400 篇命中，每篇 1 页 + PDF）
4. 验证 `query.py` 检索
5. 已知待验证点：details 阶段的摘要提取（四个 venue 的 HTML 结构各不同，extract_detail 的 pattern 匹配需要实际验证，NeurIPS/ICML/CVF/AAAI 分别是 h4#Abstract/div.abstract/#abstract/div.abstract，PMLR 摘要在 abs 页）；参考文献抽取用 fitz 正则 "References" 节，是 best-effort

## 预期产出
- `data/list_*.jsonl`：~15 个文件，~35000 条标题
- `data/screened.jsonl`：关键词命中
- `data/details.jsonl`：含摘要
- `data/pdfs/*.pdf` + details 里的 references 字段

## 礼貌性约束
每请求间隔 0.4-1s；S2 遇 429 退避 8-30s；全部为官网公开页面，无登录。

## 用途上下文
索引服务于「MoE 架构 / LLM 压缩」方向的 related work 调研，默认初筛关键词覆盖该领域；换成其他领域时用 `--keywords` 覆盖即可。
