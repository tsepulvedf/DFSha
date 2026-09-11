"""Autoridad local de leases. Toda mutación recibe la transacción de publicación."""
import time
from dfsha.common.domain import need, uid, now, asdict, proto
from dfsha.v1 import common_pb2 as c

MAX_DELTA = 16 * 1024 * 1024
MAX_OFFSET = (1 << 63) - 1


def checked_range(offset, length, maximum=None):
    need(isinstance(offset, int) and isinstance(length, int) and
         0 <= offset <= MAX_OFFSET and 0 <= length <= MAX_OFFSET - offset)
    if maximum is not None:
        need(length <= maximum, 'LIMIT_EXCEEDED')
    return offset + length


class SQLiteLeaseAuthority:
    def __init__(self, app):
        self.app = app
        self.clock = time.monotonic
        self.lock_seconds = app.cfg.get('lock_lease_seconds', 30)
        self.handle_seconds = app.cfg.get('handle_lease_seconds', 120)
        need(0 < self.lock_seconds <= 300 and 0 < self.handle_seconds <= 3600)
        with app.store.transaction(True) as tx:
            previous = tx.get('settings', 'control-epoch') or dict(id='control-epoch', generation=0)
            previous.update(generation=previous['generation'] + 1, epoch=uid())
            tx.put('settings', previous)
            self.epoch = previous['epoch']
            for handle in tx.all('handle'):
                handle['closed'] = True
                tx.put('handle', handle)
            for lock in tx.all('lock'):
                tx.delete('lock', lock['id'])

    def live(self, record):
        return record.get('control_epoch') == self.epoch and record.get('deadline', 0) > self.clock()

    def expiry_hint(self, record):
        return now() + max(0, int((record['deadline'] - self.clock()) * 1000))

    def refresh_handle(self, handle, initial=False):
        if initial:
            handle.update(control_epoch=self.epoch, maximum=self.clock() + 86400)
        handle['deadline'] = min(self.clock() + self.handle_seconds, handle['maximum'])
        handle['expires'] = now() + max(0, int((handle['deadline'] - self.clock()) * 1000))

    def acquire(self, tx, handle, indices=(), whole=False, size=False, automatic=False):
        indices = sorted(set(indices))
        owner = (handle['session'], handle['id'])
        for lock in tx.all('lock'):
            if not self.live(lock) or lock['file'] != handle['file']:
                continue
            if (lock['session'], lock['handle']) == owner:
                continue
            need(not (whole or lock['whole'] or size and lock['size'] or
                      set(indices).intersection(lock['indices'])), 'LOCK_CONFLICT')
        sequence = tx.get('settings', 'lock-sequence') or dict(id='lock-sequence', generation=0)
        sequence['generation'] += 1
        tx.put('settings', sequence)
        lock = dict(id=uid(), handle=handle['id'], file=handle['file'], session=handle['session'],
                    generation=sequence['generation'], control_epoch=self.epoch, indices=indices,
                    whole=whole, size=size, automatic=automatic, lease=sequence['generation'], active=[],
                    deadline=self.clock() + self.lock_seconds)
        tx.put('lock', lock)
        return lock

    def message(self, lock):
        return c.Fence(lock_id=lock['id'], handle_id=lock['handle'], service_epoch=self.epoch,
            generation=lock['generation'], lease_id=lock['lease'], block_indices=lock['indices'],
            whole_file=lock['whole'], includes_size=lock['size'],
            expires_at_unix_ms=now() + max(0, int((lock['deadline'] - self.clock()) * 1000)))

    def validate(self, tx, session, fence):
        lock = tx.get('lock', fence.lock_id)
        need(lock, 'LOCK_EXPIRED')
        need(lock['session'] == session['id'] and lock['handle'] == fence.handle_id,
             'PERMISSION_DENIED')
        need(self.live(lock) and fence.service_epoch == self.epoch and
             fence.generation == lock['generation'] and fence.lease_id == lock['lease'], 'LOCK_EXPIRED')
        expected, supplied = asdict(self.message(lock)), asdict(fence)
        expected.pop('expires_at_unix_ms', None)
        supplied.pop('expires_at_unix_ms', None)
        need(expected == supplied, 'PERMISSION_DENIED')
        return lock

    def release_operation(self, tx, op):
        for identity in op.get('locks', []):
            lock = tx.get('lock', identity)
            if lock and op['id'] in lock['active']:
                lock['active'].remove(op['id'])
                if lock['automatic']:
                    tx.delete('lock', identity)
                else:
                    tx.put('lock', lock)
        handle = tx.get('handle', op.get('handle', ''))
        if handle and handle.get('busy') == op['id']:
            handle['busy'] = None
            tx.put('handle', handle)
