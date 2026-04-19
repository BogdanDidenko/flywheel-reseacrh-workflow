# Workflow Recommendations (Generic)

This guide describes a stable, reusable workflow for autonomous and collaborative Flywheel execution.

## 1) Node Types

- `insight`: decisions, synthesis, interpretation
- `empirical`: experiments, measurements, verification reports
- `untyped`: temporary task/control nodes

## 2) Task State Tags

Recommended state machine:

- `task:new` -> backlog
- `task:running` -> active execution
- `task:done` -> execution complete, awaiting verification
- `task:verified` -> completion criterion validated
- `task:failed` -> terminal failure

Allowed transitions:

- `task:new -> task:running`
- `task:running -> task:done | task:failed`
- `task:done -> task:verified`
- `task:done -> task:running` (verification failed)

## 3) Mandatory Completion Criterion

Each task node should include explicit `Completion Criterion` section.

The verifier must evaluate `task:done` only against this criterion.

## 4) Verification Node Pattern

For every verification event, create a separate node:

- kind: `empirical`
- tag: `verification:report`
- parent: exactly one verified task node
- children: none (terminal node)

Verification report should include:

- reproduction attempt method
- commands/environment
- observed outputs
- criterion-by-criterion pass/fail
- final verdict

## 5) Topology Integrity

- Do not create detached standalone nodes in autonomous cycles
- Every new non-root node must be linked into current root lineage
- If detached node appears, fix immediately (attach or delete)

## 6) Protected and Waiting Policies

- `protected`: hard exclude from autonomous mutation
- `awaiting-user-input`: strategic blocker only (not routine uncertainty)

## 7) Collaboration and Sharing

Flywheel access is node-based.

To share an entire graph in practice:

1. Read full node tree from root
2. Apply one access policy to all node ids via bulk sharing
3. Re-check sharing state after mutation

Typical collaborator roles:

- `viewer`
- `editor`
- `admin`

## 8) Operational Guardrails

- preflight each cycle: pip inventory, skills, MCP access, python execution
- enforce single-runner lock
- keep cycle outputs schema-constrained and auditable
- prefer parallel hypothesis branches, then merge evidence
