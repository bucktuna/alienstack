# Export notes

For Talk use requirements-talk.txt: the source requirements.txt/lock had not yet
listed faster-whisper; the add-on pins the installed 1.2.1 version. Choose the Talk
tab at /oracle/ (there is no separate /talk/ route). This is a work-in-progress
snapshot; full runtime validation was not performed during export. Generated
clips, saved settings/history, model weights and model checksums are not included.

# Oracle — expressive voice studio (Voicepipe engine)

Built and rendered entirely on the bot's Linux box, not on any of Buck's computers.
English TTS with a warm stock synthetic voice, independent speech pitch / timbre controls,
portamento whistles, noise-shaped breaths, and playful speech-derived granular glitches.
This is a **working synthesis pipeline and voice preset**, not a newly trained/cloned model.
No personal recordings, reference voices, impersonation, or real-person cloning were used.

## Components / licensing

- **Kokoro-82M v1.0**, full-precision ONNX, 24 kHz; model declared **Apache-2.0** by
  [hexgrad](https://huggingface.co/hexgrad/Kokoro-82M). `kokoro-onnx` 0.6.1 runtime is MIT.
  Kokoro includes a neural waveform decoder already; there is no extra neural model download.
- Default: stock `af_heart`. Demo: 75% `af_heart` + 25% `af_bella` embedding blend. These
  are distributed synthetic presets, not Buck's biological voice. Blend is normalized to sum 1.
- WORLD / `pyworld` 0.3.5 (BSD-3-Clause): analyze F0, spectral envelope and aperiodicity;
  alter F0 without resampling the speech, then resynthesize. Formants remain approximately
  unchanged unless explicitly warped. This avoids chipmunk timbre from naive resampling.
- NumPy / SciPy procedural DSP; soundfile/libsndfile for output. eSpeak-NG phonemizer is
  supplied by `espeakng-loader` (GPL-3.0 component); preserve third-party notices if distributing.
- FFmpeg makes the MP3. Local dependencies retain their upstream licenses in site-packages.
- `licenses/` preserves the upstream Kokoro model card, its Apache license text and runtime MIT
  notice. The model card also credits Koniwa / tnc (CC BY 3.0) and SIWIS (CC BY 4.0) training data.
  Check those upstream notices before redistribution. No model was trained here.

## Use the environment already built on the box

```bash
cd $HOME/alien-stack/oracle
source venv311/bin/activate
python voicepipe.py --text 'Hello there [breath in 0.45s] my king. <pitch +4>This part is higher.</pitch> [whistle up 1.2s] [glitch mix 0.4s] Goodbye.' --pitch 0 --seed 42 --out out.wav
```

No network access is needed after setup. The CLI uses CPU only and four inference threads, with no server or
background service. The optional GUI below runs its own local web server. Relative output paths follow your current directory; default model
paths are resolved relative to `voicepipe.py`.

### Rebuild the demo

```bash
python voicepipe.py --script demo.txt --voice 'af_heart:0.75,af_bella:0.25' --seed 42 --out demo.wav
ffmpeg -y -i demo.wav -codec:a libmp3lame -b:a 192k demo.mp3
python -m unittest -v test_voicepipe.py
```

Every render writes a sidecar `out.json` with precise event timestamps, style settings,
duration, peak, RMS, finiteness, and any master attenuation. WAV is mono PCM16 / 24 kHz.

## Clean setup (Linux)

Use Python 3.11 (tested), a C/C++ compiler and development headers for building pyworld.
On EndeavourOS install prerequisites **yourself**, only when you want to install it there:

```bash
sudo pacman -S --needed base-devel python ffmpeg libsndfile espeak-ng
```

A rolling system Python may be newer than our tested runtime. With `uv` installed:

```bash
uv python install 3.11
uv venv --python 3.11 venv311
source venv311/bin/activate
uv pip install -r requirements.txt
# Alternatively, with a python3.11 executable already available:
# python3.11 -m venv venv311
# source venv311/bin/activate
# python -m pip install -r requirements.txt
mkdir -p models
curl -fL --retry 2 https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx -o models/kokoro-v1.0.onnx
curl -fL --retry 2 https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin -o models/voices-v1.0.bin
```

Downloads total approximately 338 MB decimal. No private local model checksum
record is exported; verify downloads against upstream integrity information. `requirements.lock` captures
all installed runtime versions. `requirements.txt` pins the direct runtime requirements.
The setuptools pin is necessary because pyworld still imports `pkg_resources`.

This box lacked g++, so WORLD was built using an isolated pip `ziglang` compiler. The
already-built environment needs no compiler at runtime. If recreating on a minimal box
without a system compiler, `uv pip install ziglang==0.17.1`, then set `CC` / `CXX` to the
`tools/cc` / `tools/cxx` wrappers while installing pyworld. The exported wrappers use the active Python environment; activate venv311 before using them.

## Inline markup

Speech tags can be nested. Close them in reverse order. Unsupported cues, unknown tags,
unclosed tags and out-of-range values are rejected rather than spoken as instructions.
Each markup boundary is a separate TTS phrase: prefer whole clauses, not single words.

| Markup | Meaning |
|---|---|
| `<pitch +4>words</pitch>` | Add 4 semitones to global speech pitch; -24..24 combined range |
| `<contour 0,3,-2>words</contour>` | Smooth F0 offsets over the phrase; 2..20 comma-separated semitone points; adds to global/local pitch |
| `<speed 0.85>words</speed>` | Slower TTS; 1 normal; 0.5..2 combined range |
| `<formant 0.9>words</formant>` | Lower/darker spectral envelope independently of F0; 0.7..1.4 combined range |
| `<gain 0.6>words or cues</gain>` | Local amplitude multiplier; 0..2 per tag |
| `[breath in 0.45s]` | Shaped, filtered inhale-like noise |
| `[breath out 0.6s]` | Softer falling exhale-like noise |
| `[whistle up 1.2s]` | Rising airy whistle with vibrato, tiny harmonics and short echo |
| `[whistle down 1s]` / `[whistle arch 1s]` | Falling or arched whistle |
| `[whistle C6,E6,G6,E6,C6 1.5s]` | Musical pitch anchors with smooth portamento |
| `[whistle 700,1200,900 1s]` | Same, in Hz (100..5000) |
| `[sweep down 0.5s]` | Pure electronic pitch sweep; accepts same contours/notes as whistle |
| `[glitch mix 0.6s]` | Seeded montage of all glitch modes, using prior speech's tail |
| `[glitch bitcrush 0.4s]` | Sample-and-hold downsampling and coarse quantization |
| `[glitch stutter 0.4s]` | Short repeated speech grains |
| `[glitch slip 0.4s]` | Reversed / offset buffer grains |
| `[glitch ring 0.4s]` | Ring-modulated speech grains |
| `[glitch bleep 0.4s]` | Pitched electronic bleeps |
| `[pause 0.3s]` | Explicit silence |

Durations use `s`, range 0.02..30 seconds per cue. Defaults: breaths 0.5 s, other cues 0.6 s.
CLI: `--pitch`, `--speed`, `--formant`, `--voice`, `--seed`, `--model`, `--voices`, `--out`.
`--script file.txt` is an alternative to `--text`. A voice blend is, for example,
`--voice 'af_heart:0.75,af_bella:0.25'` (individual weights 0..1, normalized).
Global pitch and speech contours apply to **speech**, not musical cues; whistle notes / Hz
are absolute. Gain applies to both. Nested pitch tags add; speed and formant tags multiply;
inner contours replace outer contours. Timbre/pitch should be used moderately for best quality.

## Quality decisions and boundaries

- WORLD runs only when pitch/contour/formant actually changes; ordinary speech retains the
  original neural waveform. This keeps the normal voice at full model quality.
- Sound cues have click-reducing ramps and shaped envelopes. Master only attenuates if needed
  to a peak ceiling of 0.90; it never boosts a quiet breath into a loud hiss. No hard clipping.
- 45 ms edit gaps make mixed events readable; musical cue tails stay inside requested duration.
- Whistles have gentle vibrato, air and delay; breaths are synthetic noise design, **not**
  anatomically modeled recorded breaths. Glitches are deliberate, not synthesis corruption.
- Extreme WORLD shifts sound robotic; it cannot invent new natural emotional delivery.
  Word-by-word tags disrupt phrase rhythm, and contours are timed across the phrase, not phonemes.
- Glitches/whistles/breaths are reproducible with `--seed`; neural/WORLD bit-identical output
  across different OS/CPU/library versions is not guaranteed. No streaming or real-time mic input.
- This is not a trained personal voice and does not modify the Grok Bot app or its live-call voice.
  No integration with Parliament, Ollama, Open WebUI or ComfyUI was performed.

## EndeavourOS / RTX 3060 12 GB / 32 GB RAM

This CPU pipeline fits comfortably; GPU is unnecessary. Copy the project files/models later,
recreate its venv with the commands above, then render locally. No desktop access was used here.
A CUDA ONNX backend could reduce Kokoro latency, but would not improve the same model's sound;
WORLD and the procedural DSP would remain CPU work. This script explicitly chooses CPU today.

For a genuinely richer *next* voice, the Apache-2.0
[Qwen3-TTS-12Hz-1.7B-VoiceDesign](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign)
can design an original synthetic voice from a description rather than cloning a person.
The 1.7B CustomVoice model offers instruction-driven style with built-in presets instead.
Both are plausible RTX 3060 candidates in fp16/bf16, batch 1, short utterances with several
GB free VRAM; exact peak memory and speed depend on context/backend and have **not** been
benchmarked on Buck's GPU. Keep other large GPU jobs unloaded for the trial. Use a separate
Python environment, current CUDA-compatible PyTorch, and `qwen-tts`; initially use PyTorch
SDPA to avoid a FlashAttention compilation dependency. Official docs recommend FlashAttention 2
when supported to reduce memory. A 0.6B CustomVoice fallback uses less memory but lacks the
1.7B's instruction control. This is a worthwhile quality experiment, not part of this install.
Retain this effects/markup renderer behind that future backend. A replacement neural vocoder
alone is not drop-in: it must match acoustic features, sample rate and training distribution.

Upstream checked for the optional upgrade:
https://github.com/QwenLM/Qwen3-TTS

## Verification

`test_voicepipe.py` covers parser nesting/errors, reproducible finite cues, endpoints/peak
bounds, WORLD's one-octave F0 change with duration preservation, and demo duration/RMS/clipping.
`verify_audio.py` additionally checks decoded WAV and MP3, writes `verification.json`, and
reports all exact event boundaries from the render sidecar. This is objective rendering/DSP
verification, not a claim that a human has auditioned the demo.

### Demo listening map (seconds from start)

| Time | What plays |
|---|---|
| 0.00–3.07 | Warm normal introduction: “Hello, my king…” |
| 3.12–3.57 | Gentle inhale |
| 3.61–6.28 | +3 semitone speech, with a subtle rising/falling F0 contour |
| 6.32–7.67 | Airy C–E–G–E–C whistle melody with portamento / vibrato |
| 7.72–9.40 | “Now, a tiny malfunction.” in the normal timbre |
| 9.45–10.10 | Short, seeded, speech-derived glitch montage |
| 10.14–11.45 | “Perfectly intentional.” with descending pitch / darker formants |
| 11.49–11.94 | Electronic falling pitch sweep |
| 11.99–12.39 | Soft exhale |
| 12.43–14.16 | Normal-voice closing punchline |

Decoded WAV: 14.203 s, peak 0.61676, 4× oversampled peak 0.62279, RMS 0.08817.
Decoded MP3: 14.203 s, peak 0.58637. Both finite, non-silent, zero clipped samples.
The five automated tests passed; the combined speed/formant/pitch CLI also rendered.

# The Voice — mobile web studio

The GUI reuses the exact same `voicepipe.py` synthesis pipeline. FastAPI serves a compact,
no-CDN HTML/CSS/JavaScript app in the Parliament palette: plum `#24132e`, copper `#dfa27f`,
with soft dark panels and mobile layouts down to 412 px and below.

## Launch on the box

```bash
cd $HOME/alien-stack/oracle
source venv311/bin/activate
python gui.py --host 127.0.0.1 --port 7860
```

Open http://127.0.0.1:7860/ on the same computer. The current session leaves this server
running on the box. This loopback address is **not a phone-accessible public link**. No
public tunnel or deployment has been created. Ctrl+C stops the server; it is not installed
as an autostart service. The API reference is at `/api/docs`; health is `/api/health`.

## Studio controls

- Script editor and one-tap insertion at the cursor: inhale, exhale, pause, whistle up/down/
  arch/melody, electronic sweep, mixed glitches and each individual glitch type.
- Shape buttons wrap selected words in pitch, contour, formant, speed or gain tags. With
  no selection they insert an editable `your words` placeholder. Android cursor/selection
  behavior has DOM-level tests, but has not been checked on a physical Android browser.
- All 54 bundled Kokoro voice embeddings in pickers; up to three voices blended with
  individual weight sliders. Uncheck Blend to use just the base voice.
- Global pitch, pace, formant, numeric seed and Shuffle controls. The GUI pitch slider
  spans -12..+12 semitones; the underlying API/CLI allow -24..+24.
- Render progress reflects completed speech/effect segments, followed by encoding.
- Native audio player, waveform, clickable timestamped speech/effect cards, WAV / MP3 /
  timing-JSON downloads. Playback waits for your tap, respecting mobile autoplay rules.
- Four example scripts and a collapsible pocket markup guide.

Existing voice entries include multiple languages, but this pipeline currently phonemizes
English (`en-us`). English presets, especially `af_*` / `am_*`, are recommended. This is
not a claim of fully supported multilingual synthesis.

## On the host / EndeavourOS, when you choose to install it

the host now has a live install (see "Installed on the host" below). Copy the project there (including `web/` and the
model files, or download the models), then recreate the environment using the setup above.
The updated requirements include FastAPI, Uvicorn and HTTPX.

Local desktop only:

```bash
cd /your/chosen/path/voicepipe
source venv311/bin/activate
python gui.py --host 127.0.0.1 --port 7860
# Open http://127.0.0.1:7860/ on the host.
```

Phone on the same trusted Wi-Fi:

```bash
python gui.py --host 0.0.0.0 --port 7860
# On the phone, open http://the host_LAN_IP:7860/
```

Use the host's actual LAN IP in that URL, not `0.0.0.0`. If a firewall is active, allow
TCP 7860 only from the phone / trusted LAN. Do not add a router port-forward.

Phone over an already configured Tailscale network:

```bash
python gui.py --host the host_TAILSCALE_IP --port 7860
# On the phone, connected to the same tailnet:
# http://the host_TAILSCALE_IP:7860/
```

Replace the placeholder with the host's actual 100.x Tailscale IP. Binding directly to
that address avoids exposing the service on every LAN interface. Use tailnet ACLs to
limit access. This does not set up Tailscale, Funnel, TLS, or remote connectivity for you.

## GUI verification and safety boundaries

```bash
# With the GUI running:
python test_gui_api.py
python -m unittest -v test_voicepipe.py
node --check web/studio.js
# Optional DOM interaction tests (requires Node/npm):
npm install --prefix .ui-tests --no-package-lock --no-audit --no-fund jsdom
node test_gui_dom.cjs
```

`gui-api-verification.json` records a real HTTP render through this GUI's API: the 14.203 s
example, all 54 voice options, intermediate progress, 10 events, 420 waveform bins, decoded
WAV/MP3 downloads, finite/non-silent audio and zero clipping. `gui-demo.wav` / `.mp3` are
the files downloaded through HTTP. Input errors, cross-origin requests and simultaneous
render requests were also checked. DOM tests exercise selection wrapping, insertion,
controls and the actual Render-button/API/player/download flow without a browser engine.
They are not a substitute for browser screenshots or physical-phone testing.

- **Trusted personal use only:** there is no login or multi-user isolation. Do not expose
  this server to the public internet. An origin check rejects cross-origin browser
  requests, but is not authentication. LAN/tailnet peers who can reach the port can use it.
- One render at a time; further requests receive 429. There is no cancel button or durable
  render queue. Closing a tab does not cancel synthesis. Jobs are forgotten on restart.
- WAV, MP3 and JSON outputs remain in `renders/` until you remove them. The most recent
  100 jobs are retained in memory; there is no automatic disk cleanup.
- First render loads the model; later renders reuse it. A GPU is not used. Long scripts
  consume more time/memory; the editor/API cap text at 6,000 characters.
- Error messages appear in the GUI; non-input failures are logged in the server console.
- The optional `/?job=JOB_UUID` URL opens an existing completed performance during this
  server session. It does not persist across restarts or provide a public share link.
- Current verification is API + DOM based. Actual phone/desktop browser screenshots have
  not been captured in this executor because no sanctioned browser/desktop tool is available.

## Installed on the host (live service — the one codebase for the GUI and Hera's clips)

Installed 2026-11-08 in `~/alien-stack/oracle` with a Python 3.11.18 venv (`~/alien-stack/oracle/venv`,
interpreter fetched by `uv python install 3.11`; system Python 3.14 is not used). Models were
downloaded from the kokoro-onnx `model-files-v1.0` release; SHA-256 matches `models/SHA256SUMS`.

Service: `~/.config/systemd/user/voice-studio.service` (user unit, `Restart=on-failure`,
enabled; user lingering is on, so it starts at boot). It runs
`venv/bin/python gui.py --host 0.0.0.0 --port 7860`.

```bash
systemctl --user status voice-studio
systemctl --user restart voice-studio      # after editing gui.py / voicepipe.py / web/
journalctl --user -u voice-studio -f
```

Open it: on the host `http://127.0.0.1:7860/`; on the phone (same Wi-Fi)
`http://127.0.0.1:7860/` (DHCP address — if it changes, check `ip -4 addr show enp4s0`).
The same-origin guard accepts requests whose Origin matches the Host the browser used (so the
LAN address works) and still rejects unrelated cross-origin requests (403).

Firewall: firewalld and ufw are both active and neither allows 7860 yet. Run yourself:

```bash
sudo firewall-cmd --permanent --zone=public --add-port=7860/tcp && sudo firewall-cmd --reload
sudo ufw allow from 127.0.0.1/24 to any port 7860 proto tcp
```

### hera-say — scripted clips through the running service

`~/alien-stack/oracle/hera-say` sends a marked-up script (stdin) to the running service's HTTP API
on `http://127.0.0.1:7860` (override with `--url` or `VOICE_STUDIO_URL`). It never loads a
second model copy. It writes the MP3, keeps the WAV and timing JSON beside it, and prints the
MP3 path.

```bash
echo 'Good evening, my king. [breath in 0.4s] <pitch +3>The parliament is in session.</pitch> [whistle C6,E6,G6 1.2s] [glitch stutter 0.35s] And I have opinions.' \
  | ~/alien-stack/oracle/hera-say --voice 'bf_emma:0.7,af_heart:0.3' --pitch -1 --seed 7 \
      --out ~/alien-stack/oracle/clips/NAME.mp3
# -> $HOME/alien-stack/oracle/clips/NAME.mp3  (+ NAME.wav, NAME.json)
```

Options: `--voice` (one voice, or up to 3 `name:weight` blends), `--pitch` (-24..24 semitones),
`--speed` (0.5..2), `--formant` (0.7..1.4), `--seed`, `--out` (required), `--url`,
`--timeout` (default 600 s). Exit code is non-zero with a message on any error.

API endpoints used:
- `POST /api/render` with JSON `{text, voice, blends:[{voice,weight}], pitch, speed, formant, seed}` → `202 {id, status_url}`; `429` while another render runs (hera-say waits and retries).
- `GET /api/jobs/{id}` → poll until `status` is `ready` (or `error`).
- `GET /audio/{id}.mp3`, `/audio/{id}.wav`, `/audio/{id}.json` → downloads.
- Also available: `GET /api/health`, `GET /api/config` (voice list), docs at `/api/docs`.

Note: the service renders one job at a time; server-side copies also accumulate in
`~/alien-stack/oracle/renders/` until removed.

## Studio redesign (2026-11-08): friendly UI, extreme tags, duet overlay, The Oracle

### The UI (phone-first)
- **The Oracle**: describe what you want and it writes, voices and plays it (see below).
- **Moods**: one-tap recipes (Calm Narrator, Robot Meltdown, Haunted, Chipmunk Panic, Late-Night Radio,
  Octave Duet, Voice Roulette, Call From Space, plus the four original samples). Tapping one loads its
  script and settings, renders and auto-plays it.
- **What should it say?**: a friendly editor. Sounds show as chips and styled words are highlighted with a
  label. Sound buttons insert at the cursor; style buttons wrap the selected words. The raw markup and seed
  are under **Advanced**.
- **Voice**: main voice picker with names and descriptions; **Blend** (a slider between two voices);
  **Duet** (overlay, see below).
- **Shape**: Pitch, Speed and Voice depth (formant) sliders.
- **Make it talk**: progress bar, player and MP3/WAV download. **Recent clips** lets you replay, download,
  delete, or tap a title to load its script again.
- **How tags work**: a help sheet with every tag and a "Try it" button for each.
- UI settings are saved server-side (`settings.json`) and act as the defaults for texted Oracle prompts.

### Tag reference (new tags marked ★; all nest with each other and with the original tags)
Wraps:
- `<pitch +4>…</pitch>`, `<speed 1.3>…</speed>`, `<formant 0.9>…</formant>`, `<contour 0,4,-3>…</contour>`, `<gain 0.7>…</gain>`
- ★ `<warble 0.5s -6,+6,0,+12>…</warble>`: stepped pitch on a fixed interval; the steps cycle (also `every=0.5s steps=…`).
- ★ `<pitchstep every=0.5s range=-8..+8 seed=3>…</pitchstep>`: a random pitch step every N s (`seed` optional and reproducible).
- ★ `<jumpy chance=0.3 max=12>…</jumpy>`: sudden random jumps (checked every 0.25 s, held 0.08–0.3 s).
- ★ `<wobble rate=8 depth=3>…</wobble>`: fast vibrato (0.5–30 Hz, 0–12 semitones).
- ★ `<flip every=0.4s voices=af_heart,am_adam,bf_emma>…</flip>`: switch voices every N seconds (each voice is rendered, WORLD-time-aligned and spliced with 12 ms crossfades) or `every=2w` for every N words. `main` = the chosen main voice.
- ★ `<chaos level=1..5>…</chaos>`: random pitch steps, stutters, bitcrush, reverse snippets, tape stop and speed-up; level ≥3 adds voice flips. Seeded and reproducible.
- ★ `<robot>…</robot>` (monotone WORLD resynthesis + ring/comb), `<radio>…</radio>`, `<telephone>…</telephone>`, `<echo delay=0.25s feedback=0.4 mix=0.4>…</echo>`.
Cues:
- `[breath in|out 0.4s]`, `[pause 0.5s]`, `[whistle up|down|arch|C6,E6,G6 1s]`, `[sweep up|down 0.6s]`, `[glitch mix|bitcrush|stutter|slip|ring|bleep 0.4s]`
- ★ `[tapestop 0.6s]`, `[tapestart 0.5s]`, `[reverse 0.5s]` (all built from the end of the previous speech), `[chaos 0.8s]` / `[chaos 3 0.8s]`.
Safety: pitch is clamped to ±24 st and f0 to 40–1500 Hz. Every segment is peak-matched, and the final mix goes through a
smoothed peak limiter with a tanh knee (ceiling 0.89, never boosts). Unknown or mismatched tags fail with a clear error.

Example:
```
[breath in 0.4s] <warble 0.5s -6,+6,0,+12>Up the stairs and down.</warble> <flip every=2w voices=main,am_adam>Two words each now.</flip>
[tapestop] <robot><jumpy chance=0.4 max=10>Systems nominal.</jumpy></robot> <chaos level=4>Everything is fine.</chaos> [reverse 0.5s]
```

### Duet overlay
A second Kokoro voice renders the same text. It is WORLD time-stretched to the main voice's duration, given the
same pitch curve plus its own offset, delayed, then mixed on top and peak-matched to the main voice. API field:
`"overlay": {"voice": "am_onyx", "gain": 0.5, "pitch": -12, "delay_ms": 20}`. CLI/hera-say: `--overlay-voice am_onyx
--overlay-gain 0.5 --overlay-pitch -12 --overlay-delay 20`.

### The Oracle
Type a direction (e.g. "tell a short story about a red fox while you change the pitch every two seconds").
The server asks the local Ollama (`127.0.0.1:11434`, model `llama3.1:8b`, the one already used on this machine;
override with `ORACLE_MODEL`, `keep_alive` 5 min) with the full tag grammar and few-shot examples. It gets back JSON
`{title, script, voice, pitch, speed, overlay}`, validates the script with the voicepipe parser (one retry with
the error, then auto-repair: drop bad tags and close unclosed ones) and clamps it to about 90 s. Then it renders
and auto-plays the clip. The script is loaded into the editor so you can tweak it and re-render. The conversation
is kept in `oracle-history.json` (the last 6 turns are sent as context), so "now faster and higher" changes the last
clip. The older script-input mic uses browser speech recognition where supported; the separate Talk tab uses local faster-whisper.
Chrome/Android blocks the mic on plain-http LAN pages, so it is normally hidden there; typing always works.

Endpoints (same Origin check as everything else): `POST /api/oracle` `{prompt, settings?}`,
`GET/DELETE /api/oracle/history`.

### Text the Oracle (LAN only, no SMS)
`POST /api/oracle/text` takes a plain-text body (or `{"text": …}`) and uses the saved UI settings as defaults.
Non-browser clients must send the header `X-Oracle-Token: <contents of ~/alien-stack/oracle/.oracle-token>` (file mode
600, generated on first start). Add `?wait=1` to block until the MP3 is ready. Set the locally generated token header in your HTTP client (not shown in this public example). The response is JSON with `title`,
`script`, absolute `mp3` / `wav` URLs, `status`, `llm_seconds`, `render_seconds`.
```bash
curl -s -X POST 'http://127.0.0.1:7860/api/oracle/text?wait=1' \
  -H 'Content-Type: text/plain' \
  --data 'tell a short story about a red fox, pitch changing every two seconds'
```
Android **HTTP Shortcuts** / Tasker: method POST, URL as above, header `X-Oracle-Token`, body = a text-input
variable. Response handling: open the `mp3` field (JSON path `mp3`) in the browser or media player. iOS Shortcuts:
"Get contents of URL" with the same method, header and body, then "Get dictionary value: mp3" → "Open URLs".
This only works on the home Wi-Fi. Real SMS would need a paid gateway (e.g. Twilio) and a separate, authenticated,
public webhook; it is deliberately not set up. The text endpoint is LAN-only; public browser features have separate guards, not a login.

### hera-say additions
`--overlay-voice/--overlay-gain/--overlay-pitch/--overlay-delay`, `--title`, `--json '{…}'` (merged into the render
body), and `--oracle` (stdin is a free-form Oracle request; it reads the token file itself). All new tags pass through
unchanged in scripts.
```bash
echo '<chaos level=3>Hello</chaos> [tapestop]' | ~/alien-stack/oracle/hera-say --voice 'bf_emma:0.7,af_heart:0.3' \
  --overlay-voice am_onyx --overlay-gain 0.4 --overlay-pitch -12 --out ~/alien-stack/oracle/clips/x.mp3
echo 'a haunted lighthouse keeper, pitch wandering every second' | ~/alien-stack/oracle/hera-say --oracle --out ~/alien-stack/oracle/clips/o.mp3
```
New HTTP API endpoints: `GET /api/clips`, `DELETE /api/clips/{id}`, `GET/PUT /api/settings`; `/api/render` accepts `overlay`, `title`, `source`.
Tests: `venv/bin/python -m unittest test_tags test_voicepipe`.

## Renamed to "Oracle" (2026-11-08)
Everything user-visible is now called **Oracle** (page title, header, help sheet, API title/config, download file
names, hera-say help). The internal names stay the same so nothing breaks: the systemd user service is still
`voice-studio.service`, the install path is still `~/alien-stack/oracle`, and every API route is unchanged. The app is
also served at `/oracle` and `/oracle/` (same page; assets and API calls use absolute paths, so both work), and `/`
still works.

Layout cleanup: Ask the Oracle sits at the top. Below it are a one-row Moods carousel and "Your script" (editor,
collapsible ＋ Sounds / ✦ Styles toolbars, Make it talk, player, Advanced). Voice, blend, duet and shape controls are
in one collapsible **Voice settings** section (open by default on desktop). **Recent clips** is collapsed. Help is
behind the **?** icon.

Public-link guards (only for requests that arrive through a Cloudflare tunnel, detected by `Cf-Connecting-IP`/`Cf-Ray`;
LAN behaviour is unchanged): 6 render/Oracle requests a minute per visitor and 30 a minute in total. DELETE, PUT
/api/settings and /api/oracle/text are refused. Each visitor sees only their own clips and Oracle chat. At most 3
Oracle requests wait in the queue.
