# 150q 全栈复测：selfc 摄入 × {无gate, gate-all} × 老栈（里程碑三方对比）

数据卷：data_strat150.json 同卷 150 题（6 类 × 25）。切片 = data_ms150_25.json（ms-25）+ data_150sc_{0-3}.json（125 非 ms，32/31/31/31 四路）。
摄入：LME_SELFCONTAIN=1（自足 bullet；#65 合后已是 main 默认，本实验用实验分支覆盖跑）
Reader：mainstack shadow（origin/main @6fad5ba 时代的 `_pv_gate` + SPEAKER BINDING；assist 全程关）
后端：Atria 全链（answerer=judge），与老栈线同判官。
三臂共用同一批 selfc 模型缓存（摄入零差异，只有作答路径不同）。

## 三方对比总表（Atria 判）

| 题型 | 老栈(84.7线) | 新栈·旧摄入 | **selfc+无gate** | **selfc+gate-all(pvg)** | gate 净损益 |
|---|---|---|---|---|---|
| temporal | .92 | .92 | **.88** | .28 | **−60pp** |
| knowledge-update | .96 | .92 | **1.00** | .96 | −4pp |
| single-session-preference | .84 | .84 | **.84** | .12 | **−72pp** |
| single-session-assistant | .68 | .80 | **.76** | .60 | −16pp |
| single-session-user | .96 | .92 | **.92** | .92 | 0 |
| multi-session | .72 | .28 | **.60** | .04 | **−56pp** |
| **总计 (150)** | **.847** | .780 | **.833 (125/150)** | **.487 (73/150)** | **−34.6pp** |

（"新栈·旧摄入" = reexam150_new/metrics_base.json，上轮 78% 那线，作答同样无 gate）

## 头条判词

1. **selfc 新栈 ≈ 老栈，未拉下马但已追平**：83.3% vs 84.7%（−1.4pp，噪声带内）。缺口只剩 multi-session（60 vs 72，−12pp）；非 ms 类 selfc 反超老栈隐含值（88.0 vs 87.2），ku 到 100%。selfc 修复把 ms 从 28 拉回 60 属实，但 ms 残尾仍是唯一实质差距。
2. **gate-all（premise_check=True）在本卷是 −34.6pp 净损**：125 非 ms 题 57.6%、ms-25 仅 4%。错误形态一律为拒答 "Memory has no record of X, so it does not answer"：
   - temporal："两事件相隔几天" —— 两个日期记录都在 digest，gate 找不到合成记录就拒答（不做组件推理）。f0853d11：Walk for Hunger + Coastal Cleanup 日期齐在，拒算 14 天。
   - preference/advisory："推荐点什么" —— 题面本身无字面事实前提可绑 → 12% 团灭。
   - ss-user（直接事实题）无损、ku −4：gate 只在"前提有字面记录"的题型上中性。
   - **上轮 78% 那线不带 gate** —— gate-all 是本轮首次全切片测量，此前 LoCoMo cat5 +4.5pp 的结论不可外推（那边几乎全是事实前提型题）。
3. 关联结论：assist=True（60→68，+8pp 见 lme_assist25/REPORT.md）与 gate 是两个独立增益件——assist 是聚合装配，gate 是前提否决；gate 的误伤面覆盖 assist 的收益面。

## 修复选型输入（给 A/B 决策的数据）

- gate 的损益高度题型相关：事实前提型 {ss-user: 0, ku: −4} vs 推理/建议型 {temporal: −60, pref: −72, assist-q: −16, ms: −56}。
- **A. 题型路由** 若做，路由判据 ≈ "题面是否含可字面前提"。本卷按 LME 类型切已见零损/无损区，但 ss-assist/ms 内含事实前提子题（gate 对它们的损益未单独测）。
- **B. 校验语义放宽**（"组件齐全可合成"判可答 + advisory 标 no-premise-expected）覆盖面更全，但需要 verifier 能区分"前提不存在"vs"前提可推理"——本批拒答输出里它已经能列出组件清单（f0853d11 列出了两条日期记录仍拒答），说明信息在它手里，缺的只是判定规则。
- 建议：先做 B 的廉价版——verifier 输出 schema 加 `answerable_by_inference`，跑这同 125 题看拒绝率是否归零且不误放进真无前提题（本卷 ku 里若有真·无前提题可验）。

## 产物

- 摄入模型：`results/lme150_sc{0-3}/models`（125 新摄入 + 复用 25 selfc）、`results/lme150_ms25/models`（ms-25）
- 假设：`results/lme150_sc{0-3}/hyp_pvg.jsonl`（gate-all 125）、`results/lme150_ung{0-3}/hyp_base.jsonl`（无gate 125）、`results/lme150_ms25/hyp_pvg.jsonl`、`results/lme150_hyp_{pvg,base}_125.jsonl`（合并卷）
- 判分：`results/metrics_150sc_{pvg,base}_125.json`、`metrics_150sc_pvg_ms25.json`；对照 `reexam150_{old,new}/metrics_base.json`、`metrics_selfc.json`（ms-25 无gate = 60%）
- 判分命令：`OPENAI_*=Atria python3 lme.py judge --hyp <f> --ref longmemeval_oracle.json`
