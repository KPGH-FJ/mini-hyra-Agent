# M2 Typed-record 设计稿 V2（讨论稿增补版）

V1 在同目录 REPORT.md §M2。本版按 friedmangael 三轮复核收紧：两段式对照、
留出集、事件语义、证伪边界。**仍只是讨论稿，不含实验运行。**

## 1. Schema 修订（相对 V1）

### 1.1 事件身份：独立 event_id + 疑似重复关联（不合并）

V1 的"同 verb/object/时间重叠即同事件"降级为**疑似重复关联边**：

- 每条记录分配独立 `event_id`；同日两次购买是合法两事件。
- `(verb归一, object, time_anchor区间重叠)` 匹配只产出 `dup_link` 边
  （A↔B 疑似同事件 + 证据），**不合并、不改写**。
- 聚合默认按 event 计数；重复关联作为证据列出，判重决策留痕可回查。

### 1.2 记录四态：否定不记账面负数

`kind ∈ {asserted, negated, planned, cancelled}` 分开：

- `negated`（"没做X"）不进正向枚举，也**不抵消** asserted 事件——
  它是对同一槽位的另一态事实，不是算术 −1。
- `planned`（计划）与 `asserted`（已完成）分开；`cancelled` 单列。
- `correction` 记录 = **带版本的指向**（supersede 链）：指向被纠正记录，
  旧版本保留，M3 可顺链清理——与现有 TMS 前提维护同构。

### 1.3 字段语义补全（第一轮已通过项）

- 未知数量：`quantity=null` + `quantifier="unspecified"`——区分"无记录"
  与"有记录但未报数"；枚举题答"N 条记录·数量未注明"而非编造。
- 模糊日期：`when_abs` 带 `granularity ∈ {day,month,year,relative}`；
  "last month" 存月粒度不强行解到日（anchor-v2 教训直接吸收）。
- 共指未决：`about` 保留表面形式 + `referent=null`，后续绑定走 M3
  修订字段、不改原文（留痕）。
- 溯源：字段级 `rid` 回指源 utterance，与 premise-verify 现用机制同构；
  `text` 原文永远保留，typed 字段是投影不是替代。

## 2. 最小对照设计（两段式）

目标：定位残尾枚举病灶究竟在"表征"还是"抽取"。

**段 1 — 表征上限（oracle 字段臂）**
同一 verify150 快照，typed 字段由人工/理想方式补齐（完美字段）。
- 若完美字段仍救不回枚举题 → **证伪边界：只证伪"这套
  schema+检索聚合链路"的实现，不证伪表征方向本身**（可能 schema
  维度选错，方向仍可另证）。
- 成本低、不动摄入。

**段 2 — 抽取保真（真实抽取臂）**
同题，typed 字段由真实抽取器产出。
- 与段 1 的差距 = 抽取成本；单列字段准确率、漏项率、重复事件率。
- 段 1 过了才轮到段 2 定位摄入侧病灶。

**两臂共用**：同 reader、同判官、同对照题。

## 3. 留出集与判定规则

- **留出集**：设计期没碰的枚举题 + flat 记录下本来就答对的枚举题
  （后者是对照侧误伤探针——typed 臂若把它们答错=连带伤）。
- **救回 4/5 已知错题只算诊断结果**，不构成方向证伪/证实；
  判定看留出集 + 对照侧连带伤。

## 4. 聚合规则（枚举题路径）

```
answer_enum(q):
    cands = grep(verb∈Q.verbset AND object matches AND when_abs∈Q.window)
    events = resolve_dup_links(cands)        # 按关联边去重，留痕
    kinds  = filter(kind=asserted)            # negated/planned/cancelled 排除
    return count(events) + citation(rids)
```

计数是确定性 grep+去重，模型只做接口组装不碰穷举——这是 typed-record
相对已反证三臂（答案侧候选表/摄入枚举标记/画像分节）的唯一新增机制点：
**把枚举从"模型召回"移到"代码检索"**。

## 5. 未决项

- verb 词表开放度：`other` 逃逸 + 词表漂移监控，防 schema 自身成新有损层。
- 抽取字段准确率与 verify 的联动：verify 审计要不要扩到字段级。
- 成本：typed 抽取 prompt 变大 + 可能的 dup_link 判定调用。
