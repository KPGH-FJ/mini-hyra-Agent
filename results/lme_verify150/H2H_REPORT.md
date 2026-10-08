# 基线对擂：lifemodel ruleB vs 朴素 RAG（同题同判官）

2026-10-08 · LME-150 分层全集 · Atria 答题+判题双端一致

## 总成绩

| 系统 | 得分 | 判官pass1 | pass2 复判 diff 集后 |
|---|---|---|---|
| lifemodel (verify摄入 × ruleB路由) | 134/150 | 89.3% | ~87-89% |
| naive-RAG (BM25 top-20 逐句) | 124/150 | 82.7% | ~82% |
| **净差** | **+10 题** | **+6.6pp** | ≈ +5~7pp |

pass2：24 道分歧题两臂各复判一次——5 翻（2 道 ss-user 判官噪声归我们、3 道 ss-pref 翻走）→ ours_only 14 / rag_only 6，净差收窄到 +8 题。

## 分题型（pass1）

| 题型 | lifemodel | RAG | 差 |
|---|---|---|---|
| single-session-preference | 88% | 52% | **+36pp** |
| multi-session | 68% | 60% | +8pp |
| knowledge-update | 96% | 92% | +4pp |
| temporal-reasoning | 96% | 96% | 0 |
| single-session-assistant | 100% | 100% | 0 |
| **single-session-user** | **88%** | **96%** | **−8pp** |

## 逐题 diff 归因（24 道分歧题）

**我们独有对（ours_only, pass1=17 / pass2=14）**：几乎全是**枚举/聚合/画像综合题**——
RAG 漏条目（慈善活动 2→4、主导项目 1→2、单车开销 $40→$185、柑橘 2→3、博物馆 1→2、
游戏时长总和 140h）。正是 typed-record/画像通道要解决的病灶类。

**RAG 独有对（rag_only, pass1=7 / pass2=6）**：
- 画像覆盖洞 ~4：小传概括把精确事实抹掉了——"先看的剧是Crown还是GoT"（开播日期
  没进画像）、"医生预约前一晚几点睡"（ bedtime 没进画像）、婚礼数 3→2、
  "最近一次家庭旅行" 选了 Hawaii 错丢 Paris（近因排序也错）
- 判官噪声 ~2（同义答案两判翻转，pass2 已归还我们）

## 结论

1. **89.3% 里 ~83% 是"题面可检索"的底子**——朴素 BM25+通用提示已够到。记忆工程的
   独有贡献 ≈ +6pp，集中在聚合枚举与偏好综合（画像通道的价值实证）
2. **画像通道有召回代价**：为综合而压缩的画像丢掉精确事实，ss-user 上 RAG 反超。
   修法方向：画像兜底不了时回落原文检索（混合下探），或画像保真审计
3. 对擂价值：我们的成绩放到"同题同判官同答题模型"口径下仍为正——**+6pp 是
   记忆系统的真实增量**，不是检索红利

## 产物

- `answers_naive_rag_k20.jsonl`（150 答+判分）
- `diff_rejudge.json`（24 分歧题两臂 pass2 判词）
- `naive_rag150.py`（BM25+通用答题+同 JUDGE 驱动，断点续跑）
