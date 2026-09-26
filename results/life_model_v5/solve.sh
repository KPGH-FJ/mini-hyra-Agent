#!/bin/bash
cd "$(dirname "$0")"

# solve.sh -- life_model asset (M5 control semantics)
# DELTA vs base s0080 (lifemodel v3 @ 148.935):
#   1. derived facts are now served as LIVE state: a state/stale/derive probe on
#      a slot whose current value comes from a live `derived` record returns the
#      derived value (previously 未知) -- fixes derive_alive (got 未知, want 东区).
#   2. forget(day_gte/day_lte) range erasure: window write-edges are marked gone
#      and the live value is recomputed from surviving edges, so the value rolls
#      back to its previous live value instead of a tombstone -- fixes
#      range_rollback (got 未知, want 深圳).
#   3. state()/import_state() round-trips the FULL asset (every record with
#      day+arrival ordering, the gone-set, the control-op journal, the purpose
#      registry and the alias map) and rebuilds from records on import instead of
#      a lossy materialized projection -- fixes import_state continuity.
#   4. purpose-conditioned serving (this round's direction): purpose/budget
#      probes pack ONLY probe["purpose_slots"]/probe["slots"] live values in the
#      probe's own order (never whole-asset dumps); a revoked purpose answers
#      已撤回 for purpose / budget / revoked probes.
#   5. control-op journal (forget / forget_range / correct / revoke_purpose)
#      backs ops probes with the targeted slot/purpose, or 无 when never run.
# WHY it scores better: the three lost clauses are recovered and the
# purpose/budget/revoked leakage is plugged, while the already-strong
# state/stale/prov behaviour (0.974/0.963/1.0) is preserved unchanged.

# --- defensive fallback: a valid solution.json always exists ---
cat > solution.json <<'JSON'
{"status":"fallback","contract":["ingest","answer","forget","correct","revoke_purpose","state","import_state","probe_bytes","stats"],"note":"smoke pending"}
JSON

python3 - <<'PY' || exit 0
import json, importlib.util, sys, traceback

try:
    spec = importlib.util.spec_from_file_location("asset", "asset.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
except Exception:
    traceback.print_exc()
    sys.exit(1)

results = []
def check(name, got, want):
    ok = str(got) == str(want)
    results.append({"name": name, "got": str(got), "want": str(want), "ok": ok})

# ---------------- M1 store / temporal ----------------
m.ingest({"id":"r1","day":1,"source":"self","kind":"statement","slot":"city","value":"深圳"})
m.ingest({"id":"r2","day":5,"source":"self","kind":"update","slot":"city","value":"广州"})
m.ingest({"id":"r0","day":2,"source":"self","kind":"statement","slot":"city","value":"珠海"})  # out of order
check("state_latest", m.answer({"type":"state","slot":"city","ckpt":10}), "广州")
check("as_of",       m.answer({"type":"as_of","slot":"city","day":3,"ckpt":10}), "珠海")
check("stale",       m.answer({"type":"stale","slot":"city","ckpt":10}), "广州")
check("prov",        m.answer({"type":"prov","slot":"city","value":"广州","ckpt":10}), "本人")
check("prov_bad",    m.answer({"type":"prov","slot":"city","value":"深圳","ckpt":10}), "非本人")
check("prov2",       m.answer({"type":"prov2","slot":"city","ckpt":10}), "r2")
check("unans",       m.answer({"type":"unans","slot":"phone","ckpt":10}), "未知")
m.ingest({"id":"t1","day":4,"source":"self","kind":"statement","slot":"town","value":"A"})
m.ingest({"id":"t2","day":4,"source":"self","kind":"update","slot":"town","value":"B"})
check("sameday_tie", m.answer({"type":"state","slot":"town","ckpt":10}), "B")   # later arrival wins

# ---------------- alias + attributed hearsay ----------------
m.ingest({"id":"a1","day":2,"source":"system","kind":"alias","slot":"alias","value":"同事小李","text":"小李"})
m.ingest({"id":"h1","day":3,"source":"小李","kind":"hearsay","slot":"city","value":"上海"})
m.ingest({"id":"h2","day":6,"source":"同事小李","kind":"hearsay","slot":"city","value":"北京"})
check("subject_alias", m.answer({"type":"subject","person":"小李","slot":"city","ckpt":10}), "北京")
check("subject_canon", m.answer({"type":"subject","person":"同事小李","slot":"city","ckpt":10}), "北京")
check("hearsay_not_state", m.answer({"type":"state","slot":"city","ckpt":10}), "广州")

# ---------------- M3 premises + user correction ----------------
m.ingest({"id":"d1","day":4,"source":"inference","kind":"derived","slot":"zone","value":"东区","supports":["r2"]})
check("derive_alive",  m.answer({"type":"derive","slot":"zone","ckpt":10}), "东区")
check("derive_state",  m.answer({"type":"state","slot":"zone","ckpt":10}), "东区")
m.correct("city","杭州")
check("correct_state", m.answer({"type":"state","slot":"city","ckpt":20}), "杭州")
check("derive_dead",   m.answer({"type":"derive","slot":"zone","ckpt":20}), "未知")
check("correct_prov",  m.answer({"type":"prov","slot":"city","value":"杭州","ckpt":20}), "本人")

# ---------------- expiry ----------------
m.ingest({"id":"x1","day":7,"source":"self","kind":"statement","slot":"diet","value":"轻食","expires_day":9})
check("exp_live", m.answer({"type":"state","slot":"diet","ckpt":9}),  "轻食")
check("exp_gone", m.answer({"type":"state","slot":"diet","ckpt":10}), "未知")

# ---------------- erasure / cascade ----------------
m.ingest({"id":"r4","day":8,"source":"self","kind":"statement","slot":"hobby","value":"摄影"})
m.ingest({"id":"d2","day":9,"source":"inference","kind":"derived","slot":"mood","value":"好","supports":["r4"]})
check("pre_forget_state",  m.answer({"type":"state","slot":"hobby","ckpt":15}), "摄影")
check("pre_forget_derived",m.answer({"type":"state","slot":"mood","ckpt":15}), "好")
m.forget({"slot":"hobby"})
check("cascade_state",   m.answer({"type":"cascade","slot":"hobby","ckpt":15}), "未知")
check("cascade_derived", m.answer({"type":"state","slot":"mood","ckpt":15}), "未知")
check("cascade_history", m.answer({"type":"as_of","slot":"hobby","day":8,"ckpt":15}), "未知")

# ---------------- in-stream retraction ----------------
m.ingest({"id":"r5","day":9,"source":"self","kind":"statement","slot":"car","value":"比亚迪"})
m.ingest({"id":"r6","day":10,"source":"self","kind":"retraction","slot":"car"})
check("retract",       m.answer({"type":"retract","slot":"car","ckpt":15}), "已删除")
check("retract_state", m.answer({"type":"state","slot":"car","ckpt":15}), "未知")

# ---------------- range-scoped erasure with rollback ----------------
m.ingest({"id":"j1","day":11,"source":"self","kind":"statement","slot":"job","value":"工程师"})
m.ingest({"id":"j2","day":14,"source":"self","kind":"update","slot":"job","value":"教师"})
check("pre_range", m.answer({"type":"state","slot":"job","ckpt":20}), "教师")
m.forget({"day_gte":12,"day_lte":16})
check("range_rollback", m.answer({"type":"state","slot":"job","ckpt":20}), "工程师")

# ---------------- M4 purpose views / budget / revoke ----------------
m.ingest({"id":"p1","day":17,"source":"self","kind":"statement","slot":"addr","value":"南山区"})
check("purpose", m.answer({"type":"purpose","purpose":"work","purpose_slots":["city","addr"],"ckpt":20}), "杭州,南山区")
check("budget",  m.answer({"type":"budget","slots":["addr","city"],"budget":6,"ckpt":20}), "南山区,杭州")
m.revoke_purpose("work")
check("revoked",            m.answer({"type":"revoked","purpose":"work","purpose_slots":["city"],"ckpt":20}), "已撤回")
check("purpose_after_revoke", m.answer({"type":"purpose","purpose":"work","purpose_slots":["city"],"ckpt":20}), "已撤回")

# ---------------- audit journal ----------------
check("ops_forget",       m.answer({"type":"ops","op":"forget"}), "hobby")
check("ops_forget_range", m.answer({"type":"ops","op":"forget_range"}), "job")
check("ops_correct",      m.answer({"type":"ops","op":"correct"}), "city")
check("ops_revoke",       m.answer({"type":"ops","op":"revoke_purpose"}), "work")
check("ops_none",         m.answer({"type":"ops","op":"undo"}), "无")

# ---------------- export / import continuity ----------------
snap = json.loads(json.dumps(m.state()))
m.import_state(snap)
check("import_state",   m.answer({"type":"state","slot":"job","ckpt":20}), "工程师")
check("import_city",    m.answer({"type":"state","slot":"city","ckpt":20}), "杭州")
check("import_history", m.answer({"type":"as_of","slot":"city","day":3,"ckpt":20}), "珠海")
check("import_subject", m.answer({"type":"subject","person":"小李","slot":"city","ckpt":20}), "北京")
check("import_gone",    m.answer({"type":"state","slot":"hobby","ckpt":15}), "未知")
check("import_journal", m.answer({"type":"ops","op":"correct"}), "city")
check("import_revoked", m.answer({"type":"revoked","purpose":"work","purpose_slots":["city"],"ckpt":20}), "已撤回")

# ---------------- multi-entity ----------------
m.ingest({"id":"e1","day":1,"source":"self","kind":"statement","slot":"city","value":"北京","about":"妈妈"})
m.ingest({"id":"e2","day":2,"source":"小李","kind":"hearsay","slot":"city","value":"上海","about":"妈妈"})
m.ingest({"id":"e3","day":3,"source":"self","kind":"update","slot":"city","value":"天津","about":"妈妈"})
check("about_state",   m.answer({"type":"state","about":"妈妈","slot":"city","ckpt":5}), "天津")
check("about_conf",    m.answer({"type":"conf","about":"妈妈","slot":"city","ckpt":5}), "高")
check("about_nchange", m.answer({"type":"nchange","about":"妈妈","slot":"city","ckpt":5}), "1")
check("about_subject", m.answer({"type":"subject","about":"妈妈","person":"小李","slot":"city","ckpt":5}), "上海")
m.forget({"about":"妈妈"})
check("about_forget",  m.answer({"type":"state","about":"妈妈","slot":"city","ckpt":5}), "未知")

passed = sum(1 for r in results if r["ok"])
failed = [r["name"] for r in results if not r["ok"]]
info = {
    "status": "ok" if not failed else "partial",
    "contract": [n for n in ("ingest","answer","forget","correct","revoke_purpose",
                             "state","import_state","probe_bytes","stats") if hasattr(m, n)],
    "smoke": {"passed": passed, "failed": len(failed), "failures": failed},
    "cost": {"asset_bytes": len(json.dumps(m.state(), ensure_ascii=False)),
             "probe_bytes": m.probe_bytes(), "llm_tokens": 0},
    "checks": results,
}
with open("solution.json", "w") as f:
    json.dump(info, f, ensure_ascii=False, indent=1)
print("smoke: %d/%d" % (passed, len(results)))
PY
exit 0
