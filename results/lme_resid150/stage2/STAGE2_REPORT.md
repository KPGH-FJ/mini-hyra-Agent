# M2 typed-record · stage-2 抽取保真实测

日期：2026-10-06 ｜ 抽取模型：Atria-Dawn-Preview（max_tokens 8192→16384 自动升格）
设计稿：`results/lme_resid150/TYPED_RECORD_DESIGN_V2.md` ｜ stage-1：`stage1/STAGE1_REPORT.md`

## 做了什么

stage-1 证明了「完美字段→确定性聚合」全救回（5/5）。stage-2 回答：真实抽取器
产出的字段离完美有多远。做法——

1. `typed_pass.py`：对 7 道钉子户枚举题的同一份快照（`results/lme150_rlx1/models/`）
   跑真实 LLM 打标 pass：每条记录产 event_id / kind / verb / object /
   object_class / quantity / quantifier / when_abs / granularity /
   duration_value / duration_unit / obligation_status / counterparty /
   location / dup_links。**原文永远保留，typed 字段只是投影**。
   两个 pass：逐块字段标注（20 条/块 ×4 并发）+ 全模型查重 pass
   （查重必须看到全部记录，切块会漏跨会话重复）。
2. `fidelity_eval.py`：在标注共有的 37 条记录上逐字段对比手写 gold；
   再用确定性聚合在**全量快照的真实字段**上跑候选捞取+去重+谓词
   过滤+计数，对比 gold/flat。

## 结果

### 字段保真（真实 vs 手写 gold，37 条）

| 字段 | 一致率 | 性质 |
|---|---|---|
| kind | 34/37 = 92% | asserted/negated/planned/cancelled 基本可靠 |
| when_abs | 34/37 = 92% | v2 修订后：部分日期 `YYYY-MM` 保留（首版 84%） |
| granularity | 31/37 = 84% | v2 后 |
| obligation_status | 4/4 = 100% | 义务状态识别好 |
| verb | 21/37 = 57% | **同义漂移**：bake→try、use→eat/find、visit→attend/diagnose、camp→camping_trip/attend |
| object | 22/37 = 59% | **粒度漂移**：'Zara boots'→'boots'、'3-bed townhouse, Brookside'→'3-bedroom townhouse' |
| dup_links | recall 4/5 · precision 4/10 | 查得出来但**过标**：把「同病情不同表述」（同一条鼻窦炎的多次提及）当同事件——边界约定待校准（dup=同实例，不是同主题） |
| counterparty | 1/4 = 25% | 多置 null（保守不造） |
| object_class | 3/9 = 33% | 类目词表与谓词约定不同 |
| location | 0/3 | 存具体地名，谓词要国家粒度——约定差非错误 |

### 救回（确定性聚合 × 真实字段 × 全快照候选）

| 题 | gold | 真实字段聚合 | flat 作答 | 判定 |
|---|---|---|---|---|
| 0a995998 取衣/退货计数 | 3 | 2 | 2 | MISS（blazer 记被判 kind=planned 排除） |
| 88432d0a 近两周烘焙次数 | 4 | 3 | 5 | MISS（verb=try 非 bake） |
| d682f1a2 外卖平台数 | 3 | 0 | 2 | MISS（verb≠use、object_class 不匹配） |
| gpt4_7fce9456 看房计数 | 4 | **4** | 5 | **MATCH（真救回）** |
| 7024f17c 上周运动时长 | 0.5h | **0.5** | 拒答 | **MATCH（真救回，flat 曾拒答）** |
| b5ef892d*（留出） | 8 天 | 0 | 8（本来对） | MISS（verb=camping_trip/attend≠camp、location=具体地名≠US——字段有信息，谓词字典对不上） |
| gpt4_f2262a51*（留出） | 3 | 0 | 3（本来对） | MISS（verb=attend/diagnose≠visit、object_class=medical_condition≠doctor） |

**真实字段救回 2/5**（oracle 5/5）。首版（无 duration、部分日期置 null）
只救 1/5，v2 修订（部分日期保留 + duration_value/unit）后 7024f17c 也
救回——证明那道是纯 schema 缺口。剩下 3 道全死在词表约定：字段本身
是对的（露营题连「3天/5天、2023-04、Big Sur」都对了），谓词换一套
字典就全杀。

## 结论（诚实口径）

- **抽取器能产字段**：kind/日期/义务态/dup 召回都在可用水位——结构化的
  原材料是真的能产出的，不是空想。
- **真正的断点在「词表对齐」不在「抽取能力」**：聚合谓词写的是 `verb=bake`
  `object_class=food_delivery_service` `location=US`，抽取器产出的是
  `try`/`eat`/`attend`、具体地名、另一套类目标签——两边都对，但字典对不上。
  确定性聚合死在这里。
- **schema 缺口也被实测挖出**：首版没 duration 字段，sum 题天然 0；
  部分日期全置 null 是我 prompt 的口径 bug——v2 已修。
- **留出侧警告**：真实字段若机械聚合会让两道本来对的留出题回退成 0
  （谓词全灭 → 空集），说明「字段全有但约定不通」比「没有字段」更危险——
  必须有兜底（聚合结果空/置信低时回落 flat 作答）。

## 下一步（可立项的方案）

1. **谓词生成的词表感知**：聚合 spec 生成前先读快照里 typed 字段的
   实际词表（distinct verb/object_class/location），让 `verb in {...}` 用
   抽取器的词写——确定性闭环，不碰抽取侧。成本≈一次小调用。
2. **canonical 谓词本**：摄入侧约束 verb/object_class 取自有界词表
   （像 slot catalog 的 merge 一样建 verb catalog）——更根治但要动 M1。
3. **兜底条款**：聚合命中数=0 或全部谓词排除时回落 flat 通道，
   不得输出 0——防止留出题回退。

## 成本

7 题 ≈ 35 次 Atria 调用（字段块×题数 + 查重×题数），单次 20 记录块
80-150s；dup pass 全量单次最长 ~10min（125-140 条记录）。
v2 重跑 2 题 ≈ 10 调用。总计数十次调用级，预算可忽略。
