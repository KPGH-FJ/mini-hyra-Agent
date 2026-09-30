# M4 作答端聚合对照 — LME oracle multi-session ×25（OR 作答+判分）

**结论一句话：code-assist 胜出 — 让 LLM 只提取候选 (value,date) 项、把去重/排序/计数交给确定性代码后再作答，OR 判分 40% vs OR-base 24%（+16pp，10/25 vs 6/25，且为 base 正确集的严格超集）。**

## 设置

- 数据：与完备性轮同一子卷 `../lme_completeness/data_ms25.json`（25 题 multi-session）。
- 摄入：复用 `../lme_completeness/models/` 缓存（GLM 产），本目录 `models/` 为符号链接。
- 作答+判分：OpenRouter `stealth/space-bunny-alpha`（GLM 429 限流持续 >1.5h 切换；extract 客户端构造但未调用）。
- 五臂共享同一检索（`aretrieve` 含上一轮落的头词族扩展）+ 同一 digest，只有作答阶段不同 — 与完备性轮同框架。

## 变体

| arm | 作答机制 |
|---|---|
| base | 单段：digest → ANSWER_SYS → 答案（= 改前 reader.aanswer） |
| twopass | 先逐字枚举证据行，再凭清单作答（"找全"与"算对"分离） |
| router | 先分类题型（count/compare/when/other），按强制格式模板作答 |
| verify | 草稿 → 自查"数了哪些、漏没漏" → 终稿（2× 成本） |
| **code** | LLM 抽取候选 {value,date} JSON → Python 去重排序计数 → 带预算表作答 |

## 结果（OR 判分，n=25）

| arm | acc | answer tok | calls |
|---|---|---|---|
| base | 24.0% | 97.6k | 34 |
| twopass | 24.0% | 152.7k | 61 |
| router | 28.0% | 112.5k | 58 |
| verify | 32.0% | 177.8k | 63 |
| **code** | **40.0%** | 144.6k | 60 |

参照点：GLM-base（上轮同子卷）= 16%；OR-base = 24% — judge/作答者更换带来整体水位抬升，臂间对比以 OR 内部为准。

## 逐题矩阵（Y=判对）

code 是 base 的**严格超集**：保留全部 6 个 base 胜题，另加 4 题
`gpt4_59c863d7 / c4a1ceb8 / 46a3abf7 / gpt4_15e38248`。其中
`c4a1ceb8`、`gpt4_15e38248`（及 base 也对的 `dd2973ad`/`2e6d26dc`）
正是完备性轮 >50 目录、全臂 ≤1/7 的"死题区" — 确定性计数把上一轮
判死的聚合失败救回了一半（code 4/7 vs base 2/7）。

verify 同为 base 严格超集（+c4a1ceb8、+46a3abf7，8/25）；twopass
与 base 打平但集合不同（换 2 题）；router +1。token 上 code 比
verify 省 19%、比 twopass 省 5% — 抽出 JSON 后答题 prompt 虽多一张
表，但比"再读一遍全 memory 自查"便宜。

## 落入 reader.py 的改动

`aanswer` 从两段式变三段式：retrieve → **extract candidates**
（新 `_EXTRACT_SYS`，JSON {value,date} 数组）→ Python 确定性
去重/按日排序/计数 → ANSWER_SYS 带 `PRE-EXTRACTED CANDIDATES
(count=N)` 表作答。与 v_code 臂实现逐字一致。

## 备注与残留

- `../lme_answering/`（无 _or 后缀）= GLM 作答的**残卷** 7-8 行/臂，
  已剔除 __answer_error__，GLM 恢复后可续跑补齐做 GLM 侧复核。
- OR stealth 模型特性：`content` 可能为 null（思考被 max_tokens
  截断），`lme.py` 已修 — finish_reason=length 当可重试错误抛，
  否则回退 `reasoning` 字段；OR max_tokens 8192→16384。
- 判分命令：`lme.py judge --judge-backend openrouter --hyp <f>
  --ref <oracle> --out <m>`（GLM 判用 `--glm judge`）。
