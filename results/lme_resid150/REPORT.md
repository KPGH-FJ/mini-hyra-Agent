# Residual Anatomy — verify150 批次全部判负题逐题归因

Scope: all 15 judged-wrong questions from the verify150 batch — routeB non-ms misses (8) + ms-25 forced-profile misses (7). Each attributed to one of five lesion layers: 摄入缺 / 检索欠 / 画像概括 / 作答推理 / 判官严判, with one-line evidence.

## Headline

| 病灶层 | 计数 | 占比 |
|---|---|---|
| 作答推理 | 10 | 67% |
| 判官严判 | 4 | 27% |
| 摄入缺（实体去重） | 1 | 7% |
| **画像概括** | **0** | **0%** |
| **检索欠** | **0** | **0%** |

**画像概括丢细节 = 0 题** — haystack is NOT the residual driver. M2 architecture re-prioritization is not warranted by this evidence. The next module is **answer-side enumeration/aggregation**.

## Cluster 1 — 作答推理 (10/15): two sub-lesions

### 1a. 枚举/计数边界 (5) — the dominant honest lesion

| qid | 题型/通道 | gold | ours | 证据 |
|---|---|---|---|---|
| 0a995998 | ms/profile | 3 items | 2 | 记录全齐（blazer 干洗 + Zara 靴退换 + 绿毛衣借出）；第三项界定模糊（毛衣非 store 归还 vs 靴子计两次）——聚合边界错 |
| 88432d0a | ms/profile | 4 bakes | 5 | 5 项全在记录（5-16 酸种/5-18 饼干/5-20 蛋糕/5-20 法棍/5-23 酸种）；窗口边界 + 失败烘培计不计的双重边界 |
| d682f1a2 | ms/profile | 3 services | 2 | Domino's 记录逐字在图（"had Domino's Pizza three times"），作答把它排除出 delivery service 类别 |
| gpt4_7fce9456 | ms/profile | 4 properties | 5 | 把目标 townhouse 本身计入 viewed-before-offer；gold 语义排除被购物业——边界读法不同但 ours 站不住（gold 枚举 4 套非购买） |
| 7024f17c | ms/profile | 0.5h | 拒绝 | 唯一完成训练 = 5-20 慢跑 30min；作答用严格"上周"窗排除它，gold 的"last week"口径宽松含该次——日期窗判定过紧 |

### 1b. 过度保守拒答 (3) — advisory 条款仍欠收

| qid | 题型/通道 | 证据 |
|---|---|---|
| 0edc2aef | pref/profile | 画像有明确偏好信号（城市景观+rooftop pool+hot tub balcony），仍拒绝给 Miami 酒店建议、只重述筛选标准 |
| 35a27287 | pref/profile | 画像有西/法语学习+语言交换兴趣记录，拒绝推荐文化活动、只问城市 |
| 51a45a95 | ss-user/assist | Cartwheel=Target 专属 app 记录 + "常去 Target" 记录 → 兑换地点可推断 Target；作答停在"未记录地点"诚实拒答 |

### 1c. 时序合成 (2)

| qid | 题型/通道 | gold | ours | 证据 |
|---|---|---|---|---|
| 982b5123 | temporal/assist | 5 months | 3 | 记录含 "booked 3 months in advance" + "trip exactly two months ago" → 应合成 2+3=5；作答把相对事件的提前量直接当月前读数 |
| dd2973ad | ms/profile | 2 AM | 拒答 | 会话原文 "bed until 2 AM last Wednesday"（=5-24 深夜）+ "appointment last Thursday"（Fri 5-26 会话，锚定歧义 5-25 vs 5-18）；作答把预约锚到 5-18 后拒答，gold 按同周四关联——锚定错+拒答 |

## Cluster 2 — 判官严判 (4/15) — 噪声地板，非病灶

| qid | 证据 |
|---|---|
| 3b6f954b | 答 "University of Melbourne" vs gold "University of Melbourne in Australia" — 实体完全对，缺国别尾缀 |
| 8aef76bc | 答 "Mod Podge" vs gold "Mod Podge or another sealant" — 逐字命中金标主词 |
| 38146c39 | 答用 turbinado 换 sugar + 烘焙适配 = gold 字面要求（"recommendations that complement turbinado"） |
| 09d032c9 | 答充电宝随身带 + 6 款充电宝选型 = gold（"build upon power bank mention, optimize its use"） |

## Cluster 3 — 摄入缺·实体去重 (1/15)

| qid | 证据 |
|---|---|
| gpt4_2f8be40d | 同一场城市婚礼被摄入成 3 条不同框架的记录（"cousin Emily's city wedding"+"college roommate's wedding in the city"+"Emily and Sarah's wedding"，均 rooftop garden）→ 聚合时按独立事件数 4；gold=3。实体共指消解缺口在摄入层，不是检索/画像问题 |

## 下一主攻模块裁决输入

1. **枚举聚合是最大诚实病灶**（5 题 + dd2973ad/0a995998 的计数边界成分）：画像臂和 assist 臂同病——LLM 在 ~50-200 条记录/画像上做 set-aggregation 不稳。建议方向：answer-side deterministic aggregation（把枚举题的路由到"结构化记录表→代码计数"而不是 LLM 清单），或检索臂 digest 输出结构化行（date,item）交给计数。
2. **拒答保守度**（3 题）：advisory 条款对"有信号但无字面命中"仍救不回——条款只管 advice 措辞，不管"是否有足够证据"的元判定。可试在 PROFILE_ANSWER_SYS 加"infer-from-strong-signals"档（介于 extrapolate-fully 和 refuse 之间），或干脆把 gold-inference 型题判作不可达噪声。
3. **实体共指**（1 题）：摄入层同事件多框架记录——verify 已挡 attrition 但不挡 duplication；量级太小不立项。
4. **判官严判 4 题 = ~2.7pp 评分噪声地板**：其中 3 题实质答案正确——换判官/改判词可再变现，但属测量误差不属栈能力。
5. **画像概括/haystack 病灶 = 0**：M2 架构题（分域画像/二级索引）在本残尾里**无对应损失**，维持驳回。

## Reproduce

Evidence bundles: `/tmp/resid_ev/*.json` (15 files; question, gold, our response, all records, rendered profile, channel/nv). Classification script + lesion table: `lesions.json` in this dir.
