from __future__ import annotations

import logging


def get_logger(name: str):
    try:
        from novamind.core.middleware.structured_logging import get_logger as structured_get_logger

        return structured_get_logger(name)
    except Exception:
        return logging.getLogger(name)
