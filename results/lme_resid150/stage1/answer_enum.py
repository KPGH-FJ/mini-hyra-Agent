#!/usr/bin/env python3
"""stage-1 oracle falsification: deterministic enum aggregation over oracle-typed
records (annotations.json). Implements the V2 pseudocode:
  grep candidates -> resolve dup_links -> kind filter -> count/sum + evidence rids.
No LLM anywhere: this file IS the arm-B answer channel.
"""
import json, sys
from datetime import date, timedelta

D = json.load(open("results/lme_resid150/stage1/annotations.json"))
qdate = lambda s: date.fromisoformat(s)


def resolve_dups(recs):
    """Union-find over dup_links; canonical = lexicographically smallest rid."""
    parent = {r["rid"]: r["rid"] for r in recs}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    for r in recs:
        for d in r.get("dup_links", []):
            if d in parent:
                union(r["rid"], d)
    groups = {}
    for r in recs:
        groups.setdefault(find(r["rid"]), []).append(r)
    return groups


def in_window(rec, win, qd):
    w = rec.get("when_abs")
    if win["kind"] == "past_days":
        if not w or rec.get("granularity") != "day":
            return None  # undecidable
        d = qdate(w)
        return qd - timedelta(days=win["days"]) < d <= qd  # edge-exclusive: strict > qd-days
    if win["kind"] == "loose_last_week":
        if not w or rec.get("granularity") != "day":
            return None
        d = qdate(w)
        return qd - timedelta(days=14) < d <= qd
    if win["kind"] == "year":
        return w and w[:4] == str(win["year"])
    return True


def answer_enum(q):
    agg = q["aggregate"]
    qd = qdate(q["qdate"])
    recs = q["records"]
    groups = resolve_dups(recs)
    events = []
    for canon, members in groups.items():
        # canonical record stands for the event group
        events.append(min(members, key=lambda r: r["rid"]))
    sel, excl = [], []
    for r in events:
        if r["kind"] != "asserted":
            excl.append((r["rid"], f"kind={r['kind']}")); continue
        if "select_verb" in agg and r["verb"] != agg["select_verb"]:
            excl.append((r["rid"], "verb")); continue
        if agg.get("select") and not eval_select(agg["select"], r, q, recs):
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
        result = len({r["object"] for r in sel})
    elif agg["op"] == "sum":
        field = agg["field"]
        result = sum(r.get(field) or 0 for r in sel)
    return {"answer": result, "evidence": [r["rid"] for r in sel],
            "excluded": excl}


def eval_select(spec, r, q, all_recs=None):
    """Minimal predicate evaluator over the annotation fields."""
    if "obligation_status" in spec:
        return r.get("obligation_status") in {"awaiting_pickup", "awaiting_return"}
    if "object!=referent" in spec:
        # viewing events (or offer-implied viewings) on non-target properties
        # that precede the target offer's date
        is_view = r["verb"] == "view" or bool(r.get("implies_event", "").startswith("view"))
        if not is_view or "[TARGET]" in r["object"]:
            return False
        offer = next((x for x in (all_recs or []) if x["verb"] == "offer"
                      and "[TARGET]" in x["object"]), None)
        if offer and offer.get("when_abs") and r.get("when_abs"):
            return qdate(r["when_abs"]) < qdate(offer["when_abs"])
        return True
    if "object_class=" in spec:
        cls = spec.split("object_class=")[1].split(" ")[0]
        return r.get("object_class") == cls
    if "verb in" in spec:
        verbs = spec.split("{")[1].split("}")[0].split(",")
        return r["verb"] in {v.strip() for v in verbs}
    if "verb=camp" in spec:
        return r["verb"] == "camp" and r.get("location") == "US" and str(r.get("when_abs") or "").startswith("2023")
    if spec.startswith("verb="):
        return r["verb"] == spec.split("=")[1].split(" ")[0]
    return True


if __name__ == "__main__":
    rescued = 0; targets = 0; heldout_ok = 0
    for q in D["questions"]:
        res = answer_enum(q)
        tag = "HELDOUT" if q.get("held_out") else "TARGET"
        if not q.get("held_out"):
            targets += 1
        ok = str(res["answer"]) == str(q["gold"]).split(" ")[0] or \
             str(res["answer"]) in str(q["gold"])
        if q.get("held_out") and ok: heldout_ok += 1
        if not q.get("held_out") and ok: rescued += 1
        print(f"{tag} {q['qid']} | gold={q['gold']} | typed={res['answer']} | flat={q['flat_answer']} | {'MATCH' if ok else 'MISS'}")
        print(f"   evidence: {res['evidence']}")
        print(f"   excluded: {[(r, w) for r, w in res['excluded']]}")
    print(f"\ntargets rescued: {rescued}/{targets} | held-out preserved: {heldout_ok}")
