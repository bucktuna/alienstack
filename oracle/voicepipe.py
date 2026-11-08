#!/usr/bin/env python3
"""Local Kokoro + WORLD + procedural sound-design voice instrument.

Markup: <tag ...>speech</tag> wraps change how speech is shaped (they nest);
[cue ...] inserts a sound. See README "Tag reference".
"""
import argparse
import json
import math
import re
from dataclasses import dataclass, replace, field
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy import signal

SR = 24000
ROOT = Path(__file__).resolve().parent
FRAME_MS = 5
CHAOS_VOICES = ('af_heart', 'am_adam', 'bf_emma', 'am_onyx', 'af_sky', 'bm_george', 'am_puck', 'af_nicole')


@dataclass
class Style:
    pitch: float = 0
    speed: float = 1
    formant: float = 1
    contour: tuple = (0,)
    gain: float = 1
    warble: tuple = None      # (interval_s, (steps...))
    pitchstep: tuple = None   # (every_s, lo, hi, seed|None)
    jumpy: tuple = None       # (chance, max_semitones)
    wobble: tuple = None      # (rate_hz, depth_semitones)
    flip: tuple = None        # ('s'|'w', every, (voices...))
    chaos: int = 0
    robot: bool = False
    fx: tuple = ()            # post effects, outer -> inner: ('radio',), ('telephone',), ('echo', delay, feedback, mix)


def bounded(v, lo, hi, name):
    try:
        v = float(str(v).strip().removeprefix('+'))
    except ValueError:
        raise ValueError(f'{name} must be a number')
    if not np.isfinite(v) or not lo <= v <= hi:
        raise ValueError(f'{name} must be in [{lo}, {hi}]')
    return v


def seconds(v, lo, hi, name):
    return bounded(str(v).strip().removesuffix('s'), lo, hi, name)


def tag_args(value):
    """'0.5s -6,+6 key=val' -> (positional list, keyword dict)."""
    pos, kw = [], {}
    for part in value.split():
        if '=' in part:
            k, _, v = part.partition('=')
            kw[k.strip().lower()] = v.strip()
        else:
            pos.append(part)
    return pos, kw


def semitone_list(text, name, lo=1, hi=32):
    vals = tuple(bounded(v, -24, 24, name) for v in text.split(',') if v.strip())
    if not lo <= len(vals) <= hi:
        raise ValueError(f'{name} needs {lo}..{hi} comma-separated semitone values')
    return vals


def parse_range(text, name):
    m = re.fullmatch(r'\s*([+-]?[\d.]+)\s*\.\.\s*([+-]?[\d.]+)\s*', text)
    if not m:
        raise ValueError(f'{name} range must look like -8..+8')
    lo, hi = bounded(m.group(1), -24, 24, name), bounded(m.group(2), -24, 24, name)
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def apply_tag(name, value, style, voices=None):
    pos, kw = tag_args(value)
    def only(*allowed):
        bad = set(kw) - set(allowed)
        if bad:
            raise ValueError(f'<{name}> does not understand {", ".join(sorted(bad))}')
    if name == 'pitch':
        style.pitch += bounded(value, -24, 24, name)
    elif name == 'speed':
        style.speed = min(2, max(.5, style.speed*bounded(value, .5, 2, name)))  # nested: clamp, don't fail
    elif name == 'formant':
        style.formant = min(1.4, max(.7, style.formant*bounded(value, .7, 1.4, name)))
    elif name == 'gain':
        style.gain *= bounded(value, 0, 2, name)
    elif name == 'contour':
        style.contour = tuple(bounded(v, -24, 24, name) for v in value.split(','))
        if not 2 <= len(style.contour) <= 20:
            raise ValueError('contour needs 2..20 comma-separated semitone points')
    elif name == 'warble':
        only('every', 'steps')
        every = kw.get('every') or next((p for p in pos if p.endswith('s')), None)
        steps = kw.get('steps') or next((p for p in pos if not p.endswith('s')), None)
        if not every or not steps:
            raise ValueError('Use <warble 0.5s -6,+6,0,+12>')
        style.warble = (seconds(every, .05, 10, 'warble interval'), semitone_list(steps, 'warble steps'))
    elif name == 'pitchstep':
        only('every', 'range', 'seed')
        every = kw.get('every') or next((p for p in pos if p.endswith('s')), '0.5s')
        rng_txt = kw.get('range') or next((p for p in pos if '..' in p), '-8..+8')
        seed = kw.get('seed') or next((p for p in pos if p.isdigit()), None)
        lo, hi = parse_range(rng_txt, 'pitchstep')
        style.pitchstep = (seconds(every, .05, 10, 'pitchstep every'), lo, hi, int(bounded(seed, 0, 2**31, 'seed')) if seed is not None else None)
    elif name == 'jumpy':
        only('chance', 'max')
        style.jumpy = (bounded(kw.get('chance', pos[0] if pos else .3), 0, 1, 'jumpy chance'),
                       bounded(kw.get('max', pos[1] if len(pos) > 1 else 12), 0, 24, 'jumpy max'))
    elif name == 'wobble':
        only('rate', 'depth')
        style.wobble = (bounded(kw.get('rate', pos[0] if pos else 8), .5, 30, 'wobble rate'),
                        bounded(kw.get('depth', pos[1] if len(pos) > 1 else 3), 0, 12, 'wobble depth'))
    elif name == 'flip':
        only('every', 'voices')
        every = kw.get('every') or (pos[0] if pos else '0.4s')
        names = tuple(v.strip() for v in kw.get('voices', pos[1] if len(pos) > 1 else '').split(',') if v.strip())
        if not 2 <= len(names) <= 4:
            raise ValueError('flip needs voices=a,b (2..4 voices)')
        if voices is not None:
            for v in names:
                if v != 'main' and v not in voices:
                    raise ValueError(f'Unknown voice in flip: {v}')
        if every.endswith('w'):
            style.flip = ('w', int(bounded(every[:-1], 1, 20, 'flip words')), names)
        else:
            style.flip = ('s', seconds(every, .1, 10, 'flip every'), names)
    elif name == 'chaos':
        only('level', 'seed')
        style.chaos = int(bounded(kw.get('level', pos[0] if pos else 3), 1, 5, 'chaos level'))
    elif name == 'robot':
        if value.strip():
            raise ValueError('<robot> takes no options')
        style.robot = True
    elif name in ('radio', 'telephone'):
        if value.strip():
            raise ValueError(f'<{name}> takes no options')
        style.fx = style.fx + ((name,),)
    elif name == 'echo':
        only('delay', 'feedback', 'mix')
        d = seconds(kw.get('delay', pos[0] if pos else .22), .03, 1, 'echo delay')
        fb = bounded(kw.get('feedback', .35), 0, .8, 'echo feedback')
        mix = bounded(kw.get('mix', .4), 0, 1, 'echo mix')
        style.fx = style.fx + (('echo', d, fb, mix),)
    else:
        raise ValueError(f'Unknown tag: {name}')


def parse(text, base, voices=None):
    """Strict stack parser. Fail closed on unknown/mismatched markup."""
    stack = [('root', base)]
    result = []
    for token in re.split(r'(<[^>]*>|\[[^\]]*\])', text):
        if not token:
            continue
        if token.startswith('<'):
            body = token[1:-1].strip()
            if body.startswith('/'):
                if len(stack) == 1 or stack[-1][0] != body[1:].strip():
                    raise ValueError(f'Mismatched closing tag: {token}')
                stack.pop()
                continue
            name, _, value = body.partition(' ')
            name = name.lower()
            style = replace(stack[-1][1])
            apply_tag(name, value.strip(), style, voices)
            style.pitch = min(24, max(-24, style.pitch))
            stack.append((name, style))
        elif token.startswith('['):
            spec = token[1:-1].strip()
            check_cue(spec)
            result.append(('effect', spec, replace(stack[-1][1])))
        elif token.strip():
            if any(c in token for c in '<>[]'):
                raise ValueError('Unmatched markup character')
            result.append(('speech', ' '.join(token.split()), replace(stack[-1][1])))
    if len(stack) != 1:
        raise ValueError(f'Unclosed tag: {stack[-1][0]}')
    if not result:
        raise ValueError('Empty script')
    return result


# ---------------------------------------------------------------- DSP helpers
def fade(x, seconds=.012):
    x = np.array(x, dtype=np.float64, copy=True)
    n = min(int(SR * seconds), len(x)//2)
    if n:
        ramp = np.sin(np.linspace(0, np.pi/2, n)) ** 2
        x[:n] *= ramp
        x[-n:] *= ramp[::-1]
    return x


def normalize(x, peak=.3):
    return x * (peak / max(float(np.max(np.abs(x))), 1e-9))


def peak(x):
    return float(np.max(np.abs(x))) if len(x) else 0.0


def trim_silence(x, thr=.008, pad=.02):
    idx = np.flatnonzero(np.abs(x) > thr)
    if not len(idx):
        return x
    p = int(pad*SR)
    return x[max(0, idx[0]-p):idx[-1]+p]


def crossfade_concat(parts, ms=12):
    parts = [p for p in parts if len(p)]
    if not parts:
        return np.zeros(0)
    out = np.array(parts[0], dtype=np.float64)
    for p in parts[1:]:
        n = min(int(SR*ms/1000), len(out)//2, len(p)//2)
        if n:
            r = np.linspace(0, 1, n)
            mid = out[-n:]*(1-r) + p[:n]*r
            out = np.concatenate([out[:-n], mid, p[n:]])
        else:
            out = np.concatenate([out, p])
    return out


def soft_limit(x, ceiling=.89):
    """Peak limiter (smoothed gain) + gentle tanh knee; never makes quiet audio louder."""
    if not len(x):
        return x
    from scipy.ndimage import maximum_filter1d, uniform_filter1d
    env = maximum_filter1d(np.abs(x), size=int(.012*SR))
    g = np.minimum(1, (ceiling*.92)/np.maximum(env, 1e-9))
    g = uniform_filter1d(maximum_filter1d(-g, size=int(.012*SR))*-1, size=int(.006*SR))
    y = x*g
    knee = ceiling*.8
    over = np.abs(y) > knee
    y[over] = np.sign(y[over])*(knee + (ceiling-knee)*np.tanh((np.abs(y[over])-knee)/(ceiling-knee)))
    return y


def world_analyze(x):
    import pyworld as pw
    x = np.ascontiguousarray(x, dtype=np.float64)
    f0, times = pw.dio(x, SR, f0_floor=65, f0_ceil=900, frame_period=FRAME_MS)
    f0 = pw.stonemask(x, f0, times, SR)
    return f0, times, pw.cheaptrick(x, f0, times, SR), pw.d4c(x, f0, times, SR)


def fit_length(y, n):
    return y[:n] if len(y) >= n else np.pad(y, (0, n-len(y)))


def world_stretch(x, n_target):
    """Change duration to n_target samples without changing pitch (WORLD frame resampling)."""
    if len(x) == n_target or len(x) < 1024:
        return fit_length(np.asarray(x, dtype=np.float64), n_target)
    import pyworld as pw
    f0, times, sp, ap = world_analyze(x)
    nf = max(2, int(round(len(f0)*n_target/len(x))))
    src = np.linspace(0, len(f0)-1, nf)
    idx = np.clip(np.round(src).astype(int), 0, len(f0)-1)
    lo = np.floor(src).astype(int); hi = np.minimum(lo+1, len(f0)-1); w = (src-lo)[:, None]
    sp2 = np.ascontiguousarray(sp[lo]*(1-w) + sp[hi]*w)
    ap2 = np.ascontiguousarray(ap[lo]*(1-w) + ap[hi]*w)
    y = pw.synthesize(np.ascontiguousarray(f0[idx]), sp2, ap2, SR, frame_period=FRAME_MS)
    return fit_length(y, n_target)


def build_curve(style, total_s, rng):
    """Return f(times_s) -> semitone offset. Random parameters are drawn now (seeded)."""
    contour = np.array(style.contour, dtype=float)
    parts = []
    if style.warble:
        iv, steps = style.warble
        st = np.array(steps)
        parts.append(lambda t: st[(np.floor(t/iv).astype(int)) % len(st)])
    if style.pitchstep:
        every, lo, hi, seed = style.pitchstep
        r = np.random.default_rng(seed) if seed is not None else rng
        vals = r.uniform(lo, hi, int(total_s/every)+2)
        parts.append(lambda t, v=vals, e=every: v[np.minimum((t/e).astype(int), len(v)-1)])
    if style.jumpy:
        chance, mx = style.jumpy
        jumps, t0 = [], 0.0
        while t0 < total_s:
            if rng.random() < chance:
                hold = rng.uniform(.08, .3)
                jumps.append((t0, t0+hold, float(rng.choice([-1, 1])*rng.uniform(.4*mx, mx))))
            t0 += .25
        def jf(t, jumps=jumps):
            out = np.zeros_like(t)
            for a, b, v in jumps:
                out[(t >= a) & (t < b)] = v
            return out
        parts.append(jf)
    if style.wobble:
        rate, depth = style.wobble
        parts.append(lambda t: depth*np.sin(2*np.pi*rate*t))
    if style.chaos:
        lvl = style.chaos
        every = [.6, .45, .33, .25, .18][lvl-1]
        n = int(total_s/every)+2
        on = rng.random(n) < (.3+.12*lvl)
        vals = np.where(on, rng.uniform(-2.5*lvl, 2.5*lvl, n), 0)
        parts.append(lambda t, v=vals, e=every: v[np.minimum((t/e).astype(int), len(v)-1)])
    def curve(t):
        t = np.asarray(t, dtype=float)
        u = t/max(total_s, 1e-6)
        c = style.pitch + np.interp(u, np.linspace(0, 1, len(contour)), contour)
        for p in parts:
            c = c + p(t)
        return np.clip(c, -24, 24)
    curve.static = not parts and style.pitch == 0 and not np.any(contour)
    return curve


def world_transform(x, style, curve=None, robot=None):
    robot = style.robot if robot is None else robot
    if curve is None:
        curve = build_curve(replace(style, warble=None, pitchstep=None, jumpy=None, wobble=None, chaos=0), len(x)/SR, np.random.default_rng(0))
    if getattr(curve, 'static', False) and style.formant == 1 and not robot:
        return x
    import pyworld as pw
    f0, times, sp, ap = world_analyze(x)
    voiced = f0 > 0
    if robot and voiced.any():
        f0[voiced] = np.median(f0[voiced])
        ap = np.ascontiguousarray(ap*.35)
    f0[voiced] *= 2 ** (curve(times)[voiced]/12)
    f0[voiced] = np.clip(f0[voiced], 40, 1500)
    if style.formant != 1:
        bins = np.arange(sp.shape[1])
        sp = np.ascontiguousarray([np.interp(bins / style.formant, bins, row) for row in sp])
    y = pw.synthesize(f0, sp, ap, SR, frame_period=FRAME_MS)
    if robot:
        t = np.arange(len(y))/SR
        y = .75*y + .25*y*np.sin(2*np.pi*55*t)
        d = int(.006*SR)
        y[d:] += .35*y[:-d].copy()
    return fit_length(y, len(x))


def tapestop(seg, start=1.0, end=0.0):
    """Playback rate ramps start->end across len(seg) output samples (tape stop / spin-up)."""
    n = len(seg)
    if n < 4:
        return seg
    rate = np.linspace(start, end, n)
    pos = np.cumsum(rate) - rate[0]
    return np.interp(np.clip(pos, 0, n-1), np.arange(n), seg)


def bitcrush(seg, rng):
    hold = int(rng.integers(3, 10))
    y = np.repeat(seg[::hold], hold)[:len(seg)]
    q = rng.choice([6, 10, 16])
    return np.round(y*q)/q


def chaos_fx(x, level, rng):
    """Seeded in-place chaos: stutters, bitcrush, reverse snippets, tape stop/speed-up."""
    n = len(x)
    out, pos = [], 0
    prob = .08 + .13*level
    while pos < n:
        w = min(int(rng.uniform(.1, .32)*SR), n-pos)
        seg = x[pos:pos+w]
        if w > 400 and rng.random() < prob:
            op = rng.choice(['stutter', 'bitcrush', 'reverse', 'tapestop', 'speedup'])
            if op == 'stutter':
                g = max(64, int(rng.uniform(.03, .08)*SR))
                seg = np.resize(fade(seg[:g], .004), w)
            elif op == 'bitcrush':
                seg = bitcrush(seg, rng)
            elif op == 'reverse':
                seg = seg[::-1]
            elif op == 'tapestop':
                seg = tapestop(seg, 1, 0)
            else:
                more = x[pos:pos+int(w*1.6)]
                seg = signal.resample(more, w) if len(more) > w else seg
                pos += len(more) - w
            seg = fade(seg, .004)
        out.append(seg)
        pos += w
    y = np.concatenate(out) if out else x
    return y if peak(y) <= max(peak(x), 1e-9) else y*(peak(x)/peak(y))


def apply_fx(y, fx, rng):
    for item in reversed(fx):  # innermost first
        kind = item[0]
        if kind in ('radio', 'telephone'):
            lo, hi, order = (500, 4500, 4) if kind == 'radio' else (320, 3300, 6)
            p = peak(y)
            z = signal.sosfilt(signal.butter(order, [lo, hi], btype='bandpass', fs=SR, output='sos'), y)
            z = np.tanh(z/max(peak(z), 1e-9)*(2.2 if kind == 'radio' else 3.0))
            if kind == 'telephone':
                mu = 255
                c = np.sign(z)*np.log1p(mu*np.abs(z))/np.log1p(mu)
                c = np.round(c*48)/48
                z = np.sign(c)*((1+mu)**np.abs(c)-1)/mu
            else:
                z = z*(1+.06*np.sin(2*np.pi*3*np.arange(len(z))/SR)) + .012*rng.normal(size=len(z))
            y = z*(p/max(peak(z), 1e-9))
        elif kind == 'echo':
            _, d, fb, mix = item
            dn = int(d*SR)
            taps = max(1, min(8, int(np.ceil(np.log(.03)/np.log(fb))) if fb > 0 else 1))
            tail = min(dn*taps, int(1.5*SR))
            out = np.pad(y, (0, tail))
            wet = np.zeros_like(out)
            for k in range(1, taps+1):
                if k*dn >= len(out):
                    break
                seg = y[:len(out)-k*dn]
                wet[k*dn:k*dn+len(seg)] += (fb**(k-1))*seg
            p = peak(y)
            y = out + mix*wet
            y = fade(y*(p/max(peak(y), 1e-9)) if peak(y) > p else y, .03)
    return y


def note_hz(name):
    m = re.fullmatch(r'([A-Ga-g])([#b]?)([0-8])', name)
    if not m:
        return bounded(name, 100, 5000, 'whistle frequency')
    key, accidental, octave = m.groups()
    midi = 12 * (int(octave)+1) + {'C':0,'D':2,'E':4,'F':5,'G':7,'A':9,'B':11}[key.upper()]
    midi += {'':0, '#':1, 'b':-1}[accidental]
    return 440 * 2**((midi-69)/12)


def duration(s):
    return bounded(s.removesuffix('s'), .02, 30, 'duration')


CUES = ('pause', 'breath', 'whistle', 'sweep', 'glitch', 'tapestop', 'tapestart', 'reverse', 'chaos')


def check_cue(spec):
    """Validate a cue without rendering (parse-time)."""
    effect(spec, np.random.default_rng(0), None, dry=True)


def tail_material(last, dur):
    if last is None or len(trim_silence(last)) < 512:
        t = np.arange(int(SR*max(dur, .1)))/SR
        return .3*np.sin(2*np.pi*220*t)*np.sin(np.pi*np.linspace(0, 1, len(t)))
    m = trim_silence(last)
    return m[-int(SR*dur):] if len(m) > SR*dur else np.resize(m, int(SR*dur))


def effect(spec, rng, last, dry=False):
    parts = spec.split()
    if not parts:
        raise ValueError('Empty sound cue')
    name = parts.pop(0).lower()
    if name not in CUES:
        raise ValueError(f'Unknown cue: {name}')
    default = {'breath': .5, 'reverse': .5, 'chaos': .8}.get(name, .6)
    dur = duration(parts.pop()) if parts and re.fullmatch(r'[\d.]+s', parts[-1]) else default
    if name in ('pause', 'tapestop', 'tapestart', 'reverse') and parts:
        raise ValueError(f'[{name}] accepts only a duration, e.g. [{name} 0.5s]')
    if name == 'breath' and (len(parts) > 1 or (parts and parts[0] not in ('in', 'out'))):
        raise ValueError('Use [breath in|out 0.5s]')
    if name in ('whistle', 'sweep') and len(parts) > 1:
        raise ValueError('whistle/sweep accepts one contour or comma-separated melody')
    if name in ('whistle', 'sweep') and parts and parts[0] not in ('up', 'down', 'arch'):
        [note_hz(p) for p in parts[0].split(',')]
    if name == 'glitch' and (len(parts) > 1 or (parts and parts[0] not in ('mix','bitcrush','stutter','slip','ring','bleep'))):
        raise ValueError('Unknown glitch mode')
    if name == 'chaos' and len(parts) > 1:
        raise ValueError('Use [chaos 0.8s] or [chaos 4 0.8s]')
    if name == 'chaos' and parts:
        bounded(parts[0], 1, 5, 'chaos level')
    if dry:
        return None
    t = np.arange(round(SR*dur))/SR
    n = len(t)
    if name == 'pause':
        return np.zeros(n)
    if name in ('tapestop', 'tapestart'):
        m = tail_material(last, dur*.55)
        y = tapestop(np.resize(m, n), 1, 0) if name == 'tapestop' else tapestop(np.resize(m, n), 0.05, 1)
        return fade(normalize(y, min(.5, max(peak(m), .1))), .01)
    if name == 'reverse':
        m = tail_material(last, dur)
        return fade(normalize(np.resize(m[::-1], n), min(.5, max(peak(m), .1))), .02)
    if name == 'chaos':
        lvl = int(float(parts[0])) if parts else 5
        m = np.resize(tail_material(last, max(dur, .3)), n)
        y = fit_length(chaos_fx(m, lvl, rng), n)
        y = .7*y + .3*effect(f'glitch mix {dur}s', rng, last)
        return fade(normalize(np.tanh(y*1.3), .28), .012)
    if name == 'breath':
        direction = parts[0] if parts else 'out'
        noise = rng.normal(size=n)
        sos = signal.butter(3, [450 if direction == 'in' else 250, 6500], btype='bandpass', fs=SR, output='sos')
        y = signal.sosfilt(sos, noise)
        u = np.linspace(0, 1, n)
        env = (np.sin(np.pi*u)**.9) * ((.3+.7*u) if direction == 'in' else (1-.65*u))
        y *= env * (1 + .08*np.sin(2*np.pi*17*t))
        return fade(normalize(y, .12), .035)
    if name in ('whistle', 'sweep'):
        mode = parts[0] if parts else 'up'
        if mode in ('up', 'down'):
            points = [700, 1500] if mode == 'up' else [1500, 600]
        elif mode == 'arch':
            points = [800, 1450, 1200, 650]
        else:
            points = [note_hz(p) for p in mode.split(',')]
        f = np.exp(np.interp(t / dur, np.linspace(0, 1, len(points)), np.log(points)))
        f *= 1 + .0035*np.sin(2*np.pi*5.6*t)*(1-np.exp(-t*8))
        phase = 2*np.pi*np.cumsum(f)/SR
        env = np.sin(np.pi*np.linspace(0,1,n))**.5
        if name == 'whistle':
            airy = signal.sosfilt(signal.butter(2, [1800,7000], btype='bandpass', fs=SR, output='sos'), rng.normal(size=n))
            y = (.27*np.sin(phase) + .012*np.sin(2*phase) + .009*airy) * env
        else:
            y = .22*(np.sin(phase) + .15*np.sin(2*phase)) * env
        delay = int(.085*SR)
        if n > delay:
            y[delay:] += .13*y[:-delay].copy()
        return fade(y, .025)
    mode = parts[0] if parts else 'mix'
    material = last[np.abs(last)>.015] if last is not None else np.array([])
    if len(material) < 512:
        material = np.sin(2*np.pi*220*np.arange(SR//2)/SR)
    y = np.zeros(n)
    cursor = 0
    while cursor < n:
        size = min(int(rng.uniform(.035,.095)*SR), n-cursor)
        tt = np.arange(size)/SR
        chosen = rng.choice(['bitcrush','stutter','slip','ring','bleep']) if mode == 'mix' else mode
        start = rng.integers(0, max(1,len(material)-size))
        grain = np.resize(material[start:start+size], size)
        if chosen == 'bitcrush':
            hold = int(rng.integers(3,10))
            grain = np.repeat(grain[::hold], hold)[:size]
            grain = np.round(grain*12)/12
        elif chosen == 'stutter':
            period = min(len(grain), int(rng.uniform(.012,.025)*SR))
            grain = np.resize(grain[:period], size)
        elif chosen == 'slip':
            grain = np.roll(grain[::-1], int(size*.3))
        elif chosen == 'ring':
            grain *= np.sin(2*np.pi*rng.choice([311,523,733])*tt)
        else:
            freq = float(rng.choice([523.25,659.25,783.99,1046.5]))
            grain = .4*np.sin(2*np.pi*freq*tt)*np.sin(np.pi*np.linspace(0,1,size))
        y[cursor:cursor+size] = fade(grain,.004)
        cursor += size
    return fade(normalize(np.tanh(y*1.4), .25), .012)


class Pipeline:
    def __init__(self, model, voices, voice='af_heart', seed=7):
        self.model, self.voices, self.voice = str(model), str(voices), voice
        self.rng = np.random.default_rng(seed)
        self.engine = None
        self.overlay = None  # dict(voice, gain 0..1, pitch semitones, delay_ms)

    def _engine(self):
        if self.engine is None:
            import onnxruntime as ort
            from kokoro_onnx import Kokoro
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 4
            opts.inter_op_num_threads = 1
            session = ort.InferenceSession(self.model, sess_options=opts, providers=['CPUExecutionProvider'])
            self.engine = Kokoro.from_session(session, self.voices)
        return self.engine

    def voice_style(self, spec):
        eng = self._engine()
        if spec == 'main':
            spec = self.voice
        if ':' not in spec and ',' not in spec:
            return spec
        blends = []
        for item in spec.split(','):
            name, _, weight = item.partition(':')
            blends.append((eng.get_voice_style(name.strip()), bounded(weight or 1, 0, 1, 'voice weight')))
        total = sum(w for _, w in blends)
        if total <= 0:
            raise ValueError('Voice blend weights must sum to more than zero')
        return sum(v*w/total for v, w in blends).astype(np.float32)

    def raw(self, text, voice_spec, speed):
        audio, sr = self._engine().create(text, voice=self.voice_style(voice_spec), speed=speed, lang='en-us')
        audio = np.asarray(audio, dtype=np.float64)
        return signal.resample_poly(audio, SR, sr) if sr != SR else audio

    def raw_flip(self, text, style):
        mode, every, names = style.flip
        if mode == 'w':
            words = text.split()
            groups = [' '.join(words[i:i+every]) for i in range(0, len(words), every)]
            return crossfade_concat([trim_silence(self.raw(g, names[i % len(names)], style.speed)) for i, g in enumerate(groups)], 20)
        takes = [self.raw(text, v, style.speed) for v in names]
        ref = len(takes[0])
        takes = [takes[0]] + [world_stretch(t, ref) for t in takes[1:]]
        step = max(int(every*SR), 256)
        pieces = [takes[(i//step) % len(takes)][i:i+step] for i in range(0, ref, step)]
        return crossfade_concat(pieces, 12)

    def speak(self, text, style):
        if style.flip is None and style.chaos >= 3:
            picks = list(self.rng.choice(CHAOS_VOICES, size=2, replace=False))
            style = replace(style, flip=('s', [.6, .6, .5, .35, .25][style.chaos-1], ('main', *picks)))
        main = self.raw_flip(text, style) if style.flip else self.raw(text, self.voice, style.speed)
        curve = build_curve(style, len(main)/SR, self.rng)
        y = world_transform(main, style, curve)
        ov = self.overlay
        if ov and ov.get('voice') and ov.get('gain', 0) > 0:
            o = world_stretch(self.raw(text, ov['voice'], style.speed), len(main))
            opitch = float(ov.get('pitch', 0))
            ocurve = lambda t: np.clip(curve(t)+opitch, -24, 24)
            o = world_transform(o, style, ocurve)
            d = int(SR*float(ov.get('delay_ms', 0))/1000)
            mixed = np.pad(y, (0, d)) + float(ov['gain'])*np.pad(o, (d, 0))
            p = peak(y)
            y = mixed*(p/peak(mixed)) if peak(mixed) > p > 0 else mixed
        if style.chaos:
            y = chaos_fx(y, style.chaos, self.rng)
        y = apply_fx(y, style.fx, self.rng)
        return fade(y * style.gain)

    def render(self, text, base, progress=None, voices=None):
        events = parse(text, base, voices)
        chunks, timeline, last = [], [], None
        position = 0
        for event_index, (kind, value, style) in enumerate(events):
            if kind == 'speech':
                y = self.speak(value, style)
                last = y
            else:
                y = effect(value, self.rng, last)
                if style.robot or style.fx:
                    y = apply_fx(y, style.fx, self.rng)
                y = y * style.gain
            if not np.isfinite(y).all():
                raise ValueError('Nonfinite synthesis output')
            timeline.append(dict(kind=kind, content=value, start=round(position/SR,3), end=round((position+len(y))/SR,3), style=vars(style)))
            chunks.append(y)
            position += len(y)
            chunks.append(np.zeros(round(.045*SR)))
            position += round(.045*SR)
            if progress is not None:
                progress(event_index + 1, len(events), kind)
        audio = soft_limit(np.concatenate(chunks))
        pk = float(np.max(np.abs(audio)))
        gain = min(1, .89/max(pk,1e-9))
        audio *= gain
        stats = dict(sample_rate=SR, duration=len(audio)/SR, peak=float(np.max(np.abs(audio))), rms=float(np.sqrt(np.mean(audio**2))), attenuation_db=20*np.log10(gain), finite=bool(np.isfinite(audio).all()), overlay=self.overlay, events=timeline)
        return audio, stats


def main():
    p = argparse.ArgumentParser(description=__doc__)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument('--text')
    source.add_argument('--script', type=Path)
    p.add_argument('--pitch', type=float, default=0, help='Global speech semitone shift')
    p.add_argument('--speed', type=float, default=1)
    p.add_argument('--formant', type=float, default=1, help='Spectral-envelope scale; 1 preserves formants')
    p.add_argument('--seed', type=int, default=7)
    p.add_argument('--voice', default='af_heart')
    p.add_argument('--overlay-voice'); p.add_argument('--overlay-gain', type=float, default=.5)
    p.add_argument('--overlay-pitch', type=float, default=0); p.add_argument('--overlay-delay', type=float, default=0, help='ms')
    p.add_argument('--model', type=Path, default=ROOT/'models/kokoro-v1.0.onnx')
    p.add_argument('--voices', type=Path, default=ROOT/'models/voices-v1.0.bin')
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    try:
        style = Style(bounded(a.pitch,-24,24,'pitch'), bounded(a.speed,.5,2,'speed'), bounded(a.formant,.7,1.4,'formant'))
        pipe = Pipeline(a.model,a.voices,a.voice,a.seed)
        if a.overlay_voice:
            pipe.overlay = dict(voice=a.overlay_voice, gain=bounded(a.overlay_gain,0,1,'overlay gain'), pitch=bounded(a.overlay_pitch,-12,12,'overlay pitch'), delay_ms=bounded(a.overlay_delay,0,500,'overlay delay'))
        audio, stats = pipe.render(a.script.read_text() if a.script else a.text, style)
        a.out.parent.mkdir(parents=True, exist_ok=True)
        sf.write(a.out, audio, SR, subtype='PCM_16', format='WAV')
        a.out.with_suffix('.json').write_text(json.dumps(stats,indent=2)+'\n')
        print(json.dumps({k:v for k,v in stats.items() if k != 'events'},indent=2))
        print(f'Wrote {a.out} and {a.out.with_suffix(".json")}')
    except (ValueError, FileNotFoundError) as e:
        p.error(str(e))

if __name__ == '__main__':
    main()
