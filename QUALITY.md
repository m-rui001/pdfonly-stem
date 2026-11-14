# 质量报告：pdfonly-stem

本文件由 `python scripts/validate.py --quality` 生成，所有数字来自脚本扫描。
硬门槛与删除标准见 `scripts/QUALITY_STANDARD.md`。

## 现状计数

| 指标 | 数值 |
| --- | --- |
| Markdown 文件 | 914 |
| catalog 记录 | 949 |
| 总字符数 | 4841776 |
| 最短 / 中位 / 最长（字符） | 709 / 3924 / 23942 |
| quality=ok | 667 |
| quality=low | 233 |
| quality=bad | 14 |
| catalog/正文身份冲突 | 14 |
| 年份仅差 1 年（保留 catalog 年份） | 7 |
| 已删除（REJECTED.csv） | 2 |

## 缺陷分布

| defect | 篇数 |
| --- | --- |
| review_high_issue | 181 |
| no_h2 | 34 |
| no_source | 21 |
| metadata_year_mismatch | 8 |
| metadata_year_minor | 7 |
| short_body | 5 |
| metadata_title_mismatch | 4 |
| truncated_suspect | 3 |
| metadata_doi_mismatch | 2 |
| replacement_char | 1 |

## 删除记录

| reason | 篇数 |
| --- | --- |
| body_under_400_chars | 2 |

逐文件明细见 `REJECTED.csv`（path、reason、chars、sha1）。

## 已执行的确定性修复

- 统一 UTF-8 无 BOM、LF 换行；压缩 3 行以上连续空行与行尾空白。
- 依据 catalog/manifest 补 DOI、纠正明显错误的 DOI/年份（仅在记录可信时）。
- 同步 catalog 与实际文件不一致的字符数/存在性。
- 不重写任何总结正文；正文一字未改。

## 未解决项

- `review_high_issue`：181 篇，保留并标记（不可确定性修复或证据不足）。
- `no_h2`：34 篇，保留并标记（不可确定性修复或证据不足）。
- `no_source`：21 篇，保留并标记（不可确定性修复或证据不足）。
- `short_body`：5 篇，保留并标记（不可确定性修复或证据不足）。
- `metadata_title_mismatch`：4 篇，保留并标记（不可确定性修复或证据不足）。
- `replacement_char`：1 篇，保留并标记（不可确定性修复或证据不足）。
- `truncated_suspect`：3 篇，保留并标记（不可确定性修复或证据不足）。
- `metadata_year_mismatch`：8 篇，保留并标记（不可确定性修复或证据不足）。
- `metadata_doi_mismatch`：2 篇，保留并标记（不可确定性修复或证据不足）。

## 重跑命令

```
python scripts/validate.py            # 校验并重写 MANIFEST.csv，退出码即门槛结果
python scripts/validate.py --quality  # 重写本文件
python scripts/validate.py --fix      # 重放确定性清洗/修复/删除（幂等）
```

## 说明

- 来源基准：`out/catalog.csv`。
- `MANIFEST.csv` 的 `sha1` 是文件内容 SHA-1，`doc_id` 是文件名中的来源记录 ID。
- `REJECTED.csv` 只在删除时追加；删除内容可从 git 历史恢复。
