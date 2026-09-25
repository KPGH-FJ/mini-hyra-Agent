"""M4 natural-language surface: map a Chinese question onto the probe
space, then let serve.answer do the work.

This is the product form of serve — the bench probes the same contract
through typed dicts; here free text gets routed to a probe type first.
Routing is rule-based (slot lexicon + cue patterns); an LLM router is a
drop-in replacement for the same _probe_for() output.
"""
from __future__ import annotations

import re

# slot lexicon: zh gloss -> slot id. Kept minimal and honest — this is
# the registry a deployment would populate, not a benchmark hack.
SLOT_ZH = {
    "city": ["城市", "住在", "哪里", "哪儿"],
    "job": ["工作", "职业"],
    "goal": ["目标", "打算"],
    "diet": ["饮食", "吃"],
    "contact": ["联系方式", "联系"],
    "device": ["设备", "手机", "电脑"],
    "family": ["家庭", "老人", "孩子"],
    "time_budget": ["时间预算", "时间"],
    "learning": ["学习"],
    "risk": ["风险"],
    "sleep": ["作息", "睡眠", "睡觉"],
    "exercise": ["锻炼", "运动"],
    "hobby": ["爱好", "兴趣"],
    "plan_hint": ["计划提示"],
    "routine_fit": ["作息适配"],
    "elder_plan": ["照护安排", "照护"],
}

_DAY_RE = re.compile(r"第\s*(\d+)\s*天|day\s*(\d+)", re.I)
_PERSON_RE = re.compile(r"([\u4e00-\u9fff]{1,4}?)(?:说|提到|声称|讲)")

_RID_CUES = ("哪条记录", "依据", "证据", "记录ID", "记录id")
_PURPOSE_CUES = ("制定", "生成")


def _slot_of(text):
    for slot, glosses in SLOT_ZH.items():
        if any(g in text for g in glosses):
            return slot
    return None


def _probe_for(text, purposes):
    """Free text -> probe dict (or None when unrouteable)."""
    slot = _slot_of(text)

    # purpose view: a registered purpose name appearing in the text
    for pname, pslots in purposes.items():
        if pname in text:
            return {"type": "purpose", "slot": "_view",
                    "purpose": pname, "purpose_slots": pslots}

    # evidence citation
    if slot and any(c in text for c in _RID_CUES):
        return {"type": "prov2", "slot": slot}

    # subject attribution: "X说..." asks what X claimed
    m = _PERSON_RE.search(text)
    if m and slot:
        return {"type": "subject", "slot": slot, "person": m.group(1)}

    # as_of: value at an explicit day
    if slot:
        d = _DAY_RE.search(text)
        if d:
            day = int(d.group(1) or d.group(2))
            return {"type": "as_of", "slot": slot, "day": day}

    # everything else with a slot is a state probe — the serve layer
    # already handles retracted/expired/derived/never-seen uniformly
    if slot:
        return {"type": "state", "slot": slot}
    return None


def query(model, text, purposes=None, ckpt=10**9):
    """Answer a natural-language question through the probe contract.

    purposes: {name: [slots]} — the deployment's use-case registry
    (same shape the bench's purpose probes carry).
    """
    p = _probe_for(text, purposes or {})
    if p is None:
        return "未知"
    p["ckpt"] = ckpt
    return model.answer(p)
