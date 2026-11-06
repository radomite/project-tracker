'use strict';
// The only public UI: sign in, protected first-account setup, or an invitation.
const root=document.querySelector('#login-root');
let invite=new URLSearchParams(location.hash.slice(1)).get('invite');
let status;
async function request(path,data){
  const response=await fetch('/api/v1'+path,{method:data?'POST':'GET',credentials:'same-origin',
    headers:data?{'Content-Type':'application/json'}:{},...(data?{body:JSON.stringify(data)}:{})});
  const result=await response.json();
  if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'Please check your details and try again.');
  return result;
}
function render(mode){
  const create=mode!=='login';
  root.innerHTML=`<form id="auth-form" data-mode="${mode}"><h1>${create?'Create account':'Sign in'}</h1>${invite?'<p class="help">Use the email address on your invitation.</p>':''}<div class="error" id="auth-error" role="alert"></div><label for="name">Your name</label><input id="name" name="name" required maxlength="100" autocomplete="name"><p class="help">Use the name other project members should see.</p><label for="email">Email address</label><input id="email" name="email" type="email" required autocomplete="username"><label for="password">Password</label><input id="password" name="password" type="password" required ${create?'minlength="10"':''} autocomplete="${create?'new-password':'current-password'}">${create?'<p class="help">At least 10 characters.</p>':''}${mode==='setup'&&status.setup_token_required?'<label for="setup-token">Initial setup key</label><input id="setup-token" name="setup_token" type="password" required autocomplete="off"><p class="help">Use the key provided by your server administrator.</p>':''}${mode==='setup'?'<label class="checkbox-label"><input type="checkbox" name="sample" checked>Include sample projects</label>':''}<button class="primary" type="submit">${mode==='register'?'Create account & join':create?'Create account':'Sign in'}</button>${invite?`<button type="button" class="text-btn" id="auth-switch">${create?'Sign in instead':'Create an account'}</button>`:''}</form>`;
  document.querySelector('#auth-switch')?.addEventListener('click',()=>render(create?'login':'register'));
  document.querySelector('#auth-form').addEventListener('submit',async event=>{
    event.preventDefault();const form=event.currentTarget,fields=new FormData(form),button=form.querySelector('[type=submit]');
    const error=document.querySelector('#auth-error');error.textContent='';button.disabled=true;
    try{
      const data={name:fields.get('name'),email:fields.get('email'),password:fields.get('password')};
      if(mode==='setup'){data.setup_token=fields.get('setup_token')||'';data.sample_projects=fields.has('sample');}
      if(mode==='register')data.token=invite;
      const result=await request('/auth/'+mode,data);
      if(invite&&mode==='login')await fetch('/api/v1/invitations/accept',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':result.csrf},body:JSON.stringify({token:invite})}).then(async response=>{if(!response.ok)throw new Error((await response.json()).detail);});
      if(invite){invite=null;history.replaceState(null,'','/');}
      location.reload();
    }catch(problem){error.textContent=problem.message;button.disabled=false;}
  });
}
request('/status').then(value=>{status=value;render(status.setup_required?'setup':invite?'register':'login');})
  .catch(()=>{root.textContent='Could not connect. Please reload the page.';});
