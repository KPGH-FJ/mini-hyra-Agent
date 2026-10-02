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

Evidence bundles: `evidence/` (15 files; question, gold, our response, all records, rendered profile, channel/nv). Lesion table: `lesions.json`.

---

# Addendum — Deterministic aggregation arm (answers-only)

Two-stage arm: LLM extracts a candidate-item table (`{item,date,evidence}` rows) → program dedups/sorts/counts → LLM answers itemized+total (`agg_answer.py`). Tested on all 15 residuals, then ms-25 full slice.

## Results

**Residual-15: rescued 5/15** — d682f1a2 (3 services incl. Domino's), gpt4_7fce9456 (4 properties excluding target), dd2973ad (2AM temporal join), 8aef76bc + 38146c39 (judge-variance flips, not mechanism). On the 8 enumeration lesions specifically: **3/8 rescued**. Still fails where the lesion is in stage-1 extraction itself: 0a995998 (still emitted 2 candidates — sweater never made the table), 88432d0a (window interpretation unchanged), 7024f17c (boundary unchanged), gpt4_2f8be40d (deduped correctly then over-refused: "only 1 wedding confirmed"), 982b5123 (temporal arithmetic — table doesn't compose offsets). On non-enumeration questions the table format is harmful: 0edc2aef produced 0 candidates → hard refusal; advisory questions get no purchase from an item table.

**ms-25 full slice: .64 (16/25) vs profile baseline .72 — net −2, REFUTED.**

Flips +2/−4. Rescued: dd2973ad, gpt4_7fce9456. Broke: 6d550036 (project count), c4a1ceb8 (citrus types), gpt4_15e38248 (furniture), gpt4_d84a3211 (money total) — **all four were "how many" questions profile already answered correctly**. Even narrow enumeration-gating doesn't save it: the regressions ARE enumeration questions.

## Diagnosis

The lesion was never "LLM can't count" — it is "LLM can't enumerate exhaustively over a 100-250-record list". Deterministic counting formalizes stage-1's misses instead of fixing them; the bottleneck is upstream extraction recall, which has the same haystack instability as plain answering plus new failure modes (over-literal matching, non-item questions forced into item tables). An answer-side aggregation layer cannot fix an upstream recall problem — the enumerable structure would have to be marked at ingest time (typed enumerable fields/events) rather than reconstructed at answer time.

**Verdict: do not land.** Fix for enumeration goes ingest-side (event-typed records) or accept ~5-question residual as the honest floor of this stack.

Artifacts: `agg_answer.py`, `answers_agg{,_ms25}.jsonl`, `metrics_agg{,_ms25}.json`, `ms_ev/` (ms-25 evidence inputs).

---

# Addendum 2 — Ingest-side enumerable marking (scoped prototype)

Per-session ENUM pass produces a structured countable-fact copy at ingest time (`enum_ingest.py`, ENUM_SYS → `{item,category,verb,date,detail}` rows, session-bounded ~10-20 turns → small clean tables of 6-31 rows/question). Answer side greps the marked rows → deterministic dedup/count → itemized+total answer (`enum_answer.py` reusing `dedup_count`/`ANSWER_SYS`).

Test set: 8 enumeration lesions + 4 controls that the answer-side agg arm broke (6d550036, c4a1ceb8, gpt4_15e38248, gpt4_d84a3211).

## Results

**2/8 rescued, 1/4 controls broken — fails the preset bar (≥3/8 rescue AND zero collateral). ARCHIVED.**

| | base | enum |
|---|---|---|
| Rescued | — | 982b5123 (5 months ✓), gpt4_7fce9456 (4 properties ✓) |
| Still wrong | — | 0a995998 (still 2 vs 3 — sweater/return boundary), 88432d0a (window edge), 7024f17c (date-window semantics), d682f1a2 (Domino's category), gpt4_2f8be40d (co-ref kept separate rows), dd2973ad (honest no-record for 5-17) |
| Controls held | — | 6d550036, c4a1ceb8, gpt4_15e38248 |
| **Control broken** | — | gpt4_d84a3211 (money total — enum table lost an expense row) |

## Diagnosis (why ingest-side also fails)

- **Recall is still lossy even at session granularity** — the ENUM pass itself drops items (0a995998's third return item, gpt4_d84a3211's expense row); moving extraction earlier doesn't fix the fundamental enumeration-recall problem, it just changes where the miss happens.
- **Co-reference survives as separate rows** — roommate/Emily city wedding both extracted verbatim per session; item-normalization can't merge cross-session referents.
- **Fixed item schema can't express aggregate semantics** — money totals need amounts (not item rows), category boundaries ("does Domino's count as a delivery service") need judgment a grep can't supply, date-window semantics ("last week") stay interpretive.
- Union across both arms: agg∪enum rescues 4 distinct lesions {d682f1a2, gpt4_7fce9456, dd2973ad, 982b5123} but each arm breaks different currently-correct answers — no single aggregation path is a net win.

## Verdict — ARCHIVED as inherent ceiling

**枚举计数是这栈在长记忆上的固有上限（~5 题残尾 ≈ 3.3pp of 150q）**: enumeration recall fails at every level we inject structure — flat answer (5 wrong), answer-side table (net −8pp), ingest-side marked table (net −1 incl. collateral). The residual lesion is not one mechanism's bug; it's the fundamental cost of asking LLM-side pipelines to be exhaustive over long personal histories. Recommend: accept as floor, OR if enumeration must improve, the lever is a *typed* ingest schema (records stored as events with verb/object/amount fields from the start — a representation change, not a bolt-on pass).

Artifacts: `enum_ingest.py`, `enum_answer.py`, `enum_rows/` (12 sidecar tables), `answers_enum.jsonl`, `metrics_enum.json`, `enum_ev/`, `enum_qids.txt`.

---

# Addendum 3 — Meta-judgment + temporal-composition arm (prompt layer)

One `META_SYS` system prompt (`consol_answer.py`): (a) meta-judgment clause — weigh evidence before refusing; grounded extrapolation beats abstention when signals imply a direction; (b) temporal-composition clause — resolve relative dates to absolute, then compose intervals arithmetically (N months in advance of event M months ago = N+M).

Test: 5 lesions (refusals 0edc2aef/35a27287/51a45a95 + temporal 982b5123/dd2973ad) + 5 currently-correct controls (pref×2, temporal, ss-user, ms).

## Results — 2/5 rescued, 0/5 collateral. Below the ≥3/5 land bar but provably safe.

| lesion | out | note |
|---|---|---|
| 35a27287 | **RESCUED** | inferred language-exchange cultural events from Spanish/French interest — meta clause worked |
| 982b5123 | **RESCUED** | composed 3-months-in-advance + 2-months-ago trip = 5 months — temporal clause worked |
| 0edc2aef | no | correctly reports only Seattle trip on file; no Miami signal to extrapolate — honest |
| 51a45a95 | no | still won't chain Cartwheel→Target; honest underdetermination, not over-caution |
| dd2973ad | no | computed 5-17 correctly; gold wants 5-24 2AM — underdetermined gold intent, not clause-fixable |

Controls 5/5 held (505af2f5, afdc33df, gpt4_2655b836, e47becba, 6d550036 — incl. hedged-but-correct "2 projects clearly" on 6d550036).

**Assessment:** the two clauses each rescue exactly their design target and break nothing — landable as a zero-cost prompt refinement if desired (net +2 on residual), but the residual 3 refusal failures are honest underdetermination (gold assumes an inference the evidence doesn't force), which no reader-side clause can fix without hallucination risk. Recommendation: land the clauses opportunistically (they're free and each earned its keep), accept the 3 as floor noise.

Artifacts: `consol_answer.py`, `answers_consol.jsonl`, `metrics_consol.json`, `consol_ev/`.

---

# M2 — Typed-event record representation (design draft, no code)

## Motivation

Three consecutive refutations all root in flat-text records: answer-side aggregation (net −8pp), ingest-side enum marking (2/8 + collateral), haystack/profile-section variants. Enumeration, temporal composition, and cross-session co-reference all fail because the record substrate is unstructured prose — every downstream consumer re-derives structure from text, lossily and inconsistently.

## Schema

```python
# Typed record (stored on TemporalGraph vertex/edge payload)
{
  "verb": "bought|viewed|attended|made|used|spent|lent|returned|plans|owns|...",
  "object": "canonical item name",        # entity-id or normalized string
  "quantity": 30, "unit": "minutes|USD|count|...",
  "actor": "user|assistant|<named entity>",
  "when_abs": "2023-05-20",               # resolved at ingest via session date
  "when_rel": "last Wednesday",           # verbatim, kept for audit
  "modifiers": {"location": ..., "with": ..., "source": ...},
  "provenance": "session_id:turn_idx",    # citable
  "text": "the original sentence <=25w"   # human-readable fallback
}
```

## Where it lives

- `TemporalGraph.hist[slot] → [typed_record, ts, kind, about, rid]` — same edge structure, richer payload (backwards compatible: `text` field renders like today's value for non-typed consumers).
- Ingest emits typed records directly (extractor already produces structured JSON — the schema just becomes first-class); VERIFY_SYS audit unchanged.
- Profile render consumes typed records (grouping by verb/entity is free).

## What it buys deterministically

- **Enumeration**: `SELECT object WHERE verb IN (bought,viewed,...) AND when_abs IN window` — counting is a grep, not a recall task. Fixes the ~5-question enumeration floor honestly.
- **Temporal composition**: all anchors absolute at write time; intervals are arithmetic on fields.
- **Co-reference**: `object` normalized to entity ids at ingest (aliases table exists — `asset.aliases`); same entity → same id, no cross-session dup frames.
- **Retrieval**: typed edges index by verb/object/entity — pick=50 becomes field-filtered, not semantic guessing.

## Migration path for 150q

1. Re-ingest 150 models with typed extractor (drop-in: same LLM, stricter schema) — verify+yield_guard stay.
2. Backfill option: sidecar typed tables (the `enum_rows/` prototype is a weak version — a *typed* pass with verb/quantity fields), no model rewrite.
3. Answer side: enumeration → deterministic ops on typed edges; everything else → existing channels reading `text` fallback.

## Risks / open questions

- Schema-fill reliability moves the recall problem one level down (missing `object` normalization = same co-ref bug); mitigation: verbatim `text` + provenance always kept, typed fields additive.
- Verb taxonomy coverage — open-ended lives need an extensible verb set + `other` escape, or the schema itself becomes the loss.
- Cost: typed extraction is a slightly bigger ingest prompt; verify pass already exists to audit coverage.
- Non-enumerative questions get near-zero benefit — the payoff is concentrated in the ~3-5pp residual + making profile render/retrieval structurally cheaper.
