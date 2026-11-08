"""Tests for the extreme glitch tags, overlay plumbing and Oracle sanitising."""
import unittest
import numpy as np
from voicepipe import (Style, parse, effect, build_curve, chaos_fx, apply_fx, soft_limit, world_stretch,
                       tapestop, SR)

VOICES = ['af_heart', 'am_adam', 'bf_emma']

class TagParsing(unittest.TestCase):
    def test_warble(self):
        ev = parse('<warble 0.5s -6,+6,0,+12>hi</warble>', Style())
        self.assertEqual(ev[0][2].warble, (0.5, (-6, 6, 0, 12)))
        ev = parse('<warble every=0.25s steps=1,2>hi</warble>', Style())
        self.assertEqual(ev[0][2].warble, (0.25, (1, 2)))
    def test_pitchstep(self):
        self.assertEqual(parse('<pitchstep every=2s range=-8..+8 seed=3>x</pitchstep>', Style())[0][2].pitchstep, (2, -8, 8, 3))
        self.assertEqual(parse('<pitchstep>x</pitchstep>', Style())[0][2].pitchstep, (0.5, -8, 8, None))
    def test_jumpy_wobble(self):
        st = parse('<jumpy chance=0.3 max=12><wobble rate=8 depth=3>x</wobble></jumpy>', Style())[0][2]
        self.assertEqual(st.jumpy, (0.3, 12)); self.assertEqual(st.wobble, (8, 3))
    def test_flip(self):
        st = parse('<flip every=0.4s voices=af_heart,am_adam,bf_emma>x</flip>', Style(), VOICES)[0][2]
        self.assertEqual(st.flip, ('s', 0.4, ('af_heart', 'am_adam', 'bf_emma')))
        st = parse('<flip every=2w voices=main,am_adam>x</flip>', Style(), VOICES)[0][2]
        self.assertEqual(st.flip, ('w', 2, ('main', 'am_adam')))
    def test_chaos_and_fx_nest_with_existing(self):
        ev = parse('A <pitch +3><chaos level=4><echo delay=0.2s><radio>B</radio></echo></chaos></pitch> <robot>C</robot> <telephone>D</telephone>', Style())
        b = ev[1][2]
        self.assertEqual((b.pitch, b.chaos), (3, 4))
        self.assertEqual([f[0] for f in b.fx], ['echo', 'radio'])
        self.assertTrue(ev[2][2].robot); self.assertEqual(ev[3][2].fx, (('telephone',),))
        self.assertEqual(ev[0][2].fx, ())
    def test_new_cues_parse(self):
        ev = parse('a [tapestop] [tapestart 0.4s] [reverse 0.5s] [chaos 0.8s] [chaos 3 0.5s] b', Style())
        self.assertEqual([e[1] for e in ev if e[0] == 'effect'], ['tapestop', 'tapestart 0.4s', 'reverse 0.5s', 'chaos 0.8s', 'chaos 3 0.5s'])
    def test_errors(self):
        bad = ['<warble 0.5s>x</warble>', '<warble 0.01s 1,2>x</warble>', '<pitchstep range=5>x</pitchstep>',
               '<jumpy chance=2>x</jumpy>', '<wobble rate=99>x</wobble>', '<flip voices=af_heart>x</flip>',
               '<flip voices=af_heart,nobody>x</flip>', '<chaos level=9>x</chaos>', '<robot 3>x</robot>',
               '<echo feedback=0.95>x</echo>', '<chaos level=2>x', 'x [reverse up 1s]', 'x [chaos 9 1s]',
               '<pitch +30>x</pitch>', '<wobble colour=red>x</wobble>']
        for text in bad:
            with self.assertRaises(ValueError, msg=text):
                parse(text, Style(), VOICES)

class TagDSP(unittest.TestCase):
    def test_warble_curve_steps(self):
        st = parse('<warble 0.5s -6,+6,0,+12>x</warble>', Style(pitch=1))[0][2]
        c = build_curve(st, 3, np.random.default_rng(1))
        self.assertEqual(list(c(np.array([0.1, 0.6, 1.1, 1.6, 2.1]))), [-5, 7, 1, 13, -5])
    def test_curves_reproducible_and_bounded(self):
        st = parse('<pitchstep every=0.3s range=-8..+8><jumpy chance=0.5 max=12><wobble rate=8 depth=3><chaos level=5>x</chaos></wobble></jumpy></pitchstep>', Style())[0][2]
        t = np.linspace(0, 4, 800)
        a = build_curve(st, 4, np.random.default_rng(7))(t); b = build_curve(st, 4, np.random.default_rng(7))(t)
        self.assertTrue(np.array_equal(a, b)); self.assertLessEqual(np.max(np.abs(a)), 24)
        self.assertGreater(np.std(a), 1)
    def test_chaos_fx_and_effects(self):
        x = .5*np.sin(2*np.pi*200*np.arange(SR*2)/SR)
        for lvl in range(1, 6):
            y1 = chaos_fx(x, lvl, np.random.default_rng(3)); y2 = chaos_fx(x, lvl, np.random.default_rng(3))
            self.assertTrue(np.array_equal(y1, y2)); self.assertTrue(np.isfinite(y1).all())
            self.assertLessEqual(np.max(np.abs(y1)), .5 + 1e-9)
        for fx in [(('radio',),), (('telephone',),), (('echo', .25, .5, .5),), (('echo', .2, .4, .4), ('radio',))]:
            y = apply_fx(x, fx, np.random.default_rng(1))
            self.assertTrue(np.isfinite(y).all()); self.assertLessEqual(np.max(np.abs(y)), .5 + 1e-6)
        for cue in ['tapestop 0.6s', 'tapestart 0.5s', 'reverse 0.5s', 'chaos 0.8s', 'chaos 2 0.4s']:
            a = effect(cue, np.random.default_rng(2), x); b = effect(cue, np.random.default_rng(2), x)
            self.assertTrue(np.array_equal(a, b)); self.assertTrue(np.isfinite(a).all()); self.assertLess(np.max(np.abs(a)), .95)
    def test_limiter_and_stretch(self):
        x = np.concatenate([np.zeros(100), 3*np.sin(np.arange(SR)/5), .1*np.ones(100)])
        y = soft_limit(x); self.assertLessEqual(np.max(np.abs(y)), .89 + 1e-9); self.assertEqual(len(y), len(x))
        z = .3*np.sin(2*np.pi*150*np.arange(SR)/SR)
        self.assertEqual(len(world_stretch(z, int(SR*1.4))), int(SR*1.4))
        self.assertEqual(len(tapestop(z)), len(z))

class OracleSanitise(unittest.TestCase):
    def test_repair_and_clamp(self):
        import oracle
        fixed = oracle.repair('Hi <pitch +3>there [glitch nope 1s] <bogus 2>you</bogus></pitch> <robot>unclosed', VOICES)
        parse(fixed, Style(), VOICES)
        self.assertIn('<robot>', fixed); self.assertIn('</robot>', fixed)
        long = ' '.join(['word']*600)
        self.assertLessEqual(oracle.estimate_seconds(oracle.clamp_length(long, 1)), oracle.MAX_SECONDS)
        s = oracle.clean_settings({'voice': 'nobody', 'pitch': 99, 'speed': 0.1, 'overlay': {'enabled': True, 'voice': 'am_adam', 'gain': 5, 'pitch': -40}},
                                  {'voice': 'af_heart', 'pitch': 0, 'speed': 1}, VOICES)
        self.assertEqual((s['voice'], s['pitch'], s['speed']), ('af_heart', 12, .5))
        self.assertEqual((s['overlay']['gain'], s['overlay']['pitch']), (1, -12))

if __name__ == '__main__':
    unittest.main(verbosity=2)
