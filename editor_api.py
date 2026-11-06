"""Authenticated collaborative editor, writing through the ordinary Git file model."""
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import io
import json
import os
import secrets
import time
from pathlib import Path
import zipfile
import httpx

from fastapi import HTTPException, Response, WebSocket, WebSocketDisconnect
from pycrdt import Doc, Text

from file_api import (atomic_json, checked_path, close_edit_window, disk_path, ensure_repo,
                      entries, find_entry, git, invalidate_editor_documents, local_journal, repo_lock, save_file_bytes)

MAX_TEXT = 2 * 1024 * 1024
MAX_UPDATE = 8 * 1024 * 1024


def b64(value):
    return base64.b64encode(value).decode()


def documents(repo):
    path = repo/'.git'/'editor-documents.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def document(repo, path):
    path = checked_path(path)
    item = find_entry(entries(repo)[0], path)
    if not item or item['kind']!='file':
        invalidate_editor_documents(repo, path)
        raise HTTPException(404, 'File was moved or deleted. Your draft has been preserved.')
    if item['size'] > MAX_TEXT:
        raise HTTPException(413, 'The source editor supports text files up to 2 MiB.')
    raw = disk_path(repo, path).read_bytes()
    try:
        text = raw.decode('utf-8')
        if '\0' in text:
            raise ValueError()
    except (UnicodeError, ValueError):
        raise HTTPException(422, 'Choose a UTF-8 text file.')
    stored = documents(repo)
    state = stored.get(path)
    if state is None or state['etag'] != item['etag']:
        doc = Doc({'source':Text(text)})
        state = {'generation':secrets.token_hex(16), 'update':b64(doc.get_update()), 'etag':item['etag']}
        stored[path] = state
        atomic_json(repo/'.git'/'editor-documents.json', stored)
    return state


def apply_update(repo, path, generation, encoded, person, window_id):
    state = document(repo, path)
    if state['generation'] != generation:
        raise HTTPException(409, 'The file changed outside this editor. Compare your draft before continuing.')
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_UPDATE:
            raise ValueError()
        doc = Doc()
        doc.apply_update(base64.b64decode(state['update']))
        source = doc.get('source', type=Text)
        doc.apply_update(raw)
        data = str(source).encode('utf-8')
        update = doc.get_update()
        if len(data)>MAX_TEXT or len(update)>MAX_UPDATE or b'\0' in data:
            raise ValueError()
    except Exception:
        raise HTTPException(422, 'The editor update is invalid or exceeds the source limit.')
    etag = '"blob:'+hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()+'"'
    state = {**state, 'update':b64(update), 'etag':etag}
    stored = documents(repo)
    stored[path] = state
    save_file_bytes(repo, path, data, person, window_id=window_id, editor_documents=stored)
    return state


class EditorHub:
    def __init__(self, root, connect, project_access):
        self.root, self.connect, self.project_access = root, connect, project_access
        self.peers = {}
        self.credentials = {}
        self.idle_seconds = max(1, float(os.environ.get('RESEARCH_EDITOR_IDLE_SECONDS', '120')))
        # Windows are summaries of a connection's activity; a server restart ends them.
        for repo in root.iterdir() if root.exists() else []:
            if (repo/'.git').is_dir():
                with repo_lock(root, int(repo.name)):
                    ensure_repo(root, int(repo.name))
                    close_edit_window(repo, reason='server-restart')

    def person(self, ws, pid, csrf, *, check_csrf=True):
        with self.connect() as db:
            token = ws.cookies.get('research_session', '')
            row = db.execute('SELECT s.*,u.name FROM sessions s JOIN users u ON u.id=s.user_id '
                             'WHERE s.token_hash=? AND s.expires_at>?',
                             (hashlib.sha256(token.encode()).hexdigest(), datetime.now(timezone.utc).isoformat())).fetchone()
            if not row or (check_csrf and (not isinstance(csrf,str) or not hmac.compare_digest(csrf.encode(),row['csrf'].encode()))):
                raise HTTPException(403, 'Your editor session expired. Sign in again.')
            who = {'user_id':row['user_id'], 'name':row['name'], 'kind':'human',
                   'actor':'human:'+str(row['user_id'])}
            self.project_access(db, pid, who)
            return who

    async def broadcast(self, pid, message):
        for peer in list(self.peers.get(pid, ())):
            try:
                self.person(peer,pid,self.credentials[peer])
                await asyncio.wait_for(peer.send_json(message), 3)
            except Exception:
                self.peers.get(pid, set()).discard(peer)


def install_editor(app, *, root, connect, DB, Person, project_access):
    hub = EditorHub(root, connect, project_access)
    app.state.editor = hub

    @app.get('/api/v1/editor/source')
    def editor_source(person: Person):
        """Corresponding application source, excluding all user files and secrets."""
        source_root=Path(__file__).resolve().parent
        output=io.BytesIO()
        paths=list(source_root.glob('*.py'))
        paths += list(source_root.glob('playwright*.js'))
        paths += [source_root/p for p in ('LICENSE','Dockerfile','compose.yaml','package.json','package-lock.json','requirements.txt','README.md','.dockerignore','.gitignore','.gitattributes','run.ps1','init.ps1')]
        for folder in ('editor-src','third-party','scripts','docker','tests','deploy','.github'):
            paths += [p for p in (source_root/folder).rglob('*') if p.is_file() and (p.name in ('Dockerfile','Caddyfile') or p.suffix in ('.py','.js','.mjs','.cjs','.sh','.ps1','.md','.json','.txt','.yaml','.yml','.lean')) and '__pycache__' not in p.parts]
        paths += [p for p in (source_root/'static').iterdir() if p.suffix in ('.js','.css','.html')]
        paths += [p for p in (source_root/'static/vendor').rglob('*') if p.is_file()]
        paths += [source_root/'third-party/texlyre/LICENSE']
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(set(paths)):
                if path.is_file():archive.write(path,path.relative_to(source_root).as_posix())
        return Response(output.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="research-editor-source.zip"'})

    @app.get('/api/v1/projects/{project_id}/editor/snapshot')
    def snapshot(project_id: int, person: Person, db: DB):
        project_access(db, project_id, person)
        with repo_lock(root, project_id):
            repo = ensure_repo(root, project_id)
            tree = git(repo, 'write-tree').stdout.decode().strip()
            files = entries(repo)[0]
            # One bounded response captures bytes atomically, including pending edits.
            if sum(e['size'] for e in files)>32*1024*1024:
                raise HTTPException(413, 'The browser compiler supports project snapshots up to 32 MiB.')
            return {'tree':tree, 'head':git(repo, 'rev-parse', 'HEAD').stdout.decode().strip(),
                    'idle_seconds':hub.idle_seconds,
                    'files':[{**e, 'content':b64(disk_path(repo, e['path']).read_bytes())}
                             for e in files if e['kind']=='file']}

    @app.post('/api/v1/projects/{project_id}/editor/latex')
    async def latex(project_id: int, payload: dict, person: Person, db: DB):
        project_access(db,project_id,person)
        main=checked_path(str(payload.get('main','')))
        if not main.lower().endswith('.tex'):
            raise HTTPException(422,'Select a LaTeX main document.')
        endpoint=os.environ.get('RESEARCH_LATEX_URL','').rstrip('/')
        if not endpoint:
            raise HTTPException(503,'The Docker LaTeX worker is not running. Start the app and latex services with Docker Compose.')
        captured=snapshot(project_id,person,db)
        sources={entry['path']:entry['content'] for entry in captured['files']}
        if main not in sources:raise HTTPException(404,'Main document not found.')
        try:
            async with httpx.AsyncClient(timeout=75,trust_env=False) as client:
                result=await client.post(endpoint+'/compile',json={'main':main,'files':sources})
            if result.status_code==429:raise HTTPException(429,'The LaTeX compiler is busy. Recompile in a moment.')
            result.raise_for_status()
            return {**result.json(),'tree':captured['tree']}
        except httpx.HTTPError:
            raise HTTPException(503,'The Docker LaTeX worker is unavailable. Source files remain saved.')

    @app.websocket('/api/v1/projects/{project_id}/editor/ws')
    async def editor_socket(ws: WebSocket, project_id: int):
        expected = os.environ.get('RESEARCH_PUBLIC_ORIGIN', '').rstrip('/') or str(ws.url).split('/api/')[0].replace('ws://','http://').replace('wss://','https://')
        if ws.headers.get('origin') != expected:
            await ws.close(code=1008)
            return
        try:
            hub.person(ws, project_id, '', check_csrf=False)
        except HTTPException:
            await ws.close(code=1008)
            return
        await ws.accept()
        window_id, active_path, generation = None, None, None
        last_activity = time.monotonic()
        last_poll = 0
        last_transport = time.monotonic()
        csrf = ''

        def finish(reason):
            nonlocal window_id
            if window_id:
                with repo_lock(root, project_id):
                    close_edit_window(ensure_repo(root, project_id), window_id, reason)
                window_id = None

        try:
            hello = await asyncio.wait_for(ws.receive_json(), 10)
            csrf = hello.get('csrf', '')
            person = hub.person(ws, project_id, csrf)
            hub.peers.setdefault(project_id, set()).add(ws)
            hub.credentials[ws]=csrf
            await ws.send_json({'type':'ready', 'idle_seconds':hub.idle_seconds})
            while True:
                person = hub.person(ws, project_id, csrf)
                if window_id and time.monotonic()-last_activity >= hub.idle_seconds:
                    finish('idle')
                    await ws.send_json({'type':'window-ended', 'reason':'idle'})
                if time.monotonic()-last_transport > 35:
                    break
                try:
                    message = await asyncio.wait_for(ws.receive_json(), 1)
                except asyncio.TimeoutError:
                    message = {'type':'tick'}
                last_transport = time.monotonic() if message['type']!='tick' else last_transport
                kind = message['type']
                if kind=='join':
                    active_path = checked_path(message.get('path',''))
                    with repo_lock(root, project_id):
                        state = document(ensure_repo(root, project_id), active_path)
                    generation = state['generation']
                    await ws.send_json({'type':'document', 'path':active_path, **state})
                elif kind=='update':
                    path = checked_path(message.get('path',''))
                    with repo_lock(root, project_id):
                        repo = ensure_repo(root, project_id)
                        # A Git connection may have closed/committed the preceding window.
                        if window_id and not any(e.get('window_id')==window_id and not e.get('closed') for e in local_journal(repo)['pending']):
                            window_id = None
                        window_id = window_id or secrets.token_hex(16)
                        try:
                            state = apply_update(repo, path, message.get('generation'), message.get('update',''), person, window_id)
                        except HTTPException as error:
                            await ws.send_json({'type':'conflict', 'path':path, 'message':error.detail})
                            continue
                    last_activity = time.monotonic()
                    await hub.broadcast(project_id, {'type':'update', 'path':path, **state})
                    await ws.send_json({'type':'saved', 'path':path, 'seq':message.get('seq'), 'etag':state['etag']})
                elif kind=='activity':
                    last_activity = time.monotonic()
                elif kind=='end-window':
                    finish('focus' if message.get('reason')=='focus' else 'navigation')
                    await ws.send_json({'type':'window-ended', 'reason':message.get('reason')})
                if time.monotonic()-last_poll>3:
                    last_poll = time.monotonic()
                    await ws.send_json({'type':'ping'})
                    with repo_lock(root, project_id):
                        tree = git(ensure_repo(root,project_id),'write-tree').stdout.decode().strip()
                    await ws.send_json({'type':'workspace','tree':tree})
                    if active_path:
                        try:
                            with repo_lock(root, project_id):
                                state = document(ensure_repo(root, project_id), active_path)
                            if generation != state['generation']:
                                generation = state['generation']
                                await ws.send_json({'type':'document', 'path':active_path, **state})
                        except HTTPException as error:
                            await ws.send_json({'type':'conflict', 'path':active_path, 'message':error.detail})
        except (WebSocketDisconnect, asyncio.TimeoutError, RuntimeError):
            pass
        except (HTTPException, ValueError, KeyError, TypeError) as error:
            try:
                await ws.send_json({'type':'error', 'message':getattr(error,'detail','Invalid editor request.')})
                await ws.close(code=1008)
            except RuntimeError:
                pass
        finally:
            hub.peers.get(project_id, set()).discard(ws)
            hub.credentials.pop(ws,None)
            finish('disconnect')
