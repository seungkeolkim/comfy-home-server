# Source Snapshot: web_browser/js/browser.js

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\web_browser\js\browser.js`
- Original Byte SHA-256: `762a4ac0029b648165df4546eb2c0a917a7b294d81de8b5b8f2c3a6ff4b8fe74`
- Snapshot Text SHA-256: `762a4ac0029b648165df4546eb2c0a917a7b294d81de8b5b8f2c3a6ff4b8fe74`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```javascript
import app from './app.js';
import { post } from './api.js';
import { h, icon, toast } from './ui.js';

const menuDialog = document.getElementById('browser-menu-dialog');
const mobileNavigation = document.getElementById('browser-mobile-navigation');
const fullMenu = document.getElementById('browser-full-menu');
const comparisonControls = document.getElementById('browser-comparison-controls');
const imageSelector = document.getElementById('browser-image-selector');
const voteControls = document.getElementById('browser-vote-controls');
const menuEntries = [
  ['home', '홈', 'home'], ['arena', '선별', 'swords'], ['evolution', '진화', 'dna'],
  ['locked', '융합', 'zap'], ['refine', '다듬기', 'wand'], ['styles', '그림체', 'grid'],
  ['library', '조합', 'users'], ['free', '자유 생성', 'brush'], ['settings', '설정', 'settings'],
];
let comparisonLayout = 'pair';
let comparisonSide = 'a';
try { comparisonLayout = localStorage.getItem('style-lab-comparison-layout') === 'single' ? 'single' : 'pair'; } catch {}

/** 메뉴를 이동하고 모바일 메뉴를 닫습니다. */
function navigateBrowser(route) {
  app.go(route);
  menuDialog.close();
  window.scrollTo({ top: 0 });
}

/** 현재 인증 Session을 종료합니다. */
async function signOutBrowser() {
  try { await post('/api/logout'); location.replace('/login'); }
  catch (error) { toast(error.message, 'error'); }
}

/** 현재 Route에 맞춰 PC와 모바일에서 사용할 메뉴를 만듭니다. */
function renderBrowserNavigation() {
  const mobileEntries = ['arena', 'styles', 'evolution', 'refine'].map(route => menuEntries.find(entry => entry[0] === route));
  const navigationButtons = [];
  for (const [route, label, iconName] of mobileEntries) {
    navigationButtons.push(h('button', {
      type: 'button', class: app.route === route ? 'active' : '',
      'aria-current': app.route === route ? 'page' : null, onclick: () => navigateBrowser(route),
    }, icon(iconName), h('span', {}, label)));
  }
  navigationButtons.push(h('button', { type: 'button', onclick: () => menuDialog.showModal() }, icon('settings'), h('span', {}, '더보기')));
  mobileNavigation.replaceChildren(...navigationButtons);
  const fullMenuButtons = [];
  for (const [route, label, iconName] of menuEntries) {
    fullMenuButtons.push(h('button', { class: 'nav-item', type: 'button', onclick: () => navigateBrowser(route) }, icon(iconName), label));
  }
  fullMenuButtons.push(h('button', { class: 'btn', type: 'button', onclick: signOutBrowser }, '로그아웃'));
  fullMenu.replaceChildren(...fullMenuButtons);
}

/** 비교 표시와 원래 투표 버튼의 준비 상태를 동기화합니다. */
function renderBrowserComparison() {
  const duel = document.querySelector('.duel');
  const isComparing = app.route === 'arena' && Boolean(duel);
  comparisonControls.hidden = !isComparing;
  imageSelector.hidden = comparisonLayout !== 'single';
  voteControls.hidden = !isComparing || comparisonLayout !== 'single';
  document.body.dataset.comparisonLayout = comparisonLayout;
  document.body.dataset.comparisonSide = comparisonSide;
  document.body.classList.toggle('browser-single-voting', isComparing && comparisonLayout === 'single');
  for (const layoutButton of comparisonControls.querySelectorAll('[data-comparison-layout]')) {
    layoutButton.classList.toggle('on', layoutButton.dataset.comparisonLayout === comparisonLayout);
    layoutButton.setAttribute('aria-pressed', String(layoutButton.dataset.comparisonLayout === comparisonLayout));
  }
  for (const sideButton of imageSelector.querySelectorAll('[data-comparison-side]')) {
    sideButton.classList.toggle('on', sideButton.dataset.comparisonSide === comparisonSide);
    sideButton.setAttribute('aria-pressed', String(sideButton.dataset.comparisonSide === comparisonSide));
  }
  for (const voteButton of voteControls.querySelectorAll('[data-browser-vote]')) {
    const originalButton = duel?.querySelector(`.fighter[data-side="${voteButton.dataset.browserVote}"] .pick`);
    const disabled = !originalButton || originalButton.disabled;
    if (voteButton.disabled !== disabled) voteButton.disabled = disabled;
  }
}

/** 모바일 비교 방식과 A/B 보기 선택을 저장합니다. */
function changeComparisonLayout(event) {
  const layoutButton = event.target.closest('[data-comparison-layout]');
  const sideButton = event.target.closest('[data-comparison-side]');
  if (layoutButton) {
    comparisonLayout = layoutButton.dataset.comparisonLayout;
    try { localStorage.setItem('style-lab-comparison-layout', comparisonLayout); } catch {}
  }
  if (sideButton) comparisonSide = sideButton.dataset.comparisonSide;
  renderBrowserComparison();
}

/** 하단 A/B 선택을 기존 투표 처리로 전달합니다. */
function selectComparisonImage(event) {
  const voteButton = event.target.closest('[data-browser-vote]');
  if (!voteButton || voteButton.disabled) return;
  document.querySelector(`.fighter[data-side="${voteButton.dataset.browserVote}"] .pick`)?.click();
}

document.getElementById('browser-menu-button').addEventListener('click', () => menuDialog.showModal());
document.getElementById('browser-desktop-logout').addEventListener('click', signOutBrowser);
document.getElementById('browser-menu-close').addEventListener('click', () => menuDialog.close());
comparisonControls.addEventListener('click', changeComparisonLayout);
voteControls.addEventListener('click', selectComparisonImage);
window.addEventListener('hashchange', () => { comparisonSide = 'a'; renderBrowserNavigation(); renderBrowserComparison(); });
new MutationObserver(renderBrowserNavigation).observe(document.getElementById('sidebar'), { childList: true });
new MutationObserver(renderBrowserComparison).observe(document.getElementById('content'), { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled'] });
renderBrowserNavigation();
renderBrowserComparison();
```
