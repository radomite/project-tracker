"""Offline Codex image checks; no inference, real login, or persistent volumes."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile

from codex_service import prepare_agent, Rpc, TOOLS


def main():
    if os.name!='posix' or os.geteuid()!=0:
        raise RuntimeError('Run inside the Codex image with its configured supervisor capabilities.')
    with tempfile.TemporaryDirectory(prefix='codex-check-') as folder:
        state = Path(folder)
        state.chmod(0o711)
        (state/'agents').mkdir(mode=0o711)
        (state/'control').mkdir(mode=0o700)
        (state/'login').mkdir(mode=0o700)
        # A syntactically valid dummy credential exercises copying/permissions.
        # It is removed before starting Codex and is never used for network access.
        (state/'login'/'auth.json').write_text(json.dumps({'OPENAI_API_KEY':'offline-test-not-a-real-key'}))
        first, uid_a = prepare_agent(state,'a'*32)
        second, uid_b = prepare_agent(state,'b'*32)
        for base,uid in ((first,uid_a),(second,uid_b)):
            secret = base/'work'/'private.txt'
            secret.write_text('Private agent context')
            os.chown(secret,uid,uid)
            secret.chmod(0o600)
            (base/'home'/'auth.json').unlink()
        controller = state/'control'/'service-token'
        controller.write_text('Private controller credential')
        code = '''from pathlib import Path
import sys
assert Path(sys.argv[1]).read_text()=='Private agent context'
for value in sys.argv[2:]:
 try: Path(value).read_text()
 except PermissionError: pass
 else: raise AssertionError('Read isolation failed: '+value)
'''
        for own,other,uid in ((first,second,uid_a),(second,first,uid_b)):
            subprocess.run([sys.executable,'-c',code,str(own/'work'/'private.txt'),
                            str(other/'work'/'private.txt'),str(controller)],
                           user=uid,group=uid,extra_groups=[],check=True)
        print('Distinct agent UIDs cannot read each other or controller credentials.',flush=True)

        env = {'PATH':os.environ['PATH'],'HOME':str(first/'home'),'CODEX_HOME':str(first/'home'),
               'TMPDIR':str(first/'tmp'),'LANG':'C.UTF-8'}
        config = {'model':'gpt-6-astra','cwd':str(first/'work'),
                  'approvalPolicy':'never','sandbox':'workspace-write'}

        def connect():
            process = subprocess.Popen(['codex','app-server','--listen','stdio://',
                '-c','cli_auth_credentials_store="file"','-c','mcp_servers={}'],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                cwd=first/'work',env=env,user=uid_a,group=uid_a,extra_groups=[],
                text=True,encoding='utf-8',start_new_session=True)
            rpc = Rpc(process,lambda _: (_ for _ in ()).throw(AssertionError('No tools/inference expected.')))
            rpc.call('initialize',{'clientInfo':{'name':'result_organizer_check','version':'0.1.0'},
                                   'capabilities':{'experimentalApi':True}})
            rpc.write({'method':'initialized','params':{}})
            return process,rpc

        def close(process):
            process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL)
                process.wait(timeout=10)
            process.stdout.close()

        process,rpc = connect()
        try:
            result = rpc.call('thread/start',{**config,'dynamicTools':TOOLS,
                            'developerInstructions':'Offline protocol verification. Do not start inference.'})
            thread_id = result['thread']['id']
        finally:
            close(process)
        process,rpc = connect()
        try:
            resumed = rpc.call('thread/resume',{**config,'threadId':thread_id,'excludeTurns':True})
            assert resumed['thread']['id']==thread_id
        finally:
            close(process)
        print('Real Codex initialization, dynamic-tool registration and thread resume passed without inference.',flush=True)

        # Compare an unsandboxed connection with the same command in Codex's
        # Linux workspace sandbox; a disabled sandbox cannot pass this check.
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0))
            listener.listen(2)
            port = listener.getsockname()[1]
            allowed = f'import socket; socket.create_connection(("127.0.0.1",{port}),timeout=2).close()'
            subprocess.run([sys.executable,'-c',allowed],user=uid_a,group=uid_a,extra_groups=[],check=True)
            denied = f'''import socket
try: socket.create_connection(('127.0.0.1',{port}),timeout=2)
except OSError: print('Sandbox network denied')
else: raise AssertionError('Sandbox allowed tool network access')
'''
            result = subprocess.run(['codex','sandbox','linux','--full-auto','--',sys.executable,'-c',denied],
                cwd=first/'work',env=env,user=uid_a,group=uid_a,extra_groups=[],capture_output=True,text=True,timeout=30)
            if result.returncode:
                raise RuntimeError('Codex Linux sandbox check failed: '+result.stderr[-2000:])
            assert 'Sandbox network denied' in result.stdout
        print('Real Codex Linux sandbox blocks tool network access.',flush=True)


if __name__=='__main__':
    main()
