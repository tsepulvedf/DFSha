"""Proxy TCP local para particiones reales del laboratorio; no termina TLS."""
import selectors
import socket
import threading


class FaultProxy:
    def __init__(self, target):
        self.target = target
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(16)
        self.listener.settimeout(.2)
        self.endpoint = '127.0.0.1:'+str(self.listener.getsockname()[1])
        self.blocked, self.stopped = threading.Event(), threading.Event()
        self.guard = threading.Lock()
        self.connections, self.workers = set(), []
        self.up_bytes = self.down_bytes = 0
        self.thread = threading.Thread(target=self.accept, daemon=True)
        self.thread.start()

    def accept(self):
        while not self.stopped.is_set():
            try:
                client, _ = self.listener.accept()
            except (socket.timeout, OSError):
                continue
            if self.blocked.is_set():
                client.close()
                continue
            thread = threading.Thread(target=self.forward, args=(client,), daemon=True)
            with self.guard:
                self.workers = [t for t in self.workers if t.is_alive()]
                if len(self.workers) >= 32:
                    client.close()
                    continue
                self.workers.append(thread)
            thread.start()

    def forward(self, client):
        upstream = None
        try:
            host, port = self.target.rsplit(':', 1)
            upstream = socket.create_connection((host, int(port)), timeout=1)
            # gRPC already disables Nagle; preserve that behavior through the
            # transparent proxy instead of adding delayed-ACK stalls per frame.
            upstream.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            client.settimeout(1)
            with self.guard:
                self.connections.update((client, upstream))
            with selectors.DefaultSelector() as selector:
                selector.register(client, selectors.EVENT_READ, (upstream, True))
                selector.register(upstream, selectors.EVENT_READ, (client, False))
                while not self.blocked.is_set() and not self.stopped.is_set():
                    for key, _ in selector.select(.1):
                        peer, upward = key.data
                        data = key.fileobj.recv(65536)
                        if not data:
                            return
                        peer.sendall(data)
                        with self.guard:
                            if upward:
                                self.up_bytes += len(data)
                            else:
                                self.down_bytes += len(data)
        except OSError:
            pass
        finally:
            with self.guard:
                for sock in (client, upstream):
                    if sock:
                        self.connections.discard(sock)
                        sock.close()

    def partition(self):
        self.blocked.set()
        with self.guard:
            for sock in list(self.connections):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def heal(self):
        self.blocked.clear()

    def close(self):
        self.stopped.set()
        self.partition()
        self.listener.close()
        self.thread.join(2)
        for worker in list(self.workers):
            worker.join(2)
