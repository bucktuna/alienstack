# Models: what to download and where it goes

Part of the Open Commons projects. Project home: [opencommons.app](https://opencommons.app).

Model weights are **not stored in this repository**. GitHub rejects files over
100 MB, and the language models alone are about 14 GB. Every download below is
public and needs **no account, no sign-in and no token**.

Sizes are what the tested install reports (decimal GB/MB). Paths are relative to
the folder you cloned this repo into unless noted.

## Summary

| Component | Model | Get it with | Size on disk | Where it lives |
|---|---|---|---|---|
| Sentinel (Open WebUI) | `huihui_ai/qwen3-abliterated:14b` (Qwen3 14.8B, Q4_K_M, 40k context) | `ollama pull huihui_ai/qwen3-abliterated:14b` | 9.0 GB | Ollama's model store (see below) |
| Sentinel English-only variant | built from `sentinel/qwen14b-english.Modelfile` | `ollama create qwen14b-english -f sentinel/qwen14b-english.Modelfile` | ~0 extra (reuses the 14B layers) | Ollama's model store |
| Oracle chat, voice-chat replies, Parliament bots and reviewer | `llama3.1:8b` (8.0B, Q4_K_M, 128k context) | `ollama pull llama3.1:8b` | 4.9 GB | Ollama's model store |
| Optional lighter Sentinel model | `huihui_ai/qwen3-abliterated:8b` (8.2B, Q4_K_M) | `ollama pull huihui_ai/qwen3-abliterated:8b` | 5.0 GB | Ollama's model store |
| Oracle speech synthesis | Kokoro-82M ONNX: `kokoro-v1.0.onnx` | curl (below) | 325.5 MB | `oracle/models/kokoro-v1.0.onnx` |
| Oracle voice pack | `voices-v1.0.bin` | curl (below) | 28.2 MB | `oracle/models/voices-v1.0.bin` |
| Voice-chat speech recognition | faster-whisper `small.en` (CTranslate2, run as CPU int8) | Python one-liner (below) | ~484 MB (model.bin) plus small config files | `oracle/models/whisper/` |

Model pages:
[Qwen3 abliterated on Ollama](https://ollama.com/huihui_ai/qwen3-abliterated),
[Llama 3.1 on Ollama](https://ollama.com/library/llama3.1),
[Kokoro ONNX release files](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0),
[faster-whisper small.en on Hugging Face](https://huggingface.co/Systran/faster-whisper-small.en).
Each model keeps its own upstream license (Qwen: Apache-2.0 base; Llama 3.1:
Meta Llama 3.1 Community License; Kokoro: Apache-2.0; Whisper: MIT). Read them
before redistributing weights.

## 1. Ollama models (Sentinel, Oracle, Parliament)

Install [Ollama](https://ollama.com/download), then:

```bash
ollama pull huihui_ai/qwen3-abliterated:14b     # 9.0 GB, Sentinel
ollama pull llama3.1:8b                         # 4.9 GB, Oracle + Parliament
ollama create qwen14b-english -f sentinel/qwen14b-english.Modelfile   # optional
# ollama pull huihui_ai/qwen3-abliterated:8b    # 5.0 GB, optional smaller GPU
ollama list                                     # confirm
```

You never place these files by hand. Ollama stores them in its own directory:

- Linux system service: `/usr/share/ollama/.ollama/models`
- Linux/macOS user install: `~/.ollama/models`
- Windows: `%USERPROFILE%\.ollama\models`
- Override with the `OLLAMA_MODELS` environment variable.

The apps pick models by name, and each name can be changed in its environment:
`ORACLE_MODEL` and `TALK_MODEL` (Oracle, default `llama3.1:8b`), `LLAMA_MODEL`
(Parliament, default `llama3.1:8b`). In Sentinel, choose the model in the chat's
model picker.

## 2. Kokoro voice files (Oracle)

```bash
mkdir -p oracle/models
curl -fL --retry 2 https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx -o oracle/models/kokoro-v1.0.onnx
curl -fL --retry 2 https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin -o oracle/models/voices-v1.0.bin
ls -l oracle/models   # expect 325532387 and 28214398 bytes
```

## 3. Whisper speech recognition (voice chat)

Oracle loads Whisper with `local_files_only=True`, so fetch it once, before the
first start, inside Oracle's virtual environment:

```bash
cd oracle && source venv311/bin/activate
python -c "from faster_whisper.utils import download_model; download_model('small.en', cache_dir='models/whisper')"
```

That creates `oracle/models/whisper/models--Systran--faster-whisper-small.en/`.
To trade accuracy for speed, set `TALK_WHISPER=base.en` (about 145 MB) and
download `base.en` the same way.

## 4. Running it all locally with no sign-in

- **Oracle** and the **Parliament** viewer have no login.
- **Sentinel / Open WebUI** asks you to create a first admin account by default.
  On a fresh, private, localhost-only install you can turn the login off by
  setting `WEBUI_AUTH=false` in `sentinel/sentinel.env` **before the very first
  start**. Open WebUI refuses this once any account exists, and with it off every
  visitor is an admin who can run tools on your machine, so never expose a
  no-auth Sentinel to the internet.

## Hardware notes

Tested on a 12 GB RTX 3060 with 32 GB RAM. Qwen 14B takes about 9 GB VRAM and
Llama 3.1 8B about 5 GB, so they will not both stay resident on 12 GB. Ollama
swaps them as needed. Kokoro and Whisper run on CPU. Plan for roughly 16 GB of
free disk for all downloads plus virtual environments.

## Checksums

No private checksum list is shipped. Verify against upstream: `ollama pull`
checks layer digests automatically, Hugging Face lists file hashes on each
model page, and the Kokoro release page lists its assets.
