# Phase 3 — Dependency Audit

> **STATUS: EVIDENCE-BACKED — compiled 2026-09-03**
> All claims below are classified by evidence source.

---

## 1. Selection Criteria

Target platform: **Windows x64 / Python 3.11 / CPU-only** (no CUDA, no DirectML).

---

## 2. WhisperX Stable Release

| Field | Value | Evidence |
|---|---|---|
| Selected version | **3.8.6** | PyPI stable (info.version) — LIVE_PYPI |
| Latest pre-release | 3.8.7rc1 | PyPI — LIVE_PYPI (not selected) |
| Wheel filename | `whisperx-3.8.6-py3-none-any.whl` | PyPI /pypi/whisperx/3.8.6/json — LIVE_PYPI |
| Wheel SHA-256 | `cb6d4fcd3fb6c42305cb8b222a33a0b78f6b657e9db3b714345fe43dc0a69c1f` | PyPI /pypi/whisperx/3.8.6/json — LIVE_PYPI |
| Source tarball SHA-256 | `d647aecaa6c2f413bb924d722d925878ef300c99093ca49cd6cb7840bdbffe0e` | PyPI /pypi/whisperx/3.8.6/json — LIVE_PYPI |
| Requires-Python | `<3.14,>=3.10` | PyPI metadata — LIVE_PYPI |
| Python 3.11 compatible | **YES** | 3.11 satisfies >=3.10,<3.14 — DERIVED |
| Yanked | No | PyPI yanked field — LIVE_PYPI |

---

## 3. WhisperX 3.8.6 Declared Dependencies

From `Requires-Dist` in `whisperx-3.8.6-py3-none-any.whl` metadata (LIVE_PYPI):

| Package | Constraint | Windows/Python 3.11 Availability | Evidence |
|---|---|---|---|
| `torch` | `~=2.8.0` | `torch-2.8.0+cpu-cp311-cp311-win_amd64.whl` — available on PyTorch CPU index | LIVE_PYPI + LIVE_PYTORCH_INDEX |
| `torchaudio` | `~=2.8.0` | `torchaudio-2.8.0+cpu-cp311-cp311-win_amd64.whl` — available | LIVE_PYTORCH_INDEX |
| `torchvision` | `~=0.23.0` | `torchvision-0.23.0+cpu-cp311-cp311-win_amd64.whl` — available | LIVE_PYTORCH_INDEX |
| `torchcodec` | `<0.8.0,>=0.6.0; sys_platform=="win32"` | `torchcodec-0.7.0-cp311-cp311-win_amd64.whl` — EXISTS on PyPI | LIVE_PYPI (confirmed cp311 wheel) |
| `faster-whisper` | `>=1.2.0` | Available on PyPI; no Windows binary restriction | LIVE_PYPI |
| `ctranslate2` | `>=4.5.0` | Pre-built Windows cp311 wheel available | LIVE_PYPI |
| `transformers` | `>=4.48.0` | Pure Python / available | LIVE_PYPI |
| `pyannote-audio` | `>=4.0.0` | Available; diarization models NOT loaded (diarization=False) | LIVE_PYPI |
| `huggingface-hub` | `<1.0.0` | Available | LIVE_PYPI |
| `numpy` | `>=2.1.0` | Available | LIVE_PYPI |
| `nltk` | `>=3.9.1` | Available | LIVE_PYPI |
| `omegaconf` | `>=2.3.0` | Available | LIVE_PYPI |
| `pandas` | `>=2.2.3` | Available | LIVE_PYPI |
| `triton` | Linux x86_64 only | **NOT REQUIRED on Windows** (marker `sys_platform=="linux"`) | LIVE_PYPI |

### Critical torchcodec Resolution

> **`sys.platform` on this system is `win32`** — torchcodec IS required.
> `torchcodec-0.7.0-cp311-cp311-win_amd64.whl` exists on PyPI and satisfies `<0.8.0,>=0.6.0`.
> Confirmed by querying `/pypi/torchcodec/0.7.0/json`. — LIVE_PYPI

---

## 4. PyTorch CPU Build Plan

Installation command (CPU-only):
```powershell
pip install torch==2.8.0+cpu torchaudio==2.8.0+cpu torchvision==0.23.0+cpu \
  --index-url https://download.pytorch.org/whl/cpu
```

| Requirement | Value |
|---|---|
| `torch.cuda.is_available()` | Must be `False` |
| `torch.version.cuda` | Must be `None` |
| `torch.__version__` | `2.8.0+cpu` |

---

## 5. Vietnamese Alignment Model

WhisperX performs **forced word-level alignment** using wav2vec2 models.
The language-to-model mapping is in `whisperx.alignment.DEFAULT_ALIGN_MODELS_HF`.

| Field | Value | Evidence |
|---|---|---|
| Language code | `vi` (Vietnamese) | Phase 3 contract — USER_SPECIFIED |
| Alignment model ID | `nguyenvulebinh/wav2vec2-base-vi-vlsp2020` | RUNTIME_INTROSPECTION of `whisperx.alignment.DEFAULT_ALIGN_MODELS_HF['vi']` in installed whisperx 3.8.6 |
| Model source | HuggingFace Hub (public, no token required) | Public HF model — INFERRED |
| Fallback model (if introspection fails) | Same model ID (hard-coded fallback in backend) | Code — REPOSITORY |

> **No HuggingFace access token is required** — model is publicly accessible.

---

## 6. Compatibility Assessment

| Check | Result |
|---|---|
| Python 3.11 + whisperx 3.8.6 | **COMPATIBLE** |
| Windows x64 CPU + torch 2.8.0+cpu | **COMPATIBLE** |
| torchcodec 0.7.0 cp311 Windows | **COMPATIBLE** — win_amd64 wheel exists |
| CUDA/DirectML | **EXCLUDED by installation plan** |
| Diarization models | **NOT LOADED** — diarization=False policy |

---

## 7. Evidence Classification Key

| Code | Meaning |
|---|---|
| `LIVE_PYPI` | Live query to PyPI JSON API at audit time |
| `LIVE_PYTORCH_INDEX` | Live query to download.pytorch.org/whl/cpu |
| `RUNTIME_INTROSPECTION` | Value obtained from running installed package |
| `DERIVED` | Logically derived from other evidence |
| `REPOSITORY` | From committed repository source code |
| `USER_SPECIFIED` | From user-provided phase gate instructions |
| `INFERRED` | Agent inference with low uncertainty |

---

> Phase 4 deployment is NOT implemented. Cloudflare Worker limits were removed
> from DEPLOYMENT_TARGET.md in the Phase 2 Final Correction.
