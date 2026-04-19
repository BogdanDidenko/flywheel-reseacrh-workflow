# Flywheel Research Workflow

Generic autonomous workflow scaffold for Flywheel graphs.

This repository contains:
- an autonomous daemon (`codex exec` + `$flywheel`) for periodic graph progression,
- a strict task/verification protocol,
- practical workflow recommendations for collaborative research execution.

No project-specific reproduction task content is included.

## Structure

- `automation/auto_research_daemon.py` - periodic autonomous runner
- `automation/cycle_output.schema.json` - strict JSON output schema for each cycle
- `automation/README.md` - operational guide (run modes, contracts, lock safety)
- `docs/workflow_recommendations.md` - generic team workflow recommendations

## Quick Start

1. Install and login Codex CLI.
2. Configure a Flywheel root node id.
3. Run one cycle:

```bash
python3 automation/auto_research_daemon.py \
  --root-node-id <ROOT_NODE_ID> \
  --once
```

4. Run continuously:

```bash
python3 automation/auto_research_daemon.py \
  --root-node-id <ROOT_NODE_ID> \
  --approval-policy never \
  --poll-seconds 180
```
