#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "gpt-5.3-codex"
DEFAULT_POLL_SECONDS = 90


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Periodic autonomous Flywheel runner. "
            "Uses local codex login (ChatGPT session), not direct API-key calls."
        )
    )
    parser.add_argument("--root-node-id", required=True, help="Flywheel graph root node id.")
    parser.add_argument(
        "--control-node-id",
        default="",
        help="Optional control node id with run contract. If empty, runner infers from root.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Codex model for codex exec (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=DEFAULT_POLL_SECONDS,
        help=f"Sleep interval between cycles (default: {DEFAULT_POLL_SECONDS}).",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=0,
        help="Max cycles before exit (0 = infinite).",
    )
    parser.add_argument(
        "--sandbox",
        choices=["read-only", "workspace-write", "danger-full-access"],
        default="danger-full-access",
        help="Sandbox mode for codex exec.",
    )
    parser.add_argument(
        "--approval-policy",
        choices=["untrusted", "on-failure", "on-request", "never"],
        default="never",
        help="Approval policy for codex command execution (default: never).",
    )
    parser.add_argument(
        "--green-tag-name",
        default="awaiting-user-input",
        help="Name of green graph tag that marks leaves waiting for user.",
    )
    parser.add_argument(
        "--green-bg",
        default="#22C55E",
        help="Background color for waiting tag.",
    )
    parser.add_argument(
        "--green-text",
        default="#052E16",
        help="Text color for waiting tag.",
    )
    parser.add_argument(
        "--protected-tag-name",
        default="protected",
        help="Name of graph tag for nodes excluded from daemon work.",
    )
    parser.add_argument(
        "--protected-bg",
        default="#7F1D1D",
        help="Background color for protected tag.",
    )
    parser.add_argument(
        "--protected-text",
        default="#FEE2E2",
        help="Text color for protected tag.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run exactly one cycle.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated prompt and exit.",
    )
    parser.add_argument(
        "--log-file",
        default="artifacts/auto_research_daemon.log.jsonl",
        help="JSONL execution log path.",
    )
    parser.add_argument(
        "--lock-file",
        default="/tmp/auto_research_daemon.lock",
        help="Single-instance lock file path.",
    )
    parser.add_argument(
        "--wait-lock",
        action="store_true",
        help="Wait for existing runner lock instead of exiting immediately.",
    )
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_codex_ready() -> None:
    if not shutil.which("codex"):
        raise RuntimeError("codex CLI not found in PATH.")
    proc = subprocess.run(
        ["codex", "login", "status"],
        text=True,
        capture_output=True,
        check=False,
    )
    merged = f"{proc.stdout}\n{proc.stderr}"
    if proc.returncode != 0 or "Logged in" not in merged:
        raise RuntimeError(
            "codex login session not available. Run `codex login` first."
        )


def build_cycle_prompt(args: argparse.Namespace) -> str:
    control_line = (
        f"- Control node id: {args.control_node_id}"
        if args.control_node_id
        else "- Control node id: infer from root graph context."
    )
    return f"""
Use $flywheel skill for this cycle.

You are running one autonomous Flywheel cycle.

Hard scope:
- Root node id: {args.root_node_id}
{control_line}

Task intake contract (strict):
- Task candidates are ONLY nodes that satisfy:
  1) contains `task:new` OR `task:running`
  2) does NOT contain `task:done`
  3) does NOT contain `task:failed`
  4) does NOT contain `task:verified`
  5) does NOT contain `{args.protected_tag_name}`
- Scheduling rule:
  1) Prefer nodes already tagged `task:running`.
  2) If no `task:running` node exists, pick one `task:new`, immediately retag it to
     `task:running`, then execute.
  3) Do not keep a claimed executable task as `task:new` only.
- Ignore all non-candidate tasks.

Task verification contract (strict):
- Verification candidates are ONLY nodes that satisfy:
  1) contains `task:done`
  2) does NOT contain `task:verified`
  3) does NOT contain `{args.protected_tag_name}`
- Use dedicated verification tag `verification:report` for verification nodes.
- Ensure `verification:report` tag exists on root with colors:
  - bg_color: #0F766E
  - text_color: #ECFEFF
- Each task node MUST have explicit `Completion Criterion` in node content.
- If criterion is missing on a task candidate, backfill it first before execution.
- Verification rule:
  1) For each `task:done`, create a separate verification node (kind `empirical`) tagged
     `verification:report`, linked only to the verified task node.
  2) Verifier must attempt reproduction of results from task description + attached artifacts
     before deciding pass/fail. Record commands, environment, observed outputs, and diffs.
  3) Verification node must be terminal and non-continuable:
     - exactly one parent edge (the verified task),
     - no additional parents,
     - no child edges.
  4) If criterion is satisfied, retag task node from `task:done` to `task:verified`.
  5) If criterion is NOT satisfied, retag task node from `task:done` to `task:running`
     and write explicit verification feedback (what failed and what to fix) into task content.

Protected-node contract (hard):
- Use graph tag `{args.protected_tag_name}` for nodes excluded from automation.
- Ensure this tag exists on root with colors:
  - bg_color: {args.protected_bg}
  - text_color: {args.protected_text}
- Never work on protected nodes:
  - do NOT claim tasks on protected nodes
  - do NOT edit content/tags/artifacts/executions on protected nodes
  - do NOT branch from, merge into, or reparent protected nodes
- If an action candidate touches a protected node, skip it and choose another branch.

Topology integrity contract (hard):
- Do NOT create detached standalone nodes during autonomous execution.
- Every non-root node created in this cycle must be connected to the current root graph
  via explicit parent linkage at creation time.
- Allowed exception: intentional independent root nodes only when explicitly requested by user.
- Post-write check (same cycle):
  1) inspect all newly created node ids,
  2) ensure each has at least one parent in the current graph root lineage,
  3) if detached, immediately fix by adding correct parent edge or delete duplicate detached node.

Waiting-for-user contract:
- Use graph tag `{args.green_tag_name}` as waiting state.
- Ensure this tag exists on root with colors:
  - bg_color: {args.green_bg}
  - text_color: {args.green_text}
- Treat `{args.green_tag_name}` as a BLOCKING state for critical strategic unknowns only.
- Do NOT place `{args.green_tag_name}` after each node or for routine uncertainty.
- Use `{args.green_tag_name}` only when user input is required to choose strategic direction and
  safe autonomous continuation is not possible.
- Do not use another color/tag for waiting state unless explicitly overridden.

Execution behavior for THIS cycle:
1) Run mandatory preflight BEFORE task execution:
   - inspect installed Python packages (pip inventory),
   - inspect available skills,
   - inspect available MCP tools/connectors,
   - verify Python code execution capability,
   - verify package-install capability (pip install path),
   - if needed, install missing pip packages/skills/MCP required for the task.
2) Read graph context from root.
3) Claim and execute task work with this priority:
   - first verification queue (`task:done` -> verify -> `task:verified` or back to `task:running`),
   - then `task:running`,
   - then `task:new` (retag to `task:running` before execution).
4) If no candidate tasks, continue obvious autonomous next branch if justified by control contract.
5) If there are multiple plausible hypotheses, prefer autonomous exploration:
   - spawn parallel sub-agents/branches to test several hypotheses,
   - collect evidence,
   - merge/synthesize results into a higher-level decision node.
6) Escalate to `{args.green_tag_name}` ONLY for critical strategic blockers.
7) Keep changes graph-local and auditable.

Stop criterion for THIS cycle:
- End cycle when one meaningful unit of progress is done, or when no safe progress is possible now.

Return ONLY a JSON object matching schema with:
- preflight
- cycle_status
- all_leaves_green
- eligible_task_new_count (count of `task:new` backlog seen at cycle start)
- protected_nodes_touched_count (must be 0)
- actions
- notes
- updated_node_ids (use [] when none)
- protected_nodes_skipped (use [] when none)
- waiting_decision (use null when not waiting_for_user)
- hypothesis_strategy (use null when not progress_made)
""".strip()


def run_one_cycle(args: argparse.Namespace, schema_path: Path) -> tuple[int, str, str]:
    prompt = build_cycle_prompt(args)
    with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as tmp:
        output_last_message_path = tmp.name

    cmd = [
        "codex",
        "-a",
        args.approval_policy,
        "exec",
        "--model",
        args.model,
        "--sandbox",
        args.sandbox,
        "--skip-git-repo-check",
        "--cd",
        str(Path.cwd()),
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        output_last_message_path,
        "-",
    ]

    proc = subprocess.run(
        cmd,
        input=prompt,
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        message = Path(output_last_message_path).read_text(encoding="utf-8")
    except Exception:
        message = ""
    Path(output_last_message_path).unlink(missing_ok=True)
    return proc.returncode, message.strip(), (proc.stderr or "").strip()


def append_log(log_path: Path, row: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def should_stop(result: dict[str, Any]) -> bool:
    status = result.get("cycle_status")
    if status == "all_leaves_green":
        return True
    if status == "waiting_for_user":
        waiting = result.get("waiting_decision")
        if isinstance(waiting, dict):
            return bool(waiting.get("is_strategic_blocker", False))
        return False
    return bool(result.get("all_leaves_green", False)) and int(
        result.get("eligible_task_new_count", 0)
    ) == 0


def acquire_single_instance_lock(lock_path: Path, wait: bool) -> Any:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fp = lock_path.open("a+", encoding="utf-8")
    lock_flags = fcntl.LOCK_EX
    if not wait:
        lock_flags |= fcntl.LOCK_NB
    try:
        fcntl.flock(lock_fp.fileno(), lock_flags)
    except BlockingIOError:
        lock_fp.close()
        raise RuntimeError(
            f"Another runner is active (lock busy): {lock_path}. "
            "Use --wait-lock to wait."
        )
    lock_fp.seek(0)
    lock_fp.truncate()
    lock_fp.write(json.dumps({"pid": str(os.getpid()), "started_at_utc": utc_now()}))
    lock_fp.flush()
    return lock_fp


def main() -> int:
    args = parse_args()
    try:
        ensure_codex_ready()
        schema_path = Path("automation/cycle_output.schema.json")
        if not schema_path.exists():
            raise RuntimeError(f"Schema not found: {schema_path}")

        lock_fp = acquire_single_instance_lock(Path(args.lock_file), wait=args.wait_lock)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 2

    try:
        if args.dry_run:
            print(build_cycle_prompt(args))
            return 0

        log_path = Path(args.log_file)
        cycle = 0
        while True:
            cycle += 1
            started = utc_now()
            code, out, err = run_one_cycle(args, schema_path=schema_path)

            log_row: dict[str, Any] = {
                "ts_utc": started,
                "cycle": cycle,
                "exit_code": code,
            }
            parsed: dict[str, Any] | None = None
            if out:
                try:
                    parsed = json.loads(out)
                    log_row["result"] = parsed
                except json.JSONDecodeError:
                    log_row["raw_output"] = out
            if err:
                log_row["stderr"] = err
            append_log(log_path, log_row)

            if code != 0:
                if args.once:
                    return code
                time.sleep(args.poll_seconds)
                if args.max_cycles and cycle >= args.max_cycles:
                    return 1
                continue

            if parsed and should_stop(parsed):
                print(json.dumps({"stopped": True, "cycle": cycle, "result": parsed}, ensure_ascii=False))
                return 0

            if args.once:
                print(json.dumps({"stopped": False, "cycle": cycle, "result": parsed}, ensure_ascii=False))
                return 0

            if args.max_cycles and cycle >= args.max_cycles:
                print(json.dumps({"stopped": False, "reason": "max_cycles_reached", "cycle": cycle}, ensure_ascii=False))
                return 0

            time.sleep(args.poll_seconds)
    finally:
        lock_fp.close()


if __name__ == "__main__":
    raise SystemExit(main())
