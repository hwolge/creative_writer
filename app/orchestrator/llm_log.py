"""Thin wrapper around client.chat.completions.create() that logs timing and token usage."""
import time
from typing import Any


def _fmt(n: int) -> str:
    """Right-justify a token count with thousands separator in a 6-char field."""
    return f"{n:>6,}"


def timed_completion(client: Any, *, label: str, **kwargs) -> Any:
    """Call client.chat.completions.create(**kwargs), then print one log line.

    Usage:
        response = timed_completion(client, label="reconcile_scene",
                                    model=settings.fast_model, messages=msgs,
                                    response_format={"type": "json_object"})
    """
    t0 = time.perf_counter()
    response = client.chat.completions.create(**kwargs)
    elapsed = time.perf_counter() - t0

    model: str = kwargs.get("model", "?")
    usage = getattr(response, "usage", None)

    if usage:
        print(
            f"[LLM] {model:<16}  {label:<28}"
            f"  in={_fmt(usage.prompt_tokens)}"
            f"  out={_fmt(usage.completion_tokens)}"
            f"  tok={_fmt(usage.total_tokens)}"
            f"  {elapsed:.1f}s",
            flush=True,
        )
    else:
        print(f"[LLM] {model:<16}  {label:<28}  {elapsed:.1f}s", flush=True)

    return response
