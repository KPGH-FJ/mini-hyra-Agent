# LifeModel System v0 — 框架与接口（v1.2，P3 r1–r5 已回灌）

> 研究对象是一套**可复用的方法系统**：把单个用户授权的记录流灌进去，
> 系统持续形成并维护一份"对这个人的理解资产"，供不同用途调用。
> 每个用户得到的是该系统的一个实例。现阶段核心约等于"下一代 memory"。

## 0. 设计原则（来自 RESEARCH_BRIEF，不可丢）

- 同一个人的广泛生活/工作；承认资料不完整、人会变。
- 一份积累服务多种用途（视图可不同，积累只有一份）。
- 新记录推动理解持续变化；纠错要能真正传导到后续推断。
- 资产归本人、由本人控制：看/改/删/限用途/迁出，且改动要生效。
- 一切结论用"完整生命周期总分"裁决，禁止局部优化脱节。
- 站在前人成果上：每模块先调研（见 docs/literature/），候选空间从
  已知方法族出发，不闭门造车。

## 1. 模块分解

```
record stream ──► [M1 Ingest 摄入]   归一化事件：谁说的/什么类型/何时/信源强度
              ──► [M2 Store 表征]    理解资产本体：事实/关系/目标/约束/不确定度
              ──► [M3 Update 更新]   补充/取代/纠错/撤回/过期/遗忘的传导语义
              ──► [M4 Serve 使用]    按用途生成视图与回答 + 置信度 + 补问判断
              ──► [M5 Control 控制]  查看/纠正/删除/导出/限用途；删除传导
                       ▲
                  评测器驱动全链路（LifeStream）── 质量 − 成本 = 总分
```

模块间**接口冻结、实现可换**：进化每次只放开一个模块，其余固定。

## 2. 接口契约（Python 层，与评测协议对齐）

```python
# record：进入系统的最小单位（评测器/真实管道都产这个）
rec = {day:int, source:str, kind:str, slot:str|None, text:str, value:str|None}
# source ∈ self|other|assistant|device|doc；kind ∈ statement|update|
# correction|retraction|suggestion|hearsay；value 是机器可读载荷（可选）

class LifeModel:
    # M1+M3：摄入一条记录 → 归一化事件 → 更新资产
    def ingest(self, rec) -> None

    # M4：按探针生成回答（探针带 ckpt=截止时间，禁止偷看未来）
    def answer(self, probe) -> str          # probe={q,type,slot,ckpt,...}

    # M5：用户控制 API
    def correct(self, slot, new_value) -> None   # 人工纠错，传导到派生
    def forget(self, scope) -> None              # 删除：slot 或时间范围
    def revoke_purpose(self, purpose) -> None    # 撤回某用途（数据留，视图拒）
    def export(self) -> dict                      # 完整可迁移的资产快照
    # journal：操作日志，是资产的一部分（state()/snapshot 携带、import
    # 后仍可审计）；ops 探针只读它

    # 成本——v1 起由评测器直接度量，不再信 stats() 自报（堵 s0023 漏洞）
    def state(self) -> dict            # 可序列化内部状态（评测器量字节）
    def probe_bytes(self) -> int       # 累计检索/传输给回答层的字节
```

## 3. 各模块的候选空间（调研纪要：docs/literature/m*.md）

- **M1**（m1_ingest.md，PR#3）：归一化事件 schema；truth discovery
  （TruthFinder/CATD 式信源加权）、实体消歧、subjective logic 处理传闻；
  11 个 seed 候选。
- **M2**（m2_representation.md，PR#5）：10 个表征族（bitemporal DB、frames/
  RDF、Zep/Graphiti、MemGPT/mem0/A-MEM、Generative Agents、RAPTOR/GraphRAG、
  参数记忆、PROV/NELL、TMS/AGM）；种子表 S1–S8，建议 S1 bitemporal-ledger、
  S3 episode+fact 双层、S7 event-sourced 先入库做基线。
- **M3**（m3_update.md，PR#4）：Katsuno–Mendelzon update-vs-revision 区分
  ≈ 我们的 update/correction；**TMS 依赖追踪是“纠错必须传导”的唯一直接
  机制** → M2 派生条目应挂 `supports=[rec_id]`；Zep 四时间戳边 = 双时态
  工业实现；unlearning 基本不迁移；种子 S1–S9 按 ledger→event-sourced→
  TMS 层→压缩 的顺序登。
- **M4**（m4_serve.md，PR#6）：三元决策形式化（查哪些/答不答/怎么呈现）；
  RAG 全谱系、上下文压缩、selective prediction 校准拒答、ALCE/RAGAS 溯源
  展示；种子 S1–S4 可做基线。
- **M5**（m5_control.md，PR#2）：真删除=依赖图+级联失效（与 M3/TMS 合流）；
  unlearning 对显式资产不适用；Solid pods 是“资产归本人”的最近似已有
  架构（export/forget 应是 Pod 式视图而非厂商施舍）；控制操作应走同一
  条事件管线；候选 C0–C5（派生注册表、事件溯源控制、TMS 级联、用途标注、
  待确认纠正队列）。

### 调研共识 → 接口修订（冻结进契约的增量）

1. **派生条目挂 `supports=[rec_id]`**（M2×M3×M5 三份纪要共同指向）：
   删除/撤回才能级联。v0 先不强制，P3 M3 轮次会要求。
2. **hearsay 断言带 subject 维度**（M2）：谁传闻谁 —— LifeStream v2
   subject 探针已落地此要求。
3. **as_of 时态查询**（M2/M3/M4 共同建议）：资产必须能回答“第 D 天时
   是什么” → 等价于要保留（可重建的）历史 → LifeStream v2 as_of 探针。
4. **控制操作即事件**（M5）：correct/forget 走同一管线进 journal →
   LifeStream v2 cascade 探针（评测器在 ckpt 边界调 forget()）。

## 4. 评价方案（LifeStream v6c — 已落地）

- 生命周期：ingest 分段 → checkpoint 探针 → 控制事件 → 再探针（5 ckpt）
- 探针类型（15 种，累积压强）：state/stale/prov/retract/transfer ＋
  as_of/subject/cascade（v2）＋ derive/post_import（v3）＋
  unans/purpose/budget/prov2（v4）＋ revoked（v6）＋ ops（v6c）
- 摄入压强（v5）：alias 别名消歧 + 乱序到达（day 权威，非到达序）
- 控制事件（评测器驱动）：forget(slot)@55 / forget_range@62 回滚 /
  correct@78 / revoke_purpose@84 / state→import_state 往返@72
- 成本：评测器实测（state 序列化、probe_bytes、llm_tokens），
  stats() 自报仅 fallback 并标 cost_how
- 基线：raw / ledger / rag / flat / tms / esr（六族同流同题）

## 5. 迭代协议（研究节奏）

1. 一次进化只开一个模块的实现空间；总分不降才允许接口外改动。
2. 每代产出：REPORT.md（谁赢/为什么/瓶颈在哪块）+ EB 快照 + 最优实现。
3. 模块登顶顺序预期：M2 表征 → M3 更新 → M4 使用 → M1/M5。
   依据：第一轮实验证明表征结构是最大变量（26.5MB→29KB）。
4. 文献调研纪要与代码同等地位：调研产出的方法族直接转成候选种子。

## 6. 阶段路线

- **P0**（本文件）：框架+接口定稿 ✓（cffc106）
- **P1**：五模块文献调研纪要 ✓（PR#2–#6，docs/literature/）
- **P2**：v0 骨架实现 ✓（lifemodel/，361e681；LifeStream v2 加固评测器
  — as_of/subject/cascade 探针）
- **P3**：逐模块 Hyra 进化（每次单模块开放，全链路评分）← 当前
  - **r1 M2 表征 ✓**：按（主体,槽位）时态历史获胜，已回灌为
    TemporalGraph（results/life_model_v2/FAMILY_RACE.md）
  - **r2 M3 更新 ✓**：TMS 前提维护获胜（supports→premises+
    _prune 不动点，与事件溯源同质量、读成本 ~320x 低），已回灌
    （results/life_model_v3/FAMILY_RACE.md）
  - **r3 M4 使用 ✓**：serve 语义经 v4 考题验证后直接沉淀系统
    （probe-type router + live_bundle + rvid 引用），未开实验室轮
  - **r4 M1 摄入**：v5 考题上线（别名+乱序）；lab run_v5 进化中
  - **r5 M5 控制**：v6 考题上线（revoked/forget_range 回滚/ops 审计）；
    系统已 134.97/135 满分，家族淘汰赛见 results/life_model_v6/
- **P4**：真实授权数据验证（需单独授权，brief §83）

## 7. 遗留问题（r5 后更新）

- ~~stats() 作弊洞~~：已堵。
- ~~时态查询/as_of/cascade/派生失效~~：全部落地并满分。
- ~~export-import 探针~~：v3 已落地（post_import 旗标）。
- ~~三值输出~~：unans 探针落地了 abstain 侧；clarify 无对话通道
  仍映射为“未知”。
- 新 v7 候选：NL 查询表面（query.py 未考）、部分导出（只导出某
  用途视图）、同日冲突源、审计深度（ops 带 day/scope）、
  control-cost（用户操作步数入总成本）。
