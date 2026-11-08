# Runtime 준비 참고

원본은 Windows Embedded Python 3.14 계열입니다. 아래는 설치 Metadata 관측값이며 새 앱의 최소 의존성 목록과 같지 않습니다.
Engine은 주로 Standard Library를 사용하고, 현재 Web/이미지 경로는 Bottle/Pillow가 필요합니다. Desktop은 pywebview, WebView2와 Windows 통합 의존성이 추가됩니다.
Runtime 실행 파일·DLL·바이너리 아이콘·모델·Custom Nodes는 이 문서 묶음에 포함하지 않습니다.

| Distribution | 관측 Version |
| --- | --- |
| bottle | 0.13.4 |
| cffi | 2.1.1 |
| clr_loader | 0.3.1 |
| pillow | 12.3.0 |
| proxy_tools | 0.1.0 |
| pycparser | 3.11 |
| pythonnet | 3.2.1 |
| pywebview | 6.2.1 |
| truststore | 0.10.4 |
| typing_extensions | 4.16.0 |
