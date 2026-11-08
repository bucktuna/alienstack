'use strict';
const $=id=>document.getElementById(id);
const editor=$('editor');
let config=null, voiceById={}, savedRange=null, busy=false;

const CUES=[
  ['😮‍💨 Breath in','[breath in 0.4s]'],['😮‍💨 Breath out','[breath out 0.4s]'],['⏸ Pause','[pause 0.5s]'],
  ['🎵 Whistle','[whistle up 1s]'],['🎼 Melody','[whistle C6,E6,G6 1.2s]'],['〰 Sweep','[sweep down 0.6s]'],
  ['⚡ Glitch','[glitch mix 0.4s]'],['🌀 Chaos','[chaos 0.8s]'],['⏪ Reverse','[reverse 0.5s]'],
  ['📼 Tape stop','[tapestop 0.6s]'],['🚀 Spin up','[tapestart 0.5s]']];
const WRAPS=[
  ['⬆ Higher','pitch +4'],['⬇ Lower','pitch -4'],['⏩ Faster','speed 1.3'],['🐢 Slower','speed 0.8'],
  ['🤖 Robot','robot'],['📻 Radio','radio'],['☎ Phone','telephone'],['🏔 Echo','echo delay=0.25s feedback=0.4'],
  ['〰 Wobble','wobble rate=8 depth=3'],['🪜 Warble','warble 0.5s -6,+6,0,+12'],['🎲 Pitch steps','pitchstep every=0.5s range=-8..+8'],
  ['🦘 Jumpy','jumpy chance=0.3 max=12'],['🔀 Flip voices','flip every=0.4s voices=main,am_adam,bf_emma'],['🌀 Chaos','chaos level=3']];
function cueLabel(spec){
  const p=spec.trim().split(/\s+/),n=p[0];
  const dur=(p.at(-1)||'').match(/^[\d.]+s$/)?` ${p.at(-1)}`:'';
  const m={breath:p[1]==='in'?'😮‍💨 breath in':'😮‍💨 breath out',pause:'⏸ pause',whistle:p[1]&&p[1].includes(',')?'🎼 melody':'🎵 whistle',sweep:'〰 sweep',glitch:`⚡ ${p[1]&&!p[1].endsWith('s')?p[1]:'glitch'}`,chaos:'🌀 chaos',reverse:'⏪ reverse',tapestop:'📼 tape stop',tapestart:'🚀 spin up'};
  return (m[n]||`♪ ${n}`)+dur;
}
function wrapLabel(body){
  const [n,...rest]=body.trim().split(/\s+/);const v=rest.join(' ');
  const kw=k=>(v.match(new RegExp(`${k}=([^\\s]+)`))||[])[1];
  switch(n){
    case 'pitch':return Number(v)>=0?`⬆ +${Number(v)}`:`⬇ ${Number(v)}`;
    case 'speed':return Number(v)>=1?`⏩ ${v}×`:`🐢 ${v}×`;
    case 'formant':return Number(v)<1?'deeper':'lighter';
    case 'contour':return '〰 glide';case 'gain':return `🔊 ${v}`;
    case 'warble':return '🪜 warble';case 'pitchstep':return `🎲 steps ${kw('every')||''}`;
    case 'jumpy':return '🦘 jumpy';case 'wobble':return '〰 wobble';case 'flip':return '🔀 flip';
    case 'chaos':return `🌀 chaos ${kw('level')||rest[0]||''}`;case 'robot':return '🤖 robot';
    case 'radio':return '📻 radio';case 'telephone':return '☎ phone';case 'echo':return '🏔 echo';
    default:return n;
  }
}

function makeCue(token){const s=document.createElement('span');s.className='cue';s.contentEditable='false';s.dataset.m=token;s.textContent=cueLabel(token.slice(1,-1));return s;}
function makeWrap(openTag){const s=document.createElement('span');s.className='wrap';const body=openTag.slice(1,-1).trim();s.dataset.open=openTag;s.dataset.close=`</${body.split(/\s+/)[0]}>`;s.dataset.label=wrapLabel(body);return s;}
function setScript(markup){
  editor.replaceChildren();const stack=[editor];
  for(const tok of markup.split(/(<[^>]*>|\[[^\]]*\])/)){
    if(!tok)continue;const top=stack.at(-1);
    if(tok.startsWith('</')){if(stack.length>1)stack.pop();}
    else if(tok.startsWith('<')){const w=makeWrap(tok);top.appendChild(w);stack.push(w);}
    else if(tok.startsWith('[')){top.appendChild(makeCue(tok));}
    else top.appendChild(document.createTextNode(tok));
  }
  syncRaw();
}
function serialize(node=editor){
  let out='';
  node.childNodes.forEach(n=>{
    if(n.nodeType===3)out+=n.textContent.replace(/[<>\[\]]/g,' ');
    else if(n.nodeType===1){
      if(n.classList.contains('cue'))out+=` ${n.dataset.m} `;
      else if(n.classList.contains('wrap'))out+=n.dataset.open+serialize(n)+n.dataset.close;
      else if(n.tagName==='BR')out+='\n';
      else out+=(n.tagName==='DIV'||n.tagName==='P'?'\n':'')+serialize(n);
    }
  });
  return node===editor?out.replace(/[ \t]+/g,' ').replace(/ ?\n ?/g,'\n').trim():out;
}
function syncRaw(){if($('advanced').open)$('raw').value=serialize();}
document.addEventListener('selectionchange',()=>{const s=getSelection();if(s.rangeCount&&editor.contains(s.anchorNode))savedRange=s.getRangeAt(0).cloneRange();});
function currentRange(){
  if(savedRange&&editor.contains(savedRange.startContainer))return savedRange;
  const r=document.createRange();r.selectNodeContents(editor);r.collapse(false);return r;
}
function placeCaretAfter(node){const r=document.createRange();r.setStartAfter(node);r.collapse(true);const s=getSelection();s.removeAllRanges();s.addRange(r);savedRange=r.cloneRange();}
function insertCue(token){
  const r=currentRange();r.collapse(false);
  const chip=makeCue(token),after=document.createTextNode(' ');
  r.insertNode(after);r.insertNode(chip);r.insertNode(document.createTextNode(' '));
  editor.focus({preventScroll:true});placeCaretAfter(after);editor.normalize();syncRaw();
}
function wrapSelection(body){
  const r=currentRange();const w=makeWrap(`<${body}>`);
  if(r.collapsed){w.textContent='your words';r.insertNode(w);}
  else{w.appendChild(r.extractContents());r.insertNode(w);}
  editor.focus({preventScroll:true});const sel=getSelection(),nr=document.createRange();nr.selectNodeContents(w);sel.removeAllRanges();sel.addRange(nr);savedRange=nr.cloneRange();syncRaw();
}
function toggleTool(btn,panel,other,otherPanel){const open=$(panel).hidden;$(panel).hidden=!open;btn.setAttribute('aria-expanded',open);if(open){$(otherPanel).hidden=true;$(other).setAttribute('aria-expanded',false);}}
$('t-cues').onclick=()=>toggleTool($('t-cues'),'cues','t-wraps','wraps');
$('t-wraps').onclick=()=>toggleTool($('t-wraps'),'wraps','t-cues','cues');
['t-cues','t-wraps'].forEach(id=>$(id).addEventListener('pointerdown',e=>e.preventDefault()));
function buildFx(){
  for(const [label,tok] of CUES){const b=document.createElement('button');b.type='button';b.className='fx';b.textContent=label;b.onclick=()=>insertCue(tok);$('cues').appendChild(b);}
  for(const [label,body] of WRAPS){const b=document.createElement('button');b.type='button';b.className='fx';b.textContent=label;b.onclick=()=>wrapSelection(body);$('wraps').appendChild(b);}
  document.querySelectorAll('.fx').forEach(b=>b.addEventListener('pointerdown',e=>e.preventDefault()));
}
editor.addEventListener('input',syncRaw);
$('advanced').addEventListener('toggle',()=>{if($('advanced').open)$('raw').value=serialize();});
$('raw').addEventListener('input',()=>{const v=$('raw').value;clearTimeout($('raw').t);$('raw').t=setTimeout(()=>{const keep=$('advanced').open;setScriptNoRaw(v);},400);});
function setScriptNoRaw(v){const open=$('advanced').open;$('advanced').open=false;setScript(v);$('advanced').open=open;}
$('raw-apply').textContent='Copy script';$('raw-apply').onclick=()=>navigator.clipboard?.writeText($('raw').value).then(()=>status('Script copied.'),()=>{});
$('clear').onclick=()=>{editor.replaceChildren();savedRange=null;syncRaw();editor.focus();};
$('shuffle').onclick=()=>{$('seed').value=crypto.getRandomValues(new Uint32Array(1))[0];saveSettingsSoon();};

const depthToFormant=v=>+(v>=0?1-0.3*v:1-0.4*v).toFixed(3);
const formantToDepth=f=>+(f<=1?(1-f)/0.3:(1-f)/0.4).toFixed(2);
function getSettings(){
  return {voice:$('voice').value,blend:{on:$('blend-on').checked,voice:$('blend-voice').value,mix:+$('blend-mix').value/100},
    overlay:{enabled:$('ov-on').checked,voice:$('ov-voice').value,gain:+$('ov-gain').value/100,pitch:+$('ov-pitch').value,delay_ms:+$('ov-delay').value},
    pitch:+$('pitch').value,speed:+$('speed').value,formant:depthToFormant(+$('depth').value),seed:+$('seed').value||0};
}
function applySettings(s){
  if(!s)return;
  if(s.voice&&voiceById[s.voice])$('voice').value=s.voice;
  const b=s.blend||{};$('blend-on').checked=!!b.on;if(b.voice&&voiceById[b.voice])$('blend-voice').value=b.voice;if(b.mix!=null)$('blend-mix').value=Math.round(b.mix*100);
  const o=s.overlay||{};$('ov-on').checked=!!o.enabled;if(o.voice&&voiceById[o.voice])$('ov-voice').value=o.voice;
  if(o.gain!=null)$('ov-gain').value=Math.round(o.gain*100);if(o.pitch!=null)$('ov-pitch').value=o.pitch;if(o.delay_ms!=null)$('ov-delay').value=o.delay_ms;
  if(s.pitch!=null)$('pitch').value=s.pitch;if(s.speed!=null)$('speed').value=s.speed;if(s.formant!=null)$('depth').value=formantToDepth(s.formant);if(s.seed!=null)$('seed').value=s.seed;
  refreshLabels();
}
function refreshLabels(){
  const v=voiceById[$('voice').value];$('voice-desc').textContent=v?v.desc:'';
  $('blend-box').hidden=!$('blend-on').checked;$('ov-box').hidden=!$('ov-on').checked;
  $('blend-a').textContent=voiceById[$('voice').value]?.name||'';$('blend-b').textContent=voiceById[$('blend-voice').value]?.name||'';
  $('blend-val').textContent=`${$('blend-mix').value}%`;
  $('ov-gain-val').textContent=`${$('ov-gain').value}%`;
  const op=+$('ov-pitch').value;$('ov-pitch-val').textContent=op===-12?'octave below':op===12?'octave above':`${op>0?'+':op<0?'−':''}${Math.abs(op)}`;
  $('ov-delay-val').textContent=`${$('ov-delay').value} ms`;
  const p=+$('pitch').value;$('pitch-val').textContent=`Pitch ${p>0?'+':''}${p}`;
  $('speed-val').textContent=`Speed ${(+$('speed').value).toFixed(2)}×`;
  const d=+$('depth').value;$('depth-val').textContent=d===0?'Depth normal':d>0?`Deeper ${Math.round(d*100)}%`:`Lighter ${Math.round(-d*100)}%`;
  const bits=[v?v.name:''];if(p)bits.push(`pitch ${p>0?'+':''}${p}`);if(+$('speed').value!==1)bits.push(`${(+$('speed').value).toFixed(2)}×`);
  if($('blend-on').checked)bits.push(`+ ${voiceById[$('blend-voice').value]?.name||''}`);if($('ov-on').checked)bits.push(`duet ${voiceById[$('ov-voice').value]?.name||''}`);
  $('voice-summary').textContent=bits.filter(Boolean).join(' · ');
}
let saveTimer;
function saveSettingsSoon(){if(config&&config.public)return;clearTimeout(saveTimer);saveTimer=setTimeout(()=>fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(getSettings())}).catch(()=>{}),700);}
['voice','blend-on','blend-voice','blend-mix','ov-on','ov-voice','ov-gain','ov-pitch','ov-delay','pitch','speed','depth','seed'].forEach(id=>{$(id).addEventListener('input',()=>{refreshLabels();saveSettingsSoon();});$(id).addEventListener('change',()=>{refreshLabels();saveSettingsSoon();});});
function fillVoices(){
  for(const id of ['voice','blend-voice','ov-voice']){
    const sel=$(id);sel.replaceChildren();const groups={};
    for(const v of config.voice_catalog){if(!groups[v.group]){groups[v.group]=document.createElement('optgroup');groups[v.group].label=v.group;sel.appendChild(groups[v.group]);}
      const o=document.createElement('option');o.value=v.id;o.textContent=`${v.name} — ${v.desc}`;groups[v.group].appendChild(o);}
  }
}

function status(msg,err=false,el='status'){$(el).textContent=msg;$(el).classList.toggle('error',err);}
async function readJSON(r){let d;try{d=await r.json();}catch{throw Error(`Server error (${r.status})`);}if(!r.ok){let m=d.detail||'Request failed';if(Array.isArray(m))m=m.map(x=>`${x.loc.at(-1)}: ${x.msg}`).join('; ');throw Error(m);}return d;}
const wait=ms=>new Promise(r=>setTimeout(r,ms));
function requestBody(text,s,title=''){
  const blends=s.blend.on&&s.blend.voice!==s.voice?[{voice:s.voice,weight:+(1-s.blend.mix).toFixed(3)},{voice:s.blend.voice,weight:+s.blend.mix.toFixed(3)}].filter(b=>b.weight>0):[];
  return {text,voice:s.voice,blends,pitch:s.pitch,speed:s.speed,formant:s.formant,seed:s.seed,overlay:s.overlay.enabled?s.overlay:null,title};
}
async function pollJob(url,onProgress){
  for(let i=0;i<1200;i++){const d=await readJSON(await fetch(url));onProgress&&onProgress(d);if(d.status==='ready')return d;if(d.status==='error')throw Error(d.message);await wait(450);}
  throw Error('Still rendering; try again shortly.');
}
function showResult(d,autoplay,title){
  $('result').hidden=false;$('play-title').textContent=title||d.title||'Your clip';
  $('player').src=d.mp3;$('dl-mp3').href=d.mp3;$('dl-wav').href=d.wav;
  if(autoplay)$('player').play().catch(()=>status('Tap ▶ on the player to listen.'));
}
async function renderNow({autoplay=false,title=''}={}){
  if(busy)return;const text=serialize();
  if(!text){status('Give Oracle a few words first.',true);return;}
  busy=true;const btn=$('render');btn.disabled=true;btn.textContent='Making it…';$('progress').hidden=false;$('bar').style.width='3%';status('Preparing your sound…');
  try{
    const s=getSettings();
    const job=await readJSON(await fetch('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(requestBody(text,s,title))}));
    const d=await pollJob(job.status_url,x=>{$('bar').style.width=`${x.progress}%`;status(x.message);});
    showResult(d,autoplay,title);status(`Ready · ${d.duration.toFixed(1)} s, made in ${d.render_seconds}s.`);loadHistory();
  }catch(e){status(e.message,true);}
  finally{busy=false;btn.disabled=false;btn.textContent='▶ Make it talk';setTimeout(()=>{$('progress').hidden=true;},600);}
}
$('render').onclick=()=>renderNow({autoplay:true});

const MOODS=[
  {e:'🕯',name:'Calm Narrator',desc:'Unhurried British storyteller with a soft breath between lines.',s:{voice:'bm_fable',speed:.92,pitch:0},script:'[breath in 0.4s] Once, on a quiet evening, the river forgot which way it was going. [pause 0.4s] <speed 0.9>So it simply stayed, and listened.</speed> [breath out 0.5s]'},
  {e:'🤖',name:'Robot Meltdown',desc:'A polite robot that keeps it together… until it absolutely does not.',s:{voice:'am_michael'},script:'<robot>Hello. I am functioning normally.</robot> [glitch stutter 0.3s] <robot><jumpy chance=0.35 max=9>All systems nominal. Nominal. Nom.</jumpy></robot> [tapestop 0.6s] <chaos level=4><robot>Error error I would like a hug.</robot></chaos> [chaos 0.8s] [tapestart 0.5s] <robot>Rebooted. Do not ask.</robot>'},
  {e:'👻',name:'Haunted',desc:'Whispery voice with a deep ghost an octave below, drifting echoes.',s:{voice:'af_nicole',speed:.9,overlay:{enabled:true,voice:'am_onyx',gain:.45,pitch:-12,delay_ms:40}},script:'[breath in 0.6s] <echo delay=0.3s feedback=0.45><pitchstep every=1.2s range=-4..+4>Who left the attic light on?</pitchstep></echo> [reverse 0.6s] <formant 0.9>I have been waiting… for such a long time.</formant> [breath out 0.7s]'},
  {e:'🐿',name:'Chipmunk Panic',desc:'Tiny, very high, very fast, and jumping all over the place.',s:{voice:'af_bella',pitch:9,speed:1.35},script:'<jumpy chance=0.4 max=6>Oh no oh no oh no, where did I put the acorn?</jumpy> [whistle up 0.4s] <wobble rate=10 depth=2>I had it right here!</wobble> [glitch bleep 0.3s] Found it.'},
  {e:'📻',name:'Late-Night Radio',desc:'Crackly AM radio host with a little echo in the studio.',s:{voice:'am_puck',speed:1.05},script:'<radio>You are listening to Midnight Copper, the only station broadcasting from inside your kitchen.</radio> [sweep down 0.5s] <radio><echo delay=0.18s feedback=0.3>Stay tuned.</echo></radio> [glitch ring 0.3s]'},
  {e:'🎶',name:'Octave Duet',desc:'Two voices at once: you, plus a warm voice an octave below.',s:{voice:'af_heart',overlay:{enabled:true,voice:'am_michael',gain:.6,pitch:-12,delay_ms:15}},script:'Welcome, welcome, to the grand hall of voices. [whistle C6,E6,G6 1.2s] <contour 0,3,-2>Tonight, we sing together.</contour>'},
  {e:'🔀',name:'Voice Roulette',desc:'Three voices take turns every few words, with a glitchy finish.',s:{voice:'af_heart'},script:'<flip every=2w voices=main,am_adam,bf_emma>I would like to order one pizza with absolutely everything on it please.</flip> [glitch mix 0.4s] <warble 0.4s 0,+5,+12,+5>Extra cheese.</warble>'},
  {e:'☎',name:'Call From Space',desc:'A crackly phone line from very, very far away.',s:{voice:'bm_george',speed:.95},script:'[glitch ring 0.3s] <telephone>Hello? Can you hear me? I am calling from just past the moon.</telephone> [pause 0.4s] <telephone><echo delay=0.4s feedback=0.5>The signal is terrible.</echo></telephone> [sweep up 0.6s]'},
];
const SAMPLE_EMOJI=['✦','◒','♫','⌁'];
function buildMoods(){
  const all=[...MOODS,...config.examples.map((x,i)=>({e:SAMPLE_EMOJI[i]||'✦',name:x.name,desc:x.mood,s:{voice:'af_heart'},script:x.text}))];
  for(const m of all){
    const b=document.createElement('button');b.type='button';b.className='mood';
    b.innerHTML='<span class="e"></span><b></b><small></small>';b.querySelector('.e').textContent=m.e;b.querySelector('b').textContent=m.name;b.querySelector('small').textContent=m.desc;
    b.onclick=()=>{
      const base={...config.settings,blend:{...config.settings.blend,on:false},overlay:{...config.settings.overlay,enabled:false},pitch:0,speed:1,formant:1};
      applySettings({...base,...m.s,overlay:{...base.overlay,...(m.s.overlay||{})}});saveSettingsSoon();
      setScript(m.script);status(`Loaded “${m.name}”. Rendering…`);
      $('play').scrollIntoView({behavior:'smooth',block:'center'});
      renderNow({autoplay:true,title:m.name});
    };
    $('moods').appendChild(b);
  }
}

const shared=new Audio();let playingId=null;
function ago(t){const s=Date.now()/1000-t;return s<60?'just now':s<3600?`${Math.round(s/60)} min ago`:s<86400?`${Math.round(s/3600)} h ago`:new Date(t*1000).toLocaleDateString();}
async function loadHistory(){
  try{
    const {clips}=await readJSON(await fetch('/api/clips?limit=30'));
    const ul=$('history');ul.replaceChildren();$('hist-count').textContent=clips.length?`${clips.length} saved`:'none yet';
    for(const c of clips){
      const li=document.createElement('li');
      li.innerHTML='<button class="play-btn" type="button" aria-label="Play">▶</button><div class="info"><b></b><small></small></div><a class="icon" aria-label="Download MP3" download>⬇</a><button class="icon del owner-only" type="button" aria-label="Delete">🗑</button>';
      li.querySelector('b').textContent=c.title||'Untitled';
      li.querySelector('small').textContent=`${(c.duration||0).toFixed(1)} s · ${ago(c.created)}${c.source&&c.source!=='studio'?' · '+({chat:'Oracle',chip:'Oracle',mic:'Oracle',text:'texted'}[c.source]||c.source):''}`;
      li.querySelector('a').href=c.mp3;
      const pb=li.querySelector('.play-btn');
      pb.onclick=()=>{if(playingId===c.id&&!shared.paused){shared.pause();pb.textContent='▶';return;}
        document.querySelectorAll('.history .play-btn').forEach(x=>x.textContent='▶');shared.src=c.mp3;shared.play().then(()=>{pb.textContent='❚❚';playingId=c.id;}).catch(()=>{});shared.onended=()=>{pb.textContent='▶';};};
      li.querySelector('.del').onclick=async()=>{if(!confirm(`Delete “${c.title}”?`))return;await fetch(`/api/clips/${c.id}`,{method:'DELETE'});loadHistory();};
      li.querySelector('.info').onclick=()=>{if(c.text){setScript(c.text);status(`Loaded “${c.title}” into the editor.`);}};
      ul.appendChild(li);
    }
  }catch(e){}
}

const thread=$('thread');
function bubbleMe(text){const d=document.createElement('div');d.className='bubble me';d.textContent=text;thread.appendChild(d);thread.scrollTop=thread.scrollHeight;return d;}
function bubbleOracle(msg,{pending=false}={}){
  const d=document.createElement('div');d.className='bubble them'+(pending?' thinking':'');
  if(pending){d.innerHTML='<span class="dots">The Oracle is writing</span>';thread.appendChild(d);thread.scrollTop=thread.scrollHeight;return d;}
  fillOracle(d,msg);thread.appendChild(d);return d;
}
function fillOracle(d,msg,state='ready'){
  d.className='bubble them';d.replaceChildren();
  const t=document.createElement('b');t.className='t';t.textContent=msg.title||'Oracle clip';d.appendChild(t);
  const a=document.createElement('audio');a.controls=true;a.preload='none';
  if(state==='ready')a.src=msg.mp3;
  d.appendChild(a);
  const info=document.createElement('div');info.className='meta';info.textContent=state==='ready'?(msg.llm_seconds?`written in ${msg.llm_seconds}s`:''):'Voicing it…';d.appendChild(info);
  const acts=document.createElement('div');acts.className='acts';
  const edit=document.createElement('button');edit.className='ghost';edit.type='button';edit.textContent='✎ Edit in studio';
  edit.onclick=()=>{applySettings(msg.settings);setScript(msg.script);saveSettingsSoon();$('editor').scrollIntoView({behavior:'smooth',block:'center'});status('Loaded the Oracle’s script. Tweak it and tap Make it talk.');};
  const dl=document.createElement('a');dl.className='ghost';dl.textContent='⬇ MP3';dl.href=msg.mp3;dl.download='';
  acts.append(edit,dl);d.appendChild(acts);
  const det=document.createElement('details');det.innerHTML='<summary>Show script</summary><pre></pre>';det.querySelector('pre').textContent=msg.script;d.appendChild(det);
  return {audio:a,info};
}
async function askOracle(prompt,source='chat'){
  prompt=prompt.trim();if(!prompt||busy)return;
  busy=true;$('oracle-send').disabled=true;$('oracle-input').value='';
  bubbleMe(prompt);const pend=bubbleOracle(null,{pending:true});status('Thinking…',false,'oracle-status');
  const t0=performance.now();
  try{
    const {reply,job}=await readJSON(await fetch('/api/oracle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt,settings:getSettings(),source})}));
    const {audio,info}=fillOracle(pend,reply,'pending');thread.scrollTop=thread.scrollHeight;
    status(`Written in ${reply.llm_seconds}s${reply.repaired?' (auto-fixed)':''}. Voicing it…`,false,'oracle-status');
    applySettings(reply.settings);setScript(reply.script);
    const d=await pollJob(job.status_url,x=>{info.textContent=`Voicing it… ${x.progress}%`;});
    audio.src=d.mp3;info.textContent=`written in ${reply.llm_seconds}s · voiced in ${d.render_seconds}s · ${d.duration.toFixed(1)} s long`;
    audio.play().catch(()=>{});
    showResult(d,false,reply.title);
    status(`Ready in ${((performance.now()-t0)/1000).toFixed(1)}s. It’s in the editor too, so you can tweak and re-make it.`,false,'oracle-status');
    loadHistory();
  }catch(e){pend.className='bubble them';pend.textContent=`Hmm, that didn’t work: ${e.message}`;status(e.message,true,'oracle-status');}
  finally{busy=false;$('oracle-send').disabled=false;thread.scrollTop=thread.scrollHeight;}
}
$('oracle-form').onsubmit=e=>{e.preventDefault();askOracle($('oracle-input').value);};
$('oracle-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();askOracle($('oracle-input').value);}});
document.querySelectorAll('#oracle-chips .chip').forEach(c=>c.onclick=()=>askOracle(c.dataset.prompt,'chip'));
$('oracle-clear').onclick=async()=>{if(!confirm('Clear the Oracle conversation? Your clips stay in Recent clips.'))return;await fetch('/api/oracle/history',{method:'DELETE'});thread.replaceChildren();};
async function loadThread(){
  try{const {messages}=await readJSON(await fetch('/api/oracle/history'));
    for(const m of messages.slice(-20)){if(m.role==='user')bubbleMe(m.text);else bubbleOracle(m);}
    thread.scrollTop=thread.scrollHeight;}catch(e){}
}
(function mic(){
  const Rec=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!Rec||!window.isSecureContext)return;
  const b=$('mic');b.hidden=false;let rec=null;
  b.onclick=()=>{
    if(rec){rec.stop();return;}
    rec=new Rec();rec.lang='en-US';rec.interimResults=true;rec.continuous=false;
    rec.onresult=e=>{$('oracle-input').value=[...e.results].map(r=>r[0].transcript).join(' ');};
    rec.onerror=e=>{status(`Mic: ${e.error}. Typing always works.`,true,'oracle-status');};
    rec.onend=()=>{b.classList.remove('on');rec=null;const v=$('oracle-input').value.trim();if(v)askOracle(v,'mic');};
    b.classList.add('on');status('Listening…',false,'oracle-status');rec.start();
  };
})();

const HELP=[
  ['The basics',[
    ['Plain words','Just type. Everything that isn’t a tag is spoken.','Hello there, my king.'],
    ['[sound cues]','Square brackets drop a sound in between words.','[breath in 0.4s]'],
    ['<style>words</style>','Angle brackets change how the words inside sound. They can nest.','<pitch +4>higher words</pitch>']]],
  ['Sounds',[
    ['[breath in 0.4s] · [breath out 0.5s]','A breath.','[breath in 0.4s]'],['[pause 0.5s]','Silence.','[pause 0.5s]'],
    ['[whistle up 1s] · [whistle C6,E6,G6 1.2s]','Whistle a slide (up/down/arch) or notes.','[whistle C6,E6,G6 1.2s]'],
    ['[sweep down 0.6s]','Electronic sweep.','[sweep down 0.6s]'],
    ['[glitch mix 0.4s]','Glitch made from the last words. Modes: mix, bitcrush, stutter, slip, ring, bleep.','[glitch stutter 0.4s]'],
    ['[chaos 0.8s] · [chaos 3 0.8s]','A burst of chaos (level 1–5, default 5).','[chaos 0.8s]'],
    ['[reverse 0.5s]','Plays the end of the last words backwards.','[reverse 0.5s]'],
    ['[tapestop 0.6s] · [tapestart 0.5s]','Tape winding down / spinning back up.','[tapestop 0.6s]']]],
  ['Pitch & voice styles',[
    ['<pitch +4>…</pitch>','Higher or lower, in semitones (12 = an octave).','<pitch -5>low and slow</pitch>'],
    ['<speed 1.3>…</speed>','Faster (above 1) or slower (below 1).','<speed 0.8>take your time</speed>'],
    ['<formant 0.9>…</formant>','Voice depth: below 1 sounds bigger/deeper, above 1 smaller.','<formant 0.85>big voice</formant>'],
    ['<contour 0,4,-3>…</contour>','A pitch glide across the phrase.','<contour 0,5,-2>is that so?</contour>'],
    ['<warble 0.5s -6,+6,0,+12>…</warble>','Steps through those pitches every 0.5 s, over and over.','<warble 0.5s -6,+6,0,+12>stairs up and down</warble>'],
    ['<pitchstep every=2s range=-8..+8>…</pitchstep>','A random new pitch every 2 s (add seed=3 to fix the pattern).','<pitchstep every=2s range=-6..+6>a wandering voice</pitchstep>'],
    ['<jumpy chance=0.3 max=12>…</jumpy>','Sudden random pitch jumps.','<jumpy chance=0.4 max=10>surprise!</jumpy>'],
    ['<wobble rate=8 depth=3>…</wobble>','Fast vibrato: rate per second, depth in semitones.','<wobble rate=8 depth=3>wobbly</wobble>'],
    ['<flip every=0.4s voices=main,am_adam,bf_emma>…</flip>','Switch voices every 0.4 s (or every=2w for every 2 words). “main” is your chosen voice.','<flip every=2w voices=main,am_adam>two words each</flip>'],
    ['<chaos level=3>…</chaos>','Random stutters, bitcrush, reverse, tape stops, pitch steps and (level 3+) voice flips. Level 1–5. Same seed = same chaos.','<chaos level=3>this is fine</chaos>']]],
  ['Effects',[
    ['<robot>…</robot>','Flat robotic monotone.','<robot>beep boop</robot>'],
    ['<radio>…</radio> · <telephone>…</telephone>','Old radio or phone line.','<telephone>hello?</telephone>'],
    ['<echo delay=0.25s feedback=0.4>…</echo>','Echo (delay 0.03–1 s, feedback 0–0.8, mix 0–1).','<echo>hello hello</echo>']]],
  ['Duet overlay',[
    ['Voice settings → Duet','A second voice says the same words at the same time, on top. Set its voice, volume, pitch offset (−12 = an octave below) and a tiny delay. Not the same as Blend, which melts two voices into one.',null]]],
  ['The Oracle',[
    ['Just ask','Describe it in plain words, e.g. “tell a short story about a red fox while you change the pitch every two seconds”. Follow-ups like “now faster and higher” tweak the last clip. Your voice settings here are used as defaults.',null]]],
];
function buildHelp(){
  const body=$('help-body');
  for(const [title,rows] of HELP){
    const h=document.createElement('h3');h.textContent=title;body.appendChild(h);
    for(const [code,desc,ex] of rows){
      const r=document.createElement('div');r.className='tagrow';
      r.innerHTML='<code></code><span></span><p></p>';r.querySelector('code').textContent=code;r.querySelector('p').textContent=desc;
      if(ex){const b=document.createElement('button');b.className='ghost';b.type='button';b.textContent='Try it';
        b.onclick=()=>{const r2=document.createRange();r2.selectNodeContents(editor);r2.collapse(false);savedRange=r2;
          const tmp=document.createElement('div');const keep=[...editor.childNodes];setScript(ex);const added=[...editor.childNodes];editor.replaceChildren(...keep,document.createTextNode(' '),...added);syncRaw();
          $('help').close();editor.scrollIntoView({behavior:'smooth',block:'center'});};
        r.querySelector('span').appendChild(b);}
      body.appendChild(r);
    }
  }
}
$('help-open').onclick=()=>$('help').showModal();
$('help-close').onclick=()=>$('help').close();
$('help').addEventListener('click',e=>{if(e.target===$('help'))$('help').close();});

async function init(){
  buildFx();buildHelp();
  try{
    config=await readJSON(await fetch('/api/config'));
    config.voice_catalog.forEach(v=>voiceById[v.id]=v);
    if(config.public){document.body.classList.add('public');$('oracle-clear').classList.add('owner-only');}
    if(matchMedia('(min-width:900px)').matches)$('voice-settings').open=true;
    fillVoices();applySettings(config.settings);buildMoods();
    setScript(config.examples[0].text);
    loadHistory();loadThread();
  }catch(e){status(`Studio couldn’t load: ${e.message}`,true);$('render').disabled=true;}
}
init();
(function talkMode(){
  const btn=$('talk-btn'),label=$('talk-label'),tthread=$('talk-thread'),note=$('talk-note');
  const st=(m,err)=>{const s=$('talk-status');s.textContent=m||'';s.classList.toggle('error',!!err);};
  const T={rec:null,stream:null,chunks:[],mime:'',ctx:null,an:null,timer:0,vad:0,downAt:0,turn:null,playing:0,nextAt:0,sources:[],busy:false,heardSpeech:false,quietSince:0,started:0};
  const canRecord=!!(window.isSecureContext&&navigator.mediaDevices&&navigator.mediaDevices.getUserMedia&&window.MediaRecorder);
  function bubble(kind,text){const d=document.createElement('div');d.className='bubble '+(kind==='you'?'me':'them');const w=document.createElement('span');w.className='who';w.textContent=kind==='you'?'You said':'Hera';const t=document.createElement('span');t.className='txt';t.textContent=text||'';d.append(w,t);tthread.appendChild(d);tthread.scrollTop=tthread.scrollHeight;return d;}
  function setText(d,text){d.querySelector('.txt').textContent=text;tthread.scrollTop=tthread.scrollHeight;}
  function setBtn(mode){btn.classList.toggle('rec',mode==='rec');btn.classList.toggle('busy',mode==='busy');btn.setAttribute('aria-pressed',String(mode==='rec'));label.textContent=mode==='rec'?'Listening… tap to send':mode==='busy'?'Hera is answering…':mode==='speaking'?'Tap to interrupt':'Tap to talk';}
  if(!canRecord){
    note.hidden=false;
    if(!window.isSecureContext){note.textContent='The microphone needs HTTPS or localhost. Open your own secure Oracle address, or type to Hera below.';}
    else{note.textContent='This browser can’t record audio here. You can still type to Hera below.';}
    btn.disabled=true;
  }
  function audioCtx(){if(!T.ctx){const C=window.AudioContext||window.webkitAudioContext;T.ctx=new C();}if(T.ctx.state==='suspended')T.ctx.resume();return T.ctx;}
  function stopPlayback(){for(const s of T.sources){try{s.stop();}catch(e){}}T.sources=[];T.playing=0;T.nextAt=0;}
  async function enqueue(url){
    const ctx=audioCtx();
    const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw Error('audio '+r.status);
    const buf=await ctx.decodeAudioData(await r.arrayBuffer());
    const src=ctx.createBufferSource();src.buffer=buf;src.connect(ctx.destination);
    const at=Math.max(ctx.currentTime+0.05,T.nextAt);src.start(at);T.nextAt=at+buf.duration+0.12;T.playing++;T.sources.push(src);
    src.onended=()=>{T.playing=Math.max(0,T.playing-1);T.sources=T.sources.filter(x=>x!==src);if(!T.playing&&!T.busy)afterSpeech();};
  }
  function afterSpeech(){setBtn('idle');if($('talk-auto').checked&&canRecord&&!T.rec)startRec();}
  function pickMime(){for(const m of['audio/webm;codecs=opus','audio/ogg;codecs=opus','audio/webm','audio/mp4']){if(MediaRecorder.isTypeSupported&&MediaRecorder.isTypeSupported(m))return m;}return '';}
  async function startRec(){
    if(T.rec)return;stopPlayback();
    try{
      audioCtx();
      if(!T.stream||!T.stream.active)T.stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
    }catch(e){st('Microphone permission was blocked. Allow the mic for this site, or type below.',true);setBtn('idle');return;}
    T.mime=pickMime();T.chunks=[];
    const rec=new MediaRecorder(T.stream,T.mime?{mimeType:T.mime,audioBitsPerSecond:48000}:undefined);T.rec=rec;
    rec.ondataavailable=e=>{if(e.data&&e.data.size)T.chunks.push(e.data);};
    rec.onstop=()=>{const type=(rec.mimeType||T.mime||'audio/webm').split(';')[0];const blob=new Blob(T.chunks,{type});T.rec=null;clearTimeout(T.timer);cancelAnimationFrame(T.vad);if(!$('talk-auto').checked){T.stream.getTracks().forEach(t=>t.stop());T.stream=null;}if((performance.now()-T.started)<400||blob.size<500){setBtn('idle');st('That was too short. Tap, speak, then tap again.');return;}send(blob,type);};
    rec.start(250);T.started=performance.now();T.heardSpeech=false;T.quietSince=0;setBtn('rec');st('Listening… (up to 20 seconds)');
    T.timer=setTimeout(stopRec,20000);
    try{const ctx=audioCtx(),srcN=ctx.createMediaStreamSource(T.stream),an=ctx.createAnalyser();an.fftSize=1024;srcN.connect(an);const data=new Float32Array(an.fftSize);
      const loop=()=>{if(!T.rec)return;an.getFloatTimeDomainData(data);let sum=0;for(const v of data)sum+=v*v;const rms=Math.sqrt(sum/data.length),now=performance.now();
        if(rms>0.035){T.heardSpeech=true;T.quietSince=0;}else if(T.heardSpeech){T.quietSince=T.quietSince||now;if(now-T.quietSince>1500&&now-T.downAt>0&&!T.holding){stopRec();return;}}
        T.vad=requestAnimationFrame(loop);};loop();}catch(e){}
  }
  function stopRec(){if(T.rec&&T.rec.state!=='inactive'){T.rec.stop();}}
  async function send(blob,type){await submit({method:'POST',headers:{'Content-Type':type},body:blob},null);}
  async function submit(init,typed){
    T.busy=true;setBtn('busy');st(typed?'Hera is thinking…':'Hera is listening…');
    const you=typed?bubble('you',typed):bubble('you','…');let hera=null,played=0;
    try{
      const r=await fetch('/api/talk',init);const j=await r.json().catch(()=>({}));
      if(!r.ok)throw Error(j.detail||'Hera could not hear that.');
      for(let n=0;n<400;n++){
        await new Promise(res=>setTimeout(res,n<20?250:450));
        const s=await (await fetch(j.status_url,{cache:'no-store'})).json();
        if(s.heard&&!typed)setText(you,s.heard);
        if(s.reply){hera=hera||bubble('hera','');setText(hera,s.reply);}
        for(const seg of (s.segments||[]).slice(played)){played++;try{await enqueue(seg.mp3);}catch(e){}}
        if(played)setBtn('speaking');
        if(s.status==='error'){if(!s.heard&&!typed)you.remove();throw Error(s.message||'Something went wrong.');}
        if(s.status==='done'){st('');break;}
        if(s.message&&!played)st(s.message);else if(played)st('');
      }
    }catch(e){st(e.message,true);if(you.querySelector('.txt').textContent==='…')you.remove();}
    finally{T.busy=false;if(!T.playing)afterSpeech();}
  }
  btn.addEventListener('pointerdown',e=>{if(btn.disabled)return;e.preventDefault();T.downAt=performance.now();
    if(T.rec){stopRec();return;}
    if(T.busy&&!T.playing)return;
    T.holding=true;startRec();});
  const up=()=>{if(!T.holding)return;T.holding=false;if(T.rec&&performance.now()-T.downAt>700)stopRec();};
  btn.addEventListener('pointerup',up);btn.addEventListener('pointercancel',up);btn.addEventListener('pointerleave',up);
  btn.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();if(T.rec)stopRec();else if(!T.busy||T.playing)startRec();}});
  $('talk-type').onsubmit=e=>{e.preventDefault();const v=$('talk-input').value.trim();if(!v||T.busy)return;$('talk-input').value='';audioCtx();stopPlayback();submit({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:v})},v);};
  $('talk-clear').onclick=async()=>{if(!confirm('Clear your conversation with Hera?'))return;stopPlayback();await fetch('/api/talk/clear',{method:'POST'});tthread.replaceChildren();st('');};
  fetch('/api/talk/history',{cache:'no-store'}).then(r=>r.json()).then(({messages})=>{for(const m of messages.slice(-16))bubble(m.role==='you'?'you':'hera',m.text);}).catch(()=>{});
})();
