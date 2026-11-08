# Source Snapshot: web_browser/js/pages/refine.js

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\web_browser\js\pages\refine.js`
- Original Byte SHA-256: `bd05321d238175af50412474440f7e0ffe8973f5824e66887cdd5529add8b902`
- Snapshot Text SHA-256: `bd05321d238175af50412474440f7e0ffe8973f5824e66887cdd5529add8b902`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```javascript
// 다듬기 — vary a combo's weights (artists, LoRAs or both) into dozens of variants, judge them in 선별, and read off the values the winners agree on.
import { get, post } from '../api.js';
import { createStones } from '../stones.js';
import { h, morph, icon, toast, art, fmt, copyText, lightbox, pageHead, pickCombo, confirmDialog, emptyState } from '../ui.js';

const SPREADS = [['narrow', '좁게', '±0.05~0.15'], ['normal', '보통', '±0.05~0.30'], ['wide', '넓게', '±0.10~0.45']];
const name = (tag) => tag.replace(/^artist:|^lora:/, '').replace(/^.*[\\/]/, '').replace(/\.safetensors$/, '');
const isLora = (tag) => tag.startsWith('lora:');

let root, app, tune = { active: false }, results = [], combos = [], timer = null;
const form = { id: null, count: 30, spread: 'normal', scope: 'all', draw: 4 };
const SCOPES = [['all', '전체'], ['artist', '작가만'], ['lora', 'LoRA만']];

const stones = createStones({ items: () => results, reload: () => load(), rerender: () => render() });

async function load() {
  try {
    const [t, m, c] = await Promise.all([get('/api/tune'), get('/api/merge'), get('/api/combos')]);
    tune = t;
    results = m.items.filter((i) => i.source === 'tune');
    combos = c.active;
    if (form.id && !combos.some((x) => x.id === form.id)) form.id = null;
  } catch (e) { toast(e.message, 'error'); return; }
  stones.prune();
  render();
  const busy = tune.running || (tune.active && tune.status === 'generating');
  if (busy && !timer) timer = setInterval(load, 2000);
  if (!busy && timer) { clearInterval(timer); timer = null; }
}

const tagText = (c) => c.pairs.map((p) => `${name(p.tag)} ${p.w}`).join(' · ');
const scoped = (c, scope) => c.pairs.filter((p) => scope === 'all' || (scope === 'lora') === isLora(p.tag));

// ---------------------------------------------------------------- before a session: pick the combo
function picker() {
  const c = combos.find((x) => x.id === form.id);
  const choose = async () => {
    if (!combos.length) return toast('다듬을 조합이 없습니다. 조합 탭에서 먼저 조합을 만들어 보세요.', 'warn');
    const got = await pickCombo({ list: combos, title: '다듬을 조합 고르기', ok: '이 조합으로', current: form.id });
    if (got) { form.id = got.id; render(); }
  };
  const busy = app.status?.job?.running;
  return h('section', { class: 'card tune-start' },
    h('div', { class: 'tune-pick' },
      h('div', { class: 'tune-thumb', onclick: choose, title: '눌러서 고르기' }, c ? art(c, {}) : h('div', { class: 'tune-empty' }, icon('wand'), h('span', {}, '조합 고르기'))),
      h('div', { class: 'tune-info' },
        h('h3', {}, c ? '가중치를 바꿔 가며 다듬을 조합' : '먼저 다듬을 조합을 고르세요'),
        c ? [h('div', { class: 'note' }, `Elo ${fmt(c.elo)}${c.rank ? ` · ${c.rank}위` : ''}`),
          h('div', { class: 'chips' }, c.pairs.map((p) => h('span', { class: `chip ${scoped(c, form.scope).includes(p) ? '' : 'dim'}`, title: isLora(p.tag) ? 'LoRA' : '작가' }, h('span', { class: isLora(p.tag) ? 'c-lora' : 'c-artist' }, name(p.tag)), ' ', h('b', {}, p.w))))]
          : h('p', { class: 'note' }, '고른 조합의 작가·LoRA 가중치를 크고 작게 바꾼 변형을 여러 장 그려 선별하면, 이긴 변형들의 값이 모이는 곳을 추천 값으로 알려 줍니다.'),
        h('div', { class: 'row', style: { gap: '8px', flexWrap: 'wrap' } },
          h('button', { class: 'btn', onclick: choose }, icon('grid'), c ? '다른 조합 고르기' : '조합 고르기'),
          c ? h('button', { class: 'btn ghost', onclick: () => { form.id = null; render(); } }, '고른 조합 취소') : null))),
    h('div', { class: 'tune-opts' },
      h('label', { class: 'inline-field' }, h('span', {}, '변형 수'),
        h('input', { class: 'input num', type: 'number', min: 4, max: 80, value: form.count, style: { width: '84px' }, oninput: (e) => { form.count = Number(e.currentTarget.value) || 30; } })),
      h('div', { class: 'inline-field' }, h('span', {}, '바꿀 대상'),
        h('div', { class: 'segmented' }, SCOPES.map(([k, label]) => h('button', { class: form.scope === k ? 'on' : '', title: k === 'all' ? '작가와 LoRA 가중치를 모두 바꿉니다' : k === 'artist' ? '작가 가중치만 바꾸고 LoRA는 그대로 둡니다' : 'LoRA 가중치만 바꾸고 작가는 그대로 둡니다', onclick: () => { form.scope = k; render(); } }, label)))),
      h('div', { class: 'inline-field' }, h('span', {}, '변화 폭'),
        h('div', { class: 'segmented' }, SPREADS.map(([k, label, hint]) => h('button', { class: form.spread === k ? 'on' : '', title: hint, onclick: () => { form.spread = k; render(); } }, label)))),
      h('span', { class: 'spacer' }),
      h('button', { class: 'btn primary lg', disabled: !c || busy, onclick: start }, icon('wand'), busy ? '다른 작업 중…' : '다듬기 시작')));
}

async function start() {
  const ok = await app.act(post('/api/tune/start', { id: form.id, count: form.count, spread: form.spread, scope: form.scope }), '변형을 만들기 시작했습니다. 먼저 완성된 변형부터 선별에서 고를 수 있습니다.');
  if (ok !== false) await load();
}

// ---------------------------------------------------------------- during a session
const pct = (x) => (x == null ? '–' : `${Math.round(x * 100)}%`);

function recommendation() {
  const r = tune.recommend;
  if (!r) return h('section', { class: 'card' }, h('h3', {}, '추천 값'),
    h('p', { class: 'note' }, `변형 ${tune.made}장 중 선별로 평가된 것이 4장 이상 되면 추천 값이 나옵니다. 지금은 ${fmt(tune.votes)}번 투표했습니다.`));
  const conf = { high: ['믿을 만함', 'ok'], mid: ['보통', ''], low: ['참고용 · 더 선별하면 정확해집니다', 'warn'] }[r.confidence];
  return h('section', { class: 'card' },
    h('div', { class: 'row', style: { flexWrap: 'wrap', gap: '8px' } }, h('h3', { style: { margin: 0 } }, '추천 값'),
      h('span', { class: `pill ${conf[1]}` }, conf[0]), h('span', { class: 'note' }, `평가된 변형 ${r.judged}장 중 상위 ${r.top}장 기준`), h('span', { class: 'spacer' }),
      h('button', { class: 'btn sm', onclick: () => copyText(r.anima, '추천 값을 Anima 형식으로 복사했습니다.') }, icon('copy'), '복사')),
    h('div', { class: 'table-wrap', style: { marginTop: '10px' } }, h('table', { class: 'data' },
      h('thead', {}, h('tr', {}, h('th', {}, '태그'), h('th', { class: 'num' }, '기준'), h('th', { class: 'num' }, '추천'), h('th', { class: 'num' }, '승자 범위'), h('th', { class: 'num' }, '겹침'), h('th', {}, '판정'))),
      h('tbody', {}, r.rows.map((row) => h('tr', {},
        h('td', { title: row.tag }, h('span', { class: isLora(row.tag) ? 'c-lora' : 'c-artist' }, name(row.tag))),
        h('td', { class: 'num' }, row.base == null ? '–' : row.base.toFixed(2)),
        h('td', { class: 'num' }, h('b', {}, row.agree ? row.rec.toFixed(2) : (row.base ?? row.rec).toFixed(2))),
        h('td', { class: 'num' }, `${row.range[0].toFixed(2)}~${row.range[1].toFixed(2)}`),
        h('td', { class: 'num' }, `${row.overlap}/${row.top}`),
        h('td', { class: 'note' }, row.agree
          ? `이 범위의 변형 평균 승률 ${pct(row.in_rate)} · 밖 ${pct(row.out_rate)}`
          : '승자들의 값이 흩어져 있어 이 값은 크게 중요하지 않습니다 (기준 유지)')))))),
    h('div', { class: 'row', style: { marginTop: '12px', gap: '8px', flexWrap: 'wrap' } },
      h('label', { class: 'inline-field', style: { flexDirection: 'row', alignItems: 'center', gap: '8px' } }, h('span', {}, '그릴 장수'),
        h('input', { class: 'input num', type: 'number', min: 1, max: 12, value: form.draw, style: { width: '64px' }, oninput: (e) => { form.draw = Number(e.currentTarget.value) || 4; } })),
      h('button', { class: 'btn primary', disabled: tune.running || app.status?.job?.running, onclick: drawRecommended }, icon('sparkle'), '추천 값으로 그리기'),
      h('span', { class: 'note' }, '첫 장은 원본과 같은 시드, 나머지는 새 시드입니다. 아래 "추천 값으로 그린 그림"에 쌓입니다.')));
}

async function drawRecommended() {
  await app.act(post('/api/tune/render', { count: form.draw }), `추천 값으로 ${form.draw}장을 그리기 시작했습니다.`);
  await load();
}

function variants() {
  const list = tune.items;
  return [h('div', { class: 'section-head' }, h('h2', { class: 'section' }, `변형 ${tune.made}장`), h('span', { class: 'hint' }, '승률 순 · 눌러서 크게 보기')),
    h('div', { class: 'stones' }, list.filter((i) => i.thumb).map((i) => h('div', { class: `stone ${i.reference ? 'ref' : ''}`, key: i.id,
      title: Object.entries(i.weights).map(([t, w]) => `${name(t)} ${w}`).join(', '),
      onclick: () => lightbox(i.image, Object.entries(i.weights).map(([t, w]) => ({ tag: t, w }))) },
      h('img', { src: i.thumb, alt: '', loading: 'lazy', draggable: false }),
      h('span', { class: 'stone-tag' }, i.reference ? '기준 · ' : '', i.matches ? `${pct(i.rate)} (${i.matches}전)` : '미평가'),
      h('div', { class: 'stone-weights' }, Object.entries(i.weights).map(([t, w]) => h('span', {}, `${name(t).slice(0, 10)} ${w}`))))))];
}

function sessionHead() {
  const base = tune.base;
  const left = tune.remaining;
  const statusText = tune.running || tune.status === 'generating'
    ? `변형을 만드는 중 ${tune.progress ? `${tune.progress[0]}/${tune.progress[1]}` : ''}`
    : left > 0 ? `선별할 비교가 약 ${left}번 남았습니다` : '모든 변형이 평가되었습니다';
  return h('section', { class: 'card tune-session' },
    h('div', { class: 'tune-thumb sm' }, base ? art(base, {}) : null),
    h('div', { class: 'tune-info' },
      h('h3', {}, '다듬는 중'), h('div', { class: 'note' }, base ? tagText(base) : ''),
      h('div', { class: 'note' }, `${statusText} · 투표 ${fmt(tune.votes)}회`),
      h('div', { class: 'row', style: { gap: '8px', flexWrap: 'wrap', marginTop: '8px' } },
        h('button', { class: 'btn primary', onclick: () => app.go('arena') }, icon('swords'), `선별하러 가기${left > 0 ? ` · ${left}` : ''}`),
        h('button', { class: 'btn', disabled: tune.running || app.status?.job?.running, onclick: more }, icon('plus'), '변형 더 만들기'),
        h('button', { class: 'btn ghost', onclick: finish }, '그만두기'))));
}

async function more() {
  await app.act(post('/api/tune/more', { count: 20 }), '변형 20장을 더 만들기 시작했습니다.');
  await load();
}

async function finish() {
  const ok = await confirmDialog({ title: '다듬기를 마무리할까요?', text: '변형 그림은 지워지고 추천 값으로 그린 그림만 남습니다. 추천 값은 마무리 전에 복사해 두세요.', ok: '마무리', danger: true });
  if (!ok) return;
  await app.act(post('/api/tune/finish'), '다듬기를 마무리했습니다.');
  await load();
}

function resultsSection() {
  return [h('div', { class: 'section-head', style: { marginTop: '18px' } }, h('h2', { class: 'section' }, `추천 값으로 그린 그림 ${results.length}장`),
    h('span', { class: 'hint' }, '마음에 드는 것은 북마크하며 목록에 넣으세요.')),
    stones.view('아직 없습니다. 추천 값이 나오면 "추천 값으로 그리기"를 눌러 보세요.')];
}

function render() {
  if (!root) return;
  const active = tune.active;
  morph(root,
    pageHead({ title: '다듬기', desc: '작가·LoRA 가중치를 크고 작게 바꾼 변형을 여러 장 그려 선별하고, 이긴 변형들의 값이 모이는 곳을 추천 값으로 알려 줍니다.' }),
    active ? [sessionHead(), h('div', { style: { height: '14px' } }), recommendation(), variants(), results.length ? resultsSection() : null]
      : [picker(), h('section', { class: 'card fill-grow', style: { marginTop: '16px', display: 'flex', flexDirection: 'column' } },
        results.length ? resultsSection()
          : h('div', { class: 'fill-center' }, emptyState({ iconName: 'wand', title: combos.length ? '추천 값으로 그린 그림이 여기에 쌓입니다' : '다듬을 조합이 없습니다',
            text: combos.length ? '조합을 골라 다듬기를 시작하세요.' : '조합 탭에서 조합을 만들고 선별로 순위를 잡아 보세요.' })))]);
}

export default {
  async mount(el, appRef) {
    app = appRef;
    app.setFill(true);
    root = h('div', { class: 'page-col scroll', style: { maxWidth: '1400px' } });
    el.append(root);
    if (app.params?.id) form.id = app.params.id;
    await load();
  },
  onStatus(status, previous, force) {
    if (force || !previous || previous.tune !== status.tune || previous.job?.running !== status.job?.running || previous.counts.votes !== status.counts.votes) load();
  },
  onKey(event) { stones.onKey(event); },
  unmount() {
    stones.clear();
    if (timer) { clearInterval(timer); timer = null; }
  },
};
```
