#!/usr/bin/env python3
"""Entry point used by the mise tasks (``python3 .devkit/mise/scripts/xenoide_dev.py``)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from xenoide_dev.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
