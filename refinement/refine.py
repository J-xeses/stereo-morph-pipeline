"""
④ 디테일 복원 레이어 — Colab 전용 실행(GPU 필요). 로컬에서는 import만 가능,
실제 모델 추론은 돌지 않는다(가중치 없음).

체인: 프레임 보간(RIFE) → 얼굴 복원(CodeFormer) → 업스케일(Real-ESRGAN) → ffmpeg 인코딩

각 단계는 독립 함수라 "지금은 업스케일만 하고 보간은 건너뛴다" 같은 조합이
가능하도록 설계 — 무료 Colab GPU 시간 한도 안에서 셀 단위로 켜고 끌 수 있어야 함.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def interpolate_frames_rife(
    frames_dir: str, out_dir: str, rife_repo_dir: str, exp: int = 1
) -> None:
    """RIFE(ECCV2022-RIFE)로 프레임 사이를 2^exp배 보간. Colab에서 미리
    `git clone https://github.com/hzwer/ECCV2022-RIFE` 로 rife_repo_dir 준비 필요."""
    cmd = [
        "python",
        str(Path(rife_repo_dir) / "inference_video.py"),
        "--img", frames_dir,
        "--output", out_dir,
        "--exp", str(exp),
    ]
    subprocess.run(cmd, check=True)


def restore_faces_codeformer(
    frames_dir: str, out_dir: str, codeformer_repo_dir: str, fidelity: float = 0.7
) -> None:
    """CodeFormer로 얼굴 복원. fidelity 낮을수록 보정 강함(원본에서 더 멀어짐),
    높을수록 원본 보존 — 캐릭터 동일성 유지가 중요하므로 기본 0.7 권장."""
    cmd = [
        "python",
        str(Path(codeformer_repo_dir) / "inference_codeformer.py"),
        "-i", frames_dir,
        "-o", out_dir,
        "-w", str(fidelity),
        "--bg_upsampler", "realesrgan",
    ]
    subprocess.run(cmd, check=True)


def upscale_realesrgan(
    frames_dir: str, out_dir: str, realesrgan_repo_dir: str, scale: int = 2
) -> None:
    cmd = [
        "python",
        str(Path(realesrgan_repo_dir) / "inference_realesrgan.py"),
        "-i", frames_dir,
        "-o", out_dir,
        "-s", str(scale),
        "-n", "RealESRGAN_x4plus",
    ]
    subprocess.run(cmd, check=True)


def encode_video(frames_dir: str, out_path: str, fps: int = 24, pattern: str = "%06d.png") -> None:
    """⑤출력 레이어로 넘기기 직전 — 프레임 시퀀스를 mp4로 인코딩."""
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(Path(frames_dir) / pattern),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
        out_path,
    ]
    subprocess.run(cmd, check=True)


def refine_chain(
    raw_frames_dir: str,
    work_dir: str,
    final_out_path: str,
    fps: int,
    rife_repo_dir: str | None = None,
    codeformer_repo_dir: str | None = None,
    realesrgan_repo_dir: str | None = None,
) -> None:
    """레포별 경로가 None이면 그 단계는 건너뛴다 — Colab 세션별로 설치 여부가
    다를 수 있어 전부 옵션 처리."""
    stage_dir = raw_frames_dir
    stage_fps = fps

    if rife_repo_dir:
        out = str(Path(work_dir) / "interpolated")
        interpolate_frames_rife(stage_dir, out, rife_repo_dir, exp=1)
        stage_dir, stage_fps = out, stage_fps * 2

    if codeformer_repo_dir:
        out = str(Path(work_dir) / "face_restored")
        restore_faces_codeformer(stage_dir, out, codeformer_repo_dir)
        stage_dir = out

    if realesrgan_repo_dir:
        out = str(Path(work_dir) / "upscaled")
        upscale_realesrgan(stage_dir, out, realesrgan_repo_dir)
        stage_dir = out

    encode_video(stage_dir, final_out_path, fps=stage_fps)
    print(f"최종 출력: {final_out_path} ({stage_fps}fps)")
