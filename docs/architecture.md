# 하이브리드 모핑 파이프라인 — 아키텍처

## 0. 배경 및 목적

`[[project_bullettime_direction_conclusion]]` (2026-10-21) 결론: 텍스트 프롬프트만으로
Veo류 생성 모델에 "불릿타임/회전 롱테이크"를 지시하면, 포토리얼+일상 배경 조합에서는
4회 전부 실패했고(타이밍 지시가 사건 자체를 프롬프트에서 밀어내는 패턴까지 확인),
반대로 "오빗형 리빌"(카메라가 돌며 숨은 공간을 드러내는 것)만 재현성 있게 성공했다.

결론의 함의: **프롬프트 텍스트만으로 카메라 궤적을 정밀 제어하는 데는 구조적 한계가
있다.** 따라서 이 프로젝트는 카메라 궤적(위치·회전·시간)을 텍스트가 아니라
**명시적 수치 데이터(JSON)**로 만들어, 생성 엔진에 조건(conditioning)으로 직접
주입하는 쪽으로 전환한다. 목표 연출 4종:

1. **불릿타임(Bullet Time)** — 피사체 시간은 정지/슬로우, 카메라만 궤도 비행
2. **회전 롱테이크(Rotating Long-take)** — 끊김 없이 피사체를 중심으로 선회
3. **연속 롱테이크(Continuous Long-take)** — 컷 없이 공간을 관통하는 긴 이동
4. **예측불가 카메라 루프 비행(Unpredictable Camera Loop Flight)** — 불규칙한
   궤적으로 공간을 자유비행하며 순간순간 새 구도를 드러냄

이 4종의 공통분모는 "카메라의 4차원(x, y, z, t) + 회전/화각 값이 장면 콘텐츠와
독립적으로, 사전에 결정 가능하다"는 것 — 그래서 이걸 코드로 분리해 생성 엔진에
강제로 먹이는 하이브리드 구조가 성립한다.

## 1. 실행 환경 3단 구조

| 단계 | 위치 | 역할 | 비용 |
|---|---|---|---|
| 기획 | 로컬(이 PC) | 시네마토그래피 프롬프트 설계, 카메라 제어값 코딩/수정, 결과 리뷰 | 0원 |
| 저장·버전관리 | GitHub (`stereo-morph-pipeline` 레포) | ComfyUI 워크플로우(JSON)·Blender 스크립트·궤적 생성기 코드의 단일 소스 | 0원 |
| 실행 | Google Colab (무료 GPU) | Blender 헤드리스 렌더(메시+카메라패스), ComfyUI 무거운 생성 연산, 디테일 복원, 최종 출력 | 0원(무료 티어, 쿼터 내) |

로컬은 "생각과 숫자"만 다루고, Colab은 "GPU가 필요한 무거운 작업"만 다룬다.
GitHub는 그 둘을 잇는 유일한 통로 — Colab 노트북 첫 셀이 항상 `git clone`이다.

## 2. 파이프라인 레이어 (요청하신 ①~⑤ 순서)

```
① 입력 레이어        로컬: 대본/샷 의도, 소스 이미지·레퍼런스, 연출 기법 선택
        │
② 제어 레이어        로컬 코딩 → GitHub: 4D 카메라 궤적 JSON (위치·회전·FOV·시간)
        │             control/camera_paths.py 가 궤적 "수식"을, schema.py 가 "포맷"을 정의
        │
③ 생성 엔진          Colab: Blender로 더미 메시+카메라 렌더(depth/normal pass) 생성
        │             → ComfyUI 노드그래프가 그 depth pass를 ControlNet 조건으로 받아
        │               AnimateDiff/SVD 계열 비디오 디퓨전으로 실제 프레임 생성
        │
④ 디테일 복원 레이어   Colab: 얼굴 복원(GFPGAN/CodeFormer) → 업스케일(Real-ESRGAN)
        │             → 프레임 보간(RIFE)으로 매끄러운 모션 확보
        │
⑤ 출력 레이어        Colab: 프레임 시퀀스 → 영상 인코딩(ffmpeg) → Drive 저장
                      → 로컬/yeori-studio 파이프라인으로 다운로드해 후반 합성
```

### 레이어별 "진짜 역할" — 왜 이 순서인가

- **①입력은 ②제어와 분리**해야 한다. 입력(이미지, 톤, 대사)이 바뀌어도 궤적 수식은
  재사용 가능해야 하고, 반대로 같은 궤적을 여러 입력에 적용해 테스트해야 하기 때문.
- **②제어 레이어가 이 아키텍처의 핵심**이다. 기존 Veo 프롬프트 방식은 ①과 ②가
  뒤섞여서(자연어 한 덩어리) 타이밍이 깨졌다. 여기서는 카메라 값이 숫자 배열로
  고정되므로, 생성 엔진이 "타이밍을 잊어버릴" 여지가 없다.
- **③생성 엔진은 2단계 합성**이다 — Blender가 "기하학적으로 정확한 카메라 이동"을
  먼저 만들고(진짜 3D), 그 결과를 디퓨전 모델의 조건(ControlNet depth/pose)으로
  써서 "진짜 같은 질감"을 입힌다. 순수 text-to-video가 아니라
  geometry-conditioned generation — 이게 "모핑 아키텍처"의 하이브리드 지점.
- **④는 ③의 생성 엔진이 해상도/프레임레이트를 낮게 뽑을 수밖에 없는 무료 GPU
  한계를 보정**하는 레이어. 여기를 생성 엔진과 분리해둬야 나중에 더 나은
  업스케일 모델로 교체하기 쉽다.
- **⑤는 순수 조립** — 창작 판단이 들어가지 않는 기계적 단계라 Colab에서 끝내고
  파일만 로컬로 가져온다.

## 3. 디렉토리 구조

```
stereo-morph-pipeline/
├── docs/
│   ├── architecture.md          (이 문서)
│   └── camera-techniques.md     (4종 기법별 수식/파라미터 정의)
├── input/
│   ├── cinematography_briefs/   (샷별 연출 의도 — 로컬에서 마크다운으로 작성)
│   └── reference_material/      (레퍼런스 영상/이미지 메모)
├── control/
│   ├── schema.py                 (CameraPath 데이터 모델 — pydantic)
│   ├── camera_paths.py           (4종 기법 궤적 생성 함수)
│   └── presets/                  (생성된 JSON 샘플 출력물)
├── blender/
│   ├── generate_dummy_mesh.py    (bpy: 더미 휴먼 프록시 메시 생성)
│   └── apply_camera_path.py      (bpy: JSON 궤적 → 카메라 키프레임 + depth/normal 렌더)
├── comfyui/
│   ├── workflow_builder.py       (카메라패스+depth pass → ComfyUI API JSON 조립)
│   └── workflows/
│       └── bullet_time_morph.json (ComfyUI 워크플로우 템플릿)
├── refinement/
│   └── refine.py                 (업스케일/보간/얼굴복원 체인 — Colab 전용 실행)
├── colab/
│   └── stereo_morph_pipeline.ipynb (마스터 노트북 — 전 과정 실행)
├── output/                        (Colab에서 받은 최종 결과물 — git 미추적)
├── requirements.txt
└── .gitignore
```

## 4. 데이터 흐름 — 파일 단위

1. 로컬에서 `control/camera_paths.py`로 기법 하나 선택해 궤적 JSON 생성
   (예: `orbit_reveal(radius=3.0, height=1.6, duration_s=4, fps=24)`)
2. JSON을 `control/presets/<shot_id>.json`으로 저장, git commit & push
3. Colab 노트북이 레포를 clone, 해당 JSON을 읽어
   `blender -b -P blender/apply_camera_path.py -- --path control/presets/<shot_id>.json`
   실행 → depth/normal PNG 시퀀스 생성
4. `comfyui/workflow_builder.py`가 그 PNG 시퀀스 경로 + 입력 이미지(피사체)를
   받아 ComfyUI API 포맷 워크플로우 JSON을 조립
5. ComfyUI 서버(Colab 내 백그라운드 프로세스)에 그 워크플로우를 큐 전송 → 프레임 생성
6. `refinement/refine.py`가 생성된 프레임에 업스케일·보간 적용
7. ffmpeg로 mp4 인코딩 → Google Drive 저장 (+ 선택적으로 output/에 복사)

## 5. 1차 구현 범위 (이번 세션)

- 코드 스켈레톤 전체 (위 구조) — **동작 검증은 아직 안 됨**, 다음 단계는 실제
  Colab에서 1개 샷으로 end-to-end 실행해보는 것
- `control/` 레이어는 로컬 파이썬으로 바로 실행·검증 가능 (Blender/ComfyUI 불필요)
- `blender/`, `comfyui/` 스크립트는 문법은 정확하지만 실제 Blender/ComfyUI
  버전별 API 차이가 있어 Colab 1차 실행 시 조정이 필요할 가능성 높음 —
  "설계도"로 보고 실측 후 보정할 것

## 6. 반자동 체크포인트 (CP1~CP4)

처음 기획 의도가 "반자동 시스템"이었던 것은 조사 결과로도 확인됨 — Runway/Kling/
Higgsfield 같은 업계 선두 도구들도 인물 동일성을 완전자동으로 풀지 못하고,
"히어로 프레임 고정 → 매 샷 재주입 → 사람 검수" 루프를 쓴다(2026-10-22 리서치).
그래서 이 파이프라인도 처음부터 "어디는 자동, 어디는 반드시 사람"을 명시해둔다 —
yeori-studio의 G1~G5 게이트 정책(`[[project_gate_approval_policy]]`: 시각 판단이
필요한 지점은 위임 불가, 사람 1클릭)과 같은 원칙.

| 체크포인트 | 레이어 경계 | 자동/사람 | 왜 |
|---|---|---|---|
| **CP1** 궤적 프리뷰 승인 | ①→② | **사람 필수** | Colab GPU 태우기 전이 가장 저렴한 확인 시점 — 궤적이 틀리면 전체 샷이 틀어지는데, 여기서 걸러내는 게 Colab 쿼터 날리는 것보다 훨씬 쌈 |
| **CP2** 히어로 프레임(아이덴티티 앵커) 승인 | ②→③ | **사람 필수** | 인물 동일성은 기계가 판단 못 함 — yeori-studio G4에서 "서여리 컷은 시각 판단이라 위임 불가"였던 것과 동일 논리 |
| **CP3** 1차 생성 프리뷰 | ③→④ | 위임 가능 (저해상도 자동 필터 + 사람 최종 확인) | 카메라 궤적이 JSON과 실제로 일치하는지는 optical flow 등으로 1차 자동 체크 가능, 다만 "느낌"은 사람이 봐야 함 |
| **CP4** 최종본 승인 | ⑤ 직전 | **사람 필수** | 업로드 전 마지막 게이트 — 기존 G4/G5 승인 흐름과 합류 |

CP1·CP2·CP4는 자동화 대상이 아니라 "설계상 사람 자리"임을 명확히 해둔다 —
나중에 효율화한다고 이 세 지점을 자동 승인으로 바꾸면, 업계가 아직 못 푼 문제를
혼자 풀었다고 착각하는 꼴이 된다.

## 7. 다음 결정 지점

- ComfyUI에서 어떤 비디오 디퓨전 모델을 쓸지 (AnimateDiff-Evolved vs
  Stable Video Diffusion vs CogVideoX-5B 등) — 무료 Colab GPU(T4, ~15GB)
  메모리 한도 안에서 실측 비교 필요
- 더미 메시를 Blender 기본 프리미티브(캡슐)로 할지, 간단한 휴먼 리그로 할지
- yeori-studio G2/G4 파이프라인과 언제·어떻게 연결할지 (지금은 완전 분리)
