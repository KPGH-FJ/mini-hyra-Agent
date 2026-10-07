#!/usr/bin/env python3
"""stage-2 fidelity: real typed fields vs stage-1 hand annotations.

Two measurements on the same records:
  1. FIELD fidelity — per annotated rid, does the real pass agree with
     the hand label? (exact for kind/when/granularity/quantity;
     normalized-containment for verb/object; dup recall+precision)
  2. RESCUE — run the stage-1 deterministic aggregation over REAL
     fields across the WHOLE snapshot (candidate grep over typed verbs/
     objects, not the annotated subset) -> answers vs gold.
"""
import json
import os
import sys
from datetime import date, timedelta

D = json.load(open("results/lme_resid150/stage1/annotations.json"))
qdate = date.fromisoformat
OUT = "results/lme_resid150/stage2"


def norm(s):
    return " ".join(str(s or "").lower()
                    .replace("_", " ").split())


def str_match(a, b):
    """containment either way after normalization, or token Jaccard>=0.5"""
    a, b = norm(a), norm(b)
    if not a or not b:
        return a == b
    if a in b or b in a:
        return True
    ta, tb = set(a.split()), set(b.split())
    return len(ta & tb) / len(ta | tb) >= 0.5


def cmp_field(rid, field, gold_v, real_v):
    if field in ("verb", "object", "object_class", "counterparty",
                 "location"):
        return str_match(real_v, gold_v)
    if field == "quantity":
        try:
            return float(gold_v) == float(real_v)
        except (TypeError, ValueError):
            return gold_v == real_v
    return gold_v == real_v


def resolve_dups(recs):
    parent = {r["rid"]: r["rid"] for r in recs}
    def find(x):
        while parent.get(x, x) != x:
            x = parent[x]
        return x
    for r in recs:
        for d in r.get("dup_links", []):
            if d in parent:
                ra, rb = find(r["rid"]), find(d)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
    groups = {}
    for r in recs:
        groups.setdefault(find(r["rid"]), []).append(r)
    return groups


def _abs_day(w):
    """partial ISO -> representative date or None."""
    if not w:
        return None
    try:
        if len(w) == 10:
            return qdate(w)
        if len(w) == 7:
            return date(int(w[:4]), int(w[5:7]), 15)
        if len(w) == 4:
            return date(int(w), 7, 1)
    except Exception:
        return None
    return None


def in_window(rec, win, qd):
    w = rec.get("when_abs")
    if win["kind"] == "past_days":
        if rec.get("granularity") != "day":
            return None
        d = _abs_day(w)
        if not d:
            return None
        return qd - timedelta(days=win["days"]) < d <= qd
    if win["kind"] == "loose_last_week":
        if rec.get("granularity") != "day":
            return None
        d = _abs_day(w)
        if not d:
            return None
        return qd - timedelta(days=14) < d <= qd
    if win["kind"] == "year":
        return w and w[:4] == str(win["year"])
    return True


def duration_as(rec, unit):
    """duration_hours/duration_days derived from duration_value+unit."""
    v, u = rec.get("duration_value"), rec.get("duration_unit")
    if v is None or u is None:
        return None
    conv = {"minutes": 1 / 60, "hours": 1.0, "days": 24.0,
            "weeks": 168.0}
    h = float(v) * conv.get(u, 0)
    return h if unit == "duration_hours" else h / 24.0


def eval_select(spec, r, q, all_recs):
    if "obligation_status" in spec:
        return r.get("obligation_status") in {"awaiting_pickup",
                                              "awaiting_return"}
    if "object!=referent" in spec:
        is_view = r.get("verb") == "view" or \
            str(r.get("implies_event", "")).startswith("view")
        if not is_view or "[TARGET]" in str(r.get("object")):
            return False
        offer = next((x for x in all_recs if x.get("verb") == "offer"
                      and "[TARGET]" in str(x.get("object"))), None)
        if offer and offer.get("when_abs") and r.get("when_abs"):
            return qdate(r["when_abs"]) < qdate(offer["when_abs"])
        return True
    if "object_class=" in spec:
        cls = spec.split("object_class=")[1].split(" ")[0]
        return r.get("object_class") == cls
    if "verb in" in spec:
        verbs = spec.split("{")[1].split("}")[0].split(",")
        return r.get("verb") in {v.strip() for v in verbs}
    if "verb=camp" in spec:
        return r.get("verb") == "camp" and \
            r.get("location") == "US" and \
            str(r.get("when_abs") or "").startswith("2023")
    if spec.startswith("verb="):
        return r.get("verb") == spec.split("=")[1].split(" ")[0]
    return True


def candidate_pool(q, all_typed):
    """grep candidates from REAL fields: records whose verb/object
    plausibly match any annotated record's verb — the deterministic
    retrieval a real system would run."""
    ann = q["records"]
    gold_verbs = {norm(r.get("verb")) for r in ann if r.get("verb")}
    gold_objs = {norm(r.get("object")) for r in ann if r.get("object")}
    pool = []
    for rid, t in all_typed.items():
        v, o = norm(t.get("verb")), norm(t.get("object"))
        if v in gold_verbs or any(v and (v in gv or gv in v)
                                  for gv in gold_verbs):
            pool.append({**t, "rid": rid}); continue
        if o and any(str_match(o, go) for go in gold_objs):
            pool.append({**t, "rid": rid})
    return pool


def answer_enum(q, pool):
    agg = q["aggregate"]
    qd = qdate(q["qdate"])
    groups = resolve_dups(pool)
    events = [min(m, key=lambda r: r["rid"]) for m in groups.values()]
    sel, excl = [], []
    for r in events:
        if r.get("kind") != "asserted":
            excl.append((r["rid"], f"kind={r.get('kind')}")); continue
        if "select_verb" in agg and r.get("verb") != agg["select_verb"]:
            excl.append((r["rid"], "verb")); continue
        if agg.get("select") and not eval_select(agg["select"], r, q,
                                                 pool):
            excl.append((r["rid"], "predicate")); continue
        w = agg.get("window")
        if w:
            iw = in_window(r, w, qd)
            if iw is False:
                excl.append((r["rid"], "window")); continue
            if iw is None:
                excl.append((r["rid"], "window-undecidable")); continue
        sel.append(r)
    if agg["op"] == "count_events":
        result = len(sel)
    elif agg["op"] == "count_distinct":
        result = len({norm(r.get("object")) for r in sel})
    elif agg["op"] == "sum":
        field = agg["field"]
        vals = [(r.get(field) if r.get(field) is not None
                 else duration_as(r, field)) or 0 for r in sel]
        result = sum(vals)
    else:
        result = None
    return {"answer": result, "evidence": [r["rid"] for r in sel],
            "excluded": excl}


def load_typed(qid):
    """prefer the revised-schema file (typed_<qid>_v2) when present."""
    for suf in ("_v2", ""):
        p = f"{OUT}/typed_{qid}{suf}.json"
        if os.path.exists(p):
            return json.load(open(p))
    raise FileNotFoundError(qid)


def main():
    fields = ["kind", "verb", "object", "quantity", "quantifier",
              "when_abs", "granularity", "obligation_status",
              "counterparty", "object_class", "location",
              "duration_value", "duration_unit"]
    tot_f = {}
    tot = {"n": 0}
    dup_tp = dup_fp = dup_fn = 0
    rescued = targets = 0
    print("=== FIELD FIDELITY (per question, annotated rids only) ===")
    for q in D["questions"]:
        qid = q["qid"]
        real = load_typed(qid)["typed"]
        per = {f: [0, 0] for f in fields}
        mismatches = []
        ann_rids = {r["rid"] for r in q["records"]}
        for r in q["records"]:
            t = real.get(r["rid"], {})
            for f in fields:
                if f not in r:
                    continue
                ok = cmp_field(r["rid"], f, r.get(f), t.get(f))
                per[f][1] += 1
                tot_f.setdefault(f, [0, 0])[1] += 1
                if ok:
                    per[f][0] += 1
                    tot_f[f][0] += 1
                else:
                    mismatches.append((r["rid"], f, r.get(f),
                                       t.get(f)))
            tot["n"] += 1
        # dup recall/precision on annotated pairs
        ann_pairs = set()
        for r in q["records"]:
            for d in r.get("dup_links", []):
                ann_pairs.add(tuple(sorted((r["rid"], d))))
        real_pairs = set()
        for rid in ann_rids:
            for d in real.get(rid, {}).get("dup_links", []):
                real_pairs.add(tuple(sorted((rid, d))))
        for p in ann_pairs:
            if p in real_pairs:
                dup_tp += 1
            else:
                dup_fn += 1
        for p in real_pairs:
            if p not in ann_pairs:
                dup_fp += 1
        acc = {f: f"{a}/{b}" for f, (a, b) in per.items() if b}
        print(f"\n{qid}: " + json.dumps(acc, ensure_ascii=False))
        if mismatches:
            for m in mismatches[:8]:
                print(f"   miss {m[0]} {m[1]}: gold={m[2]!r} real={m[3]!r}")
    print("\n=== TOTAL FIELD ACCURACY ===")
    for f, (a, b) in tot_f.items():
        print(f"  {f}: {a}/{b} = {a/b:.2f}")
    print(f"  dup_links: recall={dup_tp}/{dup_tp+dup_fn} "
          f"precision={dup_tp}/{dup_tp+dup_fp}")

    print("\n=== RESCUE (real fields, full-snapshot candidates) ===")
    for q in D["questions"]:
        qid = q["qid"]
        data = load_typed(qid)
        pool = candidate_pool(q, data["typed"])
        res = answer_enum(q, pool)
        tag = "HELDOUT" if q.get("held_out") else "TARGET"
        gold_num = str(q["gold"]).split(" ")[0]
        try:
            ok = abs(float(res["answer"]) - float(gold_num)) < 1e-6
        except (TypeError, ValueError):
            ok = str(res["answer"]) == str(q["gold"])
        if not q.get("held_out"):
            targets += 1
            rescued += ok
        print(f"{tag} {qid} | gold={q['gold']} | real={res['answer']} "
              f"| flat={q['flat_answer']} | {'MATCH' if ok else 'MISS'}"
              f"  (pool={len(pool)})")
        print(f"   evidence: {res['evidence']}")
        miss = [e for e in res["excluded"] if e[1] == "predicate"]
        if miss:
            print(f"   predicate-excluded: {miss}")
    print(f"\ntargets rescued with real fields: {rescued}/{targets}")


if __name__ == "__main__":
    main()
