"""Set datum up on this host. See `bootstrap.py --help`."""

import sys

from datum.setup import Installer, Options


def main(argv: list[str] | None = None) -> None:
    Installer(Options.from_argv(argv)).run()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as refused:
        # These messages are written for whoever ran the script; a traceback
        # would only bury them.
        print(f"\n{refused}", file=sys.stderr)
        raise SystemExit(1) from None
