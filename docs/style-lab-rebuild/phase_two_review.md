# 2단계: 프로젝트 조건으로 실제 이미지 생성

2026-11-10. `/style`에 고정 조합의 실제 생성·결과 조회와 [22번 작업·출력 분리](22_style_job_output_separation_and_project_rename.md)를 연결했습니다. 개발자 검증과 운영 GPU 생성 검증을 마쳤으며, 사용자 결과·사용성 확인을 기다립니다. 다음 단계의 Random 초기 조합·선별·Elo·진화는 추가하지 않았습니다.

## 먼저 확인할 화면

1. Home 상단 **스타일 구성** 또는 `http://localhost:8388/style`로 접속합니다.
2. **테스트 프로젝트 → 그림체**에서 실제로 생성한 A/B 결과를 봅니다. 같은 조합이 Prompt 1·2에 모두 적용되어 있습니다. 선별 화면에서도 현재는 결과 조회만 제공합니다.
3. 이미지 아래 **성분·실제 생성 조건**에서 구성·STR·Seed·해상도·Steps·CFG·확정 Prompt를 확인합니다. 이미지를 누르면 원본을 확대합니다.
4. 추가 확인이 필요하면 **이미지 생성 → 생성 조합 준비**를 누릅니다. 프로젝트에서 허용한 성분만 포함·제외하거나 STR 범위 안에서 바꿀 수 있습니다. 계획 확인은 GPU 생성을 실행하지 않습니다.
5. **생성 계획 확인**에서 조합 수 × Prompt 수와 조건을 확인한 뒤 **N장 이미지 생성**을 누르면 실제 작업을 접수합니다. 단순 저장·화면 이동·새로고침으로 생성하지 않습니다.
6. 일반 **작업**, **결과물**의 **스타일 구성 작업/이미지도 보기** Checkbox를 켜고 꺼 봅니다. 기본은 숨김이며 각 Checkbox의 상태를 해당 Browser에 보존합니다.

이번 사용자 확인은 실제 이미지·Workflow·최소 생성 흐름에 대한 확인입니다. 결과가 평소와 다르거나 조합 편집의 의미가 불분명하면 Random 생성이나 평가를 추가하기 전에 수정합니다. 기존 8389 Style Lab은 변경하지 않았습니다.

## 연결한 동작

- 프로젝트의 저장된 등록 Workflow API/UI Snapshot을 CHS `prepare_anima` Adapter에 전달합니다. Comfy 주소·Port·인증·Queue·완료 감시는 Home과 공유합니다. 현재 등록 Anima 이미지 Workflow가 대상이며 Moss·영상 지원 완료를 뜻하지 않습니다.
- 1~2개 고정 조합을 사용합니다. 초기 입력값은 허용 STR 범위의 1/3·2/3 지점이며 진화 알고리즘이 아닙니다. 둘이 동일하면 한 조합으로 준비합니다. 필요 없는 성분을 제외할 수 있고 프로젝트 설정 자체를 수정하지 않습니다.
- 같은 조합의 성분·STR는 모든 Prompt Case에서 동일합니다. Sampling Seed와 Case별 태그·Wildcard 전개를 고정한 뒤 후보에 공통 적용합니다. `{artist}`는 공통 전개에서 보호했다가 조합별 작가 문자열로 치환하며 슬롯이 없으면 뒤에 추가합니다.
- LoRA는 별도 Loader 입력으로 전달합니다. UI는 STR를 사용하고 별도 CLIP 지정이 없으면 Model STR와 같은 값을 전달합니다. 내부 API의 명시적인 CLIP 0도 보존합니다. Trigger Words 자동 삽입은 일반 CHS Adapter와 같이 비활성입니다.
- 실제 Saver 의존 Node·모델/CLIP/VAE 파일·LoRA 존재를 확인합니다. 미사용 Detector Node는 사전 검사에서 제외합니다. LoRA Manager가 제공하면 Hash·크기·수정 시각과 그 출처를 기록하고 제출 전에 다시 비교합니다. 서버가 파일 바이트를 직접 다시 Hash한 것으로 표시하지 않습니다. 파일 존재 검사만으로 모델 호환성·시각적 효과를 보장하지 않습니다.
- 계획·후보·Case Render를 CHS Job/Request와 연결합니다. 제출 Graph·확정 Prompt·Negative·LoRA·Sampling·소유 ID를 제출 전에 저장하고 PNG Metadata에도 담습니다.
- 동일 Operation의 중복 요청과 이미 제출한 계획의 재제출을 막습니다. 실패·취소가 확인된 최신 Render만 재시도하며 완료 Case·후보 ID는 유지합니다. 접수 여부 미확인은 `stopped`로 남기고 자동 재전송하지 않습니다.
- 프로젝트 생성 Job만 취소합니다. Browser를 닫아도 Home이 완료를 감시하고, 재접속 시 실제 결과를 읽습니다. 실제 실패 Node·오류를 보여주며 TE 미사용만으로 모든 LoRA가 무효라는 경고를 만들지 않습니다.

## 작업·파일과 Rename

작업은 실제 모델 폴더 아래 프로젝트 전용 분류에 배정하고 메모는 `세대001-01 이미지 생성`부터 시작합니다. 현재는 고정 확인 조합이므로 세대는 001이며 이후 생성 Batch는 뒤 순번을 올립니다. 진화로 세대를 진행하는 기능은 후속 단계입니다.

실제 운영 출력 예:

```text
ComfyUI/common/output/from_comfy_home_style/
  anima_turboV11/
    테스트 프로젝트__<project-id>/
      세대001-조합01-Prompt01-<render-id>.png
```

프로젝트 동명이름과 Case 재시도 충돌을 피하기 위해 폴더에 안정적인 Project ID, 파일에 Render ID를 붙입니다. 확장자는 강제 WebP 변환 없이 등록 Workflow의 PNG 설정을 유지합니다.

일반 출력의 기존 상대 경로는 유지합니다. Catalog의 스타일 경로는 `from_comfy_home_style/` 접두사로 두 번째 승인 루트를 해석합니다. Docker에 해당 형제 폴더만 추가 Bind Mount하며 임의의 외부 파일 루트를 열지 않습니다. Media·Preview·History 수집·Sync·즐겨찾기에서도 이 경계를 사용합니다.

기본 숨김은 목록·총건수·페이지·분류 건수·전체 선택·삭제 후보·즐겨찾기·Preview 이전/다음에 같은 서버 필터로 적용합니다. 활성 작업의 감시는 숨김과 관계없이 계속됩니다. 스타일 Job 분류·출력 파일의 수동 이동을 차단하고 일반/스타일 혼합 일괄 이동은 시작 전에 전체 거부합니다. 프로젝트 분류의 개별 Rename·상위 이동·삭제도 막습니다. 스타일 Job 이력은 프로젝트 소유 참조를 보존하기 위해 일반 작업 삭제에서 제외합니다. 프로젝트 삭제 기능은 후속 단계입니다.

출력이 생긴 프로젝트의 웹 Rename은 실제 폴더·자동 분류명·Catalog 현재 경로·Request 출력 참조를 함께 바꿉니다. Output ID·Job ID·메모·최초 경로·불변 Graph/PNG Metadata는 보존합니다. 생성·취소 중에는 Rename을 거부하고, 파일 Rename 뒤 DB 반영 중 중단되면 Journal Operation을 같은 요청 또는 다음 기동에서 재개합니다. 기존 목적 폴더를 덮어쓰지 않습니다.

이미 Render가 있는 프로젝트의 Prompt·Sampling 조건 변경은 아직 지원하지 않습니다. 원본 결과를 다른 조건과 섞지 않도록 후속 Prompt 재시험 단계까지 거절합니다. 이름·메모·향후 조합의 성분 사용 여부·STR 범위는 편집할 수 있습니다.

## 개발자 검증

- Python 전체 회귀 검사: **433 passed, 1 skipped**. 기존 Starlette/httpx Deprecation Warning 1건, Symlink 권한에 따른 Skip 1건.
- 격리 서버의 Browser 검증: 계획 확인 전 미제출, 실제 임시 PNG 2×2 생성, 결과 Polling·확대·새로고침, 일반 화면 Checkbox와 이동 제한. 320/390/768/1280px에서 가로 넘침 없음·Browser Error 없음.
- 기존 프로젝트 Browser 검증: 새 프로젝트·설정 저장·기기 간 조회·초안 보존·Revision 충돌·같은 창 전환 통과.
- API/DB/파일 검사: CLIP 0 보존, Case 공통 전개·Seed, NegPip·PNG Metadata, 중복 접수 방지, 실패 한 Case만 재시도, 잘못된 성분/범위/중복 조합/파일 변경/Node 누락 거절, 사전 확인 연결 실패 502, 미확인 재제출 금지.
- 관리 경계: 실행 중 Rename 거절, 폴더 이동 후 DB 실패를 주입한 복구, Output ID·파일 바이트·메모 보존, 혼합 파일 이동의 전부 거부, 스타일 취소 후 일반 Queue 요청 유지.

## 운영 확인 기록

- 변경 전 DB: Schema 15, Job 184·Request 3,024·Output Catalog 7,735·태그 339·Preset 3·프로젝트 1.
- 백업: `runtime/style-generation-deployment-20261110-154413/before-stage-two.sqlite3`. 정지 직후 사본은 같은 폴더의 `stopped-before-stage-two.sqlite3`, 기존 변경 파일은 `source/`에 보관했습니다. 별도 사본에서 Schema 16 Migration·무결성·Foreign Key·기존 수량/프로젝트 설정 Hash 보존과 Schema 15 백업 복원을 확인했습니다.
- Docker 재생성·Schema 16 Migration 직후 기존 수량과 프로젝트 설정 Hash가 모두 유지됐습니다. 추가한 Host 폴더는 `C:/Users/azzib/Desktop/ComfyUI/common/output/from_comfy_home_style`입니다.
- 사용자 기존 **테스트 프로젝트**에서 두 Prompt·960×1280·Steps 12·CFG 1·Seed 42로 실제 4장 완료. 허용된 Dark Synth·Masoq 두 성분을 각각 A STR 0.6, B STR 0.8로 사용했습니다. 이 검증을 위해 프로젝트 설정·원문 Prompt를 변경하거나 예시 프로젝트를 추가하지 않았습니다.
- 실제 Job: `f1e01769285345499b995844b68c2f8c`. 메모 `세대001-01 이미지 생성`. PNG 4개의 크기·Metadata·LoRA·공통 Seed와 저장 Graph를 대조했습니다. PNG Graph는 Comfy가 추가한 내부 `is_changed` Field를 제외하면 공통 Adapter Graph와 일치합니다. 서로 다른 PNG Hash 네 개는 확인했지만 모든 Runtime에서 같은 픽셀 재현이나 각 LoRA의 개별 효과를 입증한 것으로 해석하지 않습니다.
- 생성 후 Job 185·Request 3,028·Output Catalog 7,739이며 기존 태그·Preset·프로젝트 수와 설정 Hash는 동일합니다. 실제 가용 결과물은 기본 2,446장, 스타일 포함 2,450장입니다. 전체 선택 범위 차이도 4장입니다. Catalog에는 과거 삭제/비가용 행도 있으므로 전체 행 수와 가용 장수는 구분합니다.
- 운영 Browser에서도 네 결과·320/390/768/1280px·재접속·상세 펼치기·일반 화면 기본 숨김/표시·Checkbox 보존·이동 버튼 비활성·원본 다운로드를 확인했습니다. Browser Error 없음.
- 검증 증거는 `runtime/verification/style-generation-phase-two/`에 보관합니다. 사용자가 수정 피드백 전달 전에 현재 구현의 Commit을 요청했습니다. 이번 Commit은 구현 수락이나 다음 단계 진행 승인을 뜻하지 않으며 Push는 하지 않습니다.

사용자 확인 후 다음 단계는 **작은 초기 조합 Batch 생성과 공통 잠금**입니다. 현재 A/B 결과의 품질·조건 일치와 생성 버튼 흐름을 먼저 확인하고 진행합니다.
