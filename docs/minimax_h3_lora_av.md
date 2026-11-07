# Dasiwa MiniMax H3 LoRA AV

MiniMax 생성 요청의 식별자 `minimax_h3`는 유지하고 실행 템플릿을 `data/workflows/DasiwaMinimaxH3LoraAV/DasiwaMinimaxH3LoraAV_api.json`으로 연결합니다. 기존 `data/workflows/DasiwaMinimaxH3/`의 API·UI JSON은 보존합니다.

## 연결과 저장

- 기존 DaSiWa loader 대신 설치된 `H3ModalityLoraLoader`를 사용합니다.
- 이 node의 VIS·AUDIO는 stack 전체에 적용되므로 LoRA 하나당 loader 하나를 직렬로 연결합니다. 선택 순서대로 최대 10개를 적용합니다.
- 선택하지 않은 slot에는 `stack_data=[]`를 전달합니다. Upstream은 빈 stack에서 원래 MODEL을 반환합니다.
- 최종 MODEL을 기존 model consumer 세 곳으로 전달합니다. 새 loader는 CLIP을 반환하지 않으므로 DirectorGuide의 CLIP은 기존 CLIPLoader에서 직접 받습니다. 복원용 UI JSON의 내부 subgraph도 같은 연결을 사용합니다.
- 실행 요청, UI widget 값, loader의 `properties.stack_data`를 함께 갱신합니다. Upstream UI는 복원할 때 properties를 먼저 읽습니다.
- DB의 `lora_profiles.settings_json`, `lora_presets.loras_json`, 작업의 입력 JSON에 기존 `strength`, `video_strength`, `audio_strength` 필드를 계속 저장합니다. Schema 변경은 없습니다. 기존 preset·이력·즐겨찾기의 값도 새 배선에 전달합니다.

## Weight

| 화면 | 전달 위치 | 의미 |
| --- | --- | --- |
| STR | 해당 node의 단일 stack entry `str` | LoRA 전체 강도. 0과 음수도 보존 |
| VIS | 해당 node의 `video` | 영상 행의 직접 LoRA 보정 multiplier, 0~5 |
| AUDIO | 해당 node의 `audio` | 음성 행의 직접 LoRA 보정 multiplier, 0~5 |
| 별도 입력 없음 | `text=1` | Text/refiner multiplier 고정 |

직접 보정은 STR × modality multiplier에 비례합니다. 예를 들어 STR=0.5, VIS=2, AUDIO=0.25이면 영상 직접 보정은 1, 음성 직접 보정은 0.125입니다. Shared attention을 통한 간접 영향까지 분리되는 것은 아닙니다.

기존 DaSiWa Basic 모드는 모든 weight에 STR × VIS를 적용하고 AUDIO를 무시했습니다. 저장된 숫자를 유지하더라도 새 loader로 바꾸면 효과의 의미가 달라집니다.

## 현재 INT8 호환 제약

설치된 loader는 Linear의 `forward` wrapper로 LoRA delta를 더합니다. 현재 로컬 ComfyUI의 H3 MLP는 `linear_input_act(fc2, fc1(x), "swiglu")`를 사용하며, fused INT8/FP16 분기는 `fc2.forward`를 거치지 않습니다. 따라서 이 분기에서는 fc2 LoRA delta가 누락됩니다. VIS·AUDIO가 모두 1이어도 같은 문제입니다.

현재 사용하는 INT8 H3 모델의 backbone `fc2` 50개는 모두 `int8_tensorwise`, ConvRot enabled이며 모델 header에 full-precision 강제 옵션이 없습니다. 다음 LoRA 네 개 모두 이 50개를 대상으로 합니다.

- `H3_Motion_BoosterV2.safetensors`
- `H3_Motion_Booster_anime.safetensors`
- `H3_slop_bounce.safetensors`
- `minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors`

각 파일은 208개 adapter pair를 포함하며 backbone fc2 50개 외에 text refiner fc2 2개도 포함합니다. Refiner는 FP16 fast path 조건이 맞을 때 같은 영향을 받을 수 있습니다. 누락된 pair 수가 전체 효과의 감소 비율을 뜻하지는 않습니다.

기존 DaSiWa loader와 Anima의 LoRA Manager는 ComfyUI의 `load_lora_for_models`를 통해 weight patch를 사용합니다. 이번 forward wrapper 우회 문제와 다릅니다. Anima의 현재 모델 `anima_turboV11.safetensors`와 text encoder `qwen_3_06b_base.safetensors`는 BF16입니다. MiniMax의 Video VAE는 INT8이지만 LoRA MODEL·CLIP 경로에 포함되지 않습니다.

사용자 fork의 `fix/fused-mlp-lora` branch에서 설치된 custom node를 보완했습니다. Native H3 MLP의 실행을 유지하고 fc1의 실제 출력으로 fc2 LoRA delta를 계산해 MLP 출력에 더합니다. Backbone과 text refiner의 fc2를 모두 처리하며, 여러 loader의 보정은 하나의 wrapper에서 합산합니다. ComfyUI core와 모델 파일은 수정하지 않습니다.

2026-10-27 검증에서 CPU 55개와 실제 CUDA kernel 검증 3개가 통과했습니다. CUDA 검증은 작은 native H3 MLP를 사용해 일반·FP16 fused·INT8 ConvRot 경로를 실행했으며, kernel 유지와 AUDIO=0 행의 직접 보정 제외를 확인했습니다. 2026-11-07 사용자가 이 MiniMax 변경의 검증 완료를 확인했습니다.

## 비교 시 고정할 값

동일한 이미지, Prompt, Seed, 해상도, 길이, STR, VIS로 AUDIO만 0 → 0.25 → 0.5 → 1 순서로 바꾸어 비교할 수 있습니다. LoRA 없는 결과도 같은 조건으로 확보하면 baseline 비교에 도움이 됩니다. 수정 이전 upstream loader의 결과는 fc2 보정이 빠질 수 있다는 점을 고려해야 합니다.
