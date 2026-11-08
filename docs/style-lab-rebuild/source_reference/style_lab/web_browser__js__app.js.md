# Source Snapshot: web_browser/js/app.js

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\web_browser\js\app.js`
- Original Byte SHA-256: `4901aa10f4243451f458d558beb85d345d9bbb915fedb2fc3f1933592437b8e4`
- Snapshot Text SHA-256: `4901aa10f4243451f458d558beb85d345d9bbb915fedb2fc3f1933592437b8e4`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```javascript
// App shell: sidebar, workflow stepper, router, status polling, toasts and keyboard routing.
import { get, post } from './api.js';
import { h, clear, morph, icon, toast, run, fmt, setMeta, promptViewer } from './ui.js';

const PAGES = {
  home:      { label: '홈', icon: 'home', load: () => import('./pages/home.js') },
  arena:     { label: '선별', icon: 'swords', load: () => import('./pages/arena.js') },
  evolution: { label: '진화', icon: 'dna', load: () => import('./pages/evolution.js') },
  locked:    { label: '융합', icon: 'zap', load: () => import('./pages/locked.js') },
  refine:    { label: '다듬기', icon: 'wand', load: () => import('./pages/refine.js') },
  styles:    { label: '그림체', icon: 'grid', load: () => import('./pages/styles.js') },
  library:   { label: '조합', icon: 'users', load: () => import('./pages/library.js') },
  free:      { label: '자유 생성', icon: 'brush', load: () => import('./pages/free.js') },
  settings:  { label: '설정', icon: 'settings', load: () => import('./pages/settings.js') },
};
const NAV = [
  ['워크플로', ['home', 'arena', 'evolution', 'locked', 'refine']],
  ['라이브러리', ['styles', 'library', 'free']],
  ['', ['settings']],
];
const STEP_ROUTES = ['library', 'arena', 'evolution', 'refine', 'refine'];

const app = {
  status: null,
  meta: null,
  // What /api/settings returns ({settings, connection, workflow}), kept here for every page. Fetched again
  // only when the server's copy changes (status.settings_rev), so a change made anywhere reaches all pages.
  conf: null,
  get settings() { return this.conf?.settings ?? {}; },
  route: null,
  params: {},
  page: null,
  go(route, params = {}) {
    const query = new URLSearchParams(params).toString();
    const hash = `#/${route}${query ? `?${query}` : ''}`;
    if (location.hash === hash) mount();
    else location.hash = hash;
  },
  async refresh() {
    await poll(true);
  },
  // What every button that changes something does: run the request (a success toast if ``okText``, the
  // error toast otherwise), then bring the status, the settings and the page up to date: the page reloads
  // its data in onStatus when ``force`` is set. On failure it throws (already shown), so the caller stops.
  async act(request, okText) {
    const result = await run(request, okText);
    await this.refresh();
    return result;
  },
  setFill(fill) {
    document.getElementById('content').classList.toggle('fill', fill);
  },
};

let lastEvent = 0;
let polling = null;
let confRev = null;

// ---------------------------------------------------------------- sidebar
function renderSidebar() {
  const s = app.status;
  const side = document.getElementById('sidebar');
  const badges = {};
  if (s) {
    const arenaWork = s.counts.newcomers + (s.tie ? 1 : 0);
    if (arenaWork) badges.arena = [arenaWork, 'hot'];
    else if (s.stage.route === 'arena') badges.arena = ['•', 'hot'];
    badges.evolution = [`${s.counts.generation}세대`, ''];
    if (s.improve || s.tune) badges.refine = ['진행', 'warn'];
    badges.styles = [fmt(s.counts.active), ''];
  }
  const nav = NAV.map(([label, routes]) => [
    label ? h('div', { class: 'nav-label' }, label) : h('div', { style: { height: '10px' } }),
    routes.map((route) => {
      const page = PAGES[route];
      const badge = badges[route];
      return h('button', { class: `nav-item ${app.route === route ? 'active' : ''}`, onclick: () => app.go(route) },
        icon(page.icon), h('span', {}, page.label),
        badge ? h('span', { class: `nav-badge ${badge[1]}` }, badge[0]) : null);
    }),
  ]);
  const job = s?.job;
  const jobCard = job && job.running ? h('div', { class: 'job-card fade-in' },
    h('div', { class: 'row' },
      h('div', { class: 'spinner' }), h('div', { class: 'title' }, job.label),
      h('button', { class: 'btn ghost icon-btn sm', 'aria-label': '생성 중단',
        onclick: () => app.act(post('/api/job/stop'), '현재 이미지가 끝나면 멈춥니다.') }, icon('stop'))),
    h('div', { class: 'bar' }, h('span', { style: { width: `${job.total ? (job.done / job.total) * 100 : 0}%` } })),
    h('div', { class: 'meta' }, h('span', { class: 'num' }, `${job.done} / ${job.total}`),
      job.failures ? h('span', { class: 'fail' }, `실패 ${job.failures}`) : h('span', {}, '생성 중'))) : null;
  const conn = s?.connection;
  // Checked at launch and whenever the address is changed; a failed check stays visible too.
  const subCard = !conn ? null : conn.error ? h('div', { class: 'sub-card' },
    h('div', {}, h('strong', { style: { color: 'var(--red)' } }, 'ComfyUI 연결 실패')),
    h('div', { class: 'muted' }, `${conn.checked} 확인 · 설정에서 다시 확인`))
    : h('div', { class: 'sub-card' },
      h('div', {}, h('strong', {}, 'ComfyUI 연결됨')),
      h('div', { class: 'muted' }, `${conn.version ? `v${conn.version} · ` : ''}${conn.checked} 확인`));
  morph(side,
    h('div', { class: 'brand' }, h('img', { class: 'brand-mark', src: '/static/icon.svg', alt: '' }),
      h('div', {}, h('div', { class: 'brand-name' }, 'Anima Style Lab'),
        h('div', { class: 'brand-sub' }, app.meta?.version ? `나만의 그림체 찾기 · v${app.meta.version}` : '나만의 그림체 찾기'))),
    nav,
    h('div', { class: 'sidebar-foot' }, jobCard, subCard));
  placeToasts();
}

// Keep the toast stack just above the sidebar's bottom cards, wherever they end up.
function placeToasts() {
  const top = document.querySelector('.sidebar-foot')?.firstElementChild?.getBoundingClientRect().top;
  const bottom = top ? window.innerHeight - top + 10 : 14;
  document.documentElement.style.setProperty('--toast-bottom', `${Math.round(bottom)}px`);
}
window.addEventListener('resize', placeToasts);

// ---------------------------------------------------------------- topbar
function renderTopbar() {
  const s = app.status;
  const bar = document.getElementById('topbar');
  if (!s) return clear(bar);
  const { step, names, todo, route, action } = s.stage;
  const steps = [];
  names.forEach((name, i) => {
    if (i) steps.push(h('span', { class: `step-link ${i <= step ? 'done' : ''}` }));
    const state = i < step ? 'done' : i === step ? 'current' : '';
    steps.push(h('button', { class: `step ${state}`, 'aria-label': name, onclick: () => app.go(STEP_ROUTES[i]) },
      h('span', { class: 'dot' }, i < step ? icon('check') : String(i + 1)), h('span', { class: 'name' }, name)));
  });
  morph(bar,
    h('nav', { class: 'stepper', 'aria-label': '워크플로 단계' }, steps),
    h('div', { class: 'todo' }, h('span', { class: 'label' }, '지금 할 일'), h('span', { class: 'text' }, todo),
      app.route === route && !s.stage.params?.focus ? null :  // a focus target (a settings section) is worth jumping to from the same page
      h('button', { class: 'btn primary sm pill', onclick: () => app.go(route, s.stage.params) }, action, icon('arrowRight'))));
  const line = document.querySelector('#progress-line span');
  const job = s.job;
  line.style.width = job && job.running && job.total ? `${Math.max(3, (job.done / job.total) * 100)}%` : '0';
}

// ---------------------------------------------------------------- status polling
async function poll(force = false) {
  try {
    const previous = app.status;
    const status = await get(`/api/status?since=${lastEvent}`);
    for (const event of status.events) {
      lastEvent = Math.max(lastEvent, event.id);
      toast(event.text, event.level);
    }
    if (status.settings_rev !== confRev) {
      app.conf = await get('/api/settings');
      confRev = status.settings_rev;
    }
    app.status = status;
    renderSidebar();
    renderTopbar();
    app.page?.onStatus?.(status, previous, force);
  } catch (error) {
    if (force) toast(error.message, 'error');
  }
}

function schedule() {
  clearTimeout(polling);
  const busy = app.status?.job?.running;
  // Same pace when hidden: Python is in the same process, and a hidden window still has to notice a relaunch.
  const delay = busy ? 1000 : 1800;
  polling = setTimeout(async () => { await poll(); schedule(); }, delay);
}

// ---------------------------------------------------------------- router
function parseHash() {
  const [path, query] = location.hash.replace(/^#\/?/, '').split('?');
  return { route: PAGES[path] ? path : 'home', params: Object.fromEntries(new URLSearchParams(query || '')) };
}

let mountToken = 0;
// Mark the content area while it has a scrollbar (see .content.scrolling). Watches the area itself (window
// resizes) and the page root inside it (the page re-rendering), re-attached on every mount.
// The padding change resizes what is being watched, so apply it on the next frame: done inside the callback,
// the browser reports "ResizeObserver loop completed with undelivered notifications".
const scrollWatch = new ResizeObserver(() => requestAnimationFrame(() => {
  const content = document.getElementById('content');
  content.classList.toggle('scrolling', content.offsetWidth - content.clientWidth > 0);  // a real scrollbar only (fill pages clip)
}));

async function mount() {
  const { route, params } = parseHash();
  const token = ++mountToken;
  app.page?.unmount?.();
  app.page = null;
  app.route = route;
  app.params = params;
  renderSidebar();
  renderTopbar();
  const content = document.getElementById('content');
  app.setFill(false);
  clear(content);
  scrollWatch.disconnect();  // drop the old page root
  scrollWatch.observe(content);
  const module = await PAGES[route].load();
  if (token !== mountToken) return;
  app.page = module.default;
  content.scrollTop = 0;
  try {
    await app.page.mount(content, app);
    for (const el of content.children) scrollWatch.observe(el);
  } catch (error) {
    toast(error.message, 'error');
  }
}

// ---------------------------------------------------------------- keyboard
document.addEventListener('keydown', (event) => {
  const tag = event.target.tagName;
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag) || event.target.isContentEditable) return;
  if (document.querySelector('.backdrop, .lightbox')) return;
  app.page?.onKey?.(event);
});

// ---------------------------------------------------------------- dropped pictures
// A file dropped anywhere on the window: a ComfyUI picture opens the prompt viewer (the first PNG, if several).
// Without this the window would try to open the file itself.
document.addEventListener('dragover', (event) => {
  if (event.dataTransfer?.types.includes('Files')) event.preventDefault();
});
document.addEventListener('drop', (event) => {
  if (!event.dataTransfer?.types.includes('Files')) return;
  event.preventDefault();
  const file = [...event.dataTransfer.files].find((f) => f.type === 'image/png');
  if (!file) return toast('ComfyUI로 만든 PNG 그림을 놓아 주세요.', 'warn');
  if (document.querySelector('.backdrop')) return;  // a dialog is open: one thing at a time
  promptViewer(app, file).catch(() => {});  // a failed request was already shown by run()
});

// Never fail silently: anything the pages did not catch shows up as a toast.
window.addEventListener('error', (event) => toast(`화면에서 오류가 났습니다: ${event.message}`, 'error'));
window.addEventListener('unhandledrejection', (event) => {
  if (event.reason?.shown) return;  // already shown by run()
  toast(event.reason?.message || String(event.reason), 'error');
});

document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });  // catch up at once after the browser throttled a hidden window
window.addEventListener('hashchange', mount);

(async function start() {
  try {
    app.meta = await get('/api/meta');
    setMeta(app.meta);
  } catch (error) {
    toast(error.message, 'error');
  }
  await poll();
  if (!location.hash) location.replace('#/home');
  await mount();
  schedule();
})();

export default app;
```
