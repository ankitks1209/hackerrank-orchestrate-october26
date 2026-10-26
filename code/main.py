"""Run the solver from a checkout: `python3 code/main.py` (the CLI lives in `ghostaudit.cli`)."""
import sys

from ghostaudit.cli import main

if __name__ == "__main__":
    sys.exit(main())
