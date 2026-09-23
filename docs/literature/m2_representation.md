# M2 表征（Store）文献调研纪要

> 对应 `docs/LIFEMODEL_ARCHITECTURE.md` 的 M2：理解资产的**存储结构本体**——
> 事实/关系/目标/偏好/约束/不确定度如何落盘，一个人的状态随时间如何被表征。
> M3（更新传导）与 M4（视图生成）在别的纪要里；本文只管"摆什么结构"以及
> "这个结构天然支持/不支持哪些更新语义与查询形态"。
>
> 评测锚点（`tasks/life_model/`）：state / stale / prov / retract / transfer
> 五类探针 + 成本（asset_bytes、probe_bytes、llm_tokens）。每条方法都对照
> 这五类探针和成本来评，不空谈"表达力"。

## 0. M2 的问题定义

M2 要在一条多源、含噪、会变、可纠错可撤回的记录流上，维护一份：

- **可纠正**——correction 要真正取代旧值并传导到派生内容（LifeStream 的
  stale/prov 探针就是抓"旧值没死透"）；
- **带不确定度与溯源**——同一断言要知道谁说的（self/hearsay/device…）、
  多可信、哪条记录说的；
- **带时间**——"day40 时我认为是 X，day60 改成了 Y"要能同时成立，
  互不污染；
- **跨用途复用**——一份积累，多种视图（状态查询、沿革查询、打包迁移、
  自由问答），不能每种用途重新建一份；
- **便宜**——asset_bytes 与 probe_bytes 都计入总分，LLM 参与维护要扣
  token 成本。

## 1. 表征方法族分类（taxonomy）

```
                    抽象程度 →
原始日志      显式事实     结构化关系      压缩/索引形态      参数化
─────────  ─────────  ─────────────  ───────────────  ───────────
A 事件日志   B 槽位账本   C 符号 KR      F LLM 记忆系统     H 参数记忆
(append-     (frames/    (语义网/        (分层/自编辑/      (权重即记忆,
 only,       slot KV,   RDF/PKG,      抽取+巩固,         不可读)
 MyLifeBits, ledger)    TMS 标签)      Zettelkasten)
 事件溯源)
            D 双时态表   E 时态知识图谱  G 层级摘要树
            (Snodgrass, (Zep/Graphiti) (RAPTOR/GraphRAG/
            TSQL2,      边带            HippoRAG)
            SQL:2011)   有效/事务时间)

正交维度（不是一族，而是每条断言都要带的注解）：
I 不确定度与溯源标注（confidence / provenance / 信源权威度）
J 依赖与修正结构（TMS justification、ATMS 假设集、supersede 链、
  派生物注册表）——表征层决定"删除/纠错能传导多远"的上限
```

一条重要经验：**真实系统几乎全是混合**。Graphiti 是 C+E+F+I 的混合
（episode 原始层 + 双时态实体边 + community 摘要层）；mem0 是 B+E+F；
Generative Agents 是 A+F（事件流 + 反思树）。下面的家族是按"主导表征"
分类的。

## 2. 各方法族：代表系统与要点

### A. 原始保留：事件日志 / lifelog store / 事件溯源

- **MyLifeBits**（Gemmell, Bell, Lueder, CACM 2006, doi:10.1145/1107458.1107460;
  项目页 https://www.microsoft.com/en-us/research/project/mylifebits/）：
  Memex 构想（Bush 1945, https://www.theatlantic.com/magazine/archive/1945/07/as-we-may-think/303881/）
  的工程版——个人全部记录进 SQL Server，靠超链接/注解/facets 检索。
  教训："存一切"验证过可行（~1TB/人生），但论文明确说**管理工具
  比存储难**；原始存留不产生"理解"。
- **事件溯源**（Fowler, https://martinfowler.com/eaaDev/EventSourcing.html）：
  状态 = 事件日志的折叠；天然支持 as-of 重建、回放修正、审计。
  LifeStream 的 `raw` 基线与 seed `asset.py` 本质都是这类：
  对错全靠查询时重新演绎。
- 要点：保真无损、provenance 天然、删除（M5 forget）语义上却最难
  （append-only 与"真删"矛盾，需要 tombstone + 投影层真正消化）。

### B. 显式事实账本：槽位 / 属性-值 / frames

- **Frames/slots**（Minsky, "A Framework for Representing Knowledge",
  MIT AI Memo 306, 1974, https://web.media.mit.edu/~minsky/papers/Frames/frames.html）：
  slot 带默认值、facet（值域约束、"何时更新"）——槽位+元注解的思想
  直接是 LifeStream slot 模型的祖宗。
- **当前 seed**（`tasks/life_model/seed_solution/asset.py`）：
  last-write-wins per slot，正确但无历史、无冲突面。
- **mem0 的 fact 层**（下详）本质也是"自然语言事实账本"+ LLM 裁决
  ADD/UPDATE/DELETE/NOOP——账本族在 LLM 时代的形态。
- 要点：state/stale 探针最便宜（O(1) 查槽）；弱点是表达不了关系、
  多值、条件、以及"我不知道"（未知 vs 空值 vs 冲突要区分）。

### C. 符号知识表征：语义网 → 描述逻辑 → RDF → 个人知识图谱

- 语义网/描述逻辑一脉（Woods 1975 "What's in a Link"；KL-ONE,
  Brachman & Schmolze 1985, Cognitive Science 9(2):171–216）给出了
  断言式知识的形式化：个体/概念/角色（关系）+ 继承 + 受限推理。
- **RDF/三元组**（https://www.w3.org/TR/rdf11-concepts/）+ 属性图是
  现代 KG 的底物。
- **个人知识图谱 PKG**：Balog & Kenter 2019 研究议程
  （doi:10.1145/3341981.3344241）——PKG 与通用 KG 的三点差异直接命中
  LifeModel：实体无需全局重要性、用户永远是中心节点、与外部数据源
  集成是内生属性。生态综述（Skjæveland et al. 2024,
  doi:10.1016/j.aiopen.2024.01.003；WIDM 综述 doi:10.1002/widm.1513）
  把人口/表征/利用三段拆开，可直接当 checklist。
- **NEPOMUK Semantic Desktop 的 PIMO 本体**
  （https://www.semanticdesktop.org/ontologies/2007/11/01/pimo/）：
  早于 LLM 的"个人知识工作台"——把桌面资源映射进个人信息模型。
  它失败在生态而非思想；其教训是**本体过重的个人 schema 没人维护**。
- **Solid POD**（https://solidproject.org）：用户自持数据仓的所有权
  架构参照（M5 出口/所有权侧）。

### D. 双时态数据库（supersede/correction 的教科书）

- **Snodgrass《Developing Time-Oriented Database Applications in SQL》**
  （Morgan Kaufmann 1999, 全文 https://archive.org/details/developingtimeor0000snod）：
  - **valid time**：事实在现实世界成立的时间；
  - **transaction time**：事实被数据库记录/仍为当前信念的时间。
  纠错 = 关闭旧断言的 transaction 区间 + 开新断言，**永不覆盖**；
  "day40 时我以为 X" 正是 transaction-time as-of 查询——这直接回答
  架构文档 §7 遗留问题里的"时态探针"缺口。
- **TSQL2**（规范 https://www2.cs.arizona.edu/people/rts/initiatives/tsql2/finalspec.pdf）
  及其沉淀进 **SQL:2011** 的 system-versioned / application-time 表
  （ISO/IEC 9075-2:2011）：时态表已经是标准工程件，SQLite/PG 也能
  手工实现（两张时间列 + 查询约束）。
- 工程实现参照：**XTDB**（https://xtdb.com，双时态文档库）；
  **Datomic**（https://www.datomic.com，仅事务时间，不可变事实断言
  /撤销式 retract 与 LifeStream kind 语义几乎一一对应）。
- 要点：stale/prov/retract 三族探针在双时态下是**免费能力**；
  代价是每条事实多带 4 个时间戳和查询时的有效性判断（probe_bytes
  可控——只读当前有效行）。注意"真空清理/vacuuming"是标准操作：
  历史保留策略本身就是设计杠杆（asset_bytes）。

### E. 时态知识图谱：Zep/Graphiti

- **Zep**（Rasmussen et al., arXiv:2501.13956,
  https://arxiv.org/abs/2501.13956；开源 https://github.com/getzep/graphiti）：
  目前最接近"一个人的持续理解资产"的工业件。Graphiti 三层结构
  （文档 https://getzep-graphiti.mintlify.app/concepts/temporal-model
  与 /concepts/episodes）：
  - **Episodic 层**：原始 episode 永不丢，带 valid_at（内容发生时间）
    与 created_at（摄入时间）——原始层做 ground truth 与溯源锚点；
  - **实体/边层**：`EntityEdge` 带双时态四字段 `valid_at/invalid_at`
    （世界时间）与 `created_at/expired_at`（系统时间）；新事实与旧边
    冲突时**置 invalid_at 而不删**；
  - **Community 层**：定期聚类实体生成社区节点+摘要（GraphRAG 式
    全局视图）。
  - **MENTIONS 边**：每个实体/边挂回来源 episode，provenance 一等公民。
  - 语义：entity/edge 抽取、去重、失效判定都由 LLM 做（token 成本）；
    检索是 hybrid（语义+BM25+图 BFS）。LongMemEval 上较基线最高
    +18.5% 准确率、延迟 -90%。
- **时态 KG 嵌入**一脉（综述：Cai et al. IJCAI 2022,
  https://arxiv.org/abs/2201.08236）把时间编码进 embedding 做补全——
  紧凑但不可读、不可纠正（改一条要重训），对 M2 只作旁注。
- 要点：Graphiti 证明了"原始层 + 双时态断言层 + 摘要层"三段式能同时
  赢历史查询与当前状态查询；其 LLM-heavy 形成管道是 LifeStream 里的
  成本变量，可做 Graphiti-lite（规则抽取，无 LLM token）。

### F. LLM 记忆系统（表征是"给 agent 自己维护的记忆"）

- **MemGPT**（Packer et al., arXiv:2310.08560,
  https://arxiv.org/abs/2310.08560）：OS 分层内存隐喻——core memory
  （常驻上下文，persona/human 两块，**agent 自己用工具编辑**）+
  archival（向量库）+ recall（会话日志）；超限触发 self-directed
  换页。核心思想：**记忆是可编辑的结构化对象，读写在热路径上由
  LLM 决定**。
- **Letta**（MemGPT 的产品后继）：memory blocks 标签化、可共享、
  可只读；blocks 是系统 prompt 的持久段落
  （https://docs.letta.com/guides/core-concepts/memory/memory-blocks/）。
  表征极简（文本块），把全部智能压在编辑协议上。
- **Generative Agents**（Park et al., arXiv:2304.03442,
  https://arxiv.org/abs/2304.03442）：memory stream（全量观察日志）
  + 检索打分 = 近因+重要性+相关性加权 + **reflection**：周期性把观察
  归纳成更高层断言，形成断言树。教训：反思派生物**没有 provenance
  链回原观察**的话，纠错传不进去（LifeStream 正是抓这个）。
- **mem0**（Chhikara et al., arXiv:2504.19413,
  https://arxiv.org/abs/2504.19413；https://github.com/mem0ai/mem0）：
  抽取事实 → 与相似旧记忆一起喂 LLM 裁决 ADD/UPDATE/DELETE/NOOP →
  存稠密向量+可选图。LOCOMO 上 +26%（LLM-judge）、p95 延迟 -91%。
  要点：**更新决策被显式化**（每次摄入给出动作类型），这比"写日志
  事后查"更接近 correction 语义；但 DELETE 是逻辑删除策略而非真删。
- **LangMem**（LangChain, https://langchain-ai.github.io/langmem/）：
  把记忆分 semantic（事实）/episodic（事件）/procedural（行为规则）
  三型，热路径工具 + 后台 consolidation manager——分型本身是
  M2 设计词汇表：个人资产至少也要区分"事实断言/经历事件/偏好与
  行为倾向"。
- **A-MEM**（Xu et al., arXiv:2502.12110, NeurIPS 2025,
  https://arxiv.org/abs/2502.12110）：Zettelkasten 卡片式——每条记忆
  生成带 context/keywords/tags 的笔记，自动与历史笔记建立链接并
  **反向演化旧笔记的属性**。表征亮点：链接与标签让网络自组织，
  无固定 schema。
- **MemoryBank**（Zhong et al., arXiv:2305.10250, AAAI 2024,
  https://arxiv.org/abs/2305.10250）：日级摘要 + Ebbinghaus 遗忘曲线
  （按时间衰减+重要性强化）+ 人格蒸馏。把**遗忘做成表征内的显式
  强度字段**而非真删除——对应 LifeStream 的 expires_day 处理。
- **产品参照**：ChatGPT "saved memories"（OpenAI 2024-02,
  https://openai.com/index/memory-and-new-controls-for-chatgpt/）——
  事实清单式记忆，用户可见可改可删，是"记忆=用户可控资产"的
  量产先例。
- 评测侧参照：LongMemEval（arXiv:2410.10813）五能力——抽取/
  多会话/时态/知识更新/拒答；LOCOMO（arXiv:2402.17753）长会话
  记忆；综合综述 arXiv:2404.13501 与 CoALA 记忆分型
  （arXiv:2309.02427：episodic/semantic/procedural/working）。

### G. 层级摘要与图混合索引

- **RAPTOR**（Sarthi et al., ICLR 2024, arXiv:2401.18059,
  https://arxiv.org/abs/2401.18059）：embedding 聚类→摘要→递归建树，
  检索时按查询尺度取不同抽象层。QuALITY +20%。教训直接适用：
  **摘要树是只追加下层、更新需重写上游**的结构——LifeStream 里
  插入纠错会导致祖先摘要过期，若无失效标记就有 stale 泄漏。
- **GraphRAG**（Edge et al., arXiv:2404.16130,
  https://arxiv.org/abs/2404.16130）：实体 KG + Leiden 社区分层 +
  每层社区预生成摘要——**全局性问题（"这个人总体是怎样的人"）
  靠社区摘要，局部靠实体**；说明不同查询尺度需要不同索引形状，
  这正支持"一份资产多种视图"。
- **HippoRAG**（Gutiérrez et al., NeurIPS 2024, arXiv:2405.14831,
  https://arxiv.org/abs/2405.14831）：海马索引理论——KG 做新皮层
  长期记忆，OpenIE 三元组 + Personalized PageRank 做联想检索，
  多跳强于向量 RAG，更新是增量挂新节点。
- 要点：摘要/社区层是 transfer 与全局型探针的廉价答案，但**任何
  派生层都必须挂失效标记与 provenance**，否则成为不可纠正的
  化石信息源。

### H. 参数记忆（权重即记忆）——控制问题的反面教材

- LLM-as-KB（Petroni et al., arXiv:1909.01066）确立"参数能存事实"，
  但存的是不可读的概率分布。
- **模型编辑**：ROME（Meng et al., arXiv:2202.05262）、MEMIT
  （arXiv:2210.07229）可定点改事实，但 MQuAKE（arXiv:2305.14795）
  证明编辑在多跳/衍生查询上失败率高——**改一处不传导**，恰是
  U1 要验的反例。
- **遗忘/删除**：机器遗忘综述（arXiv:2503.01854；
  doi:10.1007/s10462-024-11078-6）共识是"近似遗忘"无法证明真删；
  灾难性遗忘（EWC, arXiv:1612.00796）使连续更新互相冲刷。
- 结论：参数记忆在 v0 不可行——不可审计、不可导出、不可定点删。
  但可作 M4 的隐藏对照组（"LoRA 一个自己"基线）证明可控表征的
  必要性。

### I. 不确定度与溯源标注（正交维度）

- **W3C PROV**（PROV-DM https://www.w3.org/TR/prov-dm/，
  PROV-O https://www.w3.org/TR/prov-o/）：Entity/Activity/Agent +
  wasDerivedFrom/wasAttributedTo 等——断言"谁产生、由什么活动、
  从哪派生"的标准词汇；LifeStream prov 探针就是 PROV 的最小版。
- **断言级注解**：RDF-star（https://w3c.github.io/rdf-star/cg-spec/）
  允许对单条三元组挂注解（置信度、有效期、来源）——这就是
  LifeStream 里 `source/kind` 需要落到的位置。
- **NELL**（Mitchell et al., CACM 2018,
  https://www.cs.cmu.edu/~tom/pubs/NELL-CACM-2018.pdf）：1.2 亿条
  **confidence-weighted beliefs**，多抽取器互证，冲突靠置信度裁决，
  还会自造谓词扩 ontology——个人资产需要的"开放 schema + 置信度"
  先例；其教训是低置信断言必须可隔离，否则会污染下游。
- **数据融合/真相发现**（Bleiholder & Naumann, ACM CSUR 2008,
  doi:10.1145/1456650.1456651；教程
  http://www.vldb.org/pvldb/vol2/vldb09-tutorial1.pdf；综述 Li et al.
  SIGKDD Expl. 2015, doi:10.1145/2811231.2811234）：多源冲突的策略
  分类（忽略/仲裁/投票/按源可信度加权）——LifeStream 的
  source∈{self,other,assistant,device,doc} 本质就是一套
  信源权威序，self > doc/device > other > hearsay/suggestion。
- **Lost in the Middle**（Liu et al., arXiv:2307.03172）：长上下文
  中部信息利用率塌陷——probe_bytes 不是越大越好，检索要窄而准，
  支持"结构化资产 + 窄查询"方向。

### J. 依赖与修正结构（决定删除/纠错能传导多远）

- **TMS**（Doyle, AI 1979, doi:10.1016/0004-3702(79)90008-0；
  全文 https://dspace.mit.edu/handle/1721.1/5733）：每条信念挂
  justification 集，撤回前提→非单调回滚所有依赖信念。这是
  "retraction 传导"的原始发明，M2 侧要存的结构就是
  `belief → supporting assertions` 依赖边。
- **ATMS**（de Kleer, AI 1986 28:127–162,
  https://www.sciencedirect.com/science/article/abs/pii/0004370286900802）：
  假设集 label——每条断言带"在哪些假设组合下成立"，多世界共存、
  上下文切换免费。对 LifeModel：可同时持有"本人说/传闻说/助手猜"
  的并行世界观而不互相污染。
- **AGM 修正**（Alchourrón–Gärdenfors–Makinson, JSL 1985,
  doi:10.2307/2274239）：contraction/revision 的合理性公设——
  纠正不是"替换值"而是"集合收缩+扩张"；与 ATMS 的连接见
  IJCAI'93 https://www.ijcai.org/Proceedings/93-1/Papers/075.pdf。
- **supersede 链**：版本链（新值指向被取代者），工程上是双时态的
  退化版（只留 valid-time 链）。
- 要点：这些结构是 M3 的动力源，但**边和注解必须在 M2 落库**——
  M2 不存依赖，M3 无从传导。

## 3. 对照表

| 系统/族 | 主导表征 | 更新语义 | 溯源 | 不确定度 | 成本形态 | LifeStream 强项/弱项 |
|---|---|---|---|---|---|---|
| 原文/事件溯源 | 全量记录 | 无（查询时演绎） | 天然 | 无 | asset 大、probe 大 | stale/prov 对，asset_bytes 差 |
| 槽位账本(seed) | slot→(值,day) | last-write-wins+硬删 | 隐式 | 无 | asset 小、probe 小 | state 好；无历史/冲突面 |
| 双时态表 | 断言×4 时间戳 | 闭区间不覆盖 | 记录级 | 需另加 | asset 中、probe 小 | stale/retract/prov 全免 |
| Graphiti | episode+双时态边+社区 | 边失效不删 | MENTIONS 一等 | 无显式 | LLM 贵、probe 中 | 时态+provenance 现成，token 成本 |
| MemGPT/Letta | 自编辑块+向量存档 | LLM 热路径改块 | 弱 | 无 | asset 小、probe 中 | 自编辑协议值得借 |
| Generative Agents | 观察流+反思树 | 追加+周期反思 | 反思断链 | 重要性分 | asset 大 | 反思树≈派生断言教训 |
| mem0 | 事实+向量(+图) | LLM 判 ADD/UPD/DEL | 事实级 | 隐式 | token 中 | 更新动作显式化 |
| A-MEM | Zettelkasten 笔记网 | 链接+反向演化 | 链接即溯源 | 无 | token 中 | 自组织免 schema |
| MemoryBank | 日摘要+强度字段 | 衰减/强化 | 弱 | 显著性分 | asset 小 | expires_day 的优雅解 |
| RAPTOR/GraphRAG | 摘要树/社区层 | 上游需重建 | 弱 | 无 | asset 中 | 全局视图便宜、stale 风险 |
| 参数记忆 | 权重 | 编辑/微调 | 无 | 隐式 | 训练贵 | 不可控，反面基线 |
| NELL | 置信度加权信念 | 互证+阈值 | 抽取器级 | 一等 | asset 中 | 置信度+开放谓词先例 |
| TMS/ATMS | 依赖边/假设集 | 级联失效 | justification | 假设维 | asset 中 | retract 传导的元结构 |

## 4. 对"个人 LifeModel"的取舍结论

1. **两个时钟不可省**。records 带 day（世界时间），资产摄入有先后
   （系统时间）；双时态是让 stale/retract/as-of 探针同时正确的唯一
   已知解。SQL 级实现已成熟，不需要图库。
2. **原始层必须保留为 ground truth**。Graphiti、mem0、MyLifeBits 都
   一致：派生断言会出错、会被撤回，唯一永真信源是原始记录。
   资产 = 原始 episode 层 + 断言层 + 派生层；三者都要有失效语义。
3. **删除是"断链+投影消化"而不是删字节**。append-only 日志 +
   tombstone + 投影层真正排除，比物理删文件对 probe 语义更干净
   （H 族反面：参数记忆想"真删"根本做不到）。
4. **每条断言挂三元注解**：(信源权威序, 置信度/强度, 双时态区间) +
   provenance 指针。LifeStream 的 source/kind/expires_day 已经给了
   三轴的雏形；置信度目前不用概率——分级的"断言/传闻/建议"已够用，
   NELL 教训是低置信要能被隔离。
5. **schema 会生长**。人不是固定领域：NELL 自造谓词、A-MEM 自组织
   标签、frames 需要预定义槽位——M2 应做"slot 集合开放"的 KV+关系
   混合，别定死本体。
6. **按查询尺度备多种视图**。GraphRAG/RAPTOR 证明全局问与局部问
   要不同索引；LifeModel 同理——同一断言层上挂：slot 索引（state/
   stale）、按 provenance 的记录索引（prov）、时间窗摘要
   （transfer/全局）。视图可重建，断言层才是资产。
7. **probe_bytes 是独立成本轴**：Lost-in-the-Middle 说明"多给料"
   反而降质；结构化的窄接口（slot 定向、as-of 快照）比全文回放
   质量与成本双赢。
8. **反射/摘要必须挂失效位**：GenAgents 反思树、RAPTOR 上层节点的
   共同缺陷——上游记录被纠正后下游摘要不自知。M2 给每条派生内容
   记 `derived_from` 集，M5/M3 才有抓手。

## 5. 候选方法清单（转成 seeds/baselines，按实现成本排序）

均为纯 Python、无 LLM token 的 v0 种子（LLM 变体另行标注）：

| # | 种子名 | 表征 | 更新/答案语义 | 预期强项 | 成本 |
|---|--------|------|---------------|---------|------|
| S1 | **bitemporal-ledger** | slot→断言列表，每条带 (value, valid_day, tx_day, kind, source, expires_day, retracted) | 当前值=最新未失效 self 断言；as-of 按双时钟过滤 | state/stale/retract/as-of 全对 | asset 中、probe 小 |
| S2 | **supersede-chain** | S1 的退化版：slot→版本链，新值指向旧值 | stale 探针查链头；prov 沿链找历史 | 实现最简 | 同 S1 |
| S3 | **episode+fact 双层（Graphiti-lite）** | 原始记录层 + 事实层（subject/slot/relation/value + 双时态 + 溯源记录 id） | 事实层答 state/stale；prov 回查记录层 | prov/transfer 好，hearsay（他人对象）有地方放 | asset 中 |
| S4 | **slot+窗摘要混合** | S1 + 每 N 天滚动摘要 + 派生物 `derived_from` 集 | 摘要答 transfer/全局问；断言层答点查 | transfer 命中率高 | probe 中 |
| S5 | **置信度注解账本（NELL-lite）** | 断言带 (权威级, corroboration) | 冲突双存不合并，回答按权威序取顶 | hearsay/suggestion 不误用 | 同 S1 |
| S6 | **向量+槽位混合** | S1 + 记录 embedding 索引 | transfer/开放问走向量召回，点查走 slot | 覆盖新探针型 | asset/probe 中 |
| S7 | **event-sourced 投影** | 记录=事件；state=fold；materialized 当前视图缓存 | as-of=截断重放；retraction=新事件 | as-of 最干净 | probe 小、asset 大 |
| S8 | **TMS-lite 依赖网** | 断言+justification 边+派生物注册表 | retract 级联标记失效 | retract 传导最强 | 同 S3 |
| N1 | **LLM-维护变体（mem0-lite）** | 事实层由 LLM 判 ADD/UPDATE/DELETE/NOOP | 更新动作显式 | 语义冲突识别强 | +token 成本 |
| N2 | **参数化对照（LoRA-self）** | 定期微调 | — | 仅作反证 | 训练贵、不可控 |

**建议直接入评测器的新基线**：S1（替代/加强 ledger）、S3、S7——
三者共同覆盖"历史正确性"谱系；N1 在有 LLM 预算的轮次再开。

## 6. 回灌给架构 §7 的发现

- **"as-of 时态探针"值得加**："day40 时我以为是什么"在双时态/事件
  溯源表征下是廉价查询，而它恰是检验"纠错真传导"的最强探针。
- **hearsay 需要对象维度**：当前 slot 模型默认主体=本人；传闻关于
  他人——断言要带 subject，S3 的实体层提供落点。
- **vacuuming/遗忘策略本身是变量**：保留全部历史 vs 真空清理是
  asset_bytes 与沿革能力间的显式杠杆（Snodgrass 有成熟术语与做法）。
- **诚实记账约束**：派生层必须可序列化进 state()，否则评测器量不到
  ——表征选型时把"全部内部状态可 dump 成 dict"作为硬要求。

## 7. 参考文献

**时态数据库**
- Snodgrass, *Developing Time-Oriented Database Applications in SQL*, Morgan Kaufmann 1999. https://archive.org/details/developingtimeor0000snod
- TSQL2 Language Specification (1994). https://www2.cs.arizona.edu/people/rts/initiatives/tsql2/finalspec.pdf
- XTDB (bitemporal document DB). https://xtdb.com ；Datomic. https://www.datomic.com

**知识表征与 PKG**
- Minsky, *A Framework for Representing Knowledge*, MIT AI Memo 306, 1974. https://web.media.mit.edu/~minsky/papers/Frames/frames.html
- Balog & Kenter, *Personal Knowledge Graphs: A Research Agenda*, 2019. https://doi.org/10.1145/3341981.3344241
- Skjæveland et al., *An ecosystem for personal knowledge graphs*, AI Open 2024. https://doi.org/10.1016/j.aiopen.2024.01.003
- *A comprehensive survey of personal knowledge graphs*, WIREs DMKD 2023. https://doi.org/10.1002/widm.1513
- NEPOMUK PIMO ontology. https://www.semanticdesktop.org/ontologies/2007/11/01/pimo/
- RDF 1.1 Concepts. https://www.w3.org/TR/rdf11-concepts/ ；RDF-star CG report. https://w3c.github.io/rdf-star/cg-spec/
- Solid. https://solidproject.org

**时态知识图谱**
- Rasmussen et al., *Zep: A Temporal Knowledge Graph Architecture for Agent Memory*, arXiv:2501.13956. https://arxiv.org/abs/2501.13956
- Graphiti 双时态模型文档. https://getzep-graphiti.mintlify.app/concepts/temporal-model
- Cai et al., *Temporal Knowledge Graph Completion: A Survey*, IJCAI 2022. https://arxiv.org/abs/2201.08236

**LLM 记忆**
- Packer et al., *MemGPT*, arXiv:2310.08560. https://arxiv.org/abs/2310.08560
- Letta memory blocks docs. https://docs.letta.com/guides/core-concepts/memory/memory-blocks/
- Park et al., *Generative Agents*, arXiv:2304.03442. https://arxiv.org/abs/2304.03442
- Chhikara et al., *Mem0*, arXiv:2504.19413. https://arxiv.org/abs/2504.19413 ；https://github.com/mem0ai/mem0
- LangMem SDK. https://langchain-ai.github.io/langmem/ ；https://www.langchain.com/blog/langmem-sdk-launch
- Xu et al., *A-MEM: Agentic Memory*, arXiv:2502.12110. https://arxiv.org/abs/2502.12110
- Zhong et al., *MemoryBank*, arXiv:2305.10250. https://arxiv.org/abs/2305.10250
- *A Survey on the Memory Mechanism of LLM-based Agents*, arXiv:2404.13501. https://arxiv.org/abs/2404.13501
- Sumers et al., *CoALA: Cognitive Architectures for Language Agents*, arXiv:2309.02427. https://arxiv.org/abs/2309.02427
- OpenAI, *Memory and new controls for ChatGPT*, 2024. https://openai.com/index/memory-and-new-controls-for-chatgpt/
- Wu et al., *LongMemEval*, arXiv:2410.10813. https://arxiv.org/abs/2410.10813
- Maharana et al., *LOCOMO*, arXiv:2402.17753. https://arxiv.org/abs/2402.17753

**层级摘要 / 图混合**
- Sarthi et al., *RAPTOR*, arXiv:2401.18059. https://arxiv.org/abs/2401.18059
- Edge et al., *GraphRAG*, arXiv:2404.16130. https://arxiv.org/abs/2404.16130
- Gutiérrez et al., *HippoRAG*, arXiv:2405.14831. https://arxiv.org/abs/2405.14831

**lifelogging / 事件溯源**
- Gemmell, Bell, Lueder, *MyLifeBits*, CACM 2006. https://doi.org/10.1145/1107458.1107460
- Bush, *As We May Think*, Atlantic 1945. https://www.theatlantic.com/magazine/archive/1945/07/as-we-may-think/303881/
- Fowler, *Event Sourcing*. https://www.martinfowler.com/eaaDev/EventSourcing.html

**不确定度 / 溯源**
- W3C PROV-DM. https://www.w3.org/TR/prov-dm/ ；PROV-O. https://www.w3.org/TR/prov-o/
- Mitchell et al., *Never-Ending Learning (NELL)*, CACM 2018. https://www.cs.cmu.edu/~tom/pubs/NELL-CACM-2018.pdf
- Bleiholder & Naumann, *Data Fusion*, ACM CSUR 2008. https://doi.org/10.1145/1456650.1456651
- Bleiholder & Naumann, *Data Fusion – Resolving Data Conflicts for Integration*, VLDB 2009 tutorial. http://www.vldb.org/pvldb/vol2/vldb09-tutorial1.pdf
- Li et al., *A Survey on Truth Discovery*, SIGKDD Explorations 2015. https://doi.org/10.1145/2811231.2811234
- Liu et al., *Lost in the Middle*, arXiv:2307.03172. https://arxiv.org/abs/2307.03172

**修正语义 / 参数记忆**
- Doyle, *A Truth Maintenance System*, AI 1979. https://dspace.mit.edu/handle/1721.1/5733 ；https://doi.org/10.1016/0004-3702(79)90008-0
- de Kleer, *An assumption-based TMS*, AI 28:127–162, 1986. https://www.sciencedirect.com/science/article/abs/pii/0004370286900802
- Alchourrón, Gärdenfors & Makinson, AGM, JSL 1985. https://doi.org/10.2307/2274239
- *Connections Between the ATMS and AGM Belief Revision*, IJCAI'93. https://www.ijcai.org/Proceedings/93-1/Papers/075.pdf
- Petroni et al., *Language Models as Knowledge Bases?*, arXiv:1909.01066. https://arxiv.org/abs/1909.01066
- Meng et al., *ROME*, arXiv:2202.05262. https://arxiv.org/abs/2202.05262 ；*MEMIT*, arXiv:2210.07229. https://arxiv.org/abs/2210.07229
- Zhong et al., *MQuAKE*, arXiv:2305.14795. https://arxiv.org/abs/2305.14795
- Kirkpatrick et al., *Overcoming catastrophic forgetting (EWC)*, arXiv:1612.00796. https://arxiv.org/abs/1612.00796
- LLM unlearning surveys: arXiv:2503.01854 https://arxiv.org/abs/2503.01854 ；https://doi.org/10.1007/s10462-024-11078-6
