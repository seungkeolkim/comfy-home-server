# Source Snapshot: web_browser/index.html

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\web_browser\index.html`
- Original Byte SHA-256: `9534074642023b3dc6f470b2e5dce4bcf1c33b676c3fe24be600b28da68ffdac`
- Snapshot Text SHA-256: `9534074642023b3dc6f470b2e5dce4bcf1c33b676c3fe24be600b28da68ffdac`
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
<link rel="stylesheet" href="/static/browser.css">
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
<button id="browser-desktop-logout" class="btn browser-desktop-logout" type="button">로그아웃</button>
<header class="browser-mobile-header">
  <div class="browser-mobile-brand"><img src="/static/icon.svg" width="30" height="30" alt=""><span>Anima Style Lab</span></div>
  <button class="btn sm" id="browser-menu-button" type="button">메뉴</button>
</header>
<div id="browser-comparison-controls" class="browser-comparison-controls" hidden>
  <div class="segmented" aria-label="이미지 비교 방식"><button type="button" data-comparison-layout="pair">나란히</button><button type="button" data-comparison-layout="single">한 장씩</button></div>
  <div class="segmented" id="browser-image-selector" aria-label="비교 이미지" hidden><button type="button" data-comparison-side="a">A 보기</button><button type="button" data-comparison-side="b">B 보기</button></div>
</div>
<div id="browser-vote-controls" class="browser-vote-controls" hidden><button class="btn primary" type="button" data-browser-vote="a">A 선택</button><button class="btn primary" type="button" data-browser-vote="b">B 선택</button></div>
<nav id="browser-mobile-navigation" class="browser-mobile-navigation" aria-label="모바일 메뉴"></nav>
<dialog id="browser-menu-dialog" aria-label="전체 메뉴"><div id="browser-full-menu"></div><button class="btn" id="browser-menu-close" type="button">닫기</button></dialog>
<script type="module" src="/static/js/app.js"></script>
<script type="module" src="/static/js/browser.js"></script>
</body>
</html>
```
