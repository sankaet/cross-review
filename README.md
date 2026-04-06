# cross-review

Cross-model review and debate for Claude Code. Send any Claude output to Grok for independent critique, then run an interactive debate until you're satisfied.

## Install

```bash
claude plugin install cross-review@<your-github-username>
```

## Requirements

```bash
export XAI_API_KEY=xai-...
```

## Usage

```
/cross-review              # asks which context to review
/cross-review --last       # review Claude's last response
/cross-review --full       # review full session
/cross-review --file path  # review a specific file
/cross-review --raw        # D-mode: raw Grok output every round
```

## Debate controls

After each round: `[C]` continue · `[G]` accept Grok · `[A]` accept Claude · `[S]` synthesize · `[D]` show raw

## Models

- Critic: `grok-4.20-reasoning` (auto-upgrades)
- Judge/Synthesizer: `grok-4.20-multi-agent` (auto-upgrades)

Model IDs are resolved dynamically at startup and cached for 24h at `~/.claude/cross-review-models.json`.

## Cost

$2 input / $6 output per million tokens (xAI pricing, April 2026).
