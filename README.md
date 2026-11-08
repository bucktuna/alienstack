# Alien Stack

A self-hosted local-AI and voice playground by bucktuna. This clean source export
contains three cooperating applications, not a single installer:

- **Sentinel**: custom name/configuration and a persona layer on Open WebUI.
- **Oracle**: Kokoro voice blending, octave-down duet overlay, glitch/tagged-script
  sound design, sample buttons (including Pocket Songbird), renders and a phone-first UI.
- **Parliament**: a guest discussion timeline with a bounded draft-then-review loop,
  Llama reviewer, moderation, proposals/voting, and connector-fed X draft tooling.
- **Talk**: hold-to-talk in Oracle; local faster-whisper STT, streaming Llama reply,
  sentence-by-sentence blended speech. This is a snapshot of work in progress.

## Models and hardware

**Download list, sizes and placement paths: see [MODELS.md](MODELS.md).** No weights are stored in this repo and none of the downloads need a sign-in.

Sentinel uses `huihui_ai/qwen3-abliterated:14b`; Oracle and the Parliament example
bots/reviewer use `llama3.1:8b`. The standalone English-only Qwen Modelfile is
included; the complete deployed Sentinel persona was not available outside its
app database, which was **not opened**. The clearly labeled persona example is
not a claim to reproduce that private configuration.

Test host: RTX 3060 12 GB, 32 GB RAM, EndeavourOS Linux. Qwen 14B Q4_K_M occupies
approximately 9 GB VRAM (context/KV cache and other allocations add overhead).
That is the tested configuration, not a guaranteed minimum. CPU-only Ollama can
work much more slowly; smaller models reduce memory use. Budget SSD space for both
LLMs, Kokoro (~338 MB downloaded assets), Whisper and virtual environments. Do not
assume Qwen and Llama fit in GPU memory simultaneously: Ollama may unload/reload or
offload. Whisper small.en uses CPU int8 here; ffmpeg and a browser microphone on
HTTPS or localhost are required. Keep time and disk budgets for builds/downloads.

## 1. Ollama and pile-up guard

Install Ollama from https://ollama.com/download, start it on loopback, then:

```bash
ollama pull huihui_ai/qwen3-abliterated:14b
ollama pull llama3.1:8b
```

For a system service, an administrator can run `sudo systemctl edit ollama` and add:

```ini
[Service]
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_QUEUE=4"
```

Then reload systemd and restart Ollama deliberately when no jobs are running.
These are instructions only: the export process does not install, restart or
reconfigure services. Never expose port 11434 publicly. A short queue rejects
excess requests instead of allowing an unbounded pile-up; it is not a scheduler.

## 2. Sentinel / Open WebUI

Use Python 3.11 and a separate virtual environment (or adapt to your supported
upstream deployment). From a checkout at `~/alien-stack`:

```bash
python3.11 -m venv sentinel/.venv
sentinel/.venv/bin/pip install open-webui
cp sentinel/sentinel.env.example sentinel/sentinel.env
# Edit sentinel.env: exact URL, CORS origin, desired authentication policy.
mkdir -p sentinel/data
set -a; . sentinel/sentinel.env; set +a
DATA_DIR="$PWD/sentinel/data" sentinel/.venv/bin/open-webui serve --host 127.0.0.1 --port 8080
```

The env intentionally has signups OFF. Bootstrap the first admin on loopback only
by temporarily allowing signup, then disable it **before** publishing. Keep login
required. Review and pin a current Open WebUI release yourself before production;
this export does not vendor or pin the upstream app. Optional unit and persona
provenance are in sentinel/. Persistent config is disabled in this clean example
so the anti-pile-up env takes effect. Automation, tag, follow-up and autocomplete
generation are disabled; no downtime trigger or scheduling logic is added.

## 3. Oracle voice studio

See oracle/README.md for voice grammar, blend/overlay settings, model licensing,
setup commands and tagged-script examples. Use Python 3.11, a C/C++ toolchain,
ffmpeg, libsndfile and espeak-ng. From oracle/ create `venv311`, install
requirements.txt, and download these separately (weights are not in git):

```bash
cd oracle
python3.11 -m venv venv311
venv311/bin/pip install -r requirements-talk.txt
mkdir -p models
curl -fL --retry 2 https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx -o models/kokoro-v1.0.onnx
curl -fL --retry 2 https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin -o models/voices-v1.0.bin
venv311/bin/python gui.py --host 127.0.0.1 --port 7860
```

Verify downloaded files using upstream release integrity information when provided.
requirements-talk.txt adds faster-whisper 1.2.1 (verified installed on the source
host), missing from the in-progress source requirements.txt/lock.
Whisper downloads small.en into ignored models/whisper/ on first talk use (internet
required for that first download). These model downloads are not performed by the
export. Open http://localhost:7860/oracle/ and choose the Talk tab; use HTTPS for remote mic access.
For a tagged script, pipe stdin to `oracle/hera-say` (see its help). The voice blend,
duet and tags are preserved in the source; generated clips/settings/history are not.

Snapshot talk limits: six requests/minute/visitor, 24/minute global; 20-second
recording, 1.5 MB body, at most three spoken reply sentences / 110 generated tokens.
The prompt asks for under 45 words (not a hard word-count guarantee). General public
render/Oracle limits: six/minute/visitor, 30/minute global, single render/model slot
and a small bounded waiting queue. Inspect code for authoritative enforcement;
limits are process-local, not a distributed quota. Talk code appears wired end to
end in this snapshot but has not been runtime-tested as part of packaging; re-sync
after the active implementation finishes.

## 4. Parliament

See parliament/README.md. Copy the .example.json files to their runtime filenames,
start guest.py before the loop (it generates a fresh local token), then start the
loop. Unit templates use ~/alien-stack. The optional private board is port 8765;
the guest service is port 8766. Only the latter is intended for tunnel ingress.
The X bridge imports connector-fed JSON and prepares drafts only: it cannot post
automatically and contains no X credentials. No conversation tree is included.

## 5. Optional Cloudflare tunnel

See cloudflare/README.md and config.example.yml. Create your own named tunnel and
DNS routes; replace example.com, YOUR_TUNNEL_UUID and the credentials path locally.
The three origins are loopback ports 7860, 8766 and 8080, with a 404 catch-all.
No certificate, credentials JSON or real tunnel identity is included.

## Security, privacy and deployment caveats

This is a public-ready **source export**, not a security audit or production SLA.
Oracle has intentional public features and no user login; same-origin checks,
body/turn limits and rate limits reduce abuse but do not replace authentication.
Use HTTPS and consider Access/WAF/authentication before making it internet-facing.
Review forwarding-header trust when changing the proxy. Public visitor recordings,
transcripts and generated output are sensitive local runtime data: keep retention
short and never commit them. Do not expose Ollama, the private board or admin ports.

No keys, member/passcode files, real guest URL, host identity, LAN addresses, app
DB, chat history, logs, generated audio, caches, backups, model weights, tunnel
credentials, phone APKs, image workflows, or cryptocurrency node are included.
Runtime credentials are generated on your host, ignored by git, and stay local.
Fill in your domain/CORS and tunnel placeholders, choose your own persona and X
watch list, and review install paths before enabling examples. No live service was
modified or restarted while assembling this export. Nothing is pushed by this repo.

## License

Original stack code/export: MIT, copyright bucktuna 2026 (LICENSE). Third-party
components and models retain their own licenses; see oracle/licenses/ and upstream
projects. This repository does not relicense Open WebUI or downloaded model weights.

## Validation status

See EXPORT-NOTES.md: syntax checks pass and credentials scans are clean, but the
source regression tests have deployment-fixture/stale-assertion failures. This
export does not claim a clean CI run or a completed Talk runtime test.
