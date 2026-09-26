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
    "city": ["城市", "住在", "住哪", "哪里", "哪儿"],
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

# entity registry: surface forms -> canonical entity id. A deployment
# populates this from the owner's address book; "X说" takes the
# claimer role, "X的slot"/plain mentions take the about role.
_ENTITY_ALIASES = {
    "妈妈": ("妈妈", "我妈", "母亲"), "爸爸": ("爸爸", "我爸", "父亲"),
    "姐姐": ("姐姐", "我姐"), "妹妹": ("妹妹", "我妹"),
    "哥哥": ("哥哥", "我哥"), "弟弟": ("弟弟", "我弟"),
    "爷爷": ("爷爷", "我爷"), "奶奶": ("奶奶", "我奶"),
    "爱人": ("爱人",), "室友": ("室友",), "孩子": ("孩子",),
    "朋友": ("朋友",), "同事": ("同事",), "老板": ("老板",),
    "老师": ("老师",),
}


def _about_of(text, speaker=None):
    for ent, forms in _ENTITY_ALIASES.items():
        if ent == speaker:
            continue
        if any(f in text for f in forms):
            return ent
    return None

_RID_CUES = ("哪条记录", "依据", "证据", "记录ID", "记录id")
_PURPOSE_CUES = ("制定", "生成")
_DURATION_CUES = ("多久", "持续了", "维持", "连续")
_NCHANGE_CUES = ("几次", "变过几次", "改过", "变过")
_CONF_CUES = ("有多确定", "确定吗", "信心", "把握")
_DRVPROV_CUES = ("凭什么相信", "为什么相信", "前提是什么", "为什么认为")
_OPS_CUES = (("撤回过", "revoke_purpose"), ("纠正过", "correct"),
             ("删过", "forget"), ("忘记过", "forget"), ("抹掉过", "forget"))
_XCMP_CUES = ("一样", "相同", "一致")
_FIRST_CUES = ("最早", "最初", "一开始", "第一次记录")
_ORDER_CUES = ("变化过程", "变化顺序", "依次是", "演变", "怎么变的")
_ABSENT_CUES = ("一直没变", "稳定", "保持")
_WINDOW_CUES = ("之间变", "期间变", "中间那段时间")


def _slot_of(text):
    for slot, glosses in SLOT_ZH.items():
        if any(g in text for g in glosses):
            return slot
    return None


def _probe_for(text, purposes):
    """Free text -> probe dict (or None when unrouteable)."""
    slot = _slot_of(text)
    m = _PERSON_RE.search(text)
    about = _about_of(text, m.group(1) if m else None)

    # purpose view: a registered purpose name appearing in the text
    for pname, pslots in purposes.items():
        if pname in text:
            return {"type": "purpose", "slot": "_view",
                    "purpose": pname, "purpose_slots": pslots}

    # evidence citation
    if slot and any(c in text for c in _RID_CUES):
        return {"type": "prov2", "slot": slot}

    # subject attribution: "X说..." asks what X claimed (about whom)
    if m and slot:
        return {"type": "subject", "slot": slot, "person": m.group(1),
                "about": about}

    # temporal aggregation / epistemic grading / premise citation
    if slot and any(c in text for c in _DURATION_CUES):
        return {"type": "duration", "slot": slot, "about": about}
    if slot and any(c in text for c in _NCHANGE_CUES):
        return {"type": "nchange", "slot": slot, "about": about}
    if slot and any(c in text for c in _CONF_CUES):
        return {"type": "conf", "slot": slot,
                "person": m.group(1) if m else None, "about": about}
    if slot and any(c in text for c in _DRVPROV_CUES):
        return {"type": "drvprov", "slot": slot}

    # owner-control audit: "你删过/纠正过/撤回过什么"
    if any(cue in text for cue, _ in _OPS_CUES):
        op = next(op for cue, op in _OPS_CUES if cue in text)
        return {"type": "ops", "slot": "_audit", "op": op}

    # v9 history reasoning: entity-vs-self compare needs both an
    # entity mention and a sameness cue; run-shape cues route to the
    # edge-walk handlers before nchange eats "变过"
    if slot and about and any(c in text for c in _XCMP_CUES):
        return {"type": "xcmp", "slot": slot, "about": about}
    if slot and any(c in text for c in _FIRST_CUES):
        return {"type": "first", "slot": slot}
    if slot and any(c in text for c in _ORDER_CUES):
        return {"type": "order", "slot": slot}
    if slot and any(c in text for c in _ABSENT_CUES):
        return {"type": "absent", "slot": slot}
    if slot and any(c in text for c in _WINDOW_CUES):
        return {"type": "window", "slot": slot}

    # as_of: value at an explicit day
    if slot:
        d = _DAY_RE.search(text)
        if d:
            day = int(d.group(1) or d.group(2))
            return {"type": "as_of", "slot": slot, "day": day,
                    "about": about}

    # everything else with a slot is a state probe — the serve layer
    # already handles retracted/expired/derived/never-seen uniformly;
    # about routes to the entity vertex ("妈妈的睡眠" vs 本人)
    if slot:
        return {"type": "state", "slot": slot, "about": about}
    return None


def query(model, text, purposes=None, ckpt=10**9):
    """Answer a natural-language question through the probe contract.

    purposes: {name: [slots]} — the deployment's use-case registry
    (same shape the bench's purpose probes carry).
    """
    p = _probe_for(text, purposes or {})
    if p is None:
        return "未知"
    # open horizon means "now": the latest day the model has observed,
    # so duration/as_of answer relative to ingest, not an infinite day
    if ckpt >= 10**9:
        ckpt = getattr(getattr(model, "store", model), "_now", ckpt)
    p["ckpt"] = ckpt
    return model.answer(p)
