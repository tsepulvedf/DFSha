"""Watch es una notificación; la autoridad sigue siendo Range/Txn consistente."""
import threading
import grpc
from dfsha._vendor.etcd.api.etcdserverpb import rpc_pb2 as pb


class RootWatch:
    def __init__(self, store):
        self.store = store
        self.stop = threading.Event()
        self.paused = threading.Event()
        self.wake = threading.Event()
        self.disconnected = threading.Event()
        self.revision = 0
        self.rebuilds = self.events = self.reconnects = self.compactions = 0
        self.stream = None
        self.thread = threading.Thread(target=self.run, name='metadata-watch', daemon=True)

    def start(self):
        self.thread.start()

    def pause(self):
        self.paused.set()
        if self.stream:
            self.stream.cancel()

    def resume(self):
        self.paused.clear()

    def run(self):
        while not self.stop.is_set():
            if self.paused.is_set():
                self.disconnected.set()
                self.stop.wait(.05)
                continue
            self.disconnected.clear()
            try:
                if not self.revision:
                    response = self.store.rpc(self.store.kv.Range, pb.RangeRequest(key=self.store.root_key))
                    if response.kvs:
                        self.store.object(response.kvs[0].value.decode())
                    self.revision = response.header.revision
                    self.rebuilds += 1
                request = pb.WatchRequest(create_request=pb.WatchCreateRequest(key=self.store.root_key,
                    start_revision=self.revision+1, progress_notify=True))
                self.stream = self.store.watch.Watch(iter([request]), timeout=30)
                self.reconnects += 1
                for response in self.stream:
                    if response.compact_revision:
                        self.compactions += 1
                        self.revision = 0
                        break
                    if response.events:
                        self.revision = max(e.kv.mod_revision for e in response.events)
                        self.events += len(response.events)
                        self.wake.set()
                    if self.stop.is_set() or self.paused.is_set():
                        break
            except Exception:
                with self.store.channel.guard:
                    self.store.channel.index = (self.store.channel.index+1) % len(self.store.channel.channels)
                self.stop.wait(.1)
            finally:
                if self.stream:
                    self.stream.cancel()
                self.disconnected.set()

    def close(self):
        self.stop.set()
        if self.stream:
            self.stream.cancel()
        self.thread.join(5)
