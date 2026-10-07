# Comfy Home Server 기획 결정사항

이 문서는 구현 전에 합의한 MVP 범위와 운영 원칙을 기록합니다. 아래의 **확정 사항**과 **추가로 정할 사항**을 구분합니다.

## 목적과 화면

- 집에서 실행하는 웹 서버를 통해 ComfyUI API에 여러 생성 요청을 제출하고 결과물을 확인합니다.
- 데스크톱과 mobile 모두 웹 브라우저로 접속합니다. 별도 desktop GUI 실행 파일은 MVP에 포함하지 않습니다.
- 데스크톱 화면은 Prompt·상황·Batch·결과물 관리 중심으로, mobile 화면은 요청·진행 상태·결과 확인 중심으로 구성합니다. 같은 웹 앱에서 화면 크기에 맞춰 표시합니다.
- 앱의 기본 포트는 **8388**입니다. 외부 접속을 위한 포트포워딩은 사용자가 설정합니다.

## ComfyUI와 앱의 경계

- 기존 ComfyUI의 설정, 기동 스크립트, 8188 서버, 접속 방식은 변경하지 않습니다.
- 앱은 설정된 ComfyUI API endpoint로 요청을 보냅니다. 현재 예시는 `http://127.0.0.1:8188`입니다.
- ComfyUI의 `--base-directory`는 앱 데이터 저장소가 아닙니다. 앱이 생성된 결과물의 위치를 찾는 데에만 참고합니다.
- 앱 설정, Prompt, 상황 정의, 작업 기록, workflow 원본은 프로젝트 내부에서 관리합니다.
- `old_codes/`와 기존 `data/` 구성은 참고 자료입니다. 구현 시 필요한 파일을 옮기거나 사용하지 않는 파일을 정리할 수 있습니다.

## 지원 workflow

MVP에서 지원하는 workflow는 다음 두 가지입니다.

1. `DasiwaMinimaxH3`: 이미지별 upload, Prompt·해상도·길이·upscale 설정을 반영해 video 생성. `old_codes/run_fl2va_v4.py`가 기존 동작의 참고 자료입니다.
2. `AnimaTurboV9`: Prompt wildcard, 해상도·sampling 설정, 선택한 LoRA를 반영해 image 생성.

두 workflow의 API/UI JSON은 현재 `data/workflows/`에 있습니다. 범용 workflow 등록 기능은 MVP 범위에서 제외합니다. Workflow별로 필요한 입력 변환은 별도 adapter가 담당합니다.

## 모델별 Prompt 입력

- Prompt를 저장·불러오기하고 버전을 관리합니다.
- MiniMax H3는 영상 전용 Prompt를 평문으로 입력합니다. wildcard와 상황 builder는 적용하지 않고, 한 Batch의 모든 입력 이미지에 같은 문구를 그대로 전달합니다. 추후 structured 입력을 별도로 설계합니다.
- Anima의 **상황 하나**는 `캐릭터 구성 / 상황 표현 / 필요한 경우의 세부 동작 / 표정·감정선`의 묶음입니다. 장소는 선택 항목입니다.
- Anima에서는 GUI의 checkbox로 이번 Batch에 사용할 상황을 선택합니다. 여러 상황을 선택하면 요청별로 그중 **한 상황**을 무작위로 고릅니다.
- Anima의 각 상황 내부 선택지와 상황 간 선택을 중첩 wildcard로 조립합니다. 긴 최종 문구는 앱이 생성하고, 제출 전 미리보기를 제공합니다.
- Anima의 `sample_prompt.txt`는 wildcard 작성 형식을 파악하기 위한 샘플입니다. 샘플의 소재를 앱의 고정 기능으로 취급하지 않습니다.
- Anima는 요청별 상황·최종 Prompt·random seed를, MiniMax는 입력한 평문을 기록해 생성 조건을 확인할 수 있게 합니다.

## LoRA

- 선택 가능한 파일은 ComfyUI의 모델 목록 API를 조회해 인식합니다. 새로고침과 제출 전 존재 여부 확인을 제공합니다.
- 새 파일이 발견되어도 자동 적용하지 않습니다. 호환 workflow와 기본 강도 등은 앱에서 사용자가 지정합니다.
- Anima는 `Lora Loader (LoraManager)`의 `loras` 입력에 활성 항목과 model/CLIP strength를 전달합니다. 기존 `text` 입력만 바꾸는 방식에 의존하지 않습니다.
- MiniMax H3는 `DaSiWa_LTX2LoraLoader`의 `stack_data`에 LoRA와 STR·video·audio 배율을 반영합니다.
- 요청에 실제 적용한 LoRA 파일명과 강도를 작업 기록에 남깁니다.
- `LoRA 조합` 화면에서 workflow별 파일 목록과 각 weight를 preset으로 저장·편집·복제·삭제합니다. 개별 LoRA 기본 강도와 독립된 snapshot으로 저장합니다.
- 생성 화면에서는 preset을 카드에 복사해 편집하거나 직접 구성합니다. 원본과 다른 조합은 `수정됨`으로 표시하며 새 preset으로 저장할 수 있습니다. 기존 preset 갱신은 관리 화면에서 명시적으로 수행합니다.
- 조합 관리의 Workflow 변경은 새 조합으로 초기화하며, 생성 시에는 현재 workflow에 맞는 preset만 선택합니다. Anima는 STR·CLIP, MiniMax는 STR·V×·A×를 보관합니다.
- 저장된 조합은 ComfyUI 연결 없이도 관리합니다. 없어진 파일을 불러와도 카드에서 제거하지 않고 표시하며, 제출 전 현재 LoRA 목록으로 검증합니다.

## 결과물과 폴더 관리

- 앱이 생성한 결과물은 `C:\Users\azzib\Desktop\ComfyUI\common\output\from_home_server` 아래에 처음부터 저장합니다.
- 앱의 결과물 조회 및 폴더 이동 범위도 이 폴더 **내부로 제한**합니다. ComfyUI 웹에서 직접 만든 결과물과 구분합니다.
- **두 workflow의 폴더 구조와 파일 이름 규칙을 통일**합니다. 경로에서 어떤 workflow로 생성했는지만 구분되면 됩니다.
- 기본 규칙은 `from_home_server/{workflow}/{YYMMDD_HHmmss}_{seed}.{확장자}`입니다. `workflow`는 `anima` 또는 `minimax_h3`로 구분합니다. ComfyUI Saver 실행 시점의 로컬 시간을 사용하며, 영상은 encoding 시작 직전입니다. Saver 자체의 counter나 `_audio` 접미사는 그대로 유지하며 파일명 후처리는 하지 않습니다. 상위 `job_id`와 하위 `request_id`는 작업 기록에 보관합니다. 기존 폴더의 결과물은 그대로 조회합니다.
- Anima의 `Image Saver Simple`에는 `%time_%seed`와 `time_format=%y%m%d_%H%M%S`, MiniMax Saver에는 `%date:yyMMdd_HHmmss%_%seed%`를 전달합니다. MiniMax의 `DaSiWa_SeedControl` 출력을 sampling과 Saver에 함께 연결합니다. 두 node의 내부 저장 방식 차이는 workflow adapter가 처리합니다.
- 결과물 목록의 기준은 파일 시스템의 **현재 상태**입니다. 앱 시작 시 읽고 사용자가 새로고침할 수 있습니다.
- 요청 완료 시 ComfyUI history의 실제 출력 참조를 하위 요청에 보관합니다. 작업 결과 보기에서는 하위 요청의 출력 참조를 합쳐 현재 파일 시스템에 남은 결과를 조회합니다. 결과물 파일 경로를 지속적으로 추적하거나 이동 후 DB 경로를 갱신하지 않습니다. Windows Explorer에서 직접 이동·삭제한 내용도 다음 전체 결과물 조회에 반영합니다.
- 앱 전용 휴지통은 두지 않습니다. 완료된 작업은 이력만 삭제하거나 이력과 원래 생성 위치에 남은 결과물을 함께 삭제할 수 있습니다. 이동·삭제되어 원래 위치에 없는 파일은 로그에 남기고 건너뜁니다. 앱에서 폴더 이동은 허용하며, 이동 후 ComfyUI 웹의 기존 결과물 참조가 깨져도 괜찮습니다.
- 원본 입력 파일을 재실행용으로 따로 보관하지 않습니다. 생성물에 포함된 metadata를 ComfyUI로 drag and drop해 재실행할 수 있음을 확인했습니다. 앱을 통한 재현 기능은 MVP 이후 사용 경험을 보고 결정합니다.

## Batch와 작업 상태

- 앱은 각 요청을 ComfyUI queue에 제출하고 `/prompt` 응답의 `prompt_id`로 접수 여부를 확인합니다.
- Anima의 요청 횟수 N은 N개의 독립된 ComfyUI 요청을 의미합니다. 각 요청은 상황·wildcard·random seed를 별도로 선택하며, workflow 내부 생성 수는 항상 1입니다. 앱에서 batch size를 설정하지 않습니다.
- 생성 화면에서 한 번 제출할 때 선택적인 한 줄 설명, 상위 작업 하나와 요청 횟수만큼의 하위 요청을 기록합니다. 각 요청은 독립적인 ComfyUI `prompt_id`·상태를 가지며, 상위 작업은 완료·실패·취소 건수로 진행 상태를 계산합니다. 일부만 완료된 작업도 완료된 결과부터 조회할 수 있습니다. 작업 목록은 10건씩 페이지네이션합니다.
- 활성 작업이 있을 때 서버가 약 **1초 간격**으로 상태를 조회합니다. 브라우저를 닫아도 조회를 계속합니다. 앱에서는 요청한 작업의 접수·대기·실행·완료·실패 상태를 제공합니다. 대기·실행 중인 요청은 개별 또는 상위 작업 단위로 취소합니다.
- ComfyUI가 Batch의 queue와 실행 순서를 관리합니다. 앱은 재시작 후 미완료 요청을 자동 재제출하지 않습니다.
- 이미 접수된 요청을 확인할 수 있도록 최소한의 `prompt_id`와 제출 기록은 프로젝트 내부에 남깁니다. 재시작 후 조회는 가능하되 자동 재실행하지 않습니다.
- Mobile에서 업로드한 입력은 실행을 위해 일시적으로 다룰 수 있지만, 재실행용 원본 보관 기능은 만들지 않습니다.
- 앱의 임시 upload 파일은 해당 Batch 제출이 끝나면 제거합니다. 비정상 종료로 남은 파일은 다음 실행 시 오래된 파일을 정리합니다.
- 작업 계층 DB 전환 때 기존 요청 단위 작업 기록은 한 번 폐기합니다. Prompt preset·버전과 LoRA 기본값·조합 preset, 생성물 파일은 보존합니다.

## 인증과 접속

- 앱의 기본 비밀번호는 `bibunbibun`이며, 프로젝트 내부 설정 파일에 **평문**으로 저장합니다.
- 앱의 웹 페이지, API, 결과물 조회에 비밀번호 인증을 적용합니다. 로그인 상태는 서버 측 session으로 유지합니다.
- HTTPS는 MVP 이후로 미룹니다. 따라서 외부에서 HTTP로 접속하면 비밀번호와 통신 내용이 암호화되지 않습니다.
- 인증과 포트 설정은 **새 앱에만** 적용합니다. 기존 ComfyUI 서버는 변경하지 않습니다.

## 추가로 정할 사항

실행 중인 요청도 현재 ComfyUI의 특정 `prompt_id` 취소 API로 중단합니다.

두 workflow의 지정 하위 폴더 저장과 결과 조회는 2026-10-06 실요청으로 확인했습니다. MiniMax video saver는 단일 WebM에 `_00001_audio` 접미사를 붙여 저장했습니다.
