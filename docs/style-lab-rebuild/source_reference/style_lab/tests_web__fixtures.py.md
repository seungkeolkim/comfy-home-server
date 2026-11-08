# Source Snapshot: tests_web/fixtures.py

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\tests_web\fixtures.py`
- Original Byte SHA-256: `94ec73e81ab0c8d98da3a7b60f7d03d39856f01cb6ab103e551f54ce485ebb64`
- Snapshot Text SHA-256: `94ec73e81ab0c8d98da3a7b60f7d03d39856f01cb6ab103e551f54ce485ebb64`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```python
"""실제 ComfyUI와 사용자 데이터를 건드리지 않는 웹 검증용 자료입니다."""

import io
import json
from pathlib import Path
import sys

ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIRECTORY))
import web_server
import core
from engine import Engine
from PIL import Image

TEST_PASSWORD = 'style-lab-test-password-only'


def fixture_image_bytes():
    """노출해도 되는 단색 PNG를 만듭니다."""
    image_stream = io.BytesIO()
    Image.new('RGB', (384, 512), '#819e91').save(image_stream, format='PNG')
    return image_stream.getvalue()


def generate_fixture_image(settings, style, seed, stop_event, log=None):
    """ComfyUI를 호출하지 않고 테스트 이미지만 반환합니다."""
    return fixture_image_bytes()


def fixture_connection(url):
    """웹 화면에 필요한 모델 목록만 반환합니다."""
    return {
        'url': url, 'version': 'test', 'unet_names': ['anima_turboV11.safetensors'],
        'clip_names': ['qwen_3_06b_base.safetensors'], 'vae_names': ['qwen_image_vae.safetensors'],
        'lora_names': ['example.safetensors'], 'samplers': ['er_sde'], 'schedulers': ['simple'],
    }


def create_fixture_engine(data_directory):
    """원본 데이터와 독립적인 비교 조합·이미지·Workflow를 준비합니다."""
    data_directory.mkdir(parents=True, exist_ok=True)
    image_directory = data_directory / 'images'
    image_directory.mkdir(exist_ok=True)
    state = core.empty_state()
    state['ui_state'].update({
        'unet_name': 'anima_turboV11.safetensors', 'clip_name': 'qwen_3_06b_base.safetensors',
        'vae_name': 'qwen_image_vae.safetensors', 'base_prompt': 'masterpiece, garden, {artist}',
        'negative': '', 'cfg': 1.0, 'steps': 12, 'seed': '42', 'sampler': 'er_sde',
        'scheduler': 'simple', 'artists_checked': True, 'prompt_checked': True,
    })
    for combination_index in range(12):
        image_name = f'fixture-{combination_index}.png'
        (image_directory / image_name).write_bytes(fixture_image_bytes())
        state['combinations'].append({
            'id': f'fixture-{combination_index}', 'style': f'1.2::artist:rurudo ::, {0.8 + combination_index * 0.05:.2f}::artist:necomi ::',
            'elo': 10000 + combination_index * 120, 'matches': 4, 'wins': 2, 'placed': True,
            'image_file': image_name, 'seed': 42, 'created': 1700000000 + combination_index,
            'generation': 1,
        })
    (data_directory / 'state.json').write_text(json.dumps(state), encoding='utf-8')
    workflow = core.default_workflow(state['ui_state'])
    workflow['style_lab_negpip'] = {'class_type': 'CLIPNegPip', 'inputs': {'model': ['1', 0], 'clip': ['2', 0]}}
    workflow['4']['inputs']['clip'] = ['style_lab_negpip', 1]
    workflow['5']['inputs']['clip'] = ['style_lab_negpip', 1]
    workflow['7']['inputs']['model'] = ['style_lab_negpip', 0]
    (data_directory / 'workflow.json').write_text(json.dumps(workflow), encoding='utf-8')
    engine = Engine(data_directory, generate=generate_fixture_image, check_connection=fixture_connection)
    engine.check_connection()
    return engine
```
