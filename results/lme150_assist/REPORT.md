# 150q 终局选型：nogate×assist = 86.0% — 首个反超老栈的栈

- 切片：150q 全卷（125 非-ms `data_150sc_{0-3}` + ms-25 `data_ms150_25`），selfc 摄入缓存共用
- 判官：Atria（answerer=judge）；ms-25 assist 臂沿用 assist25 结果（68%，同缓存同口径）
- 栈：main post-#67 reader + `assist=True`（候选栈假设终局）
- 产物：`sc{0-3}/hyp_assist.jsonl`、`hyp_assist_125.jsonl`（合并）、`metrics_assist_125.json`

## 最终选型表（150q，Atria 判）

| 栈 | 150q | vs 老栈 |
|---|---|---|
| 老栈（twostage+pre-fix reader） | 84.7% | — |
| selfc + strict gate | 48.7% | −36.0 |
| selfc + relaxed gate | 81.3% | −3.4 |
| selfc + no gate | 83.3% | −1.4 |
| **selfc + no gate + assist** | **86.0%** | **+1.3** |

**首个反超老栈的栈**：86.0% = 112/125 + 17/25。候选栈终局实锤。

## per-type（nogate×assist vs nogate×off）

| type | ungated | +assist | Δ |
|---|---|---|---|
| temporal | .88 | **.96** | +8 |
| knowledge-update | 1.0 | 1.0 | 0 |
| ss-preference | .84 | .80 | −4 |
| ss-assistant | .76 | .80 | +4 |
| ss-user | .92 | .92 | 0 |
| multi-session | .60 | .68 | +8 |

assist 在非-ms 上是净增益而非稀释：temporal +8（把"组件推理"变成显式候选表装配）、ss-assist +4、pref −4（一题波动）、ku/user 持平。125 题翻转：+5 救回（09d032c9/3b6f954b/a3838d2b/cc539528/gpt4_2312f94c）/ −3 损失（57f827a0/66f24dbb/fca70973）。

## abstain 分布（150q）

- **nogate×assist：2/150**（自发拒答，非门控）
- **relaxed gate：14/150**（125q 10 + ms-25 4；其中诚实信息缺口 ~9，残余误杀 ~5）
- 结论：无对抗题的 LME 上，gate 防线面暴露 ≈9% 拒答率，收益端（cat5 对抗防线）在基准内无对应题型——gate 在 LME 纯开销；其价值需在 LoCoMo cat5 类对抗切片单独计价。

## 裁决

**候选栈 = selfc 摄入 + no gate + assist（86.0%）反超老栈（84.7%）**——研究问题闭环：三段式/selfc/gate 三轮修复把 78→86，老栈线下马。gate 选型留给产品决策（LME 纯开销 vs LoCoMo cat5 +4.5pp 防线）。

- 判分器插曲：首轮 judge 中途流断卡死（0 socket 0% CPU），重跑第二轮出数——metrics 有效。
