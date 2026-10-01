# M4 ms-72→28 归因分解（2×2 切片臂，全 Atria）

Round 问题：150q A/B（PR #57/61 档案）里 multi-session 从老栈 72% 崩到新栈
28%，归"新摄入 ×2.6 记录淹检索"还是"三段式候选表丢族"？
两臂拆开作答层，摄入零成本复用 reexam150 缓存。

## 臂定义

- **R1** = `reexam150_old/models`（twostage 摄入，median 55 recs）×
  **新 reader**（origin/main a5b4b7c，`LME_STACK_ROOT=/home/ubuntu/stack_main`；
  assist/三段式不存在 ⇒ 等价 #62 `aanswer(assist=False)`；premise_check 默认关）。
- **R2** = `reexam150_new/models`（事件日期+拆解摄入，median 102 recs）×
  **老 reader**（`LME_STACK_ROOT=results/oldstack` = 525e1b9 两段式，max_pick=50）。

切片 = `results/data_ms150_25.json`（data_strat150 的 multi-session 子集，25 题，
与 150q A/B 的崩塌观测同卷）。作答+判分全 Atria-Dawn-Preview。0 错误行。

## 2×2 结果（Atria 判）

| 摄入 \ reader | 老 reader（两段式） | 新 reader（assist 关） | 新 reader（三段式，全 A/B） |
|---|---|---|---|
| **老摄入** | 72%（oo） | **84%（R1）** | — |
| **新摄入** | **32%（R2）** | — | 28%（nn） |

## 裁决：主凶是新摄入，reader 反而无辜

- **R2 = 32% ≈ nn = 28%**：换老 reader 也救不回——崩塌跟随摄入走，不跟随
  reader 走。逐题交叉：R2 的 17 个败题中 **16 个与 nn 败集重合**（同一份重
  摄入喂给谁谁都死）；对 oo 净翻转 −11/+1。
- **R1 = 84% > oo = 72%**：新检索层（编号边+族扩展+前提校验关闭）在轻摄入
  下不是元凶，反而净赢 5 题（vs oo：+5/−2）。
- **三段式属次要修正项**：nn(28) 比 R2(32) 再低 4pp（噪声量级），主崩塌
  44pp 已在摄入侧发生。

## 机制（预算被目录挤兑）

| arm | median n_records | median picked | median digest_bytes |
|---|---|---|---|
| 老摄入臂（oo/R1） | 55 | 33 | 6.7KB |
| 新摄入臂（R2/nn） | 102 | 25 | 4.0KB |

新摄入把顶点目录灌到 ~1.9×，LLM 的挑选数却不升反降（25 vs 33），渲染出的
digest 反而小 40%——同族顶点互相挤掉，聚合所需的全量证据根本到不了作答端。
这同时解释了完备性轮的"目录>50 全臂皆 ≤1/7"：挤兑临界点在目录 ≈50+ 顶点。

## 含义

- ms 修复方向在**摄入/目录侧**（控顶点粒度、聚合预合并、或 pick 预算随目录
  规模缩放），不在作答端再加机器。
- 新 reader（assist 关）应保留：它是全场最强单格（84%），三段式 opt-in
  维持现状。

## 产物

- `results/lme_decomp_R1/`（old 摄入 × 新 reader：hyp/metrics/run.log/models 快照）
- `results/lme_decomp_R2/`（new 摄入 × 老 reader：同上）
- `results/data_ms150_25.json`（切片定义）
- 摄入缓存来源：`results/reexam150_{old,new}/models`（lifemodel-reexam-150 /
  #61 档案）
- 判分口径：answerer=judge=Atria-Dawn-Preview；与 OR/GLM 侧绝对值不可对账
