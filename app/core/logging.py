import logging
import logging.config
from typing import Any, Dict


def setup_logging(*, debug: bool = False) -> None:
    config: Dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "level": "DEBUG" if debug else "INFO",
            "handlers": ["console"],
        },
        "loggers": {
            "uvicorn": {"level": "INFO"},
            "sqlalchemy.engine": {"level": "WARNING" if not debug else "INFO"},
        },
    }
    logging.config.dictConfig(config)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
