"""``python -m governance_sentinel``."""

from __future__ import annotations

import logging
import sys

from governance_sentinel.cli import main

logger = logging.getLogger(__name__)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Fatal error during execution.")
        sys.exit(1)
