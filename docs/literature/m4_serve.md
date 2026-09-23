# M4 Serve 文献调研纪要

> 对应 `docs/LIFEMODEL_ARCHITECTURE.md` §1 M4：给定 need/probe，从理解资产产出
> "任务恰当的视图或回答"——检索、上下文预算、作答、置信度、以及"该补问而非瞎猜"
> 的判断。本文调研五条战线：RAG 检索族、上下文预算与压缩、任务条件化视图、
> 校准拒答与补问、溯源展示；外加消费级"一份记忆多处用"产品的公开信息。

## 0. 先把 M4 的问题形式化（对齐 LifeStream 评分面）

`answer(probe)` 的真实优化目标（见 `tasks/life_model/evaluate.py`）：

- 质量：子串命中 +1 / 部分 0.5 / 未命中 0 / **must_not 泄漏 −0.5**（答错比不答更糟）
- 成本：`probe_bytes`（回答时实际查阅的字节）+ `asset_bytes` + `llm_tokens`
- 探针类型即任务：state/stale（点查）、prov（"这条是不是本人说的"）、
  retract（删除后应"已删除/未知"）、transfer（多槽打包视图）

由此，M4 每次作答是三元决策：**(a) 查哪些**（视图/检索）、**(b) 答不答**
（abstain/补问——bench 中无法真问人，退化为返回"未知"）、**(c) 怎么呈现**
（短值、打包清单、还是带溯源的回答）。`probe_bytes` 就是经典 "token budget"
问题的等价物：**每一字节都要挣回分数**。

一个贯穿全文的判断：LifeStream 的探针是**结构化**的（slot/类型都是显式字段），
所以"检索"在这里首先是**路由与物化视图**问题，而不是纯向量检索问题——
这与 LongMemEval 论文的框架吻合（见 §1.8）。向量/图检索是槽位缺失或文本
噪声大时的补充手段。

---

## 1. 检索族（Retrieval families）

综述入口：Gao et al., *Retrieval-Augmented Generation for Large Language
Models: A Survey*（RAG 范式三代划分：naive → advanced → modular）
<https://arxiv.org/abs/2312.10997>；RAG 原始论文 Lewis et al. 2020
<https://arxiv.org/abs/2005.11401>。

### 1.1 稀疏检索

- **BM25**（Robertson & Zaragoza, FnTIR 2009, <https://doi.org/10.1561/1500000019>）：
  仍是强基线；对个人记录这类短文本、含稀有专有名词的场景往往不输初版稠密模型。
- **doc2query**（Nogueira et al. 2019, <https://arxiv.org/abs/1904.08375>）：
  索引期给每篇文档"预测用户会问什么"并回写——思路可借给 M4：摄入时为每条
  记录生成"会被什么探针命中"的伪查询扩展，缓解表面形式不匹配。
- **SPLADE v2**（Formal et al. 2021, <https://arxiv.org/abs/2109.10086>）：
  学习式稀疏展开，把"同义不同词"放进倒排。对"city/住在/搬到"这类词面漂移有用。

### 1.2 稠密检索

- **DPR**（Karpukhin et al. 2020, <https://arxiv.org/abs/2004.04906>）开山；
  **ANCE**（Xiong et al. 2020, <https://arxiv.org/abs/2007.00808>）难负例；
  **Contriever**（Izacard et al. 2021, <https://arxiv.org/abs/2112.09118>）
  无监督对比——个人语料没标注，无监督路线更贴。
- **ColBERT**（Khattab & Zaharia 2020, <https://arxiv.org/abs/2004.12832>）：
  late interaction，逐 token 相似度后再聚合，精度高、索引体积大；
  也可只作**重排器**用在 top-k 之后。

### 1.3 重排

- **monoT5**（Nogueira et al. 2020, <https://arxiv.org/abs/2003.06713>）：
  seq2seq 打分 "relevant true/false"，小模型即可跑。
- **RankGPT**（Sun et al. 2023, <https://arxiv.org/abs/2304.09542>）：
  LLM listwise 重排，零样本即可用——成本记进 llm_tokens，要谨慎。

### 1.4 查询改写 / 扩展（读端不变，写查询侧）

- **Rewrite-Retrieve-Read**（Ma et al. 2023, <https://arxiv.org/abs/2305.14283>）：
  先改写 query 再检索，训练用小模型 + reader 反馈。
- **HyDE**（Gao et al. 2022, <https://arxiv.org/abs/2212.10496>）：
  先让 LLM 写"假想答案文档"再检索其近邻。对个人记忆是天然思路——
  例如探针"此人对风险的偏好"先生成"我是保守型"式伪陈述去匹配记录文本。
- **Query2Doc**（Wang et al. 2023, <https://arxiv.org/abs/2303.07678>）：
  伪文档拼进稀疏/稠密 query。
- **Step-Back prompting**（Zheng et al. 2023, <https://arxiv.org/abs/2310.06117>）：
  先抽象成高层问题再检索——对应 transfer 类"制定计划需要哪些约束"探针。

### 1.5 迭代 / 自适应检索（答着答着再查）

- **ReAct**（Yao et al. 2022, <https://arxiv.org/abs/2210.03629>）：
  推理-行动交错，引出"按需检索"范式。
- **IRCoT**（Trivedi et al. 2022, <https://arxiv.org/abs/2212.10509>）：
  CoT 每一步交替检索，多跳问题显著优于单跳。
- **FLARE**（Jiang et al. 2023, <https://arxiv.org/abs/2305.06983>）：
  生成中遇到低置信 token 就触发再检索——**置信度驱动检索**，直接对应
  "先写草稿→发现低置信位→补查"的双层结构。
- **Self-RAG**（Asai et al. 2023, <https://arxiv.org/abs/2310.11511>）：
  用 reflection token 让模型自己决定"要不要检索/证据是否相关/答案是否忠实"——
  检索必要性判定本身就是 M4 的 abstain gate。
- **Adaptive-RAG**（Jeong et al. 2024, <https://arxiv.org/abs/2403.14403>）：
  按查询复杂度路由（不检索/单跳/多跳），直接省 probe_bytes。
- **Corrective RAG**（Yan et al. 2024, <https://arxiv.org/abs/2401.15884>）：
  检索结果先过相关性评估器，不行就改写/降级——"检索质量门"。
- 基准侧参考 **CRAG**（Meta KDD Cup 2024 综合 RAG 基准,
  <https://arxiv.org/abs/2404.02120>）：把"不可答""动态变化"作显式类别，
  冠军方案的共同点都是**路由器前置**而非检索器堆料。

### 1.6 图检索与层级索引

- **GraphRAG**（Microsoft, Edge et al. 2024, <https://arxiv.org/abs/2404.16130>）：
  LLM 抽实体图→社区检测→层级社区摘要→map-reduce 作答全局问题。
  对"这个人的整体画像"型探针有用，但索引构建成本高。
- **LightRAG**（Guo et al. 2024, <https://arxiv.org/abs/2410.05779>）：
  图 + key-value 双层检索，比 GraphRAG 快省。
- **HippoRAG**（Gutiérrez et al. 2024 NeurIPS, <https://arxiv.org/abs/2405.14831>）：
  海马体索引理论启发，KG + Personalized PageRank 单步达到迭代检索效果，
  便宜 10-20 倍——**多槽关联（transfer）探针的强候选**。
- **RAPTOR**（Sarthi et al. 2024 ICLR, <https://arxiv.org/abs/2401.18059>）：
  递归聚类-摘要成树，不同粒度问题查不同层——"粒度条件化视图"的标准形态。

### 1.7 多样性 / 去重

- **MMR**（Carbonell & Goldstein, SIGIR 1998,
  <https://dl.acm.org/doi/10.1145/290941.291025>）：相关性与多样性线性折中；
  transfer 探针需要"覆盖面"而非"最像的 top-k"，MMR 或简单按槽去重都值得测。

### 1.8 记忆系统专用检索

- **Generative Agents**（Park et al. 2023 UIST, <https://arxiv.org/abs/2304.03442>）：
  记忆流检索打分 = recency × importance × relevance。**recency×权威性×相关性**
  三因子直接可搬进 LifeStream（self>other 的权威性、day 衰减、slot/text 相似度）。
- **Zep / Graphiti**（Rasmussen et al. 2025, <https://arxiv.org/abs/2501.13956>）：
  时态知识图谱，边带 `valid_at/invalid_at`，天然支持"day40 时我认为是什么"
  的时点查询——正面回应架构 §7 关于时态探针的遗留问题。
- **Mem0**（2025, <https://arxiv.org/abs/2504.19413>）：抽取-合并-检索的
  轻量记忆层，报告了时延/成本数据，可作"最小可维护记忆"参照。
- **A-MEM**（Xu et al. NeurIPS 2025, <https://arxiv.org/abs/2502.12110>）：
  Zettelkasten 式动态链接+记忆演化，记忆条目自带上下文/关键词/标签，
  检索靠链接扩展——服务端的"链式召回"思路。
- **LongMemEval**（Wu et al. 2024, <https://arxiv.org/abs/2410.10813>）把记忆
  系统分解为 **index → retrieve → read** 三阶段并给出各自优化点
  （session 切分、fact-augmented key、时间感知 query expansion）——
  M4 正好覆盖 retrieve+read 两段；框架本身可当我们的设计 checklist。

---

## 2. 上下文预算与压缩（relevance vs token cost）

- **Lost in the Middle**（Liu et al. 2023 TACL, <https://arxiv.org/abs/2307.03172>）：
  关键信息放中间性能显著下降→上下文**排序本身就是优化变量**；把最相关/最新
  证据放首尾，长清单按重要性重排。
- **LLMLingua**（Jiang et al. EMNLP 2023,
  <https://aclanthology.org/2023.emnlp-main.825/>）：token 级删冗，粗到细分级压缩。
- **LongLLMLingua**（Jiang et al. 2023, <https://arxiv.org/abs/2310.06839>）：
  **问题感知**压缩+文档重排——压缩必须知道 query，否则留错东西；
  对应 M4"视图必须 probe-conditioned，不能 query-agnostic 压缩"。
- **LLMLingua-2**（Pan et al. 2024, <https://arxiv.org/abs/2403.12968>）：
  蒸馏出的轻量分类器做压缩，成本更低。
- **RECOMP**（Xu et al. 2023, <https://arxiv.org/abs/2310.04408>）：
  检索文档先压缩成摘要再喂 LM；抽取式（选句）与抽象式（重写）两种；
  **检索结果无关时压缩器输出空串**——压缩器兼任"该不该答"的旁路信号。
- **Selective Context**（Li et al. EMNLP 2023, <https://arxiv.org/abs/2310.06201>）：
  按自信息量删词元，朴素但零成本。
- **MemGPT**（Packer et al. 2023, <https://arxiv.org/abs/2310.08560>）：
  OS 分页式虚拟上下文——context window 当 RAM，外部存储当 disk，
  "分页换入"的决定就是 probe_bytes 的出处；its queue/heartbeat 机制可借鉴
  做"后台补查"。

**对 LifeModel 的翻译**：压缩有两个时点——写时（M2/M3 的资产蒸馏，省
asset_bytes）与读时（M4 的视图/摘要，省 probe_bytes）。M4 侧的最优大概率是
**物化视图**：摄入时就维护 per-slot 摘要条目，读时 O(1) 取出，而不是回答时
临时压缩整库——后者省空间不省 probe_bytes。

---

## 3. 任务条件化视图（一份资产，多种用途）

核心观点：serve 层 = **视图物化器 + 路由器**，而非单一检索器。

- **探针类型路由**：CRAG 冠军方案（见 §1.5）与 Adaptive-RAG 都验证了
  "前置路由器"模式。LifeStream 的 `probe.type` 是显式字段，路由是白送的：
  - state/stale → 槽位点查视图（含 expires/supersede 过滤）
  - prov → (slot,value)→来源 的布尔索引，不查全文
  - retract → 删除登记表
  - transfer → 约束打包视图（一次取多槽、按重要性排序、去旧值）
- **层级/粒度路由**：RAPTOR 树（§1.6）给"细节问题查叶子、概览问题查根"
  的标准做法；GraphRAG 的社区摘要同理用于"整体画像"探针。
- **时点路由**：Zep 的 valid/invalid 边 → "as-of day T" 视图是
  图存储上的物化视图，回答架构 §7 遗留问题：时点探针值得加。
- **写时物化 vs 读时计算**：数据库物化视图的老结论在此依然成立——
  高频低延迟视图（state）写时维护，低频复杂视图（profile 摘要）读时合成。

---

## 4. 校准、拒答与补问（何时说"问用户"）

### 4.1 置信度怎么来

- **Kadavath et al. 2022**（<https://arxiv.org/abs/2207.05221>）：
  大模型自评 P(True)/P(IK) 校准不错，可作 verbalized confidence；
  但有源材料在场时 P(IK) 应上升——正适合"检索命中→置信度↑"的联动。
- 内部探针可区分认知/非认知不确定度（ICML 2024,
  <https://dl.acm.org/doi/10.5555/3692070.3692092>）——黑盒 API 用不了，
  但开源 reader 可用。
- **SelfCheckGPT**（Manakul et al. 2023, <https://arxiv.org/abs/2303.08896>）：
  多次采样一致性当置信度，零资源黑盒可用。
- **conformal prediction**（Angelopoulos & Bates,
  <https://arxiv.org/abs/2107.07511>）：给拒答阈值一个分布无关的保证框架。

### 4.2 拒答（abstention）的可判定性

- **选择性预测**经典：Geifman & El-Yaniv NeurIPS 2017
  （<https://arxiv.org/abs/1705.08500>）risk-coverage 曲线是标准评测；
  Kamath et al. ACL 2020（<https://aclanthology.org/2020.acl-main.503/>）
  把"领域外就拒答"搬到 QA。
- **SQuAD 2.0**（Rajpurkar et al. 2018, <https://arxiv.org/abs/1806.03822>）：
  "不可答"问题的开山标注与 F1 评测方式。
- **R-Tuning**（Zhang et al. 2024 ICLR, <https://arxiv.org/abs/2311.09677>）：
  训练 LLM 对未知问题说 IDK；**Unanswerability Eval for RAG**
  （<https://arxiv.org/abs/2412.12300>）把"不可答"细分为查询侧/证据侧/
  系统侧三类——映射到 LifeStream：证据缺失（retracted/expired）、
  证据冲突（hearsay vs self）、查询歧义，三种该给出不同反应。
- LifeStream 已把"未知"当合法输出，且 must_not 惩罚 −0.5 使
  **拒答的期望收益为正**——阈值设计直接读 §4.3。

### 4.3 补问（clarifying questions）

- 数据/任务：**Qulac**（Aliannejadi et al. SIGIR 2019,
  <https://github.com/aliannejadi/qulac>）与扩展版 **ClariQ**
  （ConvAI3 挑战, <https://arxiv.org/abs/2009.11352>）定义了
  "判断要不要问→问什么"的评测；**AmbigQA**（Min et al. EMNLP 2020,
  <https://arxiv.org/abs/2004.10645>）标注开放域歧义问题。
- 决策框架：**Selectively Answering Ambiguous Questions**（Cole et al.
  2023, <https://arxiv.org/abs/2305.14613>）——"不知道"要区分
  *知识缺失*与*问题本身歧义*，后者才该补问。
- 提问质量：**LaMAI**（Zhang et al. 2024, <https://arxiv.org/abs/2402.03719>）
  用主动学习选"信息量最大的问题"，准确率 31.9%→50.9%；
  **ProactiveCoT**（Deng et al. EMNLP-Findings 2023,
  <https://aclanthology.org/2023.findings-emnlp.711/>）给 LLM 加目标规划
  让主动澄清成习；**Clarify When Necessary**（Zhang & Choi 2023,
  <https://arxiv.org/abs/2311.09469>）主张先估算信息增益再决定问不问。
- **决策理论化**：问的成本是打断用户；答错的风险是 −0.5（bench）或
  信任损失（产品）。策略= `argmax{ E[quality|answer], E[quality|ask]−cost(ask) }`。
  bench 中 ask 恒不可得 → 退化为"答 vs 未知"的二元阈值；产品上 M4 应输出
  `answer | clarify(q') | abstain` 三选一。

---

## 5. 溯源展示（为什么系统这么以为）

- **ALCE**（Gao et al. EMNLP 2023, <https://arxiv.org/abs/2305.14627>,
  代码 <https://github.com/princeton-nlp/ALCE>）：首个自动 citation 评测——
  citation precision/recall + correctness；prov 探针就是它的退化形态。
- **ARES**（Saad-Falcon et al. NAACL 2024, <https://arxiv.org/abs/2311.09476>）：
  微调小 LM judge 评 context relevance / answer faithfulness / answer relevance
  + PPI 校正——"用便宜模型评贵模型"的思路可用于 LifeStream 双层循环。
- **RAGAS**（Es et al. 2023, <https://arxiv.org/abs/2309.15217>）：
  无参考答案的 faithfulness/context precision/context recall 套件，业界事实标准。
- **FActScore**（Min et al. EMNLP 2023,
  <https://aclanthology.org/2023.emnlp-main.741/>）：把长文本拆成原子事实逐个
  查证——评测对象是**人物传记**，与"对一个人的理解资产"完全同构，原子事实
  精确率这个指标可直接抄。
- **RARR**（Gao et al. 2022, <https://arxiv.org/abs/2210.08726>）：
  生成后再检索证据、修订不可归因的句子——"先答后证"流程。
- **Chain-of-Verification**（Dhuliawala et al. 2023,
  <https://arxiv.org/abs/2309.11495>）：自生成核查问题→独立回答→修订，
  可作 must_not 泄漏的事后拦截器。
- **AIS**（Rashkin et al. 2021 综述,
  <https://arxiv.org/abs/2112.12870>）："可归因于已识别来源"的形式化定义，
  prov 探针的理论底座：每个断言要能指回具体 record id。
- 工程含义：视图条目应带 `evidence_ids`，回答侧能把"我说 X 是因为
  r0042（day12，本人，statement）"渲成脚注——也是 M5 删除传导的天然挂点。

---

## 6. 消费级"一份记忆多处用"产品（公开信息）

- **Rewind → Limitless**：Mac 端常驻录屏+录音，VideoToolbox 硬件编码差分压缩
  （宣称 3750x，每月约 14GB），本地 OCR/ASR 建索引，本地存储不上云；
  "Ask Rewind" 用 GPT-4 对检索结果作答。见官网 <https://www.rewind.ai/> 与
  Kevin Chen 技术拆解 <https://kevinchen.co/blog/rewind-ai-app-teardown/>。
  2024 年更名/转向为 **Limitless**（pendant + apps），卖点是"无限存储"
  （自动卸载到手机→云）与 **Consent Mode**（声纹识别+口头 opt-in 才录他人）
  <https://help.limitless.ai/en/articles/10761340-pendant-storage>、
  <https://help.limitless.ai/en/articles/10546658-interacting-with-the-pendant-search-ask-ai-summaries>。
  **教训**：全量记录的能力天花板在"被记录者授权"，不在存储。
- **ChatGPT memory**（OpenAI 2024-02 起, <https://openai.com/index/memory-and-new-controls-for-chatgpt/>，
  FAQ <https://help.openai.com/en/articles/8590148>）：双层——显式
  *saved memories*（用户可见可编辑的单条记忆）+ 隐式 *reference chat history*
  （对历史会话做检索式引用）。回答下方可点开 "sources" 看哪条记忆参与了
  个性化。**删除语义是公开教训**：删记忆不删源聊天、重新开启记忆还会
  从历史重建——说明"删除要传导到派生"连头部产品也做得不彻底，是我们
  M5+M4 联动的机会点。
- **Claude**（Anthropic 2025-09 起, <https://claude.com/blog/memory>，
  文档 <https://support.claude.com/en/articles/11817273-use-claude-s-chat-search-and-memory-to-build-on-previous-context>）：
  **project-scoped memory**——每个项目独立记忆实例（与"每个用户一个
  LifeModel 实例"同构的隔离设计）；incognito 聊天不入记忆；检索历史会话
  以 RAG tool call 形式显式呈现；用户可查看/编辑记忆内容。
- **Microsoft Recall**（Copilot+ PC）：周期性截屏建本地可搜索快照；
  因隐私反弹改为默认关闭+opt-in+Windows Hello 验证+应用/网站过滤
  <https://blogs.windows.com/windowsexperience/2024/06/07/update-on-the-recall-preview-feature-for-copilot-pcs/>、
  <https://support.microsoft.com/en-US/Windows/privacy/privacy-and-control-over-your-recall-experience>。
  **教训**：全量捕获本身不是护城河，授权与可控性才是。
- **可嵌入的记忆层产品**：Mem0（<https://mem0.ai/>）、Zep
  （<https://www.getzep.com/>）、LangMem（LangChain 的记忆 SDK,
  <https://langchain-ai.github.io/langmem/>）——把"一份资产供多 app 用"
  做成了 API 生意，接口形态值得参考。
- 开源平替：Khoj（<https://khoj.dev/>）、screenpipe
  （<https://github.com/mediar-ai/screenpipe>）。

**对 M4 的启示**：头部产品的 serve 层都是"检索+注入 system prompt"的薄层，
真正的差异化在**可控性 UI**（可见/可改/可删/按范围隔离）——这与我们的
"资产归本人"原则一致；而 bench 侧的创新空间在它们都没做的
**置信度-溯源-补问**联动。

---

## 7. 值得照抄的评测指标

| 指标 | 出处 | 搬到 LifeStream 的形态 |
|---|---|---|
| quality per probe type | LifeStream 现状 | 已做（breakdown），保持 |
| must_not 泄漏率 | LifeStream 现状 | 已做（−0.5），保持 |
| probe_bytes / asset_bytes / llm_tokens | LifeStream 现状 | 已做；建议加 **quality-vs-probe_bytes 帕累托曲线** 作汇报主图 |
| context precision / recall | RAGAS <https://arxiv.org/abs/2309.15217> | 改造为"查阅字节中真正用到的字节占比"= 检索精度 |
| answer faithfulness / context relevance | ARES <https://arxiv.org/abs/2311.09476> | LM judge 评"答案是否被检索证据支撑"（双层循环可用） |
| citation precision / recall | ALCE <https://arxiv.org/abs/2305.14627> | prov 探针升级：不只问"是不是本人"，还要求列证据 record id |
| 原子事实精确率 | FActScore <https://aclanthology.org/2023.emnlp-main.741/> | 对概览/画像类回答拆事实逐条验 |
| risk-coverage / selective accuracy | Geifman & El-Yaniv <https://arxiv.org/abs/1705.08500> | abstention 的标凈评测：不同阈值下"答的题里对多少" |
| unanswerable F1 | SQuAD 2.0 <https://arxiv.org/abs/1806.03822>；LongMemEval <https://arxiv.org/abs/2410.10813> | retract/expired/从未见过 三类"应未知"探针的命中率 |
| knowledge-update / temporal accuracy | LongMemEval、LoCoMo <https://aclanthology.org/2024.acl-long.747/> | stale 探针已覆盖；可加"day T 时点查询"（Zep 先例） |
| 歧义处理分类 | Cole et al. <https://arxiv.org/abs/2305.14613> | 区分"知识缺失"与"问题歧义"的混淆矩阵 |
| ECE（校准误差） | Kadavath <https://arxiv.org/abs/2207.05221> | 若回答附置信度，可量校准质量 |
| 不可答分类评测 | <https://arxiv.org/abs/2412.12300> | 按查询歧义/证据缺失/证据冲突分列 |

LoCoMo 另有一条直接可用：**对抗性探针**（adversarial questions，看似
可答实则不可答）——正好测 hearsay/suggestion 污染。

---

## 8. 候选方法 → 种子/基线清单（按预期性价比排序）

S 档（建议直接编码为基线）：

| # | 方法 | 做法 | 覆盖探针 | probe_bytes 预期 |
|---|------|------|----------|------------------|
| S1 | 槽位物化视图直接 serve | 摄入时维护 per-slot 条目 {value, day, src, kind, expires}；answer 只查视图，不查原始记录 | state/stale/transfer | O(1)/探针 |
| S2 | 探针类型路由器 | type→对应视图/索引；prov 走 (slot,value)→source 布尔表；retract 走删除登记表 | 全类型 | O(1) |
| S3 | 拒答门（abstention gate） | 证据缺失/被撤回/仅 hearsay-suggestion/过期 → "未知"或"已删除"（借鉴 selective prediction 阈值） | state/stale/retract/prov | ≈0（守门先于检索） |
| S4 | 时点过滤+末写权威 | ckpt 截断 + expires_day + last-write-wins + source 权威序（self>other/assistant） | state/stale | O(1) |

A 档（高收益、中成本，二轮进化候选）：

| # | 方法 | 做法 | 备注 |
|---|------|------|------|
| A1 | 混合检索 BM25+dense+RRF+重排 | 记录文本建稀疏/稠密双索引，top-k 后小模型重排 | 槽位缺失或文本噪声大时兜底 |
| A2 | recency×authority×relevance 打分 | Generative Agents 三因子（day 衰减 × source 权威 × 文本相似度） | 对噪声/冲突记录天然过滤 |
| A3 | CRAG 式检索质量门 | 检索结果先评相关性，不相关→改写查询或 abstain | 与 S3 互补：S3 管"资产里没有"，A3 管"检索到的不对" |
| A4 | 写时蒸馏视图 | RECOMP/LLMLingua 思路移到摄入侧：每条记录蒸馏为 {断言, 证据id, 有效期} 短条目 | 省 asset_bytes 也省 probe_bytes |
| A5 | 先答后证（post-hoc verification） | CoVe/RARR：草稿→自查 must_not/证据→修订 | 拦截 must_not 泄漏（值 −0.5） |
| A6 | 查询改写 / HyDE | 探针 q → 伪陈述/改写再检索 | 表面形式不匹配时补召回 |

B 档（探索性，视收益再上）：

| # | 方法 | 价值 |
|---|------|------|
| B1 | 时态知识图谱（Zep 式 valid/invalid 边） | 时点查询、跨槽推理、retraction 级联可视 |
| B2 | HippoRAG 图检索（PPR） | transfer 类多跳打包；比迭代检索便宜 |
| B3 | RAPTOR 摘要树 | "整体画像"类概览探针的粒度视图 |
| B4 | 补问队列（LaMAI/Clarify-When-Necessary 策略） | 产品域刚需；bench 上退化为 abstain，先占接口位 `answer|clarify` |
| B5 | LLM 读端（reader 用 LLM 而非规则） | llm_tokens 成本换泛化理解；LongMemEval 显示该花则花 |

---

## 9. 给评测器/协议的建议（带回架构 §7）

1. **时点探针值得加**："day40 时此人认为 X 是什么"——Zep 的
   valid/invalid 边证明这是可回答、可评分的，且直接测更新传导。
2. probe_bytes 建议按"answer() 实际触碰的 asset 字节"由评测器计量
   （接口层面已规划 v1 由评测器度量，保持）。
3. **三值输出空间**：产品侧 answer 应能返回 `值 | clarify(q') | abstain`；
   bench 中 clarify 映射为"未知"即可，但接口现在就留位。
4. prov 探针可升级为"给出证据 record id"（ALCE 式），顺带打通 M5
   删除传导的测试点（删了 record → 依赖它的回答应失效）。
5. 对抗性探针（LoCoMo 式）：表面可答、实则不可答（hearsay 刚好
   长得像本人陈述）——专测 S3/A3 门。

---

## 参考文献（全文引用 URL 汇总）

检索族：BM25 <https://doi.org/10.1561/1500000019>；doc2query
<https://arxiv.org/abs/1904.08375>；SPLADE v2 <https://arxiv.org/abs/2109.10086>；
DPR <https://arxiv.org/abs/2004.04906>；ANCE <https://arxiv.org/abs/2007.00808>；
Contriever <https://arxiv.org/abs/2112.09118>；ColBERT
<https://arxiv.org/abs/2004.12832>；monoT5 <https://arxiv.org/abs/2003.06713>；
RankGPT <https://arxiv.org/abs/2304.09542>；RRR <https://arxiv.org/abs/2305.14283>；
HyDE <https://arxiv.org/abs/2212.10496>；Query2Doc
<https://arxiv.org/abs/2303.07678>；Step-Back <https://arxiv.org/abs/2310.06117>；
MMR <https://dl.acm.org/doi/10.1145/290941.291025>。

迭代/自适应：RAG 原始 <https://arxiv.org/abs/2005.11401>；RAG 综述
<https://arxiv.org/abs/2312.10997>；ReAct <https://arxiv.org/abs/2210.03629>；
IRCoT <https://arxiv.org/abs/2212.10509>；FLARE <https://arxiv.org/abs/2305.06983>；
Self-RAG <https://arxiv.org/abs/2310.11511>；Adaptive-RAG
<https://arxiv.org/abs/2403.14403>；Corrective RAG <https://arxiv.org/abs/2401.15884>；
CRAG benchmark <https://arxiv.org/abs/2404.02120>。

图/层级：GraphRAG <https://arxiv.org/abs/2404.16130>；LightRAG
<https://arxiv.org/abs/2410.05779>；HippoRAG <https://arxiv.org/abs/2405.14831>；
RAPTOR <https://arxiv.org/abs/2401.18059>。

记忆系统：Generative Agents <https://arxiv.org/abs/2304.03442>；MemGPT
<https://arxiv.org/abs/2310.08560>；Zep <https://arxiv.org/abs/2501.13956>；
Mem0 <https://arxiv.org/abs/2504.19413>；A-MEM <https://arxiv.org/abs/2502.12110>；
LongMemEval <https://arxiv.org/abs/2410.10813>；LoCoMo
<https://aclanthology.org/2024.acl-long.747/>。

压缩/预算：LLMLingua <https://aclanthology.org/2023.emnlp-main.825/>；
LongLLMLingua <https://arxiv.org/abs/2310.06839>；LLMLingua-2
<https://arxiv.org/abs/2403.12968>；RECOMP <https://arxiv.org/abs/2310.04408>；
Selective Context <https://arxiv.org/abs/2310.06201>；Lost in the Middle
<https://arxiv.org/abs/2307.03172>。

置信/拒答/补问：Kadavath <https://arxiv.org/abs/2207.05221>；Kempner
<https://dl.acm.org/doi/10.5555/3692070.3692092>；SelfCheckGPT
<https://arxiv.org/abs/2303.08896>；Conformal <https://arxiv.org/abs/2107.07511>；
Geifman & El-Yaniv <https://arxiv.org/abs/1705.08500>；Kamath et al.
<https://aclanthology.org/2020.acl-main.503/>；SQuAD 2.0
<https://arxiv.org/abs/1806.03822>；R-Tuning <https://arxiv.org/abs/2311.09677>；
Unanswerability-for-RAG <https://arxiv.org/abs/2412.12300>；Qulac
<https://github.com/aliannejadi/qulac>；ClariQ <https://arxiv.org/abs/2009.11352>；
AmbigQA <https://arxiv.org/abs/2004.10645>；Cole et al.
<https://arxiv.org/abs/2305.14613>；LaMAI <https://arxiv.org/abs/2402.03719>；
ProactiveCoT <https://aclanthology.org/2023.findings-emnlp.711/>；
Clarify When Necessary <https://arxiv.org/abs/2311.09469>。

溯源/归因：ALCE <https://arxiv.org/abs/2305.14627>；ARES
<https://arxiv.org/abs/2311.09476>；RAGAS <https://arxiv.org/abs/2309.15217>；
FActScore <https://aclanthology.org/2023.emnlp-main.741/>；RARR
<https://arxiv.org/abs/2210.08726>；CoVe <https://arxiv.org/abs/2309.11495>；
AIS 综述 <https://arxiv.org/abs/2112.12870>。

产品：Rewind <https://www.rewind.ai/>；Rewind 拆解
<https://kevinchen.co/blog/rewind-ai-app-teardown/>；Limitless
<https://www.limitless.ai/>、
<https://help.limitless.ai/en/articles/10761340-pendant-storage>、
<https://help.limitless.ai/en/articles/10546658-interacting-with-the-pendant-search-ask-ai-summaries>；
ChatGPT memory <https://openai.com/index/memory-and-new-controls-for-chatgpt/>、
<https://help.openai.com/en/articles/8590148>；Claude memory
<https://claude.com/blog/memory>、
<https://support.claude.com/en/articles/11817273-use-claude-s-chat-search-and-memory-to-build-on-previous-context>；
Microsoft Recall <https://blogs.windows.com/windowsexperience/2024/06/07/update-on-the-recall-preview-feature-for-copilot-pcs/>、
<https://support.microsoft.com/en-US/Windows/privacy/privacy-and-control-over-your-recall-experience>；
Mem0 <https://mem0.ai/>；Zep <https://www.getzep.com/>；LangMem
<https://langchain-ai.github.io/langmem/>；Khoj <https://khoj.dev/>；
screenpipe <https://github.com/mediar-ai/screenpipe>。
