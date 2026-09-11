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


class DistributedMetadataStore(Protocol):
    def get(self, key: str) -> Record | None: ...
    def page(self, prefix: str, cursor: str, limit: int) -> tuple[list[Record], str]: ...
    def commit(self, conditions: CommitConditions, changes: Mapping[str, bytes | None],
               *, request_id: str, intent_digest: bytes) -> int:
        """CAS atómico con resultado idempotente o conflicto, nunca éxito parcial."""
        ...


class DistributedCoordinator(Protocol):
    def acquire(self, resource_keys: tuple[str, ...], owner: str, ttl: int) -> Record: ...
    def renew(self, fence: Record, ttl: int) -> Record: ...
    def release(self, fence: Record) -> None: ...


class DistributedBlockStore(Protocol):
    def put_immutable(self, block_id: str, chunks: Iterable[bytes], size: int,
                      expected_sha256: bytes) -> Record:
        """Recibo solo después de verificar integridad y persistencia durable."""
        ...
    def read_verified(self, block_id: str, offset: int, length: int) -> Iterator[bytes]: ...
    def delete_retired(self, block_id: str, retirement_revision: int) -> None: ...


class DistributedAuthorizer(Protocol):
    def authenticate(self, credentials: bytes) -> str: ...
    def require(self, subject: str, resource: str, action: str) -> int: ...
    def require_block(self, subject: str, capability: bytes, block_id: str,
                      node_id: str, offset: int, length: int, action: str) -> int: ...


# Puertos ejercidos por H1. Los Distributed* anteriores conservan el objetivo
# E4/E7, sin afirmar que SQLite pueda convertirse en etcd cambiando una URL.
class MetadataStore(Protocol):
    def transaction(self, write=False): ...


class Coordinator(Protocol):
    def admit(self, block_size, seconds=5): ...


class LeaseAuthority(Protocol):
    """Fencing comprobado dentro de la UoW autoritativa, sustituible en E7."""
    def acquire(self, tx, handle, indices=(), whole=False, size=False, automatic=False): ...
    def validate(self, tx, session, fence): ...
    def live(self, record): ...
    def release_operation(self, tx, operation): ...


class BlockStore(Protocol):
    def put(self, block, chunks): ...
    def read_verified(self, block): ...
    def pin(self, block_id, exclusive=False): ...
    def collect(self, retained): ...


class Authorizer(Protocol):
    def authenticate(self, tx, token): ...
    def require(self, tx, user, node, bits): ...
    def capability(self, user_id, binding, block_id, action): ...


class Placement(Protocol):
    def location(self): ...
