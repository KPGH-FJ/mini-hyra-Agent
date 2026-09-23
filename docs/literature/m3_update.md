# M3 Update（持续更新）文献调研纪要

> 调研对象：新记录、纠错、撤回、过期、遗忘、压缩如何在"理解资产"内传导。
> 对应架构文档 §1 M3 与 §7 遗留问题（retraction 传导深度、时态探针）。
> 评价语境：LifeStream 协议——`update/correction/retraction/expires_day/forget`
> 是 M3 必须处理的更新算子；`stale/retract/prov` 探针专门考"更新是否真实生效"。

## 0. 问题界定：LifeModel 的更新算子

先把记录流里的更新语义列成算子表——后面每个方法族都拿这张表对号入座：

| record kind / 操作 | 语义 | 逻辑对应 | 数据层对应 |
|---|---|---|---|
| `statement`（首次断言） | 新增信念 | expansion | 插入 |
| `update`（真实变化：搬家、换工作） | **世界变了**，旧值曾经为真 | *update*（Katsuno–Mendelzon 意义下） | valid-time 新区间 |
| `correction`（纠正错误记录） | **我之前记错了**，旧值从未为真 | *revision* / contraction+expansion | tx-time 关闭旧行 + 新行 |
| `retraction` | 撤回某断言，不得再断言 | contraction + 派生级联失效 | 标记失效 / 级联清扫 |
| `suggestion`/`hearsay` | 非本人断言，不入 state | 带信源标注的弱信念层 | 低权威证据层 |
| `expires_day` | 硬过期边界（约束到期） | —（不是遗忘） | valid_to = expires_day |
| `forget(scope)`（M5 API） | 用户要求物理删除 | forgetting（签名收缩） | 删除 + lineage 清扫 |
| 资产压缩 | 省字节不丢语义 | logical forgetting / uniform interp. | snapshot + delta |

关键区分（调研中最重要的概念收获）：

- **update ≠ revision**。Katsuno & Mendelzon 1991 明确区分：revision 修正对
  静态世界的错误认知（取全局最小变化模型），update 响应世界本身的变化
  （对每个旧模型分别做最小变化）。LifeStream 的 `update`（决定翻转、偏好漂移）
  和 `correction`（记错了）正好对应这两个算子——**实现里混为一谈会丢掉
  "旧值曾经为真"的历史**，而 prov/stale 探针恰恰考这个。
- **supersede ≠ delete**。被取代的旧条目对 state/stale 探针必须"死"，
  但对 prov 探针（"本人是否说过 slot=v"）和部分时态查询必须"活"。
  撤回(retraction)同理是"不再断言"而非"从记忆抹去"；只有 `forget` 才要求
  真删除。→ 记账上需要的是**失效标记**，不是删除。
- **过期是硬边界不是衰减**。`expires_day` 是 valid-time 端点；
  ACT-R 式衰减只能用于检索优先级/压缩取舍，绝不能决定真伪状态
  （否则 stale 类探针会造假）。
- **传导是核心难点**。proposal U1 明说已有原型"部分纠正没有真正生效"——
  派生结论（摘要、归纳、跨槽推论）若不挂 provenance，撤回前提后它们照常作答。

## 1. 方法族分类学与代表工作

### 1.1 信念修正逻辑：AGM 与迭代修正

**代表工作**

- Alchourrón, Gärdenfors & Makinson (1985), *On the Logic of Theory Change:
  Partial Meet Contraction and Revision Functions*, JSL 50(2) — 定义三个算子：
  expansion `K+p`、contraction `K÷p`、revision `K*p`，以及 Levi identity
  `K*p = (K÷¬p)+p`、Harper identity `K÷p = K∩(K*¬p)`。partial meet contraction
  在所有"不再推出 p 的极大子集"（remainder sets）里做选择——
  **选择标准叫 epistemic entrenchment（认识论牢固度）**。
  <https://www.cambridge.org/core/journals/journal-of-symbolic-logic/article/abs/on-the-logic-of-theory-change-partial-meet-contraction-and-revision-functions/7ED837BAD5FB6D9A7C77906D73527F9C>
- SEP 综述 *Logic of Belief Revision*：完整公设（success、inclusion、vacuity、
  consistency、minimal change、recovery…）+ belief set vs belief base 之分。
  <https://plato.stanford.edu/ENTRIES/logic-belief-revision/>
- Katsuno & Mendelzon (1991), *Propositional knowledge base revision and
  minimal change*：把所有满足 Gärdenfors 公设的修正方案统一刻画为
  "对模型序的最小变化"；同作者 *On the difference between updating a
  knowledge base and revising it* 区分 update/revision（见 §0）。
  <https://www.sciencedirect.com/science/article/abs/pii/000437029190069V>
- Darwiche & Pearl (1997), *On the logic of iterated belief revision*：
  AGM 公设只约束单步修正；序列修正要保留"条件信念"，必须给知识库挂上
  额外结构（epistemic state ≈ entrenchment ordering），给出 C1–C4 公设。
  <https://doi.org/10.1016/s0004-3702(96)00038-0>
- belief base 修正（Hansson 的 kernel contraction 等）：对**信念基**（显式
  句子集）而非演绎闭包操作；incision function 负责"割掉哪些句子使 p 不再
  可推出"。对我们更贴切——资产里存的是条目，不是其闭包。

**对本模块的启示**

- AGM 给的是**算子的契约词汇表与性质测试**，不是机制：success（修正后必须
  推出新事实）、consistency、minimal change。这些公设可直接翻译成
  LifeStream 探针性质：`correction` 后 state 必须给新值（success）、
  不得同时保留新旧（consistency）、无关槽位不得动（minimal change）。
- entrenchment ordering 是"冲突时保谁"的排序——在 LifeModel 里可落地为
  **信源强度 × 时效**排序（self > doc > device > assistant > hearsay，
  同级新近者优先），这正是 M1 归一化事件里的 `source` 字段的用途。
- **recovery 公设是反面警示**：AGM contraction 设计上满足"先删再加能恢复
  原状"；但 `retraction`/`forget` 要求删除是**不可逆**的——不可恢复的
  contraction（或 base 层删除）才是正确语义。
- AGM 框架本身不带 provenance、不处理"派生内容随前提失效"——那是 TMS 的事
  （§1.2）。直接拿 AGM 当实现会导致 U1 问题重演。

### 1.2 依赖追踪：真值维护系统（TMS）

**代表工作**

- Doyle (1979), *A Truth Maintenance System*, AI 12(3):231–272（JTMS 原型）：
  每个节点带 support-list justification（前提清单）；节点状态只有 IN/OUT；
  前提变 OUT 时所有以它为 justification 的节点级联转 OUT；
  非单调 justification 支持 dependency-directed backtracking。
  <https://doi.org/10.1016/0004-3702(79)90008-0>
- de Kleer (1986) ATMS 三篇（*An assumption-based TMS* / *Problem solving
  with the ATMS* / *Extending the ATMS*, AI 28(2)）：每个结论标记的不是
  单一上下文而是**全部极小前提集（environments）**；不一致环境标记 nogood；
  撤回一个假设 → 所有 env 含该假设的结论同时失效，且多上下文查询免费。
  <https://doi.org/10.1016/0004-3702(86)90080-9>

**对本模块的启示**

- TMS 是"correction must actually propagate"的**唯一直接机制**：派生内容
  在形成时登记 justification（= 依赖的 record id 集合），撤回/纠错触发
  级联失效。这正是架构文档 §7 "TMS 式级联失效是 M3 首个候选"的出处。
- JTMS（单上下文，IN/OUT）实现轻；ATMS（每节点全部极小支持集）表达力强、
  天然回答"这个结论还凭什么成立"——prov 探针的免费副产品。但 ATMS 的 env
  集合可能指数膨胀；90 天流规模下 JTMS 大概够用。
- 工程接口含义：**M2 产出的每个派生条目必须携带 supports=[record ids]**。
  这是对 M2 接口的最小要求，越早冻结越好——否则 TMS 路线没法插进来。
- 同一事实多路支持的情况（本人说过 + doc 也有）：撤回一路后结论应存活。
  JTMS 天然处理（还有其他 justification）；counting 算法（§1.3）是
  同一思想的数据库版本。

### 1.3 事件溯源与增量视图维护

**代表工作**

- Fowler, *Event Sourcing*：应用状态 = 事件日志的重放投影；纠正用
  retroactive event（逆事件/调整事件），支持 complete rebuild、temporal
  query、snapshot+delta 混合。
  <https://www.martinfowler.com/eaaDev/EventSourcing.html>
  <https://www.martinfowler.com/articles/201701-event-driven.html>
- Gupta, Mumick & Subrahmanian (1993), *Maintaining views incrementally*
  （含 **counting algorithm** 与 **DRed**）：物化视图增量维护——
  counting 给每个派生 tuple 记"推导路径数"，删除至 0 才真正消失；
  DRed 对递归视图先过度删除再重新推导。视图定义含 negation/aggregation。
  <https://psycnet.apa.org/doi/10.1145/170036.170066>
  综述：Gupta & Mumick (1995), *Maintenance of Materialized Views*,
  IEEE Data Eng. Bull. 18(2)。<https://vldb.org/dblp/db/journals/debu/GuptaM95.html>
- McSherry et al. (2013), *Differential dataflow*（Naiad）：状态按偏序版本
  维护，增量算到任意版本——嵌套迭代计算也能增量。
  <https://www.cidrdb.org/cidr2013/Papers/CIDR13_Paper111.pdf>
- Noria (OSDI'18)：工业级增量物化视图数据流（partially-stateful，
  可逐出少用状态）——"给所有查询都维护视图"是可行的。
  <https://pdos.csail.mit.edu/papers/noria:osdi18.pdf>

**对本模块的启示**

- 天然的结构映射：**M1 的归一化记录流就是 event log；理解资产是它的
  物化视图；update/correction/retraction 只是新事件类型**。这条路线给出
  "正确性地板"——任何东西失效不了就 replay 重建。
- 成本轴上的两个极端：纯 replay（对探针全量回放）正确但 probe_bytes 爆掉
  （现有 seed 的 `answer()` 就是这么花冤枉钱的）；增量维护省字节但要求
  依赖信息——**IVM 的 counting/DRed 正是 TMS 级联失效的数据库实现**，
  两者在 M3 这里是同一件事的两种表述。
- snapshot+delta 混合（Fowler 明说了）给"压缩不丢语义"一条工程路线：
  ckpt 处存投影快照，之后只留增量；资产字节数可控，as-of 查询仍可对。
- retroactive event（把"纠正"当成针对过去事件的逆事件追加，而非就地改
  历史）与 bitemporal 的 tx-time 关闭（§1.4）是同一机制。

### 1.4 双时态语义（bitemporal）

**代表工作**

- Snodgrass 等，TSQL2（1994）：区分 valid time（现实为真的时间）与
  transaction time（数据库记录的时间）；bitemporal 表同时带两个维度。
  <https://doi.org/10.1145/181550.181562>
- Jensen & Snodgrass, *Temporal Data Management*, TKDE 1999（概念综述）。
- Kulkarni & Michels (2012), *Temporal features in SQL:2011*：
  标准化落地——application-time period（valid）+ SYSTEM_TIME 版本化
  （transaction）；删除/更新都实现为"关闭区间 + 新行"，历史不可篡改。
  <https://sigmodrecord.org/2012/09/30/temporal-features-in-sql2011/>
- 工业实现参考：Zep/Graphiti 的双时态边（详见 §1.7）——
  `valid_at/invalid_at`（valid time）+ `created_at/expired_at`
  （transaction time），矛盾检测后旧边置 `invalid_at` 而非删除。
  <https://getzep-graphiti.mintlify.app/concepts/temporal-model>

**对本模块的启示**

- 双时态是 M3 的**记账基元**，一句话说清了我们一直混淆的两件事：
  - `update`（真变化）→ 旧行 valid_to 关闭，新行开新 valid 区间；
  - `correction`（记错）→ 旧行 tx_to 关闭（"我们不再认为它为真"），
    valid-time 维度按新信息修正；
  - `retraction` → tx-time 关闭 + 级联；
  - `expires_day` → 写入时的 valid_to；
  - prov/时态探针（"day40 时我以为是什么"）= 对 tx-time 的 as-of 查询，
    **这正是架构 §7 问的"时态探针"的形式基础**——双时态天然支持。
- supersede 链 = valid-time 区间链（同一 slot 的连续真值区间）+
  tx-time 版本链（同一事实的记录版本）。不需要物理链结构，区间即可。
- 边界：双时态只管**原子事实**的记账；派生结论（由多个事实推出）的失效
  仍然需要 §1.2/§1.3 的依赖追踪。双时态 + TMS 是互补的两层。

### 1.5 遗忘与衰减（认知架构与记忆系统）

**代表工作**

- ACT-R 陈述性记忆：chunk 激活 = base-level（历史有用度）+ 关联激活；
  base-level learning equation `B_i = ln Σ_j t_j^{-d}`（t_j = 第 j 次使用
  距今），来自 Anderson & Schooler (1991) 的理性分析——衰减反映
  "这条记忆现在被需要的几率"。Pavlik & Anderson (2005) 扩展出 spacing
  effect。<http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/workshops/2004/IntegratedTheory.pdf>
- Ebbinghaus 遗忘曲线 → MemoryBank（Zhong et al., AAAI 2024）：
  `R = e^{-t/S}`，S 由记忆强度/重要性调制；检索时按 R 排序，
  低于阈值的记忆可遗忘。<https://arxiv.org/abs/2305.10250>
- KR 逻辑遗忘（logical forgetting / uniform interpolation）：
  Lin & Reiter (1994) *Forget It!* <https://aaai.org/papers/0037-fs94-02-037-forget-it/>；
  Lang & Marquis (JAIR 2010) *A Knowledge Level Account of Forgetting*——
  遗忘 = 收缩签名，结果 = 原理论在缩小后语言上的全部推论。
  <https://jair.org/index.php/jair/article/download/11105/26298>

**对本模块的启示**

- 衰减的两个正确用途：(a) **检索优先级**——probe_bytes 压力下先查高激活
  条目；(b) **压缩取舍**——决定哪些低频细节可以丢进冷层/摘要层。
- 一个错误用途：让衰减决定 state 真伪。衰减是软回忆概率，LifeStream 的
  `expires_day` 是硬 valid_to——两者必须分开实现，否则 stale 探针造假。
- 逻辑遗忘给出"**compression without distortion**"的精确语义：缩小签名
  但在保留语言上推论等价——即"删掉某类细节，保证剩余部分的所有推论不变"。
  这是压缩算子的理论标尺：压缩后资产在保留 vocabulary 上的回答必须与
  压缩前一致。可作为压缩类种子的正确性定义。
- `forget(scope)`（M5 物理删除）语义上 = 对特定 slot/时间的 forgetting +
  派生清扫（依赖 §1.2 的 lineage）。

### 1.6 机器学习遗忘（unlearning）：能借鉴什么、不能解决什么

**代表工作**

- Cao & Yang (2015), *Towards Making Systems Forget with Machine
  Unlearning*, IEEE S&P：首次把"数据及其 lineage 一起忘掉"形式化；
  把学习算法转成 summation form，删一个样本只更新少数 summation。
  <https://yinzhicao.org/unlearning/UnlearningOakland15.pdf>
- Bourtoule et al. (2021), *Machine Unlearning*（SISA），IEEE S&P：
  数据分 shard/slice 训练，删除只需重训受影响 shard。
  <https://doi.org/10.1109/sp40001.2021.00019>
- 综述：*A Survey of Machine Unlearning*，arXiv:2209.02299。
  <https://doi.org/10.48550/arxiv.2209.02299>

**对本模块的启示**

- 对符号资产，unlearning 的核心难题（参数里散布的记忆）**不存在**——
  只要 lineage 可追，删除是精确的。这条线主要价值是两个设计隐喻：
  - **lineage-first**：派生数据必须登记"由谁推出"（与 TMS 同一要求，
    再次互相印证）；
  - **影响域分片**（SISA 思想）：让派生内容按"输入分片"组织，撤回时
    只需重建受影响分片而非全资产——即"撤回半径"的工程界。
- 它解决不了的部分：我们的"撤回"不是模型近似遗忘，而是**符号级语义传导**；
  certified removal 的概率界对符号资产是杀鸡用牛刀，但"删除后资产必须
  与'从未见过该数据'不可区分"这个判据可借用为 retract 探针的正确性定义。

### 1.7 LLM 记忆系统的工程做法（MemGPT / mem0 / Zep / A-MEM 等）

**代表工作**

- MemGPT (Packer et al., 2023)：main context（RAM）+ archival/recall
  storage（disk）；LLM 通过 function call 自我编辑记忆
  （core_memory_append/replace、archival_memory_insert/search）。
  <https://arxiv.org/abs/2310.08560>
- mem0 (Chhikara et al., 2025)：抽取候选事实 → embedding 检索相似记忆 →
  LLM 判 ADD/UPDATE/DELETE/NOOP；UPDATE 保留原 memory id 并留
  `old_memory` 历史；图变体再加实体关系抽取。LOCOMO 上胜基线。
  <https://arxiv.org/abs/2504.19413>
  （实现上是一个藏在 UPDATE 决策后的事件日志：
  <https://github.com/mem0ai/mem0/blob/main/mem0/memory/main.py>）
- Zep/Graphiti (2025)：episode（原始记录）不可变；实体边带四时间戳
  （valid_at/invalid_at/created_at/expired_at）；新事实矛盾时 LLM+规则
  检测 invalidation candidates，旧边置 invalid_at/expired_at **不删除**；
  查询天然支持"as of（valid）/as known at（tx）"两维。
  <https://arxiv.org/abs/2501.13956>
  <https://github.com/getzep/Graphiti>
- A-MEM (Xu et al., NeurIPS 2025)：Zettelkasten 式记忆网络；新记忆入库时
  分析历史记忆并建链，且**可触发既有记忆的上下文表示更新（memory
  evolution）**——软性传导，LLM 判定，不保证完备。
  <https://arxiv.org/abs/2502.12110>
- Generative Agents (Park et al., 2023)：反思/计划是 LLM 派生物，
  **不挂 provenance**——撤回原始观察后反思无法定位失效。反面教材。
  <https://arxiv.org/abs/2304.03442>
- 评测先例：LongMemEval (arXiv:2410.10813) 把 "knowledge updates" 单列为
  五大能力之一；商业系统在该项掉分显著——证明这是真实难点。
  <https://arxiv.org/abs/2410.10813>

**对本模块的启示**

- 这族系统的共性模式：**"原始记录不可变 + 派生层可写"** 的双层结构
  （Graphiti 的 episode vs edge 是最干净的版本）。映射到我们：
  归一化记录流 = episode 层（append-only），资产条目 = edge/derived 层。
- 共性短板：dedupe/矛盾检测靠 embedding 相似度 + LLM 判定——**召回式传导**，
  只能处理"语义相近"的旧条目，命中不了"由已失效前提推出但措辞不相似"的
  派生物。mem0 的 DELETE、A-MEM 的 evolution、Zep 的 invalidation
  candidates 都是这个量级的能力。这正是 U1"纠错没真正生效"的重灾区。
- 可借鉴的工程件：Graphiti 的四时间戳边（直接可抄作种子结构）；
  mem0 的 ADD/UPDATE/DELETE/NONE 决策协议（LLM-in-the-loop 更新的
  参考协议，可做成 M3 的一个可选算子实现）。

## 2. 适配性结论：谁最适合"纠错必须真正传导"

| 方法族 | 对传导的贡献 | 对本任务的局限 | 建议角色 |
|---|---|---|---|
| TMS（JTMS/ATMS） | **唯一直接的级联失效机制**；prov 免费 | 要求派生物登记 supports；env 可能膨胀 | **主力机制** |
| 双时态 | 原子事实的正确记账；stale/prov/时态探针语义 | 不管派生结论 | **记账基元** |
| 事件溯源 + IVM | 正确性地板（replay）+ 省字节的增量维护（counting/DRed） | 全量 replay 贵；增量需要依赖信息 | **骨架 + 兜底** |
| AGM/迭代修正 | 算子词汇表与性质测试；entrenchment=信源×时效 | 信念集框架无 provenance；recovery 公设与删除冲突 | **契约/测试规范** |
| update vs revision 区分 | 让 update/correction 不再混同 | — | **语义规定** |
| unlearning | lineage-first、影响域分片隐喻 | 为参数记忆设计，符号资产上问题不成立 | **设计隐喻** |
| 衰减（ACT-R/Ebbinghaus） | 检索优先级、压缩取舍 | 绝不能决定真伪 | **检索/压缩辅助** |
| 逻辑遗忘 | 压缩的正确性定义（保剩余语言全部推论） | 计算贵，只能小规模用 | **压缩语义标尺** |
| MemGPT/mem0/A-MEM | 工程参考（双层、决策协议、演化钩子） | 召回式传导，不保证 U1 | **结构参考，别当机制** |

**推荐组合（v0 候选骨架）**：
双时态账本记原子条目（事实层）+ JTMS/计数法管派生条目（推论层）+
事件日志作 append-only 真相源（审计层）。纠正/撤回 = 新事件 → tx-time 关闭
旧条目 → 沿 justification 图级联失效 → 派生层重推导或标记失效。
这条链上每一环都有成熟对应物，且全程无 LLM 即可保证传导完备——
LLM 只在"判定两条目是否矛盾/谁优先"时可选接入（mem0 式决策协议）。

## 3. 候选方法 → seeds/baselines 编码清单

每个种子解给：结构 / 更新语义 / 成本画像 / 主要探针收益 / 风险。

- **S1（现有基线，保留对照）**：last-write-wins slot 账本。
  成本画像：asset≈O(记录全文)，probe≈全量回放（现状）。角色：下界。
- **S2 双时态 supersede 链账本**：slot → 区间链 `{value, valid_from, valid_to,
  tx_from, tx_to, source, rec_id}`。state/stale 按 ckpt 两维点查；
  prov 查 tx 维。asset 只存值不存文本 → asset_bytes 大降；
  probe 只查该 slot 链 → probe_bytes 大降。收益：stale/prov/expires。
  风险：派生结论仍无传导（state 之外靠运气）。
- **S3 JTMS 派生层**：S2 之上，每个派生条目（摘要、归纳、跨槽约束）登记
  `supports=[rec_id]`；retraction/correction 时沿 justification 图级联
  OUT；多 justification 存活语义（counting）。收益：retract 探针、
  派生一致性。成本：supports 数组 + 失效标记（小）。风险：依赖 M2 在形成
  派生物时如实登记——接口约束。
- **S4 事件溯源 + 增量投影**：append-only 事件层 + 可重建投影（带 ckpt
  快照）。answer 只读投影。收益：正确性地板、可审计、时态查询天然。
  成本：事件层仍需紧凑编码（否则 asset_bytes 高）；probe_bytes 低。
  角色：兜底/对照——"任何传导 bug 都可以用 replay 验证"。
- **S5 ATMS 变体**：条目挂极小支持集集合（多上下文）。收益：prov 探针
  满分语义（"该结论的全部最小依据集"）、多路支持天然。风险：env 膨胀；
  90 天规模多半可控但作为高风险高收益种子。
- **S6 AGM 算子层**：把 M3 算子实现为 expand/revise/contract +
  entrenchment 排序（source 强度 × 新近度），性质用公设做断言自检
  （success/consistency/minimal-change）。收益：update/correction 语义清晰；
  风险：本身无机制，须叠在 S2/S3 上——适合做"算子接口规范"种子。
- **S7 衰减辅助检索**：条目加 ACT-R 式激活分（使用次数×新近度），
  仅用于 probe 检索排序与压缩淘汰；`expires_day` 仍为硬边界。
  收益：probe_bytes 再降；风险：衰减门槛调坏会让 state 探针漏答。
- **S8 mem0 式 LLM 决策协议**：更新时 retrieve top-k 相似条目 → LLM 判
  ADD/UPDATE/DELETE/NONE（留 old_memory 历史链）。收益：LLM-in-the-loop
  更新的参照系；成本：llm_tokens>0（被显式计费）；风险：传导不完备，
  预计 retract/stale 输给 S3——作为对照种子有价值。
- **S9 压缩不失真子问题**：快照 + 增量（Fowler 式）或逻辑遗忘式压缩
  （小范围条目合并，验证保推论等价后再落盘）。收益：asset_bytes；
  正确性判据直接借 Lang & Marquis 定义。风险：验证成本。

**建议登顶顺序**：S2（记账基元，必做）→ S4（正确性地板，便宜）→
S3（传导主力，U1 直接得分点）→ S7/S9（成本优化）→ S5/S6/S8（对照实验）。

## 4. 给评测器/接口的对齐提示

- 探针 ↔ 机制映射：state→S2 点查；stale→S2 valid/tx 区分 + S3 失效；
  prov→S2 tx 维 / S5 env；retract→S3 级联；transfer→S7 检索排序 +
  派生条目；成本→资产序列化字节（S4 事件层要紧凑）。
- 防作弊面：保留全量原文过 prov 会爆 asset_bytes；answer 全量回放过
  correctness 会爆 probe_bytes（现有 seed 已踩）；supersede 后物理删除
  会错杀 prov——判分上要区分"不再断言"与"从未断言"。
- 新探针建议（回 §7）：**时态探针**（`as_of=d` 问 day-d 时刻的 state——
  考 tx 维）值得加，双时态实现免费支持，ledger 实现露馅。
- 对 M2 的接口要求（建议写入接口契约）：派生条目必须携带
  `supports=[rec_id]`（或 envs）；否则一切传导机制无从挂载。

## 5. 参考文献（均为真实链接）

信念修正
- Alchourrón, Gärdenfors & Makinson 1985 (JSL):
  <https://www.cambridge.org/core/journals/journal-of-symbolic-logic/article/abs/on-the-logic-of-theory-change-partial-meet-contraction-and-revision-functions/7ED837BAD5FB6D9A7C77906D73527F9C>
- SEP, Logic of Belief Revision: <https://plato.stanford.edu/ENTRIES/logic-belief-revision/>
- Darwiche & Pearl 1997: <https://doi.org/10.1016/s0004-3702(96)00038-0>
- Katsuno & Mendelzon 1991 (revision):
  <https://www.sciencedirect.com/science/article/abs/pii/000437029190069V>;
  update vs revision: <https://doi.org/10.1017/cbo9780511526664.007>

TMS
- Doyle 1979 TMS: <https://doi.org/10.1016/0004-3702(79)90008-0>
- de Kleer 1986 ATMS: <https://doi.org/10.1016/0004-3702(86)90080-9>;
  ATMS problem solving: <https://doi.org/10.1016/0004-3702(86)90082-2>;
  extending: <https://doi.org/10.1016/0004-3702(86)90081-0>;
  PDF: <https://www.dekleer.org/Publications/An%20Assumption-Based%20TMS.pdf>

事件溯源 / 视图维护 / 数据流
- Fowler Event Sourcing: <https://www.martinfowler.com/eaaDev/EventSourcing.html>;
  event-driven 辨析: <https://www.martinfowler.com/articles/201701-event-driven.html>
- Gupta, Mumick & Subrahmanian 1993 (counting/DRed):
  <https://psycnet.apa.org/doi/10.1145/170036.170066>;
  survey 1995: <https://vldb.org/dblp/db/journals/debu/GuptaM95.html>
- Differential dataflow: <https://www.cidrdb.org/cidr2013/Papers/CIDR13_Paper111.pdf>
- Noria (OSDI'18): <https://pdos.csail.mit.edu/papers/noria:osdi18.pdf>

时态数据库
- TSQL2 spec: <https://doi.org/10.1145/181550.181562>
- Kulkarni & Michels, SQL:2011 temporal:
  <https://sigmodrecord.org/2012/09/30/temporal-features-in-sql2011/>
- Jensen & Snodgrass bitemporal semantics (NYU archive):
  <http://archive.nyu.edu/handle/2451/14356>

遗忘 / 衰减
- ACT-R activation & base-level learning:
  <http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/workshops/2004/IntegratedTheory.pdf>
- MemoryBank (AAAI 2024): <https://arxiv.org/abs/2305.10250>
- Lin & Reiter, Forget It!: <https://aaai.org/papers/0037-fs94-02-037-forget-it/>
- Lang & Marquis, A Knowledge Level Account of Forgetting (JAIR 2010):
  <https://jair.org/index.php/jair/article/download/11105/26298>

unlearning
- Cao & Yang 2015: <https://yinzhicao.org/unlearning/UnlearningOakland15.pdf>
- Bourtoule et al. SISA 2021: <https://doi.org/10.1109/sp40001.2021.00019>
- Survey: <https://doi.org/10.48550/arxiv.2209.02299>

LLM 记忆系统
- MemGPT: <https://arxiv.org/abs/2310.08560>
- mem0: <https://arxiv.org/abs/2504.19413>
- Zep/Graphiti: <https://arxiv.org/abs/2501.13956>;
  双时态实现文档: <https://getzep-graphiti.mintlify.app/concepts/temporal-model>;
  代码: <https://github.com/getzep/Graphiti>
- A-MEM: <https://arxiv.org/abs/2502.12110>
- Generative Agents: <https://arxiv.org/abs/2304.03442>
- LongMemEval: <https://arxiv.org/abs/2410.10813>
