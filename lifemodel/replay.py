"""Reference temporal replay for exceptional writes and erasure.

Legacy snapshots carry only a partial arrival order. Explore their legal
orders, merging equivalent states, and accept only a confluent result.
Never manufacture a cross-vertex order from dictionary keys or record IDs.
"""
from __future__ import annotations

import copy
import json


class TemporalReplayUnavailable(ValueError):
    """The retained legacy history cannot determine this mutation safely."""


class _State:
    def __init__(self):
        self.cur, self.exp, self.known, self.drv = {}, {}, {}, {}
        self.pending = []

    def key(self):
        return json.dumps(self.__dict__, sort_keys=True, ensure_ascii=False)

    def live(self, slot, day):
        edge = self.cur.get(slot)
        if (edge is not None and edge[2] != "retraction"
                and not (self.exp.get(slot) is not None
                         and day > self.exp[slot])
                and not (edge[3] is not None and day > edge[3])):
            return edge[0]
        entry = self.drv.get(slot)
        return entry["value"] if entry else None

    def register(self, dev):
        premises = {}
        for rid in dev["supports"]:
            if rid not in self.known:
                return "pending"
            slot, value, day = self.known[rid]
            if day > dev["day"]:
                return "dead"
            premises[slot] = value
        self.drv[dev["slot"]] = dict(premises=premises, value=dev["value"])
        return "live"

    def prune(self, day):
        self.pending = [dev for dev in self.pending
                        if self.register(dev) == "pending"]
        changed = True
        while changed:
            changed = False
            for slot, entry in list(self.drv.items()):
                if any(self.live(s, day) != value
                       for s, value in entry["premises"].items()):
                    del self.drv[slot]
                    changed = True

    def apply(self, event):
        edge, slot = event["edge"], event["slot"]
        if event["support"] and edge[4]:
            self.known[edge[4]] = (slot, edge[0], edge[1])
        if event["owner"]:
            self.cur[slot] = edge
            if edge[2] != "retraction" and edge[3]:
                self.exp[slot] = edge[3]
        if event["dev"] is not None:
            if self.register(event["dev"]) == "pending":
                self.pending.append(event["dev"])
        self.prune(edge[1])


def _events(hist, logs, affected):
    """Project the dependency ancestors, retaining all clock transitions."""
    by_id = {e[4]: (k.rsplit("|", 1)[-1], e[0])
             for k, edges in hist.items() for e in edges if e[4]}
    needed = set(affected)
    while True:
        before = set(needed)
        for dev in logs:
            if dev["slot"] in needed:
                needed.update(by_id[rid][0] for rid in dev["supports"]
                              if rid in by_id)
        if needed == before:
            break
    selected_logs = [d for d in logs if d["slot"] in needed]
    supports = {rid for d in selected_logs for rid in d["supports"]}
    events, used = [], set()
    for vertex, edges in hist.items():
        slot = vertex.rsplit("|", 1)[-1]
        for index, edge in enumerate(edges):
            dev = None
            if edge[2] == "derived" and slot in needed:
                matches = [(i, d) for i, d in enumerate(selected_logs)
                           if i not in used and d["slot"] == slot
                           and d["day"] == edge[1]
                           and (len(edge) < 6 or d.get("arrival_seq") == edge[5])
                           and d.get("vertex", f"{d['src']}|{d['slot']}") == vertex
                           and (d.get("id") == edge[4] if edge[4]
                                else not d.get("id") and d["value"] == edge[0])]
                if not matches:
                    raise TemporalReplayUnavailable("missing derived birth metadata")
                i, dev = min(matches, key=lambda pair: pair[1]["seq"])
                used.add(i)
            owner = (vertex == f"self|{slot}" and slot in needed
                     and edge[2] in {"statement", "update", "correction", "retraction"})
            events.append(dict(vertex=vertex, index=index, edge=edge, slot=slot,
                               owner=owner, support=edge[4] in supports,
                               dev=dev, arrival=edge[5] if len(edge) > 5 else None))
    if len(used) != len(selected_logs):
        raise TemporalReplayUnavailable("derived log has no matching retained edge")
    return events


def _day_orders(states, events):
    """All outcomes of a day's known partial order, not one guessed order."""
    count = len(events)
    parents = [0] * count
    for i, a in enumerate(events):
        for j, b in enumerate(events):
            if i == j:
                continue
            # Unknown legacy arrivals predate newly recorded arrivals.
            precedes = (a["arrival"] is None and b["arrival"] is not None)
            if a["arrival"] is not None and b["arrival"] is not None:
                precedes = a["arrival"] < b["arrival"]
            elif a["arrival"] is None and b["arrival"] is None:
                precedes = (a["vertex"] == b["vertex"] and a["index"] < b["index"])
                if a["dev"] is not None and b["dev"] is not None:
                    precedes |= a["dev"]["seq"] < b["dev"]["seq"]
            if precedes:
                parents[j] |= 1 << i
    complete = (1 << count) - 1
    significant = [i for i, event in enumerate(events)
                   if event["owner"] or event["support"] or event["dev"] is not None]
    if len(significant) != count:
        # Clock-only events are idempotent after the first event of a
        # day: every meaningful event already prunes at that same day.
        # Preserve both possible initial-clock cases when the partial
        # order permits them, without enumerating 2**N irrelevant noise
        # subsets. Pairwise retained ordering is transitively closed for
        # clocks (same vertex, known sequence, legacy-before-new).
        if not significant:
            for state in states:
                state.prune(events[0]["edge"][1])
            return states
        first_clock = any(parents[i] == 0 for i in range(count)
                          if i not in significant)
        outcomes = []
        # Without an initial clock, only a genuinely minimal meaningful
        # event may go first. Removing its clock predecessors before this
        # choice would admit impossible renew-before-expiry histories.
        for first in significant:
            if parents[first] != 0:
                continue
            starts = []
            for state in states:
                nxt = copy.deepcopy(state)
                nxt.apply(events[first])
                starts.append(nxt)
            outcomes.extend(_day_orders(starts, [events[i] for i in significant
                                                 if i != first]))
        if first_clock:
            starts = []
            for state in states:
                clocked = copy.deepcopy(state)
                clocked.prune(events[0]["edge"][1])
                starts.append(clocked)
            outcomes.extend(_day_orders(starts, [events[i] for i in significant]))
        if not outcomes:
            raise TemporalReplayUnavailable("inconsistent retained arrival order")
        return list({state.key(): state for state in outcomes}.values())
    frontier = {(0, state.key()): state for state in states}
    for _ in range(count):
        following = {}
        for (done, _key), state in frontier.items():
            for i, event in enumerate(events):
                bit = 1 << i
                if done & bit or parents[i] & ~done:
                    continue
                nxt = copy.deepcopy(state)
                nxt.apply(event)
                following[(done | bit, nxt.key())] = nxt
        frontier = following
        if not frontier:
            raise TemporalReplayUnavailable("inconsistent retained arrival order")
    return [state for (done, _key), state in frontier.items() if done == complete]


def replay(hist, logs, now, affected):
    """Return exact derived/pending results, or reject legacy ambiguity."""
    events = _events(hist, logs, affected)
    days = {}
    for event in events:
        days.setdefault(event["edge"][1], []).append(event)
    states = [_State()]
    for day in sorted(days):
        group = days[day]
        if all(e["arrival"] is not None for e in group):
            for state in states:
                for event in sorted(group, key=lambda e: e["arrival"]):
                    state.apply(event)
        else:
            states = _day_orders(states, group)
        states = list({state.key(): state for state in states}.values())
    outcomes = {}
    for state in states:
        state.prune(now)
        drv = {s: d for s, d in state.drv.items() if s in affected}
        pending = [d for d in state.pending if d["slot"] in affected]
        outcome = (drv, pending)
        outcomes[json.dumps(outcome, sort_keys=True, ensure_ascii=False)] = outcome
    if len(outcomes) != 1:
        raise TemporalReplayUnavailable("legacy cross-vertex arrival order is ambiguous")
    return next(iter(outcomes.values()))
