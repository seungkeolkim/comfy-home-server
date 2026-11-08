# Source Snapshot: web/js/stones.js

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\web\js\stones.js`
- Original Byte SHA-256: `65b9592d4e2e8c3448a4643ab1a007ffc7e4a36321b06d1d4e237e6f1b7f8d04`
- Snapshot Text SHA-256: `65b9592d4e2e8c3448a4643ab1a007ffc7e4a36321b06d1d4e237e6f1b7f8d04`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```javascript
// 바둑돌: candidate pictures (융합 · 다듬기 results) kept in "merged" until the user decides. One place for the card, the
// selection bar and the keys, so both pages behave alike: select (checkbox / 전체 선택), 북마크하며 목록에 / 목록에 넣기 / 삭제,
// Delete · Esc · Ctrl+A.
import { post } from './api.js';
import { h, icon, toast, lightbox, confirmDialog } from './ui.js';

const name = (tag) => tag.replace(/^artist:|^lora:/, '');

// opts: app, items() -> the pictures shown (view items), reload() -> refetch and render, rerender() -> render only,
//       extra(selected) -> more buttons for the selection bar, refine(item) -> the card's 다듬기 action (optional).
export function createStones(opts) {
  const picked = new Set();
  const byKey = () => new Map(opts.items().map((i) => [i.key, i]));
  const selected = () => [...picked].map((k) => byKey().get(k)).filter(Boolean);
  const prune = () => { const known = byKey(); [...picked].forEach((k) => { if (!known.has(k)) picked.delete(k); }); };

  async function act(path, body, message) {
    try { await post(path, body); if (message) toast(message); } catch (e) { toast(e.message, 'error'); return false; }
    picked.clear();
    await opts.reload();
    return true;
  }
  const addSel = (keep) => act('/api/merge/add', { keys: [...picked], keep }, keep ? '북마크하고 목록에도 넣었습니다.' : '목록에 넣었습니다. 선별에서 자리를 찾습니다.');
  async function removeSel() {
    if (!picked.size) return;
    if (picked.size > 1 && !(await confirmDialog({ title: `${picked.size}장을 지우시겠습니까?`, text: '그림이 삭제됩니다.', ok: '삭제', danger: true }))) return;
    await act('/api/merge/delete', { keys: [...picked] });
  }
  const toggle = (key) => { picked.has(key) ? picked.delete(key) : picked.add(key); opts.rerender(); };
  const solo = (it, fn) => () => { picked.clear(); picked.add(it.key); fn(); };

  function card(it) {
    const on = picked.has(it.key);
    const tags = it.pairs.map((p) => `${name(p.t)} ${p.w}`).join(', ');
    const act1 = (iconName, label, onclick, cls = '') =>
      h('button', { class: `stone-btn ${cls}`, title: label, 'aria-label': label, onclick: (e) => { e.stopPropagation(); onclick(); } }, icon(iconName, 'width="16" height="16"'));
    return h('div', { class: `stone ${on ? 'on' : ''}`, key: it.key, title: tags, onclick: () => lightbox(it.image, it.pairs) },
      h('img', { src: it.thumb, alt: '', loading: 'lazy', draggable: false }),
      h('div', { class: 'stone-parents' }, it.parents.map((p) => h('img', { src: p.thumb, alt: '', draggable: false }))),
      h('button', { class: `stone-check ${on ? 'on' : ''}`, 'aria-label': '선택', 'aria-pressed': String(on), onclick: (e) => { e.stopPropagation(); toggle(it.key); } }, icon('check', 'width="14" height="14"')),
      h('div', { class: 'stone-bar' },
        act1('bookmark', '북마크 (목록에 넣고 북마크에)', solo(it, () => addSel(true))),
        opts.refine ? act1('wand', '다듬기로 보내기', () => opts.refine(it)) : null,
        act1('trash', '삭제', solo(it, removeSel), 'danger')));
  }

  function bar() {
    const n = picked.size;
    const all = opts.items().length;
    return h('div', { class: 'sel-bar' },
      h('button', { class: 'btn sm', onclick: () => { n === all ? picked.clear() : opts.items().forEach((i) => picked.add(i.key)); opts.rerender(); } }, icon('check', 'width="13" height="13"'), n === all && all ? '선택 해제' : '전체 선택'),
      n ? [h('span', { class: 'hint' }, `${n}장 선택`),
        h('button', { class: 'btn sm primary', onclick: () => addSel(true) }, icon('bookmark'), '북마크하며 목록에'),
        h('button', { class: 'btn sm', onclick: () => addSel(false) }, '목록에 넣기'),
        ...(opts.extra ? opts.extra(selected()) : []),
        h('button', { class: 'btn sm danger', onclick: removeSel }, icon('trash'), '삭제')]
        : h('span', { class: 'hint' }, '체크해서 여러 장을 한꺼번에 북마크·삭제할 수 있습니다. (Delete 키)'));
  }

  return {
    picked, selected, prune, clear: () => picked.clear(),
    view: (emptyText) => [bar(), opts.items().length ? h('div', { class: 'stones' }, opts.items().map(card)) : h('p', { class: 'muted' }, emptyText)],
    onKey(event) {
      if (event.target?.closest?.('input, textarea, select')) return false;
      if (event.key === 'Delete' && picked.size) { event.preventDefault(); removeSel(); return true; }
      if (event.key === 'Escape' && picked.size) { picked.clear(); opts.rerender(); return true; }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a' && opts.items().length) {
        event.preventDefault(); opts.items().forEach((i) => picked.add(i.key)); opts.rerender(); return true;
      }
      return false;
    },
  };
}
```
