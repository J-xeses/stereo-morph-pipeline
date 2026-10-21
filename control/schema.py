"""
4D 카메라 궤적 데이터 모델.

로컬에서 만들고(camera_paths.py) JSON으로 저장되면, 그 이후 모든 레이어
(Blender, ComfyUI, Colab)는 이 포맷만 보고 동작한다 — 어떤 기법으로
생성됐는지는 여기서부터 보이지 않는다(camera-techniques.md 참고).

좌표계: Blender 기준(Z-up, 미터), 원점은 피사체 중심.
"""
from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


class Technique(str, Enum):
    BULLET_TIME = "bullet_time"
    ROTATING_LONG_TAKE = "rotating_long_take"
    CONTINUOUS_LONG_TAKE = "continuous_long_take"
    LOOP_FLIGHT = "loop_flight"


class Vec3(BaseModel):
    x: float
    y: float
    z: float


class CameraFrame(BaseModel):
    """한 프레임의 카메라 상태."""

    frame: int = Field(..., description="0-indexed 프레임 번호")
    time_s: float = Field(..., description="초 단위 타임코드")
    position: Vec3
    look_at: Vec3
    fov_deg: float = Field(default=50.0, description="수직 화각(도)")
    up: Vec3 = Field(default_factory=lambda: Vec3(x=0, y=0, z=1))


class CameraPath(BaseModel):
    """한 샷 전체의 카메라 궤적."""

    shot_id: str
    technique: Technique
    fps: int = Field(default=24)
    duration_s: float
    subject_freeze: bool = Field(
        default=False,
        description="True면 생성 엔진 쪽에 피사체 모션 고정을 조건으로 추가 요청"
        " (불릿타임 전용 플래그 — Blender/ComfyUI가 직접 강제하진 못하고,"
        " 프롬프트/컨디셔닝 쪽에 힌트로만 전달됨)",
    )
    frames: list[CameraFrame]

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def to_json_file(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))

    @classmethod
    def from_json_file(cls, path: str) -> "CameraPath":
        with open(path, "r", encoding="utf-8") as f:
            return cls.model_validate_json(f.read())
