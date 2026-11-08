import unittest
import numpy as np
import soundfile as sf
from voicepipe import Style, parse, effect, world_transform, SR

class VoiceTests(unittest.TestCase):
    def test_nested_and_reset(self):
        ev = parse('A <pitch +4>B <contour 0,3>C</contour></pitch> D',Style(pitch=1))
        self.assertEqual([x[2].pitch for x in ev],[1,5,5,1])
        self.assertEqual(ev[2][2].contour,(0,3))
    def test_errors(self):
        for text in ['<pitch 3>oops','</pitch>','[nope 1s]','<speed 9>x</speed>','<oops 2>x</oops>']:
            with self.assertRaises(ValueError):
                ev=parse(text,Style())
                for kind,v,st in ev:
                    if kind=='effect': effect(v,np.random.default_rng(4),None)
    def test_effects_finite_reproducible(self):
        for cue in ['whistle C6,E6,G6 1s','whistle up 1s','sweep down .3s','breath in .4s','breath out .4s','glitch mix .4s','glitch bitcrush .4s','glitch stutter .4s','glitch slip .4s','glitch ring .4s','glitch bleep .4s','pause .2s']:
            a=effect(cue,np.random.default_rng(9),None)
            b=effect(cue,np.random.default_rng(9),None)
            self.assertTrue(np.array_equal(a,b),cue)
            self.assertTrue(np.isfinite(a).all(),cue)
            self.assertLess(np.max(np.abs(a)),.95,cue)
            self.assertAlmostEqual(a[0],0,places=6)
            self.assertAlmostEqual(a[-1],0,places=6)
    def test_octave_preserves_duration(self):
        import pyworld as pw
        t=np.arange(SR)/SR
        x=(.2*np.sin(2*np.pi*180*t)+.12*np.sin(2*np.pi*360*t)+.06*np.sin(2*np.pi*540*t))
        y=world_transform(x,Style(pitch=12))
        self.assertEqual(len(x),len(y))
        f0,tt=pw.dio(np.ascontiguousarray(y),SR,f0_floor=100,f0_ceil=800)
        med=np.median(f0[f0>0])
        self.assertTrue(330<med<390,med)
    def test_rendered_demo(self):
        from pathlib import Path
        if not Path('demo.wav').exists(): self.skipTest('render demo first')
        x,sr=sf.read('demo.wav')
        self.assertEqual(sr,SR)
        self.assertTrue(10 <= len(x)/sr <= 20)
        self.assertTrue(np.isfinite(x).all())
        self.assertTrue(.02 < np.sqrt(np.mean(x*x)))
        self.assertLess(np.max(np.abs(x)),.95)
        self.assertEqual(np.count_nonzero(np.abs(x)>=.999),0)

if __name__=='__main__': unittest.main(verbosity=2)
