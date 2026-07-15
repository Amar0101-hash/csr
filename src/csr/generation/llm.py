"""Claude-on-Bedrock client wrapper (Anthropic SDK, Bedrock backend)."""
from __future__ import annotations

import json
import re
from typing import Any

import anthropic

from ..config import Settings


class ClaudeClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self._client = anthropic.AnthropicBedrock(
            aws_region=settings.aws_region,
            timeout=settings.request_timeout,
            max_retries=1,
        )

    def complete_json(
        self,
        system: str,
        user: str,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Call Claude and parse a single JSON object from the reply.

        Adaptive thinking at high effort can consume the whole token budget
        before any JSON is emitted (empty reply) or cut it off mid-object
        (truncated). So we escalate the budget and retry until the JSON parses.
        """
        base = max_tokens or self.s.max_gen_tokens
        budgets = [base, min(base * 3, 48000)]
        last_err: Exception | None = None
        for budget in budgets:
            text, stop = self.complete_text(system, user, budget, return_stop=True)
            if not text.strip():
                last_err = ValueError(f"empty reply (stop={stop}, budget={budget})")
                continue
            try:
                return _extract_json(text)
            except (ValueError, json.JSONDecodeError) as e:
                last_err = e
                # only worth retrying bigger if the model ran out of room
                if stop != "max_tokens" and budget >= budgets[1]:
                    break
        raise last_err or ValueError("generation failed")

    def complete_text(
        self,
        system: str,
        user: str,
        max_tokens: int | None = None,
        return_stop: bool = False,
    ):
        max_tokens = max_tokens or self.s.max_gen_tokens
        kwargs: dict[str, Any] = dict(
            model=self.s.gen_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # Sonnet 4.6 supports adaptive thinking + effort. Stream so large
        # max_tokens don't trip the SDK's non-streaming timeout guard.
        try:
            kwargs["thinking"] = {"type": "adaptive"}
            kwargs["output_config"] = {"effort": self.s.effort}
            msg = self._final_message(kwargs)
        except anthropic.BadRequestError:
            kwargs.pop("thinking", None)
            kwargs.pop("output_config", None)
            msg = self._final_message(kwargs)
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        if return_stop:
            return text, getattr(msg, "stop_reason", None)
        return text

    def _final_message(self, kwargs: dict[str, Any]):
        with self._client.messages.stream(**kwargs) as stream:
            return stream.get_final_message()


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    # strip code fences
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # find first balanced { ... }
    start = text.find("{")
    if start == -1:
        raise ValueError(f"No JSON object in model reply: {text[:200]}")
    depth = 0
    in_str = False
    esc = False
    candidate = None
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    break
    if candidate is None:
        candidate = text[start:]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return json.loads(_repair_json(candidate))


def _repair_json(s: str) -> str:
    """Best-effort repair of the two failures we actually see from the model:
    trailing commas, and unescaped double-quotes inside string values."""
    # drop trailing commas before } or ]
    s = re.sub(r",\s*([}\]])", r"\1", s)
    # escape stray double-quotes that sit inside a value (not structural). A
    # structural quote is preceded by { , : [ or whitespace after those, or is a
    # closing quote followed by , } ] or :. Anything else inside a string body
    # gets escaped.
    out = []
    in_str = False
    esc = False
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                out.append(ch)
                esc = False
            elif ch == "\\":
                out.append(ch)
                esc = True
            elif ch == '"':
                nxt = _next_nonspace(s, i + 1)
                if nxt in ",}]:":       # legitimate closing quote
                    in_str = False
                    out.append(ch)
                else:                    # stray inner quote -> escape it
                    out.append('\\"')
            else:
                out.append(ch)
        else:
            out.append(ch)
            if ch == '"':
                in_str = True
    return "".join(out)


def _next_nonspace(s: str, i: int) -> str:
    while i < len(s) and s[i] in " \t\r\n":
        i += 1
    return s[i] if i < len(s) else ""
