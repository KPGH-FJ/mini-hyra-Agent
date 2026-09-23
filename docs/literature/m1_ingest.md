# M1 Ingest 文献调研纪要 — 摄入与溯源

> 对应 `LIFEMODEL_ARCHITECTURE.md` §1 的 M1 模块。M1 的职责：把一条原始 record
> 变成**归一化事件（normalized event）**——标注谁说的（source）、什么类型的
> 言语行为（kind）、什么时候有效（temporal context）、信源多可信
> （source reliability）、与其他来源是否冲突（conflict）、是否重复（duplicate）、
> 缺了什么（missing info）。M1 是资产的"语言+认知前端"：M2/M3/M4 之后只见
> 归一化事件，不应再回去啃原始 text。

## 0. M1 的问题界定（锚定到 LifeStream）

LifeStream 的 record 已经是"半归一化"的 `{day, source, kind, slot, value, text,
expires_day?}`，真实管道里 day/source/kind/slot/value 都要从自然语言或多源
API 里自己提取。ground truth 语义给 M1 定了明确边界：

- **两个平面的分离**：所有 record 都该入档（data plane，prov 探针靠它），
  但只有 `source=self` 且 `kind ∈ {statement, update, correction}` 才允许写进
  状态候选（assertion plane）。hearsay / suggestion 永远不算本人状态——
  prov 探针专门考这个区分。
- **retraction 是删除行为**，不是负值陈述；`expires_day` 是 valid-time 区间右端点。
- **冲突的答案是权限而非投票**：变更后紧跟的 hearsay 不能赢——因为它
  来源不对，不是因为它"票数"少。
- **ckpt 探针 = transaction-time as-of 查询**（"day X 之前你知道什么"），
  这直接指向 bitemporal 模型（见 §3.6）。

一句话：**provenance 在摄入时不记，之后永远补不回来**。M4 的置信度、
M5 的删除传导、retract 探针，全都依赖 M1 留下的标注质量。

## 1. 方法族 taxonomy

按"摄入时多做多少工作"从浅到深排：

| 族 | 核心想法 | M1 成本 | 下游能得到什么 |
|---|---|---|---|
| F0 透传 append-only | 原文入库，归一化留给消费端 | ≈0 | 原始记录可回放；其它全推给 M2-M4 |
| F1 规则归一化 | source×kind 规则表 + schema 落位 | 低 | 结构化事件流（现种子） |
| F2 标注增强归一化 | F1 + provenance/confidence/valid-time/dup 链接 | 低-中 | 全量溯源、置信度、时态查询 |
| F3 冲突登记 (conflict registry) | 不裁决，存竞争 claims + source weights | 中 | 冲突可视化、延迟裁决、retract 友好 |
| F4 摄入即裁决 (truth discovery) | 摄入时估计 source reliability 并融合 | 中-高 | 单一口径状态；风险是把噪音判真 |
| F5 学习式归一化 | LLM/ML 做抽取、归并、act 分类 | 高（token） | 最强泛化，最弱可解释/可审计 |
| F6 双时态规范化 | valid time + transaction time 双时间戳 | 低-中 | "当时是以为 X"类时态探针 |

工程侧还有一族必须垫底：**幂等与去重**（idempotency keys、near-dup
collapse），见 §3.4。真实管道 at-least-once 投递是常态，合成基准没有显式
重复但文本近重复天然存在。

## 2. 归一化事件的候选 schema（调研共识的交集）

把各系统摄入产物取并集，M1 输出可以收敛为：

```python
event = {
  rec_id,                 # 原始 record 引用（回指原文）
  tx_day,                 # transaction time：记录到达系统之日（≈ rec.day / ckpt 语义）
  valid: (start, end|None),# valid time：事实声称成立的区间；expires_day → end
  actor: {type: self|other|assistant|device|doc, name?, resolved_id},
  act: assert|update|correct|retract|suggest|report,  # kind 的言语行为层
  object: {slot, value, modality: fact|preference|constraint|goal|negated},
  confidence: float|None,  # 摄入时的证据强度先验
  trust_path: [actor_id],  # hearsay 链：谁转述谁
  dup_of: event_id|None,
  conflicts_with: [event_id], supersedes: [event_id],
}
```

这正是 W3C **PROV** 三件套（Entity=claim、Agent=actor、Activity=ingest/act）
+ bitemporal + evidentiality 标注的合成体（参考链接见 §5）。

## 3. 代表系统 / 论文：一句话 takeaway + 对个人 LifeModel 的适配度

### 3.1 Data provenance / lineage（数据库溯源）

| 工作 | 一句话 takeaway | 对 M1 的适配 |
|---|---|---|
| Buneman, Khanna, Tan — *Why and Where: A Characterization of Data Provenance* (ICDT'01) | 区分 why-provenance（结果为何成立）与 where-provenance（字节从哪来），溯源研究的起点 | 概念框架：prov 探针问的是 where（"这句话谁说的"），但 retract/纠正传导需要 why（"这个结论依赖哪些记录"）。M1 应同时留两类链接 |
| Cheney, Chiticariu, Tan — *Provenance in Databases: Why, How, and Where* (FnT DB'09) | 综述：provenance 用于 confidence 计算、view maintenance、annotation propagation | 正面教材：provenance 可在摄入时以 annotation 形态携带并随派生传播——正是 M5"删除传导"的理论根基 |
| Buneman et al. — *On propagation of deletions and annotations through views* (PODS'02) | 删除经由 view 传播的语义分析 | 直接对应 M5 `forget()`：M1 若给每条派生事件挂 record 指针，删除才有机械实现 |
| W3C PROV-O / PROV-JSON | 标准化 Entity-Activity-Agent 溯源数据模型 | M1 归一化事件的最成熟现成 schema；`wasAttributedTo`/`wasDerivedFrom`/`actedOnBehalfOf` 直接覆盖"代人说/转述"语义 |
| Green et al. — provenance semirings (PODS'07) | provenance 作为可交换计算的半环对象 | 提示置信度可以沿派生链代数化传播，而不只是标个死数字 |

**小结**：DB provenance 给了"链接怎么记"，没给"信谁"。LifeModel 里
provenance 是及格线，reliability 才是打分点。

### 3.2 Truth discovery & 多源冲突解决

| 工作 | 一句话 takeaway | 对 M1 的适配 |
|---|---|---|
| Yin, Han, Yu — TruthFinder (KDD'07) | 信源可信度与 claim 真实性互相迭代估计（web conflicts） | 经典 F4 路线；但 LifeModel 的"自我陈述"问题里 self 是一阶权威源，迭代权重反而可能稀释 self——要用权限先验固定 |
| Li et al. — *A Survey on Truth Discovery* (KDD Explorations'15) | 全景综述：数据形态（数值/类别/文本）、源依赖、长尾 source、confidence 区间 | 选型地图：M1 若走 F4，按 survey 的方法家族逐项试（voting → TruthFinder → CRH/CATD） |
| Bleiholder & Naumann — *Data fusion* (ACM CSUR'09) + Dong & Naumann VLDB'09 tutorial | 冲突处理策略三分法：conflict-ignoring / conflict-avoiding / conflict-resolving | M1 的 taxonomy 骨架；个人流的核心冲突是"自我更新 vs 他人噪音"，属 conflict-avoiding（按 authority 过滤）而非融合 |
| Dong, Berti-Equille, Srivastava — *Integrating Conflicting Data: The Role of Source Dependence* (VLDB'09) | 投票会被互相抄袭的源骗过；建模 source dependence（谁抄谁） | hearsay 的本质就是"依赖于上游源"的派生记录——`trust_path` 字段即此 |
| Li et al. — *On the Discovery of Evolving Truth* (CATD, KDD'15) | 增量式 truth discovery：truth 与 source reliability 都随时间漂移 | 直接命中 LifeStream：人会变、信源也会变；可用作"在线 reliability"种子 |
| Dong et al. — Knowledge Vault (KDD'14) | Web-scale 抽取 + supervised fusion，给每条 fact 标 calibrated probability + provenance | "归一化 + 置信度标注"的最强工程范本；但其 confidence 是全局真值概率，个人模型要的是"对本人当前状态的置信"——语义不同 |
| MYCIN certainty factors (Shortliffe & Buchanan'75) | 专家系统鼻祖级不确定性标注：CF ∈ [-1,1] 沿规则传播 | 极简可实现的 confidence 方案，作为 F2 的最低配种子 |

**小结**：truth discovery 的核心循环"信源越准它说越对，它说越对信源越准"
对 web 数据有效，对个人流要改造：self 对自己的事实状态是**定义性权威**
（authoritative by definition, not by reputation）。正确做法是 **authority
matrix**：`reliability[actor][scope]`——self 对 self-state 恒为 1，device/doc
对客观字段高、对偏好类字段无权威，assistant 的 suggestion 权威恒 0，
named others 随历史可学习。

### 3.3 Source reliability & hearsay / 二手信息

| 工作 | 一句话 takeaway | 对 M1 的适配 |
|---|---|---|
| Jøsang — Subjective Logic (IJUFKS'01; Springer'16 专著) | opinion=(belief, disbelief, uncertainty, base rate)；discounting 算子形式化"我信 X，X 说 P → 我对 P 打折后的 opinion" | hearsay 的现成数学：`report` act = discount(trust(actor), claim)；consensus 算子合并多源。F2/F3 的置信度体系首选 |
| Jøsang & Ismail — Beta Reputation System (BLED'02) | 用 Beta 分布的 α/β 在线学习 source reliability | 实现最便宜的 reliability 学习器：每条 "self 后来证实/证伪了 X 的说法" 更新一次 |
| Johnson, Hashtroudi, Lindsay — Source Monitoring (Psych. Bulletin'93) | 人类记忆本来就带 source attribution；source-monitoring error 是人脑已知缺陷 | 设计隐喻：prov 探针考的就是 source monitoring；系统应把 attribution 当一等公民，人类都不能靠回忆补上，何况模型 |
| Aikhenvald — *Evidentiality* (OUP'04) | 人类语言语法化区分"亲见/转述/推断"，hearsay 标记是语言本能 | `kind=hearsay` 不是噪声标签而是语法级的 evidentiality——M1 从文本提取时按 evidentials 切 act 类型 |
| CoNLL-2010 Shared Task — hedge/uncertainty detection | NLP 基准：自动检测文本中不确定措辞（"可能/大概/听说"） | 摄入时跑 hedging 检测 → confidence 先验折扣；"他说可能搬到了上海" ≠ "他搬到了上海" |

**小结**：hearsay 处理 = discounting + attribution，不是"丢弃"。LifeStream 把
hearsay 设为非真值但保留在记录流里，正好对应"留着以便 prov 探针，但不参与
状态"。注意 truth semantics 里 hearsay 的 `source` 是讲述者本人之外的某人，
`trust_path` 要把"谁转述的"留全。

### 3.4 Entity resolution / dedup（个人记录去重与指称消解）

| 工作 | 一句话 takeaway | 对 M1 的适配 |
|---|---|---|
| Fellegi & Sunter (JASA'69) | record linkage 的概率模型鼻祖：按字段相似度加权得匹配分 | 参考框架；个人流里 ER 的对象是两层——(a) "同事小李"vs"小李"这种**提及的实体**，(b) 同一 slot 的**重复断言** |
| Elmagarmid, Ipeirotis, Verykios — *Duplicate Record Detection: A Survey* (TKDE'07) | dedup 经典综述：blocking + pairwise similarity + clustering | blocking 思想可直接搬：按 (slot, normalized value) 分桶做去重，不用全对全比 |
| Getoor & Machanavajjhala — *Entity resolution: theory, practice & open challenges* (VLDB'12) | ER 教程：确定性与概率方法、关系 ER、新挑战 | 关系 ER（提及人物之间的共指）对应 LifeModel 的"他人"实体表 |
| Steorts et al. — *(Almost) all of entity resolution* (Science Advances'23) | 现代统计 ER 综述：Bayesian、半监督、隐私保护 | 选型补充 |
| Ditto (VLDB'20) / DeepMatcher (SIGMOD'18) | 预训练 LM 做 entity matching，少标注达 SOTA | F5 路线：LLM 判重/归一化 slot-value；贵但泛化强 |
| Whang & Garcia-Molina — *Entity resolution with evolving rules* (VLDB'10) | 规则随数据演化的增量 ER | 对应"流式 dedup"：规则也纳入资产可进化 |
| MinHash/LSH (Broder'97; Indyk-Motwani'98) | 文本近重复的高效签名 | text 层近重复检测的工程底座；LifeStream 虽无显式重复，真实管道必有 |

**小结**：M1 的 dedup 分三档——(1) `rec_id` 幂等去重（工程必备），
(2) slot+value 语义去重（断言层：同 slot 同值重复断言合并并计数，作为
reinforcement 信号），(3) 人物提及归一化（actor resolved_id）。档 1 必须，
档 2 是高 ROI 种子，档 3 是 prov 探针深化的前提。

### 3.5 LLM memory 系统怎么摄入（最新一代同行）

| 系统 | 摄入做法 | 对 M1 的适配 |
|---|---|---|
| MemGPT → Letta (arXiv 2310.08560) | agent 自主 function-call 编辑 core memory + append-only archival；摄入即自我决策 | "把 M1+M3 合进 agent 推理"的极端；自由度高但行为不可审计——对可控性目标是反例多于正例 |
| mem0 (arXiv 2504.19413) | 每轮对话 LLM 抽取候选记忆 → 与 top-k 旧记忆比对 → ADD/UPDATE/DELETE/NOOP 四决策 | 最值得抄的 F5 管线：ingest 时即对现有资产做语义冲突检查；缺点是 black-box 决策、无 per-claim provenance，prov 探针会挂 |
| Zep / Graphiti (arXiv 2501.13956) | episode → entity/edge 抽取入 temporal KG；边带 valid_at/invalid_at 双时态；矛盾时 invalidate 旧边而非覆盖 | 与本项目语义最接近的工业实现：bi-temporal + 不丢历史 + 矛盾登记。M1 可抄"边永不删除、只 invalid"的原则 |
| LangMem | hot-path/background LLM 抽取 → profile（schema 固定）或 collection（自由文档）存库 | "slot=固定 schema"与我们的 slot 设计同源；其 semantic dedup on collection 是档 2 dedup 的现成参考 |
| Generative Agents (UIST'23, arXiv 2304.03442) | 全部 observation 进 memory stream（原文+时间戳+importance 分）；reflection 产物挂 evidence 指针 | "先全存，重要性打分"路线 + 派生物带 provenance 指针的先例；importance 可作为 ingest 开销的分配信号 |
| MemoryBank (AAAI'24, arXiv 2305.10250) | 日记式归纳 + Ebbinghaus 遗忘曲线衰减 | 摄入时就给记忆一个可衰减的 salience 初值；遗忘语义属 M3，但 salience 初值属 M1 |

**小结**：业界摄入侧的两极——"LLM 全包决策"（mem0/Letta，灵活不可审计）
vs "结构化抽取+时态标注"（Graphiti，可审计但 schema 重）。LifeModel 评测
把 prov/retract 探针作为硬指标，且要求成本记账，因此 **F2 结构化标注应为主
轴，LLM 决策只用于文本→事件的抽取前端（可选、可替换）**。

### 3.6 Temporal validity at ingest

| 工作 | 一句话 takeaway | 对 M1 的适配 |
|---|---|---|
| Snodgrass — TSQL2 / *Developing Time-Oriented DB Applications in SQL* | valid time（现实中何时成立）与 transaction time（何时入库）分离是时态数据库的基石 | 本项目的 `day` 兼具两义（合成流里重合），真实摄入必须分开；ckpt 探针语义 = `AS OF transaction time = ckpt` |
| Kulkarni & Michels — *Temporal features in SQL:2011* | 标准里的 application-time（valid）period 与 system-time（transaction）period | 归一化事件 schema 的权威参照：`valid=(start,end)` 直接对应 expires_day |
| Allen's interval algebra (1983) | 区间关系 13 式 | expires_day、自然语言"下个月之前"等转化为区间的形式工具 |
| Akidau et al. — The Dataflow Model (PVLDB'15) | event time vs processing time + watermark + late data 处理 | 真实管道记录乱序到达是必然；`rec.day` 是 event time，到达时刻是 processing time——dedup 和 truth 排序都应按前者 |
| TimeML / HeidelTime (SEM'10) | 文本时间表达式的标注标准与规则抽取器 | 真实摄入时 valid-time 要从 text 提取；"下周五之前吃素" → interval |

**小结**：双时态是便宜的大杀器——多条 `valid`/`tx` 两列，换来 retract/stale
探针的干净语义和"day40 时我以为是什么"这类时态查询的能力（直接回应
架构文档 §7 的开放问题：建议加，机制已经现成）。

### 3.7 Missing / negative info

- **Closed-world vs open-world**：`slot` 无记录 ≠ 值为假；M1 应让"未知"
  成为显式状态而非空缺，M4 据此决定拒答/补问。
- **显式否定**：retraction（"删掉这条"）与 negation（"我不再跑步了"）不同，
  后者是值为"无/否定"的正常陈述——`modality=negated` 区分之。
- **Missingness taxonomy**（Little & Rubin）：个人记录缺失多为 MAR/MNAR
  ——没提的可能就是不想说；`export()` 时缺失语义要能随行。
- **Abduction**: `assistant suggestion` + 后来 `self` 采纳 = 新的 self 断言，而不是
  给旧 suggestion 升级——只保留 provenance 链接即可（wasDerivedFrom）。

## 4. 个人 LifeModel 与通用 truth discovery 的三处本质差异

1. **权威不是统计出来的**：web 融合里没有"谁说了算"的先验；个人模型里
   self 对自身状态是定义性权威。M1 的正确抽象不是 `reliability[source]`
   而是 `authority[source_type][slot_scope]`——others 对本人的当前事实
   权重恒小于 self（hearsay 永不赢），但 others 可以是"对自己的可信度"
   的唯一信息源（如对本人不自知的盲区的反馈——schema 上允许 hearsay
   存进"关于我"但标 modality，不进 self-state）。
2. **记录平面与断言平面分离**：所有记录（含 hearsay、assistant suggestion、
   已 retract 的）都必须留档供 prov/retract 探针；只有权威行为才进状态候选。
   摄入产物的最小合同：**`records[]` 全量归一化 + `candidates[]` 权威断言**。
3. **撤回与纠错是一等公民**：TruthFinder 时代模型处理"脏数据"，不处理
   "主人今天说昨天说的不算"。M1 必须把 retract/correct 标注为对特定
   claim 的元操作（supersedes/invalidates 链接），否则 M3 只能靠值级覆盖
   黑猜。

## 5. 候选方法 → seeds/baselines 清单

每条种子都能在现有 `LifeModel.ingest()` 合同内独立实现（只动 M1 段，
不碰 M2-M5 语义）：

| 种子 ID | 做法 | 预计赢在哪 | 预计输在哪 |
|---|---|---|---|
| `m1-raw` (已存在=raw 基线) | 透传：不建 normalized event，text 原文留给下游 | 零摄入成本 | probe_bytes 爆炸；prov/stale 靠下游裸判 |
| `m1-rules` (=现 seed) | source×kind 规则表 → accept/reject + last-wins | 合成基准语义上 100% 吻合 | 真实文本无规整 kind 字段即死；不产 confidence/冲突标注 |
| `m1-annotated` | F2：规则归一化 + 全量标注（actor/act/valid/confidence/dup/supersedes 链） | prov/retract/transfer 全探针友好；给 M3/M5 留足钩子 | 字节成本高于 raw；价值要等下游用上才兑现 |
| `m1-confreg` | 冲突登记表：同 slot 竞争 claim 不裁决，存 `{value, source, weight}`，M4 按 authority 查 | stale/hearsay 冲突从根上不丢；天然支持"当时以为" | state 探针答"consensus"需 M4 配合；实现稍重 |
| `m1-awn` | Authority matrix 种子：`authority[src_type][slot_domain]` 先验表 + hearsay/suggestion 硬排除 | 5 行代码吃到 80% 收益；精确命中基准 truth 语义 | 把"别人比本人更准"的情形一刀切死 |
| `m1-rellearn` | CATD/Beta-reputation 风格：以 self 断言为锚，在线学习 named-others 的 per-slot reliability | 长跑下能分辨"表姐总是靠谱/阿伟瞎猜" | 冷启动依赖 self 反馈；短期不如 m1-awn |
| `m1-bitemp` | 归一化事件带 (valid_start, valid_end, tx_day) | stale 探针、时态查询、过期约束一网打尽 | 需要下游 read 侧理解双时态 |
| `m1-subjlogic` | 每条 claim 存 subjective-logic opinion；hearsay = trust ⊗ claim | 置信度语义最干净；hearsay 链可任意深 | 数值传播调参成本 |
| `m1-dedup` | rec_id 幂等 + slot/value canonicalization + MinHash 近重 → `dup_of` 链接 + repeat_count | 真实管道必备；重复可作为 reinforcement 信号 | 合成基准上收益≈0（加字节） |
| `m1-hedge` | 文本侧 hedging/evidentiality 检测 → confidence 折扣 | 把"听说/可能/大概"从文本转成标注 | 需要 NLP 前端，合成流用不上 |
| `m1-llm` | mem0 式 LLM 决策：每 record → ADD/UPDATE/DELETE/NOOP + slot/value 抽取 | 真实非结构化文本下的唯一可行前端 | token 成本、决策不可审计；基准环境禁 LLM 只能做离线分析用 |

推荐编码顺序（P2 骨架阶段）：`m1-annotated`（F2，主种子）→ `m1-awn`
（权限表，几乎免费）→ `m1-bitemp`（加两列）→ `m1-confreg`（冲突登记）。
`m1-rellearn`、`m1-subjlogic` 留作进化空间里的高阶变异；`m1-llm` 仅在真实
授权数据阶段（P4）上场。

## 6. 待办与开放问题

- **时态查询探针**：bitemporal 使"day40 时我以为是什么"可答；建议给
  评测器加 `temporal` 类型探针（对应 §7 遗留问题第三条）。
- **other 提及实体消解**：真实流里同一人多名/代称；actor resolution
  需要一张 per-user 的 person-ER 子表（小数据，规则+LLM 均可）。
- **source authority 的可学习边界**：m1-awn 的硬表 vs m1-rellearn 的学习
  权重，在 LifeStream 上加"噪声源偶然命中"场景即可分胜负——值得让
  评测器生成一种"可信的他人"。
- **摄入成本控制**：importance 打分（Generative Agents）/ 只对
  `kind∈{statement,update,correction}` 的 self 记录做深标注，其余轻量
  归一化，是一条成本守恒的默认策略。

## 7. 引用列表（均为可公开访问链接）

**Provenance**
- Cheney, Chiticariu, Tan, *Provenance in Databases: Why, How, and Where*, FnT Databases 2009 — https://doi.org/10.1561/1900000006
- Buneman, Khanna, Tan, *Why and Where: A Characterization of Data Provenance*, ICDT 2001 — https://doi.org/10.1007/3-540-44503-X_20
- Herschel, Diestelkämper, Ben Lahmar, *A survey on provenance: What for? What form? What from?*, VLDB Journal 2017 — https://doi.org/10.1007/s00778-017-0486-1
- W3C PROV-O — https://www.w3.org/TR/prov-o/
- Buneman et al., *On propagation of deletions and annotations through views*, PODS 2002 — https://doi.org/10.1145/543613.543633

**Truth discovery / data fusion**
- Yin, Han, Yu, *Truth Discovery with Multiple Conflicting Information Providers on the Web* (TruthFinder), KDD 2007 — https://doi.org/10.1145/1281192.1281309 （PDF: http://hanj.cs.illinois.edu/pdf/kdd07_xyin.pdf）
- Li et al., *A Survey on Truth Discovery*, KDD Explorations 2015 — https://arxiv.org/abs/1505.02463
- Dong, Naumann, *Data Fusion: Resolving Data Conflicts for Integration*, VLDB 2009 tutorial — http://www.vldb.org/pvldb/vol2/vldb09-tutorial1.pdf
- Bleiholder, Naumann, *Data fusion*, ACM Computing Surveys 2009 — https://doi.org/10.1145/1456650.1456651
- Dong, Berti-Équille, Srivastava, *Integrating Conflicting Data: The Role of Source Dependence*, VLDB 2009 — https://doi.org/10.14778/1687627.1687690
- Li et al., *On the Discovery of Evolving Truth* (CATD), KDD 2015 — https://doi.org/10.1145/2783258.2783277 （PDF: https://cse.buffalo.edu/~jing/doc/kdd15_evolve.pdf）
- Dong et al., *Knowledge Vault: A Web-Scale Approach to Probabilistic Knowledge Fusion*, KDD 2014 — https://research.google/pubs/knowledge-vault-a-web-scale-approach-to-probabilistic-knowledge-fusion/
- Shortliffe & Buchanan, *A model of inexact reasoning in medicine* (MYCIN CF), Mathematical Biosciences 1975 — https://doi.org/10.1016/0025-5564(75)90047-4

**Source reliability / hearsay**
- Jøsang, *A Logic for Uncertain Probabilities* (Subjective Logic), IJUFKS 2001 — https://doi.org/10.1016/S0218-4885(01)00083-1
- Jøsang, *Subjective Logic: A Formalism for Reasoning Under Uncertainty*, Springer 2016 — https://link.springer.com/book/10.1007/978-3-319-42337-1
- Jøsang & Ismail, *The Beta Reputation System*, Bled eCommerce Conf 2002 — https://www.unik.no/people/josang/papers/JI2002-BLED.pdf
- Johnson, Hashtroudi, Lindsay, *Source Monitoring*, Psychological Bulletin 1993 — https://doi.org/10.1037/0033-2909.114.1.3
- Aikhenvald, *Evidentiality*, Oxford University Press 2004 — https://global.oup.com/academic/product/evidentiality-9780199263882
- Farkas et al., *The CoNLL-2010 Shared Task: Learning to Detect Hedges*, CoNLL 2010 — https://aclanthology.org/W10-3001.pdf

**Entity resolution / dedup**
- Fellegi & Sunter, *A Theory for Record Linkage*, JASA 1969 — https://doi.org/10.1080/01621459.1969.10501049
- Elmagarmid, Ipeirotis, Verykios, *Duplicate Record Detection: A Survey*, TKDE 2007 — https://doi.org/10.1109/TKDE.2007.250581
- Getoor & Machanavajjhala, *Entity resolution: theory, practice & open challenges*, VLDB 2012 — https://doi.org/10.14778/2367502.2367564
- Steorts et al., *(Almost) all of entity resolution*, Science Advances 2023 — https://pmc.ncbi.nlm.nih.gov/articles/PMC11636688/
- Li et al., *Deep Entity Matching with Pre-Trained Language Models* (Ditto), VLDB 2020 — https://arxiv.org/abs/2004.00584
- Mudgal et al., *Deep Learning for Entity Matching* (DeepMatcher), SIGMOD 2018 — https://github.com/anhaidgroup/deepmatcher
- Whang & Garcia-Molina, *Entity resolution with evolving rules*, VLDB 2010 — https://doi.org/10.14778/1920841.1920943

**LLM memory 系统摄入**
- Packer et al., *MemGPT: Towards LLMs as Operating Systems*, arXiv 2023 — https://arxiv.org/abs/2310.08560 （工程后继: https://github.com/letta-ai/letta）
- Chhikara et al., *Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory*, arXiv 2025 — https://arxiv.org/abs/2504.19413 （https://github.com/mem0ai/mem0）
- Rasmussen et al., *Zep: A Temporal Knowledge Graph Architecture for Agent Memory*, arXiv 2025 — https://arxiv.org/abs/2501.13956 （https://github.com/getzep/graphiti）
- LangMem — https://github.com/langchain-ai/langmem （概念文档: https://docs.langchain.com/oss/python/concepts/memory）
- Park et al., *Generative Agents: Interactive Simulacra of Human Behavior*, UIST 2023 — https://arxiv.org/abs/2304.03442
- Zhong et al., *MemoryBank: Enhancing Large Language Models with Long-Term Memory*, AAAI 2024 — https://arxiv.org/abs/2305.10250

**Temporal**
- Snodgrass, TSQL2 / *Developing Time-Oriented Database Applications in SQL*（免费 PDF 入口） — https://www2.cs.arizona.edu/~rts/publications.html
- Kulkarni & Michels, *Temporal features in SQL:2011*, SIGMOD Record 2012 — https://sigmodrecord.org/publications/sigmodRecord/1209/pdfs/07.industry.kulkarni.pdf
- Allen, *Maintaining Knowledge about Temporal Intervals*, CACM 1983 — https://doi.org/10.1145/182.358434
- Akidau et al., *The Dataflow Model*, PVLDB 2015 — https://doi.org/10.14778/2824032.2824076
- Strötgen & Gertz, *HeidelTime: High Quality Rule-Based Extraction and Normalization of Temporal Expressions*, SemEval 2010 — https://aclanthology.org/S10-1071.pdf

**Missing info / 工程模式**
- Little & Rubin, *Statistical Analysis with Missing Data*（MCAR/MAR/MNAR 提出者）, Wiley — https://doi.org/10.1002/9781119013563
- Fowler, *Event Sourcing*（摄入=追加事件的架构模式参照） — https://martinfowler.com/eaaDev/EventSourcing.html
- Kleppmann, *Designing Data-Intensive Applications*（exactly-once/idempotency 章）, O'Reilly 2017 — https://www.oreilly.com/library/view/designing-data-intensive-applications/9781491903063/
