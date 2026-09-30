# M4 检索完备性对照 — LME oracle multi-session ×25

**结论一句话：检索完备性不是当前瓶颈 — 在检索层真正起作用的大目录题上，六个臂全部 ≤1/7，包括"全量渲染"；小目录题上各臂 prompt 完全相同，分数差纯是作答采样噪声。**

## 设置

- 数据：`data_ms25.json` = LongMemEval oracle 中 multi-session 类型的前 25 题（84 个 haystack 会话）。
- 摄入：每题 GLM-4.5-air 提取一次，缓存到 `models/`（随本目录提交，可复现），六臂共享同一份记忆 — 只有检索层不同。
- 判分：GLM judge（`lme.py --glm judge --ref oracle`）。
- 基线参照：v5 全卷 multi-session = 24%（不同子集，不直接可比）；本切片 base = 16%。

## 变体

| arm | 机制 |
|---|---|
| base | main reader.py：目录>50 时 LLM 挑 ≤50，否则全量 |
| fam | base 挑完 + slot token 重叠≥0.5 的同族顶点自动带入 |
| topic | LLM 先挑语义族（slot 名）→ 族下全部顶点 |
| recur | 触顶 50 时第二轮问 LLM"还缺什么" |
| big150 | max_pick=150（目录≤150 时 = 全量渲染） |
| mix | base 挑完 + slot 头词（`_` 前缀）同族顶点带入 |

## 结果（GLM 判分，n=25）

| arm | acc | answer tok | calls | avg_sel |
|---|---|---|---|---|
| base | 16.0% | 69.8k | 32 | 25.8 |
| fam | 12.0% | 70.8k | 32 | 29.3 |
| topic | 12.0% | 65.2k | 32 | 26.6 |
| recur | 12.0% | 74.8k | 32 | 26.1 |
| big150 | 12.0% | 76.0k | 25 | 40.7 |
| **mix** | **20.0%** | 78.5k | 32 | 30.9 |

## 为什么不能按表面名次宣布 mix 获胜

目录大小分布（big150 选中数≈目录大小）：中位 35，范围 7–73。**18/25 题目录 ≤50** — 此时 `aretrieve` 提前返回全部顶点，六个臂产出**逐字节相同的 prompt**，该块是 A/A 噪声测试（观测 11–22% 的散布全是采样硬币翻转；例：36b9f61e 同一份 4505B digest 三次作答给出 $1,700 / $2,500 / $2,500）。

真正区分检索层的只有 **7 题目录 >50**（51–73 顶点）：

| arm | >50 目录正确 | ≤50 目录正确（噪声块） |
|---|---|---|
| base | 1/7 | 3/18 |
| fam | 1/7 | 2/18 |
| topic | 0/7 | 3/18 |
| recur | 0/7 | 3/18 |
| big150 | 1/7 | 2/18 |
| mix | 1/7 | 4/18 |

在这 7 题上：**render-all（big150）也只有 1/7** — 把全部记忆摊开照样答错，说明这些失败不是"同族顶点没取齐"导致的缺失，而是已渲染内容上的聚合/推理失败。且 LLM 在这 7 题上只挑了 4–20/51–73 个顶点（远未触顶），扩预算（recur/big150）无从发力；族扩展把选中推到 14–61 也没救回任何题。

mix 逐题矩阵是 base 的严格超集（多拿 36b9f61e），但该题两臂 digest 相同 — 是运气不是机制。

## 落入 reader.py 的改动与理由

`aretrieve` 仍落了 mix（pick 后按 slot 头词族扩展）：它是唯一未在任何题上输给 base 的臂，机制上只能加顶点不能减（≤50 目录时为无操作），成本 +12% token。**性质是"零成本保险"，不是被验证的赢点** — 完备性方向在本切片上已被证否，后续瓶颈在作答端而非检索端。

## 复现

```bash
GLM_API_KEY=... python3 tasks/life_model/external/lme_variants.py run \
  --data results/lme_completeness/data_ms25.json --per-type 25 \
  --out-dir <out> --variants base,fam,topic,recur,big150,mix
# 判分（注意 judge 在 lme.py，需 --ref）：
GLM_API_KEY=... python3 tasks/life_model/external/lme.py --glm judge \
  --hyp <out>/hyp_<v>.jsonl --ref <oracle.json> --out <out>/metrics_<v>.json
```

产物：`hyp_*.jsonl`（响应+usage+选中顶点+digest 字节数）、`metrics_*.json`、
`models/`（每题摄入缓存）、`run.log`。
