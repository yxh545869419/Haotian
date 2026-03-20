"""CLI entrypoint for the Haotian application."""

from haotian.cli.commands import app


def main() -> None:
    """Execute the Haotian CLI application."""

    app()


if __name__ == "__main__":
    main()
