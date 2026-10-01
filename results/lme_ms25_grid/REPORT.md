# ms-25 组合矩阵收官：{gate}×{assist} 四格 — 候选栈假设定案

- 切片：ms-25 全量（`results/data_ms150_25.json`），selfc 摄入缓存共用（`results/lme_selfc*/models`）
- 判官：Atria（answerer=judge 口径）；arm 内数字可与 72% 老栈线对账（同为 Atria 判 ms-25）
- 栈：main post-#67（selfc 摄入 + `premise_check="relaxed"` 默认）+ variants 组合
- 产物：`hyp_pvgassist.jsonl`（25 行，含 selected/digest_bytes）、`metrics_pvgassist.json`

## 2×2 矩阵（Atria 判 ms-25）

| | assist off | assist on |
|---|---|---|
| **no gate** | 60%（v_base） | **68%（v_assist）** |
| **relaxed gate** | 56%（v_pvgr） | **60%（v_pvgassist）** |

参照线：老栈 72%。

## 读数

1. **gate 在 assist 下的边际值 = −8pp（68→60）**：在干净摄入的聚合切片上，gate 唯一的可见作用是**把本来就错的答案改写成拒答**（4 条 abstain 全是其它臂也错的题），外加 assist 的判定方差损失 2 题（3a704032 日界 hedged、d23cf73b 枚举过数 6 vs 4）。gate 从未把错题翻转成对题——**在本切片上是纯成本**（它的本职收益在 cat5 对抗题型，ms 切片没有对应暴露面）。
2. **assist 在 gate 下的边际值 = +4pp（56→60）**：救回 c4a1ceb8 / 80ec1f4f / d682f1a2（残尾轮 assist 救援集的 3/5；d23cf73b 枚举再现失败、gpt4_2f8be40d R2 欠挑无解）。
3. **候选栈假设终局 = nogate+assist 68%**，仍距老栈 72% 差 4pp；gate 若上不能补差只会扩大差距。

## 残尾分类更新（pvgassist 臂 10 错，逐题）

| qid | 形态 | 分类 |
|---|---|---|
| 0a995998 | 答 2/3-4（全量顶点在 digest） | R1 作答端枚举 |
| 6d550036 | ABSTAIN（projects led 计数，组件未绑） | R2 欠挑（4/58）+ G 拒答 |
| 3a704032 | 答了但 hedge 取 April-only 解释 | R1（assist 方差，前三臂全对） |
| dd2973ad | ABSTAIN（day-before 时序换算未绑） | R3 锚错（各臂皆错） |
| gpt4_2f8be40d | 枚举婚礼但欠取（sel=11/1603B） | R2 欠挑 |
| gpt4_15e38248 | ABSTAIN（家具计数含 definitional 排除） | G 边界拒答（=assist −flip 同题） |
| 88432d0a | 过数 5 vs gold 4（sourdough 双记） | R3 摄入重复 |
| d23cf73b | 过数 6 vs gold 4 | R1（assist 救援未复现） |
| gpt4_7fce9456 | 答 1 vs 3（候选表只绑 1 套房产） | R1 枚举内容错 |
| 7024f17c | ABSTAIN（周慢跑总时，日界题） | G 边界拒答（=assist −flip 同题） |

**现占比：R1 作答端 4 / R2 检索欠挑 2 / R3 摄入残型 2 / G 边界拒答 2。**

vs 残尾轮（base 臂）R1 8 / R2 2 / R3 2 的变化：R1 从 8→4（assist 真实压缩了作答端残尾），新边界类 G=2 浮现——**definitional-排除/日界题是 gate 与 assist 共同攻不破的题型**（15e38248/7024f17c 在两机制下都错：gate 拒答、assist 翻转成错答）。这类题不是聚合失败，是"题目语义边界判定"问题，属独立病灶。

## 裁决

- ms-25 最优栈 = **selfc 摄入 + no gate + assist**（68%）；relaxed gate 在全 150q 上有 temporal 净增益（.92 vs .88），但在 ms 切片是纯开销。gate 是否按题型开关属下一轮决策（temporal 开 / ms 关的路由，或接受 150q 层 −3.4pp 换防线）。
- 残差 4pp（68 vs 72）拆解：2 题 G 边界（两机制皆死）+ 2 题 R2 欠挑 + 2 题 R3 摄入 + 4 题 R1 枚举方差——没有单一抓手能一次收回。
- 数据文件：`results/lme_ms25_grid/{hyp_pvgassist.jsonl, metrics_pvgassist.json, run.log}`
