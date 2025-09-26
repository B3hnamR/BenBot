import logging
import sys
from typing import Any

import orjson
import structlog
from structlog.stdlib import BoundLogger


def _resolve_level(level_name: str) -> int:
    normalized = level_name.upper()
    if normalized not in logging.getLevelNamesMapping():
        return logging.INFO
    resolved = logging.getLevelName(normalized)
    return resolved if isinstance(resolved, int) else logging.INFO


def _orjson_dumps(
    obj: Any,
    *,
    default: Any | None = None,
    option: int | None = None,
    **_: Any,
) -> str:
    dump_kwargs: dict[str, Any] = {
        "option": orjson.OPT_NON_STR_KEYS if option is None else option | orjson.OPT_NON_STR_KEYS
    }
    if default is not None:
        dump_kwargs["default"] = default
    return orjson.dumps(obj, **dump_kwargs).decode()


def configure_logging(level_name: str) -> None:
    level = _resolve_level(level_name)

    logging.basicConfig(level=level, format="%(message)s", stream=sys.stdout)

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(serializer=_orjson_dumps),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(*args: Any, **kwargs: Any) -> BoundLogger:
    return structlog.get_logger(*args, **kwargs)