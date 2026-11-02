"""Dependency-free MCP Apps view; all decisions stay in the conversation."""

# BSC-CHAT-005
REVIEW_APP = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<title>Book Studio</title>
<style>
:root{color-scheme:light dark;--bg:#faf9f6;--ink:#252923;--muted:#697066;--line:#e1e4dc;--green:#356b4b}
@media(prefers-color-scheme:dark){:root{--bg:#1b1e1a;--ink:#e7ebe3;--muted:#a9b1a3;--line:#3a4036;--green:#9ac9a7}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,sans-serif}
main{padding:24px;max-width:920px;margin:auto}header p{margin:0;color:var(--muted);font-size:12px;letter-spacing:.04em}
h1{font-size:22px;line-height:1.3;margin:8px 0 16px;font-weight:600;overflow-wrap:anywhere}
h2{font-size:14px;margin:0 0 10px;font-weight:600}section{padding:18px 0;border-top:1px solid var(--line)}
p{margin:6px 0;overflow-wrap:anywhere}.muted,small{color:var(--muted)}progress{width:100%;height:8px;accent-color:var(--green)}
#stage{color:var(--green);font-weight:600}#connection{font-size:12px;color:var(--muted)}#connection.error{color:#b04b32}
ol{list-style:none;margin:8px 0 0;padding:0}li{display:flex;justify-content:space-between;gap:16px;padding:6px 0}
li span:first-child{min-width:0;overflow-wrap:anywhere}li span:last-child{white-space:nowrap;color:var(--muted)}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:24px;padding:12px 0;border-top:1px solid var(--line)}
.pair p{white-space:pre-wrap}.label{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
details{margin-top:8px}summary{cursor:pointer;color:var(--muted)}#hint{margin-bottom:0}#sample:empty{display:none}
@media(max-width:520px){main{padding:16px}.pair{grid-template-columns:1fr;gap:12px}h1{font-size:19px}}
</style></head><body><main>
<header><p>BOOK STUDIO</p><h1 id="title">Your book</h1></header>
<p id="connection" role="status">Waiting for the book…</p>
<section><h2 id="stage">Preparing</h2><p id="counts"></p><progress id="progress" hidden></progress>
<p id="hint" class="muted"></p></section>
<section id="chapters"><h2>Chapters</h2><ol id="documents"></ol></section>
<section id="sample"><h2>Sample</h2><p class="muted">Read the comparison, then tell the AI what to keep or change.</p><div id="pairs"></div></section>
<p class="muted">Continue in chat to approve the sample, request changes, pause, or continue.</p>
</main><script>
(() => {
  let sequence = 1, ready = false, project = null, generation = 0, inflight = null, timer = null, lastStamp = null, bridgeOrigin = null;
  const pending = new Map();
  const labels = {pilot_proposed:'Sample proposed',pilot_active:'Translating the sample',pilot_review_required:'Your sample is ready',full_active:'Translating the book',finished:'Your book is ready',legacy:'Book in progress'};
  const hints = {pilot_proposed:'Tell the AI whether to prepare this sample.',pilot_active:'The sample is in progress. You can ask the AI to pause.',pilot_review_required:'Tell the AI what to change, or approve the sample to continue.',full_active:'Completed passages are saved. Ask the AI to pause or continue in chat.',finished:'The delivered book matches its final verification receipt.',legacy:'Ask the AI for the next step.'};
  const el = id => document.getElementById(id);
  const send = message => window.parent.postMessage({jsonrpc:'2.0',...message}, bridgeOrigin && bridgeOrigin !== 'null' ? bridgeOrigin : '*');
  function connection(text, error=false){el('connection').textContent=text;el('connection').className=error?'error':'';}
  function text(tag,value,cls){const n=document.createElement(tag);n.textContent=String(value ?? '');if(cls)n.className=cls;return n;}
  function render(view){
    if(!view || !view.coverage)throw new Error('Progress is unavailable. Ask the AI to check the project.');
    el('title').textContent=view.title || view.project || 'Your book';
    el('stage').textContent=labels[view.stage] || 'Book in progress';
    const c=view.coverage, progress=el('progress');
    el('counts').textContent=`${c.translated} of ${c.eligible} passages completed · ${c.remaining} remaining`;
    progress.hidden=!c.eligible;progress.max=c.eligible||1;progress.value=c.translated;
    el('hint').textContent=hints[view.stage] || 'Continue the conversation for the next step.';
    const docs=el('documents');docs.replaceChildren();
    for(const d of view.documents || []){const li=document.createElement('li');li.append(text('span',d.title || d.path),text('span',d.excluded?'Excluded':`${d.translated} / ${d.blocks}`));docs.append(li);}
    if(view.documents_total>(view.documents || []).length)docs.append(text('li',`Showing the first ${view.documents.length} of ${view.documents_total} chapters.`,'muted'));
    const pairs=el('pairs'), open=new Set([...pairs.querySelectorAll('details[open]')].map(n=>n.dataset.index));pairs.replaceChildren();
    if(view.sample_excerpt)pairs.append(text('p','Representative excerpts. Ask the AI to show more in chat.','muted'));
    for(const [i,p] of (view.pairs || []).entries()){
      const pair=document.createElement('div');pair.className='pair';
      for(const [label,value] of [['Source',p.source],['Translation',p.state==='done'?p.translation:'Not translated yet']]){
        const col=document.createElement('div');col.append(text('div',label,'label'),text('p',value));pair.append(col);
      }
      if(i<3)pairs.append(pair);else{const detail=document.createElement('details');detail.dataset.index=String(i);detail.open=open.has(String(i));detail.append(text('summary',`Passage ${i+1}`),pair);pairs.append(detail);}
    }
    el('sample').hidden=!(view.pairs || []).length;
    lastStamp=new Date().toLocaleTimeString();connection(`Updated ${lastStamp}`);
    send({method:'ui/notifications/size-changed',params:{height:document.documentElement.scrollHeight}});
  }
  function request(method,params){const id=++sequence;send({id,method,params});return new Promise((resolve,reject)=>{const timeout=setTimeout(()=>{pending.delete(id);reject(new Error('The host did not respond.'));},12000);pending.set(id,{resolve,reject,timeout});});}
  async function refresh(){
    if(!ready || !project || document.hidden || inflight===generation)return;
    const selected=project, revision=generation;inflight=revision;
    try{const result=await request('tools/call',{name:'view',arguments:{project:selected}});if(revision!==generation)return;if(result.isError)throw new Error('The project needs attention.');render(result.structuredContent?.view);}
    catch(error){if(revision===generation)connection(`${lastStamp?'Last updated '+lastStamp+'. ':''}Updates unavailable. Ask the AI to check progress.`,true);}
    finally{if(inflight===revision)inflight=null;}
  }
  window.addEventListener('message',event=>{
    if(event.source!==window.parent)return;
    if(bridgeOrigin!==null && event.origin!==bridgeOrigin)return;
    const m=event.data;if(!m || m.jsonrpc!=='2.0')return;
    if(m.id===1){if(m.error){connection('The host cannot display this view. Continue in chat.',true);return;}bridgeOrigin=event.origin;ready=true;send({method:'ui/notifications/initialized',params:{}});return;}
    const p=pending.get(m.id);if(p){clearTimeout(p.timeout);pending.delete(m.id);m.error?p.reject(new Error(m.error.message)):p.resolve(m.result);return;}
    if(m.method==='ui/notifications/tool-input'){const v=m.params?.arguments?.project;if(typeof v==='string'){const changed=v!==project;project=v;generation++;if(changed){lastStamp=null;connection('Loading selected book…');}}}
    if(m.method==='ui/notifications/tool-result'){
      generation++;
      try{if(m.params?.isError)throw new Error('Project unavailable');render(m.params?.structuredContent?.view);}catch(error){connection('This view is unavailable. Continue in chat for progress and the sample.',true);}
    }
  });
  timer=setInterval(refresh,5000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
  window.addEventListener('pagehide',()=>{clearInterval(timer);for(const p of pending.values()){clearTimeout(p.timeout);p.reject(new Error('View closed'));}pending.clear();});
  send({id:1,method:'ui/initialize',params:{protocolVersion:'2026-01-26',appInfo:{name:'book-studio-review',version:'%VERSION%'},appCapabilities:{}}});
})();
</script></body></html>'''
