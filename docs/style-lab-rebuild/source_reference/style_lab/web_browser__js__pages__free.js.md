# Source Snapshot: web_browser/js/pages/free.js

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\web_browser\js\pages\free.js`
- Original Byte SHA-256: `f37f5f13cd6a27fecd1261461ad2d1232b1705008df95c90f0aae6da8c76439f`
- Snapshot Text SHA-256: `f37f5f13cd6a27fecd1261461ad2d1232b1705008df95c90f0aae6da8c76439f`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```javascript
// 자유 생성 — try any prompt with the current settings and seed; results stay in a small gallery.
import { get, post } from '../api.js';
import { h, morph, icon, toast, art, lightbox, emptyState, openOriginal, pageHead, pickCombo, confirmDialog } from '../ui.js';

let root, app, results = [], draft = '';
// Per picture overrides of the settings (empty = the settings' own): base prompt, negative, seed. `from` is the combo loaded.
const picked = new Set();  // selected pictures (image names) for 삭제
let baseDraft = null, negDraft = null, seedDraft = '', from = null, advanced = false;

async function load_combo() {
  let list;
  try { list = (await get('/api/combos')).active; } catch (e) { toast(e.message, 'error'); return; }
  const c = await pickCombo({ list, title: '그림체에서 불러오기', ok: '이 그림체 불러오기', current: from?.id });
  if (!c) return;
  draft = c.anima;  // Anima's own writing: (@artist:1.2), ..., <lora:name:0.7>
  from = c;
  seedDraft = c.seed != null ? String(c.seed) : '';
  render();
}

function render() {
  const working = app.status?.job?.running;
  morph(root,
    pageHead({ title: '자유 생성', desc: '원하는 태그를 넣어 한 장씩 그려 봅니다. 설정의 기본·네거티브 프롬프트와 고정 시드를 그대로 씁니다.' }),
    h('div', { class: 'fill-grid', style: { gridTemplateColumns: 'minmax(0, 380px) minmax(0, 1fr)' } },
      h('section', { class: 'card fill-card' },
        h('div', { class: 'row', style: { gap: '8px', marginBottom: '10px' } },
          h('button', { class: 'btn', onclick: load_combo }, icon('grid'), '그림체에서 불러오기'),
          from ? h('span', { class: 'hint' }, `불러온 조합 · Elo ${from.elo}`) : null),
        h('div', { class: 'field' }, h('label', {}, '프롬프트 (작가 태그 자리)'),
          h('textarea', { class: 'textarea', rows: 6, value: draft, oninput: (e) => { draft = e.currentTarget.value; },
            placeholder: '예) 1.2::artist:rurudo ::, 0.9::artist:shigure ui ::  (또는 (@rurudo:1.2), @shigure ui)\n기본 프롬프트의 {artist} 자리에 들어갑니다.' })),
        h('div', { style: { marginTop: '10px' } },
          h('button', { class: 'btn ghost sm', onclick: () => { advanced = !advanced; render(); } }, advanced ? '이번만 바꾸기 접기' : '기본·네거티브 프롬프트와 시드 이번만 바꾸기')),
        advanced ? h('div', { style: { marginTop: '10px', display: 'grid', gap: '10px' } },
          h('div', { class: 'field' }, h('label', {}, '기본 프롬프트 (이번만) — {artist} 자리에 위 프롬프트가 들어갑니다'),
            h('textarea', { class: 'textarea', rows: 4, value: baseDraft ?? app.settings.base_prompt ?? '', oninput: (e) => { baseDraft = e.currentTarget.value; } })),
          h('div', { class: 'field' }, h('label', {}, '네거티브 프롬프트 (이번만)'),
            h('textarea', { class: 'textarea', rows: 3, value: negDraft ?? app.settings.negative ?? '', oninput: (e) => { negDraft = e.currentTarget.value; } })),
          h('div', { class: 'field' }, h('label', {}, '시드 (비우면 설정의 고정 시드)'),
            h('input', { class: 'input', value: seedDraft, oninput: (e) => { seedDraft = e.currentTarget.value; } })),
          h('button', { class: 'btn ghost sm', onclick: () => { baseDraft = null; negDraft = null; seedDraft = ''; render(); } }, '설정값으로 되돌리기'))
          : null,
        h('button', { class: 'btn primary lg', style: { width: '100%', marginTop: '14px' }, disabled: working, onclick: () => generate(draft) },
          icon('brush'), working ? '생성 중…' : '그리기')),
      h('section', { class: 'card fill-card' },
        results.length ? bulkBar() : null,
        results.length ? h('div', { class: 'gallery lg' }, results.map((r) =>
          h('div', { class: `tile ${picked.has(r.image) ? 'selected' : ''}`, key: r.image, onclick: () => lightbox(r.url) },
            art({ thumb: `/thumb/${r.image}`, image: r.url }, { corners: [['br', h('button', { class: `tile-check ${picked.has(r.image) ? 'on' : ''}`, 'aria-label': '선택', 'aria-pressed': String(picked.has(r.image)),
              onclick: (e) => { e.stopPropagation(); toggle(r.image); } }, icon('check', 'width="14" height="14"'))]] }),
            h('div', { class: 'caption', style: { flexDirection: 'column', alignItems: 'stretch', gap: '2px' } },
              h('span', { class: 'mono', style: { color: 'var(--text-2)', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' } }, r.prompt || '(빈 프롬프트)'),
              h('div', { class: 'row', style: { gap: '4px', flexWrap: 'wrap' } },
                r.listed ? h('span', { class: 'badge accent' }, '목록에 있음') : [
                  h('button', { class: 'btn sm primary', title: '목록에 넣고 북마크', onclick: (e) => { e.stopPropagation(); adopt(r, { keep: true }); } }, icon('bookmark'), '북마크'),
                  h('button', { class: 'btn sm', onclick: (e) => { e.stopPropagation(); adopt(r, {}); } }, '목록에'),
                  h('button', { class: 'btn sm', onclick: (e) => { e.stopPropagation(); adopt(r, { refine: true }); } }, '다듬기')],
                h('span', { class: 'spacer' }),
                h('span', { class: 'note' }, `${r.time} · 시드 ${r.seed}`),
                h('button', { class: 'btn ghost icon-btn sm danger', 'aria-label': '삭제', title: '삭제', onclick: (e) => { e.stopPropagation(); remove([r.image]); } }, icon('trash')),
                h('button', { class: 'btn ghost icon-btn sm', 'aria-label': '원본 열기',
                  onclick: (e) => { e.stopPropagation(); openOriginal({ file: r.image }); } }, icon('external')))))))
          : h('div', { class: 'fill-center' }, emptyState({ iconName: 'brush', title: '아직 그린 그림이 없습니다', text: '왼쪽에 태그를 넣고 그려 보세요. 그린 그림은 모두 여기에 모입니다.' })))));
}

async function load() {
  try {
    results = (await get('/api/free')).results;
    render();
  } catch (error) {
    toast(error.message, 'error');
  }
}

// A picture of the gallery into the list (보관함 / 다듬기 optional); no new image is drawn.
async function adopt(r, opts) {
  try {
    var res = await post('/api/free/adopt', { image: r.image, ...opts });
    toast(opts.keep ? '북마크하고 목록에도 넣었습니다.' : '목록에 넣었습니다. 선별에서 자리를 찾습니다.');
  } catch (e) { toast(e.message, 'error'); return; }
  if (opts.refine) { app.go('refine', { id: res?.id ?? res?.listed }); return; }
  await load();
}

const toggle = (image) => { picked.has(image) ? picked.delete(image) : picked.add(image); render(); };

function bulkBar() {
  const n = picked.size;
  return h('div', { class: 'sel-bar' },
    h('button', { class: 'btn sm', onclick: () => { n === results.length ? picked.clear() : results.forEach((r) => picked.add(r.image)); render(); } },
      icon('check', 'width="13" height="13"'), n === results.length ? '선택 해제' : '전체 선택'),
    n ? [h('span', { class: 'hint' }, `${n}장 선택`), h('button', { class: 'btn sm danger', onclick: () => remove([...picked]) }, icon('trash'), '삭제')]
      : h('span', { class: 'hint' }, '체크해서 여러 장을 한꺼번에 지울 수 있습니다. (Delete 키)'));
}

async function remove(images) {
  if (images.length > 1 && !(await confirmDialog({ title: `${images.length}장을 지우시겠습니까?`, text: '그림이 삭제됩니다. 목록에 넣은 그림은 조합으로 남습니다.', ok: '삭제', danger: true }))) return;
  try { await post('/api/free/delete', { images }); } catch (e) { toast(e.message, 'error'); return; }
  images.forEach((i) => picked.delete(i));
  await load();
}

async function generate(text) {
  const body = { prompt: text };
  if (baseDraft != null && baseDraft !== app.settings.base_prompt) body.base = baseDraft;
  if (negDraft != null && negDraft !== app.settings.negative) body.negative = negDraft;
  if (String(seedDraft).trim()) body.seed = String(seedDraft).trim();
  await app.act(post('/api/generate/free', body), '그리는 중입니다.');
}

export default {
  async mount(el, appRef) {
    app = appRef;
    app.setFill(true);
    root = h('div', { class: 'page-col' });
    el.append(root);
    await load();
  },
  onKey(event) {
    if (event.target?.closest?.('input, textarea, select')) return;
    if (event.key === 'Delete' && picked.size) { event.preventDefault(); remove([...picked]); }
    else if (event.key === 'Escape' && picked.size) { picked.clear(); render(); }
  },
  onStatus(status, previous, force) {
    if (force || (previous && previous.job?.running !== status.job?.running)) load();
  },
};
```
