# M2 typed-record — stage-1 oracle 证伪结果

**设计**: TYPED_RECORD_DESIGN_V2.md（#91）——段1 = 理想 typed 字段 + 确定性聚合，救不回 ≥4/5 枚举残尾题则"此 schema+检索聚合实现"被证伪（不证伪方向）。
**执行**: 离线零 LLM 成本；基板 = `results/lme150_rlx1/models/` 快照（selfc 时代真实摄入产物）；oracle 字段由人工按记录原文标注；聚合 = `answer_enum.py`（grep → dup_link 合并 → kind 过滤 → 窗口 → count/sum + 证据 rid）。判定表逐题人工写。

## 结果：5/5 靶题全救回，2/2 留出题无连带伤

| qid | gold | flat(ruleB150) | typed | 机制 |
|---|---|---|---|---|
| 0a995998 | 3 | 2 | **3** | obligation_status 枚举出 blazer/boots/sweater 三个待办 |
| 88432d0a | 4 | 5 | **4** | 窗口边界排除 14 天边事件 + kind 过滤 3 条 planned |
| d682f1a2 | 3 | 2 | **3** | object_class 去重计数，Domino's 归入 delivery |
| gpt4_7fce9456 | 4 | 5 | **4** | referent 排除目标 townhouse + offer 蕴含 viewing |
| 7024f17c | 0.5h | 拒答 | **0.5h** | duration 字段求和；拒答→带证据应答 |
| b5ef892d (held) | 8 | 8✓ | **8** | Utah 露营 kind=negated 被排除——四态 schema 的直接兑现 |
| gpt4_f2262a51 (held) | 3 | 3✓ | **3** | visit+doctor 去重；2 条 planned 预约被排除 |

## 结论：段1 未被证伪——表征层不是枚举残尾的瓶颈

确定性聚合在完美字段下全部达标 → **残尾病灶在"没有 typed 字段"而非"字段不够用"**。dup 合并、四态 kind、referent 排除、窗口过滤四件机制各司其职，每件都实际拦下了 flat 版本犯过的错。

## 三条诚实警告（决定 stage-2 的真实成本）

1. **3/5 题靠口径约定救回**：0a995998（gold 把"姐妹归还毛衣"算进 store-return）、88432d0a（14 天边界恰在窗口线上）、7024f17c（"last week"宽松口径）。typed 记录把这些变成确定性可计算+带证据，但"gold 口径"本身是我标注时对齐的——真实系统里口径要由作答策略给出，可能再次失配。
2. **判定表是我手写的**：每题的 select/window/aggregate 规范由人工产出。真实系统需要从问题自动生成查询规范（类 text-to-SQL 的 codegen 环节）——这是段2 之外的隐藏成本，设计稿未计价。
3. **段1 不度量抽取保真**：字段准确率/漏项率/重复事件率完全是段2 的事——真实抽取器能否产出这些字段才是立项的烧钱问题。

## 下一步（需 jing fu 批准，要烧 LLM）

- **stage-2 立项**：给抽取器加 typed 字段产出条款，verify150 重摄入（~150×摄入成本）→ 字段准确率/漏项率/dup 率实测 → 同判定表复跑此 7 题
- **可选 stage-1.5**（廉价）：LLM codegen 从问题生成聚合规范，测"规范生成"环节本身准不准——先于重摄入，能再砍一次不确定度

零成本声明：本次运行未调用任何 LLM/实验室会话，全部在已合并数据上做确定性计算。
