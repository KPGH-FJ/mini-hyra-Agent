"""LifeStream generator: a deterministic synthetic "life stream" for one
persona, plus the ground truth needed to score an understanding asset.

The stream is a list of records, one per dict:
  {id, day, source, kind, slot, value, text, expires_day?}

source: self | other | assistant | device | doc      — provenance
kind:   statement | update | correction | retraction |
        suggestion | hearsay                          — semantics
slot/value: the underlying state field and its asserted value.
text:     natural-language surface form (zh), what a real system would see.

Truth: for each checkpoint day, {slot: {"current": v|None, "provenance": src}}
after applying ops in order (update/correction overwrite; retraction clears;
expired constraints clear at expires_day; hearsay/suggestion never count as
the person's own state — provenance probes test that distinction).

v3 (M3 update pressure): the stream also carries DERIVED records —
kind="derived", source="inference", plus a `supports` list of premise
record ids. A derived fact lives only while every premise holds: deleting
or superseding a premise (retraction, evaluator forget(), a correction
changing the premised value, expiry) kills it — and the kill is
transitive when derived records support other derived records. Assets
that store derived facts flat keep them alive past their premise's death
and lose points; truth-maintenance wiring (supports -> dependents) is
what the round selects for.
"""
from __future__ import annotations

import random

DAYS = 90
CHECKPOINTS = [18, 36, 54, 72, 90]

SLOTS = ["city", "job", "goal", "time_budget", "family", "diet",
         "exercise", "learning", "risk", "contact", "sleep", "device"]

VALS = {
    "city": ["北京", "上海", "深圳", "杭州"],
    "job": ["在职", "自由职业", "待业", "创业中"],
    "goal": ["考虑创业", "已决定创业", "专注本职工作", "准备跳槽"],
    "time_budget": ["每周10小时", "每周4小时", "每晚1小时", "仅周末"],
    "family": ["无照护负担", "需照顾老人", "需接送孩子", "独居"],
    "diet": ["无偏好", "素食", "低碳水", "清淡少油"],
    "exercise": ["跑步", "游泳", "健身房", "不运动"],
    "learning": ["英语", "Python", "管理学", "设计"],
    "risk": ["保守", "中性", "激进"],
    "contact": ["微信", "邮件", "电话", "当面"],
    "sleep": ["23点前睡", "凌晨1点睡", "不规律"],
    "device": ["手机为主", "电脑为主", "平板"],
}

OTHER_PEOPLE = ["同事小李", "朋友阿伟", "表姐"]

# canonical person -> short alias (M1 entity-resolution pressure);
# the registry itself arrives in-stream as kind="alias" records
ALIASES = {"同事小李": "小李", "朋友阿伟": "阿伟"}

# derived slots hold facts the system inferred; their zh labels feed _txt
DSLOT_ZH = {"plan_hint": "计划提示", "routine_fit": "作息适配",
            "elder_plan": "照护安排"}


def _txt(kind, slot, value, src, day):
    who = "我" if src == "self" else ("助手" if src == "assistant" else src)
    zh = {"city": "住在", "job": "工作状态是", "goal": "目标",
          "time_budget": "每周可投入", "family": "家庭情况",
          "diet": "饮食偏好", "exercise": "运动习惯", "learning": "在学",
          "risk": "风险偏好", "contact": "联系渠道", "sleep": "作息",
          "device": "主要设备"}.get(slot) or DSLOT_ZH.get(slot, slot)
    if kind == "derived":
        return f"系统推断：{zh}为{value}。（由前提记录推出）"
    if kind == "statement":
        return f"{who}说：{zh}是{value}。"
    if kind == "update":
        return f"{who}更新：{zh}现在是{value}（之前不同了）。"
    if kind == "correction":
        return f"{who}更正：之前关于{zh}记错了，应该是{value}。"
    if kind == "retraction":
        return f"{who}要求删除关于{zh}的记录。"
    if kind == "suggestion":
        return f"助手建议：不妨试试{value}。（仅为建议，本人未表态）"
    if kind == "hearsay":
        return f"听说{who}的{zh}是{value}。"
    if kind == "alias":
        return f"{slot} 是 {value} 的简称。"
    return f"{zh}：{value}"


def generate(seed: int = 7, density: int = 1, storm: bool = False):
    """density scales record VOLUME (ambient/noise loops) inside the
    same 90-day semantics — a scale-stress knob: impls that pay per
    record per probe (replay readers) degrade linearly, vertex-lookup
    impls stay flat.

    storm=True multiplies probe COUNT (every unambiguous subject key,
    every changed slot x every post-change ckpt, all self-said prov,
    more as_of/purpose coverage) — the efficiency-selection knob: a
    real user asks thousands of questions, so serve cost becomes a
    real gradient without touching the cost coefficients."""
    rng = random.Random(seed)
    records = []
    truth_events = []          # ordered (day, op, slot, value, source)
    probes = []
    rid = 0

    first_rec_id, first_val = {}, {}

    def _person():
        p = rng.choice(OTHER_PEOPLE)
        if p in ALIASES and rng.random() < 0.4:
            return ALIASES[p]
        return p

    def _forms(person):
        """canonical + alias forms of a person name."""
        forms = {person}
        for canon, alias in ALIASES.items():
            if person == canon:
                forms.add(alias)
            elif person == alias:
                forms.add(canon)
        return forms

    def rec(day, source, kind, slot, value, expires=None,
            supports=None, premises=None):
        nonlocal rid
        r = {"id": f"r{rid:04d}", "day": day, "source": source,
             "kind": kind, "slot": slot, "value": value,
             "text": _txt(kind, slot, value, source, day)}
        if expires:
            r["expires_day"] = expires
        if supports:
            r["supports"] = list(supports)
        records.append(r)
        rid += 1
        if kind == "derived":
            truth_events.append(
                {"day": day, "op": "set_derived", "slot": slot,
                 "value": value, "premises": dict(premises or {})})
        elif source == "self" and kind in (
                "statement", "update", "correction"):
            truth_events.append(
                {"day": day, "op": "set", "slot": slot, "value": value,
                 "expires_day": expires})
        elif kind == "retraction":
            truth_events.append({"day": day, "op": "del", "slot": slot})
        return r

    # phase 1: establish all slots (self), plus noise
    day = 1
    for slot in SLOTS:
        v = rng.choice(VALS[slot])
        r = rec(day, "self", "statement", slot, v)
        first_rec_id[slot], first_val[slot] = r["id"], v
        day += rng.randint(1, 3)

    # noise: hearsay about others + assistant suggestions (never truth)
    for _ in range(10 * density):
        slot = rng.choice(SLOTS)
        rec(rng.randint(2, 20), _person(), "hearsay",
            slot, rng.choice(VALS[slot]))
        rec(rng.randint(2, 20), "assistant", "suggestion", slot,
            rng.choice(VALS[slot]))

    # ambient traffic: ~150 non-authoritative records (device/doc/other
    # statements + extra hearsay) spread across the whole stream — zero
    # effect on truth, but replay/retrieval serve machinery pays to wade
    # through them. This is what makes serve cost a real gradient.
    for _ in range(75 * density):
        slot = rng.choice(SLOTS)
        rec(rng.randint(2, 88), rng.choice(["device", "doc", "other"]),
            "statement", slot, rng.choice(VALS[slot]))
        rec(rng.randint(2, 88), _person(), "hearsay",
            slot, rng.choice(VALS[slot]))

    # mid-stream: genuine changes to ~5 slots, spread over days 20-60
    changed = rng.sample(SLOTS, 5)
    corr_slot = rng.choice(changed)   # forced correction (M3 premise-kill)
    change_day, change_rec_id = {}, {}
    for slot in changed:
        d = rng.randint(20, 60)
        change_day[slot] = d
        kind = "correction" if slot == corr_slot else rng.choice(
            ["update", "correction"])
        pool = [v for v in VALS[slot]]
        if slot == corr_slot:
            pool = [v for v in pool if v != first_val.get(slot)]
        change_rec_id[slot] = rec(d, "self", kind, slot,
                                  rng.choice(pool))["id"]
        # a conflicting hearsay right after the change (must not win)
        rec(d + 1, _person(), "hearsay", slot,
            rng.choice(VALS[slot]))

    # expiring constraint: family constraint valid days ~30-50 then lapses
    exp_day = rng.randint(45, 55)
    rec(rng.randint(28, 32), "self", "statement", "family",
        "需照顾老人", expires=exp_day)

    # retraction: user asks to delete one slot's record ~day 70
    retract_slot = rng.choice([s for s in SLOTS if s not in changed])
    rec(rng.randint(68, 74), "self", "retraction", retract_slot, "")

    # user-control event (not a stream record): the evaluator calls
    # forget(slot) right after ckpt-54 probes. Truth-wise the slot is
    # deleted entirely from that day on (state + history).
    FORGET_DAY = 55
    # must precede any later self-update on the slot, else a correct asset
    # would legitimately recreate it after forget() while truth says gone.
    # Fall back to a never-changed slot if every change lands at/after 55.
    pref = [s for s in changed if change_day[s] < FORGET_DAY]
    forget_slot = rng.choice(
        pref if pref else
        [s for s in SLOTS if s != retract_slot and s not in changed])
    truth_events.append({"day": FORGET_DAY, "op": "del",
                         "slot": forget_slot})

    # ---- M3: derived records with declared supports -----------------
    # The system-inference family: each derived fact declares premise
    # record ids; it lives only while every premise holds. Deleting the
    # forgotten slot must kill d1 (depth-1) AND d2 (premised on d1 —
    # depth-2 chain). Correcting corr_slot must kill d3 (premise value
    # superseded — revision semantics, not just deletion).
    def liveval(slot, day):
        v, vd = None, -1
        for e in truth_events:
            if e["day"] > day or e["slot"] != slot:
                continue
            if e["op"] == "del":
                v, vd = None, e["day"]
            elif e["day"] >= vd:
                v, vd = e["value"], e["day"]
        return v

    d3_val = "陪护优先排程"
    d3_day = min(18, change_day[corr_slot] - 2)
    rec(d3_day, "inference", "derived",
        "elder_plan", d3_val,
        supports=[first_rec_id[corr_slot]],
        premises={corr_slot: first_val[corr_slot]})
    # supports must name the record actually carrying the premised value —
    # the change record only if its day precedes the derivation, else the
    # initial statement (a wrong id makes honest premise resolution kill
    # the derived at birth)
    d1_sup = (change_rec_id[forget_slot]
              if forget_slot in change_rec_id
              and change_day[forget_slot] <= 46
              else first_rec_id[forget_slot])
    r_d1 = rec(46, "inference", "derived", "plan_hint", "周末上午安排",
               supports=[d1_sup],
               premises={forget_slot: liveval(forget_slot, 46)})
    rec(50, "inference", "derived", "routine_fit", "晚间例行可保留",
        supports=[r_d1["id"]], premises={"plan_hint": "周末上午安排"})
    # a derived whose premise never dies — gives the drvprov probes a
    # living citation target (all the other derived are designed to
    # die young on premise invalidation)
    r_anchor = rec(5, "self", "statement", "creed", "每天记录")
    rec(60, "inference", "derived", "habit_fit", "记录习惯可持续",
        supports=[r_anchor["id"]], premises={"creed": "每天记录"})

    # ---- M1 pressure ---------------------------------------------------
    # alias registry: person names arrive in short forms too. Delivered
    # as stream records (kind="alias", slot=alias, value=canonical) —
    # impls that merge person vertices answer subject probes correctly.
    for canon, alias in ALIASES.items():
        rec(rng.randint(3, 8), "system", "alias", alias, canon)

    records.sort(key=lambda r: r["day"])

    # out-of-order delivery: day is authoritative, not arrival order.
    # Shuffle a third of the self-write records a few positions later
    # inside their checkpoint window. Derived records and every record
    # named in a supports list keep feed order (premise availability
    # stays pinned to the current semantics).
    protected = {rid for r in records for rid in r.get("supports", [])}
    pool = [i for i, r in enumerate(records)
            if r["kind"] not in ("derived", "alias")
            and r["id"] not in protected
            and r["source"] == "self"]
    for i in rng.sample(pool, max(1, len(pool) // 3)):
        r = records.pop(i)
        j = min(len(records), i + rng.randint(1, 8))
        records.insert(j, r)

    # ---- truth at each checkpoint ----
    # truth_events are appended in CONSTRUCTION order, not day order
    # (e.g. the expiring statement is emitted after the change loop) —
    # replay must be day-ordered or a stale declaration overwrites a
    # newer value. Stable sort keeps append order within the same day.
    truth_events.sort(key=lambda e: e["day"])

    # user-correct event (not a stream record): the evaluator calls
    # asset.correct(slot, value) between ckpt-72 and ckpt-90 — a
    # user-control write that must land (and kill dependents premised
    # on the old value) exactly like a stream correction would.
    CORRECT_DAY = 78
    correct_slot = rng.choice([s for s in changed
                               if s not in (corr_slot, forget_slot,
                                            retract_slot)])
    _old = liveval(correct_slot, CORRECT_DAY)
    _pool = [v for v in VALS[correct_slot] if v != _old]
    correct_val = rng.choice(_pool) if _pool else None
    if correct_val is not None:
        truth_events.append({"day": CORRECT_DAY, "op": "set",
                             "slot": correct_slot, "value": correct_val})
        truth_events.sort(key=lambda e: e["day"])

    # user-control event 3: range forget — the evaluator calls
    # forget({"day_gte":lo,"day_lte":hi}) between ckpt 54 and 72.
    # Erasing a write record rolls the slot back to its previous live
    # value — real deletion is history-aware rollback, not a tombstone.
    # The window is [change_day, change_day+1] of a changed slot so the
    # change record itself is erased; it never covers the day-55 del.
    FORGET2_DAY = 62
    SKIP = None                      # (lo, hi) erased day window
    fr_slot = erased_val = rollback_val = None
    fr_cands = [s for s in changed
                if s not in (corr_slot, forget_slot, retract_slot,
                             correct_slot) and change_day[s] <= 60]
    rng.shuffle(fr_cands)
    for s in fr_cands:
        lo, hi = change_day[s], change_day[s] + 1
        if lo <= FORGET_DAY <= hi:
            continue                # never erase the day-55 del edge

        def liveval_ex(slot, day, lo_, hi_):
            v, vd = None, -1
            for e in truth_events:
                if e["day"] > day or e["slot"] != slot:
                    continue
                if lo_ <= e["day"] <= hi_:
                    continue
                if e["op"] == "del":
                    v, vd = None, e["day"]
                elif e["day"] >= vd:
                    v, vd = e["value"], e["day"]
            return v

        ev_ = liveval(s, hi)         # what the change wrote
        rv_ = liveval_ex(s, 90, lo, hi)  # truth after rollback
        if ev_ != rv_ and rv_ is not None:
            fr_slot, erased_val, rollback_val = s, ev_, rv_
            SKIP = (lo, hi)
            break

    def alive(r, c):
        """Is this record still knowable at read day c?"""
        if r["day"] > c:
            return False
        return not (c > FORGET2_DAY and SKIP
                    and SKIP[0] <= r["day"] <= SKIP[1])

    def state_at(day):
        cur, prov, exp, drv = {}, {}, {}, {}

        def prune_derived():
            """Kill live derived facts whose premises no longer hold —
            premise slot absent or its live value diverged; transitive via
            cur (derived values live there while valid)."""
            moved = True
            while moved:
                moved = False
                for s, d in list(drv.items()):
                    if any(cur.get(ps) != pv
                           for ps, pv in d["premises"].items()):
                        del drv[s]
                        cur.pop(s, None)
                        prov.pop(s, None)
                        moved = True

        for e in truth_events:
            if e["day"] > day:
                continue
            if (day > FORGET2_DAY and SKIP
                    and SKIP[0] <= e["day"] <= SKIP[1]):
                continue            # range-forgotten writes never wrote
            if e["op"] == "del":
                cur.pop(e["slot"], None)
                prov.pop(e["slot"], None)
            elif e["op"] == "set_derived":
                drv[e["slot"]] = {"premises": e["premises"]}
                cur[e["slot"]] = e["value"]
                prov[e["slot"]] = "inference"
            else:
                cur[e["slot"]] = e["value"]
                prov[e["slot"]] = "self"
                if e.get("expires_day"):
                    exp[e["slot"]] = e["expires_day"]
            prune_derived()
        for s, d in list(exp.items()):
            if day > d and s in cur:
                cur.pop(s)
                prov.pop(s, None)
        prune_derived()   # expiry kills dependents too
        return cur, prov

    truth = {}
    for c in CHECKPOINTS:
        cur, prov = state_at(c)
        truth[c] = {"slots": cur, "prov": prov}

    # ---- probes ----
    pid = 0
    meta_pending = []

    def probe(ckpt, ptype, slot, expect, must_not=None, q=None,
              value=None, day=None, person=None, post_import=False,
              purpose=None, purpose_slots=None, budget=None, slots=None,
              op=None, partial=False):
        nonlocal pid
        p = {"id": f"p{pid:03d}", "ckpt": ckpt, "type": ptype,
             "slot": slot, "expect": expect,
             "must_not": must_not or [], "q": q or slot, "value": value}
        if day is not None:
            p["day"] = day
        if person is not None:
            p["person"] = person
        if purpose is not None:
            p["purpose"] = purpose
        if purpose_slots is not None:
            p["purpose_slots"] = purpose_slots
        if op is not None:
            p["op"] = op
        if budget is not None:
            p["budget"] = budget
        if slots is not None:
            p["slots"] = slots
        if post_import:
            p["post_import"] = True
        if partial:
            p["post_partial"] = True
        probes.append(p)
        pid += 1

    for c in CHECKPOINTS:
        cur, prov = state_at(c)
        # state probes on changed slots
        for slot in changed:
            if slot in cur:
                probe(c, "state", slot, cur[slot],
                      q=f"此人当前的{slot}是什么？")
            else:
                probe(c, "state", slot, "未知",
                      q=f"此人当前的{slot}是什么？")
        # stale probe: first old value must NOT surface
        # (find earliest 'set' for the slot before a later change)
        for slot in changed:
            hist = [e for e in truth_events if e["slot"] == slot]
            if len(hist) >= 2:
                old = hist[0]["value"]
                probe(c, "stale", slot, cur.get(slot, "未知"),
                      must_not=[old] if old != cur.get(slot) else [],
                      q=f"此人{slot}的最新有效值（不要给已变更前的旧值）")
        # provenance probes on noise records seen before ckpt
        # skip a noise value the person independently also stated
        noise = [r for r in records if alive(r, c) and
                 r["kind"] in ("hearsay", "suggestion") and
                 r["slot"] != forget_slot and
                 not (c > CORRECT_DAY and r["slot"] == correct_slot
                      and r["value"] == correct_val)
                 and not any(s["source"] == "self" and s["slot"] == r["slot"]
                             and s["value"] == r["value"] for s in records
                             if alive(s, c))]
        for r in (noise if storm else noise[:3]):
            probe(c, "prov", r["slot"], "非本人", value=r["value"],
                  q=f"“{r['slot']}={r['value']}”这条信息是本人说的吗？"
                    "答 本人 或 非本人")
        # positive provenance controls: things the person DID say
        # (forget_slot excluded: post-forget "did they say it" is ambiguous)
        said = [r for r in records if alive(r, c) and
                r["source"] == "self" and r["slot"] != forget_slot and
                r["kind"] in ("statement", "update", "correction")]
        for r in (said if storm else said[-2:]):
            probe(c, "prov", r["slot"], "本人", value=r["value"],
                  q=f"“{r['slot']}={r['value']}”这条信息是本人说的吗？"
                    "答 本人 或 非本人")
        # subject probes: hearsay is attributable memory about OTHER people
        # (must be stored without polluting self-state). Collapse by
        # (person, slot) keeping latest so simultaneous probes never ask
        # for two different values of the same attributed fact.
        heard = [r for r in records if alive(r, c) and r["day"] <= c
                 and r["kind"] == "hearsay" and r["slot"] != forget_slot]
        latest_heard = {}
        for r in heard:
            # group alias forms onto the canonical person
            canon = next((c for c, a in ALIASES.items()
                          if r["source"] == a), r["source"])
            key = (canon, r["slot"])
            if (key not in latest_heard
                    or r["day"] >= latest_heard[key]["day"]):
                latest_heard[key] = r
        # drop keys whose latest day has a same-day rival: "latest" is
        # undefined within a day — don't probe what has no canonical
        # answer (rng collision, not designed pressure)
        def _canon_of(x):
            return next((c for c, a in ALIASES.items()
                         if x["source"] == a), x["source"])
        for key, r in list(latest_heard.items()):
            if any(x is not r and x["day"] == r["day"]
                    and (_canon_of(x), x["slot"]) == key for x in heard):
                del latest_heard[key]
        subj_keys = list(latest_heard.items())
        for key, r in (subj_keys if storm else subj_keys[-2:]):
            canon = key[0]
            probe(c, "subject", r["slot"], r["value"], person=canon,
                  q=f"传闻中{canon}的{r['slot']}是什么？")
        # as_of probes: reconstruct state at a past day — needs history,
        # not just latest-wins (bitemporal pressure per lit surveys)
        for slot in ([s for s in changed
                      if s not in (forget_slot, retract_slot)
                      and change_day[s] < c]
                     if storm else [s for s in changed
                      if s not in (forget_slot, retract_slot)
                      and change_day[s] < c][:2]):
            D = change_day[slot] - 3
            past_val = state_at(D)[0].get(slot)
            current_val = cur.get(slot)
            probe(c, "as_of", slot, past_val if past_val else "未知",
                  must_not=[current_val]
                  if current_val is not None and current_val != past_val
                  else [],
                  q=f"截至第{D}天，此人{slot}是什么？", day=D)
    # range-forget probes: after FORGET2_DAY the erased change must roll
    # back — the slot answers its previous live value and the erased
    # value is stale bait.
    if fr_slot:
        for c in (72, 90):
            probe(c, "state", fr_slot, rollback_val,
                  q=f"此人{fr_slot}现在是什么？")
            probe(c, "stale", fr_slot, rollback_val,
                  must_not=[erased_val],
                  q=f"此人{fr_slot}的最新有效值（不要给已变更前的旧值）")

    # ops-audit probes (M5): the user can ask which control ops ran —
    # requires an operation journal that survives export/import.
    probe(90, "ops", forget_slot, forget_slot, op="forget",
          q="本人曾要求彻底删除过哪一类信息？（回答槽位名）",
          post_import=True)
    if correct_val:
        probe(90, "ops", correct_slot, correct_slot, op="correct",
              q="本人纠正过哪一类信息？（回答槽位名）",
              post_import=True)
    if fr_slot and SKIP:
        probe(90, "ops", "range", f"{SKIP[0]}-{SKIP[1]}",
              op="forget_range",
              q="本人曾要求删除哪个时间段的信息？（回答天数范围）",
              post_import=True)

    # drvprov: citation of a living derived fact's premises — the TMS
    # premise registry must be inspectable, not just load-bearing.
    # (the purpose-built derived all die young by design; habit_fit's
    # premise survives, so it is the living-citation target — and the
    # dead-derived probe checks post-death honesty)
    probe(72, "drvprov", "habit_fit", ["creed:每天记录"],
          q="派生'记录习惯可持续'依赖哪个前提？（槽位:值）")
    probe(90, "drvprov", "habit_fit", ["creed:每天记录"],
          q="派生'记录习惯可持续'依赖哪个前提？（槽位:值）",
          post_import=True)
    probe(90, "drvprov", "routine_fit", "无",
          q="派生'晚间例行可保留'现在依赖哪个前提？")

    # temporal-aggregate probes: serve must walk edges, not just read
    # the latest one. duration = days since the live value's streak
    # started; nchange = count of value transitions on the self vertex.
    ctl_touched = {x for x in (forget_slot, fr_slot, correct_slot,
                             retract_slot, 'family', 'creed')
                   if x is not None}
    agg_slots = [s for s in changed if s not in ctl_touched]
    for s in agg_slots[:3]:
        for c in CHECKPOINTS:
            evs = sorted([e for e in truth_events
                          if e["slot"] == s and e["day"] <= c
                          and e["op"] != "set_derived"],
                         key=lambda e: e["day"])
            live_val, start = None, None
            for e in reversed(evs):
                if e["op"] == "del":
                    break
                if live_val is None:
                    live_val, start = e["value"], e["day"]
                elif e["value"] == live_val:
                    start = e["day"]
                else:
                    break
            if live_val is not None and c > start:
                probe(c, "duration", s, f"{c - start}天",
                      q=f"{s}这个值维持了多久？")
    for s in agg_slots[:4]:
        evs = sorted([e for e in truth_events
                      if e["slot"] == s and e["op"] != "set_derived"],
                     key=lambda e1: e1["day"])
        n, prev = 0, None
        for e in evs:
            if e["op"] == "del":
                prev = None
                continue
            if prev is not None and e["value"] != prev:
                n += 1
            prev = e["value"]
        probe(90, "nchange", s, str(n),
              q=f"{s}一共变更过几次？（回答数字）",
              post_import=True)

    # retraction probe: only at checkpoints AFTER the retraction arrived
    retract_day = next((r["day"] for r in records
                        if r["kind"] == "retraction"), 10**9)
    for c in CHECKPOINTS:
        rv = next((e for e in truth_events if e["slot"] == retract_slot
                   and e["op"] == "set"), None)
        if c >= retract_day:
            probe(c, "retract", retract_slot, ["已删除", "未知", "unknown"],
                  must_not=[rv["value"]] if rv else [],
                  q=f"此人{retract_slot}的当前值？（该记录已被本人撤回）")
    # cascade probes: after the evaluator's forget() call, every asserted
    # value of the slot must be gone (state AND history)
    fs_vals = [e["value"] for e in truth_events
               if e["slot"] == forget_slot and e["op"] == "set"]
    for c in CHECKPOINTS:
        if c > FORGET_DAY:
            probe(c, "cascade", forget_slot, ["已删除", "未知", "unknown"],
                  must_not=[v for v in fs_vals if v],
                  q=f"此人{forget_slot}的当前值？（本人已要求彻底删除该信息）",
                  post_import=(c == CHECKPOINTS[-1]))

    # ---- M3 probes: derived facts tracked while live, gone when the
    # premise dies (deletion of a supporting slot -> 'cascade' on the
    # derived slot; premise superseded by correction -> 'derive').
    dval = {"plan_hint": "周末上午安排",
            "routine_fit": "晚间例行可保留",
            "elder_plan": "陪护优先排程"}
    death = {"plan_hint": (FORGET_DAY, "cascade"),
             "routine_fit": (FORGET_DAY, "cascade"),
             "elder_plan": (change_day[corr_slot], "derive")}
    asserted_day = {"plan_hint": 46, "routine_fit": 50,
                    "elder_plan": d3_day}
    for c in CHECKPOINTS:
        cur_c, _ = state_at(c)
        for ds, (d_day, ptype) in death.items():
            if asserted_day[ds] <= c < d_day and ds in cur_c:
                probe(c, "state", ds, cur_c[ds],
                      q=f"此人的{DSLOT_ZH[ds]}是什么？")
            elif c >= d_day:
                probe(c, ptype, ds, ["已删除", "未知", "unknown"],
                      must_not=[dval[ds]],
                      q=f"此人的{DSLOT_ZH[ds]}是什么？（前提已失效）",
                      post_import=(c == CHECKPOINTS[-1]))

    # ---- export-import continuity (M5 carry-over): the evaluator
    # round-trips state() -> import_state() right after ckpt-72 probes;
    # these ckpt-90 probes are scored only if the move preserved the
    # asset (state, history, attributed hearsay, provenance, deletions).
    EXPORT_DAY = 72
    cur90, _ = state_at(90)
    ex_slot = next((s for s in changed
                    if s in cur90 and s != forget_slot), None)
    if ex_slot:
        probe(90, "state", ex_slot, cur90[ex_slot],
              q=f"此人当前的{ex_slot}是什么？", post_import=True)
    ex_asof = next((s for s in changed
                    if s not in (forget_slot, retract_slot)
                    and change_day[s] < 87), None)
    if ex_asof:
        D = change_day[ex_asof] - 3
        pv = state_at(D)[0].get(ex_asof)
        probe(90, "as_of", ex_asof, pv if pv else "未知", day=D,
              must_not=[cur90[ex_asof]]
              if cur90.get(ex_asof) and cur90[ex_asof] != pv else [],
              q=f"截至第{D}天，此人{ex_asof}是什么？",
              post_import=True)
    lh = [r for r in records if r["kind"] == "hearsay"
          and r["slot"] != forget_slot and alive(r, 90)]
    # collapse by (canon, slot) -> latest; only probe keys whose
    # latest day is unambiguous (no same-day rival)
    lh_latest = {}
    for r in lh:
        canon = next((c for c, a in ALIASES.items()
                      if r["source"] == a), r["source"])
        key = (canon, r["slot"])
        if key not in lh_latest or r["day"] >= lh_latest[key]["day"]:
            lh_latest[key] = r
    def _lhcanon(x):
        return next((c for c, a in ALIASES.items()
                     if x["source"] == a), x["source"])
    lh_cands = [r for key, r in lh_latest.items()
                if not any(x is not r and x["day"] == r["day"]
                           and (_lhcanon(x), x["slot"]) == key
                           for x in lh)]
    if lh_cands:
        r = max(lh_cands, key=lambda x: (x["day"], records.index(x)))

    # conf: epistemic grading — 'I know' (self-authoritative) vs 'I
    # heard' (hearsay). A lifemodel must retain the source's grade,
    # not just the value.
    for s in [x for x in cur90
              if x in changed and x not in ctl_touched][:2]:
        probe(90, "conf", s, "高",
              q=f"你对{s}有多确定？（高/低/无）")
    for r in lh_cands[:2]:
        canon = next((c for c, a in ALIASES.items()
                      if r["source"] == a), r["source"])
        probe(90, "conf", r["slot"], "低", person=canon,
              q=f"你对{r['source']}的{r['slot']}有多确定？（高/低/无）")
        probe(90, "subject", r["slot"], r["value"], person=r["source"],
              q=f"传闻中{r['source']}的{r['slot']}是什么？",
              post_import=True)
    said90 = [r for r in records if alive(r, 90)
              and r["source"] == "self" and r["slot"] != forget_slot
              and r["kind"] in ("statement", "update", "correction")]
    if said90:
        r = said90[-1]
        probe(90, "prov", r["slot"], "本人", value=r["value"],
              q=f"“{r['slot']}={r['value']}”这条信息是本人说的吗？"
                "答 本人 或 非本人", post_import=True)
    # ---- M4 probes (serve pressure) ---------------------------------
    rv2 = next((e for e in truth_events if e["slot"] == retract_slot
                and e["op"] == "set"), None)
    # unans: evidence-absent questions — never-asserted slots baited by
    # hearsay/suggestion values (LoCoMo-style adversarial: surface-
    # answerable, actually unanswerable). The abstention gate lives or
    # dies here: leaking the bait = -0.5.
    bait_slot = "hobby"
    bait_val = rng.choice(["摄影", "木工", "烘焙"])
    bait_rec = rec(rng.randint(8, 12), rng.choice(OTHER_PEOPLE),
                   "hearsay", bait_slot, bait_val)
    bait2 = rec(rng.randint(38, 44), "assistant", "suggestion",
                bait_slot, rng.choice(["滑雪", "潜水", "围棋"]))
    for c in CHECKPOINTS:
        if c > bait_rec["day"]:
            probe(c, "unans", bait_slot, "未知",
                  must_not=[bait_rec["value"], bait2["value"]],
                  q=f"此人{bait_slot}是什么？")

    # purpose: task-conditioned view — serve ONLY the live values of the
    # purpose's slots; anything else is a leak. purpose_slots are given
    # in the probe (the use-case definition is part of the query).
    PURPOSES = {
        "制定照护方案": ["family", "elder_plan", "sleep"],
        "制定本周计划": ["time_budget", "risk", "plan_hint",
                       "routine_fit"],
        "生成个人简介": ["city", "job", "goal", "diet", "contact",
                       "device"],
    }
    # user-control event: the evaluator calls revoke_purpose(purpose)
    # between ckpts 72 and 90. Truth-wise the use is withdrawn — the
    # data stays, the view must refuse (M5 consent-withdrawal pressure).
    REVOKE_DAY = 84
    rvk_purpose = rng.choice(list(PURPOSES))
    # ops probe for the withdrawal (journal must carry it past import)
    probe(90, "ops", rvk_purpose, rvk_purpose, op="revoke_purpose",
          q="本人撤回过哪一个用途？（回答用途名）",
          post_import=True)
    for c in CHECKPOINTS[2:]:           # 54, 72, 90
        cur_c, _ = state_at(c)
        for pname, pslots in PURPOSES.items():
            exp_vals = [cur_c[s] for s in pslots if s in cur_c]
            if c > REVOKE_DAY and pname == rvk_purpose:
                # post-withdrawal: the view must refuse, and must NOT
                # leak the purpose's own live values either
                probe(c, "revoked", pname, "已撤回", must_not=exp_vals,
                      q=f"为{pname}提供相关值（该用途授权已撤回）",
                      purpose=pname, purpose_slots=pslots,
                      post_import=True)
                continue
            if not exp_vals:
                continue
            others = {s for ps in PURPOSES.values() for s in ps
                      if s not in pslots}
            leak = [cur_c[s] for s in others
                    if s in cur_c and cur_c[s] not in exp_vals]
            probe(c, "purpose", "_view", exp_vals, must_not=leak,
                  q=f"为{pname}提供相关值（只列该用途相关槽位的当前值，"
                    "逗号分隔）",
                  purpose=pname, purpose_slots=pslots,
                  post_import=(c == CHECKPOINTS[-1] and pname ==
                               "生成个人简介"))

    # partial export (v7, M5 selective portability): the evaluator fires
    # state(scope={"slots": pslots}) crossing day 80 and scores the scoped
    # document — purpose slots' live values must be in it, every other
    # live value must be absent.
    pe_purpose = next((p for p in PURPOSES if p != rvk_purpose), None)
    if pe_purpose:
        pslots = PURPOSES[pe_purpose]
        meta_part = {"purpose": pe_purpose, "slots": pslots, "day": 80}
        meta_pending.append(("export_partial", meta_part))
        in_live = [s for s in pslots if s in cur90]
        out_live = [s for s in cur90 if s not in pslots
                    and s != forget_slot][:2]
        for s in in_live[:3]:
            probe(90, "partial", s, cur90[s],
                  q=f"按用途{pe_purpose}导出：{s}应在导出文档中",
                  partial=True)
        for s in out_live:
            probe(90, "partial", s, "", must_not=[cur90[s]],
                  q=f"按用途{pe_purpose}导出：{s}不得泄露",
                  partial=True)

    # revoked-purpose export (consent hole): a purpose-scoped export is
    # a USE — after withdrawal it must refuse, or the data leaves
    # through the side door the view closed. The evaluator fires
    # state(scope={slots, purpose=rvk}) after the revoke; the probe
    # passes only when no document comes back.
    rvk_slots = PURPOSES.get(rvk_purpose, [])
    rvk_vals = [cur90[s] for s in rvk_slots if s in cur90]
    probe(90, "expdeny", "_rvkdoc", "已撤回", must_not=rvk_vals,
          q=f"按用途{rvk_purpose}导出（该用途授权已撤回——应拒绝）")

    # budget: pack the listed slots' live values under a byte budget —
    # ordering becomes the decision (Lost-in-the-Middle pressure).
    # First `budget` bytes of the answer are what's scored.
    bslots = ["time_budget", "risk", "contact"]
    for c in (72, 90):
        cur_c, _ = state_at(c)
        exp_vals = [cur_c[s] for s in bslots if s in cur_c]
        if len(exp_vals) < 2:
            continue
        exp_bytes = sum(len(str(v).encode()) for v in exp_vals)
        stale_vals = [e["value"] for e in truth_events
                      if e["slot"] in bslots and e["op"] == "set"
                      and e["day"] <= c
                      and cur_c.get(e["slot"]) != e["value"]]
        probe(c, "budget", "_pack", exp_vals, must_not=stale_vals,
              q="列出以下槽位的当前值（逗号分隔）："
                + ",".join(bslots),
              budget=exp_bytes + 6, slots=bslots,
              post_import=(c == 90))

    # prov2: evidence citation — the answer must name the record id that
    # carries the current assertion (ALCE-style attribution).
    def latest_rid(slot, day):
        rid_, md = None, -1
        for r in records:
            if (r["source"] == "self" and r["slot"] == slot
                    and r["kind"] in ("statement", "update", "correction")
                    and r["day"] <= day and r["day"] > md
                    and alive(r, day)):
                rid_, md = r["id"], r["day"]
        return rid_

    for c in CHECKPOINTS[3:]:           # 72, 90
        p2_slots = [s for s in changed
                    if s not in (forget_slot, retract_slot)]
        for s in (p2_slots if storm else p2_slots[:2]):
            rid_ = latest_rid(s, c)
            if rid_:
                probe(c, "prov2", s, rid_,
                      q=f"你对{s}的判断依据是哪条记录？（给出记录ID）",
                      post_import=(c == 90))

    # transfer probe at final checkpoint: bundle of constraints
    cur, _ = state_at(CHECKPOINTS[-1])
    transfer_expect = [cur[s] for s in ("time_budget", "family", "risk")
                       if s in cur]
    stale_decoys = []
    if rv2:
        stale_decoys.append(rv2["value"])
    exp_rec = next((e for e in truth_events if e["slot"] == "family"
                    and e.get("expires_day")), None)
    if exp_rec:
        stale_decoys.append(exp_rec["value"])
    probe(CHECKPOINTS[-1], "transfer", "_bundle", transfer_expect,
          must_not=stale_decoys,
          q="为他制定本周计划需要哪些当前约束？列出相关值，逗号分隔")

    meta = {"changed": changed, "retract_slot": retract_slot,
            "exp_day": exp_day, "n_records": len(records),
            "corr_slot": corr_slot, "export_day": EXPORT_DAY,
            "forget": {"slot": forget_slot, "day": FORGET_DAY}}
    if correct_val is not None:
        meta["correct"] = {"slot": correct_slot, "value": correct_val,
                           "day": CORRECT_DAY}
    meta["revoke"] = {"purpose": rvk_purpose, "day": 84,
                      "slots": PURPOSES.get(rvk_purpose, [])}
    for k_, v_ in meta_pending:
        meta[k_] = v_
    if fr_slot:
        meta["forget_range"] = {"day": FORGET2_DAY,
                                "lo": SKIP[0], "hi": SKIP[1]}
    return records, probes, truth, meta
