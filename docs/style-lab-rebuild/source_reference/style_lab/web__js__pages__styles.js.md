# Source Snapshot: web/js/pages/styles.js

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\web\js\pages\styles.js`
- Original Byte SHA-256: `d0db968ef1ec389b20e0791b4aa0d5f27e3f6561a5668ce8df43316a468d4831`
- Snapshot Text SHA-256: `d0db968ef1ec389b20e0791b4aa0d5f27e3f6561a5668ce8df43316a468d4831`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```javascript
// 그림체 — every combo, active and set aside. Browse, compare, fix Elo, revive or delete.
import { get, post } from '../api.js';
import { h, morph, icon, toast, pickSelect, selectionKeys, arrowTarget, pageHead, comboTile, comboPreview, previewPage, reviveCombos, removeCombos,
  confirmDialog, modal, art, lightbox, fmt, emptyState, galleryList, galleryToolbar } from '../ui.js';

let root, app, data = { active: [], excluded: [] }, barHost = null;
const view = { tiers: new Set(), sort: 'elo-desc', selected: new Set(), focus: null, anchor: null };

function all() {
  return [...data.active, ...data.excluded];
}

const visible = () => galleryList(data.active, data.excluded, view);

function select(id, event) {
  pickSelect(view, id, event, visible().map((c) => c.id));  // the checkbox comes as a Ctrl+click
  view.focus = view.selected.has(id) ? id : [...view.selected].at(-1) || null;
  render();
}

// After Esc / Ctrl+A: the preview keeps showing a combo only while it is still selected.
function selectionChanged() {
  if (!view.selected.has(view.focus)) view.focus = null;
  render();
}

const tile = (c) => comboTile(c, { cls: view.selected.has(c.id) ? 'selected' : '', onclick: (e) => select(c.id, e),
  check: { on: view.selected.has(c.id), toggle: () => select(c.id, { ctrlKey: true }) } });

function detail() {
  return comboPreview(all().find((x) => x.id === view.focus), app);
}

// 비교: the two pictures side by side, then every tag with each side's weight (shared first).
function compare(ids) {
  const [a, b] = ids.map((id) => all().find((c) => c.id === id));
  if (!a || !b) return;
  const wa = new Map(a.pairs.map((p) => [p.tag, p.w])), wb = new Map(b.pairs.map((p) => [p.tag, p.w]));
  const tags = [...new Set([...wa.keys(), ...wb.keys()])];
  const group = (t) => (wa.has(t) && wb.has(t) ? 0 : wa.has(t) ? 1 : 2);
  tags.sort((x, y) => group(x) - group(y) || (wa.get(y) ?? wb.get(y)) - (wa.get(x) ?? wb.get(x)));
  const label = (t) => t.replace(/^artist:|^lora:/, '') + (t.startsWith('lora:') ? ' (LoRA)' : '');
  const side = (c, name) => h('div', { style: { minWidth: 0 } },
    art(c, { thumb: false }), h('div', { class: 'hint', style: { marginTop: '6px' } },
      `${name} · Elo ${c.elo}${c.rank ? ` · ${c.rank}위` : ''} · ${c.matches}전 ${c.wins}승`));
  const rows = tags.map((t) => {
    const x = wa.get(t), y = wb.get(t), g = group(t);
    const diff = g === 0 ? (y - x).toFixed(2).replace(/^(\d)/, '+$1') : '–';
    return h('tr', {}, h('td', {}, label(t)), h('td', {}, x ?? '–'), h('td', {}, y ?? '–'),
      h('td', {}, g === 0 ? (x === y ? '같음' : diff) : g === 1 ? 'A만' : 'B만'));
  });
  modal((dialog, done) => {
    dialog.style.maxWidth = '900px';
    dialog.style.width = '92vw';
    dialog.append(h('h3', {}, '두 조합 비교'),
      h('div', { style: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' } }, side(a, 'A'), side(b, 'B')),
      h('div', { style: { maxHeight: '260px', overflowY: 'auto', margin: '12px 0' } },
        h('table', { class: 'table', style: { width: '100%' } }, h('thead', {}, h('tr', {}, ['태그', 'A', 'B', '차이'].map((x) => h('th', {}, x)))), h('tbody', {}, rows))),
      h('div', { class: 'actions' }, h('button', { class: 'btn primary', onclick: () => done(null) }, '닫기')));
  });
}

// 보관함: keep the picked combos for good (all kept -> the button takes them out again).
function keepBtn(ids) {
  const picked = all().filter((c) => view.selected.has(c.id));
  const allKept = picked.length && picked.every((c) => c.kept);
  return h('button', { class: 'btn sm', onclick: async () => {
    try { await post('/api/combos/keep', { ids, kept: !allKept }); toast(allKept ? '북마크를 해제했습니다.' : '북마크했습니다. 진화에서 밀려나거나 지워지지 않습니다.'); await load(); } catch (e) { toast(e.message, 'error'); }
  } }, icon('bookmark'), allKept ? '북마크 해제' : '북마크');
}

// Shown while any are selected; it floats over the page, so it lives in its own host on <body>.
function selectionBar() {
  const ids = [...view.selected];
  if (!ids.length) return null;
  const outs = all().filter((c) => view.selected.has(c.id) && c.excluded).map((c) => c.id);
  return h('div', { class: 'selection-bar' },
    h('span', { class: 'count' }, `${ids.length}개 선택`),
    outs.length ? h('button', { class: 'btn sm', onclick: () => revive(outs) }, icon('refresh'), `부활 ${outs.length}`) : null,
    keepBtn(ids),
    ids.length === 2 ? h('button', { class: 'btn sm', onclick: () => compare(ids) }, icon('swords'), '비교') : null,
    h('button', { class: 'btn sm danger', onclick: () => remove(ids) }, icon('trash'), '삭제'),
    h('button', { class: 'btn sm ghost', onclick: () => { view.selected.clear(); view.focus = null; render(); } }, '선택 해제'));
}

function render() {
  const failed = data.excluded.filter((c) => c.excluded === '탈락').length;
  const dropped = data.excluded.length - failed;
  const judging = data.active.filter((c) => !c.rated || c.child).length;
  const list = visible();
  const toolbar = galleryToolbar(view, render);
  toolbar.style.marginBottom = '0';
  morph(root, previewPage(
    pageHead({ title: '그림체', desc: `전체 ${fmt(data.active.length)} · 평가중 ${fmt(judging)} · 탈락 ${fmt(failed)} · 제외 ${fmt(dropped)}`,
      keys: [[['←', '→', '↑', '↓'], '선택 이동'], [['Delete'], '삭제'], [['Esc'], '선택 해제'], [['Ctrl', 'A'], '모두 선택'],
        [[], 'Shift/Ctrl 클릭 · 체크로 여러 개 선택']],
      // The line under the description: sort and filters on the left, the purge buttons on the right.
      below: h('div', { class: 'row', style: { marginTop: '14px', gap: '8px', flexWrap: 'wrap' } }, toolbar, h('span', { class: 'spacer' }),
        h('button', { class: 'btn danger purge', disabled: !failed, title: `${WHY['탈락']} 눌러서 전부 삭제`, onclick: () => purge('탈락', failed) }, icon('trash'), `탈락 ${fmt(failed)}`),
        h('button', { class: 'btn danger purge', disabled: !dropped, title: `${WHY['제외']} 눌러서 전부 삭제`, onclick: () => purge('제외', dropped) }, icon('trash'), `제외 ${fmt(dropped)}`)) }),
    null,
  list.length ? h('div', { class: 'gallery cols-8' }, list.map(tile))
    : emptyState({ iconName: 'grid', title: '보여 줄 그림체가 없습니다', text: '필터를 바꾸거나 조합에서 새 조합을 만들어 보세요.' }),
  detail()));
  morph(barHost, selectionBar());
}

async function load() {
  try {
    data = await get('/api/combos');
    const known = new Set(all().map((c) => c.id));
    view.selected = new Set([...view.selected].filter((id) => known.has(id)));
    if (view.focus && !known.has(view.focus)) view.focus = null;
    render();
  } catch (error) {
    toast(error.message, 'error');
  }
}

const revive = (ids) => reviveCombos(app, ids);

async function remove(ids) {
  if (!(await removeCombos(app, ids))) return;
  view.selected.clear();
  view.focus = null;
  render();
}

// What the two labels mean: both are combos that left the list when an evolution generation was confirmed.
const WHY = {
  '탈락': '탈락: 진화로 새로 만든 조합 중 상위 30%에 들지 못해 떨어진 것입니다.',
  '제외': '제외: 기존 조합 중 새 조합들에 밀려 상위 30% 밖으로 나온 것입니다.',
};

async function purge(reason, count) {
  const ok = await confirmDialog({ title: `${reason} 전부 삭제`, text: `${WHY[reason]}\n\n이런 조합 ${count}개를 기록과 이미지에서 영구 삭제합니다. 삭제하면 부활시킬 수 없습니다. (북마크한 조합은 지워지지 않습니다.)`, ok: '전부 삭제', danger: true });
  if (!ok) return;
  await app.act(post('/api/combos/purge', { reason }), `${reason} ${count}개를 삭제했습니다.`);
}

export default {
  async mount(el, appRef) {
    app = appRef;
    app.setFill(true);
    root = h('div', { style: { display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 } });
    barHost = h('div', { style: { display: 'contents' } });
    el.append(root);
    document.body.append(barHost);
    if (app.params.focus) {
      view.selected = new Set([app.params.focus]);
      view.focus = app.params.focus;
    }
    await load();
  },
  onStatus(status, previous, force) {
    if (force || (previous && (previous.counts.active !== status.counts.active || previous.counts.excluded !== status.counts.excluded
        || previous.counts.votes !== status.counts.votes || previous.settings_rev !== status.settings_rev
        || previous.job?.running !== status.job?.running))) load();
  },
  onKey(event) {
    const id = arrowTarget(event, view.focus);
    if (id) {
      view.selected = new Set([id]);
      view.anchor = id;
      view.focus = id;
      return render();
    }
    selectionKeys(event, view, { order: () => visible().map((c) => c.id), remove, changed: selectionChanged });
  },
  unmount() {
    barHost?.remove();
    barHost = null;
  },
};
```
