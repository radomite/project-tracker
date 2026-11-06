"""Build and check an isolated Compose project; install no host toolchains."""
import argparse
import base64
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools', action='store_true', help='Also build/check Typst, TeX Live, Lean/mathlib, and SageMath (large downloads).')
    parser.add_argument('--agents', action='store_true', help='Also check the real Codex protocol, isolation, and offline app bridge (no inference).')
    parser.add_argument('--min-free-gb', type=float, help='Host free-space minimum (default: 5 GiB, 8 GiB with --agents, 30 GiB with --tools).')
    parser.add_argument('--work-root', type=Path, help='Host location for disposable tool workspaces/output; choose a drive with enough free space.')
    args = parser.parse_args()
    minimum = args.min_free_gb if args.min_free_gb is not None else 30 if args.tools else 8 if args.agents else 5
    if minimum < 0:
        parser.error('--min-free-gb cannot be negative.')
    work_root = (args.work_root or Path(os.environ.get('RESEARCH_CHECK_ROOT', ROOT/'.checks'))).resolve()
    probe = work_root
    while not probe.exists():
        probe = probe.parent
    free = shutil.disk_usage(probe).free / 1024**3
    if free < minimum:
        parser.error(f'Only {free:.2f} GiB is free on the check workspace drive; {minimum:g} GiB is required. '
                     'No Docker operations started. Free space or move Docker storage before continuing.')
    project = 'tracker-check-'+uuid.uuid4().hex[:12]
    check = work_root/project
    workspace = check/'work'
    workspace.mkdir(parents=True)
    shutil.copytree(ROOT/'tool-workspace'/'examples', workspace/'examples')
    env = {**os.environ, 'APP_BIND':'127.0.0.1', 'APP_PORT':'0',
           'APP_IMAGE':'result-organizer-web:'+project, 'RESEARCH_SECURE_COOKIE':'0',
           'TOOL_WORKSPACE':str(workspace), 'TOOL_UID':'1000', 'TOOL_GID':'1000'}
    compose = ['docker', 'compose', '--project-name', project, '--file', str(ROOT/'compose.yaml')]

    def run(*command, capture=False, extra_env=None):
        print('> '+' '.join(command), flush=True)
        return subprocess.run(command, cwd=ROOT, env={**env, **(extra_env or {})}, check=True,
                              text=True, capture_output=capture).stdout

    def dc(*command, **kwargs):
        return run(*compose, *command, **kwargs)

    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    base, csrf = '', ''

    def request(path, method='GET', data=None, headers=None):
        raw = data if isinstance(data, bytes) else json.dumps(data).encode() if data is not None else None
        response = opener.open(urllib.request.Request(base+path, data=raw, method=method,
            headers={'Content-Type':'application/octet-stream' if isinstance(data, bytes) else 'application/json',
                     'X-CSRF-Token':csrf, **(headers or {})}), timeout=15)
        content = response.read()
        return json.loads(content) if 'application/json' in response.headers.get('Content-Type','') else content

    def healthy():
        deadline = time.monotonic()+90
        while time.monotonic()<deadline:
            try:
                if request('/health')['status']=='ok':
                    return
            except (OSError, urllib.error.HTTPError):
                time.sleep(.5)
        raise RuntimeError('Container did not become healthy.')

    try:
        dc('--profile', 'tools', 'config', '--quiet')
        test_image = 'result-organizer-tests:'+project
        run('docker', 'build', '--target', 'test', '--tag', test_image, '.')
        run('docker', 'run', '--rm', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', test_image)
        dc('up', '--detach', '--build', '--wait', '--wait-timeout', '120', 'app')
        port = dc('port', 'app', '8765', capture=True).strip().rsplit(':',1)[1]
        base = 'http://127.0.0.1:'+port
        healthy()
        auth = request('/api/v1/auth/setup', 'POST', {'name':'Container checker',
            'email':'container@example.org', 'password':secrets.token_urlsafe(24), 'sample_projects':False})
        csrf = auth['csrf']
        research = request('/api/v1/projects', 'POST', {'title':'Container integration'})
        pid = research['id']
        prefix = '/api/v1/projects/'+str(pid)
        request(prefix+'/files/content?path=hello.txt', 'PUT', b'Browser to Git', {'If-None-Match':'*'})
        # A tool can read pending files but cannot mutate the canonical repositories.
        probe = ("from pathlib import Path; p=Path('/projects/"+str(pid)+"/hello.txt'); "
                 "assert p.read_bytes()==b'Browser to Git'; "
                 "import os; assert not os.access(p,os.W_OK); print('Read-only project mount verified.')")
        dc('run', '--rm', '--no-deps', '-T', 'python', '-c', probe)
        key = request(prefix+'/keys', 'POST', {'name':'Container Git check', 'scope':'write'})['token']
        git_env = {'GIT_CONFIG_COUNT':'1', 'GIT_CONFIG_KEY_0':'http.extraHeader',
                   'GIT_CONFIG_VALUE_0':'Authorization: Basic '+base64.b64encode(('token:'+key).encode()).decode()}

        def git(*command):
            dc('run', '--rm', '--no-deps', '-T', '-e', 'GIT_CONFIG_COUNT', '-e', 'GIT_CONFIG_KEY_0',
               '-e', 'GIT_CONFIG_VALUE_0', 'git', *command, extra_env=git_env)

        git('clone', 'http://app:8765/git/projects/'+str(pid)+'.git', 'clone')
        assert (workspace/'clone'/'hello.txt').read_bytes()==b'Browser to Git'
        (workspace/'clone'/'from-container.txt').write_text('Git to browser', encoding='utf-8')
        git('-C', 'clone', 'add', 'from-container.txt')
        git('-C', 'clone', '-c', 'user.name=Container checker', '-c', 'user.email=container@example.org',
            'commit', '-m', 'Check container Git push')
        git('-C', 'clone', 'push', 'origin', 'main')
        assert request(prefix+'/files/content?path=from-container.txt')==b'Git to browser'
        request(prefix+'/files/content?path=pending.txt', 'PUT', b'Pending across restart', {'If-None-Match':'*'})
        before = request(prefix+'/files')
        dc('restart', 'app')
        healthy()
        after = request(prefix+'/files')
        assert after['head']==before['head'] and len(after['history']['pending'])==1
        assert request(prefix+'/files/content?path=pending.txt')==b'Pending across restart'
        print('App, persisted database/files, pending batches, and real container Git clone/push passed.', flush=True)

        if args.agents:
            dc('--profile', 'agents', 'build', 'codex')
            dc('--profile', 'agents', 'run', '--rm', '--no-deps', '-T', '--entrypoint', 'python',
               'codex', '/service/check_codex_container.py')
            dc('--profile', 'agents', 'up', '--detach', 'codex')
            deadline = time.monotonic()+60
            while time.monotonic()<deadline:
                state = request(prefix+'/agents')
                if state['available'] and state['online']:
                    break
                time.sleep(.5)
            else:
                raise RuntimeError('Codex supervisor did not connect to the app.')
            assert [(a['role'],a['model']) for a in state['agents']]==[
                ('astra','gpt-6-astra'),('sol','gpt-6.1-sol')]
            for role in ('astra','sol'):
                request(prefix+'/agents/'+role+'/runs', 'POST', {'prompt':'Offline queue verification; no inference.'})
            deadline = time.monotonic()+45
            while time.monotonic()<deadline:
                state = request(prefix+'/agents')
                if all(a['runs'] and a['runs'][0]['status']=='failed' for a in state['agents']):
                    assert all('not signed in' in a['runs'][0]['error'] for a in state['agents'])
                    break
                time.sleep(.5)
            else:
                raise RuntimeError('Offline agent requests did not report the expected login requirement.')
            print('Astra/Sol supervisor queue and project-scoped app bridge passed without inference.', flush=True)

        if args.tools:
            dc('build', 'lean')
            dc('run', '--rm', '--no-deps', '-T', 'python', 'examples/check.py')
            dc('run', '--rm', '--no-deps', '-T', 'typst', 'compile', 'examples/hello.typ', 'output/typst.pdf')
            dc('run', '--rm', '--no-deps', '-T', 'texlive', 'latexmk', '-pdf', '-interaction=nonstopmode',
               '-halt-on-error', '-outdir=/work/output', 'examples/hello.tex')
            dc('run', '--rm', '--no-deps', '-T', 'lean', 'examples/Proof.lean')
            dc('run', '--rm', '--no-deps', '-T', 'sagemath', 'examples/check.sage')
            for filename in ('typst.pdf', 'hello.pdf'):
                assert (workspace/'output'/filename).read_bytes().startswith(b'%PDF-')
            print('All research toolchains passed; PDFs compiled without visual inspection.', flush=True)
        print('Check workspace: '+str(workspace), flush=True)
    finally:
        # This fresh random project owns only disposable test containers/volumes.
        dc('down', '--volumes', '--remove-orphans')


if __name__=='__main__':
    main()
