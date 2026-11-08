# Source Snapshot: web_browser/js/pages/locked.js

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\web_browser\js\pages\locked.js`
- Original Byte SHA-256: `5025cbfefd108b73de7ab7016c89cabc533ebc7cc36db7820fba65a6e5d8e122`
- Snapshot Text SHA-256: `5025cbfefd108b73de7ab7016c89cabc533ebc7cc36db7820fba65a6e5d8e122`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```javascript
// 융합 — two combos mixed into several pictures, kept here until they are put in the list, sent to 다듬기 or deleted.
import { get, post } from '../api.js';
import { createStones } from '../stones.js';
import { h, morph, icon, toast, pageHead, emptyState, modal, art, lightbox, comboTile, confirmDialog, galleryList, galleryToolbar } from '../ui.js';

const pview = { tiers: new Set(), sort: 'elo-desc' };  // the picker's sort and tier filters, as on 그림체
let root, app, merged = { items: [], running: false }, slots = [null, null], countDraft = 4, timer = null;
const name = (tag) => tag.replace(/^artist:|^lora:/, '');

// 조합 고르기: the list of combos, best first; one click puts it in the slot.
async function choose(index) {
  let list;
  try { list = (await get('/api/combos')).active; } catch (e) { toast(e.message, 'error'); return; }
  const other = slots[1 - index]?.id;
  let shown = slots[index] && list.find((c) => c.id === slots[index].id) || null;
  modal((dialog, done) => {
    dialog.style.maxWidth = '1100px';
    dialog.style.width = '96vw';
    dialog.style.maxHeight = '92vh';
    dialog.style.overflowY = 'auto';
    const grid = h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))', gap: '8px', alignContent: 'start', minWidth: 0 } });
    const side = h('div', { style: { position: 'sticky', top: 0, alignSelf: 'start', minWidth: 0 } });
    const bar = h('div', {});
    const draw = () => {
      bar.replaceChildren(galleryToolbar(pview, draw));
      grid.replaceChildren(...galleryList(list, [], pview).filter((c) => c.id !== other).map((c) => comboTile(c, { cls: shown?.id === c.id ? 'selected' : '',
        onclick: () => { shown = c; draw(); }, })));
      side.replaceChildren(...(shown ? [
        h('div', { style: { cursor: 'zoom-in' }, onclick: () => lightbox(shown.image, shown.pairs) }, art(shown, { thumb: false })),
        h('div', { class: 'hint', style: { margin: '6px 0' } }, `Elo ${shown.elo}${shown.rank ? ` · ${shown.rank}위` : ''} · ${shown.matches}전 ${shown.wins}승`),
        h('div', { class: 'hint', style: { fontSize: '11px', maxHeight: '5em', overflow: 'hidden', marginBottom: '8px' } }, shown.pairs.map((p) => `${name(p.tag)} ${p.w}`).join(', ')),
        h('button', { class: 'btn primary', style: { width: '100%' }, onclick: () => { slots[index] = shown; done(null); render(); } }, `${index ? 'B' : 'A'}로 선택`)]
        : [h('p', { class: 'muted' }, '조합을 누르면 크게 볼 수 있습니다.')]));
    };
    draw();
    dialog.append(h('h3', {}, `${index ? 'B' : 'A'} 조합 고르기`),
      list.length ? h('div', { style: { display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(220px, 340px)', gap: '14px', margin: '10px 0' } }, h('div', { style: { minWidth: 0 } }, bar, grid), side)
        : h('p', { class: 'muted' }, '목록에 조합이 없습니다.'),
      h('div', { class: 'actions' }, h('button', { class: 'btn ghost', onclick: () => done(null) }, '닫기')));
  });
}

function slot(index) {
  const c = slots[index];
  const label = index ? 'B' : 'A';
  const badge = h('span', { class: 'badge glass' }, label);
  return h('div', { class: 'fuse-slot' },
    c ? h('div', { style: { cursor: 'pointer' }, title: '눌러서 바꾸기', onclick: () => choose(index) }, art(c, { corners: [['tl', badge]] }))
      : h('button', { class: 'fuse-empty', onclick: () => choose(index) }, icon('plus'), h('span', {}, `${label} 조합 고르기`)));
}

async function doMerge() {
  const count = Math.max(1, Math.min(12, Number(countDraft) || 4));
  try {
    await post('/api/combos/merge', { ids: slots.map((c) => c.id), count });
    toast(`합친 그림 ${count}장을 만들기 시작했습니다.`);
  } catch (e) { toast(e.message, 'error'); return; }
  await loadMerged();
}

// The two parents, the count and the button: one small bar that is only as wide as it needs to be.
function workbench() {
  const ready = slots[0] && slots[1];
  const run = merged.running;
  return h('section', { class: 'card fuse-bench' },
    h('div', { class: 'fuse-slots' }, slot(0), h('span', { class: 'fuse-plus' }, '+'), slot(1)),
    h('div', { class: 'row', style: { gap: '10px' } }, h('span', { class: 'field-label' }, '만들 장수'),
      h('input', { class: 'input num', type: 'number', min: 1, max: 12, value: countDraft, style: { width: '72px' }, oninput: (e) => { countDraft = e.currentTarget.value; } }),
      h('span', { class: 'note' }, '겹치는 태그는 가중치 평균')),
    h('button', { class: 'btn primary lg', style: { width: '100%' }, disabled: !ready || run, onclick: doMerge }, icon('sparkle'),
      run ? `그리는 중 ${merged.progress?.[0] ?? 0}/${merged.progress?.[1] ?? ''}` : ready ? '융합하기' : '두 조합을 먼저 고르세요'));
}

async function refineOne(it) {
  try {
    const r = await post('/api/merge/refine', { key: it.key });
    app.go('refine', { id: r?.id });
  } catch (e) { toast(e.message, 'error'); }
}

const stones = createStones({
  items: () => merged.items, reload: () => loadMerged(), rerender: () => render(), refine: refineOne,
  extra: (sel) => (sel.length === 1 ? [
    h('button', { class: 'btn sm', disabled: merged.running, onclick: async () => {
      const ids = sel[0].parents.map((p) => p.id);
      if (ids.length !== 2) return toast('원본 조합이 없어 다시 만들 수 없습니다.', 'error');
      try { await post('/api/combos/merge', { ids, count: 1 }); toast('같은 조합으로 한 장 더 만들기 시작했습니다.'); } catch (e) { toast(e.message, 'error'); return; }
      stones.clear(); await loadMerged();
    } }, icon('refresh'), '재시도'),
    h('button', { class: 'btn sm', onclick: () => { navigator.clipboard?.writeText(sel[0].anima); toast('Anima 형식으로 복사했습니다.'); } }, icon('copy'), '복사')] : []),
});

function render() {
  morph(root,
    pageHead({ title: '융합', desc: '두 조합을 합쳐 마음에 드는 그림을 북마크하거나 목록에 넣고, 더 다듬고 싶은 것은 다듬기로 보냅니다.' }),
    h('div', { class: 'fuse-layout' },
      workbench(),
      h('div', { class: 'fuse-main' },
        h('section', { class: 'card fuse-panel' },
          h('div', { class: 'panel-head' }, h('h3', {}, `합친 그림 ${merged.items.length}장`), h('span', { class: 'hint' }, '마음에 드는 것은 북마크하거나 목록에 넣으세요')),
          stones.view('아직 합친 그림이 없습니다. 왼쪽에서 두 조합을 골라 융합해 보세요.')),
        merged.listed?.length ? h('section', { class: 'card fuse-panel' },
          h('div', { class: 'panel-head' }, h('h3', {}, `목록에 넣은 그림 ${merged.listed.length}장`), h('span', { class: 'hint' }, '누르면 그림체 탭에서 열립니다')),
          h('div', { class: 'stones' }, merged.listed.map((c) => h('div', { class: 'stone', key: c.id, title: `만든 날짜 ${madeAt(c.made, true)}`, onclick: () => app.go('styles', { focus: c.id }) },
            h('img', { src: c.thumb, alt: '', loading: 'lazy', draggable: false }),
            h('span', { class: 'stone-tag' }, c.kept ? icon('bookmark', 'width="11" height="11"') : null, madeAt(c.made)))))) : null)));
}

async function loadMerged() {
  try {
    merged = await get('/api/merge');
    merged = { ...merged, items: merged.items.filter((i) => i.source !== 'tune'), listed: (merged.listed || []).filter((c) => c.source !== 'tune') };
  } catch (e) { return; }
  stones.prune();
  render();
  if (merged.running && !timer) timer = setInterval(loadMerged, 1500);
  if (!merged.running && timer) { clearInterval(timer); timer = null; }
}

export default {
  async mount(el, appRef) {
    app = appRef;
    app.setFill(true);
    root = h('div', { class: 'page-col', style: { maxWidth: '1400px' } });
    el.append(root);
    try {
      if (Array.isArray(app.params?.ids)) {
        const all = (await get('/api/combos')).active;
        slots = app.params.ids.map((id) => all.find((c) => c.id === id) || null);
      }
    } catch (e) { toast(e.message, 'error'); }
    await loadMerged();
  },
  onKey(event) { stones.onKey(event); },
  unmount() {
    stones.clear();
    if (timer) { clearInterval(timer); timer = null; }
  },
};

// "10/12" (with the year in the tooltip); empty when unknown
function madeAt(sec, full = false) {
  if (!sec) return '';
  const d = new Date(sec * 1000);
  return `${full ? `${d.getFullYear()}/` : ''}${d.getMonth() + 1}/${d.getDate()}`;
}
```
