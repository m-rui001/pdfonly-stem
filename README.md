# PDF-only STEM 论文语料与处理流水线

本仓库保存一份截至 2026-09-25 的论文全文处理产物，并保留元数据采集、来源探测、PDF 下载和导出脚本。文件夹名使用 SHA-1 内容标识；`out/catalog.csv` 将每个标识映射到 DOI、OpenAlex ID、年份和已有的 HTML、OCR HTML、Markdown 文件。

## 仓库内容

- `scripts/`：OpenAlex 元数据采集、结构化来源探测、URL 补源、PDF 下载和 TSV 导出脚本。
- `out/html/<sha1>/index.html`：正文可提取文本的 HTML。
- `out/html_ocr/<sha1>/index.html`：OCR 流程处理后的 HTML。
- `out/md/<sha1>.md`：按论文脉络撰写的中文 Markdown 总结。
- `out/reviews/<sha1>.review.json`：总结审核记录；其中源 HTML 路径已转为仓库相对路径。
- `out/catalog.csv`：安全筛选后的作品目录，不含本机绝对路径和正文抽样片段。

本快照包括 **949** 个普通 HTML、**265** 个 OCR HTML、**916** 个 Markdown，总计 **916** 份对应审核记录。原始 PDF、EPUB、OCR 原始 JSON、SQLite 下载状态库、临时文件、日志、API 密钥和本机环境配置不在仓库中。原始 OCR JSON 仍保留在本机的 `out/ocr_raw_zai/`。

## 完整工作流程

### 1. 明确采集范围

项目用 OpenAlex 的 field 白名单定义 STEM，而不是把整个 `Physical Sciences` 之外的医学、护理、牙科等领域混入。采集过滤包含文章类型、年份、开放获取、可获取全文 PDF、未撤稿等条件。`scripts/config.py` 中维护 field 白名单、主机速率限制和下载排序。

### 2. 采集论文元数据

需要 Python 3.10 或更新版本。网络访问使用 OpenAlex API；设置联系邮箱可进入 polite pool，API key 可选：

    $env:CORPUS_MAILTO = "you@example.org"
    $env:OPENALEX_KEY = "your-key" # 可选；不要写入代码或提交到仓库
    python scripts/1_harvest.py --scope stem --year 2015-2024 --limit 2000 --extra best_oa_location.source.type:repository --out out/manifest.jsonl

`--extra ...repository` 会偏向机构知识库；移除此参数可扩大来源范围。`--group` 可先输出学科分布而不开始采集。

### 3. 判断是否存在可解析的结构化来源

    python scripts/2_probe_xml.py --in out/manifest.jsonl --out out/probed.jsonl --workers 16

对每篇记录依次探测 arXiv e-print 源码、Europe PMC JATS/XML 和出版商文章级 HTML。`pdf_only` 只用于有正面证据的记录；`likely_pdf_only` 和 `unknown` 表示证据不足，不应误当成已确认只有 PDF。

### 4. 可选补充 PDF URL

    python scripts/3b_enrich_urls.py --in out/probed.jsonl --out out/manifest.e.jsonl --email $env:CORPUS_MAILTO --openalex-key $env:OPENALEX_KEY --workers 16

这一步尝试用 Unpaywall/OpenAlex 补充候选链接。2000 篇样本中仅 24 篇获得了新增候选，提升约 1.2%；不是必跑步骤。

### 5. 下载并校验 PDF

    python scripts/3_download.py --in out/probed.jsonl --only pdf_only,likely_pdf_only,unknown --root out/pdfs --db out/state.db --workers 8 --verify --skip-publishers

默认从机构库等优先来源取文件，按 URL 主机限速和限制并发，校验 PDF 格式，并以 SHA-1 内容去重。SQLite 状态库支持续跑；`.part` 临时文件按记录隔离。根据网络、代理和来源站点的限流情况调整 `--workers`，不要盲目提高并发。

### 6. 导出给 PDF 抽取器的任务表

    python scripts/4_export.py --db out/state.db --probed out/probed.jsonl --prefix out/corpus

生成 `out/corpus.text.tsv` 和 `out/corpus.scanned.tsv`：前者包含有文字层的 PDF，后者列出需要 OCR 的扫描件或无法提取正文的文件。扫描件在 OCR 后再进入 HTML 转换。

### 7. 提取 HTML 与 OCR

把 `corpus.text.tsv` 中的 PDF 交给 PDF→HTML 抽取流程，结果按 SHA-1 保存到 `out/html/<sha1>/index.html`。需要 OCR 的文件走 OCR 分支，结果写入 `out/html_ocr/<sha1>/index.html`；对应原始 OCR 响应保存在本地 `out/ocr_raw_zai/`。`out/catalog.csv` 和每篇审核记录用相同 SHA-1 与这些输出对应。

本仓库没有包含当前生产环境的 PDF→HTML/OCR 批处理器及其 OCR 服务调用脚本；这两个目录是已经生成并纳入快照的结果。要从原始 PDF 完整重跑这一步，需要把对应转换器、OCR 客户端和版本化配置补入 `scripts/`。对于确认没有文字层的 PDF，可先安装 `ocrmypdf` 并执行：

    ocrmypdf --skip-text --force-ocr --jobs 8 input.pdf output.pdf

### 8. 从提取文本生成并审核 Markdown

每篇总结以抽取后的 HTML 文本为输入，不把 PDF 页面图像发送给文本模型。生成目标是中文表达自然、依照论文逻辑顺序保留研究问题、方法、结论及重要公式；不堆叠模板化模块，不补写原文没有的信息。审核侧车记录源文本长度、总结长度、章节结构、自检结果以及疑似缺失/识别错误的位置。

本快照的 916 份审核记录对应两个 Flash 模型：`deepseek-v4-flash-ga-260731`（646 份）和 `deepseek-v4-1-flash`（270 份）。提示词版本和审核记录保存在 `out/reviews/`。仓库不包含模型 API key，也没有包含生产环境中的总结 API 调用器及提示词源文件；可依据审核记录中的 `prompt_version` 检查具体版本。模型的自检字段是自动审核证据，不代表人工逐篇核对或事实无误。

## 实测状态与限制

- 本地实际运行样本：2000 条；其中 1635 条进入 PDF 下载候选，成功 907 篇（55.5%），总计约 2.1 GB。905 篇存在文字层，2 篇为扫描件。
- 初始的 60 条试样不代表总体；真实 2000 条运行中 `unknown` 占比高。缺失 PMC ID 不能证明只有 PDF，单个 OpenAlex filter 也不能证明 PDF-only。
- 2000 篇样本里，机构知识库链接的成功率高于出版商直链；单点 IP、地区、代理和来源站点限速都会改变结果。
- `html_ocr` 与普通 HTML 是两个独立产物；不要仅用 HTML 文件存在来判断 OCR 或正文完整。
- Markdown 的内容正确性仍需按论文文本抽查；KaTeX/HTML 编译通过不等同于事实核验。

## 依赖和凭据

采集脚本主要使用 Python 标准库；`certifi` 可提供更完整的 TLS 根证书。下载校验阶段需要 `pdfinfo`，文字层检查需要 `pdftotext`，扫描 PDF 的 OCR 命令需要单独安装 `ocrmypdf`。这些系统工具不随仓库提供。

任何 API key 均通过环境变量或本机凭据管理器配置。不要把 `.env`、浏览器凭据、密钥、PDF 源文件、下载数据库或请求日志提交到 Git。

## 许可

MIT 许可只适用于本项目自行编写的脚本和文档。HTML、OCR HTML 和论文 Markdown 是对原论文内容的提取或整理；它们保留各自原始出版物的版权和适用许可，本仓库的 MIT 许可不转授第三方内容的权利。再分发前应逐篇确认其来源许可。