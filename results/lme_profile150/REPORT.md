# 画像压缩损失曲线 @150q：profile 83.3% — 拐点 60+ 顶点，枚举/偏好是双病灶

- 全量：150q via_profile（`lifemodel.profile.render_profile` + `aanswer(profile=)`，#74 代码栈），每模型渲染一次
- 判官：Atria；缓存 = lme150_sc{0-3} + lme_ms25 selfc 模型
- 产物：`lane{0-3}/`（hyp+profiles）、`hyp_profile150.jsonl`、`metrics_profile150.json`、`man{0-3}.json`

## 总成绩

| 栈（150q, Atria） | acc |
|---|---|
| old stack | 84.7% |
| **profile-only** | **83.3%** |
| nogate | 83.3% |
| relaxed gate | 81.3% |
| **nogate+assist** | **86.0%** |

profile 与 nogate 打平、落后候选栈 2.7pp——但**错误分布完全不同**（下述），是互补通道不是优劣替代。

## per-type

| type | profile | nogate | assist |
|---|---|---|---|
| temporal | **1.00** | .88 | .96 |
| knowledge-update | .92 | 1.0 | 1.0 |
| ss-preference | .68 | .84 | .80 |
| ss-assistant | .80 | .76 | .80 |
| ss-user | .92 | .92 | .92 |
| multi-session | .68 | .60 | .68 |

- **temporal 100%**——画像把时锚内联，全类型唯一满分
- **pref .68 = 最大出血点**（−16pp vs nogate）：剖 3 条看全是**过度保守**——画像持有信号（"对语言多样性文化节感兴趣"）但 PROFILE_ANSWER_SYS 的"只用画像内事实"约束让模型拒答个性化推荐（35a27287 拒说无位置信息、d6233ab6 拒评估同学会）——回答提示词对 advisory 题太字面化，一半病灶是 prompt 可修的
- **ku .92**：2 错都是知识更新覆盖丢失（update 语义在画像里被最新值覆盖，丢了"曾经是什么"）

## 压缩损失曲线（profile_chars/dump_chars vs 顶点数）

| 顶点桶 | n | 中位压缩比 | 中位dump | acc |
|---|---|---|---|---|
| <30 | 81 | 0.94 | 3.4KB | .81 |
| 30-59 | 47 | 0.86 | 9.0KB | **.91** |
| 60-99 | 19 | 0.79 | 13.2KB | .74 |
| 100+ | 3 | 0.78 | 21.8KB | .67 |

**拐点实锤：60+ 顶点起成绩下滑（.91→.74→.67）**。但注意压缩比只降到 0.78——不是过度概括丢信息，而是**长画像内部 haystack 效应**：文档变大后细节被埋，作答端捞不出来。修复方向不是"渲染更全"而是"大画像需要分段/索引"。

## 枚举题损失复现（ms 8 错）

| qid | 判定 |
|---|---|
| 0a995998 / d23cf73b / c4a1ceb8 / gpt4_7fce9456 | **枚举/聚合题 4 错**——画像概括多物品清单，丢计数精度（探针预言复现） |
| gpt4_2f8be40d | 记录存在但画像压缩时丢了婚礼成员——真压缩损失 |
| 88432d0a / dd2973ad | R3 摄入残型（重复记录/锚错）——画像无法修摄入 |
| 7024f17c | 边界日界题——各机制皆死 |

**画像翻正的 ms 题（vs 所有检索臂全错）**：`6d550036`（R2 欠挑——无 pick 即无欠取）、`gpt4_15e38248`（G 边界 definitional-排除——gate 拒答 assist 翻转的画像我方答对）——**画像单枪匹马解决了 R2 和 G 两个病灶类**。

## 翻转账本（vs assist 臂，同题）

**−9 损失**：4× pref（过度保守）+ 2× ku（update 覆盖）+ 1× ss-user + 2× ms 枚举
**+5 救回**：6d550036 + gpt4_15e38248（R2/G 病灶）+ 0edc2aef（pref）+ gpt4_483dd43c（temporal）+ 1 ms

## 裁决

1. **画像不是通用替代，是分型最优通道**：temporal/ms 上打平或超过最佳栈（temporal 100%、ms 68%），pref/ku 上明显失血——**混合架构画像管时序聚合、检索管偏好更新**是正解。
2. **拐点在 60+ 顶点**：根因是长文档 haystack 效应而非压缩过度（ratio 仅 0.78）→ `export_profile()` 大记忆版需要分域索引化，不是更长。
3. **枚举病灶跨通道顽固**：检索臂欠取丢、画像概括丢、assist 候选表救一半——多物品计数是基准天花板题型。
4. **prompt 可修项**：PROFILE_ANSWER_SYS 对 advisory 题加"可基于画像信号做个性化推荐"条款，预计收回一半 pref 损失（~+2pp 全卷）。
