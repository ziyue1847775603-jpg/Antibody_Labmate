"""Prediction-only ``python -m labmate.run`` convenience entry point."""

from __future__ import annotations

import sys

from labmate.cli import main as cli_main


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    # Keep the established prediction-only convenience invocation intact while
    # allowing the explicit docking handoff to use the same module entry point.
    if arguments and arguments[0] == "dock":
        return cli_main(arguments)
    return cli_main(["predict", *arguments])


if __name__ == "__main__":
    raise SystemExit(main())
