# auto-research

A small, maintainable auto-research framework that uses the local `codex` CLI as the execution engine.

## What it does

- Launches a Codex agent for a given workspace.
- Passes workspace, model, and reasoning effort explicitly to the launch command.
- Creates and preserves a shared report directory at `workspace/auto-research-reports/`.
- Treats `SKILL.md`, `TASK.md`, `IDEAS.md`, and `ITERATION.md` as shared state between the user and the agent.
- Persists runner state to disk and automatically resumes the Codex session after unexpected exits when possible.

## Shared report files

The framework creates these files under `workspace/auto-research-reports/`:

- `SKILL.md`: the working method for the auto-research agent
- `TASK.md`: the final goal and the current optimization target
- `IDEAS.md`: candidate improvements worth considering
- `ITERATION.md`: concise per-iteration impact records

Both the user and the agent may edit these files. The generated prompt tells the agent to reread and maintain them continuously.

## Runtime files

The framework stores its own runtime state under:

- `workspace/auto-research-reports/.auto-research/state.json`
- `workspace/auto-research-reports/.auto-research/runner.lock`
- `workspace/auto-research-reports/.auto-research/last_message.txt`

## Install

```bash
cd auto-research
pip install -e .
```

## Commands

Initialize the shared report files:

```bash
auto-research init --workspace /path/to/workspace
```

`init` is non-destructive. It only creates missing report files and keeps any existing markdown files unchanged.

Start a fresh or resumable auto-research run:

```bash
auto-research run \
  --workspace /path/to/workspace \
  --model gpt-5.4 \
  --reasoning-effort high
```

Before `run` or `resume`, the CLI checks that `SKILL.md`, `TASK.md`, `IDEAS.md`, and `ITERATION.md` all exist. `TASK.md` must be filled with real content before the run starts. `IDEAS.md` may stay on the default scaffold initially, and `SKILL.md` / `ITERATION.md` may also start from the generated template.

Resume the latest unfinished session for the workspace:

```bash
auto-research resume --workspace /path/to/workspace
```

Inspect the persisted runner state:

```bash
auto-research status --workspace /path/to/workspace
```

## Launch behavior

Fresh runs use `codex exec` and include:

- `-C <workspace>`
- `-m <model>`
- `-c model_reasoning_effort="<effort>"`

By default the runner also adds `--full-auto` and `-s workspace-write`.

Resume runs use `codex exec resume <session_id>` and carry the same model and reasoning-effort settings.

## Recovery model

The runner has two recovery layers:

1. In-process recovery: if `codex` exits unexpectedly and the session id can be located from the local Codex session store, the runner will automatically call `codex exec resume`.
2. Next-start recovery: if the runner itself was interrupted, the saved `state.json` still keeps the last known session id, so `auto-research run` or `auto-research resume` can continue later.

## Limits

- If both the runner and `codex` are killed before any session metadata is persisted by Codex, there may be nothing to resume.
- The framework is intentionally simple: it does not try to parse live Codex event streams or rewrite your report files structurally.
