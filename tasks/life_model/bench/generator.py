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


def _txt(kind, slot, value, src, day):
    who = "我" if src == "self" else ("助手" if src == "assistant" else src)
    zh = {"city": "住在", "job": "工作状态是", "goal": "目标",
          "time_budget": "每周可投入", "family": "家庭情况",
          "diet": "饮食偏好", "exercise": "运动习惯", "learning": "在学",
          "risk": "风险偏好", "contact": "联系渠道", "sleep": "作息",
          "device": "主要设备"}[slot]
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
    return f"{zh}：{value}"


def generate(seed: int = 7):
    rng = random.Random(seed)
    records = []
    truth_events = []          # ordered (day, op, slot, value, source)
    probes = []
    rid = 0

    def rec(day, source, kind, slot, value, expires=None):
        nonlocal rid
        r = {"id": f"r{rid:04d}", "day": day, "source": source,
             "kind": kind, "slot": slot, "value": value,
             "text": _txt(kind, slot, value, source, day)}
        if expires:
            r["expires_day"] = expires
        records.append(r)
        rid += 1
        if source == "self" and kind in (
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
        rec(day, "self", "statement", slot, v)
        day += rng.randint(1, 3)

    # noise: hearsay about others + assistant suggestions (never truth)
    for _ in range(10):
        slot = rng.choice(SLOTS)
        rec(rng.randint(2, 20), rng.choice(OTHER_PEOPLE), "hearsay",
            slot, rng.choice(VALS[slot]))
        rec(rng.randint(2, 20), "assistant", "suggestion", slot,
            rng.choice(VALS[slot]))

    # mid-stream: genuine changes to ~5 slots, spread over days 20-60
    changed = rng.sample(SLOTS, 5)
    change_day = {}
    for slot in changed:
        d = rng.randint(20, 60)
        change_day[slot] = d
        rec(d, "self", rng.choice(["update", "correction"]), slot,
            rng.choice([v for v in VALS[slot]]))
        # a conflicting hearsay right after the change (must not win)
        rec(d + 1, rng.choice(OTHER_PEOPLE), "hearsay", slot,
            rng.choice(VALS[slot]))

    # expiring constraint: family constraint valid days ~30-50 then lapses
    exp_day = rng.randint(45, 55)
    rec(rng.randint(28, 32), "self", "statement", "family",
        "需照顾老人", expires=exp_day)

    # retraction: user asks to delete one slot's record ~day 70
    retract_slot = rng.choice([s for s in SLOTS if s not in changed])
    rec(rng.randint(68, 74), "self", "retraction", retract_slot, "")

    records.sort(key=lambda r: r["day"])

    # ---- truth at each checkpoint ----
    def state_at(day):
        cur, prov, exp = {}, {}, {}
        for e in truth_events:
            if e["day"] > day:
                continue
            if e["op"] == "del":
                cur.pop(e["slot"], None)
                prov.pop(e["slot"], None)
            else:
                cur[e["slot"]] = e["value"]
                prov[e["slot"]] = "self"
                if e.get("expires_day"):
                    exp[e["slot"]] = e["expires_day"]
        for s, d in list(exp.items()):
            if day > d and s in cur:
                cur.pop(s)
        return cur, prov

    truth = {}
    for c in CHECKPOINTS:
        cur, prov = state_at(c)
        truth[c] = {"slots": cur, "prov": prov}

    # ---- probes ----
    pid = 0

    def probe(ckpt, ptype, slot, expect, must_not=None, q=None,
              value=None):
        nonlocal pid
        probes.append({"id": f"p{pid:03d}", "ckpt": ckpt, "type": ptype,
                       "slot": slot, "expect": expect,
                       "must_not": must_not or [], "q": q or slot,
                       "value": value})
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
        noise = [r for r in records if r["day"] <= c and
                 r["kind"] in ("hearsay", "suggestion") and
                 not any(s["source"] == "self" and s["slot"] == r["slot"]
                         and s["value"] == r["value"] for s in records
                         if s["day"] <= c)]
        for r in noise[:3]:
            probe(c, "prov", r["slot"], "非本人", value=r["value"],
                  q=f"“{r['slot']}={r['value']}”这条信息是本人说的吗？"
                    "答 本人 或 非本人")
        # positive provenance controls: things the person DID say
        said = [r for r in records if r["day"] <= c and
                r["source"] == "self" and
                r["kind"] in ("statement", "update", "correction")]
        for r in said[-2:]:
            probe(c, "prov", r["slot"], "本人", value=r["value"],
                  q=f"“{r['slot']}={r['value']}”这条信息是本人说的吗？"
                    "答 本人 或 非本人")
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
    # transfer probe at final checkpoint: bundle of constraints
    cur, _ = state_at(CHECKPOINTS[-1])
    transfer_expect = [cur[s] for s in ("time_budget", "family", "risk")
                       if s in cur]
    stale_decoys = []
    rv2 = next((e for e in truth_events if e["slot"] == retract_slot
                and e["op"] == "set"), None)
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
            "exp_day": exp_day, "n_records": len(records)}
    return records, probes, truth, meta
