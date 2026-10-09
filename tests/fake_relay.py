"""A stand-in for the vendor's licence relay (Apps-Factory templates/telemetry-relay, src/licence.js), speaking the same three shop-side
calls, for tests: request (replay-safe by nonce, token shown once), status (poll token), ack. The test plays the owner's licensing
program with `issue()` / `refuse()`. The real Worker is exercised against the real Studio in the Apps Factory's tests."""
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Quiet(ThreadingHTTPServer):
    def handle_error(self, request, client_address):  # a dropped answer is on purpose: no traceback in the test log
        pass


class FakeRelay:
    def __init__(self, port=0):
        self.requests = {}      # id -> dict(body, token, status, reason, code, acked)
        self.by_nonce = {}
        self.log = []           # every call: (method, path)
        self.drop_next_answer = False
        self.delay = 0          # seconds every answer waits: a slow relay
        self.fail_status = None  # e.g. 503: every status look gets this answer (the relay is in trouble)
        self.auto = None        # a function(request) -> ('issue', code) | ('refuse', reason) | None, answered at once
        relay = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                time.sleep(relay.delay)
                n = int(self.headers.get('Content-Length') or 0)
                body = json.loads(self.rfile.read(n) or b'{}')
                relay.log.append(('POST', self.path))
                if self.path == '/licence/request':
                    return self.send(*relay.create(body))
                if self.path == '/licence/ack':
                    r = relay.own(self.headers, body.get('id'))
                    if not r:
                        return self.send(401, {'error': 'unauthorised'})
                    r['acked'] = True
                    r['status'] = 'delivered' if r['status'] == 'issued' else r['status']
                    return self.send(200, {'status': r['status']})
                self.send(404, {})

            def do_GET(self):
                time.sleep(relay.delay)
                relay.log.append(('GET', self.path.split('?')[0]))
                if self.path.startswith('/licence/status') and relay.fail_status:
                    return self.send(relay.fail_status, {'error': 'unavailable'})
                if self.path.startswith('/licence/status'):
                    r = relay.own(self.headers, self.path.split('id=')[-1])
                    if not r:
                        return self.send(401, {'error': 'unauthorised'})
                    out = {'status': r['status'], 'reason': r['reason']}
                    if r['status'] == 'issued':
                        out['code'] = r['code']
                    return self.send(200, out)
                self.send(404, {})

        self.httpd = Quiet(('127.0.0.1', port), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.base = f'http://127.0.0.1:{self.port}'
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def own(self, headers, rid):
        r = self.requests.get(rid)
        token = (headers.get('Authorization') or '').removeprefix('Bearer ').strip()
        return r if r and token and token == r['token'] else None

    def create(self, body):
        key = (body.get('product'), body.get('device'), body.get('nonce'))
        if key in self.by_nonce:
            r = self.requests[self.by_nonce[key]]
            return 200, {'id': r['id'], 'status': r['status'], 'reason': r['reason'], 'replay': True}
        r = {'id': str(uuid.uuid4()), 'body': body, 'token': 'lp_' + uuid.uuid4().hex + uuid.uuid4().hex[:16], 'status': 'pending', 'reason': '',
             'code': None, 'acked': False}
        self.requests[r['id']] = r
        self.by_nonce[key] = r['id']
        if self.auto:
            verdict = self.auto(r)
            if verdict and verdict[0] == 'issue':
                r.update(status='issued', code=verdict[1])
            elif verdict:
                r.update(status='refused', reason=verdict[1])
        answer = {'id': r['id'], 'poll_token': r['token'], 'status': r['status'], 'reason': r['reason']}
        if self.drop_next_answer:  # the request is stored but the shop never hears: the connection just dies
            self.drop_next_answer = False
            raise ConnectionResetError('answer lost')
        return 202, answer

    def last(self):
        return list(self.requests.values())[-1]

    def issue(self, r, code):
        r.update(status='issued', code=code)

    def refuse(self, r, reason='owner_refused'):
        r.update(status='refused', reason=reason)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
