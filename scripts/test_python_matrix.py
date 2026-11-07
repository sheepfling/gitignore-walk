"""Run the local Windows interpreter test matrix."""

from __future__ import annotations

import sys

from scripts.ci import main

if __name__ == "__main__":
    raise SystemExit(main(["local", "--skip-linux", *sys.argv[1:]]))
