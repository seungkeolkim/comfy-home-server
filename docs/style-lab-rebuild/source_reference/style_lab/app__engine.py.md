# Source Snapshot: app/engine.py

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\app\engine.py`
- Original Byte SHA-256: `fa67f4c244a629fb36cfc62293f66b3406fcf46e9d5bc0c6ab97af191f4d319f`
- Snapshot Text SHA-256: `e1364821524ba830131c074cff6fa7d885e9d413e5994da1711d8a4b6569c6dd`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```python
"""State, workflow and background jobs for Anima Style Lab.

Everything the UI can do goes through :class:`Engine`. All state changes happen under one
re-entrant lock and are saved atomically, so the HTTP threads and the generation thread never
race. Pure calculations live in :mod:`core`.
"""
import collections
import copy
import io
import json
import math
import random
import re
import shutil
import threading
import time
import uuid
import zipfile
import zlib
from datetime import datetime
from pathlib import Path

import core

STAGES = ('준비', '순위 결정', '진화', '다듬기', '완성')
ARENA_MODES = ('auto', 'league', 'top')
IMPROVE_JITTER_START = 0.3
IMPROVE_JITTER_MIN = 0.1
IMPROVE_JITTER_STEP = 0.1  # the adjustment narrows by this much each round
FINAL_CHECK_SEEDS = 3
CONVERGED_GENERATIONS = 2  # generations in a row where no child survived
MIN_RATED_FOR_EVOLUTION = 10
COMBO_KEYS = {'id', 'style', 'elo', 'matches', 'wins'}  # what an imported combo must have
FRESH_LADDER = 24  # rated combos before newcomers are placed on the ladder instead of fighting each other
MAX_FAILURE_STREAK = 3  # images failing in a row (each already retried) stop the job
DRAW_TRIES = 30  # draws to find a style not made before, per image (random combos, evolution, refine variants)

SETTING_DEFAULTS = {
    'comfy_url': core.COMFY_URL_DEFAULT, 'unet_name': '', 'clip_name': '', 'vae_name': '',
    'size': list(core.SIZE_PRESETS)[0], 'sampler': 'er_sde', 'scheduler': 'sgm_uniform',
    'steps': 30, 'cfg': 4.5, 'delay': 0.0, 'seed': '',
    'global_min_w': 0.8, 'global_max_w': 1.8, 'gen_min': 4, 'gen_max': 8,
    'lora_min_w': 0.4, 'lora_max_w': 1.0, 'lora_min': 0, 'lora_max': 2, 'lora_clip': False,
    'gen_count': 50, 'evo_count': 12, 'improve_variants': 4,
    'base_prompt': core.DEFAULT_BASE_PROMPT, 'negative': core.DEFAULT_NEGATIVE,
    'arena_mode': 'auto', 'arena_blind': False,
    'prompt_checked': False, 'artists_checked': False,
    'artists_on': True, 'loras_on': True,  # either side of a combo can be switched off (the ranges are kept)
}
PROMPT_KEYS = ('base_prompt', 'negative')
SETTING_TYPES = {key: type(value) for key, value in SETTING_DEFAULTS.items()}
# Same limits as the settings screen: (label, low, high).
SETTING_RANGES = {
    'steps': ('Steps', 1, 100), 'cfg': ('CFG', 0, 30),
    'delay': ('생성 간 대기', 0, 30), 'global_min_w': ('최소 가중치', 0.1, 3), 'global_max_w': ('최대 가중치', 0.1, 3),
    'gen_min': ('조합당 최소 작가 수', 0, 20), 'gen_max': ('조합당 최대 작가 수', 0, 20),
    'lora_min_w': ('LoRA 최소 가중치', 0, 3), 'lora_max_w': ('LoRA 최대 가중치', 0, 3),
    'lora_min': ('조합당 최소 LoRA 수', 0, 10), 'lora_max': ('조합당 최대 LoRA 수', 0, 10),
    'gen_count': ('무작위 조합 기본 개수', 1, 1000), 'evo_count': ('진화 조합 수', 1, 60),
    'improve_variants': ('다듬기 라운드당 변형', 2, 12),
}
SETTING_CHOICES = {'size': list(core.SIZE_PRESETS), 'arena_mode': ARENA_MODES}


class UserError(Exception):
    """A request the user can fix (shown as a message, not a crash)."""


def _now():
    return datetime.now().strftime('%H:%M:%S')


def _new_id():
    return uuid.uuid4().hex[:10]


def _next_jitter(jitter):
    return max(IMPROVE_JITTER_MIN, round(jitter - IMPROVE_JITTER_STEP, 1))


def _jitter_schedule():
    """Every round's adjustment, first to last: [0.3, 0.2, 0.1]."""
    steps = round((IMPROVE_JITTER_START - IMPROVE_JITTER_MIN) / IMPROVE_JITTER_STEP)
    return [round(IMPROVE_JITTER_START - i * IMPROVE_JITTER_STEP, 1) for i in range(steps + 1)]


class Engine:
    def __init__(self, data_dir: Path, generate=None, check_connection=None, auto_connection=False, lora_meta=None, lora_words=None):
        self.data_dir = Path(data_dir)
        self.img_dir = self.data_dir / 'images'
        self.thumb_dir = self.data_dir / 'thumbs'
        self.state_file = self.data_dir / 'state.json'
        self.workflow_file = self.data_dir / 'workflow.json'
        self.img_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._reveal_items = {}  # the final check's pictures, kept in memory just long enough to show the last vote
        # Injected for tests; the real ones call ComfyUI.
        self._generate = generate or core.generate_for_settings
        self._check_connection = check_connection or core.comfy_check
        self._lora_meta = lora_meta or core.comfy_lora_metadata
        self._lora_words = lora_words or core.comfy_lora_manager_words
        self.state = core.load_state(self.state_file)
        self.state.setdefault('loras', [])
        tune = self.state.get('tune')
        if tune and 'tags' not in tune:  # a session saved before 다듬기 could move artists too
            tune['tags'] = tune.pop('loras', [])
            tune.setdefault('scope', 'lora')
        self.state.setdefault('merged', [])  # 합친 그림: made on the 융합 tab, kept there until put in the list or deleted
        self.events = collections.deque(maxlen=60)
        self._warned_lora_problems = set()
        self._event_id = 0
        self.job = None
        self.stop_event = threading.Event()
        self.current = None
        self._last_pair = ()
        self.undo_stack = collections.deque(maxlen=30)
        self.skipped_ties = set()
        self.connection = None
        self.auto_connection = auto_connection  # the app checks it at launch; tests never call ComfyUI
        self.generating_children = None  # (made, total) while an evolution batch is being generated
        if self.state.get('load_error'):
            backup = core.backup_file(self.state_file)
            hint = f' 직전 실행 때의 백업은 {backup.name}입니다.' if backup.exists() else ''
            self._event('warn', f"state.json을 읽지 못해 새로 시작했습니다. 원본은 {self.state.pop('load_error')}에 보존했습니다.{hint}")

    # ------------------------------------------------------------------ basics
    def save(self):
        with self.lock:
            core.write_state(self.state_file, self.state)

    def _event(self, level, text):
        self._event_id += 1
        self.events.append({'id': self._event_id, 'level': level, 'text': text, 'time': _now()})

    def _event_locked(self, level, text):
        with self.lock:
            self._event(level, text)

    def events_since(self, since):
        return [event for event in self.events if event['id'] > since]

    @property
    def combos(self):
        return self.state['combinations']

    @property
    def selection(self):
        return self.state['selection']

    @property
    def retired(self):
        return self.selection['retired']

    def settings(self):
        ui = self.state['ui_state']
        s = {key: ui.get(key, default) for key, default in SETTING_DEFAULTS.items()}
        for key, choices in SETTING_CHOICES.items():
            if s[key] not in choices:  # a choice a later release dropped (the 960x1088 size): back to the default
                s[key] = SETTING_DEFAULTS[key]
        for key in ('sampler', 'scheduler'):
            if str(s[key]).startswith('k_'):  # a NovelAI sampler name from an older data file
                s[key] = SETTING_DEFAULTS[key]
        return s

    def rules(self):
        """The settings combos are made with: a side that is switched off counts as 0 pieces."""
        s = self.settings()
        if not s['artists_on']:
            s['gen_min'] = s['gen_max'] = 0
            s['lora_min'] = max(1, s['lora_min'])
            s['lora_max'] = max(s['lora_min'], s['lora_max'])
        if not s['loras_on']:
            s['lora_min'] = s['lora_max'] = 0
        return s

    def update_settings(self, changes: dict):
        with self.lock:
            ui = self.state['ui_state']
            before = dict(ui)
            try:
                self._apply_settings(ui, changes)
            except UserError:
                ui.clear()
                ui.update(before)  # a refused change leaves nothing behind
                raise
            if 'comfy_url' in changes and changes['comfy_url'] != before.get('comfy_url', core.COMFY_URL_DEFAULT):
                self.connection = None  # it was the old address's
            if 'arena_mode' in changes:
                self.current = None
            self.save()
            return self.settings()

    def _apply_settings(self, ui, changes):
        """Write checked ``changes`` into ``ui``. Raises UserError."""
        for key, value in changes.items():
            if key not in SETTING_TYPES:
                raise UserError(f'알 수 없는 설정입니다: {key}')
            kind = SETTING_TYPES[key]
            try:
                if kind is bool and not isinstance(value, bool):
                    raise TypeError
                value = kind(value)
            except (TypeError, ValueError):
                raise UserError(f'{key} 값이 올바르지 않습니다.')
            if kind is str and key != 'base_prompt' and key != 'negative':
                value = value.strip()
            if key == 'seed':
                value = value.strip()
                if value and (not value.isdigit() or int(value) > core.MAX_SEED):
                    raise UserError(f'시드는 0 ~ {core.MAX_SEED} 사이의 정수로 입력하거나 비워 두세요.')
            if key in SETTING_CHOICES and value not in SETTING_CHOICES[key]:
                raise UserError(f'{key} 값이 올바르지 않습니다.')
            if key in SETTING_RANGES:
                label, low, high = SETTING_RANGES[key]
                if not low <= value <= high:  # also refuses NaN
                    raise UserError(f'{label}은(는) {low} ~ {high} 사이로 입력해 주세요.')
            ui[key] = value
            if key in PROMPT_KEYS:
                ui['prompt_checked'] = True  # editing the prompt is checking it
        s = self.settings()
        if not s['artists_on'] and not s['loras_on']:
            raise UserError('작가와 LoRA를 모두 끌 수는 없습니다. 한쪽은 켜 두세요.')
        if s['gen_max'] < s['gen_min']:
            raise UserError('조합당 작가 수 범위를 확인해 주세요 (최소 ≤ 최대).')
        if not s['global_min_w'] < s['global_max_w']:
            raise UserError('가중치 범위를 확인해 주세요 (최소 < 최대).')
        if s['lora_max'] < s['lora_min']:
            raise UserError('조합당 LoRA 수 범위를 확인해 주세요 (최소 ≤ 최대).')
        if s['lora_max_w'] < s['lora_min_w']:
            raise UserError('LoRA 가중치 범위를 확인해 주세요 (최소 ≤ 최대).')

    def _start_count(self, key, value):
        """The count a start request asks for (or the saved one), checked like the settings field and
        kept as the next default, so the pages need no separate settings save."""
        if value is None:
            return self.settings()[key]
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise UserError('개수가 올바르지 않습니다.')
        self.update_settings({key: value})
        return value

    def workflow_state(self):
        """data/workflow.json: {'exists', 'error'}; a ComfyUI workflow saved in API format replaces the built-in one."""
        try:
            return {'exists': core.load_workflow_file(self.workflow_file) is not None, 'error': None}
        except core.ComfyError as exc:
            return {'exists': True, 'error': str(exc)}

    def _gen_settings(self):
        """Settings for one generation run; an empty seed gets a random one that is kept."""
        s = self.settings()
        try:
            workflow = core.load_workflow_file(self.workflow_file)
        except core.ComfyError as exc:
            raise UserError(str(exc))
        if workflow is None and not (s['unet_name'] and s['clip_name'] and s['vae_name']):
            raise UserError('설정에서 ComfyUI 주소를 확인하고 Anima 모델(diffusion model · 텍스트 인코더 · VAE)을 골라 주세요.')
        if not s['seed']:
            s['seed'] = str(random.randint(0, core.MAX_SEED))
            self.state['ui_state']['seed'] = s['seed']
            self._event('info', f"시드를 {s['seed']}(으)로 정했습니다. 앞으로 모든 그림이 이 시드로 생성됩니다.")
        width, height = core.SIZE_PRESETS[s['size']]
        return dict(comfy_url=s['comfy_url'], unet_name=s['unet_name'], clip_name=s['clip_name'], vae_name=s['vae_name'],
                    workflow=workflow, width=width, height=height, steps=s['steps'], cfg=s['cfg'],
                    sampler=s['sampler'], scheduler=s['scheduler'], delay=s['delay'],
                    base_prompt=s['base_prompt'], negative=s['negative'], seed=int(s['seed']),
                    lora_clip=s['lora_clip'], lora_report=self._lora_report,
                    lora_triggers={core.lora_name(l['tag']): l.get('trigger', '') for l in self.state['loras'] if l.get('trigger')})

    # ------------------------------------------------------------------ lookups
    def find(self, combo_id):
        for combo in self.combos:
            if combo['id'] == combo_id:
                return combo
        return None

    def find_any(self, combo_id):
        found = self.find(combo_id)
        if found:
            return found
        for combo in self.retired:
            if combo['id'] == combo_id:
                return combo
        improve = self.state.get('improve') or {}
        tune = self.state.get('tune') or {}
        return ((tune.get('items') or {}).get(combo_id) or (improve.get('items') or {}).get(combo_id) or (improve.get('final_items') or {}).get(combo_id)
                or self._reveal_items.get(combo_id))

    def rated(self):
        return [c for c in self.combos if core.is_rated(c)]

    def newcomers(self):
        children = set(self.selection['candidate_ids'])
        return [c for c in self.combos if not core.is_rated(c) and c['id'] not in children]

    def ranking_counts(self, rated=None, waiting=None):
        """(ranked, waiting) as the user sees them. The first combo becomes the anchor without a vote,
        so until a second one is placed there is no ranking yet and it still counts as waiting.
        ``rated`` / ``waiting``: the raw counts, when the caller already has them."""
        rated = len(self.rated()) if rated is None else rated
        waiting = len(self.newcomers()) if waiting is None else waiting
        return (rated, waiting) if rated >= 2 else (0, waiting + rated)

    def top_ids(self):
        return core.top_tier_ids(self.combos, set(self.selection['candidate_ids']))

    def boundary_tie(self):
        return core.boundary_tie_pair(self.combos, set(self.selection['candidate_ids']), self.skipped_ties)

    def top_tie(self):
        return core.top_tie_pair(self.combos, set(self.selection['candidate_ids']), self.skipped_ties)

    # ------------------------------------------------------------------ views
    def _tiers(self):
        """(tier, provisional, grade, #n, child of the running batch) for every active combo, computed once.

        #n is the place in the whole ranking (core.rank_order): every page shows this same number.
        """
        rated = self.rated()
        elos = sorted(c['elo'] for c in rated)
        places = {c['id']: n for n, c in enumerate(core.rank_order(rated), 1)} if len(rated) >= 2 else {}
        children = set(self.selection['candidate_ids'])
        out = {}
        for combo in self.combos:
            child = combo['id'] in children
            if not core.is_rated(combo) or len(rated) < 2:
                out[combo['id']] = (None, False, None, None, child)
                continue
            rank = core.rank_among(combo['elo'], elos)
            out[combo['id']] = (core.tier_for_percentile(rank / len(elos)),
                                not core.tier_confirmed(combo['matches'], len(elos)),
                                core.tier_grade(rank / len(elos)), places[combo['id']], child)
        return out

    def combo_view(self, combo, tiers=None, role=None):
        tiers = tiers if tiers is not None else self._tiers()
        tier, provisional, grade, rank, child = tiers.get(combo['id'], (None, False, None, None, False))
        excluded = (combo.get('excluded') or {}).get('reason')
        image = combo.get('image_file')
        return {
            'id': combo['id'], 'style': combo['style'],
            'pairs': [{'w': w, 'tag': t} for w, t in core.parse_style_combo(combo['style'])],
            'anima': core.anima_copy(combo['style']),
            'elo': round(combo['elo']), 'tier': tier, 'grade': grade, 'provisional': provisional, 'rank': rank,
            # An active combo without a tier while rated is the lone first anchor: not ranked against anything yet.
            'rated': core.is_rated(combo) and (tier is not None or combo['id'] not in tiers), 'matches': combo['matches'], 'wins': combo['wins'],
            'generation': combo.get('generation', 1),
            'image': f'/img/{image}' if image else None, 'thumb': f'/thumb/{image}' if image else None,
            'excluded': excluded,
            'child': child, 'role': role,
            'kept': bool(combo.get('kept')), 'memo': combo.get('memo', ''),
            'seed': combo.get('seed'), 'final': bool(combo.get('final')), 'created': combo.get('created', 0),
        }

    def list_combos(self):
        with self.lock:
            tiers = self._tiers()
            active = [self.combo_view(c, tiers) for c in self.combos]
            excluded = [self.combo_view(c, tiers) for c in self.retired]
            return {'active': active, 'excluded': excluded}

    # ------------------------------------------------------------------ jobs
    def job_view(self):
        job = self.job
        if not job:
            return None
        return {k: job[k] for k in ('label', 'done', 'total', 'failures', 'running')}

    def _require_idle(self, action, kinds=None):
        """Refuse a change while images are being made (or only while a job of one of ``kinds`` runs)."""
        job = self.job
        if job and job['running'] and (kinds is None or job['kind'] in kinds):
            raise UserError(f'생성 작업이 끝난 뒤 {action} 주세요.')

    def _start_job(self, kind, label, total, work):
        # label: short enough for the sidebar's job card (135px) even at 99세대; the count shows there as done / total.
        self._require_idle('다시 시도해')
        self.stop_event.clear()
        self.job = {'kind': kind, 'label': label, 'done': 0, 'total': total, 'failures': 0,
                    'running': True, 'streak': 0, 'renders': 0}
        job = self.job

        def run():
            try:
                work(job)
            except Exception as exc:  # a crashed job must still end cleanly
                with self.lock:
                    job['failures'] += 1
                    self._event('error', f'{label} 중 오류가 났습니다: {exc}')
            finally:
                with self.lock:
                    job['running'] = False
                    self.generating_children = None if kind == 'evolution' else self.generating_children
                    if kind == 'evolution' and self._drop_empty_batch():
                        self._event('warn', '진화 조합을 하나도 만들지 못해 이번 세대 시작을 취소했습니다. ComfyUI 연결을 확인한 뒤 진화를 다시 시작해 주세요.')
                    self.save()
                    self._after_job(kind)

        threading.Thread(target=run, daemon=True).start()

    def _drop_empty_batch(self):
        """A generation that started but has no child at all (the job was cancelled, ComfyUI went away): back to before
        the start, otherwise the evolution page waits for children that will never come. True when it did. Lock held."""
        sel = self.selection
        if not sel['batch_id'] or sel['candidate_ids'] or (self.job and self.job['running']):
            return False
        sel.update(batch_id=None, parent_ids=[], parent_scores={})
        return True

    def stop_job(self):
        self.stop_event.set()

    def _render(self, job, settings, style, seed):
        """Generate one image outside the lock; returns the saved file name or None on failure (or a stop).

        The set delay goes between a job's images: never before its first one or after its last.
        """
        if job['renders']:
            self._pause(settings)
            if self.stop_event.is_set():
                return None
        job['renders'] += 1
        try:
            png = self._generate(settings, style, seed, self.stop_event,
                                 lambda text: self._event_locked('warn', text))
        except core.Stopped:
            return None
        except Exception as exc:
            with self.lock:
                job['failures'] += 1
                self._event('error', f'이미지를 만들지 못했습니다: {exc}')
                job['streak'] += 1
                if getattr(exc, 'fatal', False):
                    self._event('error', '같은 문제로 계속 실패할 것이라 작업을 멈췄습니다. 설정의 ComfyUI 연결과 모델을 확인해 주세요.')
                    self.stop_event.set()
                elif job['streak'] >= MAX_FAILURE_STREAK and not self.stop_event.is_set():
                    self._event('error', f'이미지가 {MAX_FAILURE_STREAK}번 연속 실패해 작업을 멈췄습니다. '
                                         '설정(프롬프트·모델·크기)이나 ComfyUI 상태를 확인해 주세요.')
                    self.stop_event.set()
            return None
        name = f'{_new_id()}.png'
        (self.img_dir / name).write_bytes(png)
        job['streak'] = 0
        return name

    def _draw_and_render(self, job, settings, count, draw, keep, seen):
        """The loop shared by random combos, evolution and refine variants: ``count`` images, each from
        ``draw()`` -> (style, info), drawn again (up to DRAW_TRIES) while that style was made before.
        ``keep(style, name, info)`` runs under the lock for every image made. Returns how many were made."""
        made = 0
        for _ in range(count):
            if self.stop_event.is_set():
                break
            for _ in range(DRAW_TRIES):
                style, info = draw()
                if style not in seen:
                    break
            else:
                with self.lock:
                    self._event('warn', '더 이상 새로운 조합을 만들 수 없어 만든 만큼으로 마칩니다.')
                break
            seen.add(style)
            name = self._render(job, settings, style, settings['seed'])
            with self.lock:
                job['done'] += 1
                if name:
                    made += 1
                    keep(style, name, info)
                    self.save()
        return made

    def _new_combo(self, style, name, settings, **fields):
        """A combo just drawn: random ones, evolution children and refine variants start from the same fields."""
        return {'id': _new_id(), 'style': style, 'elo': core.START_ELO, 'matches': 0, 'wins': 0, 'placed': False,
                'image_file': name, 'seed': settings['seed'], 'created': time.time(),
                'generation': self.selection['generation'], **fields}

    def _pause(self, settings):
        if settings['delay'] > 0:
            self.stop_event.wait(settings['delay'])

    def _after_job(self, kind):
        if kind == 'improve':
            self._improve_round_check()

    # ------------------------------------------------------------------ generation: random / free
    def start_random(self, count=None):
        with self.lock:
            s = self.rules()
            count = self._start_count('gen_count', count)
            tags = [a['tag'] for a in self.state['artists']]
            if len(tags) < s['gen_min']:
                raise UserError(f"작가를 최소 {s['gen_min']}명 이상 등록해 주세요.")
            settings = self._gen_settings()
            seen = {c['style'] for c in self.combos + self.retired}
            registry = self.lora_registry(s)
            self._require_loras_without_artists(s, registry)
            self.save()

        def draw():
            size = random.randint(s['gen_min'], min(s['gen_max'], len(tags)))
            loras = core.random_lora_pairs(registry, s['lora_min'], s['lora_max'])
            if not size and not loras and tags:
                size = 1  # never an empty combo (artists allowed to be 0, but then the LoRAs must be there)
            picked = random.sample(tags, size)
            weights = [core.clamp_weight(random.uniform(s['global_min_w'], s['global_max_w']),
                                         s['global_min_w'], s['global_max_w']) for _ in picked]
            return core.style_from_pairs(list(zip(weights, picked)) + loras), (set(picked), {tag for _, tag in loras})

        def keep(style, name, used):
            self.combos.append(self._new_combo(style, name, settings, generation=self.selection['generation'] - 1))
            self._count_use(*used)

        def work(job):
            made = self._draw_and_render(job, settings, count, draw, keep, seen)
            with self.lock:
                self._event('ok', f'새 조합 {made}개를 만들었습니다. 선별에서 자리를 찾아 주세요.')

        with self.lock:
            self._start_job('random', '새 조합 생성', count, work)

    MERGE_VARIANTS = 4

    def merge_combos(self, ids, count=None):
        """Two combos in one, several ways (one picture can't tell whether the mix works): every tag of both, a tag
        in both takes the mean of its weights (the 2nd and later variants nudge some by ±0.1); what does not fit
        the artist / LoRA limits of the settings is left out, shared tags first, the rest by chance. The pictures
        wait in state['merged'] (not in the list) until the user puts one in the list or deletes it."""
        if len(ids) != 2 or ids[0] == ids[1]:
            raise UserError('합칠 조합을 서로 다른 2개로 골라 주세요.')
        count = max(1, min(int(count or self.MERGE_VARIANTS), 12))
        with self.lock:
            found = {c['id']: c for c in self.combos + self.retired}
            if any(i not in found for i in ids):
                raise UserError('선택한 조합을 찾을 수 없습니다.')
            weights = {}
            for i in ids:
                for w, tag in core.parse_style_combo(found[i]['style']):
                    weights.setdefault(tag, []).append(w)
            cfg = self.rules()
            both = {t for t, ws in weights.items() if len(ws) == 2}
            settings = self._gen_settings()
            seen = {c['style'] for c in self.combos + self.retired} | {m['style'] for m in self.state['merged']}
            if not any((core.is_lora(t) and cfg['lora_max']) or (not core.is_lora(t) and cfg['gen_max']) for t in weights):
                raise UserError('설정의 작가·LoRA 개수 한도 때문에 합칠 태그가 남지 않습니다.')
            again = any(set(m.get('parents', [])) == set(ids) for m in self.state['merged'])  # a retry: the exact mean is taken
            self.save()
        made = []

        def draw():
            nudge = len(made) > 0 or again
            pairs = []
            for is_lora, cap in ((False, cfg['gen_max']), (True, cfg['lora_max'])):
                tags = [t for t in weights if core.is_lora(t) == is_lora]
                random.shuffle(tags)
                tags.sort(key=lambda t: t not in both)
                lo, hi = (cfg['lora_min_w'], cfg['lora_max_w']) if is_lora else (cfg['global_min_w'], cfg['global_max_w'])
                for t in tags[:cap]:
                    w = sum(weights[t]) / len(weights[t])
                    if nudge and random.random() < 0.5:
                        w += random.choice((-0.1, 0.1))
                    pairs.append((round(core.clamp_weight(w, lo, hi), 2), t))
            return core.style_from_pairs(pairs), ({p[1] for p in pairs if not core.is_lora(p[1])}, {p[1] for p in pairs if core.is_lora(p[1])})

        def keep(style, name, used):
            made.append(style)
            self.state['merged'].insert(0, {'key': _new_id(), 'style': style, 'image': name, 'parents': list(ids), 'source': 'merge',
                                            'seed': settings['seed'], 'created': time.time(),
                                            'used': [sorted(used[0]), sorted(used[1])]})

        def work(job):
            n = self._draw_and_render(job, settings, count, draw, keep, seen)
            with self.lock:
                self._event('ok', f'합친 그림 {n}장을 만들었습니다. 융합 탭에서 확인하세요.')

        with self.lock:
            self._start_job('merge', '조합 합치기', count, work)

    def merge_view(self):
        with self.lock:
            tiers = self._tiers()
            by_id = {c['id']: c for c in self.combos + self.retired}
            items = []
            listed = []
            for m in self.state['merged']:
                if m.get('listed'):
                    if m['listed'] in by_id:
                        listed.append((m.get('listed_at', 0), {**self.combo_view(by_id[m['listed']], tiers), 'source': m.get('source', 'merge'), 'made': m.get('created', 0)}))
                    continue
                items.append({'key': m['key'], 'source': m.get('source', 'merge'), 'style': m['style'], 'anima': core.anima_copy(m['style']),
                              'pairs': [{'w': w, 't': t} for w, t in core.parse_style_combo(m['style'])],
                              'image': f"/img/{m['image']}", 'thumb': f"/thumb/{m['image']}", 'created': m.get('created', 0),
                              'parents': [self.combo_view(by_id[i], tiers) for i in m.get('parents', []) if i in by_id]})
            running = bool(self.job and self.job['running'] and self.job['kind'] == 'merge')
            return {'items': items, 'listed': [c for _, c in sorted(listed, key=lambda x: -x[0])], 'running': running,
                    'progress': [self.job['done'], self.job['total']] if running else None}

    def merge_add(self, keys, keep=False):
        """Put merged pictures into the list of combos (they find their place in 선별); they leave 합친 그림."""
        with self.lock:
            keys = set(keys or [])
            chosen = [m for m in self.state['merged'] if m['key'] in keys]
            if not chosen:
                raise UserError('목록에 넣을 그림을 선택해 주세요.')
            for m in reversed(chosen):
                combo = self._new_combo(m['style'], m['image'], {'seed': m['seed']}, generation=self.selection['generation'] - 1)
                if keep:
                    combo['kept'] = True  # 보관함
                self.combos.append(combo)
                self._count_use(*[set(x) for x in m['used']])
                m['listed'] = combo['id']  # stays on 융합 as "목록에 넣은 그림"
                m['listed_at'] = time.time()
            self._event('ok', f'합친 조합 {len(chosen)}개를 목록에 넣었습니다. 선별에서 자리를 찾아 주세요.')
            self.save()
            return {'added': len(chosen)}

    def merge_refine(self, key):
        """A merged picture the user likes: into the list; the page then opens 다듬기 with it."""
        with self.lock:
            if not any(m['key'] == key for m in self.state['merged']):
                raise UserError('고른 그림을 찾을 수 없습니다.')
            self.merge_add([key])
            return {'id': self.combos[-1]['id']}

    def merge_delete(self, keys):
        with self.lock:
            keys = set(keys or [])
            gone = [m for m in self.state['merged'] if m['key'] in keys]
            self._delete_images(m['image'] for m in gone if not m.get('listed'))  # a listed one's picture belongs to its combo
            self.state['merged'] = [m for m in self.state['merged'] if m['key'] not in keys]
            self.save()
            return {'deleted': len(gone)}

    def _require_loras_without_artists(self, s, registry):
        """Artists set to 0 (only LoRAs are mixed): there must be LoRAs to mix."""
        if s['gen_max'] == 0 and not registry:
            raise UserError('작가를 끄면 LoRA만 섞습니다. 조합 화면에서 LoRA를 등록해 주세요.')

    def start_custom(self, text):
        """One combo exactly as typed (its artist: tags and weights), drawn and added like a random one.
        Artists it names that are not registered yet are registered too."""
        scan = self.scan_artists(text)
        if not scan['pairs'] and not scan['loras']:
            raise UserError('artist: 또는 lora: 태그를 하나 이상 넣어 주세요.')
        with self.lock:
            loras = []
            for p in scan['loras']:
                tag = self.resolve_lora(p['tag'])
                if not tag:
                    raise UserError(f"등록되지 않은 LoRA입니다: {p['tag']}. 조합의 LoRA 탭에서 먼저 등록해 주세요.")
                loras.append((p['w'], tag))
        style = core.style_from_pairs([(p['w'], p['tag']) for p in scan['pairs']] + loras)
        with self.lock:
            if any(c['style'] == style for c in self.combos + self.retired):
                raise UserError('이미 그림체 목록에 있는 조합입니다.')
            settings = self._gen_settings()
            self.save()

        def work(job):
            name = self._render(job, settings, style, settings['seed'])
            with self.lock:
                job['done'] = 1
                if not name:
                    return
                used = {p['tag'] for p in scan['pairs']}
                for tag in scan['new']:
                    self.state['artists'].append({'tag': tag, 'count': 0, 'arena_matches': 0, 'arena_wins': 0})
                self._count_use(used, {tag for _, tag in loras})
                self.combos.append(self._new_combo(style, name, settings, generation=self.selection['generation'] - 1))
                self.save()
                self._event('ok', '조합을 만들었습니다. 선별에서 자리를 찾아 주세요.')

        with self.lock:
            self._start_job('custom', '조합 생성', 1, work)

    def start_lora_check(self, tags):
        """Each chosen LoRA alone in one picture (not kept): when ComfyUI cannot attach its layers, _lora_report marks
        that LoRA (a clean picture clears the mark and notes the check). Costs one image per LoRA."""
        with self.lock:
            wanted = [l['tag'] for l in self.state['loras'] if l['tag'] in set(tags)]
            if not wanted:
                raise UserError('검사할 LoRA를 골라 주세요.')
            # The warning comes when ComfyUI attaches the LoRA, before any sampling: a tiny, 1-step picture is enough.
            settings = dict(self._gen_settings(), width=512, height=512, steps=1, delay=0)
            self.save()

        def work(job):
            for tag in wanted:
                if self.stop_event.is_set():
                    break
                with self.lock:
                    low, high = self._lora_range(next(l for l in self.state['loras'] if l['tag'] == tag), self.settings())
                weight = min(max(1.0, low), high)
                try:
                    if job['renders']:
                        self._pause(settings)
                    job['renders'] += 1
                    self._generate(settings, core.style_from_pairs([(weight, tag)]), settings['seed'], self.stop_event,
                                   lambda text: self._event_locked('warn', text))
                except core.Stopped:
                    break
                except Exception as exc:
                    with self.lock:
                        job['failures'] += 1
                        self._event('error', f'{core.lora_label(tag)} 검사 그림을 만들지 못했습니다: {exc}')
                with self.lock:
                    job['done'] += 1
            with self.lock:
                bad = [core.lora_label(l['tag']) for l in self.state['loras'] if l['tag'] in wanted and l.get('load_failed')]
                self._event('warn' if bad else 'ok', f"LoRA {len(wanted)}개 검사 끝. " + (f"적용 경고가 있는 LoRA {len(bad)}개: {', '.join(bad[:8])}{' …' if len(bad) > 8 else ''}. 상세 기록을 확인해 주세요." if bad else '수집된 기록에서 적용 오류가 발견되지 않았습니다. Text Encoder 미적용과 로그 범위는 조합의 LoRA 적용 기록에서 확인할 수 있습니다.'))

        with self.lock:
            self._start_job('lora_check', 'LoRA 호환성 검사', len(wanted), work)

    LORA_ANGLE_RE = re.compile(r'<lora:([^:>]+):(-?[0-9.]+)>', re.I)

    def _expand_lora_syntax(self, text):
        """Anima's ``<lora:name:0.7>`` (the file name without folder and extension) into the app's own
        ``0.7::lora:folder/name.safetensors ::``, so a prompt copied from a combo works as typed."""
        def swap(m):
            want = m.group(1).strip().lower()
            for lora in self.state['loras']:
                stem = re.sub(r'\.(safetensors|ckpt|pt)$', '', lora['tag'][len(core.LORA_PREFIX):].replace('\\', '/').rsplit('/', 1)[-1], flags=re.I)
                if stem.lower() == want:
                    return f"{float(m.group(2)):g}::{lora['tag']} ::"
            raise UserError(f"등록되지 않은 LoRA입니다: {m.group(1)}. 조합의 LoRA 탭에서 먼저 등록해 주세요.")
        text = self.LORA_ANGLE_RE.sub(swap, text or '')
        return re.sub(r'(?:,\s*)+(?=,|$)', '', text).strip(' ,')

    def start_free(self, prompt, base=None, negative=None, seed=None):
        """One picture from the text typed. ``base`` / ``negative`` replace the settings' prompts for this picture only
        (the base needs {artist}); ``seed`` replaces the fixed seed (a combo's own seed, to compare with its picture)."""
        with self.lock:
            typed, prompt = prompt, self._expand_lora_syntax(prompt)  # the picture keeps the text as typed
            settings = self._gen_settings()
            if base and base.strip():
                settings['base_prompt'] = base.strip()
            if negative is not None and str(negative).strip():
                settings['negative'] = str(negative).strip()
            if seed not in (None, ''):
                try:
                    settings['seed'] = int(seed)
                except (TypeError, ValueError):
                    raise UserError('시드는 숫자로 넣어 주세요.')
            self.save()

        def work(job):
            name = self._render(job, settings, prompt.strip(), settings['seed'])
            with self.lock:
                job['done'] = 1
                if name:
                    self.state['free_results'].insert(0, {'image': name, 'prompt': typed, 'time': _now(),
                                                          'seed': settings['seed']})
                    self._event('ok', '자유 생성 이미지를 만들었습니다.')

        with self.lock:
            self._start_job('free', '자유 생성', 1, work)

    def free_delete(self, images):
        """Remove 자유 생성 pictures. One that became a combo keeps its file (the combo owns it); only the record goes."""
        with self.lock:
            names = set(images or [])
            gone = [r for r in self.state['free_results'] if r['image'] in names]
            if not gone:
                raise UserError('지울 그림을 선택해 주세요.')
            used = {c.get('image_file') for c in self.combos + self.retired}
            used |= {m.get('image') for m in self.state.get('merged', [])}
            self._delete_images(r['image'] for r in gone if r['image'] not in used)  # before the records: a refusal keeps them
            self.state['free_results'] = [r for r in self.state['free_results'] if r['image'] not in names]
            self.save()
            return {'deleted': len(gone)}

    def free_adopt(self, image, keep=False, refine=False):
        """A 자유 생성 picture the user likes becomes a combo of the list as drawn (no new image); optionally into the
        보관함, or straight into 다듬기. Artists it names that are not registered yet are registered too."""
        scan_text = None
        with self.lock:
            result = next((r for r in self.state['free_results'] if r['image'] == image), None)
            if not result:
                raise UserError('그림을 찾을 수 없습니다.')
            if result.get('listed') and any(c['id'] == result['listed'] for c in self.combos):
                raise UserError('이미 목록에 넣은 그림입니다.')
            scan_text = self._expand_lora_syntax(result.get('prompt', ''))
        scan = self.scan_artists(scan_text)
        if not scan['pairs'] and not scan['loras']:
            raise UserError('작가·LoRA 태그가 없는 프롬프트라 조합으로 넣을 수 없습니다.')
        with self.lock:
            loras = []
            for p in scan['loras']:
                tag = self.resolve_lora(p['tag'])
                if not tag:
                    raise UserError(f"등록되지 않은 LoRA입니다: {p['tag']}. 조합의 LoRA 탭에서 먼저 등록해 주세요.")
                loras.append((p['w'], tag))
            style = core.style_from_pairs([(p['w'], p['tag']) for p in scan['pairs']] + loras)
            if any(c['style'] == style for c in self.combos + self.retired):
                raise UserError('이미 그림체 목록에 있는 조합입니다.')
            for tag in scan['new']:
                self.state['artists'].append({'tag': tag, 'count': 0, 'arena_matches': 0, 'arena_wins': 0})
            self._count_use({p['tag'] for p in scan['pairs']}, {tag for _, tag in loras})
            combo = self._new_combo(style, image, {'seed': result.get('seed')}, generation=self.selection['generation'] - 1)
            if keep:
                combo['kept'] = True
            self.combos.append(combo)
            result['listed'] = combo['id']
            self._event('ok', '자유 생성 그림을 목록에 넣었습니다. 선별에서 자리를 찾아 주세요.')
            self.save()
        return {'id': combo['id']}

    # ------------------------------------------------------------------ artists
    def list_artists(self):
        with self.lock:
            scores = core.artist_scores(self.combos + self.retired)
            return [{**a, 'winrate': a['arena_wins'] / a['arena_matches'] if a['arena_matches'] else 0,
                     'score': scores.get(a['tag'], (0, 0))[0], 'combos': scores.get(a['tag'], (0, 0))[1]}
                    for a in self.state['artists']]

    def add_artists(self, text):
        with self.lock:
            existing = {a['tag'] for a in self.state['artists']}
            added = 0
            # With any artist: tag it is a prompt (pasted, or from a dropped picture): those tags only. Without, a
            # list of bare names: every comma/line-separated entry.
            names = core.artists_in_prompt(text) if ('artist:' in text or '@' in text) else core.extract_artist_names(text)
            for name in names:
                tag = core.sanitize_tag(name)
                if tag and tag not in existing:
                    self.state['artists'].append({'tag': tag, 'count': 0, 'arena_matches': 0,
                                                  'arena_wins': 0})
                    existing.add(tag)
                    added += 1
            self._artists_checked()
            self.save()
            return added

    def scan_artists(self, text):
        """The artists a prompt names with their weights, as the combos' pairs (tags as add_artists would
        register them, each once), and which are not registered yet."""
        weights = {}
        for w, raw in core.artist_weights_in_prompt(text):
            tag = core.sanitize_tag(raw)
            if tag:
                weights.setdefault(tag, w)
        with self.lock:
            existing = {a['tag'] for a in self.state['artists']}
        # LoRAs typed in the text ("0.7::lora:name ::"): a custom combo takes them along; they are not artists to register.
        loras = [{'w': w, 'tag': core.LORA_PREFIX + name} for name, w in core.lora_weights_in_prompt(text)]
        for m in self.LORA_ANGLE_RE.finditer(text):  # ComfyUI-style <lora:name:0.7> as well
            try:
                loras.append({'w': float(m.group(2) or 1), 'tag': core.LORA_PREFIX + m.group(1).strip()})
            except (TypeError, ValueError, IndexError):
                pass
        seen_l, uniq = set(), []
        for l in loras:
            if l['tag'] not in seen_l:
                seen_l.add(l['tag'])
                uniq.append({**l, 'registered': bool(self.resolve_lora(l['tag']))})
        loras = uniq
        return {'pairs': [{'w': w, 'tag': t} for t, w in weights.items()], 'new': [t for t in weights if t not in existing],
                'loras': loras}

    # ------------------------------------------------------------------ LoRAs
    def _lora_range(self, lora, s):
        low, high = lora.get('min_w'), lora.get('max_w')
        low = s['lora_min_w'] if low is None else low
        high = s['lora_max_w'] if high is None else high
        return (low, max(low, high))

    def lora_registry(self, s=None):
        """{lora tag: (lowest, highest weight)} of the registered LoRAs: their own range, else the settings'."""
        s = s or self.settings()
        return {lora['tag']: self._lora_range(lora, s) for lora in self.state['loras']}

    def resolve_lora(self, raw):
        """The registered tag a typed LoRA name means: the exact file name, else the one whose name (without folder
        and extension) is that, ignoring case. None when it is not registered or the short name is ambiguous."""
        raw = raw[len(core.LORA_PREFIX):] if raw.startswith(core.LORA_PREFIX) else raw
        tags = [lora['tag'] for lora in self.state['loras']]
        exact = [tag for tag in tags if core.lora_name(tag) == raw]
        if exact:
            return exact[0]
        short = [tag for tag in tags if core.lora_label(tag).lower() == core.lora_label(raw).lower()]
        return short[0] if len(short) == 1 else None

    def _count_use(self, artists, loras):
        """A new combo used these artist / LoRA tags."""
        for artist in self.state['artists']:
            if artist['tag'] in artists:
                artist['count'] += 1
        for lora in self.state['loras']:
            if lora['tag'] in loras:
                lora['count'] += 1

    def reset_usage(self):
        """Every artist's and LoRA's use count back to 0 (scores and combos stay)."""
        with self.lock:
            for item in self.state['artists'] + self.state['loras']:
                item['count'] = 0
            self.save()

    def list_loras(self):
        conn = self.connection
        if conn and not conn.get('error') and time.time() - conn.get('at', 0) > 30 and not getattr(self, '_refreshing', False):
            self._refreshing = True  # a file that left ComfyUI drops out on a later look, without waiting for the settings page

            def again():
                try:
                    self.check_connection()
                finally:
                    self._refreshing = False
            threading.Thread(target=again, daemon=True).start()
        with self.lock:
            s = self.settings()
            scores = core.artist_scores(self.combos + self.retired)  # LoRAs are fitted along with the artists
            available = ((self.connection or {}).get('data') or {}).get('lora_names')
            out = []
            for lora in self.state['loras']:
                low, high = self._lora_range(lora, s)
                score, combos = scores.get(lora['tag'], (0, 0))
                out.append({**lora, 'name': core.lora_name(lora['tag']), 'label': core.lora_label(lora['tag']),
                            'min': low, 'max': high, 'own_range': lora.get('min_w') is not None or lora.get('max_w') is not None,
                            'trigger': lora.get('trigger', ''), 'candidates': lora.get('candidates', []),
                            'base': lora.get('base', ''), 'incompatible': bool(lora.get('incompatible')),
                            'load_failed': lora.get('load_failed'),
                            'winrate': lora['arena_wins'] / lora['arena_matches'] if lora['arena_matches'] else 0,
                            'score': score, 'combos': combos,
                            # known only while ComfyUI answered with its list: a file it no longer has makes pictures fail
                            'missing': bool(available) and core.lora_name(lora['tag']) not in available})
            return out

    def lora_loading_notice(self):
        """최근 조합의 적용 안내를 반환하며 특정 파일의 실패로 단정하지 않습니다."""
        with self.lock:
            return copy.deepcopy(self.state.get('lora_loading_notice'))

    def _lora_report(self, names, style, seed, report):
        """의도적인 TE 미적용은 상세 기록으로, 실제 적용 문제는 중복 없는 경고로 남깁니다."""
        tags = list(dict.fromkeys(core.LORA_PREFIX + name for name in names))
        with self.lock:
            single = next((lora for lora in self.state['loras'] if lora['tag'] == tags[0]), None) if len(tags) == 1 else None
            settings = self.settings()
            components = report['components']
            warning_components = []
            for component_name in ('model', 'text_encoder', 'unknown'):
                if component_name == 'text_encoder' and not settings['lora_clip']:
                    continue
                if components[component_name]['count']:
                    warning_components.append(component_name)
            if report['patch_error_count']:
                warning_components.append('patch')
            notice = {
                'time': _now(), 'names': names, 'model_only': not settings['lora_clip'],
                'counts': {component_name: details['count'] for component_name, details in components.items()},
                'patch_errors': report['patch_errors'], 'patch_error_count': report['patch_error_count'],
                'capped': report['capped'], 'has_warning': bool(warning_components),
            }
            self.state['lora_loading_notice'] = notice
            if single:
                single['load_notice'] = notice
                if warning_components:
                    warning_samples = []
                    warning_key_count = 0
                    for component_name in warning_components:
                        if component_name != 'patch':
                            warning_samples.extend(components[component_name]['keys'])
                            warning_key_count += components[component_name]['count']
                    single['load_failed'] = {
                        'time': notice['time'], 'keys': warning_key_count, 'sample': warning_samples[:3],
                        'capped': report['capped'], 'components': warning_components,
                        'patch_errors': report['patch_errors'][:3],
                    }
                elif not report['capped']:
                    single.pop('load_failed', None)
                    single['checked'] = notice['time']
            if not report['count'] and not report['patch_error_count'] and not report['capped']:
                self.save()
                return
            if warning_components:
                # 여러 LoRA를 쓴 결과는 원인 파일을 특정하지 않고 문제 종류로 중복을 막습니다.
                warning_identity = (tags[0] if len(tags) == 1 else 'mixed', tuple(warning_components))
                if warning_identity not in self._warned_lora_problems:
                    self._warned_lora_problems.add(warning_identity)
                    component_labels = {'model': '모델 Key', 'text_encoder': 'Text Encoder Key', 'unknown': '미확인 Key', 'patch': 'Patch 오류'}
                    problem_text = ', '.join(component_labels[component] for component in warning_components)
                    affected_name = core.lora_label(tags[0]) if len(tags) == 1 else '현재 LoRA 조합'
                    self._event('warn', f'{affected_name}: {problem_text} 적용 문제가 발견되었습니다. 일부 가중치가 적용되지 않았을 수 있습니다. 자세한 기록: data/lora_warnings.log')
            lines = [f"[{notice['time']}] LoRA 적용 {'경고' if warning_components else '안내'} — 시드 {seed}",
                     f"  LoRA: {', '.join(core.lora_name(tag) for tag in tags)}"
                     + ('' if single else '  (여러 개라 어느 쪽 문제인지는 알 수 없음)'),
                     f"  조합: {style}",
                     f"  모델: diffusion={settings['unet_name'] or '-'} / 텍스트 인코더={settings['clip_name'] or '-'}"
                     + (' / workflow.json 사용' if self.workflow_file.exists() else ''),
                     f"  적용 대상: {'모델 + 텍스트 인코더' if settings['lora_clip'] else '모델만'}",
                     f"  미적용 Tensor Key: {report['count']}개 (Layer 수가 아닙니다)",
                     f"  분류: 모델 {components['model']['count']} / Text Encoder {components['text_encoder']['count']} / 미확인 {components['unknown']['count']}",
                     f"  Patch 오류: {report['patch_error_count']}개",
                     '  로그 범위: ' + ('일부 기록만 확인됨. 전체 적용 성공 여부는 단정할 수 없습니다.' if report['capped'] else '생성 중 수집된 기록'),
                     '  키 이름 유형 (숫자는 N):']
            if components['text_encoder']['count'] and not settings['lora_clip']:
                lines.insert(-1, '  Text Encoder: 모델만 적용하는 설정에 따른 미사용 Key이며 반복 Toast를 표시하지 않습니다.')
            lines += [f'    {count:>4} × {pattern}' for pattern, count in report['groups']]
            lines += ['  원본 키 예시:'] + [f'    {key}' for key in report['keys']]
            lines += ['  Patch 오류 예시:'] + [f'    {message}' for message in report['patch_errors']] + ['']
            try:
                with open(self.data_dir / 'lora_warnings.log', 'a', encoding='utf-8') as fh:
                    fh.write('\n'.join(lines) + '\n')
            except OSError:
                pass
            self.save()

    @staticmethod
    def _unread(names, infos):
        """[[label, why]] for the files nothing useful could be read from: ComfyUI could not give the metadata, or it has
        no trigger / tag information in it."""
        out = []
        for name in names:
            info = infos.get(name) or {}
            if not info.get('trigger') and not info.get('candidates'):  # the reasons are in data/lora_meta.log
                out.append([core.lora_label(name), '트리거 정보 없음'])
        return out

    def _meta_report(self, names, infos):
        """data/lora_meta.log: for every file that gave no trigger, the metadata key names it does have, so it can be
        seen what a trainer wrote (and what could be read from it)."""
        lines = []
        for name in names:
            info = infos.get(name) or {}
            if info.get('trigger') or info.get('candidates'):
                continue
            lines.append(f"[{_now()}] {name}: " + (info['error'] if info.get('error') else f"읽을 수 있는 트리거 정보 없음 / 메타데이터 키: {', '.join(info.get('keys') or []) or '(없음)'}"))
        if lines:
            try:
                with open(self.data_dir / 'lora_meta.log', 'a', encoding='utf-8') as fh:
                    fh.write('\n'.join(lines) + '\n')
            except OSError:
                pass

    def _read_infos(self, names):
        """{file name: core.lora_info} asked of ComfyUI (outside the lock: it is a network call per file)."""
        url = self.settings()['comfy_url']
        out = {}
        for name in names:
            meta = dict(self._lora_meta(url, name) or {})
            words, note = self._lora_words(url, name)
            if words:
                meta['__manager__'] = words
            elif note:
                meta['__manager_note__'] = note
            out[name] = core.lora_info(meta)
        return out

    def add_loras(self, names):
        """Register LoRAs by their file names in ComfyUI. Returns {'added', 'skipped' (names that cannot be used),
        'triggers' (how many came with a trigger phrase), 'incompatible' (the ones trained for SD1.5 / SDXL)}."""
        wanted, skipped = [], []
        for raw in names if isinstance(names, list) else []:
            name = str(raw).strip()
            name = name[len(core.LORA_PREFIX):].strip() if name.startswith(core.LORA_PREFIX) else name
            if not name or ',' in name or '::' in name or '\n' in name:
                skipped.append(str(raw))  # a comma or "::" in the file name would break the style string
            elif name not in wanted:
                wanted.append(name)
        with self.lock:
            existing = {lora['tag'] for lora in self.state['loras']}
        fresh = [n for n in wanted if core.LORA_PREFIX + n not in existing]
        infos = self._read_infos(fresh)
        with self.lock:
            added, triggers, bad = 0, 0, []
            self._meta_report(fresh, infos)
            for name in fresh:
                tag, info = core.LORA_PREFIX + name, infos[name]
                if any(l['tag'] == tag for l in self.state['loras']):
                    continue
                self.state['loras'].append({'tag': tag, 'min_w': None, 'max_w': None, 'trigger': info['trigger'], 'count': 0,
                                            'arena_matches': 0, 'arena_wins': 0, 'candidates': info['candidates'],
                                            'base': info['base'], 'incompatible': info['incompatible']})
                added += 1
                triggers += bool(info['trigger'])
                if info['incompatible']:
                    bad.append(core.lora_label(tag))
            self.save()
            return {'added': added, 'skipped': skipped, 'triggers': triggers, 'incompatible': bad,
                    'unread': self._unread(fresh, infos)}

    def read_loras(self, tags):
        """Read the files' metadata again: the trigger suggestions and the base model. A trigger phrase the file names
        is filled in where the trigger is still empty; one already typed is never replaced."""
        with self.lock:
            names = [core.lora_name(l['tag']) for l in self.state['loras'] if l['tag'] in set(tags)]
        infos = self._read_infos(names)
        with self.lock:
            filled = found = 0
            for lora in self.state['loras']:
                info = infos.get(core.lora_name(lora['tag']))
                if not info:
                    continue
                lora.update(candidates=info['candidates'], base=info['base'], incompatible=info['incompatible'])
                found += bool(info['candidates'] or info['trigger'] or info['base'])
                if info['trigger'] and not lora.get('trigger'):
                    lora['trigger'] = info['trigger']
                    filled += 1
            self._meta_report(names, infos)
            self.save()
            return {'read': len(names), 'found': found, 'filled': filled, 'unread': self._unread(names, infos)}

    def update_lora(self, tag, min_w, max_w, trigger):
        """A LoRA's own weight range (None: follow the settings') and trigger words."""
        with self.lock:
            lora = next((l for l in self.state['loras'] if l['tag'] == tag), None)
            if not lora:
                raise UserError('등록된 LoRA를 찾을 수 없습니다.')
            values = []
            for value in (min_w, max_w):
                if value in (None, ''):
                    values.append(None)
                    continue
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    raise UserError('가중치가 올바르지 않습니다.')
                if not 0 <= value <= 3:  # also refuses NaN
                    raise UserError('LoRA 가중치는 0 ~ 3 사이로 입력해 주세요.')
                values.append(round(value, 1))
            if None not in values and values[1] < values[0]:
                raise UserError('가중치 범위를 확인해 주세요 (최소 ≤ 최대).')
            lora['min_w'], lora['max_w'] = values
            lora['trigger'] = str(trigger or '').strip()
            self.save()

    def delete_loras(self, tags, with_combos=False):
        """Take LoRAs off the list. ``with_combos``: also delete every combo that has one of them (refused while a
        generation or an evolution batch is running, like any delete). Returns {'combos': how many were deleted}."""
        with self.lock:
            tags = set(tags)
            deleted = 0
            if with_combos:
                ids = [c['id'] for c in self.combos + self.retired if tags & set(core.lora_tags_from_style(c['style']))]
                if ids:
                    deleted = self.delete_combos(ids)['deleted']  # first: a refusal leaves the LoRAs listed
            self.state['loras'] = [l for l in self.state['loras'] if l['tag'] not in tags]
            self.save()
            return {'combos': deleted}

    def rename_artist(self, old, new):
        with self.lock:
            new = core.sanitize_tag(new or '')
            if not new or new == old:
                return
            if any(a['tag'] == new for a in self.state['artists']):
                raise UserError('이미 있는 작가 이름입니다.')
            self._require_idle('이름을 바꿔')  # a running job still draws with the old name
            for artist in self.state['artists']:
                if artist['tag'] == old:
                    artist['tag'] = new
            improving = list(((self.state.get('improve') or {}).get('items') or {}).values())
            for combo in self.combos + self.retired + improving:
                combo['style'] = core.rename_artist_in_style(combo['style'], old, new)
            self._artists_checked()
            self.save()

    def _artists_checked(self):
        """Editing the artist list is checking it (the setup step starts from the default list)."""
        self.state['ui_state']['artists_checked'] = True

    def delete_artists(self, tags):
        with self.lock:
            tags = set(tags)
            self.state['artists'] = [a for a in self.state['artists'] if a['tag'] not in tags]
            self._artists_checked()
            self.save()

    # ------------------------------------------------------------------ arena: choosing the next match
    def match(self, last=None):
        """The current match (kept until voted/skipped), choosing a new one if needed.
        ``last``: the match just judged, handed back as it is now (blind mode reveals it)."""
        with self.lock:
            desired = self._priority_pair()
            if desired:
                kind, a_id, b_id, meta = desired
                if not (self.current and self.current['kind'] == kind
                        and {self.current['a'], self.current['b']} == {a_id, b_id}):
                    if (hash(frozenset((a_id, b_id))) & 1):  # stable, unbiased side
                        a_id, b_id = b_id, a_id
                    self.current = {'kind': kind, 'a': a_id, 'b': b_id, 'meta': meta}
                else:
                    self.current['meta'] = meta
            elif not (self.current and self.current['kind'] in ('league', 'top')
                      and self.find(self.current['a']) and self.find(self.current['b'])):
                self.current = self._league_pair()
            return self._match_view(last)

    def _priority_pair(self):
        mode = self.settings()['arena_mode']
        # A refine the user started comes before everything else, in any mode: its variants are what they came here to
        # judge, and the refine page sends them to this screen.
        pair = self._tune_pair() or self._improve_pair()
        if pair:
            return pair
        if mode == 'auto':
            # New combos first: tie-breaking among the rated ones can wait (evolution asks for it itself), otherwise the
            # many equal Elos that placing makes keep the same rated pictures fighting while newcomers queue up.
            pair = self._fresh_pair() or self._placement_pair()
            if pair:
                return pair
        tie = self.boundary_tie()
        if tie:
            return 'tie', tie[0], tie[1], {}
        if mode != 'auto':
            return None
        for chooser in (self._placement_pair, self._selection_pair, self._improve_pair):
            pair = chooser()
            if pair:
                return pair
        # Equal Elos inside the top 30% hold nothing up any more (placing makes many equal ones; asking for each pair
        # never ended): the ordinary matches below sort them out along the way.
        return None

    def _fresh_pair(self):
        """While the ladder is short, two newcomers fight each other (both become rated by that one vote). Placing
        against a handful of rated pictures shows those same few again and again; this way every match is two new ones.
        Stable until voted; a placement already under way is finished first."""
        if self.state.get('placement'):
            return None
        cur = self.current
        if cur and cur['kind'] == 'league' and (cur.get('meta') or {}).get('fresh'):
            a, b = self.find(cur['a']), self.find(cur['b'])
            if a and b and not core.is_rated(a) and not core.is_rated(b):
                return 'league', a['id'], b['id'], {'fresh': True}
        if len(self.rated()) >= FRESH_LADDER:
            return None
        queue = self.newcomers()
        if len(queue) < 2:
            return None
        a, b = random.sample(queue, 2)
        return 'league', a['id'], b['id'], {'fresh': True}

    def _league_pair(self):
        mode = self.settings()['arena_mode']
        children = set(self.selection['candidate_ids'])
        pool = [c for c in self.combos if core.is_rated(c) and c['id'] not in children]
        if mode == 'top':
            top = set(self.top_ids())
            leaders = [c for c in pool if c['id'] in top]
            pool = leaders if len(leaders) >= 2 else sorted(pool, key=lambda c: -c['elo'])[:2]
        if len(pool) < 2:
            return None
        weights = self._match_weights(pool, pool)
        last = self._last_pair
        for _ in range(10):
            a = random.choices(pool, weights=weights)[0]
            rest = [c for c in pool if c['id'] != a['id']]
            b = random.choices(rest, weights=self._match_weights(rest, pool))[0]
            if {a['id'], b['id']} != set(last or ()) or len(pool) == 2:
                break
        return {'kind': 'top' if mode == 'top' else 'league', 'a': a['id'], 'b': b['id'], 'meta': {}}

    @staticmethod
    def _match_weights(combos, pool):
        rated = sorted(c['elo'] for c in pool if core.is_rated(c))

        def weight(combo):
            m = combo['matches']
            value = 1.0 / (m + 1)
            if m >= 1 and len(rated) >= 2 and core.tier_confirmed(m, len(rated)):
                rank = core.rank_among(combo['elo'], rated)
                value *= core.TIER_MATCH_MULTIPLIER.get(core.tier_for_percentile(rank / len(rated)), 1.0)
            return value
        return [weight(c) for c in combos]

    def _match_view(self, last=None):
        cur = self.current
        base = {'stage': self.stage(), 'mode': self.settings()['arena_mode'], 'undo': bool(self.undo_stack)}
        tiers = self._tiers() if cur or last else None
        if last:
            base['last'] = {side: self.combo_view(combo, tiers) for side in ('a', 'b') if (combo := self.find_any(last[side]))}
        if not cur:
            return {**base, 'kind': None, 'message': self._idle_message()}
        roles = self._roles(cur)
        a, b = self.find_any(cur['a']), self.find_any(cur['b'])
        if not a or not b:
            self.current = None
            return {**base, 'kind': None, 'message': self._idle_message()}
        return {**base, 'kind': cur['kind'], 'context': self._context(cur),
                'a': self.combo_view(a, tiers, roles.get(a['id'])),
                'b': self.combo_view(b, tiers, roles.get(b['id']))}

    def _roles(self, cur):
        kind = cur['kind']
        # A newcomer being placed and an evolution child look alike (평가중 in the tier chip): neither gets a role.
        if kind == 'improve':
            imp = self.state['improve']
            final = self._final_of(cur)
            if final:
                return {final['champion_id']: '챔피언', final['base_id']: '원본'}
            return {imp['champion_id']: '챔피언', **{k: '변형' for k in imp['pending']}}
        return {}

    def _context(self, cur):
        kind = cur['kind']
        if kind == 'tie' and cur['meta'].get('inner'):
            return {'title': '상위 30% 동점', 'detail': '상위권에서 점수가 같은 두 조합입니다. 순위를 가리도록 더 마음에 드는 쪽을 골라 주세요.'}
        if kind == 'tie':
            return {'title': '상위 30% 경계 동점', 'detail': '상위 30%에 들 마지막 자리를 두고 점수가 같습니다. 더 마음에 드는 쪽을 골라 주세요.'}
        if kind == 'place':
            left = len(self.newcomers())
            p = self.state['placement']
            done = sum(1 for v in self._placement_votes(p))
            return {'title': '새 조합 자리 찾기', 'detail': f'기존 순위표 사이에서 위치를 찾는 중 · {done + 1}번째 비교 · 남은 새 조합 {left}개'}
        if kind == 'select':
            low, high = core.selection_remaining_matches(self.selection, self.combos, self.state['history'])
            remain = f'{low}' if low == high else f'{low}~{high}'
            return {'title': f"{self.selection['generation']}세대 진화 조합 평가",
                    'detail': f'새 조합이 상위 30% 사이 어디쯤인지 찾는 중 · 남은 선별 약 {remain}회'}
        if kind == 'tune':
            tune = self.state['tune']
            return {'title': '다듬기 · 가중치 선별', 'detail': f"같은 그림체에서 가중치만 다른 변형입니다 · 남은 선별 약 {math.ceil(self._tune_remaining(tune))}회 · 더 마음에 드는 쪽을 고르세요"}
        if kind == 'improve':
            imp = self.state['improve']
            final = self._final_of(cur)
            if final:
                left = sum(1 for f in imp['finals'] if f.get('winner') is None)
                return {'title': '다듬기 최종 확인', 'detail': f"다른 시드 {final['seed']} · 챔피언 vs 원본 · 남은 선별 {left}개 · 이기는 쪽이 많은 그림체가 최종으로 정해집니다"}
            return {'title': f"다듬기 {imp['round']}라운드", 'detail': f"챔피언 vs 가중치 변형 · 조정 폭 ±{imp['jitter']:.1f} · 남은 변형 {len(imp['pending'])}개"}
        if kind == 'top':
            return {'title': '상위 30% 리그', 'detail': '상위권끼리 순위를 다듬습니다.'}
        return {'title': '순위 결정', 'detail': '할 일이 없을 때는 일반 선별로 순위를 더 정확하게 만듭니다.'}

    def _idle_message(self):
        if self.generating_children:
            made, total = self.generating_children
            return f'진화 조합을 만드는 중입니다 ({made}/{total}). 하나가 완성되면 바로 선별이 이어집니다.'
        if self.job and self.job['running']:
            return f"{self.job['label']} 중입니다. 완성되면 바로 선별이 이어집니다."
        if len(self.rated()) < 2 and not self.newcomers():
            return '선별할 조합이 없습니다. 먼저 새 조합을 만들어 주세요.'
        return '지금은 할 선별이 없습니다.'

    # ------------------------------------------------------------------ arena: voting
    def vote(self, side):
        with self.lock:
            cur = self.current
            if not cur or side not in ('a', 'b'):
                raise UserError('지금 투표할 선별이 없습니다.')
            winner, loser = (cur['a'], cur['b']) if side == 'a' else (cur['b'], cur['a'])
            handler = {'tie': self._vote_regular, 'league': self._vote_regular, 'top': self._vote_regular,
                       'place': self._vote_place, 'select': self._vote_select, 'improve': self._vote_improve,
                       'tune': self._vote_tune}
            before = self.undo_stack[-1] if self.undo_stack else None
            handler[cur['kind']](cur, winner, loser)
            self._remember_match(cur, before)
            self._last_pair = (cur['a'], cur['b'])
            self.current = None
            self._maybe_finish_final()
            self.save()
            return self.match(last=cur)

    def skip(self):
        with self.lock:
            cur = self.current
            if not cur:
                return self.match()
            kind = cur['kind']
            entry = None
            before = self.undo_stack[-1] if self.undo_stack else None
            if kind == 'tie':
                elo = self.find(cur['a'])['elo']
                self.skipped_ties.add((frozenset((cur['a'], cur['b'])), elo))
                self.undo_stack.append({'kind': 'tie_skip', 'key': (frozenset((cur['a'], cur['b'])), elo)})
            elif kind == 'place':
                self._record_place(cur, None)
            elif kind == 'select':
                entry = {'type': 'selection_skip', 'batch_id': self.selection['batch_id'],
                         'pair': {'a': cur['a'], 'b': cur['b']}}
            elif kind == 'tune':
                self._vote_tune(cur, None, None, tie=True)
            elif kind == 'improve':
                final = self._final_of(cur)
                if final:
                    self._final_vote(cur, final, 'tie')
                else:
                    self._improve_step(None)  # "similar": shown again at the end of the round, then the champion keeps it
            else:  # league / top: nothing to change, but the user may change their mind: an undo step all the same
                self.undo_stack.append({'kind': 'skip'})
            if entry:
                self.state['history'].insert(0, entry)
                self.undo_stack.append({'kind': 'history', 'entry': entry,
                                        'placement': copy.deepcopy(self.state['placement'])})
                core.apply_selection_ratings(self.combos, self.selection, self.state['history'])
            self._remember_match(cur, before)
            self._last_pair = (cur['a'], cur['b'])
            self.current = None
            self._maybe_finish_final()
            self.save()
            return self.match(last=cur)

    def _remember_match(self, cur, before):
        """The undo step this vote just added keeps the match itself, sides included, so undo shows it again."""
        if self.undo_stack and self.undo_stack[-1] is not before:
            self.undo_stack[-1]['match'] = copy.deepcopy(cur)

    def _vote_regular(self, cur, winner_id, loser_id):
        a, b = self.find(cur['a']), self.find(cur['b'])
        a_won = winner_id == a['id']
        tags_a, tags_b = set(core.artists_from_style(a['style'])), set(core.artists_from_style(b['style']))
        loras_a, loras_b = set(core.lora_tags_from_style(a['style'])), set(core.lora_tags_from_style(b['style']))
        snap = {'kind': 'regular',
                'combos': {c['id']: {k: c[k] for k in ('elo', 'matches', 'wins')} for c in (a, b)},
                'artists': {x['tag']: {k: x[k] for k in ('arena_matches', 'arena_wins')}
                            for x in self.state['artists'] if x['tag'] in tags_a | tags_b},
                'loras': {x['tag']: {k: x[k] for k in ('arena_matches', 'arena_wins')}
                          for x in self.state['loras'] if x['tag'] in loras_a | loras_b}}
        a['elo'], b['elo'] = core.calc_elo(a['elo'], b['elo'], a_won)
        a['matches'] += 1
        b['matches'] += 1
        (a if a_won else b)['wins'] += 1
        for artist in self.state['artists']:
            in_a, in_b = artist['tag'] in tags_a, artist['tag'] in tags_b
            if in_a != in_b:
                artist['arena_matches'] += 1
                won = a_won if in_a else not a_won
                artist['arena_wins'] += 1 if won else 0
        for lora in self.state['loras']:
            in_a, in_b = lora['tag'] in loras_a, lora['tag'] in loras_b
            if in_a != in_b:
                lora['arena_matches'] += 1
                lora['arena_wins'] += 1 if (a_won if in_a else not a_won) else 0
        entry = {'type': 'arena', 'pair': {'a': a['id'], 'b': b['id']}, 'winner_id': winner_id}
        self.state['history'].insert(0, entry)
        snap['entry'] = entry
        self.undo_stack.append(snap)

    def undo(self):
        with self.lock:
            if not self.undo_stack:
                raise UserError('되돌릴 선별이 없습니다.')
            snap = self.undo_stack.pop()
            kind = snap['kind']
            if kind in ('regular', 'history') or (kind == 'improve' and snap['entry']):
                history = self.state['history']
                index = next((i for i, e in enumerate(history) if e is snap['entry']), None)
                if index is None:
                    self.undo_stack.clear()
                    raise UserError('이 선별은 더 이상 되돌릴 수 없습니다.')
                history.pop(index)
            if kind == 'regular':
                for combo in self.combos:
                    combo.update(snap['combos'].get(combo['id'], {}))
                for artist in self.state['artists']:
                    artist.update(snap['artists'].get(artist['tag'], {}))
                for lora in self.state['loras']:
                    lora.update(snap.get('loras', {}).get(lora['tag'], {}))
            elif kind == 'history':
                if 'combo' in snap:  # the vote had settled a placement: restore the newcomer
                    combo = self.find(snap['combo']['id'])
                    if combo:
                        combo.clear()
                        combo.update(snap['combo'])
                self.state['placement'] = snap['placement']
                if snap['entry']['type'].startswith('selection'):
                    core.apply_selection_ratings(self.combos, self.selection, self.state['history'])
            elif kind == 'improve':
                imp = self.state['improve']
                if snap.get('requeued'):
                    imp['pending'].remove(snap['challenger'])
                    imp['items'].get(snap['challenger'], {}).pop('similar', None)
                imp['pending'].insert(0, snap['challenger'])  # variants made since then stay queued behind it
                imp['items'].get(snap['challenger'], {}).pop('result', None)
                imp.update(snap['before'])
            elif kind == 'tune':
                self._undo_tune(snap)
            elif kind == 'improve_final':
                imp = self.state.get('improve')
                if imp and snap['index'] < len(imp.get('finals', [])):
                    imp['finals'][snap['index']]['winner'] = None
            elif kind == 'tie_skip':
                self.skipped_ties.discard(snap['key'])
            # Back to the very match that was undone (as it was shown), not whatever the arena would pick next.
            restored = snap.get('match')
            self.current = restored if restored and self.find_any(restored['a']) and self.find_any(restored['b']) else None
            self.save()
            return self._match_view() if self.current else self.match()

    # ------------------------------------------------------------------ newcomer placement
    def _placement_votes(self, placement):
        """(rung, result) for the placed newcomer, oldest first."""
        rung = {key: i for i, key in enumerate(placement['ladder'])}
        out = []
        for vote in reversed(self.state['history']):
            if vote.get('batch_id') != placement['batch'] or vote.get('type') not in ('place_vote', 'place_skip'):
                continue
            pair = vote['pair']
            other = pair['b'] if pair['a'] == placement['id'] else pair['a']
            if other not in rung:
                continue
            if vote['type'] == 'place_skip':
                out.append((rung[other], 'tie'))
            else:
                out.append((rung[other], 'win' if vote['winner_id'] == placement['id'] else 'loss'))
        return out

    def _ensure_placement(self):
        """Start placing the next newcomer; the very first combo simply becomes the START_ELO anchor."""
        p = self.state.get('placement')
        if p:
            by_id = {c['id']: c for c in self.combos}
            if p['id'] in by_id and not core.is_rated(by_id[p['id']]) and all(k in by_id for k in p['ladder']):
                return p
        self.state['placement'] = None
        children = set(self.selection['candidate_ids'])
        while True:
            queue = self.newcomers()
            if not queue:
                return None
            newcomer = queue[0]
            ladder = sorted((c for c in self.rated() if c['id'] not in children),
                            key=lambda c: (c['elo'], c['id']))
            if not ladder:
                newcomer['placed'] = True
                newcomer['elo'] = core.START_ELO
                continue
            self.state['placement'] = {'id': newcomer['id'], 'batch': _new_id(),
                                       'ladder': [c['id'] for c in ladder], 'scores': [c['elo'] for c in ladder]}
            return self.state['placement']

    def _placement_pair(self):
        p = self._ensure_placement()
        if not p:
            return None
        _, rung = core.placement_state(self._placement_votes(p), len(p['ladder']))
        if rung is None:
            self._settle_placement()
            return self._placement_pair()
        return 'place', p['id'], p['ladder'][rung], {}

    def _vote_place(self, cur, winner_id, loser_id):
        self._record_place(cur, winner_id)

    def _record_place(self, cur, winner_id):
        """A placement vote (or skip = tie when ``winner_id`` is None); settles the slot when decided."""
        p = self.state['placement']
        entry = {'type': 'place_vote' if winner_id else 'place_skip', 'batch_id': p['batch'],
                 'pair': {'a': cur['a'], 'b': cur['b']}}
        if winner_id:
            entry['winner_id'] = winner_id
        self.state['history'].insert(0, entry)
        snap = {'kind': 'history', 'entry': entry, 'placement': copy.deepcopy(p)}
        before = copy.deepcopy(self.find(p['id']))
        if self._settle_placement():
            snap['combo'] = before
        self.undo_stack.append(snap)

    def _settle_placement(self):
        """If the current newcomer's slot is settled, give it its Elo and move on. Returns True if settled."""
        p = self.state.get('placement')
        if not p:
            return False
        votes = self._placement_votes(p)
        slot, rung = core.placement_state(votes, len(p['ladder']))
        if rung is not None:
            return False
        combo = self.find(p['id'])
        if combo:
            combo['elo'] = core.placement_elo(slot, p['scores'])
            played = [v for v in votes if v[1] != 'tie']
            combo['matches'] += len(played)
            combo['wins'] += sum(1 for v in played if v[1] == 'win')
            combo['placed'] = True
            self._event('ok', f"새 조합이 {len(p['ladder']) - slot + 1}위 자리({combo['elo']}점)에 들어갔습니다.")
        self.state['placement'] = None
        return True

    # ------------------------------------------------------------------ evolution
    def evolution_view(self):
        with self.lock:
            if self._drop_empty_batch():  # e.g. left over from a run that was cancelled before this fix
                self.save()
            sel = self.selection
            children = list(sel['candidate_ids'])
            tiers = self._tiers()
            parents = sel['parent_ids'] if children else self.top_ids()
            view = {'generation': sel['generation'], 'batch_active': bool(children or sel['batch_id']),
                    'log': sel['log'][-12:], 'parents': [], 'children': [], 'summary': None,
                    'blocker': self._evolution_blocker(),
                    'converged': self._converged(), 'converged_after': CONVERGED_GENERATIONS}
            view['can_start'] = view['blocker'] is None
            by_id = {c['id']: c for c in self.combos}
            view['parents'] = [self.combo_view(by_id[k], tiers) for k in parents if k in by_id]
            view['parents'].sort(key=lambda c: c['rank'] or float('inf'))
            if children:
                plan = self._generation_plan()
                info = plan['ranking']['info']
                for key in children:
                    if key not in by_id:
                        continue
                    child = self.combo_view(by_id[key], tiers)
                    pending = key in info and info[key]['rung'] is not None
                    child['status'] = ('평가중' if pending else '탈락' if key in plan['failed']
                                       else '상위 30% 진입' if key in plan['next_parents'] else '생존')
                    view['children'].append(child)
                pending = [c for c in view['children'] if c['status'] == '평가중']
                view['summary'] = {
                    'children': len(children), 'pending': len(pending),
                    'entered': sum(1 for c in view['children'] if c['status'] in ('생존', '상위 30% 진입')),
                    'failed': sum(1 for c in view['children'] if c['status'] == '탈락'),
                    'ready': self._selection_done(plan['ranking']),
                }
            return view

    def cancel_generation(self):
        """Abandon the running generation: its children, their votes and the batch go; the parents stay untouched."""
        with self.lock:
            sel = self.selection
            if not sel['batch_id']:
                raise UserError('취소할 진화 평가가 없습니다.')
            if self.job and self.job['running']:
                raise UserError('조합을 만드는 중입니다. 작업을 먼저 중지해 주세요.')
            ids = set(sel['candidate_ids'])
            batch = sel['batch_id']
            targets = [c for c in self.combos if c['id'] in ids]
            kept = {c.get('image_file') for c in self.combos + self.retired if c['id'] not in ids}
            self._delete_images(c.get('image_file') for c in targets if c.get('image_file') not in kept)
            self.state['combinations'] = [c for c in self.combos if c['id'] not in ids]
            self.state['history'] = [h for h in self.state['history'] if h.get('batch_id') != batch]
            sel.update(batch_id=None, candidate_ids=[], parent_ids=[], parent_scores={})
            self.generating_children = None
            self.current = None
            self.undo_stack.clear()
            core.apply_selection_ratings(self.combos, sel, self.state['history'])
            self.save()
            return {'cancelled': len(targets)}

    def _evolution_blocker(self):
        s = self.rules()
        rated, waiting = len(self.rated()), len(self.newcomers())
        if rated < MIN_RATED_FOR_EVOLUTION:
            return f'평가된 조합이 {MIN_RATED_FOR_EVOLUTION}개 이상 필요합니다 (지금 {rated}개).'
        if waiting:
            return f'자리를 찾지 못한 새 조합 {waiting}개를 먼저 배치해 주세요.'
        if self.selection['candidate_ids']:
            return '진행 중인 진화 조합 평가를 먼저 마무리해 주세요.'
        if len(self.state['artists']) < s['gen_min']:
            return f"작가가 {s['gen_min']}명 이상 필요합니다."
        if self.boundary_tie():
            return '상위 30% 경계 동점을 먼저 해소해 주세요 (선별 화면에 나옵니다).'
        if len(self.top_ids()) < 2:
            return '진화에 쓸 상위 30% 조합이 2개 이상 필요합니다.'
        return None

    def start_evolution(self, count=None):
        with self.lock:
            self._require_idle('진화를 시작해')  # before anything changes: a refused start must leave no batch behind
            blocker = self._evolution_blocker()
            if blocker:
                raise UserError(blocker)
            s = self.rules()
            count = self._start_count('evo_count', count)
            settings = self._gen_settings()
            top = set(self.top_ids())
            parents = [c for c in self.combos if c['id'] in top]
            sel = self.selection
            sel['parent_ids'] = [c['id'] for c in parents]
            sel['parent_scores'] = {c['id']: c['elo'] for c in parents}
            sel['batch_id'] = _new_id()
            sel['candidate_ids'] = []
            self.generating_children = (0, count)
            self.undo_stack.clear()
            self.save()
            artist_tags = [a['tag'] for a in self.state['artists']]
            parent_counts = collections.Counter(t for c in parents for t in core.artists_from_style(c['style']))
            scores = {tag: score for tag, (score, _) in core.artist_scores(self.combos + self.retired).items()}
            preference = core.artist_preference(scores, artist_tags)
            registry = self.lora_registry(s)
            self._require_loras_without_artists(s, registry)
            ranked = core.rank_order(parents)
            seen = {c['style'] for c in self.combos + self.retired}

        def draw():
            p_a, p_b = core.pick_parents(ranked)
            mode = random.choices(core.BREED_MODES, weights=core.BREED_WEIGHTS)[0]
            artists = '' if s['gen_max'] == 0 else core.breed_weighted_style(  # artists off: only the LoRAs are bred
                p_a['style'], p_b['style'], artist_tags, s['gen_min'], s['gen_max'],
                s['global_min_w'], s['global_max_w'], mode, parent_counts, preference)
            # The LoRAs follow the same way of breeding as the artists.
            loras = core.breed_loras(p_a['style'], p_b['style'], registry, s['lora_min'], s['lora_max'], mode)
            return core.style_from_pairs(core.parse_style_combo(artists) + loras), None

        def keep(style, name, _):
            combo = self._new_combo(style, name, settings)  # generation: the evolution tab's
            self.combos.insert(0, combo)
            self.selection['candidate_ids'].append(combo['id'])
            self.generating_children = (len(self.selection['candidate_ids']), count)

        def work(job):
            self._draw_and_render(job, settings, count, draw, keep, seen)

        with self.lock:
            self._start_job('evolution', f"{self.selection['generation']}세대 진화 조합 생성", count, work)

    def _selection_pool(self):
        """The running batch's parents and children."""
        ids = set(self.selection['parent_ids']) | set(self.selection['candidate_ids'])
        return [c for c in self.combos if c['id'] in ids]

    def _selection_pair(self):
        sel = self.selection
        if not sel['candidate_ids']:
            return None
        ranking = core.selection_ranking(sel, self.state['history'])
        pair = core.selection_next_pair(sel, self._selection_pool(), self.state['history'], ranking)
        if pair and self.generating_children:
            # More children are coming and will move the cut: only place children for now.
            if not any(child['bisecting'] for child in ranking['info'].values()):
                return None
        return ('select', pair[0]['id'], pair[1]['id'], {}) if pair else None

    def _vote_select(self, cur, winner_id, loser_id):
        entry = {'type': 'selection_vote', 'pair': {'a': cur['a'], 'b': cur['b']}, 'winner_id': winner_id,
                 'batch_id': self.selection['batch_id']}
        self.state['history'].insert(0, entry)
        core.apply_selection_ratings(self.combos, self.selection, self.state['history'])
        self.undo_stack.append({'kind': 'history', 'entry': entry,
                                'placement': copy.deepcopy(self.state['placement'])})

    def _selection_done(self, ranking=None):
        sel = self.selection
        if not sel['candidate_ids'] or self.generating_children:
            return False
        return core.selection_next_pair(sel, self._selection_pool(), self.state['history'], ranking) is None

    def _generation_plan(self):
        """Failed children leave; as many existing combos as children got in drop from the bottom of
        the list Elo; the top 30% of what remains are the new parents."""
        sel = self.selection
        ranking = core.selection_ranking(sel, self.state['history'])
        parents = set(sel['parent_ids'])
        children = set(sel['candidate_ids'])
        active = {c['id']: c for c in self.combos}
        failed = {k for k in children if k in active and ranking['info'][k]['slot'] == 0}
        entered = [k for k in children if k in active and k not in failed]
        order = sorted((k for k in active if k not in failed),
                       key=lambda k: (active[k]['elo'], k in parents, k), reverse=True)
        removable = [k for k in reversed(order) if k not in children and not active[k].get('kept')]  # 보관함 stays
        dropped = removable[:len(entered)]
        survivors = [k for k in order if k not in dropped]
        next_parents = core.top_tier_ids([active[k] for k in survivors])
        return dict(ranking=ranking, order=order, next_parents=next_parents, failed=failed,
                    entered=entered, dropped=dropped)

    def finish_generation(self):
        with self.lock:
            self._require_idle('세대를 확정해', kinds=('evolution',))
            if not self.selection['candidate_ids']:
                raise UserError('확정할 진화 세대가 없습니다.')
            if not self._selection_done():
                raise UserError('남은 평가 선별을 먼저 마쳐 주세요.')
            core.apply_selection_ratings(self.combos, self.selection, self.state['history'])
            plan = self._generation_plan()
            sel = self.selection
            by_id = {c['id']: c for c in self.combos}
            out = [(k, '탈락') for k in plan['failed']] + [(k, '제외') for k in plan['dropped']]
            for key, reason in out:
                by_id[key]['excluded'] = {'reason': reason, 'generation': sel['generation']}
            self.retired.extend(by_id[k] for k, _ in out)
            gone = {k for k, _ in out}
            self.state['combinations'] = [c for c in self.combos if c['id'] not in gone]
            promoted = len(set(sel['candidate_ids']) & set(plan['next_parents']))
            sel['log'].append({'generation': sel['generation'], 'children': len(sel['candidate_ids']),
                               'entered': len(plan['entered']), 'promoted': promoted,
                               'failed': len(plan['failed']), 'dropped': len(plan['dropped'])})
            self._record_lora_snapshot(sel['generation'], None)
            sel['parent_ids'] = plan['next_parents']
            sel['parent_scores'] = {k: by_id[k]['elo'] for k in plan['next_parents']}
            sel['candidate_ids'] = []
            sel['batch_id'] = None
            sel['generation'] += 1
            self.current = None
            self.undo_stack.clear()
            self._event('ok', f"{sel['generation'] - 1}세대 확정 · 생존 {len(plan['entered'])} · "
                              f"탈락 {len(plan['failed'])} · 기존 최하위 제외 {len(plan['dropped'])}")
            self.save()
            return sel['log'][-1]

    # ---------------------------------------------------------- LoRA record (융합)
    LOCK_TOL = 0.05    # a LoRA is steady when its weights across the top lie within ±this ...
    LOCK_GENS = 3      # ... for this many generations in a row, and its mean has not moved more than this
    LOCK_MIN_MATCHES = 5

    def _record_lora_snapshot(self, generation, top_n):
        """The LoRAs of the top combos as this generation ends: per LoRA count / mean / min / max, and which pairs
        were used together. Lock held."""
        rated = core.rank_order(c for c in self.combos if core.is_rated(c))
        ids = core.top_tier_ids(self.combos) if not top_n else [c['id'] for c in rated[:top_n]]
        by_id = {c['id']: c for c in self.combos}
        top = [by_id[i] for i in ids if i in by_id]
        weights, pairs = {}, {}
        for c in top:
            loras = [(w, t) for w, t in core.parse_style_combo(c['style']) if core.is_lora(t)]
            for w, t in loras:
                weights.setdefault(t, []).append(w)
            tags = sorted({t for _, t in loras})
            for i, a in enumerate(tags):
                for b in tags[i + 1:]:
                    pairs[f'{a}|{b}'] = pairs.get(f'{a}|{b}', 0) + 1
        snap = {'generation': generation, 'n': len(top), 'time': time.time(), 'pairs': pairs,
                'loras': {t: {'count': len(ws), 'mean': round(sum(ws) / len(ws), 3), 'min': min(ws), 'max': max(ws)}
                          for t, ws in weights.items()}}
        hist = self.state.setdefault('lora_history', [])
        hist[:] = [x for x in hist if x['generation'] != generation] + [snap]

    def lora_lock_view(self):
        """Per LoRA across the recorded generations: steady ones become 확정 (and only when the combos that used that
        value also win more than the average), the rest are 후보 (steady but not proven) or 추적 중."""
        with self.lock:
            hist = list(self.state.get('lora_history', []))
            allc = self.combos + self.retired
            tot_m = sum(c.get('matches', 0) for c in allc)
            base = (sum(c.get('wins', 0) for c in allc) / tot_m) if tot_m else 0.0
            tags = {t for snap in hist for t in snap['loras']}
            rows = []
            for t in tags:
                series = [snap['loras'].get(t) for snap in hist]
                streak = []
                for entry in reversed(series):
                    if entry and round(entry['max'] - entry['min'], 3) <= 2 * self.LOCK_TOL:
                        streak.append(entry)
                    else:
                        break
                last = next((e for e in reversed(series) if e), None)
                if not last:
                    continue
                means = [e['mean'] for e in streak]
                steady = len(streak) >= self.LOCK_GENS and max(means) - min(means) <= self.LOCK_TOL
                used = [c for c in allc if any(tag == t and abs(w - last['mean']) <= self.LOCK_TOL
                                                for w, tag in core.parse_style_combo(c['style']))]
                m = sum(c.get('matches', 0) for c in used)
                rate = (sum(c.get('wins', 0) for c in used) / m) if m else None
                proven = rate is not None and m >= self.LOCK_MIN_MATCHES and rate >= base
                top = hist[-1]
                comps = []
                for key, n in top['pairs'].items():
                    a, b = key.split('|')
                    if t in (a, b) and top['loras'].get(t, {}).get('count'):
                        comps.append({'tag': b if a == t else a, 'ratio': round(n / top['loras'][t]['count'], 2)})
                comps.sort(key=lambda x: -x['ratio'])
                rows.append({'tag': t, 'mean': last['mean'], 'range': round(last['max'] - last['min'], 3),
                             'spread': [[e['min'], e['max']] if e else None for e in series],
                             'streak': len(streak), 'gens': len(hist), 'matches': m,
                             'rate': None if rate is None else round(rate, 3),
                             'status': 'locked' if steady and proven else 'candidate' if steady else 'tracking',
                             'companions': comps[:3], 'in_latest': bool(series[-1])})
            order = {'locked': 0, 'candidate': 1, 'tracking': 2}
            rows.sort(key=lambda r: (order[r['status']], -r['streak'], r['range']))
            return {'rows': rows, 'generations': [x['generation'] for x in hist], 'baseline': round(base, 3),
                    'tol': self.LOCK_TOL, 'need': self.LOCK_GENS,
                    'recipe': core.style_from_pairs([(r['mean'], r['tag']) for r in rows if r['status'] == 'locked'])}

    def _converged(self):
        log = self.selection['log']
        recent = log[-CONVERGED_GENERATIONS:]
        return len(recent) == CONVERGED_GENERATIONS and sum(g['entered'] for g in recent) == 0

    # ------------------------------------------------------------------ 다듬기: 가중치 튜닝
    TUNE_SPREADS = {'narrow': (0.05, 0.10, 0.15), 'normal': (0.05, 0.15, 0.30), 'wide': (0.10, 0.25, 0.45)}
    TUNE_MATCHES = 3        # every variant is judged this many times
    TUNE_WINDOW = 0.10      # "values that lie close together": a window this wide

    def _tune_tags(self, pairs, scope):
        """The tags a 다듬기 moves: all of them, only the artists, or only the LoRAs."""
        return [t for _, t in pairs if scope == 'all' or (scope == 'lora') == core.is_lora(t)]

    def _tune_variant(self, base_pairs, spread, cfg, tags):
        """One variant of the base: each chosen tag's weight (artist or LoRA) moves by a small, middling or large step
        (up or down), on a 0.05 grid, inside its range from the settings widened a little. Other tags stay as they are."""
        steps = self.TUNE_SPREADS.get(spread, self.TUNE_SPREADS['normal'])
        idx = [i for i, (_, t) in enumerate(base_pairs) if t in tags]
        moved = {i for i in idx if random.random() < 0.7} or {random.choice(idx)}
        out = []
        for i, (w, t) in enumerate(base_pairs):
            if i in moved:
                lo, hi = (cfg['lora_min_w'], cfg['lora_max_w']) if core.is_lora(t) else (cfg['global_min_w'], cfg['global_max_w'])
                lo, hi = max(0.05, lo - 0.2), hi + 0.2
                step = random.choice(steps) * random.uniform(0.7, 1.15)
                w = round(min(hi, max(lo, w + random.choice((-1, 1)) * step)) / 0.05) * 0.05
            out.append((round(w, 2), t))
        return out

    def start_tune(self, combo_id, count=None, spread='normal', scope='all'):
        with self.lock:
            if self.state.get('tune'):
                raise UserError('진행 중인 다듬기를 먼저 마무리해 주세요.')
            self._require_idle('다듬기를 시작해')
            base = self.find(combo_id)
            if not base:
                raise UserError('다듬을 조합을 찾을 수 없습니다.')
            pairs = core.parse_style_combo(base['style'])
            scope = scope if scope in ('all', 'artist', 'lora') else 'all'
            tags = self._tune_tags(pairs, scope)
            if not tags:
                raise UserError('고른 조합에 LoRA가 없습니다. 바꿀 대상을 "작가"나 "전체"로 해 주세요.' if scope == 'lora'
                                else '고른 조합에 작가가 없습니다. 바꿀 대상을 "LoRA"나 "전체"로 해 주세요.')
            try:
                count = max(4, min(int(count or 30), 80))
            except (TypeError, ValueError):
                raise UserError('변형 수가 올바르지 않습니다.')
            settings = self._gen_settings()
            seed = base['seed'] if base.get('seed') is not None else settings['seed']
            ref = {'id': _new_id(), 'style': base['style'], 'elo': core.START_ELO, 'matches': 0, 'wins': 0, 'placed': True,
                   'image_file': base.get('image_file'), 'seed': seed, 'created': time.time(), 'generation': 0,
                   'weights': {t: w for w, t in pairs if t in tags}, 'reference': True}
            self.state['tune'] = {'id': _new_id(), 'base_id': base['id'], 'spread': spread if spread in self.TUNE_SPREADS else 'normal',
                                  'status': 'generating', 'count': count, 'seed': seed, 'tags': tags, 'scope': scope, 'pairs': [], 'votes': 0,
                                  'items': {ref['id']: ref}, 'order': [ref['id']]}
            self.save()
        self._tune_generate(settings, count)

    def _tune_generate(self, settings, count):
        tune = self.state['tune']
        settings = {**settings, 'seed': tune['seed']}
        base_pairs = core.parse_style_combo(self.find(tune['base_id'])['style']) if self.find(tune['base_id']) else []
        cfg = self.settings()
        seen = {i['style'] for i in tune['items'].values()}

        def draw():
            return core.style_from_pairs(self._tune_variant(base_pairs, tune['spread'], cfg, tune['tags'])), None

        def keep(style, name, _):
            item = {'id': _new_id(), 'style': style, 'elo': core.START_ELO, 'matches': 0, 'wins': 0, 'placed': True,
                    'image_file': name, 'seed': tune['seed'], 'created': time.time(), 'generation': 0,
                    'weights': {t: w for w, t in core.parse_style_combo(style) if t in tune['tags']}}
            tune['items'][item['id']] = item
            tune['order'].append(item['id'])

        def work(job):
            self._draw_and_render(job, settings, count, draw, keep, seen)
            with self.lock:
                if self.state.get('tune') is tune:
                    tune['status'] = 'voting'

        with self.lock:
            tune['status'] = 'generating'
            self._start_job('tune', '다듬기 변형 생성', count, work)

    def tune_more(self, count=None):
        with self.lock:
            tune = self.state.get('tune')
            if not tune:
                raise UserError('진행 중인 다듬기가 없습니다.')
            self._require_idle('변형을 더 만들')
            try:
                count = max(2, min(int(count or 10), 40))
            except (TypeError, ValueError):
                raise UserError('개수가 올바르지 않습니다.')
            settings = self._gen_settings()
            tune['count'] += count
            self.save()
        self._tune_generate(settings, count)

    def _tune_remaining(self, tune):
        return sum(max(0, self.TUNE_MATCHES - i['matches']) for i in tune['items'].values()) / 2

    def _tune_pair(self):
        tune = self.state.get('tune')
        if not tune or len(tune['items']) < 2:
            return None
        items = tune['items']
        cur = self.current
        if cur and cur['kind'] == 'tune' and cur['a'] in items and cur['b'] in items:
            return 'tune', cur['a'], cur['b'], {}
        played = set(tune['pairs'])
        need = [i for i in items.values() if i['matches'] < self.TUNE_MATCHES]
        if not need:
            return None
        first = min(need, key=lambda i: (i['matches'], random.random()))
        rivals = [i for i in items.values() if i['id'] != first['id'] and '|'.join(sorted((first['id'], i['id']))) not in played]
        if not rivals:
            return None
        second = min(rivals, key=lambda i: (i['matches'] >= self.TUNE_MATCHES, abs(i['elo'] - first['elo']), i['matches'], random.random()))
        return 'tune', first['id'], second['id'], {}

    def _tune_snap(self, tune, a, b, key):
        return {'kind': 'tune', 'key': key,
                'items': {i['id']: {k: i[k] for k in ('elo', 'matches', 'wins')} for i in (a, b)}}

    def _vote_tune(self, cur, winner_id, loser_id, tie=False):
        tune = self.state['tune']
        a, b = tune['items'][cur['a']], tune['items'][cur['b']]
        key = '|'.join(sorted((a['id'], b['id'])))
        snap = self._tune_snap(tune, a, b, key)
        if not tie:
            a['elo'], b['elo'] = core.calc_elo(a['elo'], b['elo'], winner_id == a['id'])
            (a if winner_id == a['id'] else b)['wins'] += 1
        a['matches'] += 1
        b['matches'] += 1
        tune['pairs'].append(key)
        tune['votes'] += 1
        self.undo_stack.append(snap)

    def _undo_tune(self, snap):
        tune = self.state.get('tune')
        if not tune:
            return
        for item_id, values in snap['items'].items():
            if item_id in tune['items']:
                tune['items'][item_id].update(values)
        if snap['key'] in tune['pairs']:
            tune['pairs'].remove(snap['key'])
        tune['votes'] = max(0, tune['votes'] - 1)

    def _tune_rate(self, item):
        return item['wins'] / item['matches'] if item['matches'] else 0.0

    def _tune_recommend(self, tune):
        """From the best-judged variants: for each tag the window of 0.10 holding the most of their weights, and the
        mean inside it. Compared with how the other variants did, so the user sees whether it matters."""
        judged = [i for i in tune['items'].values() if i['matches'] >= 1]
        if len(judged) < 4:
            return None
        ranked = sorted(judged, key=lambda i: (self._tune_rate(i), i['elo']), reverse=True)
        k = max(3, math.ceil(len(ranked) * 0.3))
        top, rest = ranked[:k], ranked[k:]
        base = self.find(tune['base_id'])
        base_w = {t: w for w, t in core.parse_style_combo(base['style'])} if base else {}
        rows, rec_weights = [], {}
        for tag in tune['tags']:
            values = sorted(i['weights'].get(tag) for i in top if i['weights'].get(tag) is not None)
            if not values:
                continue
            best = None
            for start in values:
                inside = [v for v in values if start - 1e-9 <= v <= start + self.TUNE_WINDOW + 1e-9]
                if best is None or len(inside) > len(best):
                    best = inside
            rec = round(sum(best) / len(best) / 0.05) * 0.05
            rec = round(rec, 2)
            low, high = min(best), max(best)
            inside_items = [i for i in judged if low - 1e-9 <= i['weights'].get(tag, -9) <= high + 1e-9]
            outside_items = [i for i in judged if i not in inside_items]
            avg = lambda xs: (sum(self._tune_rate(i) for i in xs) / len(xs)) if xs else None
            agree = len(best) / len(values) >= 0.5  # most of the winners lie together; if not, this LoRA's value matters little
            rows.append({'tag': tag, 'base': base_w.get(tag), 'rec': rec, 'range': [low, high], 'overlap': len(best), 'top': len(values),
                         'agree': agree, 'in_rate': avg(inside_items), 'out_rate': avg(outside_items)})
            rec_weights[tag] = rec if agree or base_w.get(tag) is None else base_w[tag]  # no agreement: keep the original value
        style = core.style_from_pairs([(rec_weights.get(t, w), t) for w, t in core.parse_style_combo(tune['items'][tune['order'][0]]['style'])]) if rows else ''
        votes = sum(i['matches'] for i in judged) / 2
        confidence = 'high' if votes >= len(judged) * 1.2 and k >= 5 else 'mid' if votes >= len(judged) * 0.6 else 'low'
        return {'rows': rows, 'style': style, 'anima': core.anima_copy(style) if style else '', 'top': k, 'judged': len(judged),
                'confidence': confidence}

    def tune_view(self):
        with self.lock:
            tune = self.state.get('tune')
            if not tune:
                return {'active': False}
            base = self.find(tune['base_id'])
            tiers = self._tiers()
            ranked = sorted((tune['items'][k] for k in tune['order'] if k in tune['items']),
                            key=lambda i: (self._tune_rate(i) if i['matches'] else -1, i['elo']), reverse=True)
            running = bool(self.job and self.job['running'] and self.job['kind'] == 'tune')
            return {'active': True, 'status': tune['status'], 'spread': tune['spread'], 'count': tune['count'],
                    'running': running, 'progress': [self.job['done'], self.job['total']] if running else None,
                    'base': self.combo_view(base, tiers) if base else None, 'tags': tune['tags'], 'scope': tune.get('scope', 'all'),
                    'votes': tune['votes'], 'remaining': math.ceil(self._tune_remaining(tune)),
                    'made': len(tune['items']) - 1,
                    'items': [{'id': i['id'], 'thumb': f"/thumb/{i['image_file']}" if i.get('image_file') else None,
                               'image': f"/img/{i['image_file']}" if i.get('image_file') else None,
                               'weights': i['weights'], 'matches': i['matches'], 'wins': i['wins'],
                               'rate': self._tune_rate(i) if i['matches'] else None, 'reference': bool(i.get('reference'))} for i in ranked],
                    'recommend': self._tune_recommend(tune)}

    def tune_render(self, count=None):
        """Pictures with the recommended values: the first with the combo's seed, the others with new seeds, so the user
        sees whether the values hold up. They wait in 'merged' (source tune) until put in the list or deleted."""
        with self.lock:
            tune = self.state.get('tune')
            if not tune:
                raise UserError('진행 중인 다듬기가 없습니다.')
            rec = self._tune_recommend(tune)
            if not rec or not rec['style']:
                raise UserError('추천 값을 내려면 선별을 조금 더 진행해 주세요.')
            try:
                count = max(1, min(int(count or 4), 12))
            except (TypeError, ValueError):
                raise UserError('개수가 올바르지 않습니다.')
            self._require_idle('추천 값으로 그리')
            settings = self._gen_settings()
            style, base_id, base_seed = rec['style'], tune['base_id'], tune['seed']
            used = [sorted(set(core.artists_from_style(style))), sorted(t for _, t in core.parse_style_combo(style) if core.is_lora(t))]
            self.save()

        def work(job):
            for i in range(count):
                if self.stop_event.is_set():
                    break
                seed = base_seed if i == 0 else random.randint(0, core.MAX_SEED)
                name = self._render(job, {**settings, 'seed': seed}, style, seed)
                with self.lock:
                    job['done'] += 1
                    if name:
                        self.state['merged'].insert(0, {'key': _new_id(), 'style': style, 'image': name, 'parents': [base_id], 'seed': seed,
                                                        'created': time.time(), 'used': used, 'source': 'tune'})
                        self.save()
            with self.lock:
                self._event('ok', '추천 값으로 그린 그림을 만들었습니다. 다듬기 탭에서 확인하세요.')

        with self.lock:
            self._start_job('tune', '추천 값으로 그리기', count, work)

    def finish_tune(self):
        """Close the session: the variants' pictures go (the reference's belongs to its combo); the pictures drawn with the
        recommended values stay in 'merged' until the user decides."""
        with self.lock:
            tune = self.state.get('tune')
            if not tune:
                return {}
            if self.job and self.job['running'] and self.job['kind'] == 'tune':
                raise UserError('그림을 만드는 중입니다. 끝난 뒤나 작업 중지 후에 마무리해 주세요.')
            names = [i['image_file'] for i in tune['items'].values() if not i.get('reference') and i.get('image_file')]
            keep = {c.get('image_file') for c in self.combos + self.retired} | {m['image'] for m in self.state['merged']}
            self._delete_images(n for n in names if n not in keep)
            self.state['tune'] = None
            if self.current and self.current['kind'] == 'tune':
                self.current = None
            self.undo_stack = collections.deque((u for u in self.undo_stack if u.get('kind') != 'tune'), maxlen=30)
            self.save()
            return {}

    # ------------------------------------------------------------------ improve workbench
    def improve_view(self):
        with self.lock:
            imp = self.state.get('improve')
            tiers = self._tiers()
            candidates = core.rank_order(c for c in self.combos if core.is_rated(c))
            view = {'session': None, 'can_undo': bool(not imp and self._finish_target()), 'candidates': [self.combo_view(c, tiers) for c in candidates],
                    'jitters': _jitter_schedule(), 'final_seeds': FINAL_CHECK_SEEDS,
                    'finals': [self.combo_view(c, tiers) for c in self.combos if c.get('final')],
                    'top': self.top_ids()}  # the live top 30%, shown first as on 진화
            if not imp:
                return view
            items = imp['items']

            def item_view(key, role=None):
                combo = self.find_any(key)
                return self.combo_view(combo, tiers, role) if combo else None
            base = self.find_any(imp['base_id'])
            champion_combo = self.find_any(imp['champion_id']) if imp.get('champion_id') else None
            view['session'] = {
                'status': imp['status'], 'round': imp['round'], 'jitter': imp['jitter'], 'next_jitter': _next_jitter(imp['jitter']),
                'base': item_view(imp['base_id']), 'champion': item_view(imp['champion_id'], '챔피언'),
                'pending': [item_view(k, '변형') for k in imp['pending'] if k in items],
                'seed': imp['seed'], 'changed': imp['changed'],
                'variants': [{**item_view(k), 'result': items[k].get('result')}
                             for k in imp['order'] if k in items],
                'finals': [{'seed': f['seed'], 'champion': f'/img/{f["champion"]}' if f.get('champion') else None,
                            'base': f'/img/{f["base"]}' if f.get('base') else None, 'winner': f.get('winner')}
                           for f in imp.get('finals', [])],
                'final_left': sum(1 for f in imp.get('finals', []) if f.get('champion_id') and f.get('winner') is None),
                'same_as_base': bool(base and champion_combo and champion_combo['style'] == base['style']),
                'suggest_final': imp['status'] == 'round_done' and not imp['changed'] and imp['jitter'] <= IMPROVE_JITTER_MIN,
            }
            return view

    def start_improve(self, combo_id, variants=None):
        with self.lock:
            if self.state.get('improve'):
                raise UserError('진행 중인 다듬기를 먼저 마무리해 주세요.')
            self._require_idle('다듬기를 시작해')
            base = self.find(combo_id)
            if not base:
                raise UserError('다듬을 조합을 찾을 수 없습니다.')
            settings = self._gen_settings()
            count = self._start_count('improve_variants', variants)
            # The original is the first champion as drawn; variants use its seed, so only the weights differ.
            # ponytail: a prompt/model changed since the original was drawn also differs; re-render it if that matters.
            seed = base['seed'] if base.get('seed') is not None else settings['seed']
            self.state['improve'] = {
                'base_id': base['id'], 'champion_id': base['id'], 'items': {},
                'round': 1, 'jitter': IMPROVE_JITTER_START, 'pending': [], 'order': [], 'changed': False,
                'status': 'generating', 'seed': seed, 'variants': count,
                'finals': [],
            }
            self.save()
        self._improve_generate(settings, count)

    def _improve_generate(self, settings, count):
        s = self.settings()
        registry = self.lora_registry(s)
        settings = {**settings, 'seed': self.state['improve']['seed']}

        def work(job):
            imp = self.state['improve']
            seen = {self.find_any(k)['style'] for k in imp['items']} | {self.find_any(imp['champion_id'])['style']}

            def draw():
                # The champion as it is now: a variant that wins mid-round is what the rest of the round varies.
                with self.lock:
                    pairs = core.parse_style_combo(self.find_any(imp['champion_id'])['style'])
                # A LoRA keeps to its own range (one no longer registered, to the settings' LoRA range).
                bounds = {tag: registry.get(tag, (s['lora_min_w'], s['lora_max_w'])) for _, tag in pairs if core.is_lora(tag)}
                return core.style_from_pairs(core.jitter_weights(pairs, imp['jitter'], s['global_min_w'], s['global_max_w'],
                                                                 bounds=bounds)), None

            def keep(style, name, _):
                champion = self.find_any(imp['champion_id'])
                item = self._new_combo(style, name, settings, elo=champion['elo'], generation=champion.get('generation', 1))
                imp['items'][item['id']] = item
                # Ahead of the variants called "similar": those come back only at the end of the round.
                again = [n for n, k in enumerate(imp['pending']) if imp['items'].get(k, {}).get('similar')]
                imp['pending'].insert(again[0] if again else len(imp['pending']), item['id'])
                imp['order'].append(item['id'])
                imp['status'] = 'voting'

            self._draw_and_render(job, settings, count, draw, keep, seen)

        with self.lock:
            self._start_job('improve', f"다듬기 {self.state['improve']['round']}라운드 생성", count, work)

    def _final_of(self, cur):
        index = (cur.get('meta') or {}).get('final')
        imp = self.state.get('improve')
        if index is None or not imp or index >= len(imp.get('finals', [])):
            return None
        return imp['finals'][index]

    def _improve_pair(self):
        imp = self.state.get('improve')
        if imp and imp['status'] == 'final_ready' and not self._same_as_base(imp):
            # The final check is a vote too: for every seed, the champion's picture against the original's.
            for index, final in enumerate(imp['finals']):
                if final.get('winner') is None and final.get('champion_id'):
                    return 'improve', final['champion_id'], final['base_id'], {'final': index}
            return None
        if not imp or not imp['pending'] or not imp.get('champion_id'):
            return None
        return 'improve', imp['champion_id'], imp['pending'][0], {}

    def _vote_improve(self, cur, winner_id, loser_id):
        final = self._final_of(cur)
        if final:
            self._final_vote(cur, final, 'champion' if winner_id == final['champion_id'] else 'base')
            return
        self._improve_step(winner_id, {'a': cur['a'], 'b': cur['b']})

    def _same_as_base(self, imp):
        champion, base = self.find_any(imp['champion_id']), self.find_any(imp['base_id'])
        return bool(champion and base and champion['style'] == base['style'])

    def _final_vote(self, cur, final, winner):
        """winner: 'champion', 'base', or 'tie' (비슷함: it counts for neither)."""
        final['winner'] = winner
        self.undo_stack.append({'kind': 'improve_final', 'index': cur['meta']['final']})

    def _maybe_finish_final(self):
        """All seeds judged: the side that won more of them is the final style (a draw keeps the original)."""
        imp = self.state.get('improve')
        if not imp or imp['status'] != 'final_ready' or not imp.get('finals') or self._same_as_base(imp):
            return
        if any(f.get('winner') is None for f in imp['finals']):
            return
        champion = sum(1 for f in imp['finals'] if f['winner'] == 'champion')
        base = sum(1 for f in imp['finals'] if f['winner'] == 'base')
        self._reveal_items = dict(imp.get('final_items') or {})
        self._event('info', f'다른 시드 {len(imp["finals"])}개 선별 결과: 챔피언 {champion}승 · 원본 {base}승')
        self.finish_improve('champion' if champion > base else 'base', defer_delete=True)

    def _improve_step(self, winner_id, pair=None):
        """The first waiting variant meets the champion, undoably. ``winner_id`` None = "similar": the first time
        the variant goes to the end of the round to be shown again; the second time the champion keeps its title."""
        imp = self.state['improve']
        snap = {'kind': 'improve', 'challenger': imp['pending'].pop(0), 'entry': None,
                'before': {k: imp[k] for k in ('champion_id', 'changed', 'status')}}
        challenger = snap['challenger']
        item = imp['items'][challenger]
        if winner_id:
            item['result'] = 'win' if winner_id == challenger else 'loss'
            if winner_id == challenger:
                imp['champion_id'] = challenger
                imp['changed'] = True
            snap['entry'] = {'type': 'improve_vote', 'pair': pair, 'winner_id': winner_id}
            self.state['history'].insert(0, snap['entry'])
        elif not item.get('similar'):
            item['similar'] = True
            imp['pending'].append(challenger)
            snap['requeued'] = True
        else:
            item['result'] = 'loss'  # similar twice: it did not take the title (no vote in the history)
        self._improve_round_check()
        self.undo_stack.append(snap)

    def _improve_round_check(self):
        imp = self.state.get('improve')
        generating = self.job and self.job['running'] and self.job['kind'] == 'improve'
        if imp and not imp['pending'] and not generating and imp['status'] in ('voting', 'generating'):
            imp['status'] = 'round_done'

    def improve_next_round(self):
        with self.lock:
            imp = self.state.get('improve')
            if not imp or imp['status'] != 'round_done':
                raise UserError('지금은 다음 라운드를 시작할 수 없습니다.')
            self._require_idle('다음 라운드를 시작해')
            imp['round'] += 1
            imp['jitter'] = _next_jitter(imp['jitter'])
            imp['changed'] = False
            imp['status'] = 'generating'
            settings = self._gen_settings()
            count = imp['variants']
            self.undo_stack.clear()  # last round's votes are settled
            self.save()
        self._improve_generate(settings, count)

    def improve_final_check(self):
        with self.lock:
            imp = self.state.get('improve')
            if not imp or imp['status'] not in ('round_done', 'final_ready'):
                raise UserError('라운드를 마친 뒤 최종 확인을 할 수 있습니다.')
            self._require_idle('최종 확인을 시작해')  # before the old final images are dropped
            settings = self._gen_settings()
            champion = self.find_any(imp['champion_id'])
            base = self.find_any(imp['base_id'])
            # The champion never beat the original (same weights): draw it once per seed, not twice.
            same = champion['style'] == base['style']
            roles = (('base', base),) if same else (('champion', champion), ('base', base))
            seeds = [random.randint(0, core.MAX_SEED) for _ in range(FINAL_CHECK_SEEDS)]
            self._drop_final_images(imp)
            imp['finals'] = [{'seed': seed} for seed in seeds]
            imp['status'] = 'final_check'
            self.undo_stack.clear()
            self.save()

        def work(job):
            for final in imp['finals']:
                for role, combo in roles:
                    if self.stop_event.is_set():
                        break
                    name = self._render(job, settings, combo['style'], final['seed'])
                    with self.lock:
                        job['done'] += 1
                        final[role] = name
                        if same:
                            final['champion'] = name
                        self.save()
            with self.lock:
                if all(final.get('champion') and final.get('base') for final in imp['finals']):
                    if not same:  # each seed's two pictures become a match of their own (arena: 챔피언 vs 원본)
                        for final in imp['finals']:
                            pair = {}
                            for role, combo in (('champion', champion), ('base', base)):
                                item = self._new_combo(combo['style'], final[role], {'seed': final['seed']}, elo=combo['elo'],
                                                       generation=combo.get('generation', 1), final_seed=True)
                                imp.setdefault('final_items', {})[item['id']] = item
                                final[f'{role}_id'] = item['id']
                            final['winner'] = None
                    imp['status'] = 'final_ready'
                else:  # stopped or failed part-way: back to the round instead of half-drawn previews
                    self._drop_final_images(imp)
                    imp['finals'] = []
                    imp['status'] = 'round_done'
                    self._event('warn', '최종 확인 이미지를 모두 그리지 못해 라운드 결과로 돌아갑니다. 다시 시도할 수 있습니다.')

        with self.lock:
            self._start_job('final', '다른 시드로 최종 확인', FINAL_CHECK_SEEDS * len(roles), work)

    def finish_improve(self, choice='champion', defer_delete=False):
        """End the session: 'champion' keeps the winner, 'base' keeps the original, 'discard' keeps neither.

        A champion that differs from the original joins the ranking as a newcomer and is marked final;
        the other variants stay visible as ✕ 탈락.
        """
        with self.lock:
            imp = self.state.get('improve')
            if not imp:
                raise UserError('진행 중인 다듬기가 없습니다.')
            if choice not in ('champion', 'base', 'discard'):
                raise UserError('마무리 방법이 올바르지 않습니다.')
            self._require_idle('마무리해', kinds=('improve', 'final'))
            base = self.find(imp['base_id'])
            champion = imp['items'].get(imp['champion_id'])
            improved = choice == 'champion' and champion is not None
            result = None
            if improved:
                champion.update({'placed': False, 'final': True})
                champion.pop('result', None)
                champion.pop('similar', None)
                self.combos.append(champion)
                result = champion['id']
            elif choice != 'discard' and base:
                base['final'] = True
                result = base['id']
            for key, item in imp['items'].items():
                if key == result:
                    continue
                item.pop('result', None)
                item.pop('similar', None)
                item['excluded'] = {'reason': '탈락', 'generation': None, 'improve': imp['base_id']}
                self.retired.append(item)
            self._drop_final_images(imp, defer=defer_delete)
            self.state['improve'] = None
            self.current = None
            self.undo_stack.clear()
            if improved:
                self._event('ok', '다듬은 조합을 최종 그림체로 저장했습니다. 선별에서 전체 순위 안의 자리를 찾습니다.')
            elif result:
                self._event('ok', '원본을 최종 그림체로 표시했습니다.')
            else:
                self._event('info', '다듬기를 끝냈습니다.')
            self.save()
            return result

    def _finish_target(self):
        """The refine that was finished last, rebuilt from what it left behind: the variants it marked 탈락 (they carry the
        original's id), the final style among the active combos. None when there is nothing to take back."""
        variants = [c for c in self.retired if (c.get('excluded') or {}).get('improve')]
        if not variants:
            return None
        base_id = max(variants, key=lambda c: c.get('created', 0))['excluded']['improve']
        mine = [c for c in variants if c['excluded']['improve'] == base_id]
        base = self.find_any(base_id)
        finals = [c for c in self.combos if c.get('final')]
        if not base or not finals:
            return None
        final = next((c for c in finals if c['id'] == base_id), None)
        if final is None:
            newer = [c for c in finals if c['id'] != base_id]
            final = max(newer, key=lambda c: c.get('created', 0)) if newer else None
        return (base, mine, final) if final else None

    def undo_finish(self):
        """Take back the last 확정: the session is back at its last round, so it can be refined further or confirmed again."""
        with self.lock:
            if self.state.get('improve'):
                raise UserError('진행 중인 다듬기가 있어 확정을 되돌릴 수 없습니다.')
            self._require_idle('되돌려', kinds=('improve', 'final'))
            target = self._finish_target()
            if not target:
                raise UserError('되돌릴 다듬기 확정이 없습니다.')
            base, variants, final = target
            items = {c['id']: c for c in variants}
            if final['id'] != base['id']:
                if final['matches']:
                    raise UserError('확정한 그림체가 이미 선별에 나가서 되돌릴 수 없습니다.')
                self.state['combinations'] = [c for c in self.combos if c['id'] != final['id']]
                final.pop('final', None)
                items[final['id']] = final
            else:
                base.pop('final', None)
            for item in items.values():
                item.pop('excluded', None)
                item.pop('result', None)
                item.pop('similar', None)
            ids = set(items)
            self.selection['retired'] = [c for c in self.retired if c['id'] not in ids]
            s = self.settings()
            order = sorted(items, key=lambda k: items[k].get('created', 0))
            self.state['improve'] = {
                'base_id': base['id'], 'champion_id': final['id'], 'items': items, 'round': len(_jitter_schedule()),
                'jitter': IMPROVE_JITTER_MIN, 'pending': [], 'order': [k for k in order if k != final['id']], 'changed': False,
                'status': 'round_done', 'seed': base['seed'] if base.get('seed') is not None else s['seed'],
                'variants': s['improve_variants'], 'finals': [], 'final_items': {},
            }
            self.current = None
            self.undo_stack.clear()
            self._event('ok', '다듬기 확정을 되돌렸습니다. 더 다듬거나 최종 확인을 다시 할 수 있습니다.')
            self.save()

    def improve_resume(self):
        """Back from the final check to keep refining."""
        with self.lock:
            imp = self.state.get('improve')
            if not imp or imp['status'] != 'final_ready':
                raise UserError('최종 확인 결과가 있을 때만 다듬기를 이어갈 수 있습니다.')
            self._drop_final_images(imp)
            imp['finals'] = []
            imp['status'] = 'round_done'
            self.save()

    def _drop_final_images(self, imp, defer=False):
        """Final-check previews are only ever shown in the app's own window: removed as far as possible.
        ``defer``: after the last vote, whose two pictures are still on screen for a moment."""
        names = [final.get(role) for final in imp.get('finals', []) for role in ('champion', 'base')]
        imp['final_items'] = {}

        def remove():
            for name in names:
                try:
                    self._delete_images([name])
                except UserError:
                    pass
        if defer:
            timer = threading.Timer(30, remove)
            timer.daemon = True
            timer.start()
        else:
            remove()

    # ------------------------------------------------------------------ combos: edit / delete / revive
    def _delete_images(self, names):
        """Delete images and their thumbnails, before the records go. Windows refuses a file another program
        holds open (a viewer): that fails the request and the records stay, so trying again finishes it."""
        for name in names:
            if not name or (self.img_dir / name).resolve().parent != self.img_dir.resolve():
                continue
            try:
                (self.img_dir / name).unlink(missing_ok=True)
                (self.thumb_dir / (Path(name).stem + '.webp')).unlink(missing_ok=True)
            except OSError:
                raise UserError('그림 파일이 다른 프로그램에서 열려 있어 삭제에 실패했습니다.')

    def _protected(self):
        sel = self.selection
        if not sel['candidate_ids']:
            return set()
        return set(sel['parent_ids']) | set(sel['candidate_ids'])

    def delete_combos(self, ids):
        with self.lock:
            self._require_idle('삭제해')
            ids = set(ids)
            if ids & self._protected():
                raise UserError('진행 중인 진화에 쓰이는 조합은 세대를 확정한 뒤 삭제할 수 있습니다.')
            imp = self.state.get('improve') or self.state.get('tune')
            if imp and imp['base_id'] in ids:
                raise UserError('다듬기 중인 원본은 다듬기를 마친 뒤 삭제할 수 있습니다.')
            targets = [c for c in self.combos + self.retired if c['id'] in ids]
            if any(c.get('kept') for c in targets):
                raise UserError('북마크한 조합은 북마크를 해제한 뒤 삭제할 수 있습니다.')
            kept = {c.get('image_file') for c in self.combos + self.retired if c['id'] not in ids}
            self._delete_images(c.get('image_file') for c in targets if c.get('image_file') not in kept)  # before the records: a refusal keeps them
            self.state['combinations'] = [c for c in self.combos if c['id'] not in ids]
            self.selection['retired'] = [c for c in self.retired if c['id'] not in ids]
            if self.state.get('placement') and (self.state['placement']['id'] in ids
                                                or ids & set(self.state['placement']['ladder'])):
                self.state['placement'] = None
            self.current = None
            self.undo_stack.clear()
            self.save()
            return {'deleted': len(targets)}

    MEMO_MAX = 2000

    def set_memo(self, combo_id, memo):
        """A free note on a combo (what it is good for, which prompt it likes ...). Empty removes it."""
        with self.lock:
            combo = next((c for c in self.combos + self.retired if c['id'] == combo_id), None)
            if not combo:
                raise UserError('조합을 찾을 수 없습니다.')
            memo = str(memo or '').strip()[:self.MEMO_MAX]
            if memo:
                combo['memo'] = memo
            else:
                combo.pop('memo', None)
            self.save()
            return {'memo': memo}

    def set_kept(self, ids, kept=True):
        """보관함: combos the user wants to keep. They are never dropped by evolution, never purged, and cannot be
        deleted until taken out."""
        with self.lock:
            ids = set(ids or [])
            found = [c for c in self.combos + self.retired if c['id'] in ids]
            if not found:
                raise UserError('조합을 선택해 주세요.')
            for c in found:
                if kept:
                    c['kept'] = True
                else:
                    c.pop('kept', None)
            self.save()
            return {'count': len(found)}

    def purge(self, reason):
        with self.lock:
            ids = [c['id'] for c in self.retired if (c.get('excluded') or {}).get('reason', '제외') == reason and not c.get('kept')]
            return self.delete_combos(ids)

    def revive(self, ids):
        with self.lock:
            self._require_idle('부활시켜')
            ids = set(ids)
            targets = [c for c in self.retired if c['id'] in ids]
            self.selection['retired'] = [c for c in self.retired if c['id'] not in ids]
            for combo in targets:
                combo.pop('excluded', None)
                if not core.is_rated(combo):
                    combo['placed'] = False  # never judged: let it find its place
                self.combos.append(combo)
            self.current = None
            self.undo_stack.clear()
            self.save()
            return len(targets)

    def set_elo(self, ids, elo):
        with self.lock:
            elo = int(elo)
            if elo < 0:
                raise UserError('Elo는 0 이상으로 입력해 주세요.')
            ids = set(ids)
            for combo in self.combos + self.retired:
                if combo['id'] in ids:
                    combo['elo'] = elo
                    if not core.is_rated(combo):
                        combo['placed'] = True
            # Ladders frozen for a running selection / placement take the new score at once.
            sel = self.selection
            if sel['candidate_ids'] and ids & set(sel['parent_scores']):
                sel['parent_scores'].update({key: elo for key in ids if key in sel['parent_scores']})
                core.apply_selection_ratings(self.combos, sel, self.state['history'])
            p = self.state.get('placement')
            if p and ids & set(p['ladder']):
                by_id = {c['id']: c for c in self.combos}
                if all(key in by_id for key in p['ladder']):
                    p['ladder'] = sorted(p['ladder'], key=lambda key: (by_id[key]['elo'], key))
                    p['scores'] = [by_id[key]['elo'] for key in p['ladder']]
                else:
                    self.state['placement'] = None  # a rung left the list: start this placement afresh
            self.current = None
            self.undo_stack.clear()
            self.save()

    def image_path(self, combo_id):
        with self.lock:
            combo = self.find_any(combo_id)
            return self.img_dir / combo['image_file'] if combo and combo.get('image_file') else None

    # ------------------------------------------------------------------ reset
    RESET_SCOPES = ('ratings', 'evolution', 'settings', 'artists', 'combos', 'all')

    def reset(self, scope):
        """Reset one part of the data. Nothing is backed up."""
        with self.lock:
            if scope not in self.RESET_SCOPES:
                raise UserError('초기화 범위가 올바르지 않습니다.')
            self._require_idle('초기화해')
            if scope in ('ratings', 'evolution') and self.selection['candidate_ids']:
                raise UserError('진행 중인 진화 세대를 확정한 뒤 초기화해 주세요.')
            if scope == 'ratings' and self.state.get('improve'):
                raise UserError('진행 중인 다듬기를 마친 뒤 초기화해 주세요.')
            s = self.state
            if scope == 'ratings':
                for combo in self.combos + self.retired:
                    combo.update(elo=core.START_ELO, matches=0, wins=0, placed=False)
                for artist in s['artists'] + s['loras']:
                    artist.update(arena_matches=0, arena_wins=0)
                s['history'], s['placement'] = [], None
            elif scope == 'evolution':
                sel = self.selection
                sel.update(generation=1, log=[], parent_ids=[], parent_scores={}, candidate_ids=[], batch_id=None)
                s['lora_history'] = []  # the 융합 record starts over with the generations
                for combo in self.combos + self.retired:
                    combo['generation'] = 0  # the next batch is 1세대 again
            elif scope == 'settings':
                seed = s['ui_state'].get('seed', '')
                s['ui_state'] = {'seed': seed}  # the seed stays so new images still compare with old ones
            elif scope == 'artists':
                s['artists'] = core.default_artists()
                s['ui_state']['artists_checked'] = False  # back to the default list: check it again
            else:
                saved = [c for c in self.combos + self.retired if c.get('kept')] if scope == 'combos' else []  # 보관함 survives
                keep_images = {c.get('image_file') for c in saved}
                self._delete_images(p.name for p in self.img_dir.iterdir() if p.is_file() and p.name not in keep_images)  # before the records: a refusal keeps them
                shutil.rmtree(self.thumb_dir, ignore_errors=True)
                keep = {'artists': s['artists'], 'loras': s['loras'], 'ui_state': s['ui_state']} if scope == 'combos' else {}
                self.state = {**core.empty_state(), **keep}
                if saved:
                    for c in saved:
                        c.pop('excluded', None)
                        c.update(elo=core.START_ELO, matches=0, wins=0, placed=False, generation=0)
                    self.state['combinations'] = saved
            if scope == 'all':
                self.connection = None
            self.current = None
            self.undo_stack.clear()
            self.skipped_ties.clear()
            self.save()
            return {}

    # ------------------------------------------------------------------ export / import
    def export_data(self, target):
        """Write one zip with state.json and every image into the binary file ``target``."""
        with self.lock:
            self.save()
            # PNGs are already compressed: store them as is, which keeps big exports fast.
            with zipfile.ZipFile(target, 'w', zipfile.ZIP_STORED) as zf:
                zf.write(self.state_file, 'state.json', compress_type=zipfile.ZIP_DEFLATED)
                for image in sorted(self.img_dir.glob('*.png')):
                    zf.write(image, f'images/{image.name}')

    def import_data(self, blob: bytes):
        """Replace everything with an exported zip. Nothing is backed up."""
        try:
            zf = zipfile.ZipFile(io.BytesIO(blob))
            state = json.loads(zf.read('state.json').decode('utf-8'))
        except (zipfile.BadZipFile, KeyError, ValueError):
            raise UserError('Anima Style Lab(또는 NAI Style Lab)에서 내보낸 zip 파일이 아닙니다.')
        try:  # an export from an older release is upgraded like its data would be at launch
            if isinstance(state, dict):
                core.upgrade_state(state)
        except core.NewerDataError:
            raise UserError('더 새 버전의 Anima Style Lab에서 내보낸 데이터입니다. 앱을 업데이트한 뒤 불러오세요.')
        except (ValueError, KeyError, TypeError, AttributeError):
            raise UserError('데이터 파일의 내용이 올바르지 않습니다.')
        combos = state.get('combinations') if isinstance(state, dict) else None
        if not isinstance(combos, list) or not all(isinstance(c, dict) and COMBO_KEYS <= c.keys() for c in combos):
            raise UserError('데이터 파일의 내용이 올바르지 않습니다.')
        # Only flat image names: nothing in the zip may write outside the images folder.
        images = [(info, Path(info.filename).name) for info in zf.infolist()
                  if info.filename.startswith('images/') and Path(info.filename).name.lower().endswith('.png')
                  and info.filename == f'images/{Path(info.filename).name}']
        # Nothing current is touched until the zip has fully unpacked and its state checks out.
        staging, retired_dir = self.data_dir / 'images.importing', self.data_dir / 'images.replaced'
        with self.lock:
            self._require_idle('불러와')
            shutil.rmtree(staging, ignore_errors=True)
            shutil.rmtree(retired_dir, ignore_errors=True)
            staging.mkdir()
            try:
                for info, name in images:
                    (staging / name).write_bytes(zf.read(info))
            except (zipfile.BadZipFile, OSError) as exc:
                shutil.rmtree(staging, ignore_errors=True)
                raise UserError(f'zip 파일의 이미지를 풀지 못했습니다: {exc}')
            try:
                self.img_dir.rename(retired_dir)
                staging.rename(self.img_dir)
            except OSError as exc:
                if retired_dir.exists() and not self.img_dir.exists():
                    retired_dir.rename(self.img_dir)
                shutil.rmtree(staging, ignore_errors=True)
                raise UserError(f'이미지 폴더를 바꾸지 못했습니다. 잠시 뒤 다시 시도해 주세요: {exc}')
            self.state = {**core.empty_state(), **state}
            shutil.rmtree(retired_dir, ignore_errors=True)
            shutil.rmtree(self.thumb_dir, ignore_errors=True)
            self.current = None
            self.undo_stack.clear()
            self.skipped_ties.clear()
            self.save()
            return {'combos': len(self.combos), 'images': len(images)}

    # ------------------------------------------------------------------ ComfyUI connection
    def refresh_connection(self):
        """Ask ComfyUI which models it has, in the background (at launch), so the settings and the sidebar know."""
        threading.Thread(target=self.check_connection, daemon=True).start()

    def check_connection(self):
        url = self.settings()['comfy_url']
        try:
            data = self._check_connection(url)
            error = None
        except Exception as exc:
            data, error = None, str(exc)
        with self.lock:
            self.connection = {'data': data, 'error': error, 'checked': _now(), 'url': url, 'at': time.time()}
            # Nothing chosen yet: take the likeliest model files so the first run works with one click.
            if data:
                ui = self.state['ui_state']
                for key, names, hints in (('unet_name', data.get('unet_names', []), ('anima',)),
                                          ('clip_name', data.get('clip_names', []), ('qwen_3_06b', 'qwen3', 'qwen')),
                                          ('vae_name', data.get('vae_names', []), ('qwen_image_vae', 'qwen_image', 'qwen'))):
                    if not ui.get(key) and (guess := core.pick_default(names, *hints)):
                        ui[key] = guess
                self.save()
                self._prune_loras(data.get('lora_names') or [])
            return self.connection_view()

    def _prune_loras(self, available):
        """LoRAs whose file ComfyUI no longer lists drop out of the registry (a combo with one cannot be drawn at all).
        Combos already made stay as they are, like after a delete. An empty list is not trusted: it is more likely
        ComfyUI's hiccup than every file gone. Call with the lock held."""
        have = set(available)
        if not have:
            return
        gone = [l for l in self.state['loras'] if core.lora_name(l['tag']) not in have]
        if not gone:
            return
        self.state['loras'] = [l for l in self.state['loras'] if l not in gone]
        names = ', '.join(core.lora_label(l['tag']) for l in gone[:5]) + (f' 외 {len(gone) - 5}개' if len(gone) > 5 else '')
        self._event('warn', f'ComfyUI에서 파일이 없어진 LoRA {len(gone)}개를 목록에서 뺐습니다: {names}')
        self.save()

    def settings_payload(self):
        """Everything /api/settings returns; the pages keep one copy and refetch it when settings_rev changes."""
        return {'settings': self.settings(), 'connection': self.connection_view(), 'workflow': self.workflow_state()}

    def connection_view(self):
        conn = self.connection
        if not conn:
            return None
        if conn['error']:
            return {'error': conn['error'], 'checked': conn['checked']}
        d = conn['data']
        return {'version': d.get('version', ''), 'checked': conn['checked'], 'unet_names': d['unet_names'],
                'clip_names': d['clip_names'], 'vae_names': d['vae_names'], 'lora_names': d.get('lora_names', []),
                'samplers': d['samplers'] or core.SAMPLERS, 'schedulers': d['schedulers'] or core.SCHEDULERS}

    # ------------------------------------------------------------------ workflow stage
    def stage(self):
        """Where the user is in 준비 → 순위 결정 → 진화 → 다듬기 → 완성, and what to do now."""
        s = self.rules()
        checklist = {
            'connection': bool(self.workflow_state()['exists'] or (s['unet_name'] and s['clip_name'] and s['vae_name'])),
            # Enough artists, and looked at: the default list alone is not a choice yet.
            'artists': len(self.state['artists']) >= s['gen_min'] and (s['artists_checked'] or bool(self.combos)),
            'prompt': s['prompt_checked'] or bool(self.combos),  # combos made before this step existed count as checked
            'combos': bool(self.combos),
        }
        imp = self.state.get('improve')
        rated = len(self.rated())
        newcomers = len(self.newcomers())
        running = self.job and self.job['running']
        shown_rated, waiting = self.ranking_counts(rated, newcomers)
        finals = any(c.get('final') for c in self.combos)  # a refine was finished: the journey is done
        if not all(checklist.values()):
            step = 0
            if not checklist['connection']:
                todo = ('설정에서 ComfyUI 주소를 확인하고 Anima 모델을 고르세요.', 'settings', '설정 열기')
            elif len(self.state['artists']) < s['gen_min']:
                todo = (f"좋아하는 작가를 {s['gen_min']}명 이상 등록하세요.", 'library', '작가 등록')
            elif not checklist['artists']:
                todo = ('작가 목록을 확인하세요. 좋아하는 작가를 더하거나 기본 목록을 그대로 써도 됩니다.', 'library', '작가 확인')
            elif not checklist['prompt']:
                todo = ('모든 그림에 쓰일 프롬프트를 확인하세요. 기본값 그대로 써도 됩니다.', 'settings', '프롬프트 확인')
            else:
                todo = ('첫 무작위 조합을 만들어 보세요.', 'library', '조합 만들기')
        elif self.state.get('tune'):
            tune = self.state['tune']
            step = 3
            if tune['status'] == 'generating':
                todo = ('가중치를 바꾼 변형을 만드는 중입니다. 만들어지는 대로 선별할 수 있습니다.', 'arena', '선별하기')
            elif self._tune_remaining(tune) > 0:
                todo = ('가중치만 다른 변형 중 마음에 드는 쪽을 고르세요. 이기는 값들이 추천 값이 됩니다.', 'arena', '선별하기')
            else:
                todo = ('선별이 끝났습니다. 다듬기 탭에서 추천 값을 확인하고 그 값으로 그려 보세요.', 'refine', '추천 보기')
        elif imp:
            step = 4 if imp['status'] in ('final_check', 'final_ready') else 3
            if imp['status'] == 'final_ready' and not self._same_as_base(imp):
                todo = ('다른 시드로 그린 챔피언과 원본을 선별에서 고르세요. 이기는 쪽이 많은 그림체가 최종으로 정해집니다.', 'arena', '선별하기')
            elif imp['status'] == 'final_ready':
                todo = ('챔피언이 원본 그대로입니다. 원본을 확정하거나 더 다듬을 수 있습니다.', 'refine', '최종 확인')
            elif imp['status'] == 'final_check':
                todo = ('다른 시드로 최종 확인 이미지를 그리는 중입니다.', 'refine', '진행 보기')
            elif imp['status'] == 'round_done':
                todo = ('라운드가 끝났습니다. 다음 라운드로 더 다듬거나 최종 확인하세요.', 'refine', '다듬기 보기')
            else:
                todo = ('챔피언과 변형을 비교하세요. 마음에 드는 쪽을 고르면 됩니다.', 'arena', '선별하기')
        elif newcomers or rated < MIN_RATED_FOR_EVOLUTION:
            step = 4 if finals else 1  # the refined style finding its place in the ranking is still 완성
            if newcomers:
                todo = (f'새 조합 {waiting}개의 자리를 찾아 주세요. 한 조합당 약 {max(1, math.ceil(math.log2(rated + 1)))}표면 됩니다.', 'arena', '선별하기')
            elif running:
                todo = ('새 조합을 만드는 중입니다. 완성되는 대로 선별이 시작됩니다.', 'arena', '선별하기')
            else:
                todo = (f'평가된 조합이 {shown_rated}개입니다. 진화를 시작하려면 {MIN_RATED_FOR_EVOLUTION}개 이상 필요합니다.', 'library', '조합 더 만들기')
        elif finals:
            step = 4
            todo = ('최종 그림체를 정했습니다. 다른 그림체를 더 다듬거나 진화를 이어 갈 수도 있습니다.', 'refine', '완성한 그림체 보기')
        else:
            step = 2
            sel = self.selection
            if sel['candidate_ids']:
                if self._selection_done():
                    todo = ('진화 조합 평가가 끝났습니다. 세대를 확정하세요.', 'evolution', '세대 확정')
                else:
                    todo = (f"{sel['generation']}세대 진화 조합을 평가하세요.", 'arena', '선별하기')
            elif self.boundary_tie():
                todo = ('상위 30% 경계에서 점수가 같은 조합이 생겼습니다. 선별에서 먼저 가려 주세요.', 'arena', '선별하기')
            elif self._converged():
                step = 3  # evolution has run its course: the stepper and home move on to refine
                todo =(f'{CONVERGED_GENERATIONS}세대 연속으로 살아남은 진화 조합이 없습니다. 이제 다듬기로 넘어가 보세요.', 'refine', '다듬기 시작')
            else:
                todo = (f"상위 30% 조합을 섞어 {sel['generation']}세대 진화 조합을 만드세요.", 'evolution', '진화 시작')
        params = {'focus': 'connection' if not checklist['connection'] else 'prompts'} if todo[1] == 'settings' else {}
        return {'step': step, 'names': STAGES, 'todo': todo[0], 'route': todo[1], 'action': todo[2], 'params': params,
                'checklist': checklist}

    def status(self, since=0):
        with self.lock:
            tie = self.boundary_tie()
            rated, waiting = self.ranking_counts()
            return {
                'stage': self.stage(), 'job': self.job_view(), 'events': self.events_since(since),
                'counts': {'active': len(self.combos), 'rated': rated, 'newcomers': waiting,
                           'excluded': len(self.retired), 'artists': len(self.state['artists']), 'loras': len(self.state['loras']),
                           'generation': self.selection['generation'],
                           # ponytail: walks the whole history each poll (~0.2 ms per 4,000 votes); a counter if it ever shows
                           'votes': sum(1 for h in self.state['history'] if h.get('type') in
                                        ('arena', 'selection_vote', 'place_vote', 'improve_vote'))},
                'tie': bool(tie), 'connection': self.connection_view(),
                # Changes whenever anything /api/settings returns changes (a save here, a seed picked by a
                # generation, a count remembered by a start, a reset or import): the page refetches then.
                'settings_rev': zlib.crc32(json.dumps(self.settings_payload(), sort_keys=True).encode()),
                'improve': (self.state.get('improve') or {}).get('status'),
                'tune': (self.state.get('tune') or {}).get('status'),
            }
```
