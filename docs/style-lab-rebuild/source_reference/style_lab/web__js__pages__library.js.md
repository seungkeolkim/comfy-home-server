# Source Snapshot: web/js/pages/library.js

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\web\js\pages\library.js`
- Original Byte SHA-256: `1fd394082f8dd0fe14bd5406012cd0799bf50190eaa27cfc688ada41807d2e4f`
- Snapshot Text SHA-256: `35bee12d9280986af3227feabfcf611a5d203b32a5e91a8865139f77f9cb538c`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```javascript
// 조합 — register artists, then roll random combos that will find their place in the arena.
import { get, post } from '../api.js';
import { h, morph, clear, modal, limits, icon, toast, fmt, confirmDialog, promptDialog, shortTag, pickSelect, selectionKeys, pageHead, card } from '../ui.js';

let root, app, artists = [], loras = [];
let latestLoraLoadingNotice = null;
// addText / customText / countDraft: what is typed in the artist and combo boxes and "만들 개수" (the count until a start saves it).
// tab: which list the left card shows (artist | lora); lview is the LoRA list's own search / sort / selection.
const lview = { q: '', sort: 'score', dir: -1, selected: new Set(), anchor: null };
const view = { tab: 'artist', q: '', sort: 'score', dir: -1, selected: new Set(), anchor: null, addText: '', countDraft: null, customText: '' };

function sorted() {
  const q = view.q.trim().toLowerCase();
  const list = artists.filter((a) => !q || a.tag.toLowerCase().includes(q));
  const key = view.sort;
  // Name order matches Windows Explorer (numbers by value); it also breaks ties in the other columns.
  const byName = (a, b) => a.tag.localeCompare(b.tag, 'ko', { numeric: true });
  return list.sort((a, b) => (key === 'tag' ? byName(a, b) * view.dir : (a[key] - b[key]) * view.dir || byName(a, b)));
}

function artistTable() {
  const list = sorted();
  const head = (key, label, num) => h('th', { class: num ? 'num' : '', onclick: () => {
    view.dir = view.sort === key ? -view.dir : key === 'tag' ? 1 : -1;
    view.sort = key;
    render();
  } }, label, view.sort === key ? h('span', { class: 'dir' }, view.dir > 0 ? '▲' : '▼') : null);
  const pick = (a, event) => {
    pickSelect(view, a.tag, event, list.map((x) => x.tag));
    render();
  };
  return h('div', { class: 'table-wrap', style: { maxHeight: '100%' } },
    h('table', { class: 'data artists' },
      h('thead', {}, h('tr', {}, head('order', '#', true), head('tag', '작가'), head('score', '점수', true), head('count', '사용', true), head('winrate', '승률', true))),
      h('tbody', {}, list.map((a) => h('tr', { key: a.tag, class: view.selected.has(a.tag) ? 'selected' : '', onclick: (e) => pick(a, e) },
        h('td', { class: 'num' }, fmt(a.order)), h('td', {}, shortTag(a.tag)), h('td', { class: 'num' },
          a.combos ? `${a.score > 0 ? '+' : ''}${fmt(a.score)}` : '–'), h('td', { class: 'num' }, fmt(a.count)),
        h('td', { class: 'num' }, a.arena_matches ? `${Math.round(a.winrate * 100)}%` : '–'))))));
}

// ---------------------------------------------------------------- LoRAs
function sortedLoras() {
  const q = lview.q.trim().toLowerCase();
  const list = loras.filter((l) => !q || l.name.toLowerCase().includes(q));
  const byName = (a, b) => a.label.localeCompare(b.label, 'ko', { numeric: true });
  return list.sort((a, b) => (lview.sort === 'label' ? byName(a, b) * lview.dir : (a[lview.sort] - b[lview.sort]) * lview.dir || byName(a, b)));
}

function loraTable() {
  const list = sortedLoras();
  const head = (key, label, num) => h('th', { class: num ? 'num' : '', onclick: () => {
    lview.dir = lview.sort === key ? -lview.dir : key === 'label' ? 1 : -1;
    lview.sort = key;
    render();
  } }, label, lview.sort === key ? h('span', { class: 'dir' }, lview.dir > 0 ? '▲' : '▼') : null);
  const pick = (l, event) => {
    pickSelect(lview, l.tag, event, list.map((x) => x.tag));
    render();
  };
  if (!loras.length) {
    return h('div', { class: 'note', style: { padding: '18px 4px' } }, '등록된 LoRA가 없습니다. 위의 "ComfyUI에서 불러오기"로 LoRA를 등록하면 무작위 · 진화 · 다듬기 조합에 함께 들어갑니다.');
  }
  const range = (l) => (l.min === l.max ? l.min.toFixed(1) : `${l.min.toFixed(1)}~${l.max.toFixed(1)}`);
  return h('div', { class: 'table-wrap', style: { maxHeight: '100%' } },
    h('table', { class: 'data artists' },
      h('thead', {}, h('tr', {}, head('order', '#', true), head('label', 'LoRA'), h('th', {}, '트리거'), head('min', '범위', true), head('score', '점수', true), head('count', '사용', true), head('winrate', '승률', true))),
      h('tbody', {}, list.map((l) => h('tr', { key: l.tag, class: lview.selected.has(l.tag) ? 'selected' : '', onclick: (e) => pick(l, e), title: l.name },
        h('td', { class: 'num' }, fmt(l.order)),
        h('td', { class: 'lname' }, l.label, ...problems(l)),
        h('td', { class: 'trig' }, l.trigger ? h('span', { title: l.trigger }, l.trigger) : h('span', { class: 'chip-none', title: '트리거 단어가 비어 있습니다. 필요하면 선택 후 "범위 · 트리거 수정"에서 적어 주세요.' }, '없음')),
        h('td', { class: 'num', style: { whiteSpace: 'nowrap', color: l.own_range ? 'var(--text)' : 'var(--text-3)' },
          title: l.own_range ? '이 LoRA만의 범위' : '설정의 LoRA 가중치 범위를 따름' }, range(l)),
        h('td', { class: 'num' }, l.combos ? `${l.score > 0 ? '+' : ''}${fmt(l.score)}` : '–'),
        h('td', { class: 'num' }, fmt(l.count)),
        h('td', { class: 'num' }, l.arena_matches ? `${Math.round(l.winrate * 100)}%` : '–'))))));
}

// Trouble with a LoRA, always at the same place: small amber marks right after its name.
function problems(l) {
  const mark = (text, title) => h('span', { class: 'warn-chip', title }, '⚠ ' + text);
  return [
    l.incompatible ? mark('호환 안 됨', `파일 정보상 ${l.base || 'SD1.5 / SDXL'} 계열로 학습된 LoRA입니다. Anima에서는 적용되지 않고 그림에 아무 효과가 없습니다.`) : null,
    l.load_failed ? mark('적용 경고', `미적용 Tensor Key ${l.load_failed.keys}${l.load_failed.capped ? '+' : ''}개 (${l.load_failed.time}). Layer 수가 아닙니다. 예: ${l.load_failed.sample.join(', ')}\n${(l.load_failed.patch_errors || []).join('\n')}\n일부 가중치의 적용 문제를 확인했습니다. 자세한 기록: data/lora_warnings.log`) : null,
    l.missing ? mark('파일 없음', 'ComfyUI의 LoRA 목록에 이 파일이 없습니다. 이 LoRA가 든 조합은 그림이 만들어지지 않습니다.') : null];
}

// The bar under a list: what is selected on the left, short actions on the right (all on one line).
function bar(count, unit, buttons) {
  return h('div', { class: 'list-bar' },
    h('span', { class: 'note' }, count ? `${count}${unit} 선택 · Delete로 삭제` : 'Shift/Ctrl로 여러 개 선택'), h('span', { class: 'spacer' }),
    buttons);
}
const sm = (label, title, onclick, cls = '', iconName = null) =>
  h('button', { class: `btn sm ${cls}`, title, onclick }, iconName ? icon(iconName) : null, label);

function loraBar() {
  const n = lview.selected.size;
  return bar(n, '개', [
    sm('', '모든 사용 횟수를 0으로', resetUsage, 'ghost icon', 'refresh'),
    sm('검사', n ? '선택한 LoRA를 하나씩 단독으로 그려 모델에 붙는지 검사합니다 (한 개에 그림 한 장)' : '모든 LoRA를 하나씩 단독으로 그려 모델에 붙는지 검사합니다 (한 개에 그림 한 장)', checkLoras, '', 'check'),
    n ? sm('트리거', '선택한 LoRA 파일에서 트리거 단어를 다시 읽습니다', readLoras, '', 'refresh') : null,
    n === 1 ? sm('수정', '가중치 범위 · 트리거 수정', () => editLora([...lview.selected][0]), '', 'pen') : null,
    n ? sm('삭제', '선택한 LoRA 삭제', () => removeLoras(), 'danger', 'trash') : null]);
}

// The file names ComfyUI has in its loras folder (known once the connection was checked), to tick the ones to register.
async function pickLoras() {
  const conn = app.conf?.connection;
  const have = new Set(loras.map((l) => l.name));
  const names = conn?.lora_names || [];
  await modal((dialog, done) => {
    const chosen = new Set();
    let q = '';
    const list = h('div', { class: 'lora-pick' });
    const manual = h('textarea', { class: 'textarea', rows: 2, placeholder: '목록에 없는 파일은 이름을 직접 적으세요 (줄바꿈으로 구분, 폴더가 있으면 anima/foo.safetensors처럼)' });
    const submit = h('button', { class: 'btn primary', onclick: () => finish() }, icon('plus'), '등록');
    const paint = () => {
      const shown = names.filter((n) => n.toLowerCase().includes(q.toLowerCase()));
      clear(list, shown.length ? shown.map((n) => h('label', { class: have.has(n) ? 'done' : '' },
        h('input', { type: 'checkbox', checked: chosen.has(n), disabled: have.has(n),
          onchange: (e) => { e.currentTarget.checked ? chosen.add(n) : chosen.delete(n); count(); } }),
        n, have.has(n) ? h('span', { class: 'note' }, '등록됨') : null))
        : h('div', { class: 'note', style: { padding: '14px' } }, names.length ? '검색 결과가 없습니다.'
          : conn?.error ? `ComfyUI에 연결하지 못했습니다. 설정에서 연결을 확인해 주세요. (${conn.error})`
            : conn ? 'ComfyUI의 loras 폴더에 LoRA가 없습니다.' : '아직 ComfyUI에서 목록을 받지 못했습니다. 설정에서 "연결 확인"을 누르면 여기에 목록이 뜹니다.'));
    };
    // 전체 선택: everything the search shows that is not registered yet; again, when all of those are ticked, clears them.
    const selectable = () => names.filter((n) => n.toLowerCase().includes(q.toLowerCase()) && !have.has(n));
    const toggleAll = () => {
      const all = selectable();
      const every = all.length > 0 && all.every((n) => chosen.has(n));
      for (const n of all) every ? chosen.delete(n) : chosen.add(n);
      paint();
      count();
    };
    const count = () => { submit.lastChild.textContent = chosen.size ? `${chosen.size}개 등록` : '등록'; };
    const finish = async () => {
      const typed = manual.value.split('\n').map((x) => x.trim()).filter(Boolean);
      const all = [...chosen, ...typed];
      if (!all.length) return toast('등록할 LoRA를 골라 주세요.', 'warn');
      const result = await app.act(post('/api/loras/add', { names: all }));
      toast(result.added ? `LoRA ${result.added}개를 등록했습니다.` : '새로 등록된 LoRA가 없습니다. 이미 있습니다.', result.added ? 'ok' : 'info');
      unreadNotice(result.unread);
      if (result.triggers) toast(`트리거 단어 ${result.triggers}개를 파일에서 읽어 채웠습니다.`, 'ok');
      if (result.incompatible.length) toast(`SD1.5 / SDXL 계열로 보이는 LoRA가 있습니다: ${result.incompatible.join(', ')}. Anima에서는 효과가 없으니 삭제를 권합니다.`, 'warn', 9000);
      if (result.skipped.length) toast(`쉼표(,)나 ::가 든 이름은 쓸 수 없습니다: ${result.skipped.join(', ')}`, 'warn', 6000);
      done(null);
      await load();
    };
    paint();
    dialog.append(h('h3', {}, 'ComfyUI에서 LoRA 불러오기'),
      h('p', {}, '체크한 LoRA를 등록합니다. 등록한 LoRA는 작가처럼 무작위 · 진화 · 다듬기 조합에 들어갑니다.'),
      ...(names.length ? [h('div', { class: 'row', style: { gap: '8px' } },
        h('input', { class: 'input', type: 'search', placeholder: 'LoRA 검색', style: { flex: 1 }, oninput: (e) => { q = e.currentTarget.value; paint(); } }),
        h('button', { class: 'btn', onclick: toggleAll }, icon('check'), '전체 선택 / 해제'))] : []),
      list, manual,
      h('div', { class: 'actions' }, h('button', { class: 'btn ghost', onclick: () => done(null) }, '취소'), submit));
  });
}

async function editLora(tag) {
  const l = loras.find((x) => x.tag === tag);
  if (!l) return;
  const s = app.settings;
  const num = (value, hint) => h('input', { class: 'input num', type: 'number', step: 0.1, min: 0, max: 3, value: value ?? '', placeholder: hint, style: { width: '110px' } });
  const low = num(l.own_range ? l.min_w : null, `${s.lora_min_w} (설정)`), high = num(l.own_range ? l.max_w : null, `${s.lora_max_w} (설정)`);
  const trigger = h('input', { class: 'input', value: l.trigger || '', placeholder: '예) my_style, 1girl' });
  await modal((dialog, done) => {
    const save = async () => {
      const value = (el) => (el.value.trim() === '' ? null : Number(el.value));
      await app.act(post('/api/loras/update', { tag, min_w: value(low), max_w: value(high), trigger: trigger.value }), '저장했습니다.');
      done(null);
      await load();
    };
    dialog.append(h('h3', {}, l.label), h('p', { class: 'note', style: { wordBreak: 'break-all' } }, l.name),
      h('div', { class: 'field-label', style: { margin: '14px 0 6px' } }, '가중치 범위'),
      h('div', { class: 'range-pair' }, low, h('span', {}, '~'), high),
      h('p', { class: 'note' }, '비워 두면 오른쪽 "무작위 조합 만들기"의 LoRA 가중치 범위를 따릅니다. 같은 값을 넣으면 그 가중치로 고정됩니다.'),
      h('div', { class: 'field-label', style: { margin: '14px 0 6px' } }, '트리거 단어 (선택)'),
      trigger,
      h('p', { class: 'note' }, '이 LoRA가 조합에 들어가면 프롬프트의 작가 자리 뒤에 함께 붙습니다.'),
      ...(l.candidates?.length ? [h('div', {}, h('div', { class: 'field-label', style: { margin: '10px 0 6px' } }, '파일에서 읽은 후보 (눌러서 추가 · 많이 쓰인 순)'),
        h('div', { class: 'tags open' }, l.candidates.map(([tag, n]) => h('button', { class: 'tag', style: { cursor: 'pointer' }, title: `${n}회`,
          onclick: () => {
            const have = trigger.value.split(',').map((x) => x.trim()).filter(Boolean);
            if (!have.includes(tag)) trigger.value = [...have, tag].join(', ');
          } }, tag, h('span', { class: 'w' }, n)))))] : []),
      ...(l.base ? [h('p', { class: 'note' }, `학습 기반: ${l.base}`)] : []),
      h('div', { class: 'actions' }, h('button', { class: 'btn ghost', onclick: () => done(null) }, '취소'),
        h('button', { class: 'btn primary', onclick: save }, '저장')));
  });
}

// Ask ComfyUI for the selected files' metadata again (trigger suggestions, base model).
async function readLoras() {
  const result = await app.act(post('/api/loras/read', { tags: [...lview.selected] }));
  const good = result.read - result.unread.length;
  if (good > 0) toast(`${good}개의 파일 정보를 읽었습니다.${result.filled ? ` 트리거 ${result.filled}개를 채웠습니다.` : ' 트리거 후보는 수정 창에서 고를 수 있습니다.'}`, 'ok');
  unreadNotice(result.unread);
  await load();
}

// Why a file gave no trigger: ComfyUI had no metadata for it, or the metadata holds no trigger / tag information.
function unreadNotice(unread) {
  if (!unread?.length) return;
  toast(`트리거를 찾지 못한 LoRA ${unread.length}개. LoRA Manager와 파일 어디에도 트리거가 없습니다. 목록에서 "트리거 없음"으로 표시되며, "트리거 없는 것 선택"으로 한꺼번에 볼 수 있습니다. 이유는 data/lora_meta.log에 있습니다.`, 'warn', 25000);
}

async function checkLoras() {
  const tags = lview.selected.size ? [...lview.selected] : loras.map((l) => l.tag);
  if (!tags.length) return;
  const ok = await confirmDialog({ title: 'LoRA 호환성 검사', text: `${tags.length}개의 LoRA를 하나씩 단독으로 그려 봅니다. 작게(512px, 1스텝) 그려서 빠르며 그림은 저장되지 않습니다. 그래도 LoRA마다 모델에 붙이는 시간은 듭니다. 모델에 붙지 않는 LoRA는 목록에 ⚠ 로드 실패로 표시됩니다.`, ok: '검사 시작' });
  if (!ok) return;
  await app.act(post('/api/loras/check', { tags }), '검사를 시작했습니다. 끝나면 알림이 뜹니다.');
}

async function resetUsage() {
  const ok = await confirmDialog({ title: '사용 횟수 초기화', text: '모든 작가와 LoRA의 "사용" 횟수를 0으로 되돌립니다. 점수와 만든 조합은 그대로입니다.', ok: '초기화', danger: true });
  if (!ok) return;
  await app.act(post('/api/usage/reset', {}), '작가와 LoRA의 사용 횟수를 모두 0으로 초기화했습니다.');
  await load();
}

async function removeLoras(tags = [...lview.selected]) {
  if (!tags.length) return;
  const choice = await modal((dialog, done) => dialog.append(
    h('h3', {}, `LoRA ${tags.length}개 삭제`),
    h('p', {}, '"명단에서만"은 이 LoRA가 앞으로 만드는 조합에 안 들어가게 합니다. 이미 만든 조합은 그대로 남습니다.'),
    h('p', {}, '"조합도 함께"는 이 LoRA가 들어간 조합(그림과 평가 기록 포함)까지 모두 지웁니다. 되돌릴 수 없습니다.'),
    h('div', { class: 'actions' },
      h('button', { class: 'btn ghost', onclick: () => done(null) }, '취소'),
      h('button', { class: 'btn', onclick: () => done('list') }, '명단에서만'),
      h('button', { class: 'btn danger', onclick: () => done('all') }, '조합도 함께 삭제'))));
  if (!choice) return;
  const result = await app.act(post('/api/loras/delete', { tags, with_combos: choice === 'all' }));
  toast(choice === 'all' ? `LoRA ${tags.length}개와 그 LoRA가 든 조합 ${result?.combos ?? 0}개를 삭제했습니다.` : `LoRA ${tags.length}개를 삭제했습니다.`, 'ok');
  lview.selected.clear();
  await load();
}

function tableBar() {
  const n = view.selected.size;
  return bar(n, '명', [
    sm('', '모든 사용 횟수를 0으로', resetUsage, 'ghost icon', 'refresh'),
    n === 1 ? sm('이름', '이름 바꾸기', () => rename([...view.selected][0]), '', 'pen') : null,
    n ? sm('삭제', '선택한 작가 삭제', removeSelected, 'danger', 'trash') : null]);
}

function render() {
  const settings = app.settings;
  const working = app.status?.job?.running;
  const count = h('input', { class: 'input num', type: 'number', ...limits('gen_count'), value: view.countDraft ?? settings.gen_count, style: { width: '84px' },
    oninput: (e) => { view.countDraft = e.currentTarget.value; } });
  const right = [
    h('label', { class: 'inline-field' }, h('span', {}, '시드'),
      h('div', { class: 'input-group' }, ruleInput('seed', null),
        h('button', { class: 'btn icon sm', title: '무작위 시드', 'aria-label': '무작위 시드', onclick: () => saveRule('seed', String(Math.floor(Math.random() * app.meta.max_seed))) }, icon('refresh')))),
    h('label', { class: 'inline-field' }, h('span', {}, '만들 개수'), count),
    h('button', { class: 'btn primary lg', disabled: working, onclick: () => generate(Number(view.countDraft ?? settings.gen_count)) }, icon('zap'), working ? '생성 중…' : '만들기')];
  const needArtists = app.status && !app.status.stage.checklist.artists && settings.artists_on && artists.length >= settings.gen_min;
  morph(root,
    pageHead({ title: '조합', right,
      keys: [[['Delete'], '삭제'], [['Esc'], '선택 해제'], [['Ctrl', 'A'], '모두 선택'], [[], 'Shift/Ctrl 클릭으로 여러 개 선택']],
      desc: '작가와 LoRA를 섞어 무작위 조합을 만듭니다. 끈 쪽은 조합에 들어가지 않습니다.',
      below: needArtists ? h('div', { class: 'row', style: { marginTop: '12px' } }, h('button', { class: 'btn primary sm', onclick: confirmArtists }, icon('check'), '작가 목록 그대로 사용'),
        h('span', { class: 'note' }, '작가를 더하거나 빼면 확인한 것으로 저장됩니다.')) : null }),
    h('div', { class: 'combo-cols' }, artistSide(settings), loraSide(settings)));
}

// One side of the page: its title and on/off switch, its two rules at the top, then its list. Off: the whole body greys out.
function side({ iconName, tone, title, key, on, rules, children }) {
  return h('section', { class: `card side ${on ? '' : 'is-off'}` },
    h('div', { class: 'side-head' },
      h('div', { class: `icon-badge ${tone}` }, icon(iconName)), h('h3', {}, title), h('span', { class: 'spacer' }),
      h('button', { class: `power ${on ? 'on' : ''}`, role: 'switch', 'aria-checked': String(on), title: on ? `${title}를 끄면 조합에 들어가지 않습니다` : `${title} 켜기`,
        onclick: () => saveRule(key, !on) }, icon('power'), on ? '켜짐' : '꺼짐')),
    h('div', { class: 'side-body' }, h('div', { class: 'side-rules' }, rules), children));
}

function artistSide(s) {
  const input = h('textarea', { class: 'textarea', rows: 2, value: view.addText, oninput: (e) => { view.addText = e.currentTarget.value; },
    placeholder: '추가할 작가 (쉼표·줄바꿈으로 여러 명)\n프롬프트를 통째로 붙여 넣어도 됩니다' });
  const search = h('input', { class: 'input', type: 'search', placeholder: '작가 검색', value: view.q, oninput: (e) => { view.q = e.currentTarget.value; render(); } });
  return side({ iconName: 'users', tone: 'rose', title: `작가 ${fmt(artists.length)}명`, key: 'artists_on', on: s.artists_on,
    rules: [rule('조합당 작가 수', pair(ruleInput('gen_min'), ruleInput('gen_max'))), rule('기본 가중치 범위', pair(ruleInput('global_min_w', 0.1), ruleInput('global_max_w', 0.1)))],
    children: [
      h('div', { class: 'add-row' }, input, h('button', { class: 'btn primary', onclick: add }, icon('plus'), '등록')),
      h('label', { class: 'search', style: { display: 'block', margin: '12px 0 8px' } }, icon('search'), search),
      h('div', { class: 'side-list' }, artistTable()),
      tableBar()] });
}

/** 최근 생성의 구성요소별 적용 안내를 알림 대신 펼쳐 보는 기록으로 표시합니다. */
function renderLoraLoadingNotice() {
  const notice = latestLoraLoadingNotice;
  if (!notice) return null;
  const counts = notice.counts;
  const encoderWasExcluded = notice.model_only && counts.text_encoder > 0;
  return h('details', { class: 'note', style: { margin: '10px 0', overflowWrap: 'anywhere' } },
    h('summary', { style: { cursor: 'pointer', color: 'var(--text-2)' } }, `LoRA 적용 기록 · ${notice.time}`),
    h('div', { style: { marginTop: '8px' } },
      h('p', {}, encoderWasExcluded ? '모델만 적용하는 설정에 따라 Text Encoder 가중치가 제외되었습니다. 이 항목은 반복 알림 없이 기록합니다.' : '최근 생성에서 수집한 LoRA 적용 기록입니다.'),
      h('p', {}, `관측한 미적용 Tensor Key: 모델 ${counts.model} · Text Encoder ${counts.text_encoder} · 미확인 ${counts.unknown}. Patch 오류 ${notice.patch_error_count}개.`),
      notice.has_warning ? h('p', {}, '일부 가중치 적용 문제를 발견했습니다. 상세 로그를 확인해 주세요.') : null,
      notice.capped ? h('p', {}, '로그가 잘려 일부 기록만 확인했습니다. 표시 수는 관측한 최소 수이며 전체 적용 성공 여부는 확정할 수 없습니다.') : null,
      h('p', {}, `생성에 사용한 LoRA: ${notice.names.join(', ')}`),
      notice.names.length > 1 ? h('p', {}, '여러 LoRA를 함께 사용한 기록이므로 원인 파일을 특정하지 않습니다.') : null,
      h('p', {}, '상세 기록: data/lora_warnings.log')));
}

function loraSide(s) {
  const search = h('input', { class: 'input', type: 'search', placeholder: 'LoRA 검색', value: lview.q, oninput: (e) => { lview.q = e.currentTarget.value; render(); } });
  return side({ iconName: 'wand', tone: 'sky', title: `LoRA ${fmt(loras.length)}개`, key: 'loras_on', on: s.loras_on,
    rules: [rule('조합당 LoRA 수', pair(ruleInput('lora_min'), ruleInput('lora_max'))), rule('기본 가중치 범위', pair(ruleInput('lora_min_w', 0.1), ruleInput('lora_max_w', 0.1)))],
    children: [
      h('div', { class: 'add-row' }, h('button', { class: 'btn primary', onclick: pickLoras }, icon('plus'), 'ComfyUI에서 불러오기'),
        h('button', { class: 'btn', onclick: () => app.go('settings', { focus: 'connection' }) }, '연결 설정')),
      h('label', { class: 'search', style: { display: 'block', margin: '12px 0 8px' } }, icon('search'), search),
      renderLoraLoadingNotice(),
      h('div', { class: 'side-list' }, loraTable()),
      loraBar()] });
}

function rule(label, value) {
  return h('div', { class: 'rule' }, h('div', { class: 'rule-label' }, label), value);
}

const pair = (a, b) => h('div', { class: 'range-pair' }, a, h('span', {}, '~'), b);

// The combo rules and the seed are edited here, where combos are made: saved when the field is left (or Enter);
// a refused value is shown in the error toast and the field goes back to what is saved. step null: the seed
// (text: it may be empty, which draws one on the first image).
function ruleInput(key, step = 1) {
  const seed = step == null;
  return h('input', { class: 'input num', ...(seed ? { inputmode: 'numeric', placeholder: '무작위', style: { width: '120px' } } : { type: 'number', step, ...limits(key) }),
    value: app.settings[key],
    onchange: (e) => saveRule(key, seed ? e.currentTarget.value.trim() : Number(e.currentTarget.value)),
    onkeydown: (e) => { if (e.key === 'Enter') e.currentTarget.blur(); } });
}

async function saveRule(key, value) {
  await app.act(post('/api/settings', { changes: { [key]: value } }), '저장했습니다.').catch(() => {});
  render();
}

async function load() {
  try {
    // The engine keeps artists in the order they were added: that place is the 등록 순 (# column).
    artists = (await get('/api/artists')).map((a, i) => ({ ...a, order: i + 1 }));
    loras = (await get('/api/loras')).map((l, i) => ({ ...l, order: i + 1 }));
    latestLoraLoadingNotice = await get('/api/loras/loading');
    const known = new Set(loras.map((l) => l.tag));
    lview.selected = new Set([...lview.selected].filter((tag) => known.has(tag)));
    render();
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function add() {
  if (!view.addText.trim()) return toast('등록할 작가를 입력해 주세요.', 'warn');
  const result = await app.act(post('/api/artists/add', { text: view.addText }));
  toast(result.added ? `작가 ${result.added}명을 등록했습니다.` : '새로 등록된 작가가 없습니다. 이미 있거나 비어 있습니다.', result.added ? 'ok' : 'info');
  view.addText = '';
  render();
}

async function confirmArtists() {
  await app.act(post('/api/settings', { changes: { artists_checked: true } }), '작가 목록을 확인했습니다.');
}

async function rename(tag) {
  // Edit just the name: the server puts "artist:" back in front.
  const name = tag.replace(/^artist:/, '');
  const value = await promptDialog({ title: '작가 이름 수정', text: '이 작가가 들어간 조합의 태그도 함께 바뀝니다.', value: name });
  if (value == null || value.trim().replace(/^artist:/, '') === name) return;
  await app.act(post('/api/artists/rename', { old: tag, new: value }), '이름을 바꿨습니다.');
  view.selected.clear();
  render();
}

async function removeSelected() {
  const tags = [...view.selected];
  const ok = await confirmDialog({ title: `작가 ${tags.length}명 삭제`, text: '명단에서만 빠지고, 이미 만든 조합은 그대로 남습니다.', ok: '삭제', danger: true });
  if (!ok) return;
  await app.act(post('/api/artists/delete', { tags }), `작가 ${tags.length}명을 삭제했습니다.`);
  view.selected.clear();
  render();
}

async function generate(count) {
  await app.act(post('/api/generate/random', { count }), `조합 ${count}개를 만들기 시작했습니다. 완성되는 대로 선별에서 자리를 찾을 수 있습니다.`);
  view.countDraft = null;  // saved as the default now
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
    if (force || (previous && (previous.job?.running !== status.job?.running || previous.settings_rev !== status.settings_rev))) load();
  },
  unmount() {
    view.countDraft = null;
  },
  // Same keys as the 그림체 list (Ctrl+A picks everyone the search shows).
  onKey(event) {
    if (view.tab === 'lora') return selectionKeys(event, lview, { order: () => sortedLoras().map((l) => l.tag), remove: removeLoras, changed: render });
    selectionKeys(event, view, { order: () => sorted().map((a) => a.tag), remove: removeSelected, changed: render });
  },
};
```
