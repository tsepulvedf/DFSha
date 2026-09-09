"""Comprobar presupuestos wire de las estructuras que crecerán con bloques/réplicas."""
from uuid import uuid4

from dfsha.common.limits import BLOCK_BYTES, MESSAGE_BYTES, WRITE_BYTES
from dfsha.v1 import common_pb2 as common, control_pb2 as control


def test_manifest_page_and_maximum_write_fit_transport_budget(record_property):
    actor, file_id, handle_id, epoch = (str(uuid4()) for _ in range(4))
    context = common.RequestContext(request_id=str(uuid4()), user_id=actor,
                                   service_epoch=epoch, intent_sha256=b"x" * 32)
    operation = common.OperationRef(operation_id=str(uuid4()), request_id=str(uuid4()), intent_sha256=b"x" * 32)
    fence = common.Fence(lock_id=str(uuid4()), handle_id=handle_id, service_epoch=epoch,
                        generation=2**63-1, lease_id=2**63-1, block_indices=list(range(5)),
                        includes_size=True, expires_at_unix_ms=2**63-1)

    def block(index):
        return common.BlockRef(file_id=file_id, block_version_id=str(uuid4()), block_index=index,
                               size_bytes=BLOCK_BYTES, plaintext_sha256=b"x" * 32)

    page = control.StageManifestPageRequest(context=context, operation=operation, page_index=2**63-1,
        blocks=[block(2**40+i) for i in range(64)], page_sha256=b"x" * 32, fence=fence)
    changes = []
    for index in range(5):
        replacement = block(index)
        receipts = [common.DurableReceipt(receipt_id=str(uuid4()), operation_id=operation.operation_id,
            block=replacement, node_id=str(uuid4()), boot_generation=2**63-1, failure_domain="x" * 64,
            stored_size_bytes=BLOCK_BYTES+65536, ciphertext_sha256=b"x" * 32, durable_at_unix_ms=2**63-1)
            for _ in range(3)]
        changes.append(control.BlockChange(base=block(index), replacement=replacement, receipts=receipts))
    commit = control.CommitWriteRequest(context=context, operation=operation, handle_id=handle_id,
        changes=changes, fences=[fence] * 5, expected_handle_revision=2**63-1)
    assert page.ByteSize() < 64 * 1024 < MESSAGE_BYTES
    assert commit.ByteSize() < MESSAGE_BYTES
    # Un write desalineado de 16 MiB toca cinco bloques; no se envían sus bytes en CommitWrite.
    assert ((BLOCK_BYTES-1 + WRITE_BYTES - 1) // BLOCK_BYTES) + 1 == 5
    record_property("manifest_page_bytes", page.ByteSize())
    record_property("commit_write_bytes", commit.ByteSize())
