# Source Snapshot: web/index.html

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\web\index.html`
- Original Byte SHA-256: `8cdbe0640e06bbd5b8e7f907ab11c7e615d3e9af15bae34039ed016db66d7ae8`
- Snapshot Text SHA-256: `8cdbe0640e06bbd5b8e7f907ab11c7e615d3e9af15bae34039ed016db66d7ae8`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Anima Style Lab</title>
<!-- PNGs so the taskbar gets a sharp icon (it does not scale the SVG well) -->
<link rel="icon" type="image/png" sizes="512x512" href="/static/icon-512.png">
<link rel="icon" type="image/png" sizes="192x192" href="/static/icon-192.png">
<link rel="icon" type="image/png" sizes="32x32" href="/static/icon-32.png">
<link rel="icon" type="image/svg+xml" href="/static/icon.svg">
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<div id="app">
  <aside class="sidebar" id="sidebar"></aside>
  <div class="main">
    <header class="topbar" id="topbar"></header>
    <div class="progress-line" id="progress-line"><span></span></div>
    <main class="content" id="content" tabindex="-1"></main>
  </div>
</div>
<div class="toasts" id="toasts" role="status" aria-live="polite"></div>
<div id="overlay-root"></div>
<script type="module" src="/static/js/app.js"></script>
</body>
</html>
```
