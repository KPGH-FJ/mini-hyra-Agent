# Stage-3: vocabulary-aware spec generation — 报告

日期: 2026-10-07 · 状态: 完成（阴性结论，边界已定位）
前置: STAGE2_REPORT.md（真实 typed 字段救回 2/5，断点在 spec↔字段词表对齐）

## 问题

stage-2 的聚合谓词（spec）是手写/标注的——验证"确定性聚合"这个概念本身。
要变成系统，spec 必须自动生成。本臂测：**让 spec 写手看到快照真实词表后，
能否自动生成救回残尾数数题的 spec**。不产生、不使用 gold 标注——spec 只从
问题+快照词表出发，确定性求值逐字执行。

## 两臂实测（同一 7 题：5 残尾 + 2 留出，同判分=数值比对）

| qid | gold | v1 词表感知 | v2 放宽DNF | flat 通道 | 标注-spec(stage2) |
|---|---|---|---|---|---|
| 0a995998 待取衣物 | 3 | 2 ✗ | 7 ✗ | 2 | — |
| 88432d0a 烘焙次数 | 4 | 3 ✗ | 7 ✗ | 5 | — |
| d682f1a2 外卖服务 | 3 | 0 ✗ | 4 ✗ | 2 | — |
| gpt4_7fce9456 看房 | 4 | **4 ✓** | **4 ✓** | 5 | — |
| 7024f17c 运动时长 | 0.5h | **0.5 ✓** | **0.5 ✓** | 拒答 | — |
| b5ef892d 露营天数(留出) | 8d | 3.0 ✗ | 0.84 ✗ | 8 ✓ | — |
| gpt4_f2262a51 医生数(留出) | 3 | 0 ✗ | 5 ✗ | 3 ✓ | — |
| **合计** | | **2/5 救回, 0/2 留出保** | **2/5 救回, 0/2 留出保** | | |

两臂都是 2/5——**救回的是同样两题**（gpt4_7fce9456 看房 distinct、7024f17c
时长 sum），这两题在 stage-2 标注-spec 臂也是同一批救回。分水岭恒定。

## 失败归因（逐题逐字段核对真实 typed 值）

v1 漏报（under-select）的三个病灶：

1. **语义帧发散（主病灶）**：同一真实事件被抽取器打在不同表面帧下——
   - Domino's 外卖 → `verb=eat, object_class=food`（非 `use/service`）
   - 黄石露营5天 → `verb=attend, object='camping trip'`（非 `camp*`）
   - ENT 就诊 → `verb=diagnose, object='chronic sinusitis'`——**医生实体整个丢失**，
     object 落的是病症不是人
   - sourdough 烘焙 → `verb=try, object='sourdough bread recipe'`（非 `bake`）
   这些打标各自都"合理"，但 spec 按单一帧选必漏。
2. **kind 误标**：干洗店西装是待取义务，`kind=planned + obligation_status=
   awaiting_pickup`——kind=asserted 过滤把对的记录杀了。obligation_status
   才是正确的选择器，kind 应放开。
3. **null 字段脆性**：`when_abs=null` 的记录被 window 子句静默丢弃
   （巧克力蛋糕、Domino's 都是 null 日期）。

v2 放宽 DNF（`any_of` 多子句覆盖备选帧）后，漏报全部变成**误报**（over-select）：
7, 7, 4, 5 vs gold 3, 4, 3, 3——连带伤的是同店其他义务记录、无日期烘焙记录、
"try"帧的食谱实验、活检/肠镜事件。**精确率/召回率在字段级别 1:1 对冲**，
闭式 DSL 的边界画不出"正确的集合"。

## 结论（阴性但有定论价值）

**spec 侧调整已穷尽**：词表感知是必要的（v1 的 spec 全部用了真实词表，不再是
字典错配），但不充分；放宽多帧覆盖只是换漏为误。残尾 3 题 + 留出 2 题的共同
残余是**抽取时的语义帧发散+实体丢失**——这是写时选择，读时无法挽回。

**这反向论证了 stage-1 设计的另一半是必做项**：typed-record 要在 M1 抽取端
约束**有界规范词表**（canonical frame，如 visit↔doctor 固定帧、use↔service、
bake 固定于烘焙义），并显式抽取 participant/counterparty（医生实体）。否则
字段是"每题一批新词表"，任何 spec 都对不齐。

## 工程必备件（两连证实）

聚合空集/异常必须回落 flat 通道：留出 2 题 flat 本来就对（8, 3），机械聚合
两臂都把它们算错（3.0/0.84/0/5）——**空结果回落条款是准入门槛**，否则
typed 字段把已对的题改错，净效果是负的。

## 下一步候选（修订后）

- ~~a) spec 词表感知~~ 已测：2/5，边界在抽取帧发散，spec 侧无解
- **b') M1 canonical frame + participant 抽取**（原 b 强化版）：摄入提示词给
  有界 verb lexicon（visit/camp/use/bake/attend…固定语义），并要求
  counterparty 落人名实体。这是唯一未证伪的方向，且顺带治 cat3 多跳
  （链式推理同样要规范实体）。需重摄入 150 题快照→烧模型预算，建议
  待 jing fu 拍板
- c) 聚合空集回落 flat（代码小修，可独立先做）
- d/e) cat3 多跳、基线对擂——原板上选项不变

## 成本

本臂 ~14 次 Atria spec 调用（7 题 × 2 臂，含重试），零重摄入、零判题——
全部确定性求值。数据: spec_gen_results.json / spec_gen_results_v2.json，
代码: spec_gen.py（ARM=v2 切换两臂）。

---

# 追加臂（同日）：stage-3b canonical-frame 打标探针

stage-3 双臂把边界定位到"抽取写时的帧发散+实体丢失"后，直接测了**最小成本
修法**：不动 schema、不动管道，只在摄入提示词加四条规范帧条款
（`FIELDS_V3_SYS`：有界动词帧 visit/use/camp/bake/eat/view/buy/exchange/lent；
object=被作用实体非话题；counterparty 必填人名实体；obligation 记录算
asserted 不算 planned），重打标 5 道未救回题的快照（~35 次 Atria 调用）。

## 字段级变化（compare_v3.py 逐条 diff）

- `try`→`bake` ×4（烘焙词表收拢），`attend`→`visit`/`camp`，
  `camping_trip`→`camp`，`schedule`→`visit`——动词规范化生效
- object 落到实体：`mole biopsy appointment`→`Dr. Lee`，
  `camping trip`→`Yellowstone National Park`
- counterparty 新填充 +43 处（Domino's/Uber Eats/Fresh Fusion/Dr./Zara…）
- 干洗西装 `kind planned→asserted`（义务条款生效）；犹他"没露营"行程
  `asserted→negated`（否定修正生效）

## 端到端实测：v1 spec 生成臂原样重跑（同提示词同求值，只换 _v3 字段）

| qid | gold | v1-spec on v2字段 | v1-spec on **v3字段** | flat |
|---|---|---|---|---|
| 0a995998 | 3 | 2 ✗ | **3 ✓** | 2 |
| 88432d0a | 4 | 3 ✗ | 3 ✗ | 5 |
| d682f1a2 | 3 | 0 ✗ | 0 ✗ | 2 |
| gpt4_7fce9456 | 4 | 4 ✓ | 4 ✓ | 5 |
| 7024f17c | 0.5h | 0.5 ✓ | 0.5 ✓ | 拒答 |
| b5ef892d(留出) | 8d | 3.0 ✗ | 10.0 ✗ | 8 ✓ |
| gpt4_f2262a51(留出) | 3 | 0 ✗ | **3 ✓** | 3 ✓ |
| **合计** | | 2/5·0/2 | **3/5·1/2**（净 4/7） | |

**结论转正：prompt 级 canonical frame 真救回两道**（义务题+医生题），
验证"写时规范帧"路线有效——这正是 stage-3 双臂预测的唯一未证伪方向。

## 新残余（全部可诊断、工程形）

1. **when_abs 覆盖缺口**：黄石露营 v3 里 when_abs 从 2023-03 退成 null——
   window 子句丢它；建议抽取侧"无日期回退记录日（day）"或 spec 侧
   window 对 null 日期宽容档（确定性小修）
2. **dup 误并**：两次不同日期的 sourdough 烘焙（05-16 首试 / 05-23 复烤）
   被 dup pass 同物不同期并成一事——dup 判据漏了"时间重叠"校验
3. **DSL 缺 counterparty 选择器**：v3 已把实体打进 counterparty，spec DSL
   里却没有字段选它（d682f1a2 三条服务记录全靠 counterparty 可解）
4. **语义边界题**："7天犹他road trip" verb=travel 被 spec 词表误收
   （v3 字段本身已正确区分 camp vs travel，是 spec 写手多收）——
   确定性验证：`verbs=[camp]` 单选即得 3+5=8=gold

残余不再是概念问题，是三个确定性小修 + spec 写手的克制问题。
