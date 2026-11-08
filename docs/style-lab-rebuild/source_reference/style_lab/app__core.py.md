# Source Snapshot: app/core.py

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\app\core.py`
- Original Byte SHA-256: `006d1d8f38ef01202db0ce3b933d1ece890f0828495176bc16dd377902ba8c4e`
- Snapshot Text SHA-256: `006d1d8f38ef01202db0ce3b933d1ece890f0828495176bc16dd377902ba8c4e`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```python
"""Pure logic for Anima Style Lab: ComfyUI (Anima) client, style strings, Elo, tiers,
breeding, and the ladder placement used by evolution selection and newcomer placement.

Most of this is carried over unchanged from v3.6 (recovered from the original by 브랙퍼스트).
"""
import bisect
import copy
import http.client
import io
import json
import math
import os
import random
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

COMFY_URL_DEFAULT = 'http://127.0.0.1:8188'

# Anima is trained around 1 megapixel.
SIZE_PRESETS = {'세로 896x1152': (896, 1152), '정방형 1024x1024': (1024, 1024), '가로 1152x896': (1152, 896)}

# Anima's own tag order: quality / meta / safety, subject count, character, series, artist, general tags.
# (The Aesthetic checkpoint advises against score_* tags, so the default leaves them out.)
DEFAULT_NEGATIVE = 'worst quality, low quality, score_1, score_2, score_3, artist name, blurry, jpeg artifacts, chromatic aberration'

DEFAULT_BASE_PROMPT = 'masterpiece, best quality, safe, 1girl, solo, {artist}, standing, simple background, upper body'

# ComfyUI's own lists (used when ComfyUI cannot be asked); the settings screen shows the live ones when connected.
SAMPLERS = ['er_sde', 'euler_ancestral', 'euler', 'dpmpp_2m_sde_gpu', 'dpmpp_2m_sde', 'dpmpp_2m', 'dpmpp_sde_gpu',
            'dpmpp_3m_sde_gpu', 'heun', 'uni_pc', 'ddim', 'euler_cfg_pp', 'euler_ancestral_cfg_pp']
SCHEDULERS = ['simple', 'beta', 'normal', 'karras', 'exponential', 'sgm_uniform', 'ddim_uniform', 'kl_optimal']

# Name order as Windows Explorer sorts it (StrCmpLogicalW: case-insensitive, numbers by value).
DEFAULT_ARTIST_TAGS = [
    'artist:chamooi',
    'artist:channel_(caststation)',
    'artist:cura',
    'artist:for-u',
    'artist:healthyman',
    'artist:hwansang',
    'artist:ke-ta',
    'artist:mignon',
    'artist:mikan03_26',
    'artist:momoko_(momopoco)',
    'artist:muchi_maro',
    'artist:necomi',
    'artist:ningen_mame',
    'artist:omutatsu',
    'artist:onineko',
    'artist:quasarcake',
    'artist:rurudo',
    'artist:shigure_ui',
    'artist:shnva',
    'artist:supernew',
    'artist:torino_aqua',
    'artist:wanke',
    'artist:zain',
]


# Ratings are kept on 10x the usual Elo scale (start 10000, 4000 points = 10x odds, K 320). They stay whole
# numbers, yet ten times finer than on the 1000 scale, where rounding made many combos tie.
RATING_SCALE = 10
START_ELO = 1000 * RATING_SCALE
ELO_K = 32 * RATING_SCALE
PLACE_GAP = 48 * RATING_SCALE  # a newcomer placed below the lowest / above the highest rung

TIER_ORDER = ['S', 'A', 'B', 'C', 'D']

# A bell curve: S 10% · A 20% · B 40% · C 20% · D 10%. S and A (the top 30%) are the evolution parents.
TIER_CUTOFFS = {'S': 0.1, 'A': 0.3, 'B': 0.7, 'C': 0.9, 'D': 1.0}

TIER_MATCH_MULTIPLIER = {'S': 1.0, 'A': 0.9, 'B': 0.6, 'C': 0.3, 'D': 0.1}

ARTIST_TAG_RE = re.compile('artist:[^:,]+')

# A LoRA rides in a combo's style string like an artist, as ``0.8::lora:<file name in ComfyUI> ::``. It never reaches
# the prompt text: it becomes a LoraLoader node in the workflow (fill_workflow).
LORA_PREFIX = 'lora:'

MAX_SEED = 4294967295


class ComfyError(RuntimeError):
    """``fatal``: trying the next image would fail the same way (ComfyUI not running, a model that does not exist)."""
    def __init__(self, message, status=None, fatal=False):
        super().__init__(message)
        self.status = status
        self.fatal = fatal


class Stopped(Exception):
    """The user stopped the job while an image was being drawn."""


# ComfyUI runs on this computer: never through a system proxy.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def comfy_base(url) -> str:
    base = (url or COMFY_URL_DEFAULT).strip().rstrip('/')
    return base if re.match(r'https?://', base) else 'http://' + base


def _error_text(raw: bytes) -> str:
    """ComfyUI's 400 reply: {"error": {...}, "node_errors": {...}} -> one readable line."""
    text = raw[:3000].decode('utf-8', errors='replace')
    try:
        data = json.loads(text)
    except ValueError:
        return text.strip()[:400]
    parts = []
    err = data.get('error') if isinstance(data, dict) else None
    if isinstance(err, dict):
        parts.append(str(err.get('message') or err.get('type') or ''))
    elif err:
        parts.append(str(err))
    for node in (data.get('node_errors') or {}).values() if isinstance(data, dict) else ():
        for item in node.get('errors', []):
            parts.append(f"{node.get('class_type', '')}: {item.get('message', '')} {item.get('details', '')}".strip())
    return ' / '.join(p for p in parts if p)[:600] or text.strip()[:400]


def comfy_call(base, method, path, body=None, timeout=30, raw=False):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method,
                                     headers={'Content-Type': 'application/json'} if data else {})
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        message = _error_text(exc.read())
        raise ComfyError(f'ComfyUI가 요청을 거부했습니다 (HTTP {exc.code}): {message}', exc.code, fatal=exc.code in (400, 404)) from exc
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        raise ComfyError(f'ComfyUI({base})에 연결하지 못했습니다. ComfyUI가 켜져 있는지, 주소가 맞는지 확인해 주세요.', fatal=True) from exc
    if raw:
        return payload
    try:
        return json.loads(payload.decode('utf-8'))
    except ValueError as exc:
        raise ComfyError('ComfyUI의 응답을 읽지 못했습니다.') from exc


def _combo_options(spec):
    """A node input spec from /object_info -> its choices: [[a, b], {...}] (older) or ["COMBO", {"options": [...]}]."""
    if isinstance(spec, list) and spec:
        if isinstance(spec[0], list):
            return [str(x) for x in spec[0]]
        if spec[0] == 'COMBO' and len(spec) > 1 and isinstance(spec[1], dict):
            return [str(x) for x in spec[1].get('options', [])]
    return []


def comfy_check(url):
    """Ask ComfyUI which models it has. Raises ComfyError when it cannot be reached."""
    base = comfy_base(url)
    stats = comfy_call(base, 'GET', '/system_stats', timeout=6)
    wanted = (('UNETLoader', 'unet_name', 'unet_names'), ('CLIPLoader', 'clip_name', 'clip_names'),
              ('VAELoader', 'vae_name', 'vae_names'), ('KSampler', 'sampler_name', 'samplers'),
              ('KSampler', 'scheduler', 'schedulers'), ('LoraLoaderModelOnly', 'lora_name', 'lora_names'))
    out = {'version': ((stats or {}).get('system') or {}).get('comfyui_version') or '', 'url': base}
    for node, field, key in wanted:
        try:
            info = comfy_call(base, 'GET', f'/object_info/{node}', timeout=10)
            out[key] = _combo_options(info[node]['input']['required'][field])
        except (ComfyError, KeyError, TypeError):
            out[key] = []
    return out


def comfy_lora_metadata(url, name):
    """The metadata block of a LoRA file (its safetensors header), asked of ComfyUI. Always a dict: when ComfyUI
    cannot give it, ``{'__error__': why}`` (ComfyUI answers 404 for a file that has no metadata, which is how many
    LoRA trainers save, and for anything that is not .safetensors)."""
    try:
        data = comfy_call(comfy_base(url), 'GET', '/view_metadata/loras?' + urllib.parse.urlencode({'filename': name}), timeout=10)
    except ComfyError as exc:
        return {'__error__': 'ComfyUI에 파일 정보가 없습니다(메타데이터 없이 저장된 LoRA이거나 .safetensors가 아님)' if exc.status == 404 else str(exc)}
    return data if isinstance(data, dict) else {'__error__': 'ComfyUI의 응답을 읽지 못했습니다.'}


def _find_words(obj):
    """Trigger words anywhere in a LoRA Manager answer: a 'trigger_words' / 'trainedWords' list, however deep."""
    if isinstance(obj, dict):
        for key in ('trigger_words', 'trainedWords', 'triggerWords'):
            if isinstance(obj.get(key), list) and obj[key]:
                return [str(x).strip() for x in obj[key] if str(x).strip()]
        for value in obj.values():
            found = _find_words(value)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_words(value)
            if found:
                return found
    return []


def comfy_lora_manager_words(url, name):
    """Trigger words ComfyUI-LoRA-Manager (a custom node, when installed) knows for a LoRA: (words, note). It keeps the
    Civitai 'trained words' of every LoRA and the ones the user typed in its own UI. Its routes have changed between
    versions, so several are tried."""
    base = comfy_base(url)
    stem = re.sub(r'\.(safetensors|ckpt|pt|pth)$', '', name, flags=re.I)
    tried = []
    for stripped in dict.fromkeys((stem, stem.replace('\\', '/'), name)):
        q = urllib.parse.urlencode({'name': stripped})
        for path in ('/api/lm/loras/get-trigger-words?' + q, '/api/loras/get-trigger-words?' + q,
                     '/loras/api/get-trigger-words?' + q, '/api/lm/loras/get-trigger-words/' + urllib.parse.quote(stripped)):
            try:
                answer = comfy_call(base, 'GET', path, timeout=8)
                words = _find_words(answer)
                if not words:
                    tried.append(f'{path.split("?")[0]}: 200 빈 응답 {json.dumps(answer, ensure_ascii=False)[:120]}')
            except ComfyError as exc:
                tried.append(f'{path.split("?")[0]}: {exc.status or exc}')
                continue
            if words:
                return words, ''
    # Fall back on the list route, searching by the file's own name.
    leaf = stem.replace('\\', '/').split('/')[-1]
    for path in ('/api/lm/loras/list?', '/api/loras/list?'):
        try:
            data = comfy_call(base, 'GET', path + urllib.parse.urlencode({'search': leaf, 'page_size': 20, 'page': 1}), timeout=8)
        except ComfyError as exc:
            tried.append(f'{path.rstrip("?")}: {exc.status or exc}')
            continue
        for item in (data.get('items') or []) if isinstance(data, dict) else []:
            file_name = str(item.get('file_name') or '')
            if file_name == leaf or str(item.get('file_path') or '').replace('\\', '/').endswith(stem + '.safetensors'):
                words = _find_words(item)
                if words:
                    return words, ''
    return [], 'LoRA Manager에서 트리거를 받지 못했습니다(' + ('; '.join(tried[:4]) or '등록된 단어 없음') + ')'


# Tags that every training set has: never worth suggesting as a LoRA's trigger word.
GENERIC_TAGS = {'1girl', '1boy', '2girls', 'solo', 'looking at viewer', 'smile', 'blush', 'open mouth', 'simple background',
                'white background', 'long hair', 'short hair', 'breasts', 'multiple girls', 'standing', 'sitting', 'upper body',
                'full body', 'masterpiece', 'best quality', 'highres', 'absurdres', 'safe', 'blue eyes', 'brown hair',
                'black hair', 'blonde hair', 'bangs', 'closed mouth', 'hair ornament', 'ribbon', 'shirt', 'skirt', 'dress'}


def lora_info(meta):
    """What a LoRA file's metadata says: {'trigger': its trigger phrase if it names one, 'candidates': [[tag, count]]
    words that are likely triggers (the training tags that occur most, the training folders' names, its tag list),
    'base': what it was trained on, 'incompatible': True when that is SD1.5 / SDXL, whose LoRAs find nothing to
    attach to in Anima, 'error': why nothing could be read, 'keys': the metadata's key names (for the debug log)}."""
    meta = meta if isinstance(meta, dict) else {}
    error = str(meta.get('__error__') or meta.get('__manager_note__') or '')
    counts = {}

    def parsed(key):
        value = meta.get(key)
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                return None
        return value

    freq = parsed('ss_tag_frequency')
    for tags in (freq.values() if isinstance(freq, dict) else ()):
        for tag, n in (tags.items() if isinstance(tags, dict) else ()):
            if isinstance(n, (int, float)) and str(tag).strip():
                counts[str(tag).strip()] = counts.get(str(tag).strip(), 0) + n
    # kohya's training folders are named "<repeats>_<trigger>": the name is very often the trigger word.
    dirs = parsed('ss_dataset_dirs')
    for folder, info in (dirs.items() if isinstance(dirs, dict) else ()):
        word = re.sub(r'^\d+_', '', str(folder)).strip()
        images = info.get('img_count') if isinstance(info, dict) else None
        if word and word not in counts:
            counts[word] = int(images) if isinstance(images, (int, float)) else 1
    # Some trainers / sites write the words themselves.
    listed = []
    for key in ('modelspec.tags', 'trigger_words', 'trainedWords', 'ss_trigger_words'):
        value = meta.get(key)
        if isinstance(value, str) and value.strip().startswith('['):
            value = parsed(key)
        listed += [str(x).strip() for x in (value if isinstance(value, list) else str(value or '').split(',')) if str(x).strip()]
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    candidates = [[tag, int(n)] for tag, n in ranked if tag.lower().replace('_', ' ') not in GENERIC_TAGS]
    candidates += [[w, 0] for w in dict.fromkeys(listed) if w not in counts]
    base = str(meta.get('ss_base_model_version') or meta.get('modelspec.architecture') or '').strip()
    low = base.lower()
    trigger = str(meta.get('modelspec.trigger_phrase') or '').strip()
    manager = [str(w) for w in (meta.get('__manager__') or [])]
    if manager:  # LoRA Manager's words are the ones the user can see there: first choice
        trigger = trigger or ', '.join(manager)
        candidates = [[w, 0] for w in manager] + [c for c in candidates if c[0] not in manager]
        error = ''
    return {'trigger': trigger, 'candidates': candidates[:12], 'base': base, 'error': error,
            'keys': sorted(k for k in meta if k not in ('__error__', '__manager__')),
            'incompatible': any(k in low for k in ('sdxl', 'stable-diffusion', 'sd_v1', 'sd_v2', 'sd1', 'sd2'))}


def pick_default(names, *hints):
    """The first of ``names`` whose lower-cased name contains one of the hints, in hint order."""
    for hint in hints:
        for name in names:
            if hint in name.lower():
                return name
    return ''


# ---------------------------------------------------------------- prompts: stored style strings -> Anima
def anima_tag(tag: str) -> str:
    """``artist:foo_bar_(baz)`` (as stored) -> ``@foo bar \\(baz\\)``; anything else is left as typed."""
    tag = tag.strip()
    if not tag.startswith('artist:'):
        return tag
    name = tag[len('artist:'):].replace('_', ' ')
    return '@' + re.sub(r'(?<!\\)([()])', r'\\\1', name)


def anima_prompt(text: str) -> str:
    """Stored ``1.2::artist:rurudo ::, 0.9::artist:shigure_ui ::`` (and ``artist:x``) -> ``(@rurudo:1.2), (@shigure ui:0.9)``.
    Text already in Anima's syntax (``@name``, ``(tag:1.2)``) passes through unchanged; a weight group of a
    non-positive weight is dropped (Anima has no negative-weight groups)."""
    pieces, at = [], 0

    def take(chunk, weight):
        for raw in chunk.split(','):
            raw = raw.strip()
            if raw and not raw.startswith(LORA_PREFIX):  # LoRAs go into the workflow, not the prompt
                tag = anima_tag(raw)
                pieces.append(tag if abs(weight - 1) < 1e-9 else f'({tag}:{weight:g})')

    for group in WEIGHT_GROUP_RE.finditer(text):
        take(text[at:group.start()], 1.0)
        if float(group.group(1)) > 0:
            take(group.group(2), float(group.group(1)))
        at = group.end()
    take(text[at:], 1.0)
    return ', '.join(pieces)


def anima_copy(style: str) -> str:
    """A stored style as it is written in Anima for pasting elsewhere: ``(@artist:1.2), ..., <lora:file:0.7>``.
    (The LoRA part is ComfyUI-LoRA-Manager's syntax: the file name without folder and extension.)"""
    text = anima_prompt(style)
    loras = []
    for weight, tag in parse_style_combo(style):
        if tag.startswith(LORA_PREFIX):
            name = tag[len(LORA_PREFIX):].replace('\\', '/').rsplit('/', 1)[-1]
            name = re.sub(r'\.(safetensors|ckpt|pt)$', '', name, flags=re.I)
            loras.append(f'<lora:{name}:{weight:g}>')
    return ', '.join(p for p in (text, ', '.join(loras)) if p)


def build_prompt(base_prompt: str, style_str: str) -> str:
    base, style = base_prompt.strip(), style_str.strip()
    if '{artist}' not in base:
        caption = ', '.join(p for p in (style, base) if p)
    elif style:
        caption = base.replace('{artist}', style)
    else:  # no artist tags (e.g. an empty free prompt): drop the slot without leaving a stray comma
        caption = ', '.join(p.strip() for p in base.replace('{artist}', '').split(',') if p.strip())
    if not caption:
        raise ValueError('프롬프트가 비어 있습니다.')
    return anima_prompt(caption)


# ---------------------------------------------------------------- workflows
def default_workflow(s: dict) -> dict:
    """Plain Anima text-to-image in ComfyUI's standard nodes (UNETLoader + CLIPLoader "stable_diffusion" + VAELoader)."""
    return {
        '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': s['unet_name'], 'weight_dtype': 'default'}},
        '2': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': s['clip_name'], 'type': 'stable_diffusion', 'device': 'default'}},
        '3': {'class_type': 'VAELoader', 'inputs': {'vae_name': s['vae_name']}},
        '4': {'class_type': 'CLIPTextEncode', 'inputs': {'text': '', 'clip': ['2', 0]}},
        '5': {'class_type': 'CLIPTextEncode', 'inputs': {'text': '', 'clip': ['2', 0]}},
        '6': {'class_type': 'EmptyLatentImage', 'inputs': {'width': 1024, 'height': 1024, 'batch_size': 1}},
        '7': {'class_type': 'KSampler', 'inputs': {
            'model': ['1', 0], 'positive': ['4', 0], 'negative': ['5', 0], 'latent_image': ['6', 0], 'seed': 0,
            'steps': 30, 'cfg': 4.5, 'sampler_name': 'er_sde', 'scheduler': 'sgm_uniform', 'denoise': 1.0}},
        '8': {'class_type': 'VAEDecode', 'inputs': {'samples': ['7', 0], 'vae': ['3', 0]}},
        '9': {'class_type': 'PreviewImage', 'inputs': {'images': ['8', 0]}},  # temp folder: nothing piles up in output/
    }


def load_workflow_file(path) -> dict | None:
    """data/workflow.json, saved from ComfyUI with "Save (API Format)"; None when the file is not there."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise ComfyError(f'workflow.json을 읽지 못했습니다: {exc}')
    if isinstance(data, dict) and 'nodes' in data and 'links' in data:
        raise ComfyError('workflow.json이 일반 저장 형식입니다. ComfyUI 메뉴의 "Save (API Format)"(설정에서 Dev mode를 켜면 나옵니다)로 저장한 파일이 필요합니다.')
    if not isinstance(data, dict) or not data or not all(isinstance(n, dict) and 'class_type' in n for n in data.values()):
        raise ComfyError('workflow.json이 ComfyUI API 형식이 아닙니다.')
    return data


def _node_behind(wf, ref, key):
    """Follow a link through the graph until a node that has the input ``key`` as a plain value."""
    seen, stack = set(), [ref]
    while stack:
        ref = stack.pop()
        if not (isinstance(ref, list) and ref):
            continue
        nid = str(ref[0])
        if nid in seen or nid not in wf:
            continue
        seen.add(nid)
        inputs = wf[nid].get('inputs') or {}
        if key in inputs and not isinstance(inputs[key], list):
            return wf[nid]
        stack.extend(v for v in inputs.values() if isinstance(v, list))
    return None


def add_loras(wf: dict, samplers: list, positive_node, negative_node, loras, with_clip: bool):
    """Chain one LoRA loader per ``(file name, weight)`` in front of the sampler's model (and, with ``with_clip``,
    in front of the text encoders' clip), keeping whatever the workflow already does before that point."""
    model_ref = samplers[0]['inputs'].get('model')
    if not (isinstance(model_ref, list) and model_ref):
        raise ComfyError('워크플로의 샘플러에 모델이 연결되어 있지 않아 LoRA를 넣을 수 없습니다.', fatal=True)
    counter = 0

    def chain(model, clip):
        nonlocal counter
        for name, weight in loras:
            counter += 1
            while f'asl_lora_{counter}' in wf:
                counter += 1
            node_id = f'asl_lora_{counter}'
            if clip is None:
                wf[node_id] = {'class_type': 'LoraLoaderModelOnly',
                               'inputs': {'model': model, 'lora_name': name, 'strength_model': weight}}
            else:
                wf[node_id] = {'class_type': 'LoraLoader', 'inputs': {
                    'model': model, 'clip': clip, 'lora_name': name, 'strength_model': weight, 'strength_clip': weight}}
                clip = [node_id, 1]
            model = [node_id, 0]
        return model, clip

    # The encoders to rewire are collected first: the new loaders read the same clip and must not be touched.
    clip_refs = []
    if with_clip:
        for node in (positive_node, negative_node):
            ref = node['inputs'].get('clip')
            if isinstance(ref, list) and ref and ref not in clip_refs:
                clip_refs.append(ref)
    encoders = {i: [n for n in wf.values() if n.get('class_type') == 'CLIPTextEncode'
                    and isinstance(n.get('inputs'), dict) and n['inputs'].get('clip') == ref] for i, ref in enumerate(clip_refs)}
    new_model = None
    for i, ref in enumerate(clip_refs):
        model, clip = chain(model_ref, ref)
        new_model = new_model or model  # one model chain is enough; the others only exist for their clip
        for node in encoders[i]:
            node['inputs']['clip'] = clip
    if new_model is None:
        new_model, _ = chain(model_ref, None)
    for sampler in samplers:
        if sampler['inputs'].get('model') == model_ref:
            sampler['inputs']['model'] = new_model


def fill_workflow(wf: dict, s: dict, positive: str, negative: str, seed: int, loras=()) -> dict:
    """Put this app's prompts, seed, size and sampler settings into a workflow (the built-in one or the user's).
    Blank sampler / scheduler settings leave the workflow's own. ``loras``: [(file name, weight)] to add."""
    wf = copy.deepcopy(wf)
    samplers = [n for n in wf.values() if isinstance(n.get('inputs'), dict)
                and isinstance(n['inputs'].get('positive'), list) and isinstance(n['inputs'].get('negative'), list)]
    if not samplers:
        raise ComfyError('워크플로에서 KSampler(positive·negative 입력이 있는 샘플러)를 찾지 못했습니다.', fatal=True)
    main = samplers[0]['inputs']
    pos, neg = _node_behind(wf, main['positive'], 'text'), _node_behind(wf, main['negative'], 'text')
    if not pos or not neg:
        raise ComfyError('워크플로에서 프롬프트 칸(CLIPTextEncode의 text)을 찾지 못했습니다. 프롬프트 입력에 다른 노드를 연결하지 않은 워크플로가 필요합니다.', fatal=True)
    pos['inputs']['text'], neg['inputs']['text'] = positive, negative
    if loras:
        add_loras(wf, samplers, pos, neg, list(loras), bool(s.get('lora_clip')))
    for sampler in samplers:
        for key in ('seed', 'noise_seed'):
            if key in sampler['inputs'] and not isinstance(sampler['inputs'][key], list):
                sampler['inputs'][key] = seed
    for key, value in (('steps', s['steps']), ('cfg', s['cfg']), ('sampler_name', s['sampler']), ('scheduler', s['scheduler'])):
        if key in main and not isinstance(main[key], list) and value not in ('', None):
            main[key] = value
    latent = _node_behind(wf, main.get('latent_image'), 'width')
    if latent and 'height' in latent['inputs']:
        latent['inputs'].update(width=s['width'], height=s['height'])
        if 'batch_size' in latent['inputs']:
            latent['inputs']['batch_size'] = 1
    return wf


# ComfyUI keeps its last console lines (about 300) and serves them at /internal/logs/raw: {"entries": [{"t", "m"}]}.
LORA_WARN_RE = re.compile(r'lora key not loaded:\s*(\S+)')
LORA_UNAPPLIED_RE = re.compile(r'(?:^|\s)NOT LOADED:?\s+(\S+)')
LORA_PATCH_ERROR_RE = re.compile(r'WARNING SHAPE MISMATCH|Calculate Weight Failed:|patch type not recognized|ERROR.*(?:lora|patch)', re.I)
LORA_LOG_BUFFER = 300  # lines ComfyUI keeps; a report that reaches this is only the tail of the warnings


def comfy_logs(base):
    """ComfyUI's recent console lines [{'t', 'm'}], or None when it does not offer them."""
    try:
        data = comfy_call(base, 'GET', '/internal/logs/raw', timeout=5)
    except ComfyError:
        return None
    entries = data.get('entries') if isinstance(data, dict) else None
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else None


def lora_tensor_component(tensor_key):
    """알려진 Text Encoder·모델 Key만 분류하고 나머지는 미확인으로 남깁니다."""
    if re.match(r'^lora_(?:te\d*|prior_te)_', tensor_key) or tensor_key.startswith(('text_encoders.', 'text_encoder.')):
        return 'text_encoder'
    if tensor_key.startswith(('lora_unet_', 'lycoris_', 'diffusion_model.', 'model.diffusion_model.')):
        return 'model'
    return 'unknown'


def summarize_lora_tensor_keys(tensor_keys):
    """Tensor Key 수와 대표 이름을 집계하며 Layer 수로 해석하지 않습니다."""
    pattern_counts = {}
    for tensor_key in tensor_keys:
        pattern = re.sub(r'\d+', 'N', tensor_key)
        pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
    return {
        'count': len(tensor_keys), 'keys': tensor_keys[:8],
        'groups': sorted(pattern_counts.items(), key=lambda entry: -entry[1])[:14],
    }


def lora_load_report(before, after):
    """새 Console 기록의 Key 누락과 Patch 오류를 구성요소별로 분리합니다."""
    if before is None or after is None:
        return None
    seen = {(str(e.get('t')), e.get('m')) for e in before}
    new = [e for e in after if (str(e.get('t')), e.get('m')) not in seen]
    tensor_keys = []
    patch_errors = []
    for entry in new:
        log_message = str(entry.get('m', ''))
        warning_match = LORA_WARN_RE.search(log_message) or LORA_UNAPPLIED_RE.search(log_message)
        if warning_match:
            tensor_keys.append(warning_match.group(1))
        if LORA_PATCH_ERROR_RE.search(log_message):
            patch_errors.append(log_message.strip())
    component_keys = {'model': [], 'text_encoder': [], 'unknown': []}
    for tensor_key in tensor_keys:
        component_keys[lora_tensor_component(tensor_key)].append(tensor_key)
    report = summarize_lora_tensor_keys(tensor_keys)
    report['components'] = {}
    for component_name, selected_keys in component_keys.items():
        report['components'][component_name] = summarize_lora_tensor_keys(selected_keys)
    report['patch_error_count'] = len(patch_errors)
    report['patch_errors'] = patch_errors[:8]
    # Log가 잘리면 보이지 않는 구간의 성공이나 실패를 단정할 수 없습니다.
    report['capped'] = len(new) >= LORA_LOG_BUFFER - 5
    return report


def generate_style_image(s: dict, style_str: str, seed: int, stop_event, log=None) -> bytes:
    """Draw one image through ComfyUI and return its PNG bytes. ``s``: the engine's generation settings."""
    loras = lora_weights_in_prompt(style_str)
    # A LoRA's trigger words (set when it is registered) join the artists' slot, right after the artists.
    triggers = [t for _, name in loras if (t := (s.get('lora_triggers') or {}).get(name, '').strip())]
    positive = build_prompt(s['base_prompt'], ', '.join([style_str.strip(), *triggers]).strip(', '))
    negative = anima_prompt(s['negative'])
    base_wf = s.get('workflow')
    if base_wf is None:
        if not s.get('unet_name') or not s.get('clip_name') or not s.get('vae_name'):
            raise ComfyError('설정에서 Anima 모델(diffusion model · 텍스트 인코더 · VAE)을 먼저 골라 주세요.', fatal=True)
        base_wf = default_workflow(s)
    wf = fill_workflow(base_wf, s, positive, negative, seed, loras)
    base = comfy_base(s['comfy_url'])
    log_before = comfy_logs(base) if loras and s.get('lora_report') else None
    reply = comfy_call(base, 'POST', '/prompt', {'prompt': wf, 'client_id': uuid.uuid4().hex}, timeout=30)
    prompt_id = reply.get('prompt_id') if isinstance(reply, dict) else None
    if not prompt_id:
        raise ComfyError('ComfyUI가 작업 번호를 돌려주지 않았습니다.')
    deadline = time.monotonic() + 900
    while True:
        if stop_event.is_set():
            try:
                comfy_call(base, 'POST', '/interrupt', {}, timeout=5)
            except ComfyError:
                pass
            raise Stopped()
        if time.monotonic() > deadline:
            raise ComfyError('ComfyUI가 15분 안에 그림을 끝내지 못했습니다.')
        history = comfy_call(base, 'GET', f'/history/{prompt_id}', timeout=15)
        entry = history.get(prompt_id) if isinstance(history, dict) else None
        if entry:
            break
        stop_event.wait(0.6)
    status = entry.get('status') or {}
    if status.get('status_str') == 'error':
        detail = ''
        for kind, data in status.get('messages', []):
            if kind == 'execution_error':
                detail = f"{data.get('node_type', '')}: {data.get('exception_message', '')}".strip()
        raise ComfyError(f'ComfyUI에서 오류가 났습니다. {detail}'.strip(), fatal=True)
    for output in (entry.get('outputs') or {}).values():
        for image in output.get('images', []):
            query = urllib.parse.urlencode({'filename': image['filename'], 'subfolder': image.get('subfolder', ''),
                                            'type': image.get('type', 'output')})
            png = comfy_call(base, 'GET', f'/view?{query}', timeout=60, raw=True)
            if loras and s.get('lora_report') and log_before is not None:
                # 모델용 Key 문제와 의도적인 Text Encoder 미적용을 분리해 기록합니다.
                try:
                    report = lora_load_report(log_before, comfy_logs(base))
                    if report is not None:
                        s['lora_report']([name for name, _ in loras], style_str, seed, report)
                except Exception:
                    pass  # a report must never cost the picture
            return png
    raise ComfyError('ComfyUI가 이미지를 내보내지 않았습니다. 워크플로 끝에 PreviewImage 또는 SaveImage 노드가 있어야 합니다.')


def generate_for_settings(settings, style, seed, stop_event, log=None):
    return generate_style_image(settings, style, seed, stop_event, log)

def default_artists():
    return [{'tag': t, 'count': 0, 'arena_matches': 0, 'arena_wins': 0} for t in DEFAULT_ARTIST_TAGS]

def sanitize_tag(raw: str):
    """``artist:`` + the name as stored: no backslash escapes, underscores for spaces (turned back into Anima's
    ``@name`` with spaces when a picture is drawn).

    ``@absolute (\\queen\\)`` / ``absolute \\(queen\\)`` -> ``artist:absolute_(queen)``.
    """
    name = raw.strip()
    name = name[len('artist:'):] if name.startswith('artist:') else name[1:] if name.startswith('@') else name
    name = '_'.join(name.replace('\\', '').split())
    return f'artist:{name}' if name else None


def _looks_like_number(token: str) -> bool:
    try:
        float(token)
        return True
    except ValueError:
        return False

# A NovelAI weight group, "1.2::tags::" (unclosed, it runs to the end); a negative one pushes its tags away.
WEIGHT_GROUP_RE = re.compile(r'(-?(?:\d+\.?\d*|\.\d+))::(.*?)(?:::|$)', re.S)
PROMPT_ARTIST_RE = re.compile(r'artist:[^:,{}\[\]|\n]+')


# Anima's own syntax: "@name" or "(@name:1.2)"; a name may hold escaped parentheses ("@channel \\(caststation\\)").
ANIMA_ARTIST_RE = re.compile(r'(\(\s*)?@((?:\\[()]|[^,:()\n|@])+?)\s*(?::\s*(-?\d+(?:\.\d+)?)\s*\))?(?=\s*(?:,|\n|\)|$))')


def artist_weights_in_prompt(text: str) -> list:
    """(weight, tag) for the artists of a whole prompt and nothing else (no 1girl, no quality tags). Both
    syntaxes are read: ``artist:name`` inside a "w::...::" group (1 outside one) and Anima's ``@name`` /
    ``(@name:w)``. One with a non-positive weight is left out: it is there to push that style away."""
    # ponytail: {} / [] emphasis (x1.05 per level) is not counted, the weight shows as its group's
    found, at = [], 0

    def take(chunk, weight):
        found.extend((weight, t.strip()) for t in PROMPT_ARTIST_RE.findall(chunk) if t.strip() != 'artist:')

    for group in WEIGHT_GROUP_RE.finditer(text):
        take(text[at:group.start()], 1.0)
        if float(group.group(1)) > 0:
            take(group.group(2), float(group.group(1)))
        at = group.end()
    take(text[at:], 1.0)
    for match in ANIMA_ARTIST_RE.finditer(text):
        weight = float(match.group(3)) if match.group(3) is not None else 1.0
        if weight > 0 and match.group(2).strip():
            found.append((weight, 'artist:' + match.group(2).strip()))
    return found


def lora_weights_in_prompt(text: str) -> list:
    """(file name, weight) for every ``lora:name`` of a prompt, in order: inside a "w::...::" group it takes the
    group's weight, elsewhere 1. Unlike an artist, a LoRA with a weight of 0 or less is kept (it is still loaded)."""
    found, at = [], 0

    def take(chunk, weight):
        for raw in chunk.split(','):
            raw = raw.strip()
            if raw.startswith(LORA_PREFIX) and raw[len(LORA_PREFIX):].strip():
                found.append((raw[len(LORA_PREFIX):].strip(), weight))

    for group in WEIGHT_GROUP_RE.finditer(text):
        take(text[at:group.start()], 1.0)
        take(group.group(2), float(group.group(1)))
        at = group.end()
    take(text[at:], 1.0)
    return found


def artists_in_prompt(text: str) -> list:
    return [tag for _, tag in artist_weights_in_prompt(text)]


def extract_artist_names(raw: str) -> list:
    names = []
    for line in raw.split('\n'):
        for chunk in line.split(','):
            chunk = chunk.strip()
            if not chunk:
                continue
            for token in chunk.split('::'):
                token = token.strip()
                if not token or _looks_like_number(token):
                    continue
                names.append(token)
    return names

def artists_from_style(style_str: str) -> list:
    return [t.strip() for t in ARTIST_TAG_RE.findall(style_str)]

def calc_elo(rating_a, rating_b, a_won, k=ELO_K):
    ea = 1 / (1 + 10 ** ((rating_b - rating_a) / (400 * RATING_SCALE)))
    eb = 1 - ea
    new_a = round(rating_a + k * ((1 if a_won else 0) - ea))
    new_b = round(rating_b + k * ((0 if a_won else 1) - eb))
    return new_a, new_b

def confirm_matches(pool_size: int) -> int:
    """Matches a combo needs before its tier is settled (no longer shown with "?").

    Placement already finds a spot by binary search in about log2(pool) comparisons; a few more games on top
    settle it: 30 combos -> 8, 100 -> 10, 200 -> 11.
    """
    return round(math.log2(max(pool_size, 2))) + 3


def tier_confirmed(matches: int, pool_size: int) -> bool:
    return matches >= confirm_matches(pool_size)

def rank_among(elo, ascending_elos) -> int:
    """Place of ``elo`` among ``ascending_elos`` counted from the top (1 = best); equal Elo share the lower place.
    What tiers and match odds are computed from."""
    return len(ascending_elos) - bisect.bisect_left(ascending_elos, elo)


def tier_for_percentile(percentile: float) -> str:
    return next((letter for letter in TIER_ORDER if percentile <= TIER_CUTOFFS[letter]), TIER_ORDER[-1])


def tier_grade(percentile: float) -> str:
    """Tier with a +/- step for display: each tier's band split in thirds (S+ top third, S, S- bottom third).
    Only for showing; parents, filters and match odds use the plain tier."""
    tier = tier_for_percentile(percentile)
    index = TIER_ORDER.index(tier)
    low = TIER_CUTOFFS[TIER_ORDER[index - 1]] if index else 0.0
    third = (TIER_CUTOFFS[tier] - low) / 3
    position = percentile - low
    return tier + ('+' if position <= third + 1e-12 else '' if position <= 2 * third + 1e-12 else '-')


def is_rated(combo: dict) -> bool:
    """Has a meaningful Elo: played a regular match or was placed on the ladder."""
    return combo.get('matches', 0) >= 1 or bool(combo.get('placed'))


def rank_order(combos):
    """Best first: higher Elo; on equal Elo the better win rate, then more matches, then the older combo.
    The one order behind every #n the app shows."""
    return sorted(combos, key=lambda c: (-c['elo'], -(c['wins'] / c['matches'] if c['matches'] else 0),
                                         -c['matches'], c.get('created', 0), c['id']))


# A tie at the top-30% cut is put to the user only while it is a handful of combos. Placing newcomers gives many of them
# the very same Elo (the rung they landed on), and calling hundreds of pairs one by one would never end: a bigger group is
# ordered by rank_order (win rate, matches, age) instead.
MAX_BOUNDARY_TIE = 6


def top_tier_cut(rated_count: int) -> int:
    """How many rated combos fit in S/A (the top 30%), using the same percentile arithmetic as the tiers."""
    return next((k for k in range(rated_count, -1, -1) if rated_count and k / rated_count <= TIER_CUTOFFS['A']), 0)


def top_tier_ids(combinations, exclude=()):
    """The parents outside a batch: the rated combos currently in S/A, best first."""
    rated = rank_order(c for c in combinations if is_rated(c) and c['id'] not in exclude)
    return [c['id'] for c in rated[:top_tier_cut(len(rated))]]


def boundary_tie_pair(combinations, exclude=(), skipped=()):
    """Two combos whose equal Elo straddles the top-30% boundary, or None.

    ``skipped`` holds ``(frozenset(pair), elo)`` keys the user already called even.
    """
    rated = sorted((c for c in combinations if is_rated(c) and c['id'] not in exclude),
                   key=lambda c: c['elo'], reverse=True)
    cut = top_tier_cut(len(rated))
    if not 0 < cut < len(rated) or rated[cut - 1]['elo'] != rated[cut]['elo']:
        return None
    elo = rated[cut]['elo']
    tied = [c['id'] for c in rated if c['elo'] == elo]
    if len(tied) > MAX_BOUNDARY_TIE:
        return None
    return next(((x, y) for i, x in enumerate(tied) for y in tied[i + 1:]
                 if (frozenset((x, y)), elo) not in skipped), None)


def top_tie_pair(combinations, exclude=(), skipped=()):
    """Two combos inside the top 30% with the same Elo, or None (the boundary tie is boundary_tie_pair's).

    Same ``skipped`` keys as boundary_tie_pair; the best-ranked tie comes first.
    """
    rated = sorted((c for c in combinations if is_rated(c) and c['id'] not in exclude),
                   key=lambda c: c['elo'], reverse=True)
    top = rated[:top_tier_cut(len(rated))]
    return next(((x['id'], y['id']) for i, x in enumerate(top) for y in top[i + 1:]
                 if x['elo'] == y['elo'] and (frozenset((x['id'], y['id'])), x['elo']) not in skipped), None)


def parse_style_combo(style_str: str) -> list:
    items = []
    for chunk in style_str.split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split('::')
        if len(parts) >= 2:
            try:
                w = float(parts[0])
            except ValueError:
                w = 1.0
            tag = parts[1].strip()
            if tag:
                items.append((w, tag))
        elif chunk.startswith('artist:') or chunk.startswith(LORA_PREFIX):
            items.append((1.0, chunk))
    return items


def is_lora(tag: str) -> bool:
    return tag.startswith(LORA_PREFIX)


def split_pairs(pairs):
    """(artist pairs, LoRA pairs) of a combo's (weight, tag) list."""
    return [p for p in pairs if not is_lora(p[1])], [p for p in pairs if is_lora(p[1])]


def lora_tags_from_style(style_str: str) -> list:
    return [tag for _, tag in parse_style_combo(style_str) if is_lora(tag)]


def lora_name(tag: str) -> str:
    """``lora:foo.safetensors`` -> ``foo.safetensors``, the name ComfyUI knows it by."""
    return tag[len(LORA_PREFIX):] if is_lora(tag) else tag


def lora_label(tag: str) -> str:
    """``lora:anima\\style\\foo.safetensors`` -> ``foo`` (display only)."""
    name = tag[len(LORA_PREFIX):] if is_lora(tag) else tag
    name = name.replace('\\', '/').rsplit('/', 1)[-1]
    return name.rsplit('.', 1)[0] if '.' in name else name

# NovelAI weighting: ``1.5::red scarf ::`` — the closing ``::`` always follows a space.
def weighted(weight: float, tag: str) -> str:
    # One decimal as always; a weight between two tenths (a tuned LoRA's 0.65) keeps its second decimal.
    text = f'{weight:.1f}' if abs(weight * 10 - round(weight * 10)) < 1e-6 else f'{weight:.2f}'
    return f'{text}::{tag} ::'


def rename_artist_in_style(style_str: str, old_tag: str, new_tag: str) -> str:
    """Rename one weighted tag (``w::tag ::``) without touching others."""
    return re.sub(r'(?<=::)' + re.escape(old_tag) + r' ?(?=::)',
                  lambda _: new_tag + ' ', style_str)


def style_from_pairs(pairs):
    return ', '.join(weighted(weight, tag) for weight, tag in pairs)


def clamp_weight(weight: float, min_w: float, max_w: float) -> float:
    """Weights are written with one decimal, so clamp on that grid to never print outside the range."""
    low, high = math.ceil(min_w * 10 - 1e-9) / 10, math.floor(max_w * 10 + 1e-9) / 10
    return min(high, max(low, round(weight, 1)))


BREED_MODES = ('mutate', 'crossover', 'random')
BREED_WEIGHTS = (1, 1, 1)  # a third each: crossover mixes lineages, random keeps looking elsewhere
FAVOURITE_BOOST = 2        # the best-scoring artist is drawn this many times as often as an average one
TOP_PARENT_BOOST = 2       # the best parent is picked this many times as often as the lowest one
MUTATE_WEIGHT_JITTER = 0.3


def artist_preference(scores, artist_tags):
    """{tag: draw weight} from artist_scores' {tag: score}: FAVOURITE_BOOST ** (score / best |score|).

    The best artist gets FAVOURITE_BOOST (2x), one scored as far below average gets its inverse (0.5x),
    an artist with no evidence (score 0) stays at 1, so it keeps being tried.
    """
    top = max((abs(scores.get(tag, 0)) for tag in artist_tags), default=0)
    return {tag: FAVOURITE_BOOST ** (scores.get(tag, 0) / top) if top else 1.0 for tag in artist_tags}


def pick_parents(ranked):
    """Two different parents from ``ranked`` (best first); the best is TOP_PARENT_BOOST times as likely as the
    lowest, falling off in a straight line, so every parent keeps a fair chance."""
    n = len(ranked)
    weights = [TOP_PARENT_BOOST - (TOP_PARENT_BOOST - 1) * i / max(n - 1, 1) for i in range(n)]
    first = random.choices(range(n), weights=weights)[0]
    rest = [i for i in range(n) if i != first]
    second = random.choices(rest, weights=[weights[i] for i in rest])[0]
    return ranked[first], ranked[second]


def breed_weighted_style(style_a, style_b, artist_tags, min_tags, max_tags,
                         min_w, max_w, mode='mutate', parent_counts=None, preference=None):
    """Create a child that always stays inside the configured artist count and weight range.

    mutate: parent A with 1-3 artists replaced/removed/added and inherited weights moved by up to
    ±0.3; crossover: artists (with their weights) drawn from both parents; random: a fresh combo.
    Newly drawn artists favour those that few current parents use (``parent_counts``), so one
    popular artist does not take over every lineage, times the user's taste (``preference``,
    from artist_preference). Inherited weights and artist counts outside
    the current settings are pulled back inside them.
    """
    first, second = split_pairs(parse_style_combo(style_a))[0], split_pairs(parse_style_combo(style_b))[0]
    if not first or not second or len(artist_tags) < min_tags:
        raise ValueError('자손 생성에 필요한 부모 또는 작가가 부족합니다.')
    max_tags = min(max_tags, len(artist_tags))
    counts = parent_counts or {}
    liked = preference or {}

    def clamp(weight):
        return clamp_weight(weight, min_w, max_w)

    def fresh(used):
        pool = [tag for tag in artist_tags if tag not in used]
        return random.choices(pool, weights=[liked.get(tag, 1.0) / (1 + counts.get(tag, 0)) for tag in pool])[0]

    if mode == 'random':
        pairs = []
    elif mode == 'crossover':
        inherited = {tag: weight for weight, tag in first}
        inherited.update({tag: weight for weight, tag in second if tag not in inherited})
        pairs = [(clamp(weight), tag) for tag, weight in inherited.items()]
        random.shuffle(pairs)
        pairs = pairs[:random.randint(min_tags, max_tags)]
    else:
        pairs = [(clamp(weight + random.uniform(-MUTATE_WEIGHT_JITTER, MUTATE_WEIGHT_JITTER)), tag)
                 for weight, tag in first]
        random.shuffle(pairs)
        pairs = pairs[:max_tags]
        for _ in range(random.randint(1, 3)):
            used = {tag for _, tag in pairs}
            can_draw = len(used) < len(artist_tags)
            actions = (['replace'] if can_draw and pairs else []) + (['remove'] if len(pairs) > min_tags else []) \
                + (['add'] if can_draw and len(pairs) < max_tags else [])
            if not actions:
                break
            action = random.choice(actions)
            if action == 'replace':
                pairs[random.randrange(len(pairs))] = (clamp(random.uniform(min_w, max_w)), fresh(used))
            elif action == 'remove':
                pairs.pop(random.randrange(len(pairs)))
            else:
                pairs.append((clamp(random.uniform(min_w, max_w)), fresh(used)))
    target = random.randint(min_tags, max_tags) if mode == 'random' else min_tags
    used = {tag for _, tag in pairs}
    while len(pairs) < target:
        tag = fresh(used)
        used.add(tag)
        pairs.append((clamp(random.uniform(min_w, max_w)), tag))
    return style_from_pairs(pairs)


def _batch_votes(selection, history):
    """This batch's entries only (newest first, like history), so ranking never walks every vote ever cast."""
    batch_id = selection.get('batch_id')
    return [vote for vote in history if batch_id and vote.get('batch_id') == batch_id]


def selection_scores(selection, history):
    """Rebuild this batch's scores from votes; parent scores never change."""
    scores = {key: float(value) for key, value in selection.get('parent_scores', {}).items()}
    if not scores:
        return {}, {}
    cutoff = min(scores.values())
    children = set(selection.get('candidate_ids', []))
    scores.update({child_id: cutoff for child_id in children})
    counts = {child_id: 0 for child_id in children}
    for vote in reversed(history):
        if vote.get('type') != 'selection_vote' or vote.get('batch_id') != selection.get('batch_id'):
            continue
        pair = vote.get('pair') or {}
        a_id, b_id = pair.get('a'), pair.get('b')
        if a_id not in scores or b_id not in scores or vote.get('winner_id') not in (a_id, b_id):
            continue
        new_a, new_b = calc_elo(scores[a_id], scores[b_id], vote['winner_id'] == a_id, k=48 * RATING_SCALE)
        if a_id in children:
            scores[a_id] = new_a
            counts[a_id] += 1
        if b_id in children:
            scores[b_id] = new_b
            counts[b_id] += 1
    return scores, counts


def apply_selection_ratings(combinations, selection, history):
    """Mirror this batch into each child's list Elo/record: Elo becomes its placed ladder score.

    Idempotent: each child remembers what it already received (``selection_applied``),
    so only the difference is applied. Regular-league changes made meanwhile are kept.
    """
    batch_id = selection.get('batch_id')
    children = set(selection.get('candidate_ids', []))
    if not batch_id or not children:
        return
    ranking = selection_ranking(selection, history)
    scores, counts = ranking['scores'], ranking['counts']
    wins = {key: 0 for key in children}
    for vote in _batch_votes(selection, history):
        if vote.get('type') == 'selection_vote' and vote.get('winner_id') in wins:
            wins[vote['winner_id']] += 1
    for combo in combinations:
        key = combo['id']
        if key not in children:
            continue
        voted = counts.get(key, 0)
        judged = bool(ranking['info'][key]['votes'])  # "비슷함" places a child too, it just is not a win or loss
        target = {'elo': round(scores[key]) - START_ELO if judged else 0,
                  'matches': voted, 'wins': wins[key] if voted else 0}
        applied = combo.get('selection_applied') or {}
        if applied.get('batch_id') != batch_id:
            applied = {}
        for field, value in target.items():
            combo[field] += value - applied.get(field, 0)
        combo['selection_applied'] = {'batch_id': batch_id, **target}


SELECTION_EXTRA_VOTES = 4  # verification/ambiguity votes a child may get beyond its bisection
SELECTION_CUT_WINDOW = 3   # children ranked this close to the promotion cut get verified


def selection_votes(selection, history):
    """Return the parent ladder (lowest score first) and each child's votes against it.

    Votes are ``(ladder_index, 'win' | 'loss' | 'tie')`` in the order they were cast;
    a skip ("무승부 / 건너뛰기") counts as a tie: the child sits right next to that parent.
    """
    frozen = selection.get('parent_scores', {})
    ladder = sorted((key for key in selection.get('parent_ids', []) if key in frozen),
                    key=lambda key: (frozen[key], key))
    rung = {key: index for index, key in enumerate(ladder)}
    batch_id = selection.get('batch_id')
    votes = {child: [] for child in selection.get('candidate_ids', [])}
    for vote in reversed(history):  # history is newest-first
        if vote.get('batch_id') != batch_id or vote.get('type') not in ('selection_vote', 'selection_skip'):
            continue
        pair = vote.get('pair') or {}
        a_id, b_id = pair.get('a'), pair.get('b')
        if a_id in votes and b_id in rung:
            child, parent = a_id, b_id
        elif b_id in votes and a_id in rung:
            child, parent = b_id, a_id
        else:
            continue
        if vote['type'] == 'selection_skip':
            result = 'tie'
        elif vote.get('winner_id') in (child, parent):
            result = 'win' if vote['winner_id'] == child else 'loss'
        else:
            continue
        votes[child].append((rung[parent], result))
    return ladder, votes


def _bisect(votes, n, climb_ties=False):
    """Slot bounds from the bisection path; slot = number of parents the child ranks above.

    A tie settles the slot next to that parent, unless ``climb_ties``: then the child is at least
    level with it and goes on to face the parent just above (see ``_climb_rung``).
    """
    lo, hi = 0, n
    for k, result in votes:
        if not lo <= k < hi:
            continue  # off-path votes (verification) are judged by _best_slots instead
        if result == 'win':
            lo = k + 1
        elif result == 'loss':
            hi = k
        elif climb_ties:
            lo = k
        else:
            lo, hi = k, k + 1
    return lo, hi


def _climb_rung(votes, hi, tried):
    """After a tie with parent k, the parent just above (k + 1) is asked next, if still open."""
    if votes and votes[-1][1] == 'tie':
        above = votes[-1][0] + 1
        if above < hi and above not in tried:
            return above
    return None


def _best_slots(votes, n):
    """Slots that contradict the fewest of the child's votes (preferences need not be transitive)."""
    def violations(slot):
        return sum(1 for k, result in votes
                   if (result == 'win' and slot <= k) or (result == 'loss' and slot > k)
                   or (result == 'tie' and slot not in (k, k + 1)))
    costs = [violations(slot) for slot in range(n + 1)]
    return [slot for slot, cost in enumerate(costs) if cost == min(costs)]


def _next_rung(lo, hi, tried):
    """Lowest parent first (most children stop there), then bisect the remaining range."""
    open_rungs = [k for k in range(lo, hi) if k not in tried]
    if not open_rungs:
        return None
    target = lo if lo == 0 else (lo + hi) // 2
    return min(open_rungs, key=lambda k: (abs(k - target), k))


def _check_rung(best, slot, tried, n):
    """A parent to re-ask about: inside an ambiguous range first, then 2-3 rungs above and below."""
    if len(best) > 1:
        open_rungs = [k for k in range(best[0], best[-1]) if k not in tried]
        if open_rungs:
            return open_rungs[len(open_rungs) // 2]
    for window in ([k for k in (slot + 1, slot + 2) if k < n], [k for k in (slot - 2, slot - 3) if k >= 0]):
        if window and not tried.intersection(window):
            return window[0]
    return None


def selection_ranking(selection, history):
    """Rank parents and children together and decide which vote, if any, is still needed.

    Returns a dict with ``ladder``, ``info`` (per child: ``slot``, ``rung`` = parent index it
    should face next or None, ``votes``), ``ascending`` (all ids, lowest first), ``scores``
    (order-preserving ladder scores), ``counts`` (decisive votes per child) and ``boundary_pairs``
    (unplayed child pairs sharing the slot that straddles the promotion cut).
    """
    history = _batch_votes(selection, history)
    ladder, votes = selection_votes(selection, history)
    n = len(ladder)
    elo, counts = selection_scores(selection, history)
    info = {}
    for child, child_votes in votes.items():
        tried = {k for k, _ in child_votes}
        lo, hi = _bisect(child_votes, n, climb_ties=True)
        rung = _climb_rung(child_votes, hi, tried)
        if rung is None:
            rung = _next_rung(lo, hi, tried)
        best = [lo] if rung is not None else _best_slots(child_votes, n)
        info[child] = dict(slot=best[(len(best) - 1) // 2], best=best, rung=rung, bisecting=rung is not None,
                           lo=lo, hi=hi, votes=child_votes, tried=tried)

    batch_id = selection.get('batch_id')
    head_to_head, played = {}, set()
    for vote in history:
        pair = vote.get('pair') or {}
        a_id, b_id = pair.get('a'), pair.get('b')
        if vote.get('batch_id') != batch_id or a_id not in info or b_id not in info:
            continue
        played.add(frozenset((a_id, b_id)))
        if vote.get('type') == 'selection_vote' and vote.get('winner_id') in (a_id, b_id):
            head_to_head[vote['winner_id']] = head_to_head.get(vote['winner_id'], 0) + 1

    def arrange():
        slots = {}
        for child, child_info in info.items():
            slots.setdefault(child_info['slot'], []).append(child)
        ordered = []
        for slot in range(n + 1):
            ordered += sorted(slots.get(slot, []), key=lambda key: (head_to_head.get(key, 0), elo.get(key, 0), key))
            if slot < n:
                ordered.append(ladder[slot])
        return slots, ordered

    slots, ascending = arrange()
    if not any(child_info['bisecting'] for child_info in info.values()):
        # Verify only where it can change who is promoted; children stopped by the lowest parent stay at one vote.
        cap = math.ceil(math.log2(n + 1)) + 1 + SELECTION_EXTRA_VOTES
        rank = {key: index for index, key in enumerate(reversed(ascending), 1)}
        for child, child_info in info.items():
            if (child_info['slot'] > 0 and len(child_info['votes']) < cap
                    and n - SELECTION_CUT_WINDOW < rank[child] <= n + SELECTION_CUT_WINDOW):
                child_info['rung'] = _check_rung(child_info['best'], child_info['slot'], child_info['tried'], n)

    frozen = selection.get('parent_scores', {})
    scores = {key: frozen[key] for key in ladder}
    for slot, mates in slots.items():
        # Children sharing a slot differ only where head-to-head votes separated them;
        # otherwise they share the slot's midpoint instead of an arbitrary spread.
        levels = sorted({head_to_head.get(key, 0) for key in mates})
        if ladder:
            low = frozen[ladder[slot - 1]] if slot else frozen[ladder[0]] - PLACE_GAP
            high = frozen[ladder[slot]] if slot < n else frozen[ladder[-1]] + PLACE_GAP // 2 * (len(levels) + 1)
        else:
            low, high = START_ELO, START_ELO + PLACE_GAP // 2 * (len(levels) + 1)
        for key in mates:
            level = levels.index(head_to_head.get(key, 0)) + 1
            scores[key] = round(low + level * (high - low) / (len(levels) + 1))

    boundary_pairs = []
    cut = len(ascending) - n
    if not any(child_info['rung'] is not None for child_info in info.values()) and 0 < cut < len(ascending):
        below, above = ascending[cut - 1], ascending[cut]
        if below in info and above in info and info[below]['slot'] == info[above]['slot']:
            group = slots[info[below]['slot']]
            # ponytail: full round-robin inside the cut slot; fine for the few children that tie there.
            boundary_pairs = [(x, y) for i, x in enumerate(group) for y in group[i + 1:]
                              if frozenset((x, y)) not in played]
    return dict(ladder=ladder, info=info, ascending=ascending, scores=scores, counts=counts,
                boundary_pairs=boundary_pairs)


def selection_next_pair(selection, combinations, history, ranking=None):
    """Next vote: bisect unsettled children, verify those near the cut, then order cut ties.
    ``ranking``: selection_ranking's result, when the caller already has it."""
    by_id = {combo['id']: combo for combo in combinations}
    ranking = ranking or selection_ranking(selection, history)
    ladder = ranking['ladder']
    waiting = [(len(child_info['votes']), child, child_info['rung'])
               for child, child_info in ranking['info'].items()
               if child_info['rung'] is not None and child in by_id and ladder[child_info['rung']] in by_id]
    if waiting:
        _, child, k = min(waiting)
        return by_id[child], by_id[ladder[k]]
    for a_id, b_id in ranking['boundary_pairs']:
        if a_id in by_id and b_id in by_id:
            return by_id[a_id], by_id[b_id]
    return None


def selection_remaining_matches(selection, combinations, history):
    """Estimate remaining votes: bisection left, up to two checks per child, plus cut ties."""
    ranking = selection_ranking(selection, history)
    if not selection_next_pair(selection, combinations, history, ranking):
        return 0, 0
    lower = upper = len(ranking['boundary_pairs'])
    for child_info in ranking['info'].values():
        if child_info['bisecting']:
            lower += 1
            upper += math.ceil(math.log2(child_info['hi'] - child_info['lo'] + 1)) + (child_info['lo'] == 0) + 2
        elif child_info['rung'] is not None:
            lower += 1
            upper += 2
    return max(1, lower), max(1, lower, upper)


# ---------------------------------------------------------------- newcomer placement
# A new combo is binary-searched into the ladder of rated combos (lowest Elo first).
# Unlike evolution selection there is no "gate" at the bottom: start from the middle.

def placement_state(votes, ladder_size):
    """Where a newcomer stands after its votes against ladder rungs.

    ``votes`` are ``(rung_index, 'win' | 'loss' | 'tie')``. Returns ``(slot, next_rung)``;
    ``next_rung`` is None once the slot is settled. slot = number of rungs it ranks above.
    """
    lo, hi = _bisect(votes, ladder_size, climb_ties=True)
    tried = {k for k, _ in votes}
    climb = _climb_rung(votes, hi, tried)  # "비슷함" with rung k: ask the one just above next
    if climb is not None:
        return lo, climb
    open_rungs = [k for k in range(lo, hi) if k not in tried]
    if open_rungs:
        middle = (lo + hi) // 2
        return lo, min(open_rungs, key=lambda k: (abs(k - middle), k))
    best = _best_slots(votes, ladder_size)
    return best[(len(best) - 1) // 2], None


def placement_elo(slot, ladder_scores):
    """Elo for a newcomer placed at ``slot`` among ascending ``ladder_scores``."""
    if not ladder_scores:
        return START_ELO
    if slot <= 0:
        return round(ladder_scores[0] - PLACE_GAP)
    if slot >= len(ladder_scores):
        return round(ladder_scores[-1] + PLACE_GAP)
    return round((ladder_scores[slot - 1] + ladder_scores[slot]) / 2)


# ---------------------------------------------------------------- artist scores

ARTIST_SCORE_PRIOR = 2.0  # combos' worth of evidence (weight 1 each) an artist needs before its score moves far from 0


def artist_scores(combos, sweeps=60):
    """Each artist's share of the combo ratings: {tag: (score, combos it is in)}.

    Fits rating - average ≈ Σ weight × artist score over the rated combos (ridge regression by coordinate
    descent). So artists that often appear together are told apart, a weight of 1.8 counts for more than 0.5,
    and every kind of vote counts (it is all in the combo ratings). An artist with little evidence stays near
    0, the average; the prior pulls it there like ARTIST_SCORE_PRIOR average combos would.
    """
    rows = [(c['elo'], parse_style_combo(c['style'])) for c in combos if is_rated(c)]
    if not rows:
        return {}
    mean = sum(elo for elo, _ in rows) / len(rows)
    residual = [elo - mean for elo, _ in rows]
    uses = {}  # tag -> [(row, weight)]
    for row, (_, pairs) in enumerate(rows):
        for weight, tag in pairs:
            uses.setdefault(tag, []).append((row, weight))
    score = dict.fromkeys(uses, 0.0)
    for _ in range(sweeps):
        for tag, hits in uses.items():
            old = score[tag]
            new = sum(w * (residual[row] + w * old) for row, w in hits) / (sum(w * w for _, w in hits) + ARTIST_SCORE_PRIOR)
            for row, w in hits:
                residual[row] -= w * (new - old)
            score[tag] = new
    return {tag: (round(score[tag]), len(hits)) for tag, hits in uses.items()}


# ---------------------------------------------------------------- LoRAs in combos
# ``registry``: {lora tag: (lowest weight, highest weight)} of the registered LoRAs; each has its own range.
LORA_MUTATE_WEIGHT_JITTER = 0.2


def random_lora_pairs(registry, min_n, max_n, used=()):
    """A fresh random pick: between min_n and max_n registered LoRAs (as many as exist, at most), each with a
    weight drawn from its own range."""
    pool = [tag for tag in registry if tag not in used]
    count = random.randint(min(min_n, len(pool)), min(max_n, len(pool)))
    return [(clamp_weight(random.uniform(*registry[tag]), *registry[tag]), tag) for tag in random.sample(pool, count)]


def breed_loras(style_a, style_b, registry, min_n, max_n, mode='mutate'):
    """The LoRA part of a child, ``mode`` being the one picked for its artists: mutate keeps parent A's LoRAs with
    their weights moved a little and maybe swaps / drops / adds one; crossover draws from both parents' LoRAs;
    random starts over. Only registered LoRAs are passed on, always within the count and each one's range."""
    if not registry:
        return []
    max_n = min(max_n, len(registry))
    min_n = min(min_n, max_n)
    first = [p for p in split_pairs(parse_style_combo(style_a))[1] if p[1] in registry]
    second = [p for p in split_pairs(parse_style_combo(style_b))[1] if p[1] in registry]

    def clamp(weight, tag):
        return clamp_weight(weight, *registry[tag])

    def fresh(used):
        tag = random.choice([t for t in registry if t not in used])
        return clamp(random.uniform(*registry[tag]), tag), tag

    if mode == 'random':
        return random_lora_pairs(registry, min_n, max_n)
    if mode == 'crossover':
        inherited = {tag: weight for weight, tag in first}
        inherited.update({tag: weight for weight, tag in second if tag not in inherited})
        pairs = [(clamp(weight, tag), tag) for tag, weight in inherited.items()]
        random.shuffle(pairs)
        pairs = pairs[:random.randint(min_n, max_n)]
    else:
        pairs = [(clamp(weight + random.uniform(-LORA_MUTATE_WEIGHT_JITTER, LORA_MUTATE_WEIGHT_JITTER), tag), tag)
                 for weight, tag in first]
        if random.random() < 0.5:  # most children move a LoRA's weight only; half also change which LoRAs are in
            used = {tag for _, tag in pairs}
            actions = (['replace'] if pairs and len(used) < len(registry) else []) + (['remove'] if len(pairs) > min_n else []) \
                + (['add'] if len(pairs) < max_n and len(used) < len(registry) else [])
            action = random.choice(actions) if actions else None
            if action == 'replace':
                pairs[random.randrange(len(pairs))] = fresh(used)
            elif action == 'remove':
                pairs.pop(random.randrange(len(pairs)))
            elif action == 'add':
                pairs.append(fresh(used))
    pairs = pairs[:max_n]
    while len(pairs) < min_n:
        pairs.append(fresh({tag for _, tag in pairs}))
    return pairs


# ---------------------------------------------------------------- improve workbench

def jitter_weights(pairs, jitter, min_w, max_w, tries=50, bounds=None):
    """Same artists, new weights: every weight moves by up to ±jitter (at least one changes).
    ``bounds``: {tag: (low, high)} for the tags (the LoRAs) that have a range of their own."""
    bounds = bounds or {}

    def clamp(weight, tag):
        return clamp_weight(weight, *bounds.get(tag, (min_w, max_w)))

    for _ in range(tries):
        moved = [(clamp(weight + random.uniform(-jitter, jitter), tag), tag) for weight, tag in pairs]
        if any(new != old for (new, _), (old, _) in zip(moved, pairs)):
            return moved
    index = random.randrange(len(pairs))  # tiny jitter / narrow range: force one visible step
    weight, tag = pairs[index]
    step = 0.1 if clamp(weight + 0.1, tag) != weight else -0.1
    return pairs[:index] + [(clamp(weight + step, tag), tag)] + pairs[index + 1:]


# ---------------------------------------------------------------- storage

# The state.json format. Whenever a release changes it: raise SCHEMA and add UPGRADES[old], which turns a format-old
# state into format old + 1 in place. Data from any older release goes through every step in order.
SCHEMA = 2
UPGRADES = {1: lambda data: data.setdefault('loras', [])}  # 2: registered LoRAs (combos may carry lora: tags)


class NewerDataError(Exception):
    """The data was saved by a newer release (a newer format): this one must not open it, or it would lose
    what it does not know."""


def upgrade_state(data: dict) -> int:
    """Bring a loaded state up to SCHEMA, in place; returns the format it had. Data without a format number is
    format 1 (saved before formats were numbered)."""
    schema = data.get('schema', 1)
    if not isinstance(schema, int) or isinstance(schema, bool) or schema < 1:
        raise ValueError(f'unknown data format: {schema!r}')
    if schema > SCHEMA:
        raise NewerDataError(schema)
    for step in range(schema, SCHEMA):
        UPGRADES[step](data)
    data['schema'] = SCHEMA
    return schema


def empty_state():
    return {'schema': SCHEMA, 'artists': default_artists(), 'loras': [], 'combinations': [], 'history': [], 'ui_state': {},
            'selection': {'generation': 1, 'candidate_ids': [], 'batch_id': None, 'retired': [],
                          'parent_ids': [], 'parent_scores': {}, 'log': []},
            'placement': None, 'improve': None, 'free_results': []}


def load_state(state_file: Path) -> dict:
    """Read state.json; an unreadable file is set aside (never overwritten) and reported.

    Data in an older format is kept as it was (state.schemaN-date.json), then upgraded and saved. Data in a newer
    format raises NewerDataError and is left untouched."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    if not state_file.exists():
        return empty_state()
    try:
        data = json.loads(state_file.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('not a state')
        schema = data.get('schema', 1)
        if not isinstance(schema, int) or isinstance(schema, bool) or schema < 1:
            raise ValueError(f'unknown data format: {schema!r}')
        if schema > SCHEMA:
            raise NewerDataError(schema)
    except NewerDataError:
        raise
    except Exception:
        corrupt = state_file.with_name(f"state.corrupt-{datetime.now():%Y%m%d_%H%M%S}.json")
        state_file.replace(corrupt)
        return {**empty_state(), 'load_error': str(corrupt)}
    # One copy per launch of the last state that loaded fine: a way back if something goes wrong this run.
    shutil.copyfile(state_file, backup_file(state_file))
    if schema < SCHEMA:
        before = state_file.with_name(f'state.schema{schema}-{datetime.now():%Y%m%d_%H%M%S}.json')
        shutil.copyfile(state_file, before)  # kept for good: the way back to the release that wrote it
        upgrade_state(data)
        write_state(state_file, data)
    data['schema'] = SCHEMA
    return data


def backup_file(state_file: Path) -> Path:
    return state_file.with_name(state_file.name + '.bak')


def write_state(state_file: Path, data: dict):
    """Atomically replace the state file so a crash never leaves half-written JSON."""
    text = json.dumps(data, ensure_ascii=False)
    tmp = state_file.with_name(state_file.name + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())  # on disk before the swap, so a power cut cannot leave an empty state.json
    # Antivirus or indexers can hold a just-written file for a moment on Windows; retry briefly.
    for attempt in range(20):
        try:
            os.replace(tmp, state_file)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05 * (attempt + 1))
```
