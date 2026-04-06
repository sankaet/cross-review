# Cross-Review Skill

Cross-model review and debate: sends content to Grok (xAI) for independent critique, then runs an interactive debate loop with user-controlled round progression.

## Invocation

```
/cross-review                  ← asks which context to review
/cross-review --last           ← review Claude's last response
/cross-review --full           ← review full session context
/cross-review --file <path>    ← review a specific file or plan
/cross-review --raw            ← D-mode: show raw Grok output every round (no Claude synthesis)
```

## Step 1 — Determine context mode

If the user passed a flag, use it. Otherwise ask:

> "What should Grok review?
> [1] My last response
> [2] Full session so far
> [3] A file — paste the path"

Wait for their answer if no flag was passed.

## Step 2 — Assemble content and invoke debate.py

Set a timestamp for this session: `TS=$(date +%Y%m%d%H%M%S)`

Based on mode:

**--last:** Write Claude's most recent response to `/tmp/cr-content-$TS.txt`. Set `SOURCE_LABEL="last response"`.

**--full:** Write the full conversation transcript to `/tmp/cr-content-$TS.txt`. Set `SOURCE_LABEL="full session"`.

**--file <path>:** Read the file at `<path>` and write its contents to `/tmp/cr-content-$TS.txt`. Set `SOURCE_LABEL="file — <path>"`. If the file doesn't exist, tell the user and stop.

Resolve the script path (works across plugin versions):

```bash
DEBATE_PY=$(ls -d ~/.claude/plugins/cache/cross-review/cross-review/*/ 2>/dev/null | sort -V | tail -1)scripts/debate.py
```

Run initial critique (Round 1):

```bash
python3 "$DEBATE_PY" \
  --mode <mode> \
  --content-file /tmp/cr-content-$TS.txt \
  --source-label "$SOURCE_LABEL" \
  --transcript-file /tmp/cross-review-$TS.md \
  --round 1
```

Read the JSON output line by line:
- `{"type": "error", ...}` → show the error message and stop
- `{"type": "critique", ...}` → store critique content and word_count
- `{"type": "convergence", "converged": true}` → note convergence, will surface after displaying

## Step 3 — Display round and get user choice

Display:

```
── GROK CRITIQUE (Round N) ──────────────────────────
<critique content — show in full if word_count ≤ 500, otherwise summarize to ~200 words and note "Full critique in transcript">

── CLAUDE RESPONSE ──────────────────────────────────
<Generate a concise rebuttal in-context: address Grok's specific objections, defend correct positions, concede valid points>
```

If convergence was detected:
```
ℹ️  Grok has no new substantive objections — positions have converged.
```

Then:
```
What next?
  [C] Continue debating   [G] Accept Grok's position
  [A] Accept Claude's position   [S] Synthesize verdict
  [D] Show raw Grok output for this round
```

If `--raw` flag was set, skip the Claude Response section and go directly to the D output (raw critique, no synthesis).

## Step 4 — Handle user choice

**[C] Continue:**
- Write Claude's rebuttal to `/tmp/cr-rebuttal-<N>-$TS.txt`
- Append to transcript: `## Round N — Claude Rebuttal\n<rebuttal>`
- Run `python3 "$DEBATE_PY"` with `--round N+1 --rebuttal-file /tmp/cr-rebuttal-<N>-$TS.txt`
- Return to Step 3

**[A] Accept Claude's position:**
- Append to transcript: `## Final Outcome\nAccepted: Claude's position`
- Show output (Step 5)
- Clean up temp files

**[G] Accept Grok's position:**
- Append to transcript: `## Final Outcome\nAccepted: Grok's position`
- Show output (Step 5)
- Clean up temp files

**[S] Synthesize:**
- Run `python3 "$DEBATE_PY" --synthesize --transcript-file /tmp/cross-review-$TS.md`
- Read `{"type": "synthesis", ...}` output
- Show synthesis inline
- Show output (Step 5)
- Clean up temp files

**[D] Show raw:**
- Print the full raw Grok critique for this round (no Claude framing)
- Print transcript path
- Ask "What next?" again with the same options

## Step 5 — Final output

Always show, regardless of exit path:

```
── SUMMARY ──────────────────────────────────────────
• <key disagreement 1>
• <key disagreement 2>
• <outcome: Claude accepted / Grok accepted / Synthesized>
• <1 sentence on what to do next, if relevant>

Transcript saved: /tmp/cross-review-<TS>.md

Want me to apply any of Grok's suggestions?
```

## Cleanup

After any terminal exit branch (A, G, S, or D-final), delete:
- `/tmp/cr-content-$TS.txt`
- `/tmp/cr-rebuttal-*-$TS.txt` (all rounds)
The transcript file (`/tmp/cross-review-$TS.md`) is kept — it's the output artifact.
