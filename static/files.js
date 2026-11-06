/* Folder browser and Git controls for project files. */
'use strict';
function fileSize(size) {
  return size<1024?`${size} B`:size<1024*1024?`${(size/1024).toFixed(1)} KB`:`${(size/1024/1024).toFixed(1)} MB`;
}
async function loadFiles() {
  const pid=S.project.id,version=S.load;
  const data=await api(`/projects/${pid}/files?history_limit=${S.fileHistoryLimit||50}`);
  if(S.project?.id!==pid||S.view!=='files'||version!==S.load||S.search)return;
  S.fileData=data;S.files=data.entries;
  const headerActions=document.querySelector('.header-actions');
  if(headerActions)headerActions.innerHTML=`<button class="text-btn git-integration" data-action="git-remote" aria-label="Git Integration">${ic('git')}<span>Git Integration</span></button>`;
  const oldHistory=document.querySelector('.file-history'),historyScroll=oldHistory?.scrollTop||0;
  S.openFileHistory=new Set([...document.querySelectorAll('.file-history details[open][data-history]')].map(el=>el.dataset.history));
  if(!data.entries.some(e=>e.kind==='folder'&&e.path===S.fileFolder))S.fileFolder='';
  const folders=data.entries.filter(e=>e.kind==='folder');
  document.querySelector('#page').innerHTML=`<section class="files-page"><div class="files-toolbar"><select id="file-destination" aria-label="Current folder"><option value="">Project root</option>${folders.map(e=>`<option value="${esc(e.path)}" ${S.fileFolder===e.path?'selected':''}>${esc(e.path)}</option>`).join('')}</select><button class="text-btn file-icon-button" data-action="file-upload" aria-label="Upload files" title="Upload files">${ic('upload')}</button><button class="text-btn file-icon-button" data-action="folder-upload" aria-label="Upload folder" title="Upload folder">${ic('folder-upload')}</button><button class="text-btn file-icon-button" data-action="file-new" aria-label="New text file" title="New text file">${ic('file-plus')}</button><button class="text-btn file-icon-button" data-action="folder-new" aria-label="New folder" title="New folder">${ic('folder-plus')}</button></div><div class="files-layout"><div class="files-tree">${fileTree(data.entries)||'<p class="muted empty">No files. Upload files or push to the Git remote.</p>'}</div><aside class="file-history" aria-label="File history">${fileHistory(data.history)}</aside></div></section>`;
  document.querySelector('.file-history').scrollTop=historyScroll;
  mountHistoryGraph();
}
function historyTime(date) {
  return `<time datetime="${esc(date)}" title="${esc(new Date(date).toLocaleString())}">${esc(new Date(date).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}))}</time>`;
}
function historyEvents(events) {
  return `<ul class="file-history-events">${[...events].reverse().map(event=>`<li><span>${esc(event.message)}${event.window_id?' · edit window':''}</span><small>${esc(event.author)} · ${historyTime(event.started_at||event.date)}${event.window_id?event.closed?` — ${historyTime(event.ended_at)} · ${esc(({focus:'focus left',idle:'inactive',disconnect:'disconnected','git-sync':'Git sync','server-restart':'server restarted',navigation:'navigation'})[event.close_reason]||event.close_reason)}`:' · active':''}</small></li>`).join('')}</ul>`;
}
function fileHistory(history) {
  const pending=history.pending;
  S.historyGraph=historyGraphRows(history.items);
  const rows=history.items.map((item,index)=>{
    const source=(item.source==='browser'?'Browser batch':item.source==='local'?'Local':'Git')+(item.parents.length>1?' · Merge':'');
    const refs=item.refs.map(ref=>`<span class="history-ref ${esc(ref.kind)} ${ref.kind==='branch'&&ref.name==='main'?'main':''}" title="${esc(ref.kind+': '+ref.name)}">${ref.kind==='tag'?'tag: ':''}${esc(ref.name)}</span>`).join('');
    return `<li class="file-history-item" data-history-row="${index}"><div class="history-graph" aria-hidden="true"></div><div class="file-history-content"><div class="file-history-title"><span class="history-commit-stamp">${item.commit?`<code title="${esc(item.commit)}">${esc(item.commit.slice(0,7))}</code>`:''}${historyTime(item.date)}</span><span class="history-entry-meta"><span class="history-author" title="${esc(item.author)}">${esc(item.author)}</span><span class="history-source">${esc(source)}</span></span></div><div class="history-subject"><p>${esc(item.message)}</p>${refs?`<span class="history-refs">${refs}</span>`:''}</div>${item.events.length?`<details data-history="${esc(item.commit||item.date)}" ${S.openFileHistory?.has(item.commit||item.date)?'open':''}><summary>${item.events.length} local changes</summary>${historyEvents(item.events)}</details>`:''}</div></li>`;
  }).join('');
  return `<h2>History</h2><p class="history-scope">All branches · files on <strong>main</strong></p><section class="file-pending"><div class="file-history-title"><strong>Local changes</strong><span class="history-source">${pending.length?pending.length+' pending':'All committed'}</span></div><p class="help">Files save immediately. Edits collect into a batch until you commit or sync with Git.</p>${pending.length?`<button class="btn" data-action="file-commit">Commit batch</button>${historyEvents(pending)}`:''}</section><ol class="file-history-list" aria-label="Commit graph across all branches" style="--graph-width:${S.historyGraph.width}px">${rows}</ol>${history.has_more&&(S.fileHistoryLimit||50)<500?'<button class="text-btn" data-action="file-history-more">Show more history</button>':''}`;
}
function fileCommitForm() {
  dialog('Commit file batch',`<form id="file-commit-form" class="dialog-body">${formError()}<p>Commit all ${S.fileData.history.pending.length} pending changes in this project together.</p><label for="file-commit-message">Commit message (optional)</label><input id="file-commit-message" name="message" maxlength="500" placeholder="Update project files"></form>`,formFooter('file-commit-form','Commit batch'));
}
function fileTree(entries) {
  const root={children:new Map()};
  for(const entry of entries){
    let node=root,path='';
    for(const part of entry.path.split('/')){
      path=path?path+'/'+part:part;
      if(!node.children.has(part))node.children.set(part,{name:part,path,children:new Map()});
      node=node.children.get(part);
    }
    node.entry=entry;
  }
  const render=node=>[...node.children.values()].sort((a,b)=>{
    const af=a.entry?.kind==='folder'||a.children.size,bf=b.entry?.kind==='folder'||b.children.size;
    return Number(!!bf)-Number(!!af)||a.name.localeCompare(b.name);
  }).map(child=>{
    const folder=child.entry?.kind==='folder'||child.children.size;
    const tools=`<button class="text-btn file-icon-button" title="Rename" data-action="file-move" data-path="${esc(child.path)}" aria-label="Rename ${folder?'folder':'file'} ${esc(child.name)}">${ic('edit')}</button><button class="text-btn file-icon-button" title="Delete" data-action="file-delete" data-path="${esc(child.path)}" aria-label="Delete ${folder?'folder':'file'} ${esc(child.name)}">${ic('trash')}</button>`;
    if(folder)return `<details class="files-folder" data-folder="${esc(child.path)}" ${S.closedFolders?.has(child.path)?'':'open'}><summary><span class="folder-title">${ic('folder')} ${esc(child.name)}</span><span class="file-actions">${tools}</span></summary><div class="folder-children">${render(child)}</div></details>`;
    return `<div class="file-row"><button class="file-title" data-action="file-open" data-path="${esc(child.path)}">${ic('file')} ${esc(child.name)}</button><span class="file-size">${fileSize(child.entry.size)}</span><span class="file-actions"><a class="text-btn file-icon-button" aria-label="Download" title="Download" href="/api/v1/projects/${S.project.id}/files/content?path=${encodeURIComponent(child.path)}" download>${ic('download')}</a>${tools}</span></div>`;
  }).join('');
  return render(root);
}
async function viewFile(path) {
  const file=await api(ctx('/files/preview?path='+encodeURIComponent(path)));
  S.previewFile=file;
  dialog(path,`<div class="dialog-body"><p class="small muted">${fileSize(file.size)}</p><div id="file-content" class="markdown"></div></div><div class="dialog-footer">${file.text!==null?'<button class="btn" data-action="file-edit">Edit</button>':''}<a class="btn" href="/api/v1/projects/${S.project.id}/files/content?path=${encodeURIComponent(path)}" download>Download</a></div>`);
  const el=document.querySelector('#file-content');
  if(file.text===null)el.textContent='Binary file. Download it to open in its application.';
  else if(path.toLowerCase().endsWith('.md'))markdown(el,file.text);
  else {const pre=document.createElement('pre');pre.textContent=file.text;el.append(pre);}
}
function newFileForm(edit=false) {
  const file=edit?S.previewFile:null;S.editingFile=file;
  dialog(edit?'Edit file':'New text file',`<form id="file-text-form" class="dialog-body">${formError()}<label for="file-path">File path</label><input id="file-path" name="path" value="${esc(file?.path||(S.fileFolder?S.fileFolder+'/':''))}" ${edit?'readonly':''} maxlength="1000" required placeholder="proofs/main.tex"><label for="file-text">Contents</label><textarea id="file-text" name="content" rows="12">${esc(file?.text||'')}</textarea></form>`,formFooter('file-text-form','Save file'));
}
function uploadFileForm(folder=false) {
  dialog(folder?'Upload folder':'Upload files',`<form id="file-upload-form" class="dialog-body">${formError()}<label for="upload-destination">Destination folder</label><input id="upload-destination" name="folder" value="${esc(S.fileFolder||'')}" placeholder="Project root"><label for="file-upload-input">${folder?'Choose folder':'Choose files'}</label><input id="file-upload-input" name="files" type="file" multiple ${folder?'webkitdirectory directory':''} required><label class="checkbox-label"><input type="checkbox" name="replace">Replace existing files</label><p class="help">Any file type. Folder uploads preserve their directory structure.</p><p id="upload-progress" class="small muted" role="status"></p></form>`,formFooter('file-upload-form','Upload'));
}
function newFolderForm() {
  dialog('New folder',`<form id="file-folder-form" class="dialog-body">${formError()}<label for="folder-path">Folder path</label><input id="folder-path" name="path" value="${esc(S.fileFolder?S.fileFolder+'/':'')}" maxlength="1000" required placeholder="proofs/figures"></form>`,formFooter('file-folder-form','Create folder'));
}
function fileMoveForm(path) {
  S.movingFile=S.files.find(e=>e.path===path);
  dialog('Rename or move',`<form id="file-move-form" class="dialog-body">${formError()}<label for="file-new-path">New path</label><input id="file-new-path" name="path" value="${esc(path)}" maxlength="1000" required></form>`,formFooter('file-move-form','Move'));
}
function fileDeleteForm(path) {
  S.deletingFile=S.files.find(e=>e.path===path);
  dialog('Delete '+(S.deletingFile.kind==='folder'?'folder':'file'),`<form id="file-delete-form" class="dialog-body">${formError()}<p>Delete <strong>${esc(path)}</strong>?</p>${S.deletingFile.kind==='folder'?'<p class="help">The folder must be empty.</p>':''}</form>`,formFooter('file-delete-form','Delete'));
}
function gitRemoteDialog() {
  const url=new URL(S.fileData.git_url);url.username='token';
  dialog('Git remote',`<div class="dialog-body"><label for="git-url">Remote URL</label><input id="git-url" value="${esc(url.href)}" readonly><button class="text-btn" data-action="copy" data-target="git-url">Copy URL</button><pre class="git-command">${esc('git clone '+url.href)}</pre><p>Use a project key from Project settings as the password. Read-only keys can clone; read/write keys can push.</p><p class="small muted">The Files page shows the main branch. Browser edits save immediately and collect into one batch. Commit the batch from History, or it will be committed when Git connects. Git pushes update these same files.</p></div>`);
}
async function uploadContent(path,body,etag=null) {
  const response=await fetch('/api/v1'+ctx('/files/content?path='+encodeURIComponent(path)),{
    method:'PUT',credentials:'same-origin',headers:{'X-CSRF-Token':S.csrf,'Content-Type':'application/octet-stream',
      ...(etag?{'If-Match':etag}:{'If-None-Match':'*'})},body});
  const result=await response.json();
  if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'The file could not be saved.');
  return result;
}
async function submitFileForm(id,form,f) {
  if(id==='file-text-form'){
    await uploadContent(f.get('path'),new Blob([f.get('content')],{type:'text/plain;charset=utf-8'}),S.editingFile?.etag);
  }else if(id==='file-upload-form'){
    const files=[...document.querySelector('#file-upload-input').files];
    const folder=String(f.get('folder')||'').replace(/\/+$/,'');
    for(let i=0;i<files.length;i++){
      const file=files[i],relative=file.webkitRelativePath||file.name,path=folder?folder+'/'+relative:relative;
      if(file.size>S.fileData.max_file_bytes)throw new Error(file.name+' exceeds the 100 MiB file limit.');
      const current=f.has('replace')?S.files.find(e=>e.path===path):null;
      document.querySelector('#upload-progress').textContent=`Uploading ${i+1} of ${files.length}: ${file.name}`;
      await uploadContent(path,file,current?.etag);
    }
  }else if(id==='file-commit-form'){
    await api(ctx('/files/commit'),'POST',{message:f.get('message')});
  }else if(id==='file-folder-form'){
    await api(ctx('/files/folders'),'POST',{path:f.get('path')});
  }else if(id==='file-move-form'){
    await api(ctx('/files/entry'),'PATCH',{path:S.movingFile.path,new_path:f.get('path')},{'If-Match':S.movingFile.etag});
  }else if(id==='file-delete-form'){
    await api(ctx('/files/entry?path='+encodeURIComponent(S.deletingFile.path)),'DELETE',undefined,{'If-Match':S.deletingFile.etag});
  }else return false;
  modal.close();await loadFiles();return true;
}
document.addEventListener('toggle',event=>{
  if(event.target.matches('.files-folder')){
    S.closedFolders ||= new Set();
    if(event.target.open)S.closedFolders.delete(event.target.dataset.folder);else S.closedFolders.add(event.target.dataset.folder);
  }
},true);
