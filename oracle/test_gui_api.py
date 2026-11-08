"""Programmatic end-to-end test against the running GUI's actual HTTP API."""
import io
import json
from pathlib import Path
import subprocess
import time
import httpx
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parent

def main():
    started=time.monotonic()
    with httpx.Client(base_url='http://127.0.0.1:7860',timeout=30) as client:
        assert client.get('/').status_code==200
        assert client.get('/studio.css').status_code==200
        assert client.get('/studio.js').status_code==200
        config=client.get('/api/config').json()
        assert 'af_heart' in config['voices'] and len(config['examples'])==4
        assert client.post('/api/render',json={'text':'x','voice':'nonexistent'}).status_code==400
        assert client.post('/api/render',json={'text':'<pitch 4>unclosed'}).status_code==400
        assert client.post('/api/render',headers={'Origin':'https://example.com'},json={'text':'x'}).status_code==403
        payload={'text':config['examples'][0]['text'],'voice':'af_heart','blends':[{'voice':'af_heart','weight':.75},{'voice':'af_bella','weight':.25}], 'pitch':0, 'speed':1,'formant':1,'seed':42}
        response=client.post('/api/render',json=payload)
        assert response.status_code==202,response.text
        job=response.json()
        assert client.post('/api/render',json=payload).status_code==429
        while True:
            state=client.get(job['status_url']).json()
            print(state['status'],state['progress'],state['message'],flush=True)
            assert state['status']!='error',state
            if state['status']=='ready':break
            assert time.monotonic()-started<180
            time.sleep(.4)
        wav=client.get(state['wav']);mp3=client.get(state['mp3']);sidecar=client.get(state['sidecar'])
        assert wav.status_code==mp3.status_code==sidecar.status_code==200
        assert len(mp3.content)>10000
        audio,sr=sf.read(io.BytesIO(wav.content))
        assert sr==24000 and 10<len(audio)/sr<20
        assert np.isfinite(audio).all() and np.max(np.abs(audio))<.99
        assert np.sqrt(np.mean(audio*audio))>.02
        assert len(state['waveform'])==420 and len(state['events'])>=10
        (ROOT/'gui-demo.wav').write_bytes(wav.content)
        (ROOT/'gui-demo.mp3').write_bytes(mp3.content)
        decoded=subprocess.check_output(['ffmpeg','-v','error','-i',str(ROOT/'gui-demo.mp3'),'-f','f32le','-ac','1','-ar','24000','pipe:1'])
        mp3audio=np.frombuffer(decoded,dtype='<f4')
        assert np.isfinite(mp3audio).all() and np.max(np.abs(mp3audio))<.99
        report={'passed':True,'http_round_trip_seconds':round(time.monotonic()-started,3),'voices':len(config['voices']),'duration_seconds':len(audio)/sr,'wav_peak':float(np.max(np.abs(audio))),'wav_rms':float(np.sqrt(np.mean(audio*audio))),'mp3_peak':float(np.max(np.abs(mp3audio))),'clipped_samples':int(np.count_nonzero(np.abs(audio)>=.999)),'event_count':len(state['events']),'waveform_bins':len(state['waveform']),'job_id':job['id'],'checks':['HTML/CSS/JS served','voice catalog','preset catalog','invalid voice rejected','malformed markup rejected','cross-origin POST rejected','concurrent render rejected','background render/progress complete','WAV download decoded','MP3 download decoded','timing JSON download','non-silent finite unclipped audio']}
        (ROOT/'gui-api-verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
if __name__=='__main__': main()
