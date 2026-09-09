"""Logging estructurado con campos permitidos; nunca cuerpos/credenciales."""
import json
import logging

LOGGER = logging.getLogger("dfsha")
SAFE_FIELDS = {"listener", "request_id", "bytes", "chunks", "code", "version", "pid"}


def configure() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def event(name: str, **fields: object) -> None:
    if set(fields) - SAFE_FIELDS:
        raise ValueError("Campo de log no autorizado")
    LOGGER.info(json.dumps({"event": name, **fields}, sort_keys=True))
