# 시그니처 카메라 기법 10종 — Flow 수동 vs 로컬 VACE 라우팅

2026-10-25 Flow Agent Mode 조사 결과(외부 API/MCP 없음, 카메라는 자연어+시작/끝
프레임으로만 조정, Characters 엔티티로 정체성 유지 지원, 8~10초 단일 클립 한계)를
근거로 10종 시그니처 기법을 1차 분류한다. 기준은 단순함: **좌표/속도를 숫자로
정확히 못 박아야 하는 기법 → 로컬(`control/camera_paths.py`, VACE)**,
**자연어 서술로 모델이 이미 많이 학습한 흔한 카메라워크 → Flow 수동(사람이
Agent Mode에서 직접 생성)**. 실측 테스트 전 1차 추정이므로, Flow에서 실제로
돌려본 뒤 재분류할 것.

## 로컬 VACE (정밀 궤적이 핵심)

| 기법 | 이유 | 상태 |
|---|---|---|
| 360° 매트릭스 불릿타임 오빗 | 정확한 원형 궤도+슬로우모션, 메인채널 시그니처라 정밀도 타협 불가 | `orbit_bullet_time` 기존 구현 |
| 패럴랙스 트래킹/트럭샷 | 전경·중경·원경 "상대 속도 차이"를 숫자로 설계해야 함 — 자연어로 지시 불가능한 영역 | 신규 함수 필요 |
| 헬리컬 나선 상승 | 나선 방정식(오빗+수직 상승 합성), `loop_flight`의 스파이럴 각도 로직 재사용 가능 | 신규 함수 필요(또는 loop_flight 파라미터 확장) |
| 에픽 크레인/지브 지평선 리빌 | 단순하지만 로우앵글→하이앵글 수직 이동을 정확히 고정해야 "리빌 타이밍"이 삼 | 신규 함수 필요(간단, 단일축 이동) |
| 이모셔널 달리 푸시인 | 가장 단순한 1축 직선 이동 — 구현 비용이 낮아 굳이 Flow에 맡길 이유가 없음 | 신규 함수 필요(간단) |

## Flow 수동 생성 (자연어+시작/끝 프레임으로 충분)

생성 모델이 이미 수없이 학습한 "흔한 카메라워크" 또는 **카메라 위치/회전만으로
표현 불가능한 효과**(초점거리 변화 등)라 로컬 파이프라인의 position/rotation
기반 카메라 모델로는 원천적으로 흉내 낼 수 없는 것들.

### 1. 버티고 / 달리 줌 (Vertigo / Zolly)
FOV(초점거리)가 피사체 크기를 상쇄하며 변하는 효과라 position/rotation만 다루는
로컬 카메라 모델로는 재현 불가 — Flow에 맡기는 게 아니라 **구조적으로 로컬이
못 하는 영역**.

```
Flow 프롬프트 템플릿:
"A vertigo dolly zoom (Hitchcock zolly) effect on @{character}: the camera
physically moves backward away from {subject} while simultaneously zooming in
(or vice versa) so {subject}'s size in frame stays constant while the
background {setting} dramatically stretches and distorts in perspective.
{duration} seconds, slow deliberate motion, dramatic psychological tension,
cinematic film grain."
```
시작/끝 프레임 가이드: 시작=클로즈업 구도, 끝=피사체 크기는 동일하되 배경만
확장된 느낌의 합성 레퍼런스를 끝 프레임으로 넣으면 목표를 더 잘 따라감.

### 2. 더치 앵글 누아르 틸트 (Dutch Angle Noir)
카메라 이동이 거의 없는 정적~준정적 구도(롤 각도만 고정) — 궤적 계산 자체가
필요 없는 "프레이밍" 문제라 로컬 파이프라인을 쓸 이유가 없음.

```
Flow 프롬프트 템플릿:
"@{character} framed at a dutch angle, camera tilted {tilt_deg} degrees off
the horizontal axis, creating psychological tension and unease, film noir
lighting with hard shadows, {setting}. Camera remains mostly static or very
slow subtle drift, {duration} seconds."
```

### 3. 시네마틱 휩 / 스위시 팬 (Whip Pan)
핵심이 "모션 블러 후 포커스 스냅"이라는 생성 모델의 학습된 질감 표현이지,
궤적 정밀도가 아님.

```
Flow 프롬프트 템플릿:
"Fast whip pan / swish pan camera movement: camera rotates rapidly across
{setting}, producing strong motion blur, then snaps to a sharp focus stop on
@{character}. {duration} seconds, cinematic, high energy transition shot."
```

### 4. 오가닉 핸드헬드 시네마 베리테 (Handheld Vérité)
목표가 "불규칙함의 질감"이라 `loop_flight`의 노이즈 로직으로도 흉내는 가능하지만,
이건 Flow가 이미 방대하게 학습한 흔한 다큐 카메라워크라 자연어가 더 싸고 빠름.

```
Flow 프롬프트 템플릿:
"Handheld documentary cinéma vérité camera style following @{character} in
{setting}, subtle natural handheld shake and breathing motion, imperfect
framing, raw authentic feel, {duration} seconds, no stabilization."
```

## 미정 — 실측 필요

### FPV 고속 드론 급강하 & 뱅킹 (FPV Drone Dive)
롤-요 복합 회전은 `loop_flight`가 다루는 영역과 비슷해 로컬로도 가능할 것
같지만, FPV 드론 샷은 보통 환경 스케일(건물/풍경) 연출이라 우리 파이프라인의
"단일 피사체 인물 클로즈업 + depth pass" 전제와 맞을지 불확실. Flow에서 먼저
테스트해 피사체 식별이 유지되는지 확인 후 분류.

```
Flow 프롬프트 템플릿(테스트용):
"FPV drone-style camera diving steeply downward with banking roll-yaw rotation
toward @{character} in {setting}, acrobatic low-altitude flight energy, fast
dynamic motion, {duration} seconds."
```

## 다음 단계

1. Flow 수동 4종(+FPV 테스트 1종) — 성준님이 Agent Mode에서 위 템플릿으로 직접
   생성해보고 결과 공유. 템플릿의 `{subject}/{setting}/{duration}/{character}`
   채워서 사용.
2. 로컬 VACE 5종 — 신규 함수(`parallax_truck`, `helical_spiral_ascent`,
   `crane_reveal`, `dolly_push_in`) 구현은 Flow 테스트 결과를 보고 우선순위
   정해서 착수(기존 4기법과 동일하게 `control/camera_paths.py`에 추가,
   `docs/camera-techniques.md`에 수식 문서화, `server/app.py`의
   `TECHNIQUE_SCHEMA` introspection이 자동으로 집어감).
