# Source Snapshot: tests_web/test_lora_reporting.py

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\tests_web\test_lora_reporting.py`
- Original Byte SHA-256: `88d2b5b4c2ff42b47efecb8f1ce9a2cb795804beb3d14bafa9f457a0e220f749`
- Snapshot Text SHA-256: `88d2b5b4c2ff42b47efecb8f1ce9a2cb795804beb3d14bafa9f457a0e220f749`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```python
"""실제 생성 없이 LoRA 경고 분류·보존·중복 방지를 검증합니다."""

import json
from pathlib import Path
import tempfile
import unittest

from fixtures import core, create_fixture_engine


def report_for_messages(messages, previous_entries=None):
    """Console 메시지를 고유한 시각의 ComfyUI Log Entry로 바꿉니다."""
    entries = []
    for message_index, message in enumerate(messages):
        entries.append({'t': message_index + 100, 'm': message})
    return core.lora_load_report(previous_entries or [], entries)


class LoraReportingTests(unittest.TestCase):
    """격리된 데이터에서 실제 문제와 의도적인 미적용을 구분합니다."""

    def setUp(self):
        """실제 서버와 연결되지 않는 임시 Engine을 준비합니다."""
        self.temporary_directory = tempfile.TemporaryDirectory(prefix='style-lab-lora-report-')
        self.data_directory = Path(self.temporary_directory.name)
        self.engine = create_fixture_engine(self.data_directory)
        self.engine.state['loras'] = [{'tag': 'lora:sample.safetensors'}]
        self.engine.events.clear()

    def tearDown(self):
        """테스트 자료만 정리합니다."""
        self.temporary_directory.cleanup()

    def apply_report(self, report, names=None):
        """선택한 LoRA 조합의 생성 후 보고를 실행합니다."""
        self.engine._lora_report(names or ['sample.safetensors'], 'test-style', 42, report)

    def test_components_are_classified_before_sample_truncation(self):
        """앞의 TE 예시 8개 때문에 뒤의 실제 모델 문제가 숨겨지지 않아야 합니다."""
        messages = []
        for layer_index in range(12):
            messages.append(f'lora key not loaded: lora_te1_layers_{layer_index}_mlp.lora_up.weight')
        messages += ['lora key not loaded: lora_unet_blocks_0_mlp.lora_up.weight',
                     'lora key not loaded: unfamiliar.tensor', 'NOT LOADED diffusion_model.blocks.1.weight']
        report = report_for_messages(messages)
        self.assertEqual(report['count'], 15)
        self.assertEqual(report['components']['text_encoder']['count'], 12)
        self.assertEqual(report['components']['model']['count'], 2)
        self.assertEqual(report['components']['unknown']['count'], 1)
        self.apply_report(report)
        failure = self.engine.state['loras'][0]['load_failed']
        self.assertEqual(failure['keys'], 3)
        self.assertIn('lora_unet_blocks_0_mlp.lora_up.weight', failure['sample'])
        self.assertEqual(len(self.engine.events), 1)

    def test_expected_encoder_omission_is_logged_without_warning(self):
        """Model Only의 TE 미적용은 상태와 Log에 남고 실패 경고는 없어야 합니다."""
        workflow_before = self.engine.workflow_file.read_bytes()
        settings_before = self.engine.settings()
        report = report_for_messages(['lora key not loaded: lora_te1_layers_0_mlp.lora_up.weight'])
        self.apply_report(report)
        self.assertFalse(self.engine.events)
        self.assertNotIn('load_failed', self.engine.state['loras'][0])
        self.assertEqual(self.engine.lora_loading_notice()['counts']['text_encoder'], 1)
        self.assertEqual(self.engine.state['loras'][0]['load_notice']['counts']['text_encoder'], 1)
        saved_state = json.loads(self.engine.state_file.read_text(encoding='utf-8'))
        self.assertFalse(saved_state['lora_loading_notice']['has_warning'])
        warning_log = (self.data_directory / 'lora_warnings.log').read_text(encoding='utf-8')
        self.assertIn('LoRA 적용 안내', warning_log)
        self.assertIn('Layer 수가 아닙니다', warning_log)
        self.assertEqual(self.engine.settings(), settings_before)
        self.assertEqual(self.engine.workflow_file.read_bytes(), workflow_before)

    def test_enabled_encoder_omission_remains_a_warning(self):
        """TE도 적용하도록 설정한 경우에는 같은 Key 누락을 경고해야 합니다."""
        self.engine.state['ui_state']['lora_clip'] = True
        self.apply_report(report_for_messages(['lora key not loaded: text_encoders.qwen3_06b.transformer.model.layers.0.weight']))
        self.assertEqual(len(self.engine.events), 1)
        self.assertEqual(self.engine.state['loras'][0]['load_failed']['components'], ['text_encoder'])

    def test_mixed_combinations_deduplicate_by_problem_kind(self):
        """조합 변경은 같은 경고를 반복하지 않지만 새로운 종류의 문제는 알립니다."""
        model_report = report_for_messages(['lora key not loaded: lora_unet_blocks_0_mlp.lora_up.weight'])
        self.apply_report(model_report, ['first.safetensors', 'second.safetensors'])
        self.apply_report(model_report, ['first.safetensors', 'third.safetensors'])
        self.assertEqual(len(self.engine.events), 1)
        self.assertNotIn('first.safetensors', self.engine.events[0]['text'])
        unknown_report = report_for_messages(['lora key not loaded: unfamiliar.tensor'])
        self.apply_report(unknown_report, ['first.safetensors', 'third.safetensors'])
        self.assertEqual(len(self.engine.events), 2)
        self.assertTrue(self.engine.lora_loading_notice()['has_warning'])

    def test_single_files_keep_separate_warning_identities(self):
        """개별 파일의 실제 문제는 다른 파일의 이전 경고에 가려지지 않아야 합니다."""
        report = report_for_messages(['lora key not loaded: lora_unet_blocks_0_mlp.lora_up.weight'])
        self.apply_report(report, ['first.safetensors'])
        self.apply_report(report, ['second.safetensors'])
        self.assertEqual(len(self.engine.events), 2)

    def test_patch_errors_are_not_suppressed_by_model_only(self):
        """Shape 불일치와 Patch 실패는 누락 Key가 없어도 경고해야 합니다."""
        for message in ['WARNING SHAPE MISMATCH diffusion_model.blocks.0.weight WEIGHT NOT MERGED',
                        'Calculate Weight Failed: lora diffusion_model.blocks.0.weight',
                        'patch type not recognized invalid diffusion_model.blocks.0.weight']:
            with self.subTest(message=message):
                self.engine.events.clear()
                self.engine._warned_lora_problems.clear()
                self.apply_report(report_for_messages([message]))
                self.assertEqual(len(self.engine.events), 1)
                self.assertEqual(self.engine.state['loras'][0]['load_failed']['components'], ['patch'])

    def test_truncated_encoder_log_does_not_clear_previous_failure(self):
        """잘린 Log에서는 TE 경고만 보여도 이전 모델 문제 해결을 단정하지 않습니다."""
        self.engine.state['loras'][0]['load_failed'] = {'keys': 1, 'sample': ['lora_unet_blocks_0.weight']}
        messages = ['lora key not loaded: lora_te1_layers_0_mlp.lora_up.weight'] * 300
        report = report_for_messages(messages)
        self.assertTrue(report['capped'])
        self.apply_report(report)
        self.assertFalse(self.engine.events)
        self.assertIn('load_failed', self.engine.state['loras'][0])
        self.assertTrue(self.engine.lora_loading_notice()['capped'])

    def test_complete_expected_omission_clears_obsolete_failure(self):
        """전체 Log에서 실제 문제 없이 끝난 개별 검사는 이전 실패 표시를 갱신합니다."""
        self.engine.state['loras'][0]['load_failed'] = {'keys': 1, 'sample': ['lora_te1_layers_0.weight']}
        self.apply_report(report_for_messages(['lora key not loaded: lora_te1_layers_0.weight']))
        self.assertNotIn('load_failed', self.engine.state['loras'][0])

    def test_existing_log_entries_are_not_reported_again(self):
        """생성 전에 있던 경고는 이번 LoRA 결과에 포함하지 않습니다."""
        old_entries = [{'t': 1, 'm': 'lora key not loaded: lora_unet_old.weight'}]
        report = core.lora_load_report(old_entries, old_entries + [{'t': 2, 'm': 'finished'}])
        self.assertEqual(report['count'], 0)
        self.assertIsNone(core.lora_load_report(None, []))


if __name__ == '__main__':
    unittest.main()
```
