"""The Oracle: turn a free-form direction into a validated voicepipe script via local Ollama."""
import json
import os
import re
import time
import urllib.request

from voicepipe import Style, parse

OLLAMA = os.environ.get('ORACLE_OLLAMA', 'http://127.0.0.1:11434')
MODEL = os.environ.get('ORACLE_MODEL', 'llama3.1:8b')
KEEP_ALIVE = '5m'
MAX_SECONDS = 90
MAX_CHARS = 1600

GRAMMAR = r"""
You write scripts for "Oracle", a speech synthesizer with sound-design markup.
Plain text is spoken. Markup:

WRAP TAGS (wrap words: <tag ...>words</tag>; they nest; always close them):
  <pitch +4>..</pitch>              shift pitch in semitones (-12..+12 sensible, max ±24)
  <speed 1.3>..</speed>             speaking rate multiplier (0.5..2)
  <formant 0.9>..</formant>         voice depth: <1 deeper/bigger, >1 smaller/brighter (0.7..1.4)
  <contour 0,4,-3>..</contour>      pitch glide across the phrase (semitone points)
  <gain 0.7>..</gain>               volume (0..2)
  <warble 0.5s -6,+6,0,+12>..</warble>     stepped pitch: every 0.5s go to the next value in the list (cycles)
  <pitchstep every=2s range=-8..+8>..</pitchstep>   random pitch step every N seconds
  <jumpy chance=0.3 max=12>..</jumpy>      sudden random pitch jumps
  <wobble rate=8 depth=3>..</wobble>       fast vibrato (rate Hz, depth semitones)
  <flip every=0.4s voices=af_heart,am_adam>..</flip>   alternate voices every N seconds (or every=2w for words); 'main' = the main voice
  <chaos level=3>..</chaos>                random stutters, bitcrush, reverse, tape-stop, pitch steps, voice flips (level 1..5)
  <robot>..</robot>   <radio>..</radio>   <telephone>..</telephone>   <echo delay=0.25s feedback=0.4>..</echo>

SOUND CUES (inserted between words, square brackets):
  [breath in 0.4s] [breath out 0.4s] [pause 0.5s]
  [whistle up 1s] [whistle down 1s] [whistle arch 1s] [whistle C6,E6,G6 1.2s]
  [sweep up 0.6s] [sweep down 0.6s]
  [glitch mix 0.4s] (modes: mix bitcrush stutter slip ring bleep)
  [chaos 0.8s] [reverse 0.5s] [tapestop 0.6s] [tapestart 0.5s]

VOICES (English): af_heart af_bella af_nicole af_sarah af_sky af_nova af_jessica af_river af_alloy af_aoede af_kore
  am_adam am_michael am_onyx am_echo am_eric am_fenrir am_liam am_puck am_santa
  bf_emma bf_alice bf_isabella bf_lily bm_george bm_daniel bm_fable bm_lewis
  (af=American woman, am=American man, bf=British woman, bm=British man)

OVERLAY = a second voice speaking the SAME words at the same time on top of the main voice (a duet/double),
  with its own pitch offset (e.g. -12 = an octave below) and volume. Use it when asked for doubling,
  harmony, octave, two voices at once, demonic/choir/ghost layers.

RULES:
- Map timing requests literally: "every two seconds" -> every=2s; "every half second" -> 0.5s.
  "change pitch every N seconds" -> <pitchstep every=Ns range=-6..+6> (random) or <warble Ns ...> (patterned).
- Put the requested effect around the words it applies to (often the whole story).
- Use only the tags above, spelled exactly. Close every wrap tag. No other < > [ ] characters.
- Keep it under about 60 seconds of speech (roughly 150 words) unless asked for shorter.
- Write the actual content requested (story, poem, line), vivid and natural, not a description of it.
- Follow-up requests ("now faster", "higher", "same but robot") modify the PREVIOUS script/settings: keep its words
  and change only what was asked (use the speed/pitch fields for global changes).
- "pitch" and "speed" fields are GLOBAL settings; keep the current ones unless asked to change them.

Reply ONLY with JSON:
{"title": short title, "script": "...", "voice": voice id, "pitch": number, "speed": number,
 "overlay": {"enabled": bool, "voice": voice id, "gain": 0..1, "pitch": semitones, "delay_ms": 0..300}}
"""

EXAMPLES = [
    ('Say good morning like a sleepy robot that keeps rebooting.\nCurrent settings: {"voice":"af_heart","pitch":0,"speed":1,"overlay":{"enabled":false}}',
     {"title": "Rebooting Morning", "script": "<robot><speed 0.85>Good. Morning.</speed></robot> [glitch stutter 0.3s] [tapestop 0.5s] [pause 0.4s] [tapestart 0.4s] <robot>System restored. <chaos level=2>Good morning, good morning, good mor</chaos></robot> [glitch bleep 0.3s] <robot>Coffee required.</robot>",
      "voice": "am_michael", "pitch": 0, "speed": 1, "overlay": {"enabled": False}}),
    ('Whisper a ghost line with a deep octave voice underneath, pitch changing every second.\nCurrent settings: {"voice":"af_heart","pitch":0,"speed":1,"overlay":{"enabled":false}}',
     {"title": "Octave Ghost", "script": "[breath in 0.5s] <echo delay=0.3s feedback=0.45><pitchstep every=1s range=-5..+5>I have been waiting in these walls for a very long time.</pitchstep></echo> [breath out 0.6s] <formant 0.85>Come closer.</formant>",
      "voice": "af_sky", "pitch": 0, "speed": 0.9, "overlay": {"enabled": True, "voice": "am_onyx", "gain": 0.6, "pitch": -12, "delay_ms": 25}}),
]


def chat(messages, timeout=180):
    body = json.dumps({'model': MODEL, 'messages': messages, 'stream': False, 'format': 'json',
                       'keep_alive': KEEP_ALIVE, 'options': {'temperature': 0.7, 'num_ctx': 4096}}).encode()
    req = urllib.request.Request(OLLAMA + '/api/chat', data=body, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())['message']['content']


def estimate_seconds(script, speed=1):
    words = len(re.sub(r'<[^>]*>|\[[^\]]*\]', ' ', script).split())
    cues = sum(float(m) for m in re.findall(r'\[[^\]]*?([\d.]+)s\]', script) if re.fullmatch(r'\d*\.?\d+', m))
    return words/2.6/max(speed, .5) + cues


def strip_markup(script):
    return ' '.join(re.sub(r'<[^>]*>|\[[^\]]*\]|[<>\[\]]', ' ', script).split())


def repair(script, voices):
    """Fallback: drop invalid cues/tags; then all wrap tags; last resort plain text."""
    from voicepipe import check_cue
    tokens = [t for t in re.split(r'(<[^>]*>|\[[^\]]*\])', script) if t]
    kept, dropped = [], set()
    for t in tokens:
        if t.startswith('['):
            try:
                check_cue(t[1:-1].strip()); kept.append(t)
            except ValueError:
                pass
        elif t.startswith('</'):
            kept.append(t)
        elif t.startswith('<'):
            name = (t[1:-1].split() or ['?'])[0].lower()
            try:
                parse(f'{t}x</{name}>', Style(), voices); kept.append(t)
            except ValueError:
                dropped.add(name)
        else:
            kept.append(re.sub(r'[<>\[\]]', ' ', t))
    balanced, stack = [], []
    for t in kept:
        if t.startswith('</'):
            name = t[2:-1].strip().lower()
            if name in stack:
                while stack and stack[-1] != name:
                    balanced.append(f'</{stack.pop()}>')
                stack.pop(); balanced.append(t)
        elif t.startswith('<'):
            stack.append(t[1:-1].split()[0].lower()); balanced.append(t)
        else:
            balanced.append(t)
    balanced += [f'</{n}>' for n in reversed(stack)]
    for candidate in (''.join(kept), ''.join(balanced), ''.join(t for t in kept if not t.startswith('<'))):
        try:
            parse(candidate, Style(), voices)
            return candidate
        except ValueError:
            continue
    return strip_markup(script) or 'Hello.'


def clamp_length(script, speed):
    if estimate_seconds(script, speed) <= MAX_SECONDS and len(script) <= MAX_CHARS:
        return script
    plain = strip_markup(script)
    words = plain.split()[:int(MAX_SECONDS*2.6*min(speed, 1))]
    return ' '.join(words)


def clean_settings(raw, defaults, voice_names):
    s = dict(defaults or {})
    def num(v, lo, hi, d):
        try:
            v = float(v)
            return min(hi, max(lo, v)) if v == v else d
        except (TypeError, ValueError):
            return d
    if isinstance(raw.get('voice'), str) and raw['voice'] in voice_names:
        s['voice'] = raw['voice']
    s.setdefault('voice', 'af_heart')
    s['pitch'] = num(raw.get('pitch', s.get('pitch', 0)), -12, 12, s.get('pitch', 0))
    s['speed'] = num(raw.get('speed', s.get('speed', 1)), .5, 2, s.get('speed', 1))
    ov = raw.get('overlay')
    base_ov = dict((defaults or {}).get('overlay') or {})
    if isinstance(ov, dict):
        on = bool(ov.get('enabled', True)) and ov.get('voice') in voice_names
        if on:
            base_ov = {'enabled': True, 'voice': ov['voice'], 'gain': num(ov.get('gain', .5), 0, 1, .5),
                       'pitch': num(ov.get('pitch', 0), -12, 12, 0), 'delay_ms': num(ov.get('delay_ms', 0), 0, 500, 0)}
        elif 'enabled' in ov and not ov.get('enabled'):
            base_ov = {**base_ov, 'enabled': False}
    s['overlay'] = base_ov or {'enabled': False}
    return s


def ask(prompt, defaults, history, voice_names):
    """Returns dict(title, script, settings, repaired, attempts, llm_seconds, model)."""
    msgs = [{'role': 'system', 'content': GRAMMAR}]
    for u, a in EXAMPLES:
        msgs += [{'role': 'user', 'content': u}, {'role': 'assistant', 'content': json.dumps(a)}]
    for turn in history[-6:]:
        if turn.get('role') == 'user':
            msgs.append({'role': 'user', 'content': turn['text']})
        elif turn.get('role') == 'oracle' and turn.get('script'):
            st = turn.get('settings') or {}
            msgs.append({'role': 'assistant', 'content': json.dumps({'title': turn.get('title'), 'script': turn['script'],
                         'voice': st.get('voice'), 'pitch': st.get('pitch'), 'speed': st.get('speed'), 'overlay': st.get('overlay')})})
    cur = {k: defaults.get(k) for k in ('voice', 'pitch', 'speed', 'overlay')}
    msgs.append({'role': 'user', 'content': f'{prompt.strip()}\nCurrent settings: {json.dumps(cur)}'})
    started, attempts, repaired = time.monotonic(), 0, False
    data, err = None, None
    for attempts in (1, 2):
        try:
            data = json.loads(chat(msgs))
            script = str(data.get('script', '')).strip()
            if not script:
                raise ValueError('empty script')
            st = clean_settings(data, defaults, voice_names)
            parse(script, Style(pitch=st['pitch'], speed=st['speed']), voice_names)
            err = None
            break
        except (ValueError, json.JSONDecodeError) as e:
            err = str(e)
            if attempts == 1:
                msgs.append({'role': 'assistant', 'content': json.dumps(data) if isinstance(data, dict) else '{}'})
                msgs.append({'role': 'user', 'content': f'That script failed validation: {err}. Fix it. Use only the listed tags, close every tag, and reply with the full JSON again.'})
    if not isinstance(data, dict):
        data = {}
    script = str(data.get('script', '')).strip() or strip_markup(prompt)
    if err:
        script, repaired = repair(script, voice_names), True
    settings = clean_settings(data, defaults, voice_names)
    clamped = clamp_length(script, settings['speed'])
    if clamped != script:
        script, repaired = clamped, True
    parse(script, Style(pitch=settings['pitch'], speed=settings['speed']), voice_names)  # must hold now
    title = re.sub(r'\s+', ' ', str(data.get('title') or 'Oracle clip'))[:60]
    return dict(title=title, script=script, settings=settings, repaired=repaired, attempts=attempts,
                llm_seconds=round(time.monotonic()-started, 2), model=MODEL)
