# Source Snapshot: tests_web/serve_fixture.py

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\tests_web\serve_fixture.py`
- Original Byte SHA-256: `ea493c683cb1a2f4794789a85429acb80d936d67cd32625d70d6eba33c129d0a`
- Snapshot Text SHA-256: `ea493c683cb1a2f4794789a85429acb80d936d67cd32625d70d6eba33c129d0a`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```python
"""Browser 검사에만 사용하는 별도 Engine과 Port를 시작합니다."""

from pathlib import Path
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import TEST_PASSWORD, create_fixture_engine, web_server


def main():
    """실제 데이터와 ComfyUI를 사용하지 않는 임시 서버를 실행합니다."""
    with tempfile.TemporaryDirectory(prefix='style-lab-browser-test-') as directory_name:
        fixture_engine = create_fixture_engine(Path(directory_name))
        authentication = web_server.WebAuthentication(web_server.password_configuration(TEST_PASSWORD))
        application = web_server.create_web_application(fixture_engine, authentication)
        server = web_server.make_server('127.0.0.1', 18389, application,
            server_class=web_server.ThreadedWebServer, handler_class=web_server.QuietRequestHandler)
        print('Browser fixture: http://127.0.0.1:18389', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
```
