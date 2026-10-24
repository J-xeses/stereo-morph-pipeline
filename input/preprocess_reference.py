"""
피사체 참조 사진 1장 -> rembg로 배경 제거 -> 흰 배경 합성.

Wan2.1-VACE의 reference_image는 배경이 지저분하면 "이 사람"이 아니라 "이 사람+배경"을
정체성으로 섞어버린다는 게 커뮤니티 트러블슈팅 공통 지적(2026-10-24,
project_periodic_direction_research 메모). rembg는 이미 로컬에 설치돼 있어
Colab을 거치지 않고 로컬에서 바로 처리 -> CP2(히어로 프레임) 자리에 즉시 떨어뜨려
모니터 앱(localhost:4100)에서 바로 확인 가능하게 한다(2026-10-24, "로컬에서 직접
연결되어 체감할 수 있는 구조" 요구사항).
"""
from __future__ import annotations

import os

from PIL import Image
from rembg import remove


def preprocess(local_photo_path: str, out_path: str) -> str:
    if not os.path.exists(local_photo_path):
        raise FileNotFoundError(f"로컬 참조 사진 없음: {local_photo_path}")

    src = Image.open(local_photo_path).convert("RGBA")
    cut = remove(src)
    white_bg = Image.new("RGBA", cut.size, (255, 255, 255, 255))
    white_bg.paste(cut, mask=cut.split()[3])

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    white_bg.convert("RGB").save(out_path)
    return out_path


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("local_photo_path")
    p.add_argument("out_path")
    args = p.parse_args()
    result = preprocess(args.local_photo_path, args.out_path)
    print(f"흰 배경 참조 이미지 저장: {result}")
