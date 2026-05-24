import typer

app = typer.Typer(
    name="job-hunter",
    help="The CLI for the job hunter AI Agent",
    pretty_exceptions_show_locals=False,
    pretty_exceptions_enable=False,
)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Job hunter AI agent."""
    if ctx.invoked_subcommand is not None:
        return

    print("Hello, World!")

def run_app() -> None:
    app()