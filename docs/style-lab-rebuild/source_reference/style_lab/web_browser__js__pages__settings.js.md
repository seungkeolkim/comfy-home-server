# Source Snapshot: web_browser/js/pages/settings.js

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\web_browser\js\pages\settings.js`
- Original Byte SHA-256: `3e333dd5a6b7c76cd986c2e444b04d21d32839b9c91c833254489c669112f8ff`
- Snapshot Text SHA-256: `3e333dd5a6b7c76cd986c2e444b04d21d32839b9c91c833254489c669112f8ff`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```javascript
// 설정 — everything saves as you type. The combo rules are edited on 조합.
import { get, post, keepDraft, downloadArchiveFile } from '../api.js';
import { h, morph, limits, icon, toast, fmt, confirmDialog, promptDialog, pageHead, card } from '../ui.js';

// The settings themselves are app.conf (one copy for every page).
let root, app;
const pending = {};
let timer = null;

// Typing only remembers the text; it is saved once, when the field is left (its change event),
// on a tab switch or leaving the page, or as the window closes (Python keeps the draft for that).
function stage(key, value) {
  pending[key] = value;
  if (key in s()) s()[key] = value;  // a re-render (tab switch) before the save returns keeps what was typed
  keepDraft({ ...pending });
}

function save(key, value) {
  stage(key, value);
  clearTimeout(timer);
  timer = setTimeout(flush, 450);
}

async function flush() {
  const changes = { ...pending };
  for (const key of Object.keys(pending)) delete pending[key];
  if (!Object.keys(changes).length) return;
  try {
    app.conf.settings = await post('/api/settings', { changes });
    keepDraft({ ...pending });  // saved: only what was typed since is left to save on close
    markSaved();
    app.refresh();
  } catch (error) {
    keepDraft({ ...pending });  // refused: like any refused change, it is not saved on close either
    toast(error.message, 'error');
    // The server kept nothing of a refused change: show what is really saved again.
    app.conf = await get('/api/settings').catch(() => app.conf);
    render();
  }
}

// Same bottom-left popup as every other notice; typing is debounced, so one per pause.
function markSaved() {
  toast('저장했습니다.', 'ok', 1600);
}

const s = () => app.conf.settings;

function field(label, control, help) {
  return h('div', { class: 'field' }, h('label', {}, label), control, help ? h('div', { class: 'help' }, help) : null);
}

function number(key, { step = 1, width } = {}) {
  // The spin buttons, arrow keys and wheel each change the value: remember every step, save once when the
  // field is left (or Enter), like the text fields. Its limits come from the server's one table.
  return h('input', { class: 'input num', type: 'number', step, ...limits(key), value: s()[key], style: width ? { width } : null,
    oninput: (e) => { const v = e.currentTarget.value; if (v !== '') stage(key, step < 1 ? parseFloat(v) : parseInt(v, 10)); },
    onblur: flush, onkeydown: (e) => { if (e.key === 'Enter') e.currentTarget.blur(); } });
}

function select(key, options) {
  return h('select', { class: 'select', onchange: (e) => save(key, e.currentTarget.value) },
    options.map((o) => h('option', { value: o, selected: s()[key] === o }, o)));
}

// The shared card (ui.js), called positionally: every settings card has an icon, tone, title and line.
const section = (iconName, tone, title, desc, ...body) => card({ icon: iconName, tone, title, desc, cls: tab === 'data' ? '' : 'fill-card' }, ...body);

// A model picker: ComfyUI's own list when it was reached, otherwise a plain text box.
function modelSelect(key, names) {
  if (!names?.length) {
    return h('input', { class: 'input', value: s()[key], placeholder: '파일 이름', onchange: (e) => save(key, e.currentTarget.value.trim()) });
  }
  const options = ['', ...names, ...(s()[key] && !names.includes(s()[key]) ? [s()[key]] : [])];
  return h('select', { class: 'select', onchange: (e) => save(key, e.currentTarget.value) },
    options.map((o) => h('option', { value: o, selected: s()[key] === o }, o || '(고르세요)')));
}

function connection() {
  const conn = app.conf.connection, flow = app.conf.workflow;
  const url = h('input', { class: 'input', id: 'comfy-url', value: s().comfy_url, placeholder: 'http://127.0.0.1:8188', autocomplete: 'off',
    onchange: (e) => checkConnection(e.currentTarget.value), onkeydown: (e) => { if (e.key === 'Enter') e.currentTarget.blur(); } });
  const status = !conn ? h('span', { class: 'faint' }, '아직 확인하지 않았습니다.')
    : conn.error ? h('span', { style: { color: 'var(--red)' } }, conn.error)
    : h('div', { class: 'row wrap', style: { gap: '8px' } },
      h('span', { class: 'badge mint' }, '연결됨'), conn.version ? h('span', { class: 'badge' }, `ComfyUI ${conn.version}`) : null,
      h('span', { class: 'badge' }, `diffusion ${conn.unet_names.length} · 텍스트 인코더 ${conn.clip_names.length} · VAE ${conn.vae_names.length} · LoRA ${(conn.lora_names || []).length}`),
      h('span', { class: 'note' }, `${conn.checked} 확인`));
  const custom = flow.exists;
  return section('key', '', 'ComfyUI 연결 · Anima 모델', 'Anima가 돌아가는 ComfyUI를 켜 둔 채로 쓰세요. 그림은 ComfyUI가 그리고, 이 앱은 작가 조합만 바꿔 가며 요청합니다.',
    field('ComfyUI 주소', h('div', { class: 'input-group' }, url,
      h('button', { class: 'btn primary', onclick: () => checkConnection(root.querySelector('#comfy-url').value) }, '연결 확인'),
      )),
    h('div', { class: 'row', style: { marginTop: '10px' } }, status),
    custom ? h('p', { class: 'note', style: { marginTop: '12px', color: flow.error ? 'var(--red)' : 'var(--text)' } },
        flow.error ? flow.error : 'data 폴더의 workflow.json을 쓰는 중입니다. 아래 모델 선택은 쓰이지 않고, 프롬프트·시드·크기·Steps·CFG·샘플러만 이 앱이 채워 넣습니다.')
      : null,
    h('div', { class: 'grid', style: { gridTemplateColumns: '1fr', marginTop: '14px', opacity: custom && !flow.error ? 0.5 : 1 } },
      field('Diffusion model (Anima)', modelSelect('unet_name', conn?.unet_names)),
      field('텍스트 인코더 (qwen_3_06b_base)', modelSelect('clip_name', conn?.clip_names)),
      field('VAE (qwen_image_vae)', modelSelect('vae_name', conn?.vae_names))),
    h('div', { class: 'row wrap', style: { marginTop: '14px', paddingTop: '12px', borderTop: '1px solid var(--line)', gap: '10px' } },
      h('span', { class: 'note', style: { flex: 1, minWidth: '200px' } },
        '내 워크플로를 쓰려면 ComfyUI에서 "Save (API Format)"으로 저장한 파일을 data 폴더에 workflow.json이라는 이름으로 넣으세요. 지우면 내장 워크플로로 돌아옵니다.'),
      h('span', { class: 'note' }, 'ComfyUI 주소와 Workflow 파일은 서버 PC 기준입니다.')));
}

function generation() {
  const meta = app.meta, conn = app.conf.connection;
  const withCurrent = (list, key) => (list.includes(s()[key]) || !s()[key] ? list : [s()[key], ...list]);
  const seed = h('input', { class: 'input num', value: s().seed, placeholder: '비우면 무작위', inputmode: 'numeric',
    onchange: (e) => save('seed', e.currentTarget.value.trim()) });
  return section('image', 'sky', '이미지 생성', '모든 그림(무작위 조합, 진화 조합, 다듬기, 자유 생성)이 이 설정과 하나의 시드로 그려집니다.',
    h('div', { class: 'grid', style: { gridTemplateColumns: 'repeat(3, 1fr)' } },
      field('크기', select('size', meta.sizes)),
      field('샘플러', select('sampler', withCurrent(conn?.samplers || meta.samplers, 'sampler'))),
      field('스케줄러', select('scheduler', withCurrent(conn?.schedulers || meta.schedulers, 'scheduler'))),
      field('Steps', number('steps'), 'Anima 권장 30~50'),
      field('CFG', number('cfg', { step: 0.1 }), 'Anima 권장 4~5'),
      field('생성 간 대기 (초)', number('delay', { step: 0.5 }), '로컬 생성이라 0이면 됩니다.'),
      h('div', { class: 'field', style: { gridColumn: 'span 2' } }, h('label', {}, '시드'),
        h('div', { class: 'input-group' }, seed,
          h('button', { class: 'btn', onclick: () => { save('seed', String(Math.floor(Math.random() * meta.max_seed))); render(); } }, icon('refresh'), '무작위'))),
      h('label', { class: 'toggle-row', style: { gridColumn: 'span 3' } },
        h('input', { type: 'checkbox', checked: !!s().lora_clip, onchange: (e) => { save('lora_clip', e.currentTarget.checked); } }),
        h('div', {}, h('div', { class: 'toggle-title' }, 'LoRA를 텍스트 인코더(CLIP)에도 적용'),
          h('div', { class: 'help' }, '끄면 모델에만 적용합니다. Anima LoRA 대부분은 끈 채로 쓰면 됩니다.')))));
}

function prompts() {
  const base = h('textarea', { class: 'textarea grow', rows: 3, value: s().base_prompt,
    oninput: (e) => stage('base_prompt', e.currentTarget.value), onchange: flush });
  const negative = h('textarea', { class: 'textarea grow', rows: 4, value: s().negative,
    oninput: (e) => stage('negative', e.currentTarget.value), onchange: flush });
  return section('brush', 'rose', '프롬프트', '작가 조합은 기본 프롬프트의 {artist} 자리에 들어가고, 그릴 때 Anima 형식 (@작가명:가중치)로 바뀝니다. {artist}가 없으면 맨 앞에 붙습니다.',
    h('div', { class: 'stack' },
      field('기본 프롬프트', base, h('span', {}, h('code', {}, '{artist}'), ' 위치에 작가 태그가 들어갑니다. 순서는 품질·안전 태그 → 인원수 → 캐릭터 → 작가 → 나머지 태그가 Anima 권장입니다. 캐릭터도 여기에 함께 쓰세요.')),
      field('네거티브 프롬프트', negative)),
    app.status?.stage.checklist.prompt ? null : h('div', { id: 'prompt-confirm', class: 'row', style: { marginTop: '14px' } },
      h('span', { class: 'note', style: { flex: 1 } }, '기본값 그대로 사용하려면 오른쪽 버튼을 누르세요.'),
      h('button', { class: 'btn primary', onclick: () => app.act(post('/api/settings', { changes: { prompt_checked: true } }), '프롬프트를 확인했습니다.') },
        icon('check'), '이대로 사용')));
}

function data() {
  return section('folder', 'mint', '데이터', app.meta.data_dir,
    h('div', { class: 'row wrap' },
      h('button', { class: 'btn', onclick: exportData }, icon('download'), '데이터 내보내기'),
      h('button', { class: 'btn', onclick: importData }, icon('upload'), '데이터 불러오기')),
    h('p', { class: 'note' },
      '데이터 내보내기를 누르면 모든 설정을 zip 하나로 묶어 추출합니다. 데이터 불러오기를 통해 데이터를 불러오면 지금의 모든 데이터는 삭제됩니다.'));
}

// Python shows Windows' Save As over this window and writes the zip there (path null: cancelled).
async function exportData() {
  try {
    await downloadArchiveFile();
    toast('ZIP 다운로드를 시작했습니다.', 'ok');
  } catch (error) {
    toast(error.message, 'error');
  }
}

// Windows' Open picks the zip (null: cancelled); Python reads that file itself, so only its name comes back here.
async function importData() {
  const file = await app.act(post('/api/data/pick'));
  if (!file) return;
  const ok = await confirmDialog({ title: '데이터 불러오기', ok: '불러오기', danger: true,
    text: `${file.name}

지금의 조합·이미지·순위·진화·작가·설정이 이 파일의 내용으로 바뀝니다. 백업을 남기지 않으니, 필요하면 먼저 내보내기 해 두세요. ` });
  if (!ok) return;
  const result = await app.act(post('/api/data/import'));
  toast(`데이터를 불러왔습니다. 조합 ${fmt(result.combos)}개, 이미지 ${fmt(result.images)}장.`, 'ok');
  render();
}

const RESETS = [
  ['ratings', '순위 기록', '모든 Elo·전적·투표 기록을 지웁니다. 조합과 이미지는 남고, 선별에서 자리를 다시 찾습니다.'],
  ['evolution', '진화 기록', '세대 번호와 진화 로그만 1세대로 되돌립니다. 조합과 순위는 그대로입니다.'],
  ['settings', '설정', '생성 설정·조합 규칙·프롬프트를 기본값으로 되돌립니다. ComfyUI 주소·모델·시드는 유지합니다.'],
  ['artists', '작가 목록', '등록한 작가를 지우고 기본 작가 목록으로 되돌립니다.'],
  ['combos', '데이터만 초기화', '조합·이미지·순위·진화·다듬기 기록을 모두 지웁니다. 작가 목록·설정은 유지합니다.', true],
  ['all', '모두 초기화', '데이터를 모두 지우고 처음 설치한 상태로 되돌립니다.', true],
];

async function reset([scope, title, text, heavy]) {
  const warn = `${text}\n\n⚠ 이 작업은 절대 되돌릴 수 없습니다.`;
  const ok = heavy
    ? (await promptDialog({ title: `${title}`, text: `${warn}\n계속하려면 "초기화"를 입력하세요.`, ok: '초기화', placeholder: '초기화' }))?.trim() === '초기화'
    : await confirmDialog({ title: `${title} 초기화`, text: warn, ok: '초기화', danger: true });
  if (!ok) return;
  await app.act(post('/api/reset', { scope }), '초기화에 성공하였습니다.');
  render();
}

function resets() {
  return section('trash', 'rose', '초기화', '초기화하면 바로 지워지며, 절대 되돌릴 수 없습니다.',
    h('div', { class: 'stack', style: { gap: '0' } }, RESETS.map((item) =>
      h('div', { class: 'reset-row' },
        h('div', {}, h('div', { style: { fontWeight: 600 } }, item[1]), h('div', { class: 'note' }, item[2])),
        h('button', { class: `btn sm ${item[3] ? 'danger' : ''}`, style: { flex: 'none' }, onclick: () => reset(item) }, '초기화')))));
}

// Tabs keep every part of the settings on one screen without scrolling.
const TABS = [['basic', '연결 · 생성'], ['prompts', '프롬프트'], ['data', '데이터']];
const TAB_OF = { connection: 'basic', prompts: 'prompts' };
let tab = 'basic';

function render() {
  const columns = (left, right) => h('div', { class: 'fill-grid settings-columns' }, left, right);
  const body = tab === 'prompts' ? h('div', { class: 'fill-grid', style: { gridTemplateColumns: 'minmax(0, 1fr)' } }, named(prompts(), 'prompts'))
    : tab === 'data' ? h('div', { class: 'stack settings-stack' }, data(), resets())
    : columns(named(connection(), 'connection'), generation());
  morph(root,
    pageHead({ title: '설정', desc: '바꾸면 바로 저장됩니다.',
      below: h('div', { class: 'segmented', role: 'tablist', 'aria-label': '설정 항목', style: { marginTop: '14px' } },
        TABS.map(([id, label]) => h('button', { class: tab === id ? 'on' : '', role: 'tab', 'aria-selected': String(tab === id),
          onclick: () => { flush(); tab = id; render(); } }, label))) }),
    body);
}

// The setup guide and "지금 할 일" link here with ?focus=<section id>. That card stays marked for as long
// as this page is open, whether or not the step is already done, so it is always clear where you were sent.
let highlight = null;

const named = (el, id) => {
  el.id = id;
  if (id === highlight) el.style.outline = '2px solid var(--accent)';
  return el;
};

function focusSection() {
  const id = app.params.focus;
  const target = id && document.getElementById(id);
  highlight = target ? id : null;
  if (!target) return;
  target.style.outline = '2px solid var(--accent)';
  target.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Saving the address always asks ComfyUI too, so a wrong address shows up right away.
// The button click follows the input's change event: both share one in-flight check.
let checking = null;
function checkConnection(value) {
  checking ??= (async () => {
    try {
      save('comfy_url', value.trim());
      await flush();
      await app.act(post('/api/connection'));
      render();
    } finally {
      checking = null;
    }
  })();
  return checking;
}

export default {
  async mount(el, appRef) {
    app = appRef;
    root = h('div', { class: 'page-col' });
    app.setFill(true);
    el.append(root);
    tab = TAB_OF[app.params.focus] ?? tab;
    render();
    focusSection();
  },
  unmount() {
    flush();
    highlight = null;
  },
  // morph() keeps what is being typed, so the page can follow every change of the settings.
  onStatus(status, previous, force) {
    if (force || previous?.settings_rev !== status.settings_rev
        || previous?.stage.checklist.prompt !== status.stage.checklist.prompt) render();
  },
};
```
