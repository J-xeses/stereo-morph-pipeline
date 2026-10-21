# stereo-morph-pipeline

불릿타임 / 회전 롱테이크 / 연속 롱테이크 / 예측불가 카메라 루프 비행 —
4D 카메라 궤적을 수치로 코딩해 생성 엔진에 직접 주입하는 하이브리드 모핑 파이프라인.

왜: 텍스트 프롬프트만으로 카메라 타이밍을 지시하면 디퓨전 모델이 타이밍을 "잊는"
한계가 실측으로 확인됨(`docs/architecture.md` §0). 그래서 카메라 궤적을 텍스트가
아니라 JSON으로 고정해, Blender(기하학) → ComfyUI(질감)로 넘기는 2단 생성 구조로 전환.

**먼저 읽을 것: [`docs/architecture.md`](docs/architecture.md)** — 5개 레이어
(입력→제어→생성→복원→출력)와 로컬/GitHub/Colab 3단 실행 흐름 전체 설계.
기법별 카메라 수식은 [`docs/camera-techniques.md`](docs/camera-techniques.md).

## 빠른 시작

### 1. 로컬 — 카메라 궤적 생성 (Blender/ComfyUI 불필요)

```bash
pip install -r requirements.txt
cd control
python camera_paths.py   # 4종 데모 궤적을 presets/ 에 JSON으로 생성
```

### 2. GitHub — 궤적 커밋 & 푸시

```bash
git add control/presets/<shot_id>.json
git commit -m "add camera path: <shot_id>"
git push
```

### 3. Colab — 실제 생성 (무료 GPU)

`colab/stereo_morph_pipeline.ipynb`를 Colab에서 열고 위에서부터 순서대로 실행.
`REPO_URL`, `SHOT_ID`를 바꿔서 원하는 샷을 생성.

## 상태

- ✅ `control/` — 로컬에서 실행 검증 완료 (4종 기법 전부 JSON 출력 확인)
- ⚠️ `blender/`, `comfyui/`, `refinement/` — 코드 스켈레톤만 존재, **Colab
  실제 실행으로 아직 검증 안 됨**. 노드 이름(class_type)·Blender 버전은
  실행 시 다를 수 있어 조정 필요.
- 다음 단계: Colab에서 샷 1개 end-to-end 1차 실행 → 깨지는 지점 보정
