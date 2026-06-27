#!/usr/bin/env python3
"""Send an ad-hoc message to the managed CEO agent and STREAM the reply live.

Modes:
  * default ("chat")  — overrides the system instruction per-call so the agent just answers
    conversationally. A bare "hi" returns a "hi".
  * --full            — uses the agent's real CEO brief, so it behaves like a mini work loop
    (runs tools, hunts for its workspace). For an ACTUAL hourly loop, use run_loop.py.

Display:
  * default           — streams the agent's text inline + a one-line marker per tool step.
  * --verbose         — also prints the SUBSTANCE LIVE as each step starts (tool args/commands,
    outputs, search queries, reasoning) + a full transcript at the end.
  * --no-stream       — block, then print (+ transcript with --verbose).
  * --raw             — debug: dump each streaming event's full payload (to pin field names).

The agent always runs to completion synchronously (the antigravity agent has no background
mode); streaming just lets you watch. In --full mode a bare "hi" can run for a few minutes
of tool steps before the final text — let it finish; don't Ctrl-C.

Usage:
  export GEMINI_API_KEY=...
  python runner/call_agent.py "hi"                       # chat: quick hello
  python runner/call_agent.py --full --verbose "hi"      # watch it work, full substance, live
  python runner/call_agent.py --raw "hi"                 # debug: dump raw event payloads
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from google import genai

AGENT_ID = os.environ.get("AGENT_ID", "ai-ceo")

CHAT_SYSTEM = (
    "You are the autonomous CEO agent, being pinged ad-hoc by your operator for a quick chat "
    "or status check. This is NOT an hourly work loop and no workspace is mounted. Answer "
    "briefly and directly in plain text. Do NOT run tools, execute code, git, or attempt any "
    "business work unless the message explicitly asks you to."
)

# fields that are bookkeeping, not substance
_SKIP = {"type", "index", "id", "signature", "call_id", "thought_signature"}


def _evt_type(event) -> str:
    return getattr(event, "event_type", "") or getattr(event, "type", "") or ""


def _to_dict(obj) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    for attr in ("model_dump", "dict", "to_dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return fn()
            except Exception:  # noqa: BLE001
                pass
    return dict(getattr(obj, "__dict__", {}) or {})


def _trim(v, n: int = 1500) -> str:
    s = v if isinstance(v, str) else json.dumps(v, default=str, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + f" … [+{len(s) - n} chars]"


def _content_text(d: dict) -> str:
    return "".join(
        item["text"] for item in (d.get("content") or [])
        if isinstance(item, dict) and item.get("text")
    )


def _delta_text(dd: dict) -> str | None:
    """Text lives at delta.content.text (thought_summary / model text)."""
    c = dd.get("content")
    if isinstance(c, dict) and c.get("text"):
        return c["text"]
    return dd.get("text")


def _clean_result(r) -> str:
    """Empty code output comes back as a debugproto blob; show it as (no output)."""
    if isinstance(r, str):
        if "debugproto" in r and 'string_value: ""' in r:
            return "(no output)"
        return _trim(r)
    if r in (None, {}, ""):
        return "(no output)"
    return _trim(r)


def _print_step(step, idx=None) -> None:
    """Print one step's substance. Quiet if the step carries no content yet."""
    d = _to_dict(step)
    t = d.get("type") or "?"
    tag = f"[{idx}] " if idx is not None else "   "

    def emit(s):
        print(f"{tag}{s}", flush=True)

    if t == "user_input":
        return
    if t == "function_call" and (d.get("name") or d.get("arguments")):
        emit(f"↳ call {d.get('name')}  args={_trim(d.get('arguments'))}")
    elif t == "function_result" and d.get("result") not in (None, "", {}):
        emit(f"↳ result {d.get('name')}: {_trim(d.get('result'))}")
    elif t == "code_execution_call":
        code = (d.get("arguments") or {}).get("code") or d.get("code")
        if code:
            emit(f"↳ code: {_trim(code)}")
    elif t == "code_execution_result" and d.get("result") not in (None, ""):
        emit(f"↳ output: {_clean_result(d.get('result'))}")
    elif t in ("google_search_call", "url_context_call") and (d.get("query") or d.get("url")):
        emit(f"↳ {t}: {_trim(d.get('query') or d.get('url'))}")
    elif t in ("google_search_result", "url_context_result") and d.get("result"):
        emit(f"↳ {t}: {_trim(d.get('result'))}")
    elif t == "thought" and d.get("summary"):
        emit(f"🧠 {_trim(d.get('summary'))}")
    elif t == "model_output" and _content_text(d):
        emit(f"💬 {_content_text(d)}")
    else:
        # unknown shape but has content → show the raw non-bookkeeping fields
        rest = {k: v for k, v in d.items() if k not in _SKIP and v not in (None, "", [], {})}
        if rest:
            emit(f"↳ {t}: {_trim(rest)}")


def _print_transcript(interaction) -> None:
    steps = getattr(interaction, "steps", None) or []
    print("\n── full transcript ──")
    for i, s in enumerate(steps):
        _print_step(s, i)
    print("── end ──")


def _kwargs(message: str, full: bool) -> dict:
    kw = {"agent": AGENT_ID, "input": message, "environment": "remote"}
    if not full:
        kw["system_instruction"] = CHAT_SYSTEM
    return kw


def stream_call(client, message: str, full: bool, verbose: bool, raw: bool) -> int:
    mode = "full CEO brief" if full else "chat"
    print(f"-> agent={AGENT_ID!r}  mode={mode}  verbose={verbose}  input={message!r}  "
          f"(streaming; sandbox spins up in ~5s)\n", flush=True)
    stream = client.interactions.create(stream=True, **_kwargs(message, full))
    env_id = None
    for event in stream:
        et = _evt_type(event)
        if raw:
            print(f"[{et}] {_trim(_to_dict(event), 1200)}", flush=True)
            continue
        if et == "interaction.created":
            env_id = getattr(getattr(event, "interaction", None), "environment_id", None)
            if env_id:
                print(f"[sandbox {env_id}]\n", flush=True)
        elif et == "step.start":
            sd = _to_dict(getattr(event, "step", None))
            stype = sd.get("type") or "step"
            if verbose:
                name = sd.get("name")
                if stype == "thought":
                    print("\n🧠 ", end="", flush=True)
                elif stype == "model_output":
                    print("\n💬 ", end="", flush=True)
                elif stype == "function_call":
                    print(f"\n▶ call {name or ''}".rstrip(), flush=True)
                elif stype == "code_execution_call":
                    print("\n▶ code", flush=True)
                elif stype not in ("function_result", "code_execution_result"):
                    print(f"\n▶ {stype}", flush=True)  # result content prints via its delta
            elif stype != "model_output":
                print(f"\n  · {stype} ...", flush=True)
        elif et == "step.delta":
            dd = _to_dict(getattr(event, "delta", None))
            dtype = dd.get("type")
            if dtype == "text":                                  # the model's reply (both modes)
                t = _delta_text(dd)
                if t:
                    print(t, end="", flush=True)
            elif verbose and dtype == "thought_summary":         # reasoning
                t = _delta_text(dd)
                if t:
                    print(t, end="", flush=True)
            elif verbose and dtype == "arguments_delta":         # function-call args
                print(f"  args: {_trim(dd.get('arguments'))}", flush=True)
            elif verbose and dtype == "code_execution_call":     # the code it ran
                code = (dd.get("arguments") or {}).get("code")
                if code:
                    print(f"  $ {code}", flush=True)
            elif verbose and dtype == "code_execution_result":   # command output
                print(f"  → {_clean_result(dd.get('result'))}", flush=True)
            elif verbose and dtype == "function_result":         # tool result
                r = dd.get("result")
                if r not in (None, {}, ""):
                    print(f"  → {_trim(r)}", flush=True)
        elif et == "interaction.completed":
            ix = getattr(event, "interaction", None)
            usage = getattr(ix, "usage", None)
            tok = getattr(usage, "total_tokens", None)
            print(f"\n\n-- done. status={getattr(ix, 'status', '?')}"
                  + (f"  tokens={tok}" if tok else "")
                  + (f"  env={env_id}" if env_id else ""), flush=True)
    return 0


def blocking_call(client, message: str, full: bool, verbose: bool) -> int:
    print(f"-> agent={AGENT_ID!r}  input={message!r}  (waiting...)", flush=True)
    ix = client.interactions.create(**_kwargs(message, full))
    print(f"status: {getattr(ix, 'status', '?')}  env={getattr(ix, 'environment_id', '?')}\n")
    print(getattr(ix, "output_text", "") or "(no text output)")
    if verbose:
        _print_transcript(ix)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("message", nargs="*", help="message to send (default: hi)")
    ap.add_argument("--full", action="store_true",
                    help="use the agent's real CEO brief instead of chat mode")
    ap.add_argument("--verbose", action="store_true",
                    help="show tool args/commands, outputs, searches, and reasoning")
    ap.add_argument("--no-stream", action="store_true", help="block until done, print once")
    ap.add_argument("--raw", action="store_true", help="debug: dump full event payloads")
    args = ap.parse_args()

    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: set GEMINI_API_KEY", file=sys.stderr)
        return 1
    message = " ".join(args.message).strip() or "hi"
    client = genai.Client()
    if args.no_stream:
        return blocking_call(client, message, args.full, args.verbose)
    return stream_call(client, message, args.full, args.verbose, args.raw)


if __name__ == "__main__":
    raise SystemExit(main())
