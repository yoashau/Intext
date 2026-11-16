import json
import select
import threading
import time
import unittest
from concurrent.futures import CancelledError, ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from intext.http_client import CancellationToken, PooledHttpClient
from intext.translate import TranslationError


class LocalApi(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self):
        super().__init__(('127.0.0.1', 0), Handler)
        self.lock = threading.Lock()
        self.calls = []
        self.active = self.peak = 0
        self.two_active = threading.Event()
        self.three_active = threading.Event()
        self.release = threading.Event()
        self.holding = threading.Event()
        self.disconnected = threading.Event()

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server_port}'


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    disable_nagle_algorithm = True

    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        server = self.server
        with server.lock:
            server.calls.append((self.path, self.client_address, body))
            server.active += 1
            server.peak = max(server.peak, server.active)
            if server.active >= 2:
                server.two_active.set()
            if server.active >= 3:
                server.three_active.set()
        try:
            hold = self.path == '/hold' or (self.path == '/cancel-once' and len(server.calls) == 1)
            if hold:
                self.send_response(200)
                self.send_header('Content-Length', '1000')
                self.end_headers()
                self.wfile.write(b'{')
                self.wfile.flush()
                server.holding.set()
                if select.select([self.connection], [], [], 3)[0] and self.connection.recv(1) == b'':
                    server.disconnected.set()
                self.close_connection = True
                return
            if self.path == '/gate':
                server.release.wait(3)
            if self.path == '/drop':
                self.close_connection = True
                return
            if self.path == '/redirect':
                self.send_response(307)
                self.send_header('Location', '/echo')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            raw = json.dumps({'value': body.get('value'), 'choices': [{'message': {'content': '译文'}}]}).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # Cancelling before the peer has consumed the partial response
            # can produce TCP reset rather than a graceful EOF. Both close
            # the request; don't mistake reset for a still-open socket.
            server.disconnected.set()
        finally:
            with server.lock:
                server.active -= 1


class HttpClientTests(unittest.TestCase):
    def setUp(self):
        self.server = LocalApi()
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.client = PooledHttpClient(trust_env=False)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.server.release.set()
        self.client.close()
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(3)

    def test_sequential_requests_reuse_one_connection_and_preserve_unicode(self):
        for value in ['你好', 'second', 'third']:
            response = self.client.post_json(self.server.url + '/echo', {}, {'value': value}, 3)
            self.assertEqual(response['value'], value)
        self.assertEqual(len({peer for _, peer, _ in self.server.calls}), 1)

    def test_running_cancel_closes_socket_and_next_request_starts_promptly(self):
        token = CancellationToken()
        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(self.client.post_json, self.server.url + '/hold', {}, {}, 3, cancellation=token)
            self.assertTrue(self.server.holding.wait(2))
            start = time.monotonic()
            token.cancel()
            with self.assertRaises(CancelledError):
                pending.result(timeout=1)
            self.assertTrue(self.server.disconnected.wait(1), 'server did not observe socket closure')
            response = self.client.post_json(self.server.url + '/echo', {}, {'value': 'new'}, 2)
            self.assertEqual(response['value'], 'new')
            self.assertLess(time.monotonic() - start, 1)

    def test_requests_have_a_global_concurrency_limit(self):
        barrier = threading.Barrier(7)
        def send(value):
            barrier.wait(timeout=3)
            return self.client.post_json(self.server.url + '/gate', {}, {'value': value}, 3)
        with ThreadPoolExecutor(max_workers=6) as workers:
            pending = [workers.submit(send, i) for i in range(6)]
            barrier.wait(timeout=3)
            try:
                self.assertTrue(self.server.two_active.wait(2))
                self.assertFalse(self.server.three_active.wait(.1))
            finally:
                self.server.release.set()
            self.assertEqual([p.result(timeout=3)['value'] for p in pending], list(range(6)))
        self.assertLessEqual(self.server.peak, 2)

    def test_queued_cancel_never_reaches_server(self):
        client = PooledHttpClient(max_concurrency=1, trust_env=False)
        self.addCleanup(client.close)
        token = CancellationToken()
        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(client.post_json, self.server.url + '/gate', {}, {'value': 1}, 3)
            # The single active request holds the pool slot until released.
            end = time.monotonic() + 2
            while not self.server.calls and time.monotonic() < end:
                time.sleep(.005)
            self.assertTrue(self.server.calls)
            second = workers.submit(client.post_json, self.server.url + '/echo', {}, {'value': 2}, 3, cancellation=token)
            token.cancel()
            try:
                with self.assertRaises(CancelledError):
                    second.result(timeout=1)
            finally:
                self.server.release.set()
            first.result(timeout=2)
        self.assertEqual([path for path, _, _ in self.server.calls], ['/gate'])

    def test_total_timeout_closes_stalled_response(self):
        with self.assertRaisesRegex(TranslationError, '^请求超时$'):
            self.client.post_json(self.server.url + '/hold', {}, {}, .2)
        self.assertTrue(self.server.disconnected.wait(1))

    def test_post_is_not_automatically_retried_after_disconnect(self):
        with self.assertRaisesRegex(TranslationError, '无法连接模型服务'):
            self.client.post_json(self.server.url + '/drop', {}, {}, 2)
        self.assertEqual([path for path, _, _ in self.server.calls], ['/drop'])
        self.assertEqual(self.client.post_json(self.server.url + '/echo', {}, {'value': 'retry'}, 2)['value'], 'retry')

    def test_redirect_preserves_post_body(self):
        self.assertEqual(self.client.post_json(self.server.url + '/redirect', {}, {'value': 'redirect'}, 2)['value'], 'redirect')
        self.assertEqual([body for _, _, body in self.server.calls], [{'value': 'redirect'}] * 2)

    def test_close_cancels_inflight_request_and_stops_io_thread(self):
        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(self.client.post_json, self.server.url + '/hold', {}, {}, 3)
            self.assertTrue(self.server.holding.wait(2))
            self.client.close()
            with self.assertRaises(CancelledError):
                pending.result(timeout=1)
        self.assertFalse(self.client._thread.is_alive())
        self.assertTrue(self.server.disconnected.wait(1))
        with self.assertRaises(CancelledError):
            self.client.post_json(self.server.url + '/echo', {}, {}, 1)

    def test_unused_client_does_not_start_a_thread(self):
        unused = PooledHttpClient()
        self.assertIsNone(unused._thread)
        unused.close()

    def test_app_new_generation_cancels_old_same_key_and_only_caches_current_result(self):
        import os
        import tempfile
        from unittest.mock import patch
        from intext.app import App
        from intext.config import Settings

        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'APPDATA': folder}):
            app = App(Settings(model='fixture', endpoint=self.server.url + '/cancel-once'))
            app._http.close()
            app._http = self.client
            states = []
            app._push = lambda state, **_: states.append(state)
            try:
                with ThreadPoolExecutor(max_workers=2) as workers, patch('intext.app.log_error') as log:
                    old = workers.submit(app._finish, 'same text', 0)
                    self.assertTrue(self.server.holding.wait(2),
                        f'worker_done={old.done()}, states={states}, errors={log.call_args_list}')
                    generation = app._next_generation()
                    new = workers.submit(app._finish, 'same text', generation)
                    old.result(timeout=1)
                    new.result(timeout=2)
                    log.assert_not_called()
                self.assertTrue(self.server.disconnected.wait(1))
                self.assertEqual(len(self.server.calls), 2)
                self.assertEqual([(s['seq'], s['result']) for s in states], [(generation, '译文')])
                self.assertEqual(app.cache._pending, {})
                self.assertEqual(app._cached('same text').text, '译文')
            finally:
                app.cache.disk.close()

    def test_total_deadline_also_applies_while_waiting_for_a_pool_slot(self):
        client = PooledHttpClient(max_concurrency=1, trust_env=False)
        self.addCleanup(client.close)
        with ThreadPoolExecutor(max_workers=1) as workers:
            first = workers.submit(client.post_json, self.server.url + '/gate', {}, {}, 3)
            end = time.monotonic() + 2
            while not self.server.calls and time.monotonic() < end:
                time.sleep(.005)
            self.assertTrue(self.server.calls)
            try:
                with self.assertRaisesRegex(TranslationError, '^请求超时$'):
                    client.post_json(self.server.url + '/echo', {}, {}, .05)
            finally:
                self.server.release.set()
            first.result(timeout=2)
        self.assertEqual([path for path, _, _ in self.server.calls], ['/gate'])

    def test_repeated_identical_selection_joins_request_instead_of_cancelling_it(self):
        import os
        import tempfile
        from concurrent.futures import Future
        from unittest.mock import patch
        from intext.app import App
        from intext.config import Settings

        joined = threading.Event()
        completed = threading.Event()
        threads = []
        class Pending(Future):
            def result(self, timeout=None):
                joined.set()
                return super().result(timeout=3)

        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'APPDATA': folder}):
            app = App(Settings(model='fixture', endpoint=self.server.url + '/gate'))
            app._http.close()
            app._http = self.client
            states = []
            app._push = lambda state, **_: states.append(state)
            finish = app._finish
            def track(*args, **kwargs):
                threads.append(threading.current_thread())
                try:
                    finish(*args, **kwargs)
                finally:
                    completed.set()
            app._finish = track
            try:
                with patch('intext.cache.Future', Pending):
                    self.assertTrue(app._capture(lambda: 'same text'))
                    end = time.monotonic() + 2
                    while not self.server.calls and time.monotonic() < end:
                        time.sleep(.005)
                    self.assertTrue(self.server.calls)
                    self.assertTrue(app._capture(lambda: 'same text'))
                    self.assertTrue(joined.wait(2), 'identical selection did not join the pending cache load')
                    obsolete_waiter = threads[-1]
                    joined.clear()
                    self.assertTrue(app._capture(lambda: 'same text'))
                    self.assertTrue(joined.wait(2))
                    obsolete_waiter.join(1)
                    self.assertFalse(obsolete_waiter.is_alive(), 'obsolete cache waiter kept a background thread alive')
                    self.server.release.set()
                    self.assertTrue(completed.wait(2))
                    for thread in threads:
                        thread.join(2)
                self.assertEqual(len(self.server.calls), 1)
                self.assertEqual([s['seq'] for s in states if s.get('result')], [app._gen])
            finally:
                self.server.release.set()
                for thread in threads:
                    thread.join(2)
                app.cache.disk.close()
