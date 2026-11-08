# Source Snapshot: tests_web/test_web_server.py

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\tests_web\test_web_server.py`
- Original Byte SHA-256: `29f5a627a4c8dcdc52f193dc1a2d64effff8b7255b7e488a424715b9e9d11b36`
- Snapshot Text SHA-256: `29f5a627a4c8dcdc52f193dc1a2d64effff8b7255b7e488a424715b9e9d11b36`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```python
"""인증·실제 상태 저장·잘못된 비교 방지·ZIP 경계를 검증합니다."""

from http.cookiejar import CookieJar
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener
import zipfile

from fixtures import TEST_PASSWORD, ROOT_DIRECTORY, create_fixture_engine, web_server, core


class WebServerTests(unittest.TestCase):
    """격리된 임시 데이터에 대해서만 HTTP 기능을 실행합니다."""

    def setUp(self):
        """테스트 전용 Engine과 임의 Port의 HTTP Server를 시작합니다."""
        self.temporary_directory = tempfile.TemporaryDirectory(prefix='style-lab-web-test-')
        self.data_directory = Path(self.temporary_directory.name)
        self.engine = create_fixture_engine(self.data_directory)
        self.authentication = web_server.WebAuthentication(web_server.password_configuration(TEST_PASSWORD))
        application = web_server.create_web_application(self.engine, self.authentication)
        self.server = web_server.make_server('127.0.0.1', 0, application,
            server_class=web_server.ThreadedWebServer, handler_class=web_server.QuietRequestHandler)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.base_url = f'http://127.0.0.1:{self.server.server_port}'
        self.client = build_opener(HTTPCookieProcessor(CookieJar()))
        self.csrf_token = ''

    def tearDown(self):
        """테스트 서버를 닫고 테스트 전용 자료만 정리합니다."""
        self.engine.stop_job()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=5)
        self.temporary_directory.cleanup()

    def send_request(self, path, payload=None, csrf=True, extra_headers=None):
        """테스트용 Cookie와 JSON으로 요청하고 오류 응답도 반환합니다."""
        headers = dict(extra_headers or {})
        body = None
        if payload is not None:
            headers['Content-Type'] = 'application/json'
            if csrf:
                headers['X-CSRF-Token'] = self.csrf_token
            body = json.dumps(payload).encode('utf-8')
        http_request = Request(self.base_url + path, data=body, headers=headers)
        try:
            return self.client.open(http_request, timeout=10)
        except HTTPError as error:
            return error

    def sign_in(self):
        """테스트 비밀번호로 로그인하고 CSRF Token을 확보합니다."""
        with self.send_request('/api/login', {'password': TEST_PASSWORD}) as login_response:
            self.assertEqual(login_response.status, 200)
            self.assertIn('HttpOnly', login_response.headers['Set-Cookie'])
            self.assertIn('samesite=strict', login_response.headers['Set-Cookie'].lower())
        with self.send_request('/api/session') as session_response:
            self.csrf_token = json.load(session_response)['data']['csrf_token']

    def test_authentication_and_path_boundaries(self):
        """상태·이미지·설정 파일은 인증 없이 공개되지 않아야 합니다."""
        for request_path in ('/api/status', '/api/loras/loading', '/img/fixture-0.png', '/static/js/app.js'):
            with self.send_request(request_path) as result:
                self.assertEqual(result.status, 401)
        self.sign_in()
        for request_path in ('/static/../app/core.py', '/img/..%2fstate.json', '/data/web-server/authentication.json'):
            with self.send_request(request_path) as result:
                self.assertEqual(result.status, 404)
        for request_path in ('/api/status', '/api/combos', '/api/artists', '/api/loras', '/api/loras/loading', '/api/evolution', '/api/merge', '/api/tune', '/api/settings', '/api/meta', '/api/free'):
            with self.send_request(request_path) as result:
                self.assertEqual(result.status, 200, request_path)
                self.assertTrue(json.load(result)['ok'])

    def test_expected_encoder_notice_is_available_without_toast_events(self):
        """TE 미적용 안내는 인증된 API로 조회되고 Warning Event는 발생하지 않습니다."""
        self.sign_in()
        report = core.lora_load_report([], [{'t': 1, 'm': 'lora key not loaded: lora_te1_layers_0_mlp.lora_up.weight'}])
        self.engine._lora_report(['first.safetensors', 'second.safetensors'], 'test-style', 42, report)
        with self.send_request('/api/loras/loading') as result:
            notice = json.load(result)['data']
            self.assertEqual(notice['counts']['text_encoder'], 1)
            self.assertFalse(notice['has_warning'])
        with self.send_request('/api/status') as result:
            events = json.load(result)['data']['events']
            self.assertFalse([event for event in events if event['level'] == 'warn'])

    def test_csrf_and_origin_protection(self):
        """인증 Cookie만 있거나 Origin이 다른 변경 요청은 거부합니다."""
        self.sign_in()
        for token_enabled, extra_headers in ((False, {}), (True, {'Origin': 'http://another-site.invalid'})):
            with self.send_request('/api/settings', {'changes': {'steps': 16}}, csrf=token_enabled, extra_headers=extra_headers) as result:
                self.assertEqual(result.status, 403)
        self.assertEqual(self.engine.settings()['steps'], 12)
        with self.send_request('/api/settings', {'changes': {'steps': 16}}) as result:
            self.assertEqual(result.status, 200)
        saved_state = json.loads(self.engine.state_file.read_text(encoding='utf-8'))
        self.assertEqual(saved_state['ui_state']['steps'], 16)

    def test_vote_persistence_and_stale_pair(self):
        """한 번 투표를 저장하고 이전 화면의 중복 투표는 거부합니다."""
        self.sign_in()
        with self.send_request('/api/match') as result:
            match = json.load(result)['data']
        expected_match = {'kind': match['kind'], 'a': match['a']['id'], 'b': match['b']['id']}
        vote_payload = {'side': 'a', 'expected_match': expected_match}
        with self.send_request('/api/vote', vote_payload) as result:
            self.assertEqual(result.status, 200)
        self.assertEqual(len(self.engine.state['history']), 1)
        with self.send_request('/api/vote', vote_payload) as result:
            self.assertEqual(result.status, 409)
        self.assertEqual(len(self.engine.state['history']), 1)
        with self.send_request('/api/undo', {}) as result:
            self.assertEqual(result.status, 200)
        self.assertEqual(len(self.engine.state['history']), 0)

    def test_zip_export_and_desktop_actions(self):
        """다운로드에는 상태와 이미지만 포함하고 서버 PC 실행은 거부합니다."""
        self.sign_in()
        with self.send_request('/api/data/export', {}) as result:
            self.assertEqual(result.status, 200)
            exported_archive = zipfile.ZipFile(io.BytesIO(result.read()))
        self.assertIn('state.json', exported_archive.namelist())
        self.assertEqual(len([name for name in exported_archive.namelist() if name.startswith('images/')]), 12)
        self.assertNotIn('authentication.json', exported_archive.namelist())
        with self.send_request('/api/open-folder', {}) as result:
            self.assertEqual(result.status, 400)

    def test_generation_uses_custom_workflow_without_comfy(self):
        """실제 생성 경로가 NegPip Workflow와 음수 가중치를 전달하는지 확인합니다."""
        self.sign_in()
        captured_requests = []
        original_generator = self.engine._generate

        def capture_generation(settings, style, seed, stop_event, log=None):
            """ComfyUI 호출 대신 전달된 설정만 기록합니다."""
            captured_requests.append((settings, style))
            return original_generator(settings, style, seed, stop_event, log)

        self.engine._generate = capture_generation
        with self.send_request('/api/generate/free', {'prompt': '(@rurudo:1.2), (blurry:-1)'}) as result:
            self.assertEqual(result.status, 200)
        for attempt in range(200):
            if self.engine.job and not self.engine.job['running']:
                break
            time.sleep(0.01)
        self.assertEqual(len(self.engine.state['free_results']), 1)
        self.assertEqual(captured_requests[0][0]['workflow']['style_lab_negpip']['class_type'], 'CLIPNegPip')
        self.assertIn('(blurry:-1)', captured_requests[0][1])

    def test_zip_import_restores_browser_state(self):
        """Browser 업로드로 복원한 뒤 융합 조회까지 정상이어야 합니다."""
        self.sign_in()
        archive_stream = io.BytesIO()
        self.engine.export_data(archive_stream)
        boundary = 'style-lab-test-upload-boundary'
        multipart_bytes = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="archive"; filename="backup.zip"\r\nContent-Type: application/zip\r\n\r\n'.encode()
            + archive_stream.getvalue() + f'\r\n--{boundary}--\r\n'.encode()
        )
        import_request = Request(self.base_url + '/api/data/import', data=multipart_bytes, headers={
            'Content-Type': f'multipart/form-data; boundary={boundary}', 'X-CSRF-Token': self.csrf_token,
        })
        with self.client.open(import_request, timeout=10) as result:
            self.assertEqual(result.status, 200)
            self.assertEqual(json.load(result)['data']['combos'], 12)
        with self.send_request('/api/merge') as result:
            self.assertEqual(result.status, 200)

    def test_login_rate_limit_and_expired_session(self):
        """반복 로그인 실패와 만료된 Session을 거부합니다."""
        for attempt in range(8):
            with self.send_request('/api/login', {'password': 'incorrect-password'}) as result:
                self.assertEqual(result.status, 401)
        with self.send_request('/api/login', {'password': TEST_PASSWORD}) as result:
            self.assertEqual(result.status, 429)
        self.authentication.login_failures.clear()
        self.sign_in()
        for session_details in self.authentication.sessions.values():
            session_details['expires_at'] = 0
        with self.send_request('/api/status') as result:
            self.assertEqual(result.status, 401)

    def test_data_mutex_rejects_another_process(self):
        """다른 프로세스가 같은 폴더의 잠금을 획득하지 못해야 합니다."""
        from data_access import DataDirectoryLock
        with DataDirectoryLock(self.data_directory):
            child_script = 'import sys;sys.path.insert(0,sys.argv[1]);from data_access import DataDirectoryLock;lock=DataDirectoryLock(sys.argv[2]);lock.__enter__()'
            child_result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', child_script, str(ROOT_DIRECTORY / 'app'), str(self.data_directory)], capture_output=True, text=True, encoding='utf-8')
            self.assertNotEqual(child_result.returncode, 0)
            self.assertIn('DataDirectoryInUseError', child_result.stderr)


if __name__ == '__main__':
    unittest.main()
```
