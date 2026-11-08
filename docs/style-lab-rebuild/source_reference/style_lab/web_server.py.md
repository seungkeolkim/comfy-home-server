# Source Snapshot: web_server.py

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\web_server.py`
- Original Byte SHA-256: `2286703ee03729c19ae27090b82e3cd000a799e962525f03d8c80530f12bf570`
- Snapshot Text SHA-256: `2286703ee03729c19ae27090b82e3cd000a799e962525f03d8c80530f12bf570`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```python
"""Style Lab의 기존 Engine을 인증된 Browser에서 사용하는 웹 서버입니다."""

import argparse
import getpass
import hashlib
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
import signal
from socketserver import ThreadingMixIn
import sys
import threading
import time
from urllib.parse import urlsplit
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

ROOT_DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIRECTORY / 'app'))

from bottle import Bottle, HTTPResponse, request, response, static_file
from bridge import App, CACHED, NO_STORE
from data_access import DataDirectoryLock
from engine import Engine, UserError

BROWSER_DIRECTORY = ROOT_DIRECTORY / 'web_browser'
SESSION_COOKIE_NAME = 'style_lab_session'
SESSION_LIFETIME_SECONDS = 12 * 60 * 60
PASSWORD_ITERATIONS = 310_000
MAXIMUM_UPLOAD_BYTES = 1024 * 1024 * 1024
LOGGER = logging.getLogger('style_lab_web')


class WebAuthentication:
    """비밀번호 Hash, 만료되는 Session, CSRF Token을 관리합니다."""

    def __init__(self, password_configuration):
        """인증 정보만 메모리에 올리고 Session은 프로세스별로 새로 만듭니다."""
        self.password_configuration = password_configuration
        self.sessions = {}
        self.login_failures = {}
        self.lock = threading.RLock()

    def verify_password(self, password):
        """저장된 PBKDF2 Hash와 입력값을 일정 시간 비교합니다."""
        configuration = self.password_configuration
        supplied_digest = hashlib.pbkdf2_hmac(
            'sha256', password.encode('utf-8'), bytes.fromhex(configuration['salt']),
            configuration['iterations'],
        ).hex()
        return hmac.compare_digest(supplied_digest, configuration['password_hash'])

    def sign_in(self, password, client_address):
        """반복되는 실패를 제한하고 로그인 성공 시 Session을 발급합니다."""
        current_time = time.monotonic()
        with self.lock:
            for expired_address in list(self.login_failures):
                recent_failures = [timestamp for timestamp in self.login_failures[expired_address] if current_time - timestamp < 300]
                if recent_failures:
                    self.login_failures[expired_address] = recent_failures
                else:
                    del self.login_failures[expired_address]
            recent_failures = self.login_failures.get(client_address, [])
            if len(recent_failures) >= 8:
                raise HTTPResponse(status=429, body=json.dumps({'ok': False, 'error': '로그인 시도가 많습니다. 5분 뒤 다시 시도해 주세요.'}))
            if not self.verify_password(password):
                self.login_failures.setdefault(client_address, []).append(current_time)
                return None
            self.login_failures.pop(client_address, None)
            session_identifier = secrets.token_urlsafe(32)
            self.sessions[session_identifier] = {
                'csrf_token': secrets.token_urlsafe(32),
                'expires_at': current_time + SESSION_LIFETIME_SECONDS,
            }
            self._remove_expired_sessions(current_time)
            return session_identifier

    def _remove_expired_sessions(self, current_time):
        """오래된 Session이 계속 메모리에 쌓이지 않도록 정리합니다."""
        for session_identifier in list(self.sessions):
            if self.sessions[session_identifier]['expires_at'] <= current_time:
                del self.sessions[session_identifier]

    def current_session(self):
        """요청 Cookie에 해당하는 유효한 Session만 반환합니다."""
        with self.lock:
            self._remove_expired_sessions(time.monotonic())
            return self.sessions.get(request.get_cookie(SESSION_COOKIE_NAME))


class BrowserBridge(App):
    """기존 App의 기능을 사용하되 Windows 전용 동작은 Browser로 바꿉니다."""

    def resource(self, resource_path):
        """웹 파일은 별도 폴더에서, 이미지는 기존 안전한 경로 검사로 제공합니다."""
        if resource_path in ('/', '/index.html'):
            return self._typed(BROWSER_DIRECTORY / 'index.html', NO_STORE)
        if resource_path.startswith('/static/'):
            from urllib.parse import unquote
            file_path = (BROWSER_DIRECTORY / unquote(resource_path[len('/static/'):])).resolve()
            if BROWSER_DIRECTORY.resolve() not in file_path.parents:
                return None
            return self._typed(file_path, NO_STORE)
        if resource_path.startswith(('/img/', '/thumb/')):
            return super().resource(resource_path)
        return None

    def post(self, route_path, payload):
        """실제 Engine을 호출하며 Desktop 전용 파일 접근은 실행하지 않습니다."""
        if route_path in ('/api/open-folder', '/api/drag', '/api/open-comfy', '/api/open', '/api/data/pick', '/api/data/export', '/api/data/import'):
            raise UserError('Browser용 파일 열기·다운로드·업로드 기능을 사용해 주세요.')
        if route_path == '/api/settings/draft':
            return None
        if route_path == '/api/combos/merge':
            return self.engine.merge_combos(payload.get('ids', []), payload.get('count'))
        result = super().post(route_path, payload)
        with self.engine.lock:
            if 'merged' not in self.engine.state:
                self.engine.state['merged'] = []
                self.engine.save()
        return result


def password_configuration(password):
    """비밀번호 원문 없이 저장할 PBKDF2 설정을 생성합니다."""
    salt_bytes = secrets.token_bytes(24)
    password_digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt_bytes, PASSWORD_ITERATIONS)
    return {'salt': salt_bytes.hex(), 'password_hash': password_digest.hex(), 'iterations': PASSWORD_ITERATIONS}


def load_authentication(data_directory, replace_password=False):
    """첫 실행에서는 임의 비밀번호를 만들고, 요청 시에만 교체합니다."""
    configuration_directory = data_directory / 'web-server'
    configuration_directory.mkdir(parents=True, exist_ok=True)
    configuration_path = configuration_directory / 'authentication.json'
    if replace_password:
        supplied_password = getpass.getpass('새 웹 접속 비밀번호: ')
        if len(supplied_password) < 10:
            raise ValueError('비밀번호는 10자 이상으로 설정해 주세요.')
        if supplied_password != getpass.getpass('비밀번호 다시 입력: '):
            raise ValueError('비밀번호가 일치하지 않습니다.')
    elif configuration_path.exists():
        return WebAuthentication(json.loads(configuration_path.read_text(encoding='utf-8')))
    else:
        supplied_password = secrets.token_urlsafe(18)
    authentication_configuration = password_configuration(supplied_password)
    temporary_path = configuration_path.with_suffix('.tmp')
    temporary_path.write_text(json.dumps(authentication_configuration, indent=2), encoding='utf-8')
    os.replace(temporary_path, configuration_path)
    initial_password_path = configuration_directory / 'initial-password.txt'
    if replace_password:
        initial_password_path.unlink(missing_ok=True)
    else:
        initial_password_path.write_text(supplied_password + '\n', encoding='utf-8')
        LOGGER.info('첫 로그인 비밀번호 파일: %s', initial_password_path)
    return WebAuthentication(authentication_configuration)


def check_same_origin():
    """다른 사이트가 Browser의 인증 Cookie를 이용해 변경 요청을 보내지 못하게 합니다."""
    origin_header = request.get_header('Origin')
    if request.get_header('Sec-Fetch-Site') == 'cross-site':
        raise HTTPResponse(status=403, body='다른 사이트에서 보낸 요청입니다.')
    if origin_header:
        parsed_origin = urlsplit(origin_header)
        if parsed_origin.scheme not in ('http', 'https') or parsed_origin.netloc != request.get_header('Host'):
            raise HTTPResponse(status=403, body='요청 Origin이 일치하지 않습니다.')


def require_session(authentication, require_csrf=False):
    """인증과 필요한 CSRF 검사를 수행하고 현재 Session을 반환합니다."""
    current_session = authentication.current_session()
    if current_session is None:
        raise HTTPResponse(status=401, body=json.dumps({'ok': False, 'error': '로그인이 필요합니다.'}), content_type='application/json')
    if require_csrf:
        check_same_origin()
        supplied_token = request.get_header('X-CSRF-Token', '')
        if not hmac.compare_digest(supplied_token, current_session['csrf_token']):
            raise HTTPResponse(status=403, body=json.dumps({'ok': False, 'error': '인증 정보가 만료되었습니다. 다시 로그인해 주세요.'}), content_type='application/json')
    return current_session


def json_reply(payload, status_code=200):
    """기존 Frontend와 같은 JSON 응답 형식을 사용합니다."""
    response.status = status_code
    response.content_type = 'application/json; charset=utf-8'
    return json.dumps(payload, ensure_ascii=False)


def archive_chunks(archive_path):
    """다운로드를 Stream으로 보내고 완료 또는 연결 종료 시 임시 파일을 지웁니다."""
    try:
        with archive_path.open('rb') as archive_file:
            while archive_chunk := archive_file.read(1024 * 1024):
                yield archive_chunk
    finally:
        archive_path.unlink(missing_ok=True)


def create_web_application(engine, authentication, secure_cookie=False):
    """기존 Engine을 HTTP로 연결하는 인증된 Bottle 애플리케이션을 만듭니다."""
    application = Bottle()
    browser_bridge = BrowserBridge(engine, engine.data_dir / 'web-server' / 'application.log')
    (engine.data_dir / 'web-server').mkdir(parents=True, exist_ok=True)
    application.style_lab_bridge = browser_bridge

    @application.hook('after_request')
    def add_security_headers():
        """인증 응답의 캐시와 외부 사이트의 화면 삽입을 막습니다."""
        response.set_header('Cache-Control', 'no-store')
        response.set_header('X-Content-Type-Options', 'nosniff')
        response.set_header('Referrer-Policy', 'same-origin')
        response.set_header('X-Frame-Options', 'DENY')
        response.set_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'")

    @application.get('/health')
    def health_status():
        """데이터를 노출하지 않고 웹 서버의 생존 여부만 응답합니다."""
        return json_reply({'ok': True, 'service': 'style-lab-web'})

    @application.get('/')
    def application_page():
        """미인증 사용자는 로그인 화면으로, 인증 사용자는 실제 앱으로 보냅니다."""
        if not authentication.current_session():
            return HTTPResponse(status=303, headers={'Location': '/login'})
        return static_file('index.html', root=str(BROWSER_DIRECTORY), mimetype='text/html; charset=utf-8')

    @application.get('/login')
    def login_page():
        """로그인 화면을 제공합니다."""
        return static_file('login.html', root=str(BROWSER_DIRECTORY), mimetype='text/html; charset=utf-8')

    @application.post('/api/login')
    def sign_in():
        """비밀번호를 검증하고 HttpOnly Cookie를 발급합니다."""
        check_same_origin()
        if request.content_length > 4096:
            return json_reply({'ok': False, 'error': '입력값이 너무 깁니다.'}, 413)
        payload = request.json or {}
        supplied_password = payload.get('password') if isinstance(payload, dict) else None
        if not isinstance(supplied_password, str) or len(supplied_password) > 512:
            return json_reply({'ok': False, 'error': '비밀번호를 입력해 주세요.'}, 400)
        session_identifier = authentication.sign_in(supplied_password, request.remote_addr or 'unknown')
        if session_identifier is None:
            return json_reply({'ok': False, 'error': '비밀번호가 일치하지 않습니다.'}, 401)
        response.set_cookie(SESSION_COOKIE_NAME, session_identifier, path='/', httponly=True,
                            secure=secure_cookie, samesite='strict', max_age=SESSION_LIFETIME_SECONDS)
        return json_reply({'ok': True})

    @application.get('/api/session')
    def session_details():
        """로그인된 Frontend에 CSRF Token을 전달합니다."""
        current_session = require_session(authentication)
        return json_reply({'ok': True, 'data': {'csrf_token': current_session['csrf_token']}})

    @application.post('/api/logout')
    def sign_out():
        """현재 Session을 무효화하고 로그인 화면으로 돌아갈 수 있게 합니다."""
        require_session(authentication, require_csrf=True)
        with authentication.lock:
            authentication.sessions.pop(request.get_cookie(SESSION_COOKIE_NAME), None)
        response.delete_cookie(SESSION_COOKIE_NAME, path='/')
        return json_reply({'ok': True})

    @application.post('/api/data/export')
    def export_archive():
        """실제 조합·설정·이미지를 ZIP 파일로 내려받습니다."""
        require_session(authentication, require_csrf=True)
        archive_directory = engine.data_dir / 'web-server' / 'downloads'
        archive_directory.mkdir(parents=True, exist_ok=True)
        archive_path = archive_directory / (secrets.token_hex(16) + '.zip')
        try:
            engine.export_data(archive_path)
        except Exception:
            archive_path.unlink(missing_ok=True)
            raise
        response.content_type = 'application/zip'
        response.set_header('Content-Disposition', 'attachment; filename="style-lab-data.zip"')
        response.set_header('Content-Length', str(archive_path.stat().st_size))
        return archive_chunks(archive_path)

    @application.post('/api/data/import')
    def import_archive():
        """Browser에서 확인 후 업로드한 ZIP을 기존 Import 기능으로 처리합니다."""
        require_session(authentication, require_csrf=True)
        if request.content_length <= 0 or request.content_length > MAXIMUM_UPLOAD_BYTES:
            return json_reply({'ok': False, 'error': '업로드할 ZIP은 1 GB 이하여야 합니다.'}, 413)
        uploaded_archive = request.files.get('archive')
        if uploaded_archive is None:
            return json_reply({'ok': False, 'error': 'ZIP 파일을 선택해 주세요.'}, 400)
        archive_bytes = uploaded_archive.file.read(MAXIMUM_UPLOAD_BYTES + 1)
        if len(archive_bytes) > MAXIMUM_UPLOAD_BYTES:
            return json_reply({'ok': False, 'error': '업로드한 파일이 너무 큽니다.'}, 413)
        try:
            imported_result = engine.import_data(archive_bytes)
            with engine.lock:
                engine.state.setdefault('merged', [])
                engine.save()
            return json_reply({'ok': True, 'data': imported_result})
        except UserError as error:
            return json_reply({'ok': False, 'error': str(error)}, 400)

    @application.route('/api/<route_name:path>', method=['GET', 'POST'])
    def engine_request(route_name):
        """기존 Engine의 조회·변경 기능을 인증과 일치 검사 후 실행합니다."""
        changing_state = request.method == 'POST'
        require_session(authentication, require_csrf=changing_state)
        if changing_state and request.content_length > 2 * 1024 * 1024:
            return json_reply({'ok': False, 'error': '요청이 너무 큽니다.'}, 413)
        payload = request.json if changing_state else None
        payload = payload if isinstance(payload, dict) else {}
        route_path = '/api/' + route_name
        if route_path in ('/api/vote', '/api/skip') and changing_state:
            with engine.lock:
                expected_match = payload.get('expected_match')
                actual_match = engine.current
                actual_signature = {key: actual_match.get(key) for key in ('kind', 'a', 'b')} if actual_match else None
                if expected_match is None or expected_match != actual_signature:
                    return json_reply({'ok': False, 'error': '다른 화면에서 비교 대상이 바뀌었습니다. 새 비교를 확인하고 선택해 주세요.'}, 409)
                reply_text = browser_bridge.call(request.method, request.path, payload)
        else:
            route_query = request.path + ('?' + request.query_string if request.query_string else '')
            reply_text = browser_bridge.call(request.method, route_query, payload)
        reply_payload = json.loads(reply_text)
        return json_reply(reply_payload, 200 if reply_payload.get('ok') else 400)

    @application.get('/<resource_path:path>')
    def resource_file(resource_path):
        """인증된 이미지와 웹 파일만 제공하며 디스크 경로를 직접 받지 않습니다."""
        if resource_path in ('static/login.js', 'static/browser.css', 'static/app.css', 'static/icon.svg'):
            found_resource = browser_bridge.resource('/' + resource_path)
        else:
            require_session(authentication)
            found_resource = browser_bridge.resource('/' + resource_path)
        if found_resource is None:
            raise HTTPResponse(status=404, body='파일을 찾을 수 없습니다.')
        file_path, content_type, cache_policy = found_resource
        file_response = static_file(file_path.name, root=str(file_path.parent), mimetype=content_type)
        file_response.set_header('Cache-Control', 'private, max-age=3600' if cache_policy == CACHED else NO_STORE)
        return file_response

    return application


class ThreadedWebServer(ThreadingMixIn, WSGIServer):
    """이미지 전송과 상태 조회가 서로를 막지 않게 HTTP 요청을 분리합니다."""

    daemon_threads = True
    block_on_close = False

    def get_request(self):
        """연결이 응답 없이 Thread를 계속 점유하지 않도록 Timeout을 둡니다."""
        connection, address = super().get_request()
        connection.settimeout(30)
        return connection, address


class QuietRequestHandler(WSGIRequestHandler):
    """Cookie와 Prompt가 Access Log에 남지 않도록 기본 기록을 생략합니다."""

    def log_message(self, message_format, *arguments):
        """요청 URL과 인증 내용을 로그에 쓰지 않습니다."""
        return None


def configure_logging(data_directory):
    """수명주기와 서버 오류만 크기가 제한된 로그로 남깁니다."""
    log_directory = data_directory / 'web-server'
    log_directory.mkdir(parents=True, exist_ok=True)
    log_handler = RotatingFileHandler(log_directory / 'server.log', maxBytes=2_000_000, backupCount=3, encoding='utf-8')
    log_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    LOGGER.addHandler(log_handler)
    LOGGER.setLevel(logging.INFO)


def main():
    """설정과 데이터 잠금을 확보한 뒤 Port 8389에서 웹 서버를 실행합니다."""
    argument_parser = argparse.ArgumentParser(description='Anima Style Lab Browser server')
    argument_parser.add_argument('--host', default='0.0.0.0')
    argument_parser.add_argument('--port', default=8389, type=int)
    argument_parser.add_argument('--data-directory', type=Path, default=ROOT_DIRECTORY / 'data')
    argument_parser.add_argument('--set-password', action='store_true')
    argument_parser.add_argument('--secure-cookie', action='store_true')
    arguments = argument_parser.parse_args()
    data_directory = arguments.data_directory.resolve()
    configure_logging(data_directory)
    authentication = load_authentication(data_directory, arguments.set_password)
    if arguments.set_password:
        LOGGER.info('웹 접속 비밀번호를 변경했습니다. 실행 중인 서버는 재시작해야 반영됩니다.')
        return
    with DataDirectoryLock(data_directory):
        engine = Engine(data_directory, auto_connection=True)
        application = create_web_application(engine, authentication, arguments.secure_cookie)
        server = make_server(arguments.host, arguments.port, application, server_class=ThreadedWebServer, handler_class=QuietRequestHandler)
        server_identity_path = data_directory / 'web-server' / 'server.json'
        server_identity_path.write_text(json.dumps({'pid': os.getpid(), 'host': arguments.host, 'port': arguments.port}), encoding='utf-8')
        shutdown_requested = threading.Event()

        def request_shutdown(signal_number, stack_frame):
            """종료 요청을 받으면 HTTP 접수를 멈추고 Engine 저장으로 진행합니다."""
            if not shutdown_requested.is_set():
                shutdown_requested.set()
                threading.Thread(target=server.shutdown, daemon=True).start()

        signal.signal(signal.SIGINT, request_shutdown)
        signal.signal(signal.SIGTERM, request_shutdown)
        if hasattr(signal, 'SIGBREAK'):
            signal.signal(signal.SIGBREAK, request_shutdown)
        threading.Thread(target=application.style_lab_bridge.thumbnail_worker, daemon=True).start()
        engine.refresh_connection()
        LOGGER.info('Style Lab Web ready host=%s port=%s pid=%s', arguments.host, arguments.port, os.getpid())
        print(f'Style Lab Web: http://127.0.0.1:{arguments.port}', flush=True)
        try:
            server.serve_forever(poll_interval=0.25)
        finally:
            application.style_lab_bridge.shutdown()
            server.server_close()
            server_identity_path.unlink(missing_ok=True)
            LOGGER.info('Style Lab Web stopped')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        LOGGER.exception('웹 서버를 시작하거나 실행하는 중 오류가 발생했습니다.')
        raise
```
