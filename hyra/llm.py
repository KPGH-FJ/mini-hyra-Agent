"""Pluggable LLM backends with retry/backoff and usage accounting.

- OpenAICompatLLM: any OpenAI-compatible /chat/completions endpoint
  (env fallbacks: OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL).
- ScriptedLLM: deterministic offline backend for --mock; drives real
  evolutionary perturbation through the whole pipeline.

File protocol emitted/consumed everywhere:

    <<<FILE: relative/path>>>
    <content>
    <<<END>>>

parse_files() also tolerates a fenced-code-block fallback so a weaker model
that drops the markers can still be used.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import urllib.request
from typing import Protocol

log = logging.getLogger("hyra.llm")


class LLM(Protocol):
    async def complete(self, system: str, prompt: str) -> str: ...


class LLMError(RuntimeError):
    pass


class LLMLengthError(LLMError):
    """Completion hit the token cap (finish_reason='length')."""


class OpenAICompatLLM:
    def __init__(self, model: str | None = None, base_url: str | None = None,
                 api_key: str | None = None, max_tokens: int = 16384,
                 temperature: float = 0.7, retries: int = 8):
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL")
                         or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.retries = retries
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
        if not self.api_key:
            raise LLMError("no API key: set OPENAI_API_KEY or pass api_key=")

    async def complete(self, system: str, prompt: str) -> str:
        delay = 1.0
        last: Exception | None = None
        max_tokens = self.max_tokens
        for attempt in range(self.retries):
            body = json.dumps({
                "model": self.model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": prompt}],
                "temperature": self.temperature,
                "max_tokens": max_tokens,
            }).encode()
            try:
                data, usage = await asyncio.to_thread(self._post, body)
                self.usage["calls"] += 1
                self.usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
                self.usage["completion_tokens"] += usage.get(
                    "completion_tokens", 0)
                return data
            except LLMLengthError as e:
                # reasoning models can burn the whole budget on reasoning;
                # raise the cap and retry without counting it as a failure
                last = e
                max_tokens = min(max_tokens * 2, 131072)
                log.warning("truncated; retrying max_tokens=%d", max_tokens)
                await asyncio.sleep(0.5)
            except Exception as e:
                last = e
                log.warning("llm call failed (attempt %d/%d): %s",
                            attempt + 1, self.retries, e)
                await asyncio.sleep(delay + random.uniform(0, delay * 0.5))
                delay = min(delay * 2, 60)
        raise LLMError(f"llm failed after {self.retries} retries: {last}")

    def _post(self, body: bytes) -> tuple[str, dict]:
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=600) as r:
            payload = json.loads(r.read())
        choice = payload["choices"][0]
        content = choice["message"].get("content")
        if choice.get("finish_reason") == "length" or not content:
            if choice.get("finish_reason") == "length":
                raise LLMLengthError("completion truncated at token cap")
            raise LLMError(
                f"empty completion (finish_reason="
                f"{choice.get('finish_reason')})")
        return content, payload.get("usage", {})


FILE_RE = re.compile(r"<<<FILE:\s*(.+?)>>>\n(.*?)<<<END>>>", re.S)
FENCE_RE = re.compile(r"```[\w.-]*\n(.*?)```", re.S)
FENCE_NAME_RE = re.compile(
    r"(?:^|\n)\s*(?:#+\s*|`?)([\w./-]+\.[a-zA-Z0-9]+)`?\s*\n```[\w.-]*\n(.*?)```")


def parse_files(text: str) -> dict[str, str]:
    """Parse <<<FILE: p>>> ... <<<END>>> blocks; fall back to ```lang blocks
    preceded by a filename line if the primary protocol is absent."""
    files = {m.group(1).strip(): m.group(2)
             for m in FILE_RE.finditer(text)}
    if files:
        return files
    for m in FENCE_NAME_RE.finditer(text):
        files.setdefault(m.group(1).strip(), m.group(2))
    if not files:  # last resort: unnamed blocks -> guess by content
        blocks = FENCE_RE.findall(text)
        for b in blocks:
            if b.lstrip().startswith("#!") or "solve.sh" in b[:200]:
                files.setdefault("solve.sh", b)
        if len(blocks) == 1 and "solve.sh" not in files:
            files["solve.sh"] = blocks[0]
    return files


def render_files(files: dict[str, str]) -> str:
    return "".join(f"<<<FILE: {p}>>>\n{c}\n<<<END>>>\n"
                   for p, c in files.items())


class ScriptedLLM:
    """Offline backend exercising the real pipeline on bundled demo tasks."""

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
        self._call = 0

    async def complete(self, system: str, prompt: str) -> str:
        self._call += 1
        self.usage["calls"] += 1
        if "<<CONTEXT_AGENT>>" in system:
            return json.dumps(
                [{"direction": d, "note": f"scripted {d} #{self._call}"}
                 for d in ("exploit", "explore", "fresh", "repair")])
        if "<<PROPOSAL>>" in system:
            return self._propose(prompt)
        if "<<EVALUATOR_GEN>>" in system or "<<EVAL_REFINE>>" in system:
            return "MOCK_NO_EVALUATOR_GEN"
        return "MOCK_EMPTY"

    def _propose(self, prompt: str) -> str:
        m = re.search(r"<<<BASE_PARAMS>>>\n(.*?)\n<<<END_BASE>>>",
                      prompt, re.S)
        dm = re.search(r"<<<DIRECTION>>>(.*?)<<<", prompt, re.S)
        direction = dm.group(1).strip() if dm else "exploit"
        params = {}
        if m:
            try:
                params = json.loads(m.group(1))
            except Exception:
                params = {}
        sigma = {"exploit": 0.05, "explore": 0.4, "fresh": 1.5,
                 "repair": 0.1, "hybrid": 0.2}.get(direction, 0.2)
        is_packing = (isinstance(params.get("positions"), list)
                      or '"positions"' in prompt or "circle" in prompt.lower())
        if is_packing:
            pts = params.get("positions")
            return self._propose_packing(
                pts if isinstance(pts, list) else [], direction, sigma)
        if not params or direction == "fresh":
            params = {k: self.rng.uniform(-2, 2) for k in "abcd"}
        params = {k: v + self.rng.gauss(0, sigma * max(abs(v), 0.5))
                  for k, v in params.items()}
        model_py = ("import json\n"
                    f"PARAMS = {json.dumps(params)}\n"
                    "if __name__ == '__main__':\n"
                    "    print(json.dumps(PARAMS))\n")
        solve_sh = ('#!/bin/bash\ncd "$(dirname "$0")"\nmkdir -p .run\n'
                    "python3 model.py > solution.json\n")
        return render_files({"solve.sh": solve_sh, "model.py": model_py})

    def _propose_packing(self, positions, direction: str,
                         sigma: float) -> str:
        """circle_packing demo policy: jitter centers, then rescale so the
        minimum pairwise distance is exactly 1 (validity projection)."""
        import math
        pts = [[float(x), float(y)] for x, y in positions]
        if direction == "fresh" or len(pts) != 10:
            pts = [[self.rng.uniform(0, 4), self.rng.uniform(0, 4)]
                   for _ in range(10)]
        j = sigma * 0.5
        pts = [[x + self.rng.gauss(0, j), y + self.rng.gauss(0, j)]
               for x, y in pts]
        mind = min(math.dist(pts[a], pts[b])
                   for a in range(len(pts)) for b in range(a + 1, len(pts)))
        if mind < 1.0:  # rescale about the centroid so circles stop overlapping
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            s = 1.0 / mind
            pts = [[cx + (x - cx) * s, cy + (y - cy) * s] for x, y in pts]
        pack_py = ("import json\n"
                   f"pts = {json.dumps(pts)}\n"
                   "print(json.dumps({'positions': pts}))\n")
        solve_sh = ('#!/bin/bash\ncd "$(dirname "$0")"\nmkdir -p .run\n'
                    "python3 pack.py > solution.json\n")
        return render_files({"solve.sh": solve_sh, "pack.py": pack_py})
