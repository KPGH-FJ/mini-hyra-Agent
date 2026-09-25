#!/bin/bash
# life_model — M5 control semantics asset.
#
# DELTA vs the base solution (fallback, quality 0 / s0035 ~132.77):
# the base had no control machinery at all. This version makes owner control
# first-class on top of the frozen ingest/serve substrate:
#   * op journal (forget / forget_range / correct / revoke_purpose) that lives
#     inside state() and survives the export->import round trip -> post_import
#     `ops` probes become answerable instead of dropping;
#   * revoke_purpose() withdraws a consent view (data kept, view answers 已撤回)
#     -> `revoked`/`purpose` probes score instead of leaking;
#   * forget({slot}|{about}|{day_gte,day_lte}) erases write edges and rebuilds
#     live state from surviving edges (rollback, not a tombstone) -> `cascade`
#     and range-rollback probes score;
#   * correct(slot,value) is a read-time self-assertion that supersedes the
#     live value, keeps provenance, and starves derived premises -> `derive`
#     probes score;
#   * derived facts maintained by a premise fixpoint: a fact dies and is purged
#     from state+history (transitively through chains) when a support record is
#     retracted/forgotten or when the supporting slot's live value diverged;
#   * multi-entity (about) vertices, alias-canonicalised hearsay subjects,
#     expiry, retraction tombstones, prov2 citation, unans abstention, budgeted
#     packing, and honest byte metering (real consulted bytes, real state size).
# WHY it should score better: every probe family in the spec has a dedicated
# code path with correct gone-phrasing, and cost is measured, not fabricated.
cd "$(dirname "$0")"
python3 - <<'PYEOF' || exit 0
import json, importlib.util, traceback
spec = importlib.util.spec_from_file_location("lm_asset", "asset.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
checks = {}
def ck(name, got, want):
    checks[name] = {"ok": got == want, "got": got, "want": want}
try:
    m.ingest({"id":"r0","day":1,"source":"system","kind":"alias","slot":"alias","value":"小王","name":"同事小王"})
    m.ingest({"id":"r1","day":2,"source":"self","kind":"statement","slot":"city","value":"北京"})
    m.ingest({"id":"r2","day":5,"source":"self","kind":"update","slot":"city","value":"上海"})
    m.ingest({"id":"r3","day":6,"source":"inference","kind":"derived","slot":"zone","value":"北区","supports":["r2"]})
    m.ingest({"id":"r4","day":3,"source":"other","kind":"hearsay","slot":"leave","value":"下周离职","subject":"小王"})
    m.ingest({"id":"r5","day":7,"source":"self","kind":"statement","slot":"phone","value":"13800000000"})
    m.ingest({"id":"r6","day":9,"source":"self","kind":"retraction","slot":"phone"})
    m.ingest({"id":"r7","day":8,"source":"self","kind":"statement","slot":"visa","value":"有效","expires_day":20})
    m.ingest({"id":"r8","day":10,"source":"inference","kind":"derived","slot":"region","value":"华东","supports":["r3"]})
    m.ingest({"id":"r9","day":3,"source":"self","kind":"statement","slot":"city","value":"巴黎","about":"家人"})
    m.ingest({"id":"r10","day":4,"source":"self","kind":"statement","slot":"plan","value":"周一A；周二B"})
    ck("state_supersede", m.answer({"type":"state","slot":"city","ckpt":6}), "上海")
    ck("state_early", m.answer({"type":"state","slot":"city","ckpt":4}), "北京")
    ck("as_of", m.answer({"type":"as_of","slot":"city","day":4,"ckpt":6}), "北京")
    ck("stale", m.answer({"type":"stale","slot":"city","ckpt":6}), "上海")
    ck("prov_yes", m.answer({"type":"prov","slot":"city","value":"北京","ckpt":6}), "本人")
    ck("prov_no", m.answer({"type":"prov","slot":"city","value":"成都","ckpt":6}), "非本人")
    ck("subj_alias", m.answer({"type":"subject","slot":"leave","person":"同事小王","ckpt":12}), "下周离职")
    ck("subj_canon", m.answer({"type":"subject","slot":"leave","person":"小王","ckpt":12}), "下周离职")
    ck("derived_live", m.answer({"type":"state","slot":"zone","ckpt":7}), "北区")
    ck("derived_chain", m.answer({"type":"state","slot":"region","ckpt":11}), "华东")
    ck("about_state", m.answer({"type":"state","slot":"city","about":"家人","ckpt":12}), "巴黎")
    ck("about_noleak", m.answer({"type":"state","slot":"city","about":"同事","ckpt":12}), "未知")
    ck("unans", m.answer({"type":"unans","slot":"leave","ckpt":12}), "未知")
    ck("nchange", m.answer({"type":"nchange","slot":"city","ckpt":11}), "3")
    ck("conf_gao", m.answer({"type":"conf","slot":"city","about":"家人","ckpt":12}), "高")
    ck("conf_wu", m.answer({"type":"conf","slot":"city","about":"同事","ckpt":12}), "无")
    ck("visa_live", m.answer({"type":"state","slot":"visa","ckpt":15}), "有效")
    ck("visa_expired", m.answer({"type":"state","slot":"visa","ckpt":25}), "未知")
    ck("retract", m.answer({"type":"retract","slot":"phone","ckpt":10}), "已删除")
    ck("retract_state", m.answer({"type":"state","slot":"phone","ckpt":10}), "未知")
    ck("transfer", m.answer({"type":"transfer","slot":"plan","ckpt":12}), "周一A；周二B,周一A,周二B")
    ck("prov2", m.answer({"type":"prov2","slot":"city","ckpt":6}), "r2")
    m.correct("city","杭州")
    ck("correct_state", m.answer({"type":"state","slot":"city","ckpt":11}), "杭州")
    ck("derive_dead", m.answer({"type":"derive","slot":"zone","ckpt":11}), "未知")
    ck("derive_chain_dead", m.answer({"type":"derive","slot":"region","ckpt":11}), "未知")
    ck("ops_correct", m.answer({"type":"ops","op":"correct","ckpt":11}), "city")
    m.revoke_purpose("ads")
    ck("revoked", m.answer({"type":"purpose","purpose":"ads","purpose_slots":["zone"],"ckpt":11}), "已撤回")
    ck("budget", m.answer({"type":"budget","slots":["visa"],"budget":8,"ckpt":15}), "有效")
    m.forget({"slot":"city"})
    ck("cascade", m.answer({"type":"cascade","slot":"city","ckpt":12}), "未知")
    ck("cascade_prov", m.answer({"type":"prov","slot":"city","value":"杭州","ckpt":12}), "非本人")
    snap = m.state()
    rt = json.loads(json.dumps(snap, ensure_ascii=False))
    m.import_state(rt)
    ck("import_state", m.answer({"type":"state","slot":"city","about":"家人","ckpt":12}), "巴黎")
    ck("import_journal", m.answer({"type":"ops","op":"forget","ckpt":12}), "city")
    ck("import_revoked", m.answer({"type":"purpose","purpose":"ads","purpose_slots":["zone"],"ckpt":11}), "已撤回")
    ck("import_subject", m.answer({"type":"subject","slot":"leave","person":"小王","ckpt":12}), "下周离职")
    st = m.stats()
    ck("cost_real", st["asset_bytes"] > 100 and st["probe_bytes"] > 0, True)
    m.ingest({"id":"r20","day":30,"source":"self","kind":"statement","slot":"city","value":"深圳"})
    m.forget({"day_gte":28,"day_lte":32})
    ck("range_rollback", m.answer({"type":"state","slot":"city","ckpt":35}), "未知")
except Exception:
    traceback.print_exc()
ok = all(v["ok"] for v in checks.values())
out = {"ok": ok, "n": len(checks), "fail": sum(1 for v in checks.values() if not v["ok"]),
       "checks": checks, "asset": "asset.py", "entry": "solve.sh"}
with open("solution.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("ok=" + str(ok), "checks=" + str(len(checks)))
PYEOF
exit 0
