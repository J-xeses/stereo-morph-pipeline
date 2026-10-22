"""
CP1(궤적 프리뷰 승인)을 실제로 "보고 판단"할 수 있게 해주는 로컬 전용 도구.
Colab/GPU 전혀 불필요 — camera_paths.py가 만든 JSON만 읽어서 그림으로 뱉는다.

    python control/preview_camera_path.py control/presets/demo_bullet_time.json

왼쪽: 위에서 본 궤적(카메라가 피사체 주위를 어떻게 도는지)
오른쪽: 옆에서 본 궤적(높이 변화 — 크레인업/다운, 아크 여부)
화살표: look_at 방향을 N프레임마다 표시 — 피사체를 계속 보고 있는지 한눈에 확인용
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load_path(json_path: str) -> dict:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def preview(json_path: str, out_path: str | None = None, arrow_every: int = 6):
    data = load_path(json_path)
    frames = data["frames"]
    xs = [f["position"]["x"] for f in frames]
    ys = [f["position"]["y"] for f in frames]
    zs = [f["position"]["z"] for f in frames]
    lx = [f["look_at"]["x"] for f in frames]
    ly = [f["look_at"]["y"] for f in frames]

    fig, (ax_top, ax_side) = plt.subplots(1, 2, figsize=(11, 5))
    fig.suptitle(
        f"{data['shot_id']}  [{data['technique']}]  "
        f"{data['duration_s']}s @ {data['fps']}fps, {len(frames)} frames"
        + ("  (subject_freeze)" if data.get("subject_freeze") else "")
    )

    # 위에서 본 뷰 (top-down, XY)
    ax_top.plot(xs, ys, "-", color="#4C72B0", linewidth=1.5)
    ax_top.scatter([xs[0]], [ys[0]], color="green", s=60, label="start", zorder=5)
    ax_top.scatter([xs[-1]], [ys[-1]], color="red", s=60, label="end", zorder=5)
    ax_top.scatter([0], [0], color="black", marker="x", s=80, label="subject", zorder=5)
    for i in range(0, len(frames), max(1, arrow_every)):
        dx, dy = lx[i] - xs[i], ly[i] - ys[i]
        ax_top.annotate(
            "", xy=(xs[i] + dx * 0.3, ys[i] + dy * 0.3), xytext=(xs[i], ys[i]),
            arrowprops=dict(arrowstyle="->", color="#999999", lw=0.8),
        )
    ax_top.set_title("Top-down (bird's-eye)")
    ax_top.set_xlabel("x (m)")
    ax_top.set_ylabel("y (m)")
    ax_top.axis("equal")
    ax_top.legend(fontsize=8)
    ax_top.grid(alpha=0.3)

    # 옆에서 본 뷰 (side, 진행률 vs z)
    progress = [f["time_s"] for f in frames]
    ax_side.plot(progress, zs, "-", color="#DD8452", linewidth=1.5)
    ax_side.scatter([progress[0]], [zs[0]], color="green", s=60, zorder=5)
    ax_side.scatter([progress[-1]], [zs[-1]], color="red", s=60, zorder=5)
    ax_side.set_title("Camera height over time")
    ax_side.set_xlabel("time (s)")
    ax_side.set_ylabel("z / height (m)")
    ax_side.grid(alpha=0.3)

    fig.tight_layout()
    out_path = out_path or os.path.splitext(json_path)[0] + "_preview.png"
    fig.savefig(out_path, dpi=120)
    print(f"프리뷰 저장: {out_path}")
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("json_path", help="control/presets/<shot_id>.json")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    preview(args.json_path, args.out)


if __name__ == "__main__":
    main()
