# 등록 Anima Workflow의 Custom Node 의존성

이 표는 현재 설치 디렉터리를 조사한 참고 자료입니다. 새 모델의 의존성 목록은 해당 Workflow에서 별도로 확인해야 합니다. 모델 Tensor·Custom Node Repository 전체는 이 Markdown 묶음에 포함하지 않습니다.

| 설치본 | 관련 역할 | 관측 Git HEAD | 로컬 변경 항목 수 |
| --- | --- | --- | ---: |
| ComfyUI core | UNET/CLIP/VAE Loader, KSampler, Encode/Decode 등 | `73c9bad4d21e7addbe1d13bc92eee0f1431b017d` | 0 |
| comfyui-ppm | CLIPNegPip, Anima용 NegPip 처리 | `확인 불가` | 확인 불가 |
| comfyui-lora-manager | LoRA Loader와 TriggerWord Toggle | `확인 불가` | 확인 불가 |
| comfyui-image-saver | Input Parameters, Image Saver Simple/Metadata | `확인 불가` | 확인 불가 |
| comfyui-impact-pack | ImpactWildcardProcessor, ImpactSwitch, ToDetailerPipe, SAMLoader 등 | `확인 불가` | 확인 불가 |
| comfyui-impact-subpack | UltralyticsDetectorProvider 등 Detector 지원 | `확인 불가` | 확인 불가 |
| comfyui-easy-use | easy int, easy showAnything | `확인 불가` | 확인 불가 |
| ComfyUI-KJNodes | Primitive, StringConcatenate, RegexReplace, WidgetToString 계열 | `d3cfe21625e5170126ce06fbfcfe1d88108688c3` | 1 |

## 복원 시 확인할 것

- 현재 ComfyUI는 별도 Embedded Python 3.13 경로를 사용하고, Style Lab은 3.14 계열입니다. 두 Runtime을 하나로 가정하지 않습니다.
- Git HEAD만 같아도 로컬 변경이 있으면 구현이 같다고 보장할 수 없습니다. 정확한 재현이 필요하면 해당 의존성의 변경분과 모델 Hash를 별도 보존합니다.
- 필요한 Model 파일은 현재 Anima 기준 anima_turboV11, qwen_3_06b_base, qwen_image_vae입니다. 실제 파일은 별도 준비합니다.
- Detector/SAM 관련 Node는 등록 Graph에 있지만 현재 Saver로 이어지는 주요 경로에서 사용되지 않을 수 있습니다. 정의 존재와 실제 실행을 구분합니다.
- 구현 단계에서는 ComfyUI object_info로 등록 Class Type과 필수 입력을 검사하고 누락 Node를 구체적으로 안내합니다.
- Moss는 실제 등록 Workflow와 Adapter를 확인한 뒤 별도 의존성을 기록합니다. 이 Anima 목록을 그대로 복사해 지원한다고 표시하지 않습니다.

## 이번 자료의 복원 경계

이 문서는 Style Lab의 기능과 새 프로젝트 설계를 다시 구현하기 위한 자료입니다. 원래 ComfyUI 설치 전체·모든 모델·기존 생성물까지 복제하는 디스크 Backup이 아닙니다. Home에 기능을 내장하면 현재의 등록 Workflow와 의존성을 공유하는 것이 기본 경로입니다.
