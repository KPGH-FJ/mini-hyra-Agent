"""M4 typed-record aggregation — deterministic enumeration over the
store's `typed` registry.

Enumeration over flat records is the measured failure mode of the
free-text representation (residual anatomy: the model cannot do
exhaustive recall; three mechanism-level fixes all died on it). With
typed fields the answer becomes grep+aggregate: a spec writer emits a
closed-DSL spec against the store's ACTUAL vocabulary, and this module
evaluates it deterministically — the model never touches enumeration.

Lab chain (results/lme_resid150): oracle fields 5/5 -> real extraction
2/7 -> canonical-frame prompt 4/7 -> deterministic fixes + spec-verify
loop 7/7. This file is the deterministic half; `lifemodel.reader`
drives the spec generation + verify loop.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta


def norm(s):
    return " ".join(str(s or "").lower().replace("_", " ").split())


def qdate(s):
    """question/reference date string -> date."""
    if isinstance(s, date):
        return s
    s = str(s)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            from datetime import datetime
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return date.today()


def _date_compat(a, b):
    """dup-merge requires the two records' stated dates to be
    compatible: shared-precision prefix must agree (year, then month,
    then day). A missing/coarser field is never a disagreement."""
    wa, wb = a.get("when_abs"), b.get("when_abs")
    if not wa or not wb:
        return True
    if "-W" in str(wa) or "-W" in str(wb):
        return True
    ga = "day" if len(str(wa)) == 10 else "month" if len(str(wa)) == 7 \
        else "year"
    gb = "day" if len(str(wb)) == 10 else "month" if len(str(wb)) == 7 \
        else "year"
    depth = min({"year": 1, "month": 2, "day": 3}[ga],
                {"year": 1, "month": 2, "day": 3}[gb])
    cut = {1: 4, 2: 7, 3: 10}[depth]
    return str(wa)[:cut] == str(wb)[:cut]


def resolve_dups(recs):
    """Union-find over dup_links with a temporal-compat check —
    same item on different days is two events (sourdough bug)."""
    by_rid = {r["rid"]: r for r in recs}
    parent = {r["rid"]: r["rid"] for r in recs}

    def find(x):
        while parent.get(x, x) != x:
            x = parent[x]
        return x
    for r in recs:
        for d in r.get("dup_links") or []:
            if d in parent and _date_compat(r, by_rid[d]):
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
    nm = win.get("null_mode", "strict")
    if w is None and nm != "strict":
        if nm == "tolerant":
            return True
        md = rec.get("_day")
        if md:
            d = date.fromordinal(int(md))  # store `day` is an ordinal
            if win["kind"] == "past_days":
                return qd - timedelta(days=win["days"]) < d <= qd
            if win["kind"] == "loose_last_week":
                return qd - timedelta(days=14) < d <= qd
            if win["kind"] == "year":
                return d.year == win["year"]
        return None
    if win["kind"] in ("past_days", "loose_last_week"):
        if rec.get("granularity") != "day":
            return None
        d = _abs_day(w)
        if not d:
            return None
        span = win["days"] if win["kind"] == "past_days" else 14
        return qd - timedelta(days=span) < d <= qd
    if win["kind"] == "year":
        return w and w[:4] == str(win["year"])
    return True


def duration_as(rec, unit):
    """duration_hours/duration_days from duration_value+unit."""
    v, u = rec.get("duration_value"), rec.get("duration_unit")
    if v is None or u is None:
        return None
    conv = {"minutes": 1 / 60, "hours": 1.0, "days": 24.0,
            "weeks": 168.0}
    h = float(v) * conv.get(u, 0)
    return h if unit == "duration_hours" else h / 24.0


def vocab_of(typed):
    """the store's actual typed vocabulary — the spec writer must pick
    predicates from THIS, never invent frames."""
    def counts(key):
        return Counter(str(t.get(key)) for t in typed.values()
                       if t.get(key))
    return {"verbs": dict(counts("verb").most_common(40)),
            "object_class": dict(counts("object_class").most_common(25)),
            "location": dict(counts("location").most_common(25)),
            "objects": dict(counts("object").most_common(30)),
            "obligation_status": dict(counts("obligation_status")),
            "counterparty": dict(counts("counterparty").most_common(25)),
            "kind": dict(counts("kind"))}


_SPEC_KEYS = {"op", "any_of", "verbs", "object_class", "objects_contain",
              "exclude_objects_contain", "obligation_status",
              "counterparties", "location", "kind", "window", "field",
              "explain", "_qdate"}


def _drop_nonselective(clause, typed):
    """a clause listing ~all vocabulary for a field is not selecting;
    strip unknown keys so stray fields can't silently narrow it."""
    for k in list(clause):
        if k not in _SPEC_KEYS:
            del clause[k]
    vocab = vocab_of(typed)
    for key, vkey in (("verbs", "verbs"), ("object_class", "object_class"),
                      ("location", "location"),
                      ("counterparties", "counterparty")):
        lst = _list(clause.get(key))
        tot = len(vocab.get(vkey, {}))
        if lst and tot and len(lst) >= max(tot * 0.8, tot - 2):
            clause[key] = None
    return clause


def norm_clause(spec, typed):
    for c in (spec.get("any_of") or [spec]):
        _drop_nonselective(c, typed)
    return spec


def _list(v):
    """spec writers sometimes emit a bare string where the DSL wants a
    list — coerce so None-valued record fields don't crash `in`."""
    if v is None:
        return None
    return v if isinstance(v, list) else [v]


def _clause_passes(clause, r, qd):
    if clause.get("kind"):
        if r.get("kind") not in _list(clause["kind"]):
            return False
    elif r.get("kind") != "asserted":
        return False
    if clause.get("verbs") and r.get("verb") not in _list(clause["verbs"]):
        return False
    if clause.get("object_class") and \
            r.get("object_class") not in _list(clause["object_class"]):
        return False
    if clause.get("objects_contain"):
        o = norm(r.get("object"))
        if not any(norm(s) in o
                   for s in _list(clause["objects_contain"])):
            return False
    if clause.get("exclude_objects_contain"):
        o = norm(r.get("object"))
        if any(norm(s) in o
               for s in _list(clause["exclude_objects_contain"])):
            return False
    if clause.get("obligation_status") and \
            r.get("obligation_status") not in \
            _list(clause["obligation_status"]):
        return False
    if clause.get("location") and \
            r.get("location") not in _list(clause["location"]):
        return False
    if clause.get("counterparties"):
        c = norm(r.get("counterparty"))
        if not c:
            return False
        if not any(norm(s) in c or c in norm(s)
                   for s in _list(clause["counterparties"])):
            return False
    w = clause.get("window")
    if w and in_window(r, w, qd) is not True:
        return False
    return True


def passes(spec, r, pool):
    qd = qdate(spec["_qdate"]) if spec.get("_qdate") else date.today()
    if spec.get("any_of"):
        return any(_clause_passes(c, r, qd) for c in spec["any_of"])
    return _clause_passes(spec, r, qd)


def answer_with_spec(spec, typed, recs=None):
    """deterministic spec eval. `typed` = rid->fields (store.typed);
    `recs` optional [{rid, day}] for mention_day window fallback."""
    spec = norm_clause(spec, typed)
    day_of = {r["rid"]: r.get("day") for r in recs or []}
    pool = [{**t, "rid": rid, "_day": t.get("_day", day_of.get(rid))}
            for rid, t in typed.items()]
    groups = resolve_dups(pool)
    events = [min(m, key=lambda r: r["rid"]) for m in groups.values()]
    sel = [r for r in events if passes(spec, r, pool)]
    op = spec.get("op")
    if op == "count_events":
        result = len(sel)
    elif op == "count_distinct":
        result = len({norm(r.get("object")) for r in sel})
    elif op == "sum":
        f = spec.get("field", "quantity")
        result = sum((r.get(f) if r.get(f) is not None
                      else duration_as(r, f)) or 0 for r in sel)
    else:
        result = None
    return {"answer": result, "evidence": [r["rid"] for r in sel],
            "pool": len(pool)}


def validate_spec(spec, typed):
    """clause enum-list values must exist in the store vocabulary —
    catch invented frames before they silently match nothing.
    Returns [{clause, key, value, nearest}] warnings."""
    vocab = vocab_of(typed)
    out = []
    for i, clause in enumerate(spec.get("any_of") or [spec]):
        for key, vkey in (("verbs", "verbs"),
                          ("object_class", "object_class"),
                          ("location", "location"),
                          ("counterparties", "counterparty")):
            for v in _list(clause.get(key)) or []:
                if v not in vocab.get(vkey, {}):
                    near = [w for w in vocab.get(vkey, {})
                            if norm(v) in norm(w) or norm(w) in norm(v)][:3]
                    out.append({"clause": i, "key": key, "value": v,
                                "nearest": near})
    return out
