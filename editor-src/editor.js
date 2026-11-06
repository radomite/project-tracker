import {EditorView,basicSetup} from 'codemirror';
import {EditorState} from '@codemirror/state';
import {keymap} from '@codemirror/view';
import {typst_lezer as typst} from 'codemirror-lang-typst/lezer';
import {latex} from 'codemirror-lang-latex';
import * as Y from 'yjs';
import {yCollab} from 'y-codemirror.next';
import {Awareness} from 'y-protocols/awareness';
import * as pdfjs from 'pdfjs-dist';
pdfjs.GlobalWorkerOptions.workerSrc='/static/editor-assets/pdf.worker.mjs';
const encoder=new TextEncoder();
const latexTemplate=String.raw`\documentclass{article}
\usepackage{amsmath,amsthm}
\begin{document}
\section{Working manuscript}
Write here.
\[
\sum_{i=1}^{n}i=\frac{n(n+1)}{2}.
\]
\end{document}
`;
const decode=value=>Uint8Array.from(atob(value),c=>c.charCodeAt(0));
const encode=bytes=>{let out='';for(let i=0;i<bytes.length;i+=16384)out+=String.fromCharCode(...bytes.subarray(i,i+16384));return btoa(out);};
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export async function mount(container,{project,user,csrf,onMenu}){
  const base=`/api/v1/projects/${project.id}`;
  const abort=new AbortController(),buffers=new Map();
  let socket,disposed=false,current=null,editor=null,main='',fileEntries=[],worker=null,pdf=null;
  let compileTimer,refreshTimer,reconnectTimer,activityTimer,lastActivity=0,buildId=0,zoom=1,pdfUrl=null,auto=true;
  let scrollObserver,renderGeneration=0,compileTimeout,lastTree=null,dirtyGeneration=0,pendingJump=null;
  const key=path=>`manuscript:${user.id}:${project.id}:${path}`;
  const mainKey=`manuscript-main:${user.id}:${project.id}`;
  const readCache=path=>{try{return JSON.parse(localStorage.getItem(key(path))||'null');}catch{return null;}};
  function cache(state){try{localStorage.setItem(key(state.path),JSON.stringify({text:state.doc.getText('source').toString(),etag:state.etag}));}catch{status('Draft recovery storage is unavailable. Keep this tab open.');}}
  function pending(state){return state.pending.length>0||state.seq>state.ack;}
  function status(message){if(!disposed)container.querySelector('#editor-save-status').textContent=message;}
  function error(message){if(!disposed){container.querySelector('#editor-errors').textContent=message;container.querySelector('#editor-errors').hidden=!message;}}
  async function request(path,options={}){
    const response=await fetch(base+path,{credentials:'same-origin',signal:abort.signal,...options,headers:{'X-CSRF-Token':csrf,...options.headers}});
    if(!response.ok){const data=await response.json().catch(()=>({}));const err=new Error(data.detail||`Request failed (${response.status})`);err.status=response.status;throw err;}
    return response;
  }
  container.innerHTML=`<section class="manuscript" aria-label="Manuscript editor">
    <div class="manuscript-toolbar"><button class="btn" id="editor-menu" title="Project menu" aria-label="Toggle project menu">☰</button><button class="btn" id="editor-tree-toggle" aria-label="Toggle manuscript files">Files</button>
    <label class="main-document-label">Main <select id="editor-main" aria-label="Main document"></select></label>
    <button class="btn" id="editor-compile">Recompile</button><label class="editor-auto"><input type="checkbox" id="editor-auto" checked>Auto</label>
    <span id="editor-save-status" role="status">Connecting…</span><span class="spacer"></span>
    <button class="btn" id="editor-zoom-out" aria-label="Zoom out">−</button><button class="btn" id="editor-zoom-in" aria-label="Zoom in">+</button><a class="btn" id="editor-download" hidden download="manuscript.pdf">PDF ↓</a>
    <button class="btn" id="editor-history">History</button><a class="text-btn" href="/api/v1/editor/source" download>Editor source</a></div>
    <div class="manuscript-mobile-tabs"><button class="btn" data-pane="source">Source</button><button class="btn" data-pane="preview">Preview</button></div>
    <div id="editor-conflict" class="editor-conflict" hidden><span></span><button class="btn" id="editor-compare">Compare draft</button><button class="btn" id="editor-use-server">Use server version</button><button class="btn" id="editor-copy-draft">Save draft as file</button></div>
    <div class="manuscript-panes"><aside class="manuscript-files"><div class="editor-file-tools"><button class="text-btn" id="editor-new">New file</button><button class="text-btn" id="editor-upload">Upload</button><input type="file" id="editor-upload-input" multiple hidden></div><nav id="editor-files" aria-label="Manuscript files"></nav></aside>
    <div class="editor-resizer" data-resize="files" role="separator" aria-label="Resize file pane"></div><section class="manuscript-source" aria-label="Source editor"><div id="editor-path"></div><div id="editor-source"><p class="muted">Choose a source file, or create a Typst document.</p></div></section>
    <div class="editor-resizer" data-resize="source" role="separator" aria-label="Resize source and preview"></div><section class="manuscript-preview" aria-label="Document preview"><div id="editor-build-status" role="status">Preview ready when a main document is selected.</div><div id="editor-errors" role="alert" hidden></div><div id="editor-pages"></div></section></div>
    <dialog id="editor-dialog"></dialog></section>`;
  const root=container.querySelector('.manuscript');
  if(innerWidth<850)root.classList.add('files-collapsed');
  const $=selector=>container.querySelector(selector);
  function listen(target,event,handler,opts={}){target.addEventListener(event,handler,{...opts,signal:abort.signal});}
  function send(data){if(socket?.readyState===WebSocket.OPEN){socket.send(JSON.stringify(data));return true;}return false;}
  function flush(state){
    clearTimeout(state.timer);
    if(state.conflicted||!state.pending.length||socket?.readyState!==WebSocket.OPEN)return;
    const update=Y.mergeUpdates(state.pending);state.pending=[];
    send({type:'update',path:state.path,generation:state.generation,update:encode(update),seq:++state.seq});
  }
  function flushAll(){for(const state of buffers.values())flush(state);}
  async function saveBarrier(){
    flushAll();const deadline=Date.now()+30000;
    while([...buffers.values()].some(pending)){
      if(socket?.readyState!==WebSocket.OPEN||Date.now()>deadline)throw new Error('Edits are not yet saved. Your drafts are preserved; reconnect before committing.');
      await new Promise(resolve=>setTimeout(resolve,30));
    }
  }
  function endWindow(reason){flushAll();send({type:'end-window',reason});}
  function activity(){
    if(disposed||document.hidden||!document.hasFocus())return;
    const now=Date.now();
    if(now-lastActivity>1500){lastActivity=now;send({type:'activity'});}
    else if(!activityTimer)activityTimer=setTimeout(()=>{activityTimer=null;lastActivity=Date.now();send({type:'activity'});},1500);
  }
  function invalidatePreview(){dirtyGeneration++;buildId++;clearTimeout(compileTimeout);if(pdf)$('#editor-build-status').textContent='Preview is out of date.';}
  function scheduleCompile(){clearTimeout(compileTimer);if(auto)compileTimer=setTimeout(()=>compile().catch(e=>error(e.message)),850);}
  function observe(state){
    state.doc.on('update',(update,origin)=>{
      if(origin==='server')return;
      state.pending.push(update);cache(state);status('Saving…');activity();invalidatePreview();
      clearTimeout(state.timer);state.timer=setTimeout(()=>flush(state),200);scheduleCompile();
    });
  }
  function newBuffer(path,message){
    const doc=new Y.Doc();Y.applyUpdate(doc,decode(message.update),'server');
    const state={path,doc,generation:message.generation,etag:message.etag,pending:[],seq:0,ack:0};
    observe(state);buffers.set(path,state);return state;
  }
  function conflict(path,message){
    const state=buffers.get(path);if(state){cache(state);state.recovery=readCache(path)?.text||state.doc.getText('source').toString();state.conflicted=true;}
    if(current===path){$('#editor-conflict').hidden=false;$('#editor-conflict span').textContent=message;}
    if(state&&current===path)attach(state);
    status('Draft needs review');
  }
  function attach(state){
    editor?.destroy();editor=null;
    $('#editor-path').textContent=state.path;$('#editor-source').replaceChildren();
    const undoManager=state.undoManager??=new Y.UndoManager(state.doc.getText('source'));
    const awareness=new Awareness(state.doc);
    state.awareness?.destroy();state.awareness=awareness;
    editor=new EditorView({parent:$('#editor-source'),state:EditorState.create({doc:state.doc.getText('source').toString(),extensions:[
      basicSetup,...(state.path.toLowerCase().endsWith('.typ')?[typst()]:state.path.toLowerCase().endsWith('.tex')?[latex({enableAutocomplete:true})]:[]),
      yCollab(state.doc.getText('source'),awareness,{undoManager}),
      EditorState.readOnly.of(!!state.conflicted),EditorView.editable.of(!state.conflicted),
      EditorView.lineWrapping,EditorView.contentAttributes.of({'aria-label':'Manuscript source','spellcheck':'false'}),
      keymap.of([{key:'Mod-s',run:()=>{flushAll();return true;}}]),
      EditorView.theme({'&':{height:'100%'},'.cm-scroller':{overflow:'auto',fontFamily:'Consolas, monospace',fontSize:'14px'},'.cm-content':{padding:'12px 0'}})
    ]})});
    if(state.cursor!==undefined)editor.dispatch({selection:{anchor:Math.min(state.cursor,editor.state.doc.length)}});
    editor.scrollDOM.scrollTop=state.scroll||0;
    if(pendingJump?.path===state.path){const line=editor.state.doc.line(Math.min(editor.state.doc.lines,Math.max(1,pendingJump.line||1)));editor.dispatch({selection:{anchor:line.from},scrollIntoView:true});pendingJump=null;}
    listen(editor.scrollDOM,'scroll',activity,{passive:true});
  }
  function receiveDocument(message){
    let state=buffers.get(message.path);
    if(state&&state.generation!==message.generation&&pending(state)){conflict(message.path,'This file changed externally. Your draft is preserved.');return;}
    if(state?.generation===message.generation){
      Y.applyUpdate(state.doc,decode(message.update),'server');state.etag=message.etag;
      if(pending(state)){state.pending=[Y.encodeStateAsUpdate(state.doc)];flush(state);}
    }else{
      state?.awareness?.destroy();state?.doc.destroy();state=newBuffer(message.path,message);
      const draft=readCache(message.path);
      if(draft&&draft.text!==state.doc.getText('source').toString()){
        if(draft.etag===message.etag){state.doc.transact(()=>{const t=state.doc.getText('source');t.delete(0,t.length);t.insert(0,draft.text);});}
        else conflict(message.path,'A recovered draft and the server version differ. Compare them before continuing.');
      }
    }
    if(current===message.path){attach(state);if(!state.conflicted&&!pending(state))status('Saved');}
  }
  function connect(){
    if(disposed)return;
    socket=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}${base}/editor/ws`);
    socket.onopen=()=>send({csrf});
    socket.onmessage=event=>{
      if(disposed)return;
      const message=JSON.parse(event.data),state=buffers.get(message.path);
      if(message.type==='ready'){status('Connected');if(current)send({type:'join',path:current});}
      else if(message.type==='ping')send({type:'pong'});
      else if(message.type==='document')receiveDocument(message);
      else if(message.type==='update'){
        if(state?.generation===message.generation){Y.applyUpdate(state.doc,decode(message.update),'server');state.etag=message.etag;}
        invalidatePreview();scheduleCompile();
      }else if(message.type==='saved'&&state){
        state.ack=Math.max(state.ack,message.seq||0);state.etag=message.etag;
        if(!pending(state)){try{localStorage.removeItem(key(state.path));}catch{}if(current===state.path)status('Saved · pending Git batch');}
      }else if(message.type==='conflict')conflict(message.path,message.message);
      else if(message.type==='error'){error(message.message);status('Disconnected');}
      else if(message.type==='workspace'){
        if(lastTree&&message.tree!==lastTree){invalidatePreview();scheduleCompile();clearTimeout(refreshTimer);refreshTimer=setTimeout(()=>refreshFiles().catch(e=>error(e.message)),500);}
        lastTree=message.tree;
      }
    };
    socket.onclose=event=>{
      if(disposed)return;
      for(const state of buffers.values())if(pending(state))cache(state);
      status('Disconnected · drafts preserved');
      if(event.code!==1008)reconnectTimer=setTimeout(connect,1500);
    };
    socket.onerror=()=>status('Connection unavailable · drafts preserved');
  }
  async function refreshFiles(){
    const listing=await request('/files').then(r=>r.json());if(disposed)return;
    fileEntries=listing.entries.filter(e=>e.kind==='file');
    $('#editor-files').innerHTML=fileEntries.map(e=>`<button class="editor-file ${e.path===current?'selected':''}" data-path="${esc(e.path)}" title="${esc(e.path)}">${esc(e.path)}</button>`).join('')||'<p class="muted">No files yet.</p>';
    const choices=fileEntries.filter(e=>/\.(typ|tex)$/i.test(e.path));
    if(!choices.some(e=>e.path===main)){main=choices.find(e=>e.path===localStorage.getItem(mainKey))?.path||choices.find(e=>e.path==='main.typ')?.path||choices[0]?.path||'';}
    $('#editor-main').innerHTML=choices.map(e=>`<option value="${esc(e.path)}" ${e.path===main?'selected':''}>${esc(e.path)}</option>`).join('')||'<option value="">No main document</option>';
    $('#editor-compile').disabled=!main;
    if(!current&&main)open(main);
    if(!choices.length&&!current)$('#editor-source').innerHTML='<div class="editor-empty"><p>Start a manuscript.</p><button class="btn" id="editor-create-main">New Typst document</button> <button class="btn" id="editor-create-latex">New LaTeX document</button></div>';
  }
  function open(path){
    if(current&&editor){const old=buffers.get(current);if(old){old.cursor=editor.state.selection.main.anchor;old.scroll=editor.scrollDOM.scrollTop;flush(old);}}
    current=path;$('#editor-conflict').hidden=true;
    if(/\.(pdf|png|jpe?g|gif|webp|zip|gz|ttf|otf|woff2?)$/i.test(path)){
      editor?.destroy();editor=null;$('#editor-path').textContent=path;$('#editor-source').innerHTML=`<div class="editor-empty"><p>Binary project asset.</p><a class="btn" href="${base}/files/content?path=${encodeURIComponent(path)}" download>Download ${esc(path.split('/').pop())}</a></div>`;return;
    }
    const state=buffers.get(path);if(state)attach(state);else{editor?.destroy();editor=null;$('#editor-source').textContent='Loading source…';$('#editor-path').textContent=path;}
    send({type:'join',path});
    $('#editor-files').querySelectorAll('[data-path]').forEach(el=>el.classList.toggle('selected',el.dataset.path===path));
    const hash=new URLSearchParams(location.hash.slice(1));hash.set('file',path);history.replaceState(null,'','#'+hash);
  }
  function showDialog(title,body){const dialog=$('#editor-dialog');dialog.innerHTML=`<div class="dialog-header"><h2>${esc(title)}</h2><button class="btn" type="button" id="editor-dialog-close">Close</button></div><div class="dialog-body">${body}</div>`;dialog.showModal();}
  async function createFile(path,text,asMain=false){
    await request('/files/content?path='+encodeURIComponent(path),{method:'PUT',headers:{'If-None-Match':'*','Content-Type':'application/octet-stream'},body:encoder.encode(text)});
    if(asMain){main=path;localStorage.setItem(mainKey,main);}
    await refreshFiles();open(path);scheduleCompile();
  }
  function fileForm(){showDialog('New manuscript file','<form id="editor-new-form"><label>File path<input name="path" aria-label="New source file path" required value="main.typ"></label><button class="btn" type="submit">Create file</button><p id="editor-form-error" class="error"></p></form>');}
  function sourceForDraft(path){const state=buffers.get(path);const recovered=readCache(path);return state?.recovery??recovered?.text??state?.doc.getText('source').toString()??'';}
  function discardBuffer(path){const state=buffers.get(path);if(current===path){editor?.destroy();editor=null;}clearTimeout(state?.timer);state?.awareness?.destroy();state?.undoManager?.destroy();state?.doc.destroy();buffers.delete(path);try{localStorage.removeItem(key(path));}catch{}}
  async function compile(){
    clearTimeout(compileTimer);if(disposed||!main)return;
    flushAll();const id=++buildId,version=dirtyGeneration,entry=main;let draft=false;
    clearTimeout(compileTimeout);
    $('#editor-build-status').textContent='Compiling…';
    if(entry.toLowerCase().endsWith('.tex')){
      await saveBarrier();if(disposed||id!==buildId)return;
      try{
        const result=await request('/editor/latex',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({main:entry})}).then(r=>r.json());
        await receiveResult({data:{id,pdf:result.pdf?decode(result.pdf):null,error:result.status!==0?result.log:undefined,diagnostics:[]}});
      }catch(e){if(id===buildId){error(e.message);$('#editor-build-status').textContent='LaTeX compilation unavailable · source preserved';if(e.status===429&&auto)scheduleCompile();}}
      return;
    }
    const snapshot=await request('/editor/snapshot').then(r=>r.json());if(disposed||id!==buildId)return;
    const sources=Object.fromEntries(snapshot.files.map(e=>[e.path,decode(e.content)]));
    for(const [path,state] of buffers)if(pending(state)){sources[path]=encoder.encode(state.doc.getText('source').toString());draft=true;}
    if(!worker){worker=new Worker('/static/editor-assets/typst-worker.js',{type:'module'});}
    clearTimeout(compileTimeout);
    compileTimeout=setTimeout(()=>{worker?.terminate();worker=null;error('Compilation timed out. Your source is preserved.');$('#editor-build-status').textContent='Preview is out of date.';},30000);
    async function receiveResult(event){
      const result=event.data;if(disposed||result.id!==buildId||version!==dirtyGeneration)return;
      clearTimeout(compileTimeout);
      const diagnostics=result.diagnostics||[];
      const failures=diagnostics.filter(d=>String(d.severity).toLowerCase()==='error'||d.severity?.Error!==undefined);
      if(result.error||failures.length||!result.pdf?.length){
        renderDiagnostics(diagnostics,result.error||(!diagnostics.length?'Compilation did not produce a PDF.':''));
        $('#editor-build-status').textContent='Compilation failed · last successful preview retained';return;
      }
      renderDiagnostics(diagnostics,'');
      try{
        const bytes=new Uint8Array(result.pdf);
        const next=await pdfjs.getDocument({data:bytes.slice()}).promise;
        if(disposed||result.id!==buildId){next.destroy();return;}
        await pdf?.destroy();pdf=next;
        if(pdfUrl)URL.revokeObjectURL(pdfUrl);pdfUrl=URL.createObjectURL(new Blob([bytes],{type:'application/pdf'}));
        $('#editor-download').href=pdfUrl;$('#editor-download').download=entry.replace(/\.(typ|tex)$/i,'.pdf').split('/').pop();$('#editor-download').hidden=false;
        $('#editor-build-status').textContent=`${draft?'Draft preview':'Preview'} · ${pdf.numPages} page${pdf.numPages===1?'':'s'}`;
        await renderPages();
      }catch(e){error(e.message);}
    }
    worker.onmessage=receiveResult;
    worker.onerror=event=>{clearTimeout(compileTimeout);error('Compiler worker: '+event.message);worker?.terminate();worker=null;};
    worker.postMessage({id,main:entry,sources});
  }
  function renderDiagnostics(diagnostics,fallback){
    const box=$('#editor-errors');box.replaceChildren();
    const seen=new Set();
    for(const diagnostic of diagnostics){
      const message=diagnostic.message||String(diagnostic),path=String(diagnostic.path||'').replace(/^\//,'');
      if(seen.has(message))continue;seen.add(message);
      const row=document.createElement('button');row.className='editor-diagnostic';row.textContent=(path?path+': ':'')+message;
      row.onclick=()=>{if(path){pendingJump={path,line:(diagnostic.range?.start?.line??0)+1};open(path);}};box.append(row);
    }
    if(fallback){
      for(const text of fallback.split('\n')){const match=text.match(/^(?:\.\/)?(.+?\.tex):(\d+):\s*(.+)$/);if(match&&fileEntries.some(e=>e.path===match[1])){const row=document.createElement('button');row.className='editor-diagnostic';row.textContent=text;row.onclick=()=>{pendingJump={path:match[1],line:Number(match[2])};open(match[1]);};box.append(row);}}
      const pre=document.createElement('pre');pre.textContent=fallback;box.append(pre);
    }box.hidden=!box.childNodes.length;
  }
  async function renderPages(){
    if(!pdf)return;const gen=++renderGeneration,documentPdf=pdf;
    scrollObserver?.disconnect();$('#editor-pages').replaceChildren();
    const render=async placeholder=>{
      if(placeholder.dataset.rendered||disposed||gen!==renderGeneration)return;placeholder.dataset.rendered='true';
      const page=await documentPdf.getPage(Number(placeholder.dataset.page));if(disposed||gen!==renderGeneration)return;
      const width=Math.max(180,$('.manuscript-preview').clientWidth-42),scale=width/page.getViewport({scale:1}).width*zoom;
      const viewport=page.getViewport({scale}),ratio=Math.min(devicePixelRatio||1,2),canvas=document.createElement('canvas');
      canvas.width=Math.floor(viewport.width*ratio);canvas.height=Math.floor(viewport.height*ratio);canvas.style.width=viewport.width+'px';canvas.style.height=viewport.height+'px';canvas.setAttribute('aria-label','Document page '+placeholder.dataset.page);
      placeholder.style.minHeight='';placeholder.append(canvas);
      await page.render({canvasContext:canvas.getContext('2d'),viewport,transform:ratio!==1?[ratio,0,0,ratio,0,0]:null}).promise;
    };
    scrollObserver=new IntersectionObserver(entries=>{for(const item of entries)if(item.isIntersecting)render(item.target).catch(e=>{if(!disposed)error(e.message);});},{root:$('.manuscript-preview'),rootMargin:'400px'});
    for(let i=1;i<=pdf.numPages;i++){const p=document.createElement('div');p.className='editor-pdf-page';p.dataset.page=i;p.style.minHeight='700px';$('#editor-pages').append(p);scrollObserver.observe(p);}
  }
  listen(root,'click',event=>{
    const button=event.target.closest('button');if(!button)return;activity();
    if(button.dataset.path){open(button.dataset.path);return;}
    if(button.dataset.pane){root.dataset.pane=button.dataset.pane;return;}
    const actions={
      'editor-menu':onMenu,'editor-tree-toggle':()=>root.classList.toggle('files-collapsed'),
      'editor-compile':()=>compile().catch(e=>error(e.message)),
      'editor-new':fileForm,'editor-create-main':()=>createFile('main.typ','= Working manuscript\n\nWrite here.\n\n$ sum_(i=1)^n i = (n(n+1))/2 $\n').catch(e=>error(e.message)),
      'editor-upload':()=>$('#editor-upload-input').click(),
      'editor-create-latex':()=>createFile('main.tex',latexTemplate,true).catch(e=>error(e.message)),
      'editor-zoom-in':()=>{zoom=Math.min(3,zoom+.15);renderPages();},'editor-zoom-out':()=>{zoom=Math.max(.4,zoom-.15);renderPages();},
      'editor-dialog-close':()=>$('#editor-dialog').close(),
      'editor-history':async()=>{const data=await request('/files').then(r=>r.json());showDialog('File history',`<p>Saved edits collect into a pending Git batch.</p>${data.history.pending.length?'<button class="btn" id="editor-commit">Commit batch</button>':''}<ul>${data.history.pending.map(e=>`<li>${esc(e.message)} · ${esc(e.author)}${e.window_id?e.closed?' · edit window closed':' · editing':''}</li>`).join('')}</ul><hr><ul>${data.history.items.map(e=>`<li>${esc(e.message)} · ${esc(e.author)} <code>${esc(e.commit?.slice(0,7)||'')}</code></li>`).join('')}</ul>`);},
      'editor-commit':async()=>{await saveBarrier();await request('/files/commit',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});$('#editor-dialog').close();status('Git batch committed');},
      'editor-compare':async()=>{const draft=sourceForDraft(current),remote=await request('/files/content?path='+encodeURIComponent(current)).then(r=>r.text());showDialog('Compare draft',`<div class="editor-compare-columns"><label>Your draft<textarea readonly>${esc(draft)}</textarea></label><label>Server version<textarea readonly>${esc(remote)}</textarea></label></div>`);},
      'editor-use-server':()=>{discardBuffer(current);$('#editor-conflict').hidden=true;send({type:'join',path:current});},
      'editor-copy-draft':()=>showDialog('Save recovered draft',`<form id="editor-draft-form"><label>New file path<input name="path" required value="${esc(current.replace(/(\.[^/.]+)?$/,'.recovered$1'))}"></label><button class="btn" type="submit">Save draft</button><p id="editor-form-error" class="error"></p></form>`)
    };
    try{Promise.resolve(actions[button.id]?.()).catch(e=>error(e.message));}catch(e){error(e.message);}
  });
  listen(root,'submit',async event=>{
    if(!['editor-new-form','editor-draft-form'].includes(event.target.id))return;event.preventDefault();
    const path=new FormData(event.target).get('path');
    try{const recovering=event.target.id==='editor-draft-form',oldPath=current,text=recovering?sourceForDraft(current):path.endsWith('.typ')?'= Working manuscript\n\nWrite here.\n':path.endsWith('.tex')?latexTemplate:'';await createFile(path,text);if(recovering)discardBuffer(oldPath);$('#editor-dialog').close();}catch(e){$('#editor-form-error').textContent=e.message;}
  });
  listen($('#editor-auto'),'change',event=>{auto=event.target.checked;if(auto)scheduleCompile();});
  listen($('#editor-main'),'change',event=>{main=event.target.value;localStorage.setItem(mainKey,main);invalidatePreview();scheduleCompile();});
  listen($('#editor-upload-input'),'change',async event=>{
    try{for(const file of event.target.files)await request('/files/content?path='+encodeURIComponent(file.name),{method:'PUT',headers:{'If-None-Match':'*','Content-Type':'application/octet-stream'},body:file});await refreshFiles();scheduleCompile();}catch(e){error(e.message);}
  });
  for(const type of ['pointerdown','pointermove','keydown','wheel','touchmove','scroll'])listen(root,type,activity,{passive:true,capture:true});
  listen(window,'blur',()=>{clearTimeout(activityTimer);activityTimer=null;endWindow('focus');});
  listen(document,'visibilitychange',()=>{if(document.hidden){clearTimeout(activityTimer);activityTimer=null;endWindow('focus');}});
  listen(window,'pagehide',()=>endWindow('navigation'));
  listen(root,'pointerdown',event=>{
    const separator=event.target.closest('[data-resize]');if(!separator)return;
    separator.setPointerCapture(event.pointerId);
    const move=e=>{if(separator.dataset.resize==='files')root.style.setProperty('--editor-files',Math.max(130,Math.min(400,e.clientX-root.getBoundingClientRect().left))+'px');else{const ratio=Math.max(20,Math.min(80,(e.clientX-$('.manuscript-source').getBoundingClientRect().left)/($('.manuscript-source').clientWidth+$('.manuscript-preview').clientWidth)*100));root.style.setProperty('--editor-source',ratio+'fr');root.style.setProperty('--editor-preview',(100-ratio)+'fr');}};
    separator.addEventListener('pointermove',move);separator.addEventListener('pointerup',()=>separator.removeEventListener('pointermove',move),{once:true});
  });
  connect();await refreshFiles();
  const requested=new URLSearchParams(location.hash.slice(1)).get('file');if(requested&&fileEntries.some(e=>e.path===requested))open(requested);
  scheduleCompile();
  return {destroy(){
    if(disposed)return;endWindow('navigation');disposed=true;abort.abort();socket?.close();worker?.terminate();pdf?.destroy();editor?.destroy();scrollObserver?.disconnect();if(pdfUrl)URL.revokeObjectURL(pdfUrl);
    for(const timer of [compileTimer,refreshTimer,reconnectTimer,activityTimer,compileTimeout])clearTimeout(timer);
    for(const state of buffers.values()){clearTimeout(state.timer);if(pending(state))cache(state);state.awareness?.destroy();state.doc.destroy();}
  }};
}
