# Autonomous Flywheel Daemon

Periodic autonomous runner for Flywheel graphs using local `codex exec` session auth.

## Preconditions

- `codex` CLI installed
- `codex login status` returns `Logged in`
- Flywheel MCP configured and authenticated in your Codex environment

## Run Once

```bash
python3 automation/auto_research_daemon.py \
  --root-node-id <ROOT_NODE_ID> \
  --once
```

## Run Continuously

```bash
python3 automation/auto_research_daemon.py \
  --root-node-id <ROOT_NODE_ID> \
  --approval-policy never \
  --poll-seconds 180
```

## Core Behavior Contract

- Uses `$flywheel` skill each cycle
- Runs mandatory preflight before task execution
- Task execution protocol:
  - candidates: `task:new` or `task:running`
  - excludes: `task:done`, `task:failed`, `task:verified`, `protected`
  - scheduling: `task:running` first, then promote `task:new` -> `task:running`
- Verification protocol:
  - candidates: `task:done` and not `task:verified`
  - requires explicit `Completion Criterion` on task node
  - creates separate `verification:report` node
  - verifier attempts reproduction from task description + artifacts
  - if pass: `task:done` -> `task:verified`
  - if fail: `task:done` -> `task:running` with fix notes
- Protected protocol:
  - `protected` nodes are never mutated
- Topology integrity:
  - no detached standalone nodes
  - newly created non-root nodes must be connected to the current root lineage
- Waiting protocol:
  - `awaiting-user-input` used only for strategic blockers

## Logs

- JSONL: `artifacts/auto_research_daemon.log.jsonl`

## Single-Instance Safety

Default lock file:

- `/tmp/auto_research_daemon.lock`

If lock is busy, a second runner exits unless `--wait-lock` is set.

## systemd (user) example

```ini
[Unit]
Description=Auto Research Daemon (Flywheel)
After=default.target

[Service]
Type=simple
WorkingDirectory=%h/flywheel-reseacrh-workflow
ExecStart=/usr/bin/python3 %h/flywheel-reseacrh-workflow/automation/auto_research_daemon.py --root-node-id <ROOT_NODE_ID> --model gpt-5.3-codex --poll-seconds 180 --approval-policy never --log-file artifacts/auto_research_daemon.log.jsonl
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```
