/* Local research project interface. */
'use strict';
const app = document.querySelector('#app');
const modal = document.querySelector('#modal');
const S = {user:null,csrf:'',projects:[],project:null,topics:[],topic:null,overview:null,messages:[],messageMap:new Map(),selected:new Set(),selectionAnchor:null,drafts:new Map(),load:0,invite:new URLSearchParams(location.hash.slice(1)).get('invite')};
const pendingReads=new Map(),knownReads=new Set();
let readTimer;
const icons = {
 quill:'<path d="M3 21 11 13M6 18l1-7C11 5 16 2 22 2c0 6-3 11-9 15l-7 1ZM11 13l7-7M11 9l4 1M14 13l1-3"/>',
 reply:'<path d="m9 5-7 7 7 7M2 12h11a8 8 0 0 1 8 8"/>',
 tag:'<path d="M3 3h8l10 10-8 8L3 11z"/><circle cx="7.5" cy="7.5" r="1"/>',
 home:'<path d="m3 10 9-7 9 7v11h-6v-8H9v8H3z"/>',
 book:'<path d="M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-2H4z"/><path d="M13 7a3 3 0 0 1 3-3h5v15h-5a4 4 0 0 0-3 2"/>',
 leaf:'<path d="M6 21V4h13M6 11h10M10 4v17"/>',
 folder:'<path d="M3 7V4h7l2 3h9v13H3z"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',
 arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',
 chevron:'<path d="m9 5 7 7-7 7"/>',
 down:'<path d="m6 9 6 6 6-6"/>',
 up:'<path d="m6 15 6-6 6 6"/>',
 search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
 question:'<path d="M9 8a3 3 0 1 1 5 2c-2 1-2 2-2 3m0 3v1"/><circle cx="12" cy="12" r="9"/>',
 technique:'<path d="M9 18h6m-5 3h4M9 15c0-2-3-3-3-6a6 6 0 0 1 12 0c0 3-3 4-3 6z"/>',
 solution:'<path d="m6 12 4 4 8-9"/><circle cx="12" cy="12" r="9"/>',
 observation:'<path d="M2 12s4-6 10-6 10 6 10 6-4 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="2"/>',
 experiment:'<path d="M9 3h6m-5 0v6L4 19a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2L14 9V3M7 15h10"/>',
 note:'<path d="M5 3h10l4 4v14H5zM14 3v5h5M8 12h8M8 16h6"/>',
 people:'<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6m2 4a5 5 0 0 1 3 5"/>',
 settings:'<path d="m9 3-.6 3-2.4 1-2.5-1.2-2 3.4L4 11v2l-2.5 1.8 2 3.4L6 17l2.4 1L9 21h4l.6-3 2.4-1 2.5 1.2 2-3.4L18 13v-2l2.5-1.8-2-3.4L16 7l-2.4-1L13 3z"/><circle cx="11" cy="12" r="3"/>',
 file:'<path d="M5 3h9l5 5v13H5zM14 3v5h5"/>',
 upload:'<path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6"/>',
 download:'<path d="M12 3v13m-5-5 5 5 5-5M4 15v6h16v-6"/>',
 trash:'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
 'file-plus':'<path d="M5 3h9l5 5v4M14 3v5h5M5 3v18h7m5-6v6m-3-3h6"/>',
 'folder-plus':'<path d="M3 7V4h7l2 3h9v13H3zM12 10v7m-3-3.5h6"/>',
 'folder-upload':'<path d="M3 7V4h7l2 3h9v13H3zM12 18v-7m-3 3 3-3 3 3"/>',
 git:'<circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="5" r="2"/><path d="M6 7v10M18 7v2a5 5 0 0 1-5 5H6"/>',
 logout:'<path d="M9 4H4v16h5m4-12 4 4-4 4M9 12h12"/>',
 close:'<path d="m6 6 12 12M18 6 6 18"/>',
 link:'<path d="m10 14 4-4M8 15l-2 2a4 4 0 0 1-5-5l5-5a4 4 0 0 1 6 0m0 2 2-2a4 4 0 0 1 5 5l-5 5a4 4 0 0 1-6 0" transform="translate(2 0)"/>',
 clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
 agent:'<rect x="4" y="7" width="16" height="13" rx="3"/><path d="M12 7V3m-3 10v2m6-2v2M2 12h2m16 0h2"/>',
 person:'<circle cx="12" cy="7" r="3"/><path d="M5 21v-3a7 7 0 0 1 14 0v3"/>',
 pin:'<path d="m14 3 7 7-5 1-3 5-3-3-5 6m5-6-3-3 5-3z"/>',
 menu:'<path d="M4 6h16M4 12h16M4 18h16"/>',
 external:'<path d="M14 3h7v7m0-7L10 14M10 5H4v16h16v-6"/>',
 edit:'<path d="m16 3 5 5-12 12H4v-5zM13 6l5 5"/>',
 archive:'<path d="M3 4h18v5H3zM5 9v12h14V9m-10 5h6"/>',
};
const ic = name => `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.note}</svg>`;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kindName = k => ({question:'Question',solution:'Proposed solution',technique:'Technique',observation:'Observation',experiment:'Experiment',note:'Note'}[k] || k);
const plural = k => ({question:'Questions',solution:'Solutions',technique:'Techniques',observation:'Observations',experiment:'Experiments',note:'Notes'}[k]);
const stateName = (v, question=false) => ({open:question?'Unresolved':'Open',in_progress:question?'Investigating':'In progress',closed:question?'Resolved':'Closed'}[v] || v);
const relationName = r => ({answers:'answers',uses:'uses',follows_up:'follows up on',refutes:'refutes'}[r] || r);
const pill = (text, cls='') => `<span class="pill ${esc(cls)}">${esc(text)}</span>`;
const statusPill = item => `<span class="pill status ${esc(item.status)}"><i class="dot"></i>${esc(stateName(item.status,item.kind==='question'))}</span>`;
function timeAgo(date) {
  const seconds = Math.max(0, (Date.now()-new Date(date).getTime())/1000);
  if (seconds < 60) return 'Just now';
  if (seconds < 3600) return `${Math.floor(seconds/60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds/3600)}h ago`;
  if (seconds < 604800) return `${Math.floor(seconds/86400)}d ago`;
  return new Date(date).toLocaleDateString(undefined,{month:'short',day:'numeric'});
}
function excerpt(body, max=155) {
  // Keep TeX intact: stripping Markdown underscores or cutting halfway through
  // an equation would change its meaning or leave an unmatched delimiter.
  const parts=body.split(/(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$(?!\s)[^$\n]+?\$)/g);
  let text='';
  for(let i=0;i<parts.length;i++) {
    const part=i%2?parts[i]:parts[i].replace(/\[([^\]]+)\]\([^)]+\)/g,'$1').replace(/[#*`_>]/g,'').replace(/\s+/g,' ');
    if(text.length>=max)return text.trimEnd()+'…';
    if(i%2)text+=part;
    else {
      const available=max-text.length;
      text+=part.slice(0,available);
      if(part.length>available)return text.trimEnd()+'…';
    }
  }
  return text.trim();
}
function toast(message, bad=false) {
  const t = document.querySelector('#toast'); t.textContent=message; t.className='visible'+(bad?' bad':'');
  clearTimeout(toast.timer); toast.timer=setTimeout(()=>t.className='',4200);
}
async function api(path, method='GET', data, headers={}) {
  const response = await fetch('/api/v1'+path,{method, credentials:'same-origin',
    headers:{...(data!==undefined?{'Content-Type':'application/json'}:{}),...(S.csrf?{'X-CSRF-Token':S.csrf}:{}),...headers},
    ...(data!==undefined?{body:JSON.stringify(data)}:{})});
  const result=await response.json().catch(()=>({detail:'The server returned an unexpected response.'}));
  if (!response.ok) {
    let message = result.detail;
    if (Array.isArray(message)) message=message.map(e=>`${e.loc?.slice(1).join(' ') || 'Input'}: ${e.msg}`).join('; ');
    const error=new Error(message || `Request failed (${response.status}).`);error.status=response.status;throw error;
  }
  return result;
}
function typeset(el) {
  renderMathInElement(el,{
    delimiters:[{left:'$$',right:'$$',display:true},{left:'\\[',right:'\\]',display:true},{left:'\\(',right:'\\)',display:false},{left:'$',right:'$',display:false}],
    ignoredClasses:['katex','katex-display'],
    throwOnError:false,trust:false,
  });
}
function markdown(el, text) {
  // Protect TeX from Markdown's interpretation of backslashes and underscores.
  const equations=[];
  const tokenPrefix = 'MATHTOKEN'+crypto.randomUUID().replaceAll('-','');
  const protectedText=text.replace(/(```[\s\S]*?```|`[^`\n]+`)|(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$(?!\s)[^$\n]+?\$)/g,(all,code,math)=>{
    if(code)return code; const key=tokenPrefix+equations.length+'END'; equations.push(math);return key;
  });
  let html=marked.parse(protectedText,{breaks:false,gfm:true});
  equations.forEach((math,i)=>html=html.replaceAll(tokenPrefix+i+'END',()=>esc(math)));
  el.innerHTML=DOMPurify.sanitize(html,{FORBID_TAGS:['style','form','input','iframe','img'],FORBID_ATTR:['style']});
  el.querySelectorAll('a').forEach(a=>{a.target='_blank';a.rel='noopener noreferrer';});
  typeset(el);
}
function dialog(title, body, footer='', wide=false) {
  modal.className=wide?'wide':'';
  modal.innerHTML=`<div class="dialog-header"><h2 id="modal-title">${esc(title)}</h2><button class="btn square" data-action="close" aria-label="Close dialog">${ic('close')}</button></div>${body}${footer}`;
  modal.querySelectorAll('.detail-title,.linked-item span:not(.pill),.question-option label').forEach(typeset);
  if(!modal.open)modal.showModal();
}
const dialogError = () => '<div class="error" id="dialog-error" role="alert"></div>';
const footer = (form, label='Save changes') => `<div class="dialog-footer"><button class="btn ghost" data-action="close">Cancel</button><button class="btn primary" type="submit" form="${form}">${esc(label)}</button></div>`;
const ctx = path => `/projects/${S.project.id}${path}`;
const short = message => message.title || message.body.split('\n').find(s=>s.trim()) || 'Message';
const dateLabel = date => new Date(date).toLocaleDateString(undefined,{day:'numeric',month:'short',year:'numeric'});
const clock = date => new Date(date).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit',hour12:false});
const dayKey = date => new Date(date).toLocaleDateString();
const initials = name => {const parts=name.trim().split(/\s+/);return (parts[0]?.[0]||'?')+(parts.length>1?parts.at(-1)[0]:'');};
const tagText = tag => tag==='solution'?'proposed solution':tag;
const tagList = value => value.split(',').map(s=>s.trim()).filter(Boolean);
const formError = () => '<div id="dialog-error" class="error" role="alert"></div>';
const formFooter = (id,label='Save') => `<div class="dialog-footer"><button class="btn" data-action="close">Cancel</button><button class="btn primary" type="submit" form="${id}">${esc(label)}</button></div>`;

function auth(mode='login') {
  const create=mode!=='login';
  app.innerHTML=`<main class="auth"><form id="auth-form" data-mode="${mode}"><h1>${create?'Create account':'Sign in'}</h1>${S.invite?'<p>Use the email address on the invitation.</p>':''}<div class="error" id="auth-error" role="alert"></div><label for="name">Your name</label><input id="name" name="name" required maxlength="100" autocomplete="name" aria-describedby="name-help"><p class="help" id="name-help">Use the name other project members should see.</p><label for="email">Email address</label><input id="email" name="email" type="email" required autocomplete="username"><label for="password">Password</label><input id="password" name="password" type="password" required ${create?'minlength="10"':''} autocomplete="${create?'new-password':'current-password'}">${create?'<p class="help">At least 10 characters.</p>':''}${mode==='setup'&&S.setupTokenRequired?'<label for="setup-token">Initial setup key</label><input id="setup-token" name="setup_token" type="password" required autocomplete="off"><p class="help">Use the key provided by your server administrator.</p>':''}${mode==='setup'?'<label class="checkbox-label"><input type="checkbox" name="sample" checked>Include sample projects</label>':''}<button class="btn primary" type="submit">${mode==='register'?'Create account & join':create?'Create account':'Sign in'}</button>${S.invite?`<button type="button" class="text-btn" data-action="auth-switch" data-mode="${create?'login':'register'}">${create?'Sign in instead':'Create an account'}</button>`:''}</form></main>`;
}
function saveDraft() {
  const body=document.querySelector('#compose-body');
  if(body&&S.topic)S.drafts.set(`${S.project.id}:${S.topic.id}`,{body:body.value,tags:document.querySelector('#compose-tags').value,replyTo:S.replyTo||null});
}
async function enter(result, accept=true) {
  if(S.user?.id!==result.user.id){S.agentDrafts=new Map();clearTimeout(readTimer);pendingReads.clear();knownReads.clear();S.readObserver?.disconnect();}
  S.user=result.user;S.csrf=result.csrf;
  if(S.invite&&accept){
    const joined=await api('/invitations/accept','POST',{token:S.invite});S.invite=null;
    history.replaceState(null,'',`/#project=${joined.project_id}`);
  }
  S.projects=await api('/projects');
  const params=new URLSearchParams(location.hash.slice(1));
  const pid=S.projects.find(p=>p.id===Number(params.get('project')))?.id || S.projects[0]?.id;
  await go(pid,Number(params.get('topic'))||null,Number(params.get('message'))||null,false,['files','search','settings','agents','editor'].includes(params.get('view'))?params.get('view'):'dashboard');
}
async function go(pid,tid=null,anchor=null,push=true,view='dashboard') {
  saveDraft();window.MessageComposer?.destroy();S.inlineEdit=null;const version=++S.load;
  if(S.project?.id!==pid){S.fileFolder='';S.closedFolders=new Set();}
  clearTimeout(searchTimer);S.search=null;S.globalQuery='';S.projectQuery='';
  S.selected.clear();S.selectionAnchor=null;S.older=false;S.anchor=anchor;
  if(pid){
    const [project,topics]=await Promise.all([api(`/projects/${pid}`),api(`/projects/${pid}/topics`)]);
    if(version!==S.load)return;
    S.project=project;S.topics=topics;S.topic=topics.find(t=>t.id===tid)||null;
    S.projects=S.projects.map(p=>p.id===pid?{...p,...project}:p);
  }else{S.project=null;S.topics=[];S.topic=null;}
  S.view=S.topic?'topic':view;
  const params=new URLSearchParams();if(['files','search','settings','agents','editor'].includes(S.view))params.set('view',S.view);if(pid)params.set('project',pid);if(S.topic)params.set('topic',S.topic.id);if(anchor)params.set('message',anchor);
  history[push?'pushState':'replaceState'](null,'',params.size?'#'+params:'/');
  shell();
  if(!pid)return;
  if(S.topic)await loadTopic({anchor});else if(S.view==='settings')await settings();else if(S.view==='files')await loadFiles();else if(S.view==='editor')await loadManuscript();else if(S.view==='agents')await loadAgents();else if(S.view==='search'){S.search={scope:'project',query:'',projectId:S.project.id,results:[],hasMore:false,loading:false,version:S.load};renderSearch();document.querySelector('#project-search').focus();}else await loadOverview();
}
const recentFirst=(a,b)=>new Date(b.last_activity||b.created_at)-new Date(a.last_activity||a.created_at)||b.id-a.id;
const unreadBadge=count=>count?`<span class="unread-count" aria-hidden="true" title="${count} unread message${count===1?'':'s'}">${count}</span>`:'';
function sidebar() {
  const projects=[...S.projects].sort(recentFirst),topics=[...S.topics].sort(recentFirst);
  const projectButton=p=>`<button class="nav-button project-button ${p.id===S.project?.id?'active':''}" data-action="project" data-id="${p.id}" aria-label="${esc(p.title)}" aria-description="${p.unread_count||0} unread messages" ${p.id===S.project?.id?'aria-current="page"':''}><span class="nav-title">${esc(p.title)}</span>${unreadBadge(p.unread_count)}</button>`;
  const recent=projects.slice(0,6),more=projects.slice(6);
  return `<div class="sidebar-search"><input type="search" id="global-search" aria-label="Search everything" placeholder="Search everything" maxlength="200" value="${esc(S.globalQuery||'')}"></div><div class="project-select"><div class="sidebar-heading"><span class="sidebar-label">Projects</span><button class="text-btn" data-action="new-project" aria-label="New project">+</button></div><nav id="project-list" aria-label="Projects">${recent.map(projectButton).join('')}${more.length?`<button class="nav-button more-projects" data-action="more-projects" aria-label="${S.moreProjects?'Show fewer projects':'Show more projects'}" aria-expanded="${!!S.moreProjects}">⋯</button><div id="more-projects" ${S.moreProjects?'':'hidden'}>${more.map(projectButton).join('')}</div>`:''}</nav></div>${S.project?`<nav aria-label="Project navigation"><h2 class="project-sidebar-title">${esc(S.project.title)}</h2><div class="project-nav-icons"><button class="nav-button project-page-link ${S.view==='dashboard'?'active':''}" data-action="overview" aria-label="Project dashboard" title="Project dashboard">${ic('home')}</button><button class="nav-button project-page-link ${S.view==='files'?'active':''}" data-action="files" aria-label="Files" title="Files">${ic('folder')}</button><button class="nav-button project-page-link ${S.view==='editor'?'active':''}" data-action="editor" aria-label="Manuscript editor" title="Manuscript editor">${ic('quill')}</button><button class="nav-button project-page-link ${S.view==='search'?'active':''}" data-action="project-search" aria-label="Search this project" title="Search this project">${ic('search')}</button><button class="nav-button project-page-link ${S.view==='agents'?'active':''}" data-action="agents" aria-label="Project agents" title="Project agents">${ic('agent')}</button><button class="nav-button project-page-link ${S.view==='settings'?'active':''}" data-action="settings" aria-label="Project settings" title="Project settings">${ic('settings')}</button></div><section class="people-section" aria-label="People"><div class="topics-label"><span>People</span></div><ul class="people-list">${(S.project.people||[]).map(person=>`<li class="person-row">${ic('person')}<span>${esc(person.name)}</span></li>`).join('')}</ul></section><div class="topics-label"><span>Topics</span><button class="text-btn" data-action="new-topic" aria-label="New topic" title="New topic; drop messages here to move into a new topic">+</button></div><div id="topic-list">${topics.map(t=>`<button class="nav-button topic-button ${t.id===S.topic?.id?'active':''}" data-action="topic" data-id="${t.id}" aria-label="${esc(t.title)}" aria-description="${t.unread_count||0} unread messages"><span class="nav-title">${esc(t.title)}</span>${unreadBadge(t.unread_count)}</button>`).join('')}</div></nav>`:''}<div class="sidebar-bottom"><div class="account"><span>${esc(S.user.name)}</span><button class="text-btn" data-action="logout">Sign out</button></div></div>`;
}
function beginSearch(scope,input) {
  cancelInline();saveDraft();window.MessageComposer?.destroy();clearTimeout(searchTimer);
  S.globalQuery=scope==='all'?input.value:'';S.projectQuery=scope==='project'?input.value:'';
  const other=document.querySelector(scope==='all'?'#project-search':'#global-search');if(other)other.value='';
  const query=input.value.trim();
  if(!query&&scope==='all'){go(S.project?.id,S.topic?.id,null,false,S.view).catch(e=>toast(e.message,true));return;}
  S.search={scope,query,projectId:S.project?.id,results:[],hasMore:false,loading:!!query,version:++S.load};
  S.selected.clear();closeMessageMenus();renderSearch();
  if(!query)return;
  const version=S.search.version;searchTimer=setTimeout(()=>runSearch(version),300);
}
async function runSearch(version,more=false) {
  const search=S.search;if(!search||!search.query||search.version!==version)return;
  search.loading=true;search.error='';renderSearch();
  const params=new URLSearchParams({q:search.query,limit:50,offset:more?search.results.length:0});
  if(search.scope==='project'){params.set('project_id',search.projectId);params.set('content_only','true');}
  try{
    const data=await api('/search?'+params);
    if(S.search!==search||S.load!==version)return;
    search.results=more?[...search.results,...data.results]:data.results;search.hasMore=data.has_more;
  }catch(error){if(S.search===search)search.error=error.message;}
  finally{if(S.search===search){search.loading=false;renderSearch();}}
}
function renderSearch() {
  const search=S.search;if(!search)return;
  const projectSearch=search.scope==='project';
  document.querySelector('.rename-topic-icon')?.remove();document.querySelector('.page-header h1').classList.remove('topic-heading');
  document.querySelector('.page-header h1').textContent=projectSearch?'Search this project':'Search everything';
  document.querySelector('.header-actions').innerHTML='<button class="text-btn" data-action="close-search">Close search</button>';
  const labels={project:'Project',topic:'Topic',message:'Message',note:'Note',file:'File'};
  const resultHTML=(result,index)=>`<button class="search-result" data-action="search-result" data-index="${index}"><span class="search-result-context">${labels[result.kind]} · ${esc(result.project_title)}${result.topic_title?' › '+esc(result.topic_title):''}</span><span class="search-result-title">${esc(excerpt(result.title||result.snippet||labels[result.kind],120))}</span>${result.title&&result.snippet?`<span class="search-result-snippet">${esc(excerpt(result.snippet,200))}</span>`:''}</button>`;
  const group=kinds=>search.results.map((r,i)=>kinds.includes(r.kind)?resultHTML(r,i):'').join('');
  let view=document.querySelector('.search-view');
  if(!view||view.dataset.scope!==search.scope){
    document.querySelector('#page').innerHTML=`<section class="search-view" data-scope="${search.scope}">${projectSearch?`<input type="search" id="project-search" aria-label="Search this project" placeholder="Search messages and files" maxlength="200" value="${esc(S.projectQuery||'')}">`:''}<div id="search-output"></div></section>`;
  }
  const columns=`<div class="search-columns"><section aria-label="Messages"><h2>Messages</h2>${group(['message'])||'<p class="muted small">No matching messages.</p>'}</section><section aria-label="Files"><h2>Files</h2>${group(['file','note'])||'<p class="muted small">No matching files.</p>'}</section></div>`;
  document.querySelector('#search-output').innerHTML=`<p class="small muted">${esc(projectSearch?S.project.title:'All your projects')}</p>${search.error?`<p class="error" role="alert">${esc(search.error)}</p>`:''}<div class="search-results">${search.query?(projectSearch?columns:group(['project','topic'])+columns):'<div class="search-columns"><section aria-label="Messages"><h2>Messages</h2></section><section aria-label="Files"><h2>Files</h2></section></div>'}</div>${search.loading?'<p class="muted" role="status">Searching…</p>':!search.query?'<p class="muted" role="status">Search messages, file names, and text file contents.</p>':!search.error&&!search.results.length?'<p class="muted" role="status">No results.</p>':''}${search.hasMore?`<button class="btn" data-action="more-search" ${search.loading?'disabled':''}>Load more results</button>`:''}`;
  document.querySelectorAll('.search-result-title,.search-result-snippet').forEach(typeset);
}
async function openSearchResult(index) {
  const result=S.search?.results[index];if(!result)return;
  if(result.kind==='message')await go(result.project_id,result.topic_id,result.id);
  else if(result.kind==='topic')await go(result.project_id,result.id);
  else if(result.kind==='file'||result.kind==='note'){await go(result.project_id,null,null,true,'files');const path=result.file_path||S.fileData.legacy_notes?.[result.id];if(path)await viewFile(path);}
  else await go(result.project_id);
}
function shell() {
  app.innerHTML=`<div class="shell"><aside class="sidebar" id="sidebar">${sidebar()}</aside><main class="main"><header class="page-header"><button class="btn mobile-menu" data-action="menu" aria-label="Toggle project menu">☰</button><div class="page-title"><h1 class="${S.topic?'topic-heading':''}">${esc(S.topic?.title||(S.project?(S.view==='settings'?'Project settings':S.view==='files'?'Files':S.view==='agents'?'Project agents':'Project dashboard'):'Projects'))}</h1>${S.project&&S.topic?`<button class="text-btn file-icon-button rename-topic-icon" data-action="rename-topic" aria-label="Rename topic" title="Rename topic">${ic('edit')}</button>`:''}</div><div class="header-actions"></div></header><div id="page">${S.project?'<div class="loading">Loading…</div>':'<div class="empty">No projects.</div>'}</div></main></div>`;
  document.querySelectorAll('.page-header h1,#topic-list button').forEach(typeset);
}
async function loadOverview() {
  const pid=S.project.id, version=S.load;
  const data=await api(`/projects/${pid}/overview`);
  if(S.project.id!==pid||S.view!=='dashboard'||version!==S.load)return;
  S.overview=data;S.project=data.project;
  const questionRows=data.project.dashboard_questions.map(question=>`<section class="question-block" data-question-id="${question.id}"><div class="question-body markdown">${esc(question.body)}</div><div class="question-actions"><button class="text-btn file-icon-button" data-action="edit-question" data-id="${question.id}" aria-label="Edit main question" title="Edit main question">${ic('edit')}</button><button class="text-btn file-icon-button" data-action="delete-question" data-id="${question.id}" aria-label="Delete main question" title="Delete main question">${ic('trash')}</button></div></section>`).join('');
  document.querySelector('#page').innerHTML=`<div class="overview"><section class="overview-section"><div class="main-questions">${questionRows}</div><button class="text-btn file-icon-button" data-action="new-question" aria-label="Add main question" title="Add main question">${ic('plus')}</button></section><section class="overview-section recent">${data.recent_topics.map(group=>`<section class="recent-topic"><h3><button class="text-btn" data-action="topic" data-id="${group.topic_id}">${esc(group.title)}</button></h3>${messagesHTML(group.messages,true)}</section>`).join('')||'<p class="muted small">No messages.</p>'}</section></div>`;
  document.querySelectorAll('.question-block').forEach(el=>{const question=data.project.dashboard_questions.find(q=>q.id===Number(el.dataset.questionId));markdown(el.querySelector('.question-body'),question.body);});
  document.querySelectorAll('.question-body,.recent-topic h3').forEach(typeset);
  hydrateMessages();
}
const standardTags=['question','solution','technique','observation','experiment','note','promising','failed','roadblock','open end'];
const quickTagQueues=new Map(),menuCloseTimers=new WeakMap();
function messageTags(message) {
  return message.tags.map(tag=>`<span class="tag ${['question','promising','failed','roadblock'].includes(tag)?tag:''}">${esc(tagText(tag))}</span>`).join('');
}
function tagChoices(message) {
  const tags=[...new Set([...standardTags,...(S.project.available_tags||[]),...message.tags])];
  return tags.map(tag=>`<button type="button" class="tag-choice ${message.tags.includes(tag)?'applied':''}" data-action="quick-tag" data-id="${message.id}" data-tag="${esc(tag)}" aria-label="Apply tag ${esc(tagText(tag))}" aria-pressed="${message.tags.includes(tag)}" ${message.tags.includes(tag)?'disabled':''}>${esc(tagText(tag))}</button>`).join('');
}
function messageMenu(message,canEdit,compact=false) {
  const action=(name,label,icon)=>`<button type="button" class="message-action-icon" data-action="${name}" data-id="${message.id}" aria-label="${label}" title="${label}" ${name==='toggle-message-tags'?'aria-expanded="false"':''}>${ic(icon)}</button>`;
  return `<div class="message-menu" role="group" aria-label="Message actions for ${message.id}"><div><div class="message-actions">${action('reply','Reply','reply')}${action('toggle-message-tags','Tag message','tag')}${canEdit?action('edit','Edit message','edit')+action('archive','Archive message','archive'):''}${compact?action('jump','Open message '+message.id+' in topic','external'):''}</div><div class="quick-tags" hidden role="group" aria-label="Available tags"><div class="tag-options">${tagChoices(message)}</div><button type="button" class="text-btn" data-action="tags" data-id="${message.id}">Edit tags</button></div></div></div>`;
}
function hideTagChoices(menu){menu.querySelector('.quick-tags').hidden=true;menu.querySelector('[data-action="toggle-message-tags"]').setAttribute('aria-expanded','false');}
function toggleMessageTags(el){
  const menu=el.closest('.message-menu'),panel=menu.querySelector('.quick-tags'),show=panel.hidden;
  openMessageMenu(el.closest('.message'));panel.hidden=!show;el.setAttribute('aria-expanded',String(show));
  if(show){const scroller=el.closest('.topic-scroll'),bar=menu.querySelector('.message-actions').getBoundingClientRect();const bounds=scroller?.getBoundingClientRect()||{top:0,bottom:innerHeight};const below=bounds.bottom-bar.bottom-8,above=bar.top-bounds.top-8;const flip=below<Math.min(panel.scrollHeight,260)&&above>below;panel.classList.toggle('tags-above',flip);panel.style.maxHeight=Math.max(60,Math.min(320,flip?above:below))+'px';}
}
function quickTag(el) {
  const id=Number(el.dataset.id),pid=S.project.id,tag=el.dataset.tag;
  const previous=quickTagQueues.get(id)||Promise.resolve();
  const update=previous.catch(()=>{}).then(async()=>{
    const message=await api(`/projects/${pid}/messages/${id}`);
    if(message.tags.includes(tag))return;
    const updated=await api(`/projects/${pid}/messages/${id}/tags`,'PATCH',{tags:[...message.tags,tag],revision:message.revision});
    if(S.project?.id!==pid)return;
    S.messageMap.set(id,updated);S.messages=S.messages.map(m=>m.id===id?updated:m);
    S.project.available_tags=[...new Set([...(S.project.available_tags||[]),...updated.tags])];
    document.querySelectorAll(`.message[data-id="${id}"]`).forEach(row=>{
      row.querySelector('.message-tags').innerHTML=messageTags(updated);
      row.querySelector('.tag-options').innerHTML=tagChoices(updated);
      if(row.matches(':hover'))openMessageMenu(row);
    });
  });
  quickTagQueues.set(id,update);
  return update.finally(()=>{if(quickTagQueues.get(id)===update)quickTagQueues.delete(id);});
}
function messagesHTML(messages,compact=false) {
  let previous=null;
  return messages.map(message=>{
    S.messageMap.set(message.id,message);
    const newDay=!previous||dayKey(previous.created_at)!==dayKey(message.created_at);
    const grouped=!newDay && previous.author_id===message.author_id && previous.agent_id===message.agent_id;
    previous=message;
    const canEdit=S.project.is_owner||(message.author_id===S.user.id&&!message.agent_id);
    return `${newDay?`<div class="message-date"><time datetime="${esc(message.created_at)}">${esc(dateLabel(message.created_at))}</time></div>`:''}<article class="message ${grouped?'grouped':''} ${S.selected.has(message.id)?'selected':''}" id="message-${message.id}" data-id="${message.id}" ${compact?'':'draggable="true" tabindex="0" aria-label="Message by '+esc(message.author.name)+'; Enter for actions, Shift-click to select, or drag to a topic"'}><div class="message-meta">${grouped?'':`<span class="avatar ${message.agent_id?'agent-avatar':''}" title="${esc(message.author.name)}${message.agent_id?' (agent)':''}" aria-label="${esc(message.author.name)}${message.agent_id?' (agent)':''}">${esc(initials(message.author.name).toUpperCase())}</span><time datetime="${esc(message.created_at)}" title="${esc(new Date(message.created_at).toLocaleString())}">${esc(clock(message.created_at))}</time>`}${compact?'':`<div class="message-selection"><input type="checkbox" aria-label="Select message ${message.id}" data-select="${message.id}" ${S.selected.has(message.id)?'checked':''}></div>`}</div><div class="message-content"><div class="message-tags">${messageTags(message)}</div>${message.reply_to?replyPreview(message.reply_to):''}${message.title?`<div class="message-title">${esc(message.title)}</div>`:''}<div class="message-body markdown" data-message="${message.id}" ${compact?'data-compact="true"':''}></div></div>${messageMenu(message,canEdit,compact)}</article>`;
  }).join('');
}
function replyPreview(message) {
  const author=message.author.name;
  return `<button type="button" class="reply-preview" data-action="jump" data-id="${message.id}" ${message.archived?'disabled':''} aria-label="Reply to ${esc(author)}"><strong>↪ ${esc(author)}</strong><span>${message.archived?'Archived message':esc(excerpt(short(message),120))}</span></button>`;
}
function renderReplyComposer() {
  const banner=document.querySelector('#reply-compose');if(!banner)return;
  banner.hidden=!S.replyTo;
  banner.innerHTML=S.replyTo?`<div><span class="small muted">Replying to</span>${replyPreview(S.replyTo)}</div><button class="btn square" type="button" data-action="cancel-reply" aria-label="Cancel reply">${ic('close')}</button>`:'';
  banner.querySelectorAll('.reply-preview').forEach(typeset);
}
async function replyTo(id) {
  const version=S.load,message=await freshMessage(id);
  if(S.load!==version||!S.topic)return;
  S.replyTo=message;renderReplyComposer();saveDraft();
  document.querySelector('#compose-form').dataset.key='';
  document.querySelector('#compose-body').focus();
}
function hydrateMessages() {
  document.querySelectorAll('.message-body[data-message]').forEach(el=>{
    const message=S.messageMap.get(Number(el.dataset.message));
    markdown(el,message.body);
  });
  document.querySelectorAll('.message-title,.reply-preview').forEach(typeset);
  observeReads();
}
function observeReads() {
  S.readObserver?.disconnect();
  if(!S.user||!S.topic||S.search||document.hidden)return;
  const pid=S.project.id,tid=S.topic.id,version=S.load;
  S.readObserver=new IntersectionObserver(entries=>{
    if(document.hidden||S.load!==version||S.topic?.id!==tid)return;
    for(const entry of entries){
      if(!entry.isIntersecting)continue;
      const id=Number(entry.target.dataset.id),message=S.messageMap.get(id);
      if(knownReads.has(id)||(message?.author_id===S.user.id&&!message.agent_id))continue;
      if(!pendingReads.has(pid))pendingReads.set(pid,new Set());
      pendingReads.get(pid).add(id);S.readObserver.unobserve(entry.target);
    }
    if(pendingReads.size){clearTimeout(readTimer);readTimer=setTimeout(flushReads,200);}
  });
  document.querySelectorAll('#messages .message').forEach(row=>S.readObserver.observe(row));
}
async function flushReads() {
  if(S.reading||!S.user)return;
  S.reading=true;const userId=S.user.id;
  try{
    for(const [pid,ids] of pendingReads){
      if(S.user?.id!==userId)return;
      const messageIds=[...ids].slice(0,200),version=S.load;
      if(!messageIds.length){pendingReads.delete(pid);continue;}
      try{
        const data=await api(`/projects/${pid}/read`,'POST',{message_ids:messageIds});
        if(S.user?.id!==userId)return;
        messageIds.forEach(id=>{knownReads.add(id);ids.delete(id);});
        if(!ids.size)pendingReads.delete(pid);
        S.projects=S.projects.map(p=>p.id===pid?{...p,...data.project}:p);
        if(S.project?.id===pid&&S.load===version&&!S.search){
          S.project={...S.project,...data.project};S.topics=data.topics;
          if(!S.drag&&!S.movingDrop&&!document.activeElement?.matches('.sidebar-search input'))document.querySelector('#sidebar').innerHTML=sidebar();
        }
      }catch{ /* Keep pending receipts for the next poll or visible-message change. */ }
    }
  }finally{S.reading=false;}
}
document.addEventListener('visibilitychange',()=>{if(!document.hidden)observeReads();});
async function loadTopic({before=null,anchor=null,quiet=false}={}) {
  const pid=S.project.id,tid=S.topic.id,version=S.load;
  const query=new URLSearchParams({limit:60});if(before)query.set('before',before);if(anchor)query.set('anchor',anchor);
  const data=await api(`/projects/${pid}/topics/${tid}/messages?${query}`);
  if(S.project.id!==pid||S.topic?.id!==tid||version!==S.load)return;
  S.topic=data.topic;S.before=data.next_before;
  S.messages=before?[...data.messages,...S.messages]:data.messages;
  if(before)S.older=true;
  if(quiet){
    const scroller=document.querySelector('.topic-scroll');
    const nearBottom=scroller.scrollTop+scroller.clientHeight>=scroller.scrollHeight-100;
    const scrollTop=scroller.scrollTop;
    document.querySelector('#messages').innerHTML=messagesHTML(S.messages);
    hydrateMessages();selectionBar();
    document.querySelector('#older-control').innerHTML=S.before?'<button class="text-btn" data-action="older">Load older messages</button>':'';
    document.querySelector('#new-activity').hidden=true;
    scroller.scrollTop=nearBottom?scroller.scrollHeight:scrollTop;
    return;
  }
  const previousScroller=document.querySelector('.topic-scroll');
  const previousTop=previousScroller?.scrollTop||0,previousHeight=previousScroller?.scrollHeight||0;
  const wasAtBottom=previousScroller&&previousTop+previousScroller.clientHeight>=previousHeight-100;
  const draft=S.drafts.get(`${pid}:${tid}`)||{body:'',tags:''};
  S.replyTo=draft.replyTo||null;
  document.querySelector('#page').innerHTML=`<div class="topic-view"><div class="topic-scroll"><div class="topic-activity"><button class="text-btn" id="new-activity" data-action="refresh" hidden>New activity</button></div><div id="selection-bar" class="selection-bar" hidden></div><div id="older-control">${S.before?'<button class="text-btn" data-action="older">Load older messages</button>':''}</div><div id="messages" class="messages">${messagesHTML(S.messages)||'<p class="muted small empty">No messages.</p>'}</div></div><div class="composer-dock"><form id="compose-form" class="composer"><div id="reply-compose" class="reply-compose" hidden></div><textarea id="compose-body" name="body" aria-label="Message" placeholder="Message" required rows="3" maxlength="50000">${esc(draft.body)}</textarea><div class="compose-bottom"><button type="button" class="text-btn" data-action="composer-tags">Tags</button><input id="compose-tags" name="tags" aria-label="Message tags" placeholder="question, open end, technique…" value="${esc(draft.tags)}" ${draft.tags?'':'hidden'}><span class="spacer"></span><button class="btn primary" type="submit" title="Ctrl+Enter">Send</button></div><div class="error" id="compose-error" role="alert"></div></form></div></div>`;
  window.MessageComposer?.mount(document.querySelector('#compose-body'));
  hydrateMessages();selectionBar();renderReplyComposer();
  const scroller=document.querySelector('.topic-scroll');
  scroller.scrollTop=before?previousTop+scroller.scrollHeight-previousHeight:wasAtBottom?scroller.scrollHeight:previousTop;
  if(anchor){const el=document.querySelector(`#message-${anchor}`);if(el){el.classList.add('highlight');el.scrollIntoView({block:'center'});}}
}
function selectionBar() {
  const bar=document.querySelector('#selection-bar');if(!bar)return;
  bar.hidden=!S.selected.size;
  document.querySelector('#messages').classList.toggle('move-mode',!!S.selected.size);
  bar.innerHTML=`<span>${S.selected.size} selected</span><button class="btn" data-action="move-selected">Move selected messages</button><button class="text-btn" data-action="clear-selection">Clear selection</button>`;
  document.querySelectorAll('#messages .message').forEach(el=>{
    const yes=S.selected.has(Number(el.dataset.id));el.classList.toggle('selected',yes);el.querySelector('[data-select]').checked=yes;
  });
}
function selectMessage(id,range=false) {
  const ids=S.messages.map(m=>m.id);
  if(range&&S.selectionAnchor!==null){
    const a=ids.indexOf(S.selectionAnchor),b=ids.indexOf(id);
    if(a>=0&&b>=0)for(const selected of ids.slice(Math.min(a,b),Math.max(a,b)+1))S.selected.add(selected);
  }else{
    if(S.selected.has(id))S.selected.delete(id);else S.selected.add(id);
    S.selectionAnchor=id;
  }
  selectionBar();
}
function closeMessageMenus(except=null) {
  document.querySelectorAll('.message-menu[open]').forEach(menu=>{if(menu!==except){clearTimeout(menuCloseTimers.get(menu));menu.classList.remove('menu-closing');menu.removeAttribute('open');hideTagChoices(menu);}});
}
function openMessageMenu(message) {
  if(S.inlineEdit)return;
  const menu=message.querySelector('.message-menu');if(!menu)return;
  closeMessageMenus(menu);clearTimeout(menuCloseTimers.get(menu));menu.classList.remove('menu-closing');menu.setAttribute('open','');
}
document.addEventListener('pointerover',event=>{
  if(event.pointerType==='touch'||S.inlineEdit||S.drag||S.selected.size||!matchMedia('(hover:hover)').matches)return;
  const row=event.target.closest('.message');if(row&&!row.contains(event.relatedTarget))openMessageMenu(row);
});
document.addEventListener('pointermove',event=>{
  if(event.pointerType==='touch'||modal.open||S.inlineEdit||S.drag||S.selected.size||!matchMedia('(hover:hover)').matches)return;
  const row=event.target.closest('.message');if(row&&!row.querySelector('.message-menu')?.hasAttribute('open'))openMessageMenu(row);
});
document.addEventListener('pointerout',event=>{
  const row=event.target.closest('.message');if(!row||row.contains(event.relatedTarget))return;
  const menu=row.querySelector('.message-menu');if(!menu?.hasAttribute('open'))return;
  menu.classList.add('menu-closing');
  menuCloseTimers.set(menu,setTimeout(()=>{menu.removeAttribute('open');menu.classList.remove('menu-closing');hideTagChoices(menu);},200));
});
async function freshMessage(id) {
  const message=await api(ctx(`/messages/${id}`));S.messageMap.set(message.id,message);return message;
}
async function jump(id) {
  const message=await freshMessage(id);await go(S.project.id,message.topic_id,id);
}
async function reloadProject() {
  S.projects=await api('/projects');
  S.project=await api(ctx(''));S.topics=await api(ctx('/topics'));
  document.querySelector('#sidebar').innerHTML=sidebar();
  if(S.topic)await loadTopic({anchor:S.anchor});else if(S.view==='settings')await settings();else if(S.view==='files')await loadFiles();else if(S.view==='editor')await loadManuscript();else if(S.view==='agents')await loadAgents();else if(S.view==='search'){S.search={scope:'project',query:'',projectId:S.project.id,results:[],hasMore:false,loading:false,version:S.load};renderSearch();document.querySelector('#project-search').focus();}else await loadOverview();
}
async function topicForm(rename=false) {
  if(rename)return inlineTopic();
  if(rename){const pid=S.project.id,tid=S.topic.id;const topics=await api(`/projects/${pid}/topics`);if(S.project?.id!==pid||S.topic?.id!==tid)return;S.topic=topics.find(t=>t.id===tid);}
  dialog(rename?'Rename topic':'New topic',`<form id="topic-form" class="dialog-body" data-rename="${rename}">${formError()}<label for="topic-title">Topic name</label><input id="topic-title" name="title" required maxlength="160" value="${rename?esc(S.topic.title):''}"></form>`,formFooter('topic-form',rename?'Save':'Create topic'));
}
function inlineButtons(label='Save') {
  return `<div class="inline-edit-actions"><button class="btn primary" type="submit">${label}</button><button class="text-btn" type="button" data-action="cancel-inline">Cancel</button></div><div class="error inline-error" role="alert"></div>`;
}
function cancelInline() {
  const edit=S.inlineEdit;if(!edit)return;S.inlineEdit=null;
  if(edit.host.isConnected){if(edit.isNew)edit.host.remove();else edit.host.innerHTML=edit.original;}
  if(edit.row)edit.row.draggable=edit.wasDraggable;
}
function startInline(host,kind,fields,values={},isNew=false) {
  cancelInline();closeMessageMenus();saveDraft();
  const row=host.closest('.message');
  S.inlineEdit={host,kind,...values,isNew,pid:S.project.id,original:host.innerHTML,row,wasDraggable:row?.draggable};
  if(row)row.draggable=false;
  host.innerHTML=`<form id="inline-${kind}-form" class="inline-editor ${kind==='topic'?'inline-title':''}">${fields}${inlineButtons(isNew?'Add question':'Save')}</form>`;
  const input=host.querySelector('input,textarea');input.focus();if(kind==='topic')input.select();
}
async function inlineTopic() {
  const pid=S.project.id,tid=S.topic.id,version=S.load;
  const topics=await api(`/projects/${pid}/topics`);if(S.load!==version||S.topic?.id!==tid)return;
  const topic=topics.find(t=>t.id===tid);
  startInline(document.querySelector('.page-title'),'topic',`<input name="title" aria-label="Topic name" required maxlength="160" value="${esc(topic.title)}">`,{topic});
}
async function tagsForm(id) {
  const version=S.load,message=await freshMessage(id);if(S.load!==version)return;
  const host=document.querySelector(`.message[data-id="${id}"] .message-content`);
  startInline(host,'tags',`<label for="tags-input">Tags</label><input id="tags-input" name="tags" value="${esc(message.tags.map(tagText).join(', '))}" placeholder="Comma-separated tags">`,{message});
}
async function editForm(id) {
  const version=S.load,message=await freshMessage(id);if(S.load!==version)return;
  const host=document.querySelector(`.message[data-id="${id}"] .message-content`);
  startInline(host,'message',`${message.title?`<label for="edit-title">Title</label><input id="edit-title" name="title" maxlength="200" value="${esc(message.title)}">`:''}<label for="edit-body">Message</label><textarea id="edit-body" name="body" required rows="6" maxlength="50000">${esc(message.body)}</textarea><label for="edit-tags">Tags</label><input id="edit-tags" name="tags" value="${esc(message.tags.map(tagText).join(', '))}">`,{message});
}
async function saveInline(form,f) {
  const edit=S.inlineEdit;if(!edit||edit.host.querySelector('form')!==form)return;
  saveDraft();
  if(edit.kind==='topic'){
    await api(`/projects/${edit.pid}/topics/${edit.topic.id}`,'PATCH',{title:f.get('title'),revision:edit.topic.revision});
  }else if(edit.kind==='question'){
    await api(`/projects/${edit.pid}/dashboard-questions${edit.question?'/'+edit.question.id:''}`,edit.question?'PATCH':'POST',{body:f.get('body'),...(edit.question?{revision:edit.question.revision}:{})});
  }else{
    const m=edit.message;
    await api(`/projects/${edit.pid}/messages/${m.id}`+(edit.kind==='tags'?'/tags':''),'PATCH',edit.kind==='tags'?{tags:tagList(f.get('tags')),revision:m.revision}:{body:f.get('body'),title:f.get('title')??m.title,tags:tagList(f.get('tags')),model:m.model,run_id:m.run_id,revision:m.revision,archived:m.archived});
  }
  if(S.inlineEdit!==edit)return;
  cancelInline();
  if(edit.kind==='topic')await go(edit.pid,edit.topic.id,null,false);else await reloadProject();
}
async function moveForm(id=null,draggedMessages=null) {
  const messages=draggedMessages||(id?[await freshMessage(id)]:S.messages.filter(m=>S.selected.has(m.id)));
  if(!messages.length)return;
  S.moving=messages;S.batchMove=!id;
  const options=S.topics.filter(t=>t.id!==messages[0].topic_id);
  dialog('Move messages',`<form id="move-form" class="dialog-body">${formError()}<label for="move-target">Destination topic</label><select id="move-target" name="target"><option value="new">New topic…</option>${options.map(t=>`<option value="${t.id}">${esc(t.title)}</option>`).join('')}</select><div id="new-topic-field"><label for="move-new-title">New topic name</label><input id="move-new-title" name="title" maxlength="160" required></div>${id?'<label for="move-scope">Messages to move</label><select id="move-scope" name="mode"><option value="single">This message</option><option value="following">This message and all later messages</option><option value="all">All messages in this topic</option></select>':`<p class="help">Move the ${messages.length} selected message${messages.length===1?'':'s'}.</p>`}</form>`,formFooter('move-form','Move'));
}
function questionForm(id=null) {
  cancelInline();
  const question=id?S.project.dashboard_questions.find(q=>q.id===id):null;
  let host=id?document.querySelector(`.question-block[data-question-id="${id}"]`):null;
  if(!host){host=document.createElement('section');host.className='question-block';document.querySelector('.main-questions').append(host);}
  startInline(host,'question',`<label for="question-body">Question</label><textarea id="question-body" name="body" required rows="5" maxlength="50000">${esc(question?.body||'')}</textarea>`,{question},!id);
}
function deleteQuestionForm(id) {
  S.editQuestion=S.project.dashboard_questions.find(q=>q.id===id);
  dialog('Delete main question',`<form id="delete-question-form" class="dialog-body">${formError()}<p>Delete this main question?</p></form>`,formFooter('delete-question-form','Delete'));
}
function invitationLink(email,token,id='invite-link') {
  return `<div class="secret"><p>Single-use invitation for ${esc(email)}. Expires in seven days.</p><input id="${id}" aria-label="Invitation link for ${esc(email)}" readonly value="${esc(location.origin+'/#invite='+token)}"><button class="btn" data-action="copy" data-target="${id}" type="button">Copy invitation</button></div>`;
}
async function settings() {
  const pid=S.project.id,version=S.load;
  const [members,keys]=await Promise.all([api(ctx('/members')),api(ctx('/keys'))]);
  if(S.project?.id!==pid||S.load!==version||S.view!=='settings')return;
  S.project.people=members.map(({id,name,is_owner})=>({id,name,is_owner}));
  const peopleList=document.querySelector('.people-list');if(peopleList)peopleList.innerHTML=S.project.people.map(person=>`<li class="person-row">${ic('person')}<span>${esc(person.name)}</span></li>`).join('');
  document.querySelector('#page').innerHTML=`<div class="settings-page"><div id="settings-error" class="error" role="alert"></div><section class="settings-section"><h3>Collaborators</h3><p class="help">Private project. These people can access all discussions and files in this project. Other projects require separate invitations.</p>${members.map(m=>`<div class="setting-row"><span>${esc(m.name)} <span class="muted small">${esc(m.email)}</span></span>${m.is_owner?'<span class="muted small">Owner</span>':S.project.is_owner?`<button class="text-btn" data-action="remove-member" data-id="${m.id}">Remove</button>`:''}</div>`).join('')}${S.project.is_owner?'<form id="invite-form" class="inline-form"><input type="email" name="email" aria-label="Collaborator email" required placeholder="Email address"><button class="btn" type="submit">Create invitation</button></form><div id="invite-result"></div>':''}</section><section class="settings-section"><h3>Agent keys</h3>${keys.map(k=>`<div class="setting-row"><span>${esc(k.name)} <span class="muted small">${esc(k.owner)} · ${k.scope==='write'?'Read and write':'Read only'}</span></span>${k.revoked?'<span class="muted small">Revoked</span>':`<button class="text-btn" data-action="revoke-key" data-id="${k.id}">Revoke</button>`}</div>`).join('')}<form id="key-form" class="inline-form"><input name="name" aria-label="Agent name" placeholder="Agent name" required maxlength="100"><select name="scope" aria-label="Agent scope"><option value="write">Read and write</option><option value="read">Read only</option></select><button class="btn" type="submit">Create key</button></form><div id="key-result"></div><a class="text-btn" href="/docs" target="_blank" rel="noopener">API reference</a></section><section class="settings-section"><h3>Related projects</h3><form id="links-form">${S.projects.filter(p=>p.id!==S.project.id).map(p=>`<label class="checkbox-label"><input name="project" type="checkbox" value="${p.id}" ${S.project.linked_projects.some(r=>r.id===p.id)?'checked':''}>${esc(p.title)}</label>`).join('')||'<p class="muted small">No other accessible projects.</p>'}<button class="btn" type="submit">Save project links</button></form></section></div>`;
}
const actions={
  close:()=>modal.close(),
  'cancel-inline':cancelInline,
  menu:()=>document.querySelector('.shell').classList.toggle('nav-open'),
  'project-search':()=>{document.querySelector('.shell')?.classList.remove('nav-open');return go(S.project.id,null,null,true,'search');},
  overview:()=>go(S.project.id),
  files:()=>go(S.project.id,null,null,true,'files'),
  editor:()=>go(S.project.id,null,null,true,'editor'),
  'file-open':el=>viewFile(el.dataset.path),
  'file-new':()=>newFileForm(),
  'file-edit':()=>newFileForm(true),
  'file-upload':()=>uploadFileForm(),
  'folder-upload':()=>uploadFileForm(true),
  'folder-new':newFolderForm,
  'file-move':el=>fileMoveForm(el.dataset.path),
  'file-delete':el=>fileDeleteForm(el.dataset.path),
  'git-remote':gitRemoteDialog,
  'file-commit':fileCommitForm,
  'file-history-more':()=>{S.fileHistoryLimit=Math.min(500,(S.fileHistoryLimit||50)+50);return loadFiles();},
  'close-search':()=>go(S.project?.id,S.topic?.id,null,false,S.view==='search'?'dashboard':S.view),
  'more-search':()=>runSearch(S.search.version,true),
  'search-result':el=>openSearchResult(Number(el.dataset.index)),
  project:el=>go(Number(el.dataset.id)),
  'more-projects':()=>{S.moreProjects=!S.moreProjects;document.querySelector('#sidebar').innerHTML=sidebar();},
  topic:el=>{modal.close();return go(S.project.id,Number(el.dataset.id));},
  jump:el=>{modal.close();return jump(Number(el.dataset.id));},
  'auth-switch':el=>auth(el.dataset.mode),
  logout:async()=>{window.activeManuscript?.destroy();window.activeManuscript=null;await api('/auth/logout','POST');S.user=null;S.csrf='';S.agentDrafts=new Map();location.replace('/');},
  'new-project':()=>dialog('New project',`<form id="project-form" class="dialog-body">${formError()}<label for="project-title">Project name</label><input id="project-title" name="title" required maxlength="160"><p class="help">Private project. Only you and collaborators who accept an invitation can access its discussions and files.</p><label for="project-collaborators">Invite collaborators</label><textarea id="project-collaborators" name="collaborators" rows="3" maxlength="12800" placeholder="alice@example.org, bob@example.org" aria-describedby="collaborators-help"></textarea><p class="help" id="collaborators-help">Separate email addresses with commas or new lines. You can invite people later. After creating the project, copy and share their invitation links.</p></form>`,formFooter('project-form','Create project')),
  'new-topic':()=>topicForm(),
  'rename-topic':()=>topicForm(true),
  refresh:async()=>{saveDraft();S.anchor=null;S.older=false;await reloadProject();},
  older:()=>{saveDraft();return loadTopic({before:S.before});},
  'composer-tags':()=>{const el=document.querySelector('#compose-tags');el.hidden=!el.hidden;if(!el.hidden)el.focus();},
  'quick-tag':quickTag,
  'toggle-message-tags':toggleMessageTags,
  tags:el=>tagsForm(Number(el.dataset.id)),
  edit:el=>editForm(Number(el.dataset.id)),
  reply:async el=>{const id=Number(el.dataset.id);if(!S.topic){const message=await freshMessage(id);await go(S.project.id,message.topic_id,id);}await replyTo(id);},
  'cancel-reply':()=>{S.replyTo=null;renderReplyComposer();saveDraft();document.querySelector('#compose-form').dataset.key='';},
  move:el=>moveForm(Number(el.dataset.id)),
  'move-selected':()=>moveForm(),
  'clear-selection':()=>{S.selected.clear();S.selectionAnchor=null;selectionBar();},
  'new-question':()=>questionForm(),
  'edit-question':el=>questionForm(Number(el.dataset.id)),
  'delete-question':el=>deleteQuestionForm(Number(el.dataset.id)),
  'question-up':el=>{const row=el.closest('.question-option');if(row.previousElementSibling)row.parentNode.insertBefore(row,row.previousElementSibling);},
  'question-down':el=>{const row=el.closest('.question-option');if(row.nextElementSibling)row.parentNode.insertBefore(row.nextElementSibling,row);},
  agents:()=>go(S.project.id,null,null,true,'agents'),
  settings:()=>go(S.project.id,null,null,true,'settings'),
  'project-info':()=>{
    const related=S.project.linked_projects.map(p=>`<button class="text-btn linked-project" data-action="linked-project" data-id="${p.id}">${esc(p.title)}</button>`).join('');
    dialog('Project details',`<div class="dialog-body">${S.project.objective?'<h3>Objective</h3><div class="markdown" id="project-objective-view"></div>':''}${S.project.description?'<h3>Context</h3><div class="markdown" id="project-context-view"></div>':''}${related?'<h3>Related projects</h3>'+related:''}</div>`);
    if(S.project.objective)markdown(document.querySelector('#project-objective-view'),S.project.objective);
    if(S.project.description)markdown(document.querySelector('#project-context-view'),S.project.description);
  },
  'linked-project':el=>{modal.close();return go(Number(el.dataset.id));},
  'preview-edit':()=>{const el=document.querySelector('#edit-preview');el.hidden=!el.hidden;if(!el.hidden)markdown(el,document.querySelector('#edit-body').value);},
  archive:async el=>{const m=await freshMessage(Number(el.dataset.id));await api(ctx(`/messages/${m.id}`),'PATCH',{body:m.body,title:m.title,tags:m.tags,model:m.model,run_id:m.run_id,revision:m.revision,archived:true});await reloadProject();toast('Message archived.');},
  'remove-member':async el=>{await api(ctx(`/members/${el.dataset.id}`),'DELETE');await settings();},
  'revoke-key':async el=>{await api(ctx(`/keys/${el.dataset.id}`),'DELETE');await settings();},
  copy:async el=>{const input=document.querySelector('#'+el.dataset.target);try{await navigator.clipboard.writeText(input.value);toast('Copied.');}catch{input.select();}},
};
document.addEventListener('mousedown',event=>{if(event.shiftKey&&event.target.closest('#messages .message')&&!event.target.closest('button,a,summary,textarea'))event.preventDefault();});
document.addEventListener('click',async event=>{
  const clickedMessage=event.target.closest('#messages .message');
  if(S.selected.size&&!event.shiftKey&&!event.target.closest('#selection-bar,#modal,[data-select]')
      &&(!clickedMessage||!S.selected.has(Number(clickedMessage.dataset.id)))){
    S.selected.clear();S.selectionAnchor=null;selectionBar();
  }
  const select=event.target.closest('[data-select]');
  if(select){
    if(event.shiftKey||S.selected.size)selectMessage(Number(select.dataset.select),event.shiftKey);
    else select.checked=false;
    return;
  }
  const el=event.target.closest('[data-action]');
  if(el){
    if(el.disabled)return;
    if(!['quick-tag','toggle-message-tags'].includes(el.dataset.action))closeMessageMenus();
    try{await actions[el.dataset.action]?.(el);}catch(error){const err=modal.open?document.querySelector('#dialog-error'):document.querySelector('#settings-error');if(err)err.textContent=error.message;else toast(error.message,true);}return;
  }
  const message=event.target.closest('#messages .message');
  const summary=event.target.closest('.message-menu summary');
  if(summary){event.preventDefault();openMessageMenu(summary.closest('.message'));return;}
  if(message&&!event.target.closest('a,button,summary,input,textarea,details,.inline-editor')&&!window.getSelection().toString()){
    const id=Number(message.dataset.id);
    if(event.shiftKey){closeMessageMenus();selectMessage(id,true);}
    else {if(!S.selected.size)S.selectionAnchor=id;openMessageMenu(message);}
  }else if(!event.target.closest('.message-menu'))closeMessageMenus();
});
function clearDragTargets() {
  document.querySelectorAll('.drop-target').forEach(el=>el.classList.remove('drop-target'));
}
function dragTarget(event) {
  if(!S.drag||S.movingDrop||S.drag.project!==S.project?.id||S.drag.topic!==S.topic?.id)return null;
  const target=event.target.closest('#topic-list [data-action="topic"],.topics-label [data-action="new-topic"]');
  return target&&Number(target.dataset.id)!==S.drag.topic?target:null;
}
document.addEventListener('dragstart',event=>{
  const row=event.target.closest('#messages .message');
  if(!row||event.target.closest('a,button,input,summary,details')){event.preventDefault();return;}
  const id=Number(row.dataset.id),ids=S.selected.has(id)?S.selected:new Set([id]);
  S.drag={project:S.project.id,topic:S.topic.id,messages:S.messages.filter(m=>ids.has(m.id)).map(m=>({id:m.id,revision:m.revision}))};
  event.dataTransfer.effectAllowed='move';
  event.dataTransfer.setData('text/plain',`${S.drag.messages.length} message${S.drag.messages.length===1?'':'s'}`);
  closeMessageMenus();row.classList.add('dragging');document.querySelector('.shell').classList.add('drag-active');
});
document.addEventListener('dragover',event=>{
  const target=dragTarget(event);clearDragTargets();
  if(target){event.preventDefault();event.dataTransfer.dropEffect='move';target.classList.add('drop-target');}
});
document.addEventListener('dragleave',event=>{
  const target=event.target.closest('.drop-target');if(target&&!target.contains(event.relatedTarget))target.classList.remove('drop-target');
});
document.addEventListener('dragend',()=>{
  S.drag=null;clearDragTargets();document.querySelector('.shell')?.classList.remove('drag-active');
  document.querySelectorAll('.dragging').forEach(el=>el.classList.remove('dragging'));
});
document.addEventListener('drop',async event=>{
  const target=dragTarget(event);if(!target)return;
  event.preventDefault();const drag=S.drag;S.drag=null;clearDragTargets();S.movingDrop=true;
  try{
    if(target.dataset.action==='new-topic'){
      await moveForm(null,drag.messages.map(m=>({...m,topic_id:drag.topic})));
    }else{
      const response=await api(`/projects/${drag.project}/topics/${drag.topic}/move-messages`,'POST',{target_topic_id:Number(target.dataset.id),messages:drag.messages});
      await go(drag.project,response.topic_id);
    }
  }catch(error){toast(error.message,true);}
  finally{S.movingDrop=false;document.querySelector('.shell')?.classList.remove('drag-active');document.querySelectorAll('.dragging').forEach(el=>el.classList.remove('dragging'));}
});
let searchTimer;
document.addEventListener('input',event=>{
  if(['compose-body','compose-tags'].includes(event.target.id)){saveDraft();document.querySelector('#compose-form').dataset.key='';}
  if(event.target.id==='global-search')beginSearch('all',event.target);
  if(event.target.id==='project-search')beginSearch('project',event.target);
});
document.addEventListener('change',async event=>{
  try{
    if(event.target.id==='file-destination')S.fileFolder=event.target.value;
    if(event.target.id==='move-target'){const yes=event.target.value==='new';document.querySelector('#new-topic-field').hidden=!yes;document.querySelector('#move-new-title').required=yes;}
  }catch(error){toast(error.message,true);}
});
document.addEventListener('keydown',event=>{
  const inline=event.target.closest('.inline-editor');
  if(inline&&event.key==='Escape'){event.preventDefault();cancelInline();return;}
  if(inline&&event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();inline.requestSubmit();return;}
  if(['global-search','project-search'].includes(event.target.id)&&event.key==='Enter'){event.preventDefault();clearTimeout(searchTimer);document.querySelector('.shell')?.classList.remove('nav-open');if(S.search)runSearch(S.search.version);}
  if(event.target.id==='compose-body'&&(event.ctrlKey||event.metaKey)&&event.key==='Enter'){event.preventDefault();event.target.form.requestSubmit();}
  if(event.target.matches('#messages .message')&&(event.key==='Enter'||event.key===' ')){
    event.preventDefault();
    if(event.shiftKey)selectMessage(Number(event.target.dataset.id),true);
    else {S.selectionAnchor=Number(event.target.dataset.id);openMessageMenu(event.target);event.target.querySelector('.message-menu button:not(:disabled)')?.focus();}
  }
  if(event.key==='Escape'){closeMessageMenus();if(S.selected.size){S.selected.clear();S.selectionAnchor=null;selectionBar();}}
});
document.addEventListener('submit',async event=>{
  event.preventDefault();const form=event.target,f=new FormData(form),id=form.id;
  const error=form.querySelector('.inline-error')||document.querySelector(id==='auth-form'?'#auth-error':id==='compose-form'?'#compose-error':form.closest('.settings-page')?'#settings-error':'#dialog-error');if(error)error.textContent='';
  const buttons=[...document.querySelectorAll(`button[form="${id}"],#${id} button[type="submit"]`)];buttons.forEach(b=>b.disabled=true);
  try{
    if(id.startsWith('inline-')){await saveInline(form,f);return;}
    if(id.startsWith('agent-')){await submitAgentForm(form,f);return;}
    if(id.startsWith('file-')){await submitFileForm(id,form,f);return;}
    if(id==='auth-form'){
      const mode=form.dataset.mode,data={email:f.get('email'),password:f.get('password')};
      data.name=f.get('name');if(mode==='setup'){data.sample_projects=f.has('sample');data.setup_token=f.get('setup_token')||'';}if(mode==='register')data.token=S.invite;
      const result=await api('/auth/'+mode,'POST',data);
      if(mode==='register'){S.invite=null;history.replaceState(null,'','/');}
      await enter(result);
    }else if(id==='project-form'){
      const collaborator_emails=String(f.get('collaborators')||'').split(/[,;\s]+/).filter(Boolean);
      const project=await api('/projects','POST',{title:f.get('title'),collaborator_emails});
      modal.close();S.projects=await api('/projects');await go(project.id);
      if(project.invitations.length)dialog('Invite collaborators',`<div class="dialog-body"><p>Your project is private. Share each link with the person shown below. Links expire in seven days and can be used once. No email has been sent.</p>${project.invitations.map((inv,i)=>invitationLink(inv.email,inv.token,'created-invite-'+i)).join('')}</div>`,`<div class="dialog-footer"><button class="btn primary" data-action="close">Done</button></div>`);
    }else if(id==='topic-form'){
      const rename=form.dataset.rename==='true';
      const topic=await api(ctx(rename?`/topics/${S.topic.id}`:'/topics'),rename?'PATCH':'POST',{title:f.get('title'),...(rename?{revision:S.topic.revision}:{})});modal.close();await go(S.project.id,topic.id);
    }else if(id==='compose-form'){
      if(!String(f.get('body')||'').trim()){error.textContent='Enter a message.';document.querySelector('#compose-body').focus();return;}
      form.dataset.key ||= crypto.randomUUID();
      await api(ctx(`/topics/${S.topic.id}/messages`),'POST',{body:f.get('body'),tags:tagList(f.get('tags')||''),reply_to_id:S.replyTo?.id||null},{'Idempotency-Key':form.dataset.key});
      S.drafts.delete(`${S.project.id}:${S.topic.id}`);S.replyTo=null;form.reset();S.selected.clear();S.anchor=null;S.older=false;await reloadProject();const scroller=document.querySelector('.topic-scroll');scroller.scrollTop=scroller.scrollHeight;document.querySelector('#compose-body').focus();
    }else if(id==='tags-form'){
      await api(ctx(`/messages/${S.editMessage.id}/tags`),'PATCH',{tags:tagList(f.get('tags')),revision:S.editMessage.revision});modal.close();await reloadProject();
    }else if(id==='edit-form'){
      const m=S.editMessage;await api(ctx(`/messages/${m.id}`),'PATCH',{body:f.get('body'),title:f.get('title')||'',tags:tagList(f.get('tags')),model:m.model,run_id:m.run_id,revision:m.revision,archived:m.archived});modal.close();await reloadProject();
    }else if(id==='move-form'){
      const target=f.get('target')==='new'?{new_topic_title:f.get('title')}:{target_topic_id:Number(f.get('target'))};
      const m=S.moving[0];const response=S.batchMove?await api(ctx(`/topics/${S.topic.id}/move-messages`),'POST',{...target,messages:S.moving.map(m=>({id:m.id,revision:m.revision}))}):await api(ctx(`/messages/${m.id}/move`),'POST',{...target,mode:f.get('mode'),revision:m.revision});
      modal.close();await go(S.project.id,response.topic_id);
    }else if(id==='dashboard-question-form'){
      const q=S.editQuestion;
      await api(ctx('/dashboard-questions'+(q?'/'+q.id:'')),q?'PATCH':'POST',{body:f.get('body'),...(q?{revision:q.revision}:{})});
      modal.close();await reloadProject();
    }else if(id==='delete-question-form'){
      const q=S.editQuestion;await api(ctx(`/dashboard-questions/${q.id}?revision=${q.revision}`),'DELETE');modal.close();await reloadProject();
    }else if(id==='invite-form'){
      const result=await api(ctx('/invitations'),'POST',{email:f.get('email')});
      document.querySelector('#invite-result').innerHTML=`<div class="secret"><p>Single-use invitation for ${esc(f.get('email'))}. Expires in seven days.</p><input id="invite-link" aria-label="Invitation link" readonly value="${esc(location.origin+'/#invite='+result.token)}"><button class="btn" data-action="copy" data-target="invite-link" type="button">Copy invitation</button></div>`;
    }else if(id==='key-form'){
      const result=await api(ctx('/keys'),'POST',Object.fromEntries(f));await settings();
      document.querySelector('#key-result').innerHTML=`<div class="secret"><p>Copy this key now; it will not be shown again.</p><input id="agent-key" aria-label="New agent API key" readonly value="${esc(result.token)}"><button class="btn" data-action="copy" data-target="agent-key" type="button">Copy key</button></div>`;
    }else if(id==='links-form'){
      const ids=f.getAll('project').map(Number),old=S.project.linked_projects.map(p=>p.id);
      for(const target of ids.filter(i=>!old.includes(i)))await api(ctx('/linked-projects'),'POST',{project_id:target});
      for(const target of old.filter(i=>!ids.includes(i)))await api(ctx(`/linked-projects/${target}`),'DELETE');
      S.project=await api(ctx(''));toast('Project links saved.');
    }
  }catch(e){if(error?.isConnected)error.textContent=e.message;else toast(e.message,true);}
  finally{buttons.forEach(b=>b.disabled=false);}
});
window.addEventListener('popstate',()=>{if(S.user){const p=new URLSearchParams(location.hash.slice(1));go(Number(p.get('project'))||S.projects[0]?.id,Number(p.get('topic'))||null,Number(p.get('message'))||null,false,['files','search','settings','agents','editor'].includes(p.get('view'))?p.get('view'):'dashboard').catch(e=>toast(e.message,true));}});
setInterval(async()=>{
  if(!S.user||!S.project||S.view==='editor'||S.view==='settings'||S.search||document.activeElement?.matches('.sidebar-search input')||modal.open||document.hidden||S.polling||S.inlineEdit||quickTagQueues.size||S.drag||S.movingDrop||document.querySelector('.message-menu[open]'))return;
  if(S.view==='agents'){await loadAgents(true).catch(()=>{});return;}
  S.polling=true;const pid=S.project.id,tid=S.topic?.id,version=S.load;
  if(pendingReads.size)flushReads();
  try{
    const [topics,projects,project]=await Promise.all([api(ctx('/topics')),api('/projects'),api(ctx(''))]);if(S.load!==version)return;
    S.project={...S.project,...project};
    const changed=tid&&topics.find(t=>t.id===tid)?.revision!==S.topic.revision;
    S.topics=topics;S.projects=projects;document.querySelector('#sidebar').innerHTML=sidebar();
    if(tid){
      if(changed){
        if(S.selected.size||S.older||S.anchor){document.querySelector('#new-activity').hidden=false;}
        else await loadTopic({quiet:true});
      }
    }else if(S.view==='settings')await settings();else if(S.view==='files')await loadFiles();else if(S.view==='editor')await loadManuscript();else if(S.view==='agents')await loadAgents();else if(S.view==='search'){S.search={scope:'project',query:'',projectId:S.project.id,results:[],hasMore:false,loading:false,version:S.load};renderSearch();document.querySelector('#project-search').focus();}else await loadOverview();
  }catch(error){if(error.status===401){S.user=null;location.reload();}}
  finally{S.polling=false;}
},8000);
async function init(){
  try{
    const status=await api('/status');if(status.setup_required){S.setupTokenRequired=status.setup_token_required;auth('setup');return;}
    let result;try{result=await api('/auth/me');}catch(error){if(error.status===401){auth(S.invite?'register':'login');return;}throw error;}
    await enter(result);
  }catch(error){app.innerHTML=`<main class="auth"><div><h1>Could not load projects.</h1><p>${esc(error.message)}</p><a href="/">Retry</a></div></main>`;}
}
init();
