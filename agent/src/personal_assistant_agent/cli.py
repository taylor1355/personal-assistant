from __future__ import annotations

import typer

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
def version() -> None:
    from personal_assistant_agent import __version__

    typer.echo(__version__)


if __name__ == "__main__":
    app()
