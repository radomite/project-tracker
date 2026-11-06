"""Isolated pdfLaTeX/BibTeX worker. Receives snapshots, never mounts project data."""
import asyncio
import base64
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import tempfile
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

app=FastAPI(docs_url=None,redoc_url=None)
busy=asyncio.Semaphore(1)


class CompileRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    main:str=Field(min_length=1,max_length=1000)
    files:dict[str,str]=Field(max_length=4096)


def safe_path(path):
    if (not path or '\\' in path or ':' in path or path.startswith('/') or
            any(part in ('','.','..','.git') for part in path.split('/')) or
            any(ord(c)<32 for c in path)):
        raise ValueError('Invalid source path')
    return PurePosixPath(path)


def process_limits():
    import resource
    resource.setrlimit(resource.RLIMIT_FSIZE,(20*1024*1024,20*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU,(35,35))
    resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))


def compile_snapshot(payload):
    safe_path(payload.main)
    if not payload.main.lower().endswith('.tex') or payload.main not in payload.files:
        raise ValueError('Select a .tex main document present in the snapshot.')
    files={path:base64.b64decode(content,validate=True) for path,content in payload.files.items()}
    if sum(map(len,files.values()))>32*1024*1024:
        raise ValueError('Compilation snapshot exceeds 32 MiB.')
    deadline=time.monotonic()+60
    with tempfile.TemporaryDirectory(prefix='manuscript-') as temporary:
        root=Path(temporary);out=root/'__build';out.mkdir()
        for path,raw in files.items():
            parts=safe_path(path).parts
            if parts[0]=='__build':raise ValueError('The __build directory is reserved for compiler output.')
            dest=root.joinpath(*parts);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
            out.joinpath(*parts[:-1]).mkdir(parents=True,exist_ok=True)
        env={**os.environ,'HOME':str(root),'TEXMFOUTPUT':str(out),'openin_any':'p','openout_any':'p',
             'shell_escape':'f','TEXMFVAR':str(root/'texmf-var'),'TEXMFCONFIG':str(root/'texmf-config'),
             'BIBINPUTS':str(root)+'//:','BSTINPUTS':str(root)+'//:'}
        log_path=root/'compile-output.txt'
        def run(command,cwd=root):
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('LaTeX compilation exceeded 60 seconds.')
            with log_path.open('ab') as stream:
                process=subprocess.Popen(command,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
                                         start_new_session=True,preexec_fn=process_limits if os.name=='posix' else None)
                try:return process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    if os.name=='posix':os.killpg(process.pid,signal.SIGKILL)
                    else:process.kill()
                    process.wait()
                    raise TimeoutError('LaTeX compilation exceeded 60 seconds.')
        command=['pdflatex','-no-shell-escape','-halt-on-error','-interaction=nonstopmode','-file-line-error','-output-directory='+str(out),payload.main]
        result=run(command)
        stem=PurePosixPath(payload.main).stem
        aux=out/(stem+'.aux')
        if result==0 and aux.exists() and '\\bibdata' in aux.read_text(errors='replace'):
            result=run(['bibtex',stem],cwd=out)
        if result==0:result=run(command)
        if result==0:result=run(command)
        log=log_path.read_text(errors='replace')[-60000:]
        pdf=out/(stem+'.pdf')
        return {'status':result,'log':log,'pdf':base64.b64encode(pdf.read_bytes()).decode() if result==0 and pdf.exists() else None}


@app.get('/health')
def health():return {'status':'ok'}


@app.post('/compile')
async def compile_document(payload:CompileRequest):
    if busy.locked():raise HTTPException(429,'The LaTeX compiler is busy. Recompile in a moment.')
    async with busy:
        try:return await asyncio.to_thread(compile_snapshot,payload)
        except (ValueError,TimeoutError,OSError) as error:
            return {'status':1,'log':str(error),'pdf':None}
