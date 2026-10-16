"""Loopback Responses fixture: synthetic requests and scripted replies, never inference."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class ResponsesFixture:
    def __init__(self, folder, reply):
        self.folder, self.reply = folder, reply
        self.requests, self.errors = [], []

    def __enter__(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                try:
                    assert self.path == '/responses', self.path
                    body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    fixture.requests.append(body)
                    number = len(fixture.requests)
                    (fixture.folder / f'{number:03d}.json').write_text(json.dumps(body, indent=2) + '\n')
                    item = fixture.reply(body, number)
                    response = {'id': f'fixture-response-{number}', 'status': 'completed', 'output': [item],
                                'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}
                    events = [{'type': 'response.created', 'response': {**response, 'status': 'in_progress', 'output': []}},
                              {'type': 'response.output_item.added', 'output_index': 0, 'item': item},
                              {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
                              {'type': 'response.completed', 'response': response}]
                    data = ''.join('event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n'
                                   for event in events).encode()
                    (fixture.folder / f'{number:03d}.response.sse').write_bytes(data)
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except Exception as exc:
                    fixture.errors.append(str(exc))
                    self.send_error(400, 'Local fixture rejected request')

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def message(text='SCRIPTED_LOCAL_FIXTURE_ONLY; no remote model was called.'):
    return {'id': 'fixture-message', 'type': 'message', 'role': 'assistant', 'status': 'completed',
            'content': [{'type': 'output_text', 'text': text, 'annotations': []}]}
