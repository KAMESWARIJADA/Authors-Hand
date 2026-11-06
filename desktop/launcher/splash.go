package main

const splashHTML = `<!doctype html>
<html><head><meta charset="utf-8"><title>Author&#39;s Hand</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--navy:#0b1f33;--teal:#0f766e;--amber:#b45309;--ink:#13233a;--muted:#5b6b7f}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
     background:linear-gradient(135deg,#0b1f33 0%,#0f3d4a 60%,#0f766e 100%);font-family:"Segoe UI",Arial,sans-serif;color:#fff}
.card{width:min(620px,92vw);background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.18);border-radius:18px;padding:34px 36px}
.logo{width:56px;height:56px;border-radius:50%;background:var(--teal);display:flex;align-items:center;justify-content:center;
      font-weight:700;font-size:20px;margin-bottom:14px;border:2px solid rgba(255,255,255,.35)}
h1{margin:0 0 4px;font-size:28px}
.sub{color:#cfe3e8;margin:0 0 26px;font-size:15px}
.stage{font-weight:600;font-size:17px}
.detail{color:#cfe3e8;font-size:14px;margin:4px 0 14px}
.bar{height:10px;border-radius:99px;background:rgba(255,255,255,.15);overflow:hidden}
.fill{height:100%;width:2%;background:linear-gradient(90deg,#5eead4,#f3c48c);transition:width .6s}
.log{margin-top:18px;font:12px Consolas,monospace;color:#9fbfc8;height:110px;overflow:hidden;white-space:pre-wrap}
.err{display:none;margin-top:18px;background:#fff3f0;color:#7c1d0b;border-radius:10px;padding:12px 14px;font-size:14px}
button{margin-top:10px;background:var(--amber);color:#fff;border:0;border-radius:8px;padding:9px 16px;font-size:14px;cursor:pointer}
a{color:#5eead4}
.note{margin-top:20px;font-size:12.5px;color:#9fbfc8}
</style></head>
<body><div class="card">
<div class="logo">&#9997;</div>
<h1>Author&#39;s Hand</h1>
<p class="sub">Your AI research companion — from papers to your own manuscript</p>
<div class="stage" id="stage">Starting…</div>
<div class="detail" id="detail"></div>
<div class="bar"><div class="fill" id="fill"></div></div>
<div class="log" id="log"></div>
<div class="err" id="err"><b>Setup could not finish.</b><br><span id="errmsg"></span><br>
<button onclick="fetch('/retry').then(()=>location.reload())">Retry</button>  <a href="/log" target="_blank">Open the log</a></div>
<div class="note">First start installs a private Python and research libraries into your user folder (no admin rights, nothing system-wide). Later starts take a few seconds.</div>
</div>
<script>
async function tick(){
  try{
    const s = await (await fetch('/status',{cache:'no-store'})).json();
    document.getElementById('stage').textContent = s.stage||'';
    document.getElementById('detail').textContent = s.detail||'';
    document.getElementById('fill').style.width = (s.percent||2)+'%';
    document.getElementById('log').textContent = (s.lines||[]).join('\n');
    if(s.error){ document.getElementById('err').style.display='block'; document.getElementById('errmsg').textContent=s.error; return; }
    if(s.ready && s.url){ location.replace(s.url); return; }
  }catch(e){}
  setTimeout(tick, 700);
}
tick();
</script></body></html>`
