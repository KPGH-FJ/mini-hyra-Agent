# 宽化 premise gate（方案 B）150q 复测

背景：严格 gate-all 在 150q 上 −34.6pp（57.6% 非ms / 4% ms），误杀形态 = 把"答案无字面记录"当前提缺失（temporal 要组件合成、advisory 无字面前提）。方案 B = verifier schema 加 `premise_expected` / `synthesis_needed`：

- `premise_expected=false`（建议/推荐/偏好类，无事实前提可验）→ `NO_PREMISE` 直接放行作答；
- `synthesis_needed=true`（计数/日期运算/跨记录聚合）→ 跨记录组件合法（不再是 splice），detail 原子豁免字面校验（它是算出来的答案不是要绑的名词）；who/event 组件未绑仍 `ABSENT` 拒答——cat5 对抗防线不动；
- 实现：`aanswer(premise_check="relaxed")`，PVERIFY_SYS 扩两字段，`_pv_gate` 加 relaxed 分支（results/mainstack/lifemodel/reader.py shadow）；严格 `premise_check=True` 行为不变。
- 变体 `v_pvgr`（lme_variants.py）。同一批 selfc 模型缓存，零摄入，Atria 作答+判分。

## 125 非 ms 题三方对比（Atria 判）

| 题型 | 无gate | 严gate | **宽gate** | 宽−无 |
|---|---|---|---|---|
| temporal | .88 | .28 | **.92** | **+4pp** |
| knowledge-update | 1.00 | .96 | .96 | −4pp |
| single-session-preference | .84 | .12 | .80 | −4pp |
| single-session-assistant | .76 | .60 | .72 | −4pp |
| single-session-user | .92 | .92 | .92 | 0 |
| **总计 (125)** | **.88** | **.576** | **.864** | **−1.6pp** |

## 拒答审计（验收线）

- 拒答 55 → **10**；误杀率从 44% 压到 **2.4%**（3/125 残余误杀：dc439ea3 powwow 舞、58ef2f1c 志愿轮班日期、488d3006 步道推荐——都是组件没绑上判 ABSENT，无害化处理可再议）。
- 剩 10 条拒答中 **7 条是真信息缺口**（无 gate 臂同样答错——拒答诚实且口径正确）：6ae235be / 89527b6b / 1d4da289 / 51a45a95 / gpt4_483dd43c / 58470ed2 / 8752c811。
- 事实型防线验证：合成放行只在 who/event 组件全绑定时生效；detail 豁免只限 `synthesis_needed`——严 gate 的 SUPPORTED→SPLICED 跨人判定与 detail 字面校验在非合成题上原样保留。

## 机制注脚

**temporal 宽 gate 反超无 gate（.92 vs .88）**——绑定约束对时序题不是开销是增益：强制把组件钉到具体记录再合成，比裸答更准。gate 的 LoCoMo cat5 +4.5pp 与 LME 灾难不是矛盾，是同一条边界的两面：对"前提型"题它是护栏，对"推理/建议型"题它曾是路障——现在边界按题面语义画，不按题型画。

## ms-25（补全 150q）

`results/lme150_ms25r/`（同 selfc 模型缓存跑 v_pvgr）：**56%**（严 gate 4% / 无 gate 60%）——gate 的 ms 误杀从 −56pp 压到 −4pp。

- 拒答 4/25：6d550036、dd2973ad（无 gate 臂同错，诚实拒答）；gpt4_15e38248、7024f17c（无 gate 臂对——残余误杀 2/25）。
- 注意：这 2 道误杀正是 assist 轮翻车的同两题（定义/边界裁决题），属于"多加一个判定级就多一条错误通道"的硬币面。

## 150q 总账（Atria 判）

| 栈 | 非ms(125) | ms(25) | 总(150) | vs 老栈 84.7 |
|---|---|---|---|---|
| selfc+严gate | 57.6 | 4 | 48.7 | −36.0pp |
| **selfc+宽gate** | **86.4** | **56** | **81.3** | **−3.4pp** |
| selfc+无gate | 88.0 | 60 | 83.3 | −1.4pp |

宽 gate 把严 gate 的 −36pp 救回 32.6pp，距无 gate 只差 2pp（残余误杀：非ms 3/125 + ms 2/25，均为"组件未绑"或定义/边界题——与无 gate 的差距本质上是 5 道硬币题）。

## 产物

- `results/lme150_rlx{0-3}/hyp_pvgr.jsonl`（125）+ `results/lme150_hyp_pvgr_125.jsonl`（合并）
- `results/metrics_150sc_pvgr_125.json`
- 代码：results/mainstack/lifemodel/reader.py（PVERIFY_SYS/_pv_gate/_pverify/aanswer relaxed 分支）、lme_variants.py（v_pvgr）
