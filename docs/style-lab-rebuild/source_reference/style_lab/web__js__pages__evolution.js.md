# Source Snapshot: web/js/pages/evolution.js

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\web\js\pages\evolution.js`
- Original Byte SHA-256: `8848563a734d4808dba09760b510b975fe178c890fff0fabc2546f7b3df7b0b8`
- Snapshot Text SHA-256: `8848563a734d4808dba09760b510b975fe178c890fff0fabc2546f7b3df7b0b8`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```javascript
// 진화 — breed from the live top 30%, place children between parents, settle the generation.
import { get, post } from '../api.js';
import { h, morph, limits, icon, toast, fmt, notice, tooltip, emptyState, confirmDialog, pageHead, comboTile, comboPreview, previewPage, arrowTarget } from '../ui.js';

// Ordinal ramp for outcomes (validated: one hue, monotone lightness, light end clears the dark surface).
// Two outcomes only: a child either stays in the list (생존) or leaves (탈락). Whether it also became a parent
// is detail: the tooltip and the stat card.
const OUTCOME = [['failed', '탈락', '#4a4f63'], ['entered', '생존', '#9b8fff']];
const STATUS_BADGE = { '평가중': 'sky', '생존': 'accent', '탈락': 'red' };
const statusLabel = (status) => (status === '상위 30% 진입' ? '생존' : status);

// countDraft: what is typed in "만들 개수" until a start saves it as the new default.
let root, app, data = null, countDraft = null, focus = null;
// 세대별 결과: one compact card above the lists, the legend on its title line.
function history(log) {
  const head = h('div', { class: 'row', style: { marginBottom: '12px' } }, h('h3', { style: { margin: 0 } }, '세대별 결과'), h('span', { class: 'spacer' }),
    log.length ? h('div', { class: 'legend', style: { marginTop: 0 } }, OUTCOME.map(([, label, color]) => h('span', {}, h('i', { style: { background: color } }), label))) : null);
  if (!log.length) return h('section', { class: 'card pad-sm' }, head, h('p', { class: 'muted', style: { margin: 0 } }, '세대를 확정하면 결과가 여기에 쌓입니다.'));
  const max = Math.max(...log.map((g) => g.children), 1);
  const columns = h('div', { class: 'columns', role: 'img', 'aria-label': '세대별 진화 결과' }, log.map((g) => {
    const values = { failed: g.failed, entered: g.entered };
    const col = h('div', { class: 'col', key: g.generation }, OUTCOME.filter(([key]) => values[key] > 0).map(([key, , color]) =>
      h('span', { style: { height: `${(values[key] / max) * 100}%`, background: color } })));
    tooltip(col, () => h('div', {}, h('div', { class: 't' }, `${g.generation}세대 · 진화 조합 ${g.children}개`),
      OUTCOME.map(([key, label, color]) => h('div', { class: 'r' }, h('i', { style: { background: color } }), label, h('b', {}, values[key])))));
    return col;
  }));
  return h('section', { class: 'card pad-sm' }, head, columns, h('div', { class: 'col-labels' }, log.map((g) => h('span', {}, g.generation))));
}

// This generation's combos show how their evaluation went where other tiles show the tier.
const pick = (id) => { focus = focus === id ? null : id; render(); };
const childTile = (c) => comboTile(c, { cls: focus === c.id ? 'selected' : '', onclick: () => pick(c.id),
  badge: h('span', { class: `badge ${STATUS_BADGE[statusLabel(c.status)] || ''}` }, statusLabel(c.status)) });
// Once every child is judged, the survivors come first (best rank first), then the ones that failed.
function orderedChildren(d) {
  if (!d.summary?.ready) return d.children;
  const survived = (c) => statusLabel(c.status) === '생존';
  return [...d.children.filter(survived).sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity)),
    ...d.children.filter((c) => !survived(c))];
}
const parentTile = (c) => comboTile(c, { cls: focus === c.id ? 'selected' : '', onclick: () => pick(c.id) });

// When evolution is done: the engine's rule, d.converged_after generations in a row with no survivor. The badge
// and 다듬기로 (off until reached, as 진화 시작 is until it can start) end the line under the page description;
// the rule itself is the badge's tooltip.
function endRule(d) {
  const CONVERGED = d.converged_after;
  let streak = 0;
  for (const g of [...d.log].reverse()) {
    if (g.entered) break;
    streak += 1;
  }
  const badge = h('span', { class: `badge ${d.converged ? 'accent' : ''}` }, `전멸 세대 ${Math.min(streak, CONVERGED)} / ${CONVERGED}`);
  tooltip(badge, () => h('div', {}, `${CONVERGED}세대 연속으로 살아남은 조합이 없으면 다듬기로 넘어가세요. 진화는 언제든 이어 갈 수 있습니다.`));
  return h('div', { class: 'row', style: { gap: '8px', marginLeft: 'auto' } }, badge,
    h('button', { class: 'btn', disabled: !d.converged, title: '두 조합을 섞어 새 그림을 만든 뒤 다듬습니다', onclick: () => app.go('locked') }, '융합 거치기'),
    h('button', { class: 'btn primary', disabled: !d.converged, title: '상위 조합의 가중치를 바로 다듬습니다', onclick: () => app.go('refine') }, '바로 다듬기', icon('arrowRight')));
}

async function discard() {
  const c = [...data.parents, ...data.children].find((x) => x.id === focus);
  if (!c) return toast('버릴 조합을 먼저 선택하세요.', 'error');
  if (!(await confirmDialog({ title: '이 조합을 버리시겠습니까?', text: '그림과 기록이 삭제되고, 진화의 부모에서도 빠집니다.', ok: '버리기' }))) return;
  focus = null;
  await app.act(post('/api/combos/delete', { ids: [c.id] }));
}

function render() {
  const d = data;
  const s = d.summary;
  const job = app.status?.job;
  const countInput = h('input', { class: 'input', type: 'number', ...limits('evo_count'), value: countDraft ?? app.settings.evo_count,
    style: { width: '76px' }, oninput: (e) => { countDraft = e.currentTarget.value; } });
  // Start controls live in the page head, as on 다듬기, so they need no card of their own.
  const controls = h('div', { class: 'row wrap', style: { gap: '8px', marginTop: '14px' } },
      d.batch_active ? null : h('label', { class: 'row', style: { gap: '8px' } }, h('span', { class: 'field-label' }, '만들 개수'), countInput),
      d.batch_active ? null : h('button', { class: 'btn', disabled: !focus || job?.running, onclick: discard }, '선택한 조합 버리기'),
      d.batch_active ? null : h('button', { class: 'btn primary', disabled: !d.can_start || job?.running,
        onclick: () => start(Number(countDraft ?? app.settings.evo_count)) }, icon('play'), '진화 시작'),
      // Once every selection vote is in, there is nothing left to fight: confirming is the next step.
      d.batch_active && !s?.ready ? h('button', { class: 'btn primary', onclick: () => app.go('arena') }, icon('swords'), '평가하러 가기') : null,
      d.batch_active ? h('button', { class: `btn ${s?.ready ? 'primary' : ''}`, disabled: !s?.ready, onclick: finish }, icon('check'), '세대 확정') : null,
      d.batch_active ? h('button', { class: 'btn', disabled: job?.running, onclick: cancelGen }, '이번 세대 취소') : null,
      endRule(d));

  const shown = [...d.children, ...d.parents].find((c) => c.id === focus);
  morph(root, previewPage(
    // The numbers on the description line, as on 그림체; 생존 / 탈락 are this generation's, once it is confirmed.
    pageHead({ title: '진화', desc: `현재 ${d.generation}세대 · 생존 ${s ? fmt(s.entered) : '–'} · 탈락 ${s ? fmt(s.failed) : '–'}`,
      keys: [[['←', '→', '↑', '↓'], '미리보기 이동']],
      // Under the controls, why 진화 시작 is off, as wide as the page.
      below: [controls, !d.batch_active && d.blocker ? h('div', { style: { marginTop: '12px' } },
        notice({ tone: 'amber', iconName: 'alert', title: '지금은 시작할 수 없습니다', text: d.blocker })) : null] }), null, [
    history(d.log),
    d.batch_active ? [
      h('div', { class: 'section-head' }, h('h2', { class: 'section' }, '이번 세대 진화 조합'), h('span', { class: 'hint' }, '선별에서 평가하면 상태가 바뀝니다.')),
      d.children.length ? h('div', { class: 'gallery cols-10' }, orderedChildren(d).map(childTile))
        : emptyState({ iconName: 'sparkle', title: '진화 조합을 만드는 중입니다', text: '첫 조합이 완성되면 바로 평가를 시작할 수 있습니다.' }),
    ] : null,
    h('div', { class: 'section-head' }, h('h2', { class: 'section' }, d.batch_active ? '이번 세대의 비교 기준 (시작할 때의 상위 30%)' : '지금의 상위 30%'),
      h('span', { class: 'hint' }, `${d.parents.length}개 · Elo 순`)),
    d.parents.length ? h('div', { class: 'gallery cols-10' }, d.parents.map(parentTile))
      : emptyState({ iconName: 'crown', title: '아직 상위 30% 조합이 없습니다', text: '선별로 조합들의 순위를 먼저 잡아 주세요.' })],
    comboPreview(shown, app)));
}

async function load() {
  try {
    data = await get('/api/evolution');
    render();
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function start(count) {
  await app.act(post('/api/evolution/start', { count }), `진화 조합 ${count}개를 만들기 시작했습니다. 만들어지는 대로 선별에서 평가할 수 있습니다.`);
  countDraft = null;  // saved as the default now
}

async function cancelGen() {
  if (!(await confirmDialog({ title: `${data.generation}세대 평가를 취소하시겠습니까?`,
    text: '이번에 만든 진화 조합과 그 선별 기록이 삭제되고, 기존 조합은 그대로 남습니다.', ok: '취소하기' }))) return;
  await app.act(post('/api/evolution/cancel'), '이번 세대를 취소했습니다.');
}

async function finish() {
  const s = data.summary;
  const ok = await confirmDialog({ title: `${data.generation}세대를 확정하시겠습니까?`,
    text: `생존 ${s.entered}개 · 탈락 ${s.failed}개\n탈락·제외된 조합도 그림체 목록에 표시와 함께 남습니다.`, ok: '확정' });
  if (!ok) return;
  await app.act(post('/api/evolution/finish'));
}

export default {
  async mount(el, appRef) {
    app = appRef;
    app.setFill(true);
    root = h('div', { style: { display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 } });
    el.append(root);
    await load();
  },
  onStatus(status, previous, force) {
    if (force || !previous || previous.counts.generation !== status.counts.generation || previous.job?.done !== status.job?.done
        || previous.job?.running !== status.job?.running || previous.counts.votes !== status.counts.votes
        || previous.settings_rev !== status.settings_rev) load();
  },
  onKey(event) {
    const id = arrowTarget(event, focus);
    if (id) {
      focus = id;
      render();
    }
  },
  unmount() {
    countDraft = null;
    focus = null;
  },
};
```
