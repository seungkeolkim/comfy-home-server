# Source Snapshot: web_browser/browser.css

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\web_browser\browser.css`
- Original Byte SHA-256: `ba06526a7e8658dd84c9ca7578833875190e437161de08914b31316a9f63d271`
- Snapshot Text SHA-256: `ba06526a7e8658dd84c9ca7578833875190e437161de08914b31316a9f63d271`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```css
/* Desktop은 기존 배치를 사용하고 모바일만 문서 흐름으로 전환합니다. */
body { overflow: hidden; }
[hidden] { display: none !important; }
.sidebar { padding-bottom: 72px; }
.browser-desktop-logout { position: fixed; left: 18px; bottom: 16px; width: 170px; z-index: 20; }
#app { min-width: 0; height: 100dvh; grid-template-columns: 208px minmax(0, 1fr); }
.content { padding: 24px; }
.content.scrolling { padding-right: 12px; }
.topbar { padding: 14px 24px; gap: 12px; }
.todo { max-width: 60%; }
.brand { gap: 8px; padding-left: 2px; }
.brand-name { font-size: 14px; }
.brand-sub { overflow-wrap: anywhere; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
.browser-mobile-header, .browser-mobile-navigation, .browser-comparison-controls, .browser-vote-controls { display: none; }
#browser-menu-dialog { width: min(400px, calc(100% - 28px)); max-height: calc(100dvh - 48px); border: 1px solid var(--line-2); border-radius: 16px; padding: 18px; background: var(--panel); color: var(--text); }
#browser-menu-dialog::backdrop { background: rgba(0, 0, 0, .65); }
#browser-full-menu { display: grid; gap: 5px; margin-bottom: 14px; }
.browser-login-page { display: grid; place-items: center; min-height: 100dvh; padding: 24px; overflow: auto; }
.browser-login-card { width: min(100%, 390px); border: 1px solid var(--line-2); border-radius: 20px; padding: 30px; background: var(--panel); }
.browser-login-card h1 { font-size: 24px; margin: 20px 0 4px; }
.browser-login-card > p { color: var(--text-2); margin: 0 0 28px; }
.browser-login-card .input { width: 100%; font-size: 16px; margin: 8px 0 18px; }
.browser-login-card .btn { width: 100%; }
#browser-login-error { color: var(--red); min-height: 24px; margin: 12px 0 0; }
@media (max-width: 1100px) {
  .topbar { flex-wrap: wrap; }
  .todo { max-width: 100%; width: 100%; }
}
@media (max-width: 760px) {
  html, body { height: auto; min-height: 100%; overflow: auto; }
  body { padding: 62px 0 calc(82px + env(safe-area-inset-bottom)); }
  #app { display: block; min-width: 0; height: auto; }
  .sidebar, .topbar, .progress-line { display: none; }
  .browser-desktop-logout { display: none; }
  .main { display: block; }
  .content, .content.scrolling, .content.fill { display: block; overflow: visible; padding: 17px 13px 22px; min-height: 0; --tile: 130px; }
  .page-col, .page-col.scroll, .fill-card, .fuse-main, .settings-stack { height: auto; min-height: 0; overflow: visible; flex: none; }
  .fill-grid, .fuse-layout { display: grid; grid-template-columns: minmax(0, 1fr) !important; grid-template-rows: auto; min-height: 0; flex: none; }
  .fill-grid > *, .fuse-layout > * { min-width: 0; }
  .page-head .title-line { flex-wrap: wrap; }
  .page-head h1 { font-size: 23px; }
  .page-head { margin-bottom: 17px; }
  .page-head p { font-size: 13px; }
  .btn, .segmented button, .nav-item { min-height: 44px; }
  .input, .textarea, .select { font-size: 16px; max-width: 100%; }
  .row { flex-wrap: wrap; }
  .card { padding: 15px; }
  .browser-mobile-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; position: fixed; inset: 0 0 auto; height: 62px; padding: 10px 14px; border-bottom: 1px solid var(--line); background: var(--panel); z-index: 40; }
  .browser-mobile-brand { display: flex; align-items: center; gap: 9px; font-weight: 600; }
  .browser-mobile-navigation { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); position: fixed; inset: auto 0 0; padding: 8px 5px calc(8px + env(safe-area-inset-bottom)); background: var(--panel); border-top: 1px solid var(--line); z-index: 40; }
  .browser-mobile-navigation button { border: 0; background: transparent; min-height: 47px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; font-size: 11px; color: var(--text-2); }
  .browser-mobile-navigation button.active { color: var(--accent-2); }
  .browser-mobile-navigation svg { width: 19px; height: 19px; }
  .browser-comparison-controls:not([hidden]) { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 7px; padding: 9px 13px; background: var(--bg); z-index: 15; }
  #browser-comparison-controls { position: fixed; top: 62px; left: 0; right: 0; }
  body:has(#browser-comparison-controls:not([hidden])) { padding-top: 130px; }
  .browser-comparison-controls .segmented button { padding: 7px 11px; }
  .arena-head .context .detail { font-size: 12px; white-space: normal; }
  .arena-controls { display: flex; flex-wrap: wrap; gap: 6px; }
  .arena-controls > .spacer { display: none; }
  .arena-controls .segmented { flex: 1; display: flex; }
  .arena-controls .segmented button { flex: 1; padding: 5px 7px; white-space: nowrap; font-size: 12px; }
  .arena-controls > .btn { padding: 7px 9px; }
  .duel { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 9px; flex: none; }
  .fighter { padding: 8px; min-width: 0; gap: 8px; }
  .fighter[data-side="a"] { grid-column: 1; grid-row: 1; }
  .fighter[data-side="b"] { grid-column: 2; grid-row: 1; }
  .fighter .art { flex: none; min-height: 0; width: 100%; height: auto; aspect-ratio: 3 / 5; }
  .fighter-info { flex-wrap: wrap; gap: 7px; min-height: 74px; }
  .fighter-info .tier.lg { height: 28px; min-width: 28px; font-size: 13px; }
  .fighter-info .elo { font-size: 18px; }
  .fighter-info .meta { font-size: 11px; }
  .fighter-actions { width: 100%; margin: 0; display: flex; flex-wrap: wrap; }
  .fighter-actions .btn { min-height: 36px; padding: 4px; font-size: 11px; }
  .fighter-tags { display: block; }
  .fighter-tags .tags { max-width: 100%; }
  .fighter-tags > .btn { min-height: 36px; padding: 4px; }
  .fighter .pick { width: 100%; padding: 9px 3px; min-height: 48px; font-size: 12px; white-space: normal; }
  .fighter .pick kbd { display: none; }
  .versus { grid-column: 1 / -1; grid-row: 2; display: flex; flex-direction: row; justify-content: center; gap: 10px; padding: 5px; }
  .vs-orb { display: none; }
  .pick-similar { width: auto; min-height: 44px; }
  body[data-comparison-layout="single"] .duel { display: block; }
  body[data-comparison-layout="single"] .fighter { display: none; }
  body[data-comparison-layout="single"][data-comparison-side="a"] .fighter[data-side="a"],
  body[data-comparison-layout="single"][data-comparison-side="b"] .fighter[data-side="b"] { display: flex; }
  body[data-comparison-layout="single"] .fighter .art { aspect-ratio: 4 / 5; max-height: 58dvh; }
  body[data-comparison-layout="single"] .fighter .pick { display: none; }
  body[data-comparison-layout="single"] .fighter-info { min-height: 0; }
  body[data-comparison-layout="single"] .fighter-actions { width: auto; margin-left: auto; }
  body[data-comparison-layout="single"] .versus { margin-top: 10px; }
  .browser-vote-controls:not([hidden]) { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; position: fixed; left: 0; right: 0; bottom: calc(70px + env(safe-area-inset-bottom)); padding: 10px 13px; z-index: 35; background: var(--bg); border-top: 1px solid var(--line); }
  .browser-single-voting { padding-bottom: calc(150px + env(safe-area-inset-bottom)); }
  .preview-layout { display: flex; flex-direction: column; min-height: 0; }
  .preview-main, .preview-side { flex: none; width: 100%; min-width: 0; }
  .preview-side { max-height: none; overflow: visible; }
  .split, .split.fill { display: flex; flex-direction: column; height: auto; min-height: 0; gap: 16px; }
  .split.fill .split-main, .split.fill .split-list { display: block; width: 100%; flex: none; height: auto; overflow: visible; margin: 0; padding: 0; }
  .split.fill .detail { width: 100%; max-height: none; overflow: visible; padding: 0; margin: 0; }
  .detail .art { max-height: 65dvh; }
  .combo-cols { display: grid; grid-template-columns: minmax(0, 1fr); flex: none; min-height: 0; }
  .combo-cols .side, .side-body { height: auto; min-height: 0; flex: none; }
  .side-list { max-height: none; height: auto; overflow-x: auto; }
  .side-rules { grid-template-columns: minmax(0, 1fr); }
  .range-pair .input { padding-left: 9px; padding-right: 4px; font-size: 16px; }
  .selection-bar { left: 10px; right: 10px; bottom: calc(84px + env(safe-area-inset-bottom)); flex-wrap: wrap; transform: none; width: auto; }
  .gallery, .gallery.lg { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .table-wrap { overflow-x: auto; max-width: 100%; }
  .data { min-width: 420px; }
  .library-layout, .library-sides, .tune-start, .home-lower { display: flex; flex-direction: column; }
  .library-sides > *, .library-layout > * { width: 100%; min-width: 0; }
  .settings-columns .grid { grid-template-columns: minmax(0, 1fr) !important; }
  .settings-columns .grid > * { grid-column: auto !important; }
  .settings-columns .textarea.grow { min-height: 160px; }
  .reset-row { align-items: flex-start; gap: 10px; }
  .toasts { left: 12px; right: 12px; bottom: calc(84px + env(safe-area-inset-bottom)) !important; width: auto; max-width: none; z-index: 90; }
  .lightbox.with-info { flex-direction: column; overflow: auto; padding: 12px; }
  .lightbox img { max-width: 100%; max-height: 65dvh; }
  .lightbox-info { width: 100%; max-width: none; max-height: none; }
  .backdrop { padding: 10px; }
  .modal { width: 100%; max-height: calc(100dvh - 30px); overflow: auto; }
  .browser-login-page { padding: 24px; }
}
```
