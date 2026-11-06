/* Project agents use the same session and CSRF protection as the main app. */
function agentRunHTML(run,role) {
  const active=['queued','running'].includes(run.status);
  return `<article class="agent-run"><div class="agent-run-meta"><span class="pill">${esc(run.status)}</span><time datetime="${esc(run.created_at)}" title="${esc(new Date(run.created_at).toLocaleString())}">${esc(clock(run.created_at))}</time>${active?`<button type="button" class="text-btn" data-agent-cancel="${run.id}" data-role="${role}">Cancel</button>`:''}</div><p class="agent-prompt">${esc(run.prompt)}</p>${run.output?`<div class="markdown agent-answer" data-agent-output="${run.id}"></div>`:''}${run.error?`<p class="error" role="alert">${esc(run.error)}</p>`:''}</article>`;
}
function updateAgentRuns(data) {
  for(const agent of data.agents){
    const panel=document.querySelector(`[data-agent-runs="${agent.role}"]`);
    if(!panel)continue;
    const signature=JSON.stringify(agent.runs);
    if(panel.dataset.signature!==signature){
      panel.innerHTML=agent.runs.slice(0,10).map(run=>agentRunHTML(run,agent.role)).join('')||'<p class="muted small">No requests yet.</p>';
      panel.dataset.signature=signature;
      for(const run of agent.runs){const out=panel.querySelector(`[data-agent-output="${run.id}"]`);if(out)markdown(out,run.output);}
    }
    const submit=document.querySelector(`#agent-run-${agent.role} button[type="submit"]`);
    if(submit)submit.disabled=!data.available||agent.runs.some(run=>['queued','running'].includes(run.status));
  }
  const status=document.querySelector('#agent-service-status');
  if(status)status.textContent=data.online?'Codex server connected.':data.available?'Codex server offline. Requests will wait in the queue.':'Codex service has not been started.';
}
async function loadAgents(quiet=false) {
  const pid=S.project.id,version=S.load;
  const [data,clusters]=await Promise.all([api(`/projects/${pid}/agents`),quiet?Promise.resolve(null):api('/agent-clusters')]);
  if(S.load!==version||S.project?.id!==pid||S.view!=='agents')return;
  if(quiet&&document.querySelector('.agents-page')){updateAgentRuns(data);return;}
  document.querySelector('.page-header h1').textContent='Project agents';
  document.querySelector('.header-actions').innerHTML='<button class="text-btn" type="button" data-agent-refresh>Refresh</button>';
  S.agentDrafts ||= new Map();
  document.querySelector('#page').innerHTML=`<div class="agents-page"><p id="agent-service-status" class="muted small" role="status"></p><div class="agent-columns">${data.agents.map(agent=>`<section class="agent-card" aria-labelledby="agent-name-${agent.role}"><header class="agent-card-heading"><span class="avatar agent-avatar" aria-hidden="true">${agent.name[0]}</span><div><h2 id="agent-name-${agent.role}">${esc(agent.name)} <span class="muted">${esc(agent.purpose)}</span></h2><span class="muted small">${esc(agent.model)}</span></div></header><form id="agent-run-${agent.role}" data-role="${agent.role}"><label class="sr-only" for="agent-prompt-${agent.role}">Request for ${esc(agent.name)}</label><textarea id="agent-prompt-${agent.role}" name="prompt" required maxlength="50000" rows="3" placeholder="${agent.role==='astra'?'Ask Astra to investigate a question…':'Ask Sol to edit a file or passage…'}">${esc(S.agentDrafts.get(`${pid}:${agent.role}`)||'')}</textarea><div class="agent-form-footer"><button type="submit" class="btn primary">Send to ${esc(agent.name)}</button><button type="button" class="text-btn" data-agent-mail="${agent.role}">Agent messages</button></div><div class="inline-error error" role="alert"></div></form><div data-agent-mailbox="${agent.role}" hidden></div><div data-agent-runs="${agent.role}"></div></section>`).join('')}</div><section class="agent-clusters"><h2>Project clusters</h2><p class="help">Astra and Sol can talk within this project. Agents in projects sharing a cluster can exchange messages. Other agents stay isolated. A project can belong to several clusters; cluster access does not extend through other clusters.</p><div class="error" id="agent-cluster-error" role="alert"></div>${clusters.map(cluster=>{
    const member=cluster.projects.find(project=>project.id===pid);
    const active=member?.cluster_approved&&member?.project_approved;
    const canChange=(S.project.is_owner||cluster.is_owner)&&(member||cluster.is_owner);
    return `<label class="agent-cluster-row"><input type="checkbox" data-agent-cluster="${cluster.id}" ${active?'checked':''} ${canChange?'':'disabled'}><span><strong>${esc(cluster.name)}</strong>${member&&!active?' <span class="pill">Awaiting owner approval</span>':''}<span class="muted small agent-cluster-projects">${cluster.projects.map(project=>esc(project.title)).join(' · ')||'No projects assigned'}</span></span></label>`;
  }).join('')||'<p class="muted small">No clusters yet.</p>'}<form id="agent-cluster-create" class="inline-form"><label class="sr-only" for="agent-cluster-name">New cluster name</label><input id="agent-cluster-name" name="name" maxlength="100" required placeholder="New cluster name"><button type="submit" class="btn">Create & assign</button><div class="error inline-error" role="alert"></div></form><p class="help">Assignments require approval from both the project owner and cluster owner. Removing an assignment blocks future exchanges immediately. Content already read remains in the recipient's saved conversation. Messages arrive in an inbox read on the recipient's next request.</p></section></div>`;
  updateAgentRuns(data);
}
async function submitAgentForm(form,fields) {
  const pid=S.project.id;
  if(form.id==='agent-cluster-create'){
    const cluster=await api('/agent-clusters','POST',{name:fields.get('name')});
    await api(`/agent-clusters/${cluster.id}/projects/${pid}`,'PUT');
  }else{
    const role=form.dataset.role;
    await api(`/projects/${pid}/agents/${role}/runs`,'POST',{prompt:fields.get('prompt')});
    S.agentDrafts.delete(`${pid}:${role}`);
  }
  if(S.project?.id===pid&&S.view==='agents')await loadAgents();
}
document.addEventListener('input',event=>{
  if(event.target.matches('.agents-page textarea[name="prompt"]'))S.agentDrafts.set(`${S.project.id}:${event.target.form.dataset.role}`,event.target.value);
});
document.addEventListener('change',async event=>{
  const checkbox=event.target.closest('[data-agent-cluster]');if(!checkbox)return;
  checkbox.disabled=true;
  try{
    await api(`/agent-clusters/${checkbox.dataset.agentCluster}/projects/${S.project.id}`,checkbox.checked?'PUT':'DELETE');
    await loadAgents();
  }catch(error){checkbox.checked=!checkbox.checked;document.querySelector('#agent-cluster-error').textContent=error.message;checkbox.disabled=false;}
});
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-agent-cancel],[data-agent-refresh],[data-agent-mail]');if(!button)return;
  const pid=S.project?.id;if(!pid)return;
  try{
    if(button.hasAttribute('data-agent-refresh')){
      button.disabled=true;
      try{await loadAgents();}finally{if(button.isConnected)button.disabled=false;}
      return;
    }
    if(button.dataset.agentCancel){
      await api(`/projects/${pid}/agents/${button.dataset.role}/runs/${button.dataset.agentCancel}`,'DELETE');
      if(S.project?.id===pid&&S.view==='agents')await loadAgents(true);
      return;
    }
    const role=button.dataset.agentMail,mail=await api(`/projects/${pid}/agents/${role}/mail`);
    if(S.project?.id!==pid||S.view!=='agents')return;
    const host=document.querySelector(`[data-agent-mailbox="${role}"]`);host.hidden=!host.hidden;
    host.innerHTML=mail.map(message=>`<article class="agent-mail"><div class="small muted">${esc(message.sender_role)} · ${esc(message.sender_project)} → ${esc(message.recipient_role)} · ${esc(message.recipient_project)}</div><div class="markdown" data-agent-mail-body="${message.id}"></div></article>`).join('')||'<p class="muted small">No agent messages.</p>';
    mail.forEach(message=>markdown(host.querySelector(`[data-agent-mail-body="${message.id}"]`),message.body));
  }catch(error){toast(error.message,true);}
});
