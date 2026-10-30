"""
Wan-Move GGUF 환경을 한 번에 복구하고, Cloudflare 터널로 ComfyUI 편집 화면을
브라우저에서 바로 열 수 있게 URL을 띄워주는 "원샷" 스크립트.

2026-10-30 세션에서 반복 발생한 두 가지를 이 스크립트 하나로 흡수한다:
  1) ComfyUI pip install이 끝나면 numpy/scipy ABI가 깨지는 Colab 환경 버그
     (cannot import name '_slice' from numpy._core.umath) — 매번 재발했음.
     **중요 발견**: 이 버그 수정에 "커널 재시작"이 필요했던 건 노트북 커널 안에서
     직접 import 테스트를 했기 때문이다. ComfyUI 서버는 어차피 `python main.py`로
     별도 프로세스로 뜨므로, 이 스크립트처럼 pip install을 먼저 끝내고 나서
     서버를 기동하면 커널 재시작이 전혀 필요 없다.
  2) Colab+Cloudflare 터널 라이브뷰잉(2026-10-27 최초 성공)을 다시 셋업하는
     과정 — cloudflared 설치 + `--enable-cors-header *`로 ComfyUI 기동 +
     터널 URL 파싱까지 자동화.

Colab에서 쓰는 법 (셀 0으로 레포 클론한 다음, 이 스크립트가 유일하게 필요한 셀):
    !python /content/stereo-morph-pipeline/colab/bootstrap_wanmove_and_tunnel.py

실행이 끝나면 "LIVE VIEW URL: https://xxxx.trycloudflare.com" 한 줄이 출력된다 —
그 주소를 그대로 브라우저에서 열면 ComfyUI 편집기가 뜬다(최초 로딩에 최대 7분
걸릴 수 있음, 조급해하지 말 것 — 2026-10-27 메모 참고).

멱등성: 이미 설치/복사된 건 전부 건너뛰므로 같은 런타임에서 여러 번 실행해도
안전하다(런타임이 바뀌면 /content가 전부 비므로 처음부터 다시 받는다).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time

CONTENT = "/content"
COMFYUI = f"{CONTENT}/ComfyUI"
REPO = f"{CONTENT}/stereo-morph-pipeline"
DRIVE_CACHE = f"{CONTENT}/drive/MyDrive/morph-pipeline-models"
LOG_DIR = f"{CONTENT}/bootstrap_logs"
os.makedirs(LOG_DIR, exist_ok=True)


def run(cmd: str, **kwargs) -> subprocess.CompletedProcess:
    print(f"$ {cmd}")
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kwargs)


def step(title: str) -> None:
    print(f"\n{'=' * 10} {title} {'=' * 10}")


# ---------------------------------------------------------------------------
step("1/7 numpy/scipy ABI 깨짐 선제 수정")
# ComfyUI의 pip install -r requirements.txt가 깨뜨려놓는 조합 — 서버를 띄우기
# *전*에 고쳐두면 커널 재시작 없이 바로 반영된다(서버는 별도 프로세스라서).
r = run("pip install -q --force-reinstall --no-cache-dir numpy scipy")
print("numpy/scipy 재설치 완료" if r.returncode == 0 else f"경고: {r.stderr[-500:]}")

# ---------------------------------------------------------------------------
step("2/7 레포 / ComfyUI / GGUF 노드 확인")
if not os.path.isdir(REPO):
    run(f"git clone https://github.com/J-xeses/stereo-morph-pipeline.git {REPO}")
else:
    run(f"git -C {REPO} pull")

if not os.path.isdir(COMFYUI):
    run(f"git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git {COMFYUI}")
    run(f"pip install -q -r {COMFYUI}/requirements.txt")
else:
    print("ComfyUI 이미 있음, 건너뜀")

gguf_node = f"{COMFYUI}/custom_nodes/ComfyUI-GGUF"
if not os.path.isdir(gguf_node):
    run("pip install -q --upgrade gguf")
    run(f"git clone --depth 1 https://github.com/city96/ComfyUI-GGUF {gguf_node}")
else:
    print("ComfyUI-GGUF 노드 이미 있음, 건너뜀")

for sub in ["unet", "text_encoders", "clip_vision", "vae", "loras"]:
    os.makedirs(f"{COMFYUI}/models/{sub}", exist_ok=True)

# ---------------------------------------------------------------------------
step("3/7 Google Drive 마운트")
try:
    from google.colab import drive  # type: ignore

    drive.mount("/content/drive")
    print("Drive 마운트 성공")
except Exception as e:  # noqa: BLE001
    print("Drive 마운트 실패, 캐시 없이 진행:", e)

os.makedirs(DRIVE_CACHE, exist_ok=True)

# ---------------------------------------------------------------------------
step("4/7 Wan-Move 모델 5종 (Drive 캐시 우선)")
WANMOVE_MODELS = [
    ("unet", "Wan-Move-14B-480P-Q4_K_M.gguf",
     "https://huggingface.co/vantagewithai/Wan-Move-14B-480P-GGUF/resolve/main/Wan-Move-14B-480P-Q4_K_M.gguf"),
    ("text_encoders", "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
     "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
    ("clip_vision", "clip_vision_h.safetensors",
     "https://huggingface.co/Comfy-Org/Wan-2.1/resolve/main/split_files/clip_vision/clip_vision_h.safetensors"),
    ("vae", "wan_2.1_vae.safetensors",
     "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors"),
    ("loras", "Wan21_I2V_14B_lightx2v_cfg_step_distill_lora_rank64.safetensors",
     "https://huggingface.co/lightx2v/Wan2.1-I2V-14B-480P-StepDistill-CfgDistill-Lightx2v/resolve/main/loras/Wan21_I2V_14B_lightx2v_cfg_step_distill_lora_rank64.safetensors"),
]
for subdir, filename, url in WANMOVE_MODELS:
    target_path = f"{COMFYUI}/models/{subdir}/{filename}"
    cache_path = f"{DRIVE_CACHE}/{filename}"
    if os.path.exists(target_path):
        print(f"이미 있음: {filename}")
    elif os.path.exists(cache_path):
        print(f"Drive 캐시에서 복사: {filename}")
        run(f"cp '{cache_path}' '{target_path}'")
    else:
        print(f"다운로드: {filename}")
        run(f"wget -c -q --show-progress -O '{target_path}' '{url}'")
        run(f"cp '{target_path}' '{cache_path}'")
        print(f"Drive에 캐시 저장: {filename}")

# ---------------------------------------------------------------------------
step("4b/7 참조 이미지 확인")
subject_src = f"{CONTENT}/subject_ref.png"
subject_cache = f"{DRIVE_CACHE}/subject_ref.png"
comfy_input = f"{COMFYUI}/input/subject_ref.png"
if os.path.exists(subject_src):
    run(f"cp '{subject_src}' '{comfy_input}'")
    if not os.path.exists(subject_cache):
        run(f"cp '{subject_src}' '{subject_cache}'")
        print("subject_ref.png를 Drive 캐시에도 저장 — 다음부터는 재업로드 불필요")
    print("subject_ref.png 준비 완료")
elif os.path.exists(subject_cache):
    run(f"cp '{subject_cache}' '{comfy_input}'")
    print("Drive 캐시에서 subject_ref.png 복사 완료")
else:
    print(
        "⚠️ subject_ref.png 없음 — Colab 파일 패널(좌측 폴더 아이콘)에서 "
        "/content/ 에 업로드한 뒤 이 스크립트를 다시 실행할 것"
    )

# ---------------------------------------------------------------------------
step("5/7 cloudflared 설치 확인")
cloudflared_bin = "/usr/local/bin/cloudflared"
if not os.path.exists(cloudflared_bin):
    run(
        "wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/"
        f"cloudflared-linux-amd64 -O {cloudflared_bin}"
    )
    run(f"chmod +x {cloudflared_bin}")
    print("cloudflared 설치 완료")
else:
    print("cloudflared 이미 설치됨")

# ---------------------------------------------------------------------------
step("6/7 ComfyUI 서버 기동 (CORS 허용, 백그라운드)")
comfyui_log = f"{LOG_DIR}/comfyui.log"
# start_new_session=True 필수 — 안 주면 노트북 셀 중단(Ctrl+M I)이 이 프로세스까지
# 같이 죽인다(2026-10-27 실측).
comfyui_proc = subprocess.Popen(
    ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188", "--enable-cors-header", "*"],
    cwd=COMFYUI,
    stdout=open(comfyui_log, "w"),
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
print(f"ComfyUI PID={comfyui_proc.pid}, 로그: {comfyui_log}")

ready = False
for i in range(40):  # 최대 120초
    time.sleep(3)
    try:
        import requests

        resp = requests.get("http://127.0.0.1:8188/object_info", timeout=2)
        if resp.status_code == 200:
            ready = True
            break
    except Exception:  # noqa: BLE001
        pass
    print(f"ComfyUI 기동 대기... ({(i + 1) * 3}초)")

if not ready:
    print("⚠️ 120초 넘게 응답 없음 — 로그 확인 필요:", comfyui_log)
    with open(comfyui_log) as f:
        print(f.read()[-2000:])
    sys.exit(1)

print("ComfyUI 준비 완료 (http://127.0.0.1:8188)")

# ---------------------------------------------------------------------------
step("7/7 Cloudflare 터널 기동 + URL 파싱")
tunnel_log = f"{LOG_DIR}/cloudflared.log"
tunnel_proc = subprocess.Popen(
    [cloudflared_bin, "tunnel", "--url", "http://localhost:8188", "--no-autoupdate"],
    stdout=open(tunnel_log, "w"),
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
print(f"cloudflared PID={tunnel_proc.pid}, 로그: {tunnel_log}")

url = None
for i in range(20):  # 최대 60초
    time.sleep(3)
    if os.path.exists(tunnel_log):
        with open(tunnel_log) as f:
            content = f.read()
        m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", content)
        if m:
            url = m.group(0)
            break
    print(f"터널 URL 대기... ({(i + 1) * 3}초)")

if url:
    print("\n" + "=" * 60)
    print(f"LIVE VIEW URL: {url}")
    print("=" * 60)
    print("위 주소를 브라우저에서 열면 ComfyUI 편집기가 뜬다.")
    print("최초 로딩에 최대 7분 걸릴 수 있음 — 안 뜨면 새로고침할 것.")
else:
    print("⚠️ 터널 URL을 못 찾음 — 로그 확인:", tunnel_log)
    with open(tunnel_log) as f:
        print(f.read()[-2000:])
