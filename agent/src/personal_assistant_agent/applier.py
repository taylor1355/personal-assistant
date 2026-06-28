"""Host-side proposal applier.

Reads APPROVED proposals from the queue, re-validates each against the closed
schema, applies it via a typed adapter, and records the outcome. This process
holds vault write access; the LLM orchestrator never does — it can only emit
*pending* proposals through the ``propose`` MCP tool. Run as a separate process
(cron or manual), NOT as part of the agent's toolset.

The trust boundary in one sentence: the orchestrator proposes, this applier
disposes. It acts only on files the user flipped to ``status: approved`` (which
the agent cannot write — the queue lives outside the agent's writable area),
and only after ``parse_proposal`` re-validates the file. A bad file is marked
``failed`` and left in place; the sweep never crashes on one proposal.

Adapters implemented: ``vault_edit`` (mode=replace), ``vault_create``,
``vault_move`` (file or folder). Others (vault_edit mode=diff → PA-25,
vault_delete, calendar_*, email_*) are not applied yet — an approved proposal
for one is marked ``failed`` with a reason, not silently skipped.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from personal_assistant_agent.models import (
    Action,
    Mode,
    Proposal,
    ProposalParseError,
    Status,
    parse_proposal,
)
from personal_assistant_agent.tools.vault_read import VaultPathError, is_within, resolve_within

DEFAULT_PROPOSALS_SUBDIR = "00 - Proposals"
_FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{4}-(?P<slug>.+)\.md$")


class ApplyError(Exception):
    """An approved proposal could not be applied. The file is marked ``failed``
    with this message; the rest of the sweep proceeds."""


@dataclass(frozen=True)
class ApplyOutcome:
    filename: str
    status: Status  # applied | failed
    action: str
    detail: str


def sweep(
    proposals_dir: Path,
    vault_root: Path,
    now: datetime,
    *,
    audit_log: Path | None = None,
) -> list[ApplyOutcome]:
    """Apply every approved proposal in ``proposals_dir`` (non-recursive, so the
    ``Applied/`` archive is skipped). Returns one outcome per proposal acted on;
    pending/rejected/applied/failed files are left untouched."""
    outcomes: list[ApplyOutcome] = []
    for path in _candidate_files(proposals_dir):
        try:
            outcome = _process_one(path, proposals_dir, vault_root, now)
        except Exception as e:
            # Broad by design: the sweep is the top-level resilience boundary.
            # A single proposal failing even mid-transition (an unlink or
            # archive write erroring) must not stop the rest of the queue.
            print(f"applier: ERROR processing {path.name}: {e}", file=sys.stderr)
            continue
        if outcome is None:
            continue
        outcomes.append(outcome)
        if audit_log is not None:
            _append_audit(audit_log, outcome, now)
    return outcomes


def _candidate_files(proposals_dir: Path) -> list[Path]:
    if not proposals_dir.is_dir():
        return []
    return sorted(p for p in proposals_dir.glob("*.md") if p.is_file())


def _process_one(
    path: Path, proposals_dir: Path, vault_root: Path, now: datetime
) -> ApplyOutcome | None:
    text = path.read_text(encoding="utf-8")
    if _frontmatter_status(text) is not Status.approved:
        return None  # not ours to act on
    slug = _slug_from_filename(path.name)
    try:
        proposal = parse_proposal(text, slug)
    except (ProposalParseError, ValidationError) as e:
        return _fail(path, "?", f"re-validation failed: {e}", now)
    action = proposal.frontmatter.action.value
    try:
        detail = _apply(proposal, vault_root, proposals_dir)
    except (ApplyError, VaultPathError, OSError) as e:
        return _fail(path, action, str(e), now)
    return _succeed(path, proposals_dir, detail, action, now)


# --- adapters ---


def _apply(proposal: Proposal, vault_root: Path, proposals_dir: Path) -> str:
    action = proposal.frontmatter.action
    if action is Action.vault_edit:
        return _apply_vault_edit(proposal, vault_root, proposals_dir)
    if action is Action.vault_create:
        return _apply_vault_create(proposal, vault_root, proposals_dir)
    if action is Action.vault_move:
        return _apply_vault_move(proposal, vault_root, proposals_dir)
    raise ApplyError(f"no adapter for action '{action.value}' yet")


def _apply_vault_edit(proposal: Proposal, vault_root: Path, proposals_dir: Path) -> str:
    fm = proposal.frontmatter
    if fm.mode is not Mode.replace:
        mode = fm.mode.value if fm.mode else "none"
        raise ApplyError(
            f"vault_edit mode='{mode}' not supported; use mode='replace' "
            "(diff support tracked in PA-25)"
        )
    target = _resolve_target(vault_root, proposals_dir, fm.target)
    if not target.exists():
        raise ApplyError(f"target file does not exist: {fm.target}")
    if target.is_dir():
        raise ApplyError(f"target is a directory, not a file: {fm.target}")
    content = _unwrap_fence(proposal.body.change)
    _atomic_write(target, content)
    return f"replaced {fm.target} ({len(content)} chars)"


def _apply_vault_create(proposal: Proposal, vault_root: Path, proposals_dir: Path) -> str:
    fm = proposal.frontmatter
    target = _resolve_target(vault_root, proposals_dir, fm.target)
    if target.exists():
        raise ApplyError(f"target already exists: {fm.target}")
    content = _unwrap_fence(proposal.body.change)
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(target, content)
    return f"created {fm.target} ({len(content)} chars)"


def _apply_vault_move(proposal: Proposal, vault_root: Path, proposals_dir: Path) -> str:
    fm = proposal.frontmatter
    if not fm.destination:
        raise ApplyError("vault_move requires a destination")
    src = _resolve_target(vault_root, proposals_dir, fm.target)
    if not src.exists():
        raise ApplyError(f"source does not exist: {fm.target}")
    dst = _resolve_target(vault_root, proposals_dir, fm.destination)
    if dst.exists():
        raise ApplyError(f"destination already exists, refusing to overwrite: {fm.destination}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    # shutil.move (not Path.rename) so a vault spanning mount points — a folder
    # symlinked to another drive — falls back to copy+delete instead of EXDEV.
    shutil.move(str(src), str(dst))  # file or whole subtree
    return f"moved {fm.target} -> {fm.destination}"


def _resolve_target(vault_root: Path, proposals_dir: Path, rel: str) -> Path:
    """Confine an adapter's target to the vault, and refuse the proposal queue
    itself (a proposal must not rewrite or approve other proposals)."""
    try:
        path = resolve_within(vault_root, rel)
    except VaultPathError as e:
        raise ApplyError(str(e)) from e
    if is_within(path, proposals_dir.resolve()):
        raise ApplyError(f"refusing to target the proposal queue: {rel}")
    return path


# --- transitions ---


def _succeed(
    path: Path, proposals_dir: Path, detail: str, action: str, now: datetime
) -> ApplyOutcome:
    text = path.read_text(encoding="utf-8")
    archived = _flip_status(text, Status.applied) + _result_block(Status.applied, detail, now)
    dest = proposals_dir / "Applied" / now.strftime("%Y-%m") / path.name
    _atomic_write(dest, archived)
    path.unlink()
    return ApplyOutcome(path.name, Status.applied, action, detail)


def _fail(path: Path, action: str, error: str, now: datetime) -> ApplyOutcome:
    text = path.read_text(encoding="utf-8")
    updated = _flip_status(text, Status.failed) + _result_block(Status.failed, error, now)
    _atomic_write(path, updated)  # left in place for the user to fix / retry
    return ApplyOutcome(path.name, Status.failed, action, error)


def _result_block(status: Status, detail: str, now: datetime) -> str:
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"\n## Result\n\n- {status.value} at {ts}\n- {detail}\n"


def _flip_status(text: str, new_status: Status) -> str:
    """Replace the frontmatter ``status:`` line, leaving the body verbatim.

    Edits only inside the leading ``---`` block, so a ``status:`` line that
    happens to appear in a proposal's file-content body is not touched."""
    out: list[str] = []
    in_fm = False
    flipped = False
    for i, line in enumerate(text.splitlines(keepends=True)):
        bare = line.rstrip("\r\n")
        if i == 0 and bare.strip() == "---":
            in_fm = True
        elif in_fm and bare.strip() == "---":
            in_fm = False
        elif in_fm and not flipped and bare.startswith("status:"):
            newline = line[len(bare):]  # preserve original line ending
            out.append(f"status: {new_status.value}{newline}")
            flipped = True
            continue
        out.append(line)
    return "".join(out)


# --- helpers ---


def _frontmatter_status(text: str) -> Status | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        if line.startswith("status:"):
            # Tolerate valid YAML the user might hand-write: a trailing
            # `# comment` and surrounding quotes. Getting this wrong would
            # silently skip an approved proposal.
            value = line[len("status:") :].split("#", 1)[0].strip().strip("'\"")
            try:
                return Status(value)
            except ValueError:
                return None
    return None


def _slug_from_filename(name: str) -> str:
    match = _FILENAME_RE.match(name)
    if match:
        return match.group("slug")
    return name[:-3] if name.endswith(".md") else name


def _unwrap_fence(change: str) -> str:
    """Return the inner content of a single fenced code block, else the text
    as-is. vault_create / vault_edit replace bodies wrap the file content in a
    fence per PROPOSAL_FORMAT; the file on disk should not include it.

    Matches the closing fence by character and length, so a longer outer fence
    (```` wrapping a note that itself contains a ``` block) unwraps correctly
    and only strips the outer pair."""
    stripped = change.strip()
    if not (stripped.startswith("```") or stripped.startswith("~~~")):
        return change
    lines = stripped.splitlines()
    if len(lines) < 2:
        return change
    opener = lines[0].strip()
    char = opener[0]
    open_len = len(opener) - len(opener.lstrip(char))
    closer = lines[-1].strip()
    if closer and set(closer) == {char} and len(closer) >= open_len:
        return "\n".join(lines[1:-1])
    return change


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Preserve the existing file's mode across the replace — mkstemp creates
    # the temp file 0o600, which would otherwise silently tighten an edited
    # vault file's permissions.
    original_mode: int | None = None
    if path.exists():
        try:
            original_mode = path.stat().st_mode
        except OSError:
            original_mode = None
    fd, tmp_str = tempfile.mkstemp(prefix=".apply-", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if original_mode is not None:
            try:
                os.chmod(tmp, original_mode)
            except OSError:
                pass
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _append_audit(audit_log: Path, outcome: ApplyOutcome, now: datetime) -> None:
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts}\t{outcome.status.value}\t{outcome.action}\t{outcome.filename}\t{outcome.detail}\n"
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    with audit_log.open("a", encoding="utf-8", newline="\n") as f:
        f.write(line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply approved proposals from the queue.")
    parser.add_argument("--vault-root", default=os.environ.get("VAULT_ROOT"))
    parser.add_argument(
        "--proposals-dir",
        default=None,
        help=f"defaults to <vault-root>/{DEFAULT_PROPOSALS_SUBDIR}",
    )
    args = parser.parse_args(argv)
    if not args.vault_root:
        parser.error("--vault-root (or VAULT_ROOT) is required")

    vault_root = Path(args.vault_root).expanduser()
    proposals_dir = (
        Path(args.proposals_dir).expanduser()
        if args.proposals_dir
        else vault_root / DEFAULT_PROPOSALS_SUBDIR
    )
    outcomes = sweep(
        proposals_dir, vault_root, datetime.now(UTC), audit_log=proposals_dir / "audit.log"
    )
    for o in outcomes:
        print(f"applier: {o.status.value} {o.filename}: {o.detail}")
    applied = sum(1 for o in outcomes if o.status is Status.applied)
    failed = sum(1 for o in outcomes if o.status is Status.failed)
    print(f"applier: swept {proposals_dir} — {applied} applied, {failed} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
