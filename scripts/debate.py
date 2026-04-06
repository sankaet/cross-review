#!/usr/bin/env python3
"""
debate.py — Pure Grok interface for cross-review plugin.

Handles: xAI API calls, model resolution + caching, transcript writing.
Does NOT call Anthropic API. Claude rebuttals come from the skill layer.

Usage:
  python debate.py --mode last --content-file /tmp/cr-content-ts.txt \
    --source-label "last response" --transcript-file /tmp/cross-review-ts.md
  python debate.py --mode last --content-file ... --rebuttal-file /tmp/cr-rebuttal-1-ts.txt \
    --transcript-file ... --round 2
  python debate.py --synthesize --transcript-file /tmp/cross-review-ts.md
"""
import calendar
import json
import os
import sys
import time
from pathlib import Path

CACHE_PATH = Path.home() / ".claude" / "cross-review-models.json"
CACHE_TTL_SECONDS = 86400  # 24 hours
CRITIC_ALIAS = "grok-4.20-reasoning"
JUDGE_ALIAS = "grok-4.20-multi-agent"
XAI_BASE_URL = "https://api.x.ai/v1"

CONVERGENCE_PROMPT = (
    "Review the following critique. Does it raise specific, substantive new objections "
    "— or is it primarily rehashing general concerns and previously addressed points? "
    "Answer YES if there are new substantive objections, NO if it has converged. "
    "Answer YES or NO only."
)

CRITIC_SYSTEM = (
    "You are an independent expert reviewer. Be adversarial. "
    "Find flaws, false assumptions, blind spots. Do not be polite."
)


def emit(obj: dict):
    """Write one JSON object to stdout (one per line)."""
    print(json.dumps(obj), flush=True)


def check_api_key():
    key = os.environ.get("XAI_API_KEY", "")
    if not key:
        print(
            "Error: XAI_API_KEY is not set. Export it and retry:\n"
            "  export XAI_API_KEY=xai-...",
            file=sys.stderr
        )
        sys.exit(1)
    return key


def get_client():
    from openai import OpenAI
    return OpenAI(api_key=check_api_key(), base_url=XAI_BASE_URL)


def resolve_models(client) -> tuple[str, str]:
    """Return (critic_model_id, judge_model_id), using cache if fresh."""
    # Try cache
    if CACHE_PATH.exists():
        try:
            cache = json.loads(CACHE_PATH.read_text())
            resolved_at = cache.get("resolved_at", "")
            age = time.time() - calendar.timegm(time.strptime(resolved_at, "%Y-%m-%dT%H:%M:%SZ"))
            if age < CACHE_TTL_SECONDS:
                return cache["critic"], cache["judge"]
        except Exception:
            # Malformed JSON or missing keys — treat as miss
            print("Warning: cache corrupted, re-fetching model IDs.", file=sys.stderr)
            try:
                CACHE_PATH.unlink()
            except Exception:
                pass

    # Fetch from API
    try:
        models = client.models.list()
        all_ids = [m.id for m in models.data]
        critics = sorted([m for m in all_ids if CRITIC_ALIAS in m], reverse=True)
        judges = sorted([m for m in all_ids if JUDGE_ALIAS in m], reverse=True)

        if not critics:
            grok_models = [m for m in all_ids if "grok" in m.lower()]
            print(
                f"Error: No models matching critic alias '{CRITIC_ALIAS}' found.\n"
                f"Available Grok models: {grok_models}\n"
                "Check XAI_API_KEY or update CRITIC_ALIAS in debate.py.",
                file=sys.stderr
            )
            sys.exit(1)
        if not judges:
            grok_models = [m for m in all_ids if "grok" in m.lower()]
            print(
                f"Error: No models matching judge alias '{JUDGE_ALIAS}' found.\n"
                f"Available Grok models: {grok_models}\n"
                "Check XAI_API_KEY or update JUDGE_ALIAS in debate.py.",
                file=sys.stderr
            )
            sys.exit(1)

        critic, judge = critics[0], judges[0]
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps({
            "resolved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "critic": critic,
            "judge": judge
        }))
        return critic, judge

    except SystemExit:
        raise
    except Exception as e:
        print(f"Warning: Could not resolve model IDs ({e}), using aliases. Verify XAI_API_KEY.", file=sys.stderr)
        return CRITIC_ALIAS, JUDGE_ALIAS


if __name__ == "__main__":
    pass  # main() added in Task 4
