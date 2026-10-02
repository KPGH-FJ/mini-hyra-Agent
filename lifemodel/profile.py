"""M4 serve surface: consolidated persona profile — the user-asset primitive.

renders the TemporalGraph into a single profile document (life-domain
sections, one bullet per atomic fact, temporal anchors inline). Probe-validated
on 24 LME questions: profile-only answering scored 87.5%, the best channel
measured (nogate/assist 83.3, relaxed-gate 75) — no retrieval stage means no
under-pick; the only measured loss is multi-item enumeration questions that
the profile summarizes.

Prompt text is the exam-validated PROFILE_SYS from results/lme_profile/; keep
the verbatim-fact and assistant-facts clauses — dropping them regresses recall.
"""
from .reader import render_vertices, vertex_catalog

PROFILE_SYS = """You are compiling a PERSONA PROFILE from a user's memory records.
Organize the records into a coherent profile of this person, grouped by life
domain (identity/work, health & habits, hobbies & interests, possessions &
purchases, relationships & social, plans & commitments, events & timeline,
preferences & opinions).

CRITICAL: this profile will be the ONLY memory used to answer questions later.
- Preserve EVERY concrete fact verbatim-ish: names, counts, dates, durations,
  places, prices, items — never generalize "bought a peace lily on 2023-05-07"
  into "bought plants recently".
- Keep temporal anchors (dates / relative times) inline with each fact.
- Keep both user facts AND assistant-provided facts (recommendations, advice
  the user received) — tag assistant-side facts as "assistant suggested X".
- Group by domain; within a domain keep one bullet per atomic fact.
- No preamble, no analysis — emit ONLY the profile document."""


async def render_profile(model, llm) -> str:
    """Compile the whole graph into a profile document.

    Callers wanting to answer many questions off one profile should render
    once and reuse the string (the graph is immutable between calls).
    """
    cat = vertex_catalog(model)
    dump = render_vertices(model, list(cat))
    return await llm.complete(
        PROFILE_SYS,
        f"MEMORY RECORDS ({len(cat)} topics):\n" + dump)
