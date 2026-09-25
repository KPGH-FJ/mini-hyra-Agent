"""LifeModel contract conformance suite — the pinned bench semantics as
executable spec. Any implementation conforming to the module contract
(lifemodel package, TMS/ESR reference baselines, evolved solutions)
must satisfy every clause; baseline divergences are reported honestly
(the bench scores them as quality loss).

Run:  python tests/test_lifemodel_contract.py [impl ...]
impls:  lm tms esr raw ledger flat rag  (default: all)

Each clause drives a minimal hand-built lifecycle through the same
method surface the evaluator uses: ingest / answer / forget / correct /
revoke_purpose / state / import_state.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tasks" / "life_model"))

_argv, sys.argv = sys.argv, [sys.argv[0]]  # evaluate.py reads argv[2] as seed
import evaluate as ev  # noqa: E402
sys.argv = _argv
from lifemodel.model import LifeModel  # noqa: E402

IMPLS = {
    "lm": lambda: LifeModel(),
    "tms": ev.TMSBaseline,
    "esr": ev.ESRBaseline,
    "raw": ev.RawBaseline,
    "ledger": ev.LedgerBaseline,
    "flat": ev.FlatServeBaseline,
    "rag": ev.RAGBaseline,
}


def R(day, source, kind, slot, value, **kw):
    r = {"day": day, "source": source, "kind": kind,
         "slot": slot, "value": value}
    r.update(kw)
    return r


def P(ptype, slot, expect=None, **kw):
    p = {"type": ptype, "slot": slot, "expect": expect}
    p.update(kw)
    return p


CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


# ---------- M2 store semantics ----------

@case("expiry: lapsed lease reads as unknown at read day")
def _(a):
    a.ingest(R(1, "self", "statement", "gym", "月卡", expires_day=30))
    a.ingest(R(2, "self", "statement", "city", "北京"))
    assert a.answer(P("state", "gym", ckpt=40)) == "未知"
    assert a.answer(P("state", "city", ckpt=40)) == "北京"


@case("out-of-order: day wins over arrival order")
def _(a):
    a.ingest(R(40, "self", "update", "city", "上海"))
    a.ingest(R(10, "self", "statement", "city", "北京"))
    assert a.answer(P("state", "city", ckpt=50)) == "上海"


@case("retraction kills the value")
def _(a):
    a.ingest(R(1, "self", "statement", "job", "上班"))
    a.ingest(R(20, "self", "retraction", "job", "上班"))
    assert a.answer(P("state", "job", ckpt=30)) == "未知"


@case("hearsay never sets self state")
def _(a):
    a.ingest(R(1, "self", "statement", "city", "北京"))
    a.ingest(R(5, "小李", "hearsay", "city", "广州"))
    assert a.answer(P("state", "city", ckpt=10)) == "北京"
    assert a.answer(P("subject", "city", person="小李", ckpt=10)) == "广州"


@case("alias: person forms merge for subject lookup")
def _(a):
    a.ingest(R(1, "self", "alias", "小丽", "小李"))
    a.ingest(R(2, "小丽", "hearsay", "diet", "低碳水"))
    assert a.answer(P("subject", "diet", person="小李", ckpt=10)) == "低碳水"


# ---------- M3 update semantics ----------

@case("derived: dangling supports = dead at birth")
def _(a):
    a.ingest(R(1, "inference", "derived", "fit", "适配",
             supports=["rid-missing"]))
    assert a.answer(P("state", "fit", ckpt=10)) == "未知"


@case("derived: premise diverged kills the derived (and chains)")
def _(a):
    a.ingest(R(1, "self", "statement", "creed", "每天记录", id="r1"))
    a.ingest(R(2, "inference", "derived", "habit", "可持续",
             supports=["r1"], id="r2"))
    a.ingest(R(3, "inference", "derived", "plan", "按习惯排程",
             supports=["r2"]))
    assert a.answer(P("state", "plan", ckpt=5)) == "按习惯排程"
    a.ingest(R(6, "self", "update", "creed", "偶尔记录"))
    assert a.answer(P("state", "habit", ckpt=10)) == "未知"
    assert a.answer(P("state", "plan", ckpt=10)) == "未知"


# ---------- M5 control semantics ----------

@case("forget(slot): slot + dependents erased, journal recorded")
def _(a):
    a.ingest(R(1, "self", "statement", "creed", "每天记录", id="r1"))
    a.ingest(R(2, "inference", "derived", "habit", "可持续",
             supports=["r1"]))
    a.ingest(R(3, "self", "statement", "city", "北京"))
    a.forget({"slot": "creed"})
    assert a.answer(P("state", "creed", ckpt=10)) == "未知"
    assert a.answer(P("state", "habit", ckpt=10)) == "未知"
    assert a.answer(P("state", "city", ckpt=10)) == "北京"
    ops = a.answer(P("ops", "_audit", op="forget"))
    assert "creed" in ops


@case("forget_range: erasing write edges rolls the slot back")
def _(a):
    a.ingest(R(10, "self", "statement", "city", "北京"))
    a.ingest(R(40, "self", "update", "city", "上海"))
    a.forget({"day_gte": 40, "day_lte": 41})
    assert a.answer(P("state", "city", ckpt=50)) == "北京"


@case("correct(): owner write wins and is journal-auditable")
def _(a):
    a.ingest(R(1, "self", "statement", "city", "北京"))
    a.correct("city", "天津")
    assert a.answer(P("state", "city", ckpt=10)) == "天津"
    ops = a.answer(P("ops", "_audit", op="correct"))
    assert "city" in ops


@case("revoke_purpose: view refuses, scoped export refuses")
def _(a):
    a.ingest(R(1, "self", "statement", "city", "北京"))
    a.revoke_purpose("health_plan")
    assert a.answer(P("revoked", "_v", purpose="health_plan",
                      purpose_slots=["city"], ckpt=10)) == "已撤回"
    assert a.state(scope={"slots": ["city"],
                          "purpose": "health_plan"}) == {}


# ---------- v8 multi-entity ----------

@case("entity: about vertexes isolated from self domain")
def _(a):
    a.ingest(R(1, "self", "statement", "diet", "素食"))
    a.ingest(R(2, "self", "statement", "diet", "清淡",
             about="妈妈"))
    assert a.answer(P("state", "diet", ckpt=10)) == "素食"
    assert a.answer(P("state", "diet", about="妈妈", ckpt=10)) == "清淡"


@case("entity: subject+about routes to claimer|entity vertex")
def _(a):
    a.ingest(R(1, "表姐", "hearsay", "diet", "低碳水", about="妈妈"))
    assert a.answer(P("subject", "diet", person="表姐",
                      about="妈妈", ckpt=10)) == "低碳水"


@case("entity: as_of+about reads entity history, not self")
def _(a):
    a.ingest(R(1, "self", "statement", "diet", "素食"))
    a.ingest(R(2, "self", "statement", "diet", "清淡", about="妈妈"))
    a.ingest(R(3, "self", "update", "diet", "无偏好", about="妈妈"))
    assert a.answer(P("as_of", "diet", about="妈妈", day=2,
                      ckpt=10)) == "清淡"
    # never leaks the self vertex's value for an entity read
    assert a.answer(P("as_of", "diet", about="爸爸", day=5,
                      ckpt=10)) == "未知"


@case("entity: conf grades self-claim about entity high")
def _(a):
    a.ingest(R(1, "self", "statement", "sleep", "规律", about="爸爸"))
    assert a.answer(P("conf", "sleep", about="爸爸", ckpt=10)) == "高"
    a.ingest(R(2, "表哥", "hearsay", "sleep", "熬夜", about="叔叔"))
    assert a.answer(P("conf", "sleep", person="表哥",
                      about="叔叔", ckpt=10)) == "低"


@case("entity: forget(about) erases her vertexes, self untouched")
def _(a):
    a.ingest(R(1, "self", "statement", "diet", "素食"))
    a.ingest(R(2, "self", "statement", "diet", "清淡", about="妈妈"))
    a.ingest(R(3, "表姐", "hearsay", "diet", "低碳水", about="妈妈"))
    a.forget({"about": "妈妈"})
    assert a.answer(P("state", "diet", about="妈妈", ckpt=10)) == "未知"
    assert a.answer(P("subject", "diet", person="表姐",
                      about="妈妈", ckpt=10)) == "未知"
    assert a.answer(P("state", "diet", ckpt=10)) == "素食"


@case("entity alias: name forms resolve at read (alias records)")
def _(a):
    a.ingest(R(1, "self", "statement", "diet", "清淡", about="妈妈"))
    a.ingest(R(2, "system", "alias", "我妈", "妈妈"))
    a.ingest(R(3, "表姐", "hearsay", "diet", "低碳水", about="我妈"))
    # either form asks: self claim wins, hearsay attributing by alias
    assert a.answer(P("state", "diet", about="妈妈", ckpt=10)) == "清淡"
    assert a.answer(P("state", "diet", about="我妈", ckpt=10)) == "清淡"
    assert a.answer(P("subject", "diet", person="表姐",
                      about="我妈", ckpt=10)) == "低碳水"
    assert a.answer(P("conf", "diet", about="我妈", ckpt=10)) == "高"


@case("erase is not brick: post-forget claims about entity live again")
def _(a):
    a.ingest(R(1, "self", "statement", "diet", "清淡", about="妈妈"))
    a.forget({"about": "妈妈"})
    assert a.answer(P("state", "diet", about="妈妈", ckpt=10)) == "未知"
    a.ingest(R(3, "self", "statement", "diet", "重口", about="妈妈"))
    assert a.answer(P("state", "diet", about="妈妈", ckpt=10)) == "重口"


@case("isconf: disagreeing claim flags 是, agreeing claims flag 否")
def _(a):
    a.ingest(R(1, "self", "statement", "city", "北京"))
    a.ingest(R(2, "表姐", "hearsay", "city", "上海"))
    a.ingest(R(3, "self", "statement", "diet", "素食"))
    a.ingest(R(4, "表姐", "hearsay", "diet", "素食"))
    assert a.answer(P("isconf", "city", ckpt=10)) == "是"
    assert a.answer(P("isconf", "diet", ckpt=10)) == "否"


@case("forget_range: erased write's lease must not kill survivors")
def _(a):
    a.ingest(R(1, "self", "statement", "family", "无照护负担"))
    a.ingest(R(2, "self", "statement", "family", "需照顾老人",
               expires_day=10))
    a.forget({"day_gte": 2, "day_lte": 2})
    # the erased write carried the lease — the survivor has none
    assert a.answer(P("state", "family", ckpt=20)) == "无照护负担"


# ---------- export / scoped export ----------

@case("export round-trip preserves behavior incl journal")
def _(a):
    a.ingest(R(1, "self", "statement", "city", "北京"))
    a.ingest(R(2, "self", "statement", "diet", "清淡", about="妈妈"))
    a.forget({"slot": "city"})
    doc = a.state()
    import json
    a.import_state(json.loads(json.dumps(doc, ensure_ascii=False)))
    assert a.answer(P("state", "diet", about="妈妈", ckpt=10)) == "清淡"
    ops = a.answer(P("ops", "_audit", op="forget"))
    assert "city" in ops


@case("scoped export: self-domain only (entity + aliases out)")
def _(a):
    a.ingest(R(1, "self", "statement", "city", "北京"))
    a.ingest(R(2, "self", "statement", "diet", "清淡", about="妈妈"))
    a.ingest(R(3, "self", "alias", "小丽", "小李"))
    a.correct("city", "天津")
    doc = a.state(scope={"slots": ["city"]})
    # out-of-scope material must not leak: no entity vertex data, no
    # alias map (it carries corrected values + person identities)
    assert "妈妈" not in str(doc) and "小丽" not in str(doc)


# ---------- v9 derived revival + history reasoning ----------

@case("derived revival: erasing the killer write revives the derived")
def _(a):
    a.ingest(R(1, "self", "statement", "creed", "每天记录", id="r1"))
    a.ingest(R(2, "inference", "derived", "habit", "可持续",
             supports=["r1"]))
    a.ingest(R(5, "self", "update", "creed", "偶尔记录"))
    assert a.answer(P("state", "habit", ckpt=6)) == "未知"
    a.forget({"day_gte": 5, "day_lte": 5})
    # the erasure rewrote the log — premise holds again, derived lives
    assert a.answer(P("state", "habit", ckpt=10)) == "可持续"
    assert a.answer(P("state", "creed", ckpt=10)) == "每天记录"


@case("derived revival: erasing the derived's own edge buries it")
def _(a):
    a.ingest(R(1, "self", "statement", "creed", "每天记录", id="r1"))
    a.ingest(R(2, "inference", "derived", "habit", "可持续",
             supports=["r1"], id="r2"))
    a.forget({"day_gte": 2, "day_lte": 2})
    assert a.answer(P("state", "habit", ckpt=10)) == "未知"


@case("derived revival: a surviving user write outranks a revived derived")
def _(a):
    a.ingest(R(1, "self", "statement", "creed", "每天记录", id="r1"))
    a.ingest(R(2, "inference", "derived", "habit", "可持续",
             supports=["r1"]))
    # explicit beats inferred — the correction lands on the same slot
    a.ingest(R(3, "self", "correction", "habit", "不稳定"))
    a.ingest(R(5, "self", "update", "creed", "偶尔记录"))
    a.forget({"day_gte": 5, "day_lte": 5})
    # the derived revives in the registry but the user's surviving
    # edge still wins the read
    assert a.answer(P("state", "habit", ckpt=10)) == "不稳定"


@case("first/order: run after last retraction, day order")
def _(a):
    a.ingest(R(1, "self", "statement", "city", "北京"))
    a.ingest(R(10, "self", "update", "city", "上海"))
    a.ingest(R(20, "self", "retraction", "city", "上海"))
    a.ingest(R(30, "self", "statement", "city", "广州"))
    a.ingest(R(35, "self", "update", "city", "深圳"))
    assert a.answer(P("first", "city", ckpt=40)) == "广州"
    assert a.answer(P("order", "city", ckpt=40)) == "广州→深圳"


@case("absent: stable iff no surviving write with day > 40")
def _(a):
    a.ingest(R(30, "self", "statement", "gym", "月卡"))
    a.ingest(R(50, "self", "statement", "city", "北京"))
    assert a.answer(P("absent", "gym", ckpt=60)) == "是"
    assert a.answer(P("absent", "city", ckpt=60)) == "否"


@case("window: transitions of live value inside [30,60]")
def _(a):
    a.ingest(R(10, "self", "statement", "city", "北京"))
    a.ingest(R(40, "self", "update", "city", "上海"))
    a.ingest(R(50, "self", "update", "city", "广州"))
    a.ingest(R(70, "self", "update", "city", "深圳"))
    assert a.answer(P("window", "city", ckpt=80)) == "2"


@case("join: slot2's live value at the probe's day")
def _(a):
    a.ingest(R(10, "self", "statement", "diet", "素食"))
    a.ingest(R(30, "self", "update", "diet", "清淡"))
    assert a.answer(P("join", "diet", day=20, ckpt=40)) == "素食"
    assert a.answer(P("join", "diet", day=35, ckpt=40)) == "清淡"


@case("xcmp: entity live value vs own, 未知 when no entity claim")
def _(a):
    a.ingest(R(1, "self", "statement", "diet", "素食"))
    a.ingest(R(2, "self", "statement", "diet", "素食", about="妈妈"))
    a.ingest(R(3, "self", "statement", "sleep", "规律"))
    a.ingest(R(4, "self", "statement", "sleep", "熬夜", about="妈妈"))
    assert a.answer(P("xcmp", "diet", about="妈妈", ckpt=10)) == "是"
    assert a.answer(P("xcmp", "sleep", about="妈妈", ckpt=10)) == "否"


def main():
    names = sys.argv[1:] or list(IMPLS)
    results = {}
    for name in names:
        for cname, fn in CASES:
            try:
                fn(IMPLS[name]())
                results.setdefault(name, []).append((cname, True, ""))
            except Exception as e:
                msg = f"{type(e).__name__}: {str(e)[:80]}"
                results.setdefault(name, []).append((cname, False, msg))
    w = max(len(c) for c, _ in CASES)
    print(f"{'clause':<{w}}  " + "  ".join(f"{n:>6}" for n in names))
    for i, (cname, _) in enumerate(CASES):
        row = []
        for n in names:
            ok = results[n][i][1]
            row.append("PASS" if ok else "fail")
        print(f"{cname:<{w}}  " + "  ".join(f"{r:>6}" for r in row))
    print()
    for n in names:
        fails = [(c, m) for c, ok, m in results[n] if not ok]
        npass = len(results[n]) - len(fails)
        print(f"{n}: {npass}/{len(results[n])} conformant")
        for c, m in fails:
            print(f"    - {c}\n        {m}")


if __name__ == "__main__":
    main()
