"""
logger.py — SolveX v2
──────────────────────
Structured logging using structlog.
Every agent logs with context: agent name, iteration, AI used.
"""

import structlog
import logging
from config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(message)s",
)

# NOTE: `structlog.stdlib.*` processors (add_logger_name, filter_by_level, etc.)
# expect a stdlib-backed logger. Pairing them with `PrintLoggerFactory` crashes
# with `AttributeError: 'PrintLogger' object has no attribute ...` on the
# structlog version pinned in requirements.txt. Using plain (non-stdlib)
# processors here keeps the same console output without that mismatch.
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="%H:%M:%S"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.log_level.upper(), logging.INFO)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

log = structlog.get_logger("solvex")
