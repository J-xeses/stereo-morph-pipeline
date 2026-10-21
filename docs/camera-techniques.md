# 카메라 기법별 수식 정의

모든 기법은 `t ∈ [0, duration_s]` 구간에서 카메라의 위치 `(x, y, z)`, 조준점(lookAt),
화각(fov_deg)을 프레임 단위로 샘플링해 `control/schema.py`의 `CameraPath`로 뱉는다.
좌표계는 Blender 기준(Z-up, 미터 단위), 원점은 피사체 중심.

## 1. 불릿타임 (Bullet Time)

피사체는 정지(또는 1/Nx 슬로우), 카메라만 피사체 주위를 구체 궤도로 빠르게 선회.

```
x(t) = radius * cos(ω * t)
y(t) = radius * sin(ω * t)
z(t) = height + arc_height * sin(π * t / duration_s)   # 살짝 위아래 아크
lookAt = (0, 0, subject_height * 0.5)                   # 피사체 중심 고정
ω = (arc_degrees / duration_s) * (π / 180)
```

핵심 파라미터: `arc_degrees`(보통 90~270도), `radius`, `duration_s`(보통 1~3초,
체감상 "순간"이어야 함), `freeze_subject=True`(생성 엔진 쪽에 피사체 프레임 고정 지시).

## 2. 회전 롱테이크 (Rotating Long-take)

불릿타임과 수식은 비슷하지만 **피사체도 움직이고**, 컷 없이 더 긴 시간(5~15초)
선회하며 배경 정보를 드러낸다. 속도 프로파일에 ease-in/out을 반드시 넣어야
"의도된 연출"처럼 보인다(등속은 기계적으로 보임).

```
θ(t) = arc_degrees * ease_in_out_cubic(t / duration_s) * (π / 180)
x(t) = radius(t) * cos(θ(t))          # radius(t): 서서히 좁혀지거나 넓어지는 궤도 가능
y(t) = radius(t) * sin(θ(t))
z(t) = height(t)                       # 완만한 크레인 업/다운 허용
```

`ease_in_out_cubic(p) = 4p³ if p<0.5 else 1-(-2p+2)³/2`

## 3. 연속 롱테이크 (Continuous Long-take)

궤도가 아니라 **공간을 관통하는 경로** — 베지어 스플라인으로 웨이포인트를 잇는다.
컷 없이 여러 공간(실내→실외 등)을 지나가는 게 핵심이라 `waypoints`가 3~6개.

```
P(t) = CatmullRom(waypoints, t / duration_s)   # 제어점 보간, C1 연속 보장
lookAt(t) = P(t) + forward_offset(t)            # 진행 방향을 살짝 앞서 봄(관성감)
```

`waypoints`: `[(x,y,z,lookAt_hint), ...]` — 로컬에서 수동으로 좌표 입력 (기획자가
공간 레이아웃을 알아야 하는 유일한 기법이라 "로컬 기획" 비중이 가장 높음).

## 4. 예측불가 카메라 루프 비행 (Unpredictable Camera Loop Flight)

노이즈 기반 궤적 — Perlin/Simplex 노이즈로 "불규칙하지만 끊기지 않는" 비행 경로를
생성. 완전 랜덤이면 어지럽고 완전 규칙이면 "루프"의 긴장감이 안 산다 — 저주파
노이즈로 큰 흐름을 잡고 고주파 노이즈로 미세 흔들림을 얹는 2단 구조.

```
x(t) = base_radius * (1 + 0.3 * noise1D(seed_x, t * low_freq)) * cos(spiral_rate * t)
y(t) = base_radius * (1 + 0.3 * noise1D(seed_y, t * low_freq)) * sin(spiral_rate * t)
z(t) = height + jitter_amp * noise1D(seed_z, t * high_freq)
fov(t) = base_fov + fov_jitter * noise1D(seed_fov, t * high_freq)   # 미세 줌 흔들림
```

시드(`seed_x/y/z/fov`)를 고정하면 같은 "불규칙성"을 재현 가능 — 매번 랜덤이면
디버깅도 재사용도 불가능해지므로 반드시 seed 기반.

## 공통 스키마로의 변환

4종 모두 최종적으로 `List[CameraFrame]` (프레임당 position/rotation/fov)로
환원되어 `schema.py`를 거쳐 JSON 직렬화된다 — Blender/ComfyUI 쪽은 "어떤
기법이었는지" 모르고 그냥 프레임 배열만 받는다. 기법 차이는 **②제어 레이어
안에서만 존재**하고 그 아래로는 노출되지 않는 게 설계 의도.
