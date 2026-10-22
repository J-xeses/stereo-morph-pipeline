"""
4종 카메라 기법의 궤적 생성기. docs/camera-techniques.md의 수식을 그대로 구현.

의존성은 표준 라이브러리만 사용(math, random) — 로컬에서 Blender/ComfyUI 없이
바로 실행·검증 가능해야 ②제어 레이어가 ③생성 엔진과 독립적으로 테스트된다.

사용 예:
    from control.camera_paths import orbit_bullet_time
    path = orbit_bullet_time(shot_id="SF_E01_C03", radius=3.0, arc_degrees=180)
    path.to_json_file("control/presets/SF_E01_C03.json")
"""
from __future__ import annotations

import math
import random

from schema import CameraFrame, CameraPath, Technique, Vec3


# ---------------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------------

def ease_in_out_cubic(p: float) -> float:
    if p < 0.5:
        return 4 * p ** 3
    return 1 - ((-2 * p + 2) ** 3) / 2


def _value_noise_1d(seed: int, freq_scale: float = 1.0):
    """시드 고정된 코사인보간 value-noise. 외부 의존성(noise/perlin-numpy) 없이
    재현 가능한 "불규칙하지만 끊기지 않는" 1D 곡선을 만들기 위함."""
    lattice = {}

    def lattice_value(i: int) -> float:
        if i not in lattice:
            rng_local = random.Random(f"{seed}:{i}")
            lattice[i] = rng_local.uniform(-1.0, 1.0)
        return lattice[i]

    def noise(t: float) -> float:
        t *= freq_scale
        i0 = math.floor(t)
        frac = t - i0
        a, b = lattice_value(i0), lattice_value(i0 + 1)
        smooth = (1 - math.cos(frac * math.pi)) / 2
        return a * (1 - smooth) + b * smooth

    return noise


def _catmull_rom(p0: Vec3, p1: Vec3, p2: Vec3, p3: Vec3, t: float) -> Vec3:
    t2, t3 = t * t, t * t * t

    def axis(a0, a1, a2, a3):
        return 0.5 * (
            (2 * a1)
            + (-a0 + a2) * t
            + (2 * a0 - 5 * a1 + 4 * a2 - a3) * t2
            + (-a0 + 3 * a1 - 3 * a2 + a3) * t3
        )

    return Vec3(
        x=axis(p0.x, p1.x, p2.x, p3.x),
        y=axis(p0.y, p1.y, p2.y, p3.y),
        z=axis(p0.z, p1.z, p2.z, p3.z),
    )


def _sample_times(duration_s: float, fps: int) -> list[tuple[int, float]]:
    total_frames = max(1, round(duration_s * fps))
    return [(f, f / fps) for f in range(total_frames)]


# ---------------------------------------------------------------------------
# 1. 불릿타임
# ---------------------------------------------------------------------------

def orbit_bullet_time(
    shot_id: str,
    radius: float = 0.45,
    height: float = 1.45,
    arc_height: float = 0.08,
    subject_height: float = 1.6,
    arc_degrees: float = 180.0,
    duration_s: float = 1.5,
    fps: int = 24,
    fov_deg: float = 50.0,
) -> CameraPath:
    # 불릿타임은 "표정을 포착"하는 얼굴 클로즈업 용도라 radius/height 기본값도
    # 전신이 아니라 얼굴에 맞춰져 있어야 함 — CP3 실측(2026-10-22)에서 기본값이
    # 3m/허리높이였을 때 참조 이미지(얼굴 클로즈업)와 depth 프레이밍이 안 맞아
    # 괴상한 합성 아티팩트가 났던 걸 고침. look_at도 몸 중심(허리)이 아니라
    # 머리 중심 높이를 보도록 — generate_dummy_mesh.py의 비율(머리중심 ≈ 키*0.915)과
    # 맞춰뒀다.
    omega = math.radians(arc_degrees) / duration_s
    head_center_z = subject_height * 0.915
    frames = []
    for f, t in _sample_times(duration_s, fps):
        angle = omega * t
        z = height + arc_height * math.sin(math.pi * t / duration_s)
        frames.append(
            CameraFrame(
                frame=f,
                time_s=t,
                position=Vec3(x=radius * math.cos(angle), y=radius * math.sin(angle), z=z),
                look_at=Vec3(x=0, y=0, z=head_center_z),
                fov_deg=fov_deg,
            )
        )
    return CameraPath(
        shot_id=shot_id,
        technique=Technique.BULLET_TIME,
        fps=fps,
        duration_s=duration_s,
        subject_freeze=True,
        frames=frames,
    )


# ---------------------------------------------------------------------------
# 2. 회전 롱테이크
# ---------------------------------------------------------------------------

def rotating_long_take(
    shot_id: str,
    radius_start: float = 4.0,
    radius_end: float = 2.5,
    height_start: float = 1.5,
    height_end: float = 2.2,
    subject_height: float = 1.6,
    arc_degrees: float = 270.0,
    duration_s: float = 8.0,
    fps: int = 24,
    fov_deg: float = 45.0,
) -> CameraPath:
    frames = []
    for f, t in _sample_times(duration_s, fps):
        p = t / duration_s
        eased = ease_in_out_cubic(p)
        angle = math.radians(arc_degrees) * eased
        radius = radius_start + (radius_end - radius_start) * eased
        z = height_start + (height_end - height_start) * eased
        frames.append(
            CameraFrame(
                frame=f,
                time_s=t,
                position=Vec3(x=radius * math.cos(angle), y=radius * math.sin(angle), z=z),
                look_at=Vec3(x=0, y=0, z=subject_height * 0.5),
                fov_deg=fov_deg,
            )
        )
    return CameraPath(
        shot_id=shot_id,
        technique=Technique.ROTATING_LONG_TAKE,
        fps=fps,
        duration_s=duration_s,
        subject_freeze=False,
        frames=frames,
    )


# ---------------------------------------------------------------------------
# 3. 연속 롱테이크
# ---------------------------------------------------------------------------

def continuous_long_take(
    shot_id: str,
    waypoints: list[tuple[float, float, float]],
    look_ahead: float = 1.5,
    duration_s: float = 10.0,
    fps: int = 24,
    fov_deg: float = 42.0,
) -> CameraPath:
    """waypoints: 3개 이상의 (x,y,z) 제어점. Catmull-Rom으로 보간."""
    if len(waypoints) < 3:
        raise ValueError("연속 롱테이크는 waypoints가 최소 3개 필요 (양끝 접선 계산용)")

    pts = [Vec3(x=x, y=y, z=z) for x, y, z in waypoints]
    pts = [pts[0]] + pts + [pts[-1]]  # 양끝 복제로 Catmull-Rom 경계 처리

    n_segments = len(pts) - 3
    frames = []
    for f, t in _sample_times(duration_s, fps):
        p = t / duration_s
        seg_f = p * n_segments
        seg_i = min(int(seg_f), n_segments - 1)
        local_t = seg_f - seg_i
        pos = _catmull_rom(pts[seg_i], pts[seg_i + 1], pts[seg_i + 2], pts[seg_i + 3], local_t)

        local_t_ahead = min(1.0, local_t + 0.01)
        pos_ahead = _catmull_rom(
            pts[seg_i], pts[seg_i + 1], pts[seg_i + 2], pts[seg_i + 3], local_t_ahead
        )
        direction = Vec3(x=pos_ahead.x - pos.x, y=pos_ahead.y - pos.y, z=pos_ahead.z - pos.z)
        mag = math.sqrt(direction.x ** 2 + direction.y ** 2 + direction.z ** 2) or 1.0
        look_at = Vec3(
            x=pos.x + direction.x / mag * look_ahead,
            y=pos.y + direction.y / mag * look_ahead,
            z=pos.z + direction.z / mag * look_ahead,
        )
        frames.append(
            CameraFrame(frame=f, time_s=t, position=pos, look_at=look_at, fov_deg=fov_deg)
        )
    return CameraPath(
        shot_id=shot_id,
        technique=Technique.CONTINUOUS_LONG_TAKE,
        fps=fps,
        duration_s=duration_s,
        subject_freeze=False,
        frames=frames,
    )


# ---------------------------------------------------------------------------
# 4. 예측불가 카메라 루프 비행
# ---------------------------------------------------------------------------

def loop_flight(
    shot_id: str,
    base_radius: float = 3.5,
    height: float = 1.8,
    spiral_rate_deg_per_s: float = 60.0,
    low_freq: float = 0.15,
    high_freq: float = 1.2,
    radius_jitter: float = 0.3,
    height_jitter_amp: float = 0.35,
    base_fov: float = 48.0,
    fov_jitter: float = 4.0,
    duration_s: float = 6.0,
    fps: int = 24,
    seed: int = 42,
) -> CameraPath:
    noise_x = _value_noise_1d(seed + 1)
    noise_y = _value_noise_1d(seed + 2)
    noise_z = _value_noise_1d(seed + 3, freq_scale=high_freq)
    noise_fov = _value_noise_1d(seed + 4, freq_scale=high_freq)

    frames = []
    for f, t in _sample_times(duration_s, fps):
        radial_mod = 1 + radius_jitter * noise_x(t * low_freq)
        spiral_angle = math.radians(spiral_rate_deg_per_s) * t
        wobble_angle = 0.4 * noise_y(t * low_freq)
        angle = spiral_angle + wobble_angle

        z = height + height_jitter_amp * noise_z(t)
        fov = base_fov + fov_jitter * noise_fov(t)

        frames.append(
            CameraFrame(
                frame=f,
                time_s=t,
                position=Vec3(
                    x=base_radius * radial_mod * math.cos(angle),
                    y=base_radius * radial_mod * math.sin(angle),
                    z=z,
                ),
                look_at=Vec3(x=0, y=0, z=height * 0.6),
                fov_deg=fov,
            )
        )
    return CameraPath(
        shot_id=shot_id,
        technique=Technique.LOOP_FLIGHT,
        fps=fps,
        duration_s=duration_s,
        subject_freeze=False,
        frames=frames,
    )


if __name__ == "__main__":
    # 4종 전부 기본 파라미터로 생성해 control/presets/ 에 저장 — 로컬에서
    # `python camera_paths.py` 한 줄로 궤적 수식이 깨지지 않았는지 바로 확인.
    import os

    out_dir = os.path.join(os.path.dirname(__file__), "presets")
    os.makedirs(out_dir, exist_ok=True)

    samples = {
        "demo_bullet_time": orbit_bullet_time("demo_bullet_time"),
        "demo_rotating_long_take": rotating_long_take("demo_rotating_long_take"),
        "demo_continuous_long_take": continuous_long_take(
            "demo_continuous_long_take",
            waypoints=[(0, -5, 1.6), (2, -2, 1.8), (1, 1, 1.5), (-2, 3, 2.0)],
        ),
        "demo_loop_flight": loop_flight("demo_loop_flight"),
    }
    for name, path in samples.items():
        out_path = os.path.join(out_dir, f"{name}.json")
        path.to_json_file(out_path)
        print(f"{name}: {path.frame_count} frames -> {out_path}")
