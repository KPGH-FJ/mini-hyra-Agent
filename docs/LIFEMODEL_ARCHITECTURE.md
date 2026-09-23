# LifeModel System v0 — 框架与接口（草案，待发起人过目）

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
    def export(self) -> dict                      # 完整可迁移的资产快照

    # 成本——v1 起由评测器直接度量，不再信 stats() 自报（堵 s0023 漏洞）
    def state(self) -> dict            # 可序列化内部状态（评测器量字节）
    def probe_bytes(self) -> int       # 累计检索/传输给回答层的字节
```

## 3. 各模块的候选空间（先占位，调研后充实）

- **M1**：透传式 / 归一化+置信度标注 / 冲突登记表（truth discovery 思路）
- **M2**：s0011 式按槽权威索引（现任冠军）/ 双时态表 / 时态知识图谱(Zep-like)
  / 摘要树 / 向量+结构混合
- **M3**：直接覆盖（现状）/ supersede 链 / **TMS 依赖追踪**（撤回自动失效推论）
  / AGM 修正语义 / 事件溯源+投影重建
- **M4**：全量回放 / 槽位定向 / RAG top-k / 置信度门槛+拒答补问
- **M5**：无 / 操作日志+级联失效 / 派生物注册表（每派生内容挂溯源，
  删除时可清扫）

## 4. 评价方案（沿用并加固 LifeStream）

- 生命周期：ingest 分段 → checkpoint 探针 → 更新事件 → 再探针（5 个 ckpt）
- 探针类型：state / stale / prov / retract / transfer，77 个
- 成本：评测器实测（state 序列化字节、probe_bytes、llm_tokens）——
  stats() 仅作声明性参考，不作分数依据（v1 修复点）
- 基线：raw / ledger / rag + 调研后新增方法族基线
- 双层循环：评估器可共进化，专门盯着新型作弊面

## 5. 迭代协议（研究节奏）

1. 一次进化只开一个模块的实现空间；总分不降才允许接口外改动。
2. 每代产出：REPORT.md（谁赢/为什么/瓶颈在哪块）+ EB 快照 + 最优实现。
3. 模块登顶顺序预期：M2 表征 → M3 更新 → M4 使用 → M1/M5。
   依据：第一轮实验证明表征结构是最大变量（26.5MB→29KB）。
4. 文献调研纪要与代码同等地位：调研产出的方法族直接转成候选种子。

## 6. 阶段路线

- **P0**（本文件）：框架+接口定稿 ← 当前，待过目
- **P1**：五模块文献调研纪要（并行子会话）→ 候选空间充实 + 新基线
- **P2**：v0 骨架实现：M2 用 s0011 方案，其余最简实现；基准全绿
- **P3**：逐模块 Hyra 进化（每次单模块开放，全链路评分）
- **P4**：真实授权数据验证（需单独授权，brief §83）

## 7. 当前遗留问题（带进 P1 调研）

- stats() 作弊洞：state()/probe_bytes 由评测器度量后，接口语义如何
  约束"诚实记账"仍要保证模块可自由换实现。
- retraction 的传导深度：v0 只删槽位，TMS 式级联失效是 M3 首个候选。
- prov/transfer 之外是否需要"时态查询"探针（"day40 时我以为是什么"）——
  取决于调研发现的能力缺口。
