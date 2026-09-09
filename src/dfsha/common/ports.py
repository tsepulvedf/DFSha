"""Puertos de arquitectura, sin adaptadores de negocio implementados en E2.

Las condiciones de revisión, fencing y tombstone deben validarse DENTRO del
commit del MetadataStore; una consulta previa a Coordinator no las sustituye.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Record:
    key: str
    value: bytes
    revision: int


@dataclass(frozen=True)
class CommitConditions:
    revisions: Mapping[str, int]
    live_fence_keys: Mapping[str, int]
    service_epoch: str
    file_id: str
    content_epoch: int


class MetadataStore(Protocol):
    def get(self, key: str) -> Record | None: ...
    def page(self, prefix: str, cursor: str, limit: int) -> tuple[list[Record], str]: ...
    def commit(self, conditions: CommitConditions, changes: Mapping[str, bytes | None],
               *, request_id: str, intent_digest: bytes) -> int:
        """CAS atómico con resultado idempotente o conflicto, nunca éxito parcial."""
        ...


class Coordinator(Protocol):
    def acquire(self, resource_keys: tuple[str, ...], owner: str, ttl: int) -> Record: ...
    def renew(self, fence: Record, ttl: int) -> Record: ...
    def release(self, fence: Record) -> None: ...


class BlockStore(Protocol):
    def put_immutable(self, block_id: str, chunks: Iterable[bytes], size: int,
                      expected_sha256: bytes) -> Record:
        """Recibo solo después de verificar integridad y persistencia durable."""
        ...
    def read_verified(self, block_id: str, offset: int, length: int) -> Iterator[bytes]: ...
    def delete_retired(self, block_id: str, retirement_revision: int) -> None: ...


class Authorizer(Protocol):
    def authenticate(self, credentials: bytes) -> str: ...
    def require(self, subject: str, resource: str, action: str) -> int: ...
    def require_block(self, subject: str, capability: bytes, block_id: str,
                      node_id: str, offset: int, length: int, action: str) -> int: ...
