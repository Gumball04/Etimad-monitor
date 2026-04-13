import io
import logging
import os
import sys


_SAFE_STDOUT = None


def _get_safe_stdout():
    global _SAFE_STDOUT
    if _SAFE_STDOUT is not None:
        return _SAFE_STDOUT

    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        _SAFE_STDOUT = sys.stdout
    else:
        _SAFE_STDOUT = io.TextIOWrapper(buffer, encoding="utf-8", errors="replace", line_buffering=True)
    return _SAFE_STDOUT


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    level_name = os.getenv("LOG_LEVEL", "").upper()
    if not level_name:
        try:
            from app.core.config import settings

            level_name = settings.log_level.upper()
        except Exception:
            level_name = "INFO"
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)

    handler = logging.StreamHandler(_get_safe_stdout())
    handler.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger
