"""Compose Codex supervisor. No TCP Codex listener or Docker socket is exposed.

Each project/role has a distinct Linux UID, private CODEX_HOME, workspace, and
persistent thread. Only this trusted supervisor holds the app service credential.
"""
import concurrent.futures
import json
import os
from pathlib import Path
import queue
import re
import secrets
import signal
import subprocess
import threading
import time

import httpx

VERSION = '0.1.0'
IDENTITY_LOCK = threading.Lock()
OPERATIONS = ['context', 'files', 'read_file', 'write_file', 'peers', 'send', 'inbox']
TOOLS = [{
    'name':'project_tool',
    'description':('Access only your project. context returns project questions and recent messages; files lists files; '
        'read_file takes path; write_file takes path,text and the current etag (omit for a new file); '
        'peers lists agents permitted by project clusters; send takes recipient_id,body; inbox reads incoming messages. '
        'Mail is persistent and read when the recipient next works. File saves stay in the app batch, without committing.'),
    'inputSchema':{'type':'object', 'properties':{
        'operation':{'type':'string','enum':OPERATIONS},
        'arguments':{'type':'object','properties':{
            'path':{'type':'string'}, 'text':{'type':'string'}, 'etag':{'type':'string'},
            'recipient_id':{'type':'integer'}, 'body':{'type':'string'}}, 'additionalProperties':False}},
        'required':['operation','arguments'], 'additionalProperties':False}
}]


def sandbox(work):
    return {'type':'workspaceWrite', 'writableRoots':[str(work)],
            'readOnlyAccess':{'type':'restricted','includePlatformDefaults':True,'readableRoots':[str(work)]},
            'networkAccess':False}


class Rpc:
    """Small bidirectional JSONL client; incoming requests never bypass our tool gate."""
    def __init__(self, process, callback, check=None):
        self.process, self.callback = process, callback
        self.serial = 0
        self.events = queue.Queue()
        self.pending = {}
        self.thread_id = None
        self.check = check or (lambda: None)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.events.put(json.loads(line))
        except Exception:
            pass
        finally:
            self.events.put(None)

    def write(self, value):
        self.process.stdin.write(json.dumps(value)+'\n')
        self.process.stdin.flush()

    def message(self, timeout=1):
        self.check()
        try:
            event = self.events.get(timeout=timeout)
        except queue.Empty:
            return {}
        if event is None:
            raise RuntimeError('Codex app-server disconnected.')
        if 'method' in event and 'id' in event:
            params, method = event.get('params', {}), event['method']
            if method=='item/tool/call' and self.thread_id and params.get('threadId')==self.thread_id:
                try:
                    if params.get('tool')!='project_tool':
                        raise ValueError('Unrecognized tool.')
                    args = params.get('arguments', {})
                    if isinstance(args,str):
                        args = json.loads(args)
                    result = self.callback(args)
                    answer = {'contentItems':[{'type':'inputText','text':json.dumps(result)}], 'success':True}
                except Exception as error:
                    answer = {'contentItems':[{'type':'inputText','text':str(error)[:2000]}], 'success':False}
                self.write({'id':event['id'],'result':answer})
            elif method in ('item/commandExecution/requestApproval','item/fileChange/requestApproval'):
                self.write({'id':event['id'],'result':{'decision':'decline'}})
            elif method=='item/permissions/requestApproval':
                self.write({'id':event['id'],'result':{'permissions':{},'scope':'turn'}})
            else:
                self.write({'id':event['id'],'error':{'code':-32601,'message':'Interactive or unscoped requests are disabled.'}})
            return {}
        return event

    def call(self, method, params, timeout=60):
        self.serial += 1
        rid = self.serial
        self.write({'id':rid,'method':method,'params':params})
        deadline = time.monotonic()+timeout
        while time.monotonic()<deadline:
            event = self.message()
            if event.get('id')==rid and 'method' not in event:
                if 'error' in event:
                    raise RuntimeError(event['error'].get('message','Codex protocol error.'))
                return event.get('result', {})
            if event:
                self.pending.setdefault('notifications', []).append(event)
        raise TimeoutError('Codex did not acknowledge '+method)


def private_dir(path, uid=0):
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError('Agent state must not be a symlink.')
    os.chown(path, uid, uid)
    path.chmod(0o700)


def agent_uid(state, identity):
    if not re.fullmatch('[0-9a-f]{32}', identity):
        raise ValueError('Invalid agent identity.')
    # Numeric database IDs can be reused after database restoration/replacement.
    # Stable random identities must never inherit a different agent's UID/home.
    with IDENTITY_LOCK:
        mapping = state/'control'/'identities.json'
        identities = json.loads(mapping.read_text(encoding='utf-8')) if mapping.exists() else {}
        if identity not in identities:
            identities[identity] = max(identities.values(),default=20000)+1
            if identities[identity]>=2000000000:
                raise RuntimeError('Agent UID allocation exhausted.')
            temporary = mapping.with_suffix('.tmp')
            temporary.write_text(json.dumps(identities),encoding='utf-8')
            temporary.replace(mapping)
        return identities[identity]


def prepare_agent(state, identity):
    uid = agent_uid(state, identity)
    base = state/'agents'/identity
    # The root-owned parent prevents a worker replacing its home directory with
    # a symlink before the supervisor copies refreshed login credentials.
    private_dir(base)
    base.chmod(0o711)
    for name in ('home','work','tmp'):
        private_dir(base/name, uid)
    login = state/'login'/'auth.json'
    if not login.is_file():
        raise RuntimeError('Codex is not signed in. Run the documented container login first.')
    auth = base/'home'/'auth.json'
    # Never follow a path created by model tools when copying a credential as root.
    if auth.is_symlink():
        raise RuntimeError('Agent auth path must not be a symlink.')
    if not auth.exists() or login.stat().st_mtime>auth.stat().st_mtime:
        descriptor = os.open(auth, os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor,'wb') as stream:
            stream.write(login.read_bytes())
        os.chown(auth,uid,uid)
        auth.chmod(0o600)
    return base, uid


def run_job(job, state, app_url, secret, stopping=None):
    headers = {'Authorization':'Bearer '+secret, 'X-Agent-Lease':job['lease']}
    endpoint = f'/internal/agents/runs/{job["id"]}'
    process = None
    stopping = stopping or threading.Event()
    with httpx.Client(base_url=app_url, headers=headers, timeout=30, trust_env=False) as client:
        def post(path, value=None):
            response = client.post(endpoint+path, json=value or {})
            response.raise_for_status()
            return response.json()
        try:
            last_heartbeat = time.monotonic()
            deadline = time.monotonic()+1800
            def check():
                nonlocal last_heartbeat
                if stopping.is_set():
                    raise RuntimeError('Codex service is stopping.')
                if time.monotonic()>deadline:
                    raise TimeoutError('Codex run exceeded the 30 minute limit.')
                if time.monotonic()-last_heartbeat>=20:
                    post('/heartbeat')
                    last_heartbeat = time.monotonic()
            base, uid = prepare_agent(state, job['identity'])
            work = base/'work'
            checkpoint = state/'control'/f'{job["identity"]}.json'
            # Build a fresh environment: app credential, proxy settings, and other
            # projects' environment are never inherited by the Codex child.
            env = {'PATH':os.environ.get('PATH','/usr/local/bin:/usr/bin:/bin'),
                   'HOME':str(base/'home'), 'CODEX_HOME':str(base/'home'), 'TMPDIR':str(base/'tmp'),
                   'LANG':'C.UTF-8', 'PYTHONDONTWRITEBYTECODE':'1'}
            process = subprocess.Popen(['codex','app-server','--listen','stdio://',
                '-c','cli_auth_credentials_store="file"', '-c','features.multi_agent=false',
                '-c','mcp_servers={}', '-c','web_search="live"'],
                cwd=work, env=env, user=uid, group=uid, extra_groups=[],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf-8', start_new_session=True)
            rpc = Rpc(process, lambda args: post('/tool', args), check=check)
            rpc.call('initialize', {'clientInfo':{'name':'result_organizer','title':'Project agents','version':VERSION},
                                    'capabilities':{'experimentalApi':True}})
            rpc.write({'method':'initialized','params':{}})
            config = {'model':job['model'], 'cwd':str(work), 'approvalPolicy':'never', 'sandbox':'workspace-write'}
            if checkpoint.is_file():
                rpc.thread_id = json.loads(checkpoint.read_text(encoding='utf-8'))['thread_id']
                rpc.call('thread/resume', {**config,'threadId':rpc.thread_id,'excludeTurns':True})
            else:
                role = ('Research mathematical questions. Separate proved results, conjectures and gaps; cite sources and preserve explanations.'
                        if job['role']=='astra' else
                        'Help edit prose, source files and code. Preserve intent, explanations and collaborators\' changes; make focused edits.')
                response = rpc.call('thread/start', {**config, 'dynamicTools':TOOLS,
                    'developerInstructions':role+' You belong to exactly one project. Use project_tool for app data and files. '
                    'Read context and inbox when starting work. Talk only to agents returned by peers. '
                    'Workspaces are private scratch space; publish file changes through write_file with etag. '
                    'Never bypass the sandbox, change branches, commit files, install toolchains, or spawn extra agents.'})
                rpc.thread_id = response['thread']['id']
                temporary = checkpoint.with_suffix('.tmp')
                temporary.write_text(json.dumps({'thread_id':rpc.thread_id}),encoding='utf-8')
                temporary.replace(checkpoint)
            rpc.call('turn/start', {'threadId':rpc.thread_id,'input':[{'type':'text','text':job['prompt']}],
                                   'model':job['model'],'effort':'high' if job['role']=='astra' else 'medium',
                                   'cwd':str(work),'approvalPolicy':'never','sandboxPolicy':sandbox(work)})
            output = []
            while time.monotonic()<deadline:
                check()
                pending = rpc.pending.get('notifications', [])
                event = pending.pop(0) if pending else rpc.message()
                params = event.get('params', {})
                if params.get('threadId')!=rpc.thread_id:
                    continue
                if event.get('method')=='item/completed' and params.get('item',{}).get('type')=='agentMessage':
                    output.append(params['item'].get('text',''))
                if event.get('method')=='turn/completed':
                    turn = params['turn']
                    if turn['status']!='completed':
                        raise RuntimeError((turn.get('error') or {}).get('message') or 'Codex turn '+turn['status'])
                    post('/finish', {'status':'completed','output':'\n\n'.join(output)[-100000:]})
                    return
            raise TimeoutError('Codex run exceeded the 30 minute limit.')
        except Exception as error:
            # Never log headers, job prompt, auth data, or arbitrary tool output.
            message = str(error)[:1500]
            try:
                post('/finish', {'status':'failed','error':message})
            except Exception:
                pass
            print(f'Agent run {job["id"]} ended without completion.', flush=True)
        finally:
            if process:
                # Kill the session, including subprocess tools; a cancelled run
                # cannot continue editing after its capability has been revoked.
                try:
                    process.stdin.close()
                    process.wait(timeout=5)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    pass
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=10)


def main():
    if os.name!='posix' or os.geteuid()!=0:
        raise RuntimeError('Run this supervisor only in its Linux Compose container.')
    os.umask(0o077)
    state = Path(os.environ.get('CODEX_STATE','/state'))
    state.mkdir(parents=True,exist_ok=True)
    state.chmod(0o711)
    (state/'agents').mkdir(exist_ok=True)
    (state/'agents').chmod(0o711)
    private_dir(state/'control')
    private_dir(state/'login')
    link = Path(os.environ.get('RESEARCH_AGENT_SECRET_FILE','/agent-link/token'))
    link.parent.mkdir(exist_ok=True)
    os.chown(link.parent,0,1000)
    link.parent.chmod(0o710)
    if not link.exists():
        link.write_text(secrets.token_urlsafe(48),encoding='utf-8')
    os.chown(link,0,1000)
    link.chmod(0o640)
    secret = link.read_text(encoding='utf-8').strip()
    url = os.environ.get('RESEARCH_APP_URL','http://app:8765')
    stopping = threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stopping.set())
    signal.signal(signal.SIGINT,lambda *_:stopping.set())
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool, httpx.Client(
            base_url=url,headers={'Authorization':'Bearer '+secret},timeout=15,trust_env=False) as client:
        active = set()
        while not stopping.is_set():
            active = {future for future in active if not future.done()}
            try:
                if len(active)<2:
                    response = client.post('/internal/agents/claim')
                    response.raise_for_status()
                    job = response.json()['job']
                    if job:
                        active.add(pool.submit(run_job,job,state,url,secret,stopping))
                        continue
            except Exception:
                pass
            stopping.wait(2)


if __name__=='__main__':
    main()
