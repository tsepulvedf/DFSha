"""Logging estructurado con campos permitidos; nunca cuerpos/credenciales."""
import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER = logging.getLogger("dfsha")
SAFE_FIELDS = {"listener", "request_id", "bytes", "chunks", "code", "version", "pid", "actor", "action", "resource"}


def configure(path=None) -> None:
    if path is not None:
        from dfsha.control.auth import protect
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        protect(path.parent)
        for handler in LOGGER.handlers:
            handler.close()
        LOGGER.handlers.clear()
        handler = RotatingFileHandler(path, maxBytes=5*1048576, backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(message)s'))
        LOGGER.addHandler(handler)
        LOGGER.setLevel(logging.INFO)
        LOGGER.propagate = False
        return
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def event(name: str, **fields: object) -> None:
    if set(fields) - SAFE_FIELDS:
        raise ValueError("Campo de log no autorizado")
    LOGGER.info(json.dumps({"time": datetime.now(timezone.utc).isoformat(), "event": name, **fields}, sort_keys=True))
