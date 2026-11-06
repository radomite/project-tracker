"""Offline image smoke checks used before publishing; no inference or PDF review."""
import base64
import os
import subprocess
import sys

service=sys.argv[1]
if service=='app':
    os.chdir('/tmp')
    env={**os.environ,'PYTHONPATH':'/app','RESEARCH_DB':'/tmp/release-check.db'}
    subprocess.run([sys.executable,'-m','unittest','discover','-s','/app/tests','-p','test_*.py','-v'],env=env,check=True)
elif service=='latex':
    sys.path.insert(0,'/worker')
    from latex_worker import CompileRequest, compile_snapshot
    text=b'\\documentclass{article}\\begin{document}Release check.\\end{document}'
    result=compile_snapshot(CompileRequest(main='main.tex',files={'main.tex':base64.b64encode(text).decode()}))
    assert result['status']==0,result['log']
    assert base64.b64decode(result['pdf']).startswith(b'%PDF-')
    print('LaTeX compiles successfully; PDF header checked.')
elif service=='codex':
    subprocess.run(['codex','--version'],check=True)
    # CLI/package smoke only; isolation is tested separately by check_codex_container.py.
    subprocess.run([sys.executable,'-c','import httpx; import codex_service'],cwd='/service',env={**os.environ,'PYTHONPATH':'/service'},check=True)
else:
    raise SystemExit('Unknown service: '+service)
