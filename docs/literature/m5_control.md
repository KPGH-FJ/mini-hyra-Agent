# M5 Control（个人控制）— 文献调研纪要

> 目标：用户能查看、纠正、限制用途、撤回、删除、保有、迁移自己的资产；
> 且操作**真正传导**到派生内容与使用端，而非表面开关。
> 对应 RESEARCH_BRIEF §1.5 / §3.6。

## 1. 方法族谱

### A. 数据主权架构（"资产在我手里"的结构性实现）
- **Solid Pods**（Berners-Lee, MIT/Inrupt）：个人在线数据存储（Pod）与应用
  解耦；WebID 身份 + ACL 细粒度授权 + 全部 W3C 标准。
  *要点*：数据所有权不是靠 App 提供"导出按钮"，而是存储层就归本人；
  应用是被授权访问的客人。**与 LifeModel 理念同构**——我们的 export()/
  forget() 应视自己为 Pod 的视图与操作，而非厂商施舍的功能。
  参考: https://solidproject.org/ ; solid.pdf (cs.brown.edu)
- **Diaspora / Musubi / WebBox**：早期去中心化尝试，证明纯理念可行，
  死于生态；教训是控制层必须在通用接口上，不然没有应用肯接。

### B. 法定权利工程化（"删除"到底删多深）
- **GDPR Art.17 right to erasure**：要求"删除个人数据"，但对**派生数据**
  （推断、摘要、嵌入向量、已训练权重）是否算"个人数据"界定模糊——
  这正是我们资产的最难点：删掉一条原始记录容易，删掉它产生的
  结论/概括难。
- **删除传导（deletion propagation）**：数据库侧的级联删除、
  物化视图的失效重建、备份/日志中的残留——工程共识是"没有依赖图
  就没有真删除"。**依赖注册表（每派生物挂溯源指针）是实现真删除的
  唯一通用机制**，与 M3 的 TMS 依赖追踪天然合流。

### C. 机器学习遗忘（unlearning）
- **精确遗忘**（SISA sharding / retrain-free）：分片重训，理论保证但
  成本高；**近似遗忘**（影响函数、梯度反冲）快但只有经验保证。
- **对本项目的启示**：unlearning 针对的是"权重里的记忆"；我们的资产
  是**符号化/显式的**——删除可以直接作用于事实条目，真正的难点在
  **派生结论**（从被删事实推出的其他条目）。所以我们的问题更像 TMS
  而非 unlearning；但如果未来引入参数化记忆（模型权重里的人），
  unlearning 才重新变成必答题。**v0 选择显式表征部分原因在此。**
  参考: ACM Computing Surveys "Machine Unlearning: A Survey" (10.1145/3603620)

### D. 操作与审计（"控制要留痕"）
- **Append-only 操作日志 / 事件溯源**：每一次 correct/forget/restrict
  记入不可变日志，既是审计依据也是重放基础（资产可从日志重建）。
- **派生物注册表（derived-content registry）**：每个派生条目登记
  `derived_from=[src_ids]`；删除源 → 遍历派生 → 失效/重算。
  LifeModel v0 的 journal 是其雏形，尚缺派生端。

### E. 产品层的控制 UI（"让用户管得动"）
- **ChatGPT memory / Mem.ai / Notion memory**：提供记忆条目的
  查看/删除/开关；共同弱点：**无派生传导**（删一条记忆不保证已生成
  回答/摘要失效），无版本/纠错语义，无迁移格式。
- **维护负担最小化**：全部手动逐条管理不可行（用户记不住几百条）；
  已知手法：批量审阅视图、过期自动过期、"系统建议的纠正"待确认队列
  （让系统主动提出"这条可能过时了？"由用户一键确认——把纠正成本
  从"找"降到"点"）。

### F. 同意与用途限制（purpose limitation）
- **Consent receipts / data-use policies**（Kantara, Open Consent）：
  授权记录为可机读收据（谁/何用途/何时/多长期限）。
- **Solid 的 ACL + 用途标注**：访问按"用途"而不仅是"身份"授权——
  LifeModel 场景是"同一资产不同用途视图"：控制层应支持按用途开关
  （如"健康相关槽位不用于日程规划"）。

## 2. 对 LifeModel 的直接结论

1. **真删除 = 依赖图 + 级联失效**，不可能是"删一条记录"。
   短期实现：派生物注册表（ctx/prov/摘要均挂源 ID）；长期与 M3 TMS 合一。
2. **控制操作本身是记录流的一种**：correct/forget 应走和 ingest
   同一条事件管线（带操作语义的事件），而不是旁路直接改库——
   保证日志一致、可重放、评测器可注入控制事件考核传导。
3. **维护负担是硬指标**：除了正确性，还应度量"用户做了几步操作"——
   评测时可加"控制探针"：删除后派生探针是否也失效（cascade probe）。
4. **迁移/导出**：export() 输出必须是完整自描述快照（含 journal），
   能喂给另一个实例 ingest 重建——评测可加"导出-重建-再答"探针。

## 3. 候选方法（作为 seeds/baselines 编码）

| 候选 | 描述 | 预期表现 |
|---|---|---|
| C0 现状 v0 | journal + slot/day 范围删除 | 基线：能删 state/prov，不删派生 |
| C1 派生注册表 | 每个缓存/摘要条目挂 derived_from；删除级联 | 控制探针满分，成本略增 |
| C2 事件溯源控制 | correct/forget 也写成事件，资产=日志投影 | 天然可重放/可迁移；删除=反向事件 |
| C3 TMS 级联（与 M3 合流）| 结论挂支持集，源失效→派生自动失效 | 最强语义，实现最重 |
| C4 用途标注 | 槽位/条目带 purpose tag，serve 按用途过滤 | 支持"限用途"探针 |
| C5 待确认纠正队列 | 系统发现疑似过时→进 review 队列→用户确认生效 | 测维护负担指标 |

## 4. 建议评测补充（写进 LifeStream v2）

- **cascade probe**：forget(slot) 后，凡依赖该槽的回答必须转为"未知/已删除"——
  当前基准只测 state 消失，未测派生失效。
- **export-import probe**：export() → 新实例 ingest 重建 → 再答全部探针，
  检验可迁移性（"资产归本人"的直接证据）。
- **control-cost 度量**：把控制操作步数/字节计入总成本（维护负担）。

## 5. 关键参考

- Solid spec & pods: https://solidproject.org/ ; Mansour et al., "A Demonstration
  of the Solid Platform for Social Web Applications" (cs.brown.edu/courses/csci2390/2021/readings/solid.pdf)
- "Making Sense of Solid for Data Governance and GDPR", Information 14(2), 2023, doi:10.3390/info14020114
- "Machine Unlearning: A Survey", ACM Computing Surveys, doi:10.1145/3603620
- "Algorithms that forget: Machine unlearning and the right to erasure",
  Computer Law & Security Review, doi:10.1016/j.clsr.2023.01.001
- Kantara Consent Receipt spec: https://kantarainitiative.org/
- de Kleer, "An Assumption-based TMS", Artificial Intelligence 28(2), 1986
  （与 M3 纪要互相引用）
