# M4 code-assist 成本精修 — temporal-25（Atria 全链）

Round: 给 #54 落地的 code-assist（retrieve→extract→deterministic-table 三段式）
做成本/时序精修。后端按 lab 调度切分：**temporal-25 整条链走 Atria**
（摄入+4臂作答+判分全 Atria-Dawn-Preview，自成口径）；
**ms-25 走 OpenRouter**（日池烧穿后暂停，重置后补齐——见下）。

切片：LME oracle temporal-reasoning 子卷 25 题（`results/lme_agg_t/data_t25.json`）。

## 结果（Atria 作答 + Atria 判分，n=25）

| arm | acc | tokens(ans) | calls(ans) |
|---|---|---|---|
| **base** | **100%** | 105,309 | 68 |
| tjoin | 96% | 117,448 | 69 |
| code | 92% | 108,298 | 68 |
| gate | 92% | 111,460 | 67 |

ingest 成本（全题共享，Atria extract）：~205k completion tok/题 vs 作答 ~4.5k/题 ——
摄入是绝对大头，作答端优化省的是零头。

## 诚实结论：强作答端上，抽取机器只亏不赚

base 在该切片饱和（25/25），三段式 arms 没有任何增益空间——只有新增错误通道：

- **982b5123** "How many months ago did I book the Airbnb"（REF: 5 months）。
  code/gate/tjoin 全答 "three months"：抽取步把 "booked 3 months
  **in advance**" 当成候选喂进表，三条结构化臂同错；base 凭原文答对。
  → 候选表会**把错误抽取确定性放大**：LLM 抽错一次，下游无可挽回。
- **a3838d2b** "How many charity events before X"（REF: 4）。
  code/gate 枚举只数到 2（抽取欠举）；base 与 tjoin 对。

与 OR 子卷（ms-25）结果方向相反：那边 code 曾以 40% vs base 24% 胜出
（前一批次），这边 base 强（100%），code 反而 −8pp。
**code-assist 的净收益是作答端强弱的函数，不是无条件改进**——gate 的
"按需走表"思路方向对，但门控本身判断不了"这题抽取会不会抽错"。

## ms-25 结果（OR 作答 + OR 判分，n=25，重置后补齐）

OR 日池 ~05:50 UTC 烧穿（账号级 1000/day，两 lab 共用），~00:14 UTC
重置后探测脚本自动续跑收尾；判分用 `hyp_*_dedup.jsonl`（按 qid 去重、
非错误行优先，剔除 ~10 个 429 残留错误行）。

| arm | acc | ptok | ctok | calls |
|---|---|---|---|---|
| base | 36% | 98,484 | 54,324 | 58 |
| code | 36% | 102,051 | 78,172 | 60 |
| gate | 32% | 98,932 | 69,335 | 62 |
| tjoin | 32% | 98,335 | 55,407 | 62 |

逐题翻转 vs base：code +2/−2（恰恰丢掉上批赢的 c4a1ceb8+gpt4_15e38248
两题——翻转方向对调）、gate +2/−3、tjoin +0/−1。

**批间方差警告**：同切片同栈 base 从 24%（上批）漂到 36%（本批）——
n=25 采样噪声 ±12pp 量级，本轮全部臂差都在噪声内；上轮 code 的 +16pp
优势**未能复现**（两批翻转题交叉验证：c4a1ceb8/gpt4_15e38248 上批赢、
本批输，属采样敏感题）。

**gate 的结构性盲区**：ms-25 切片几乎全是聚合题，门控按设计把 ~所有题
仍送进候选表（calls 62 ≈ code 60，>2 调用行占比相同）——"省 ~40% 调用"
的前提只能在混合题型卷上检验，纯聚合切片上兑现不了。

## 综合裁决（两条切片合并）

- **没有任何精修臂在两切片上稳定胜出**：temporal 上 base 满分封顶、
  三段式纯亏；ms 上臂间差全在批间噪声内。
- **code-assist（#54 三段式）的定位修正**：收益是作答端强弱的函数——
  对弱 answerer（OR space-bunny）曾救回聚合失败，对强 answerer
  （Atria）只注入错误通道。读者里落地的三段式不撤（对弱端无害兜底），
  但不该再当作无条件改进引用。
- **temporal-join 不落地**：ms −1（噪声）、temporal −4pp——确定性日期
  运算没救到任何题，强 answerer 自己会算。
- 本轮无可进 reader.py 的最优 diff。

## 判分口径声明

- temporal-25：answerer=Atria-Dawn-Preview, judge=Atria-Dawn-Preview。
  绝对值不可与 OR/GLM 侧直接对账——后端不同。
- ms-25：answerer=stealth/space-bunny-alpha (OR), judge=同。
- 人工抽查 6/25 判对样本：答案+日期均真实命中，非判官放水；
  Atria 作答端在时序题上确实显著强于 glm-4.5-air / space-bunny。

## 产物

- `results/lme_agg_atria/hyp_{base,code,gate,tjoin}.jsonl`（25×4 干净行）
- `results/lme_agg_atria/metrics_*.json`
- `results/lme_agg_ms/hyp_*_dedup.jsonl` + `metrics_*.json`（OR 批，去重后判分）
- `results/lme_agg_ms/hyp_{base,code,gate,tjoin}.jsonl`（原始含错误行，留档）
- `results/lme_agg_tA/`, `results/lme_agg_tA2/`（两半 out-dir + Atria 摄入模型）
- `results/lme_agg_t/`（OR 期 temporal 摄入残留，留档）、`data_t25.json`（切片）
- harness：`--answer-backend atria`（SSE OpenAICompatLLM，不带 extra_body）、
  ingest deferral 重试、`LME_STACK_ROOT` 影子包根
