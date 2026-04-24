from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import typer

from personal_assistant_agent.models import (
    Action,
    Mode,
    Proposal,
    ProposalBody,
    ProposalFrontmatter,
)
from personal_assistant_agent.tools.proposal_enqueue import enqueue

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def wake(
    reason: str = typer.Option(..., "--reason", help="Why the agent is waking up."),
) -> None:
    """Wake the agent with a named trigger.

    v0 entrypoint. The root agent is not yet wired; this prints the trigger
    and exits. Real dispatch lands in the next commit.
    """
    typer.echo(f"agent: wake reason={reason!r} — root not yet implemented")


@app.command()
def propose(
    agent: str = typer.Option(..., help="Subagent name, e.g. journal_agent"),
    action: Action = typer.Option(..., case_sensitive=False),
    target: str = typer.Option(..., help="File path, event ID, etc."),
    intent: str = typer.Option(..., help="One-sentence description for the user."),
    reasoning: str = typer.Option(..., help="Why this is being proposed now."),
    change: str = typer.Option(..., help="Diff or payload. Pass @path to read from a file."),
    slug: str = typer.Option(..., help="Kebab-case, <=40 chars."),
    mode: Mode | None = typer.Option(None, case_sensitive=False),
    notes: str | None = typer.Option(None, help="Optional. Pass @path to read from a file."),
    proposals_dir: Path | None = typer.Option(
        None, "--proposals-dir", help="Override PROPOSALS_PATH / default."
    ),
) -> None:
    """Manually enqueue a proposal. Useful for testing the executor pipeline."""
    proposal = Proposal(
        frontmatter=ProposalFrontmatter(
            proposed_at=datetime.now(timezone.utc),
            agent=agent,
            action=action,
            target=target,
            mode=mode,
        ),
        body=ProposalBody(
            intent=intent,
            reasoning=reasoning,
            change=_read_maybe_file(change),
            notes=_read_maybe_file(notes) if notes else None,
        ),
        slug=slug,
    )
    path = enqueue(proposal, proposals_dir=proposals_dir)
    typer.echo(str(path))


@app.command()
def version() -> None:
    from personal_assistant_agent import __version__

    typer.echo(__version__)


def _read_maybe_file(value: str) -> str:
    """Resolve ``@path`` style arguments against the filesystem.

    Typer passes the literal flag value. Supporting ``@path`` here keeps
    diffs and long payloads out of the shell-quoting escape game.
    """
    if value.startswith("@"):
        return Path(value[1:]).read_text(encoding="utf-8")
    return value


if __name__ == "__main__":
    app()
