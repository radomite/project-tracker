"""Project files backed by Git, including authenticated Git smart HTTP."""
import asyncio
import base64
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import threading
import unicodedata
from urllib.parse import quote

from fastapi import HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_PACK_BYTES = 256 * 1024 * 1024
GIT = shutil.which('git')
_locks = {}
_locks_guard = threading.Lock()


def valid_path(value):
    value = unicodedata.normalize('NFC', value)
    if not value or len(value) > 1000 or value.startswith('/') or '\\' in value:
        raise ValueError('Use a relative folder/file path with forward slashes.')
    for part in value.split('/'):
        if (not part or part in ('.', '..') or part.casefold() == '.git'
                or part.endswith((' ', '.')) or len(part) > 200
                or any(ord(c) < 32 or c in '<>:"|?*' for c in part)
                or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', part)):
            raise ValueError('Choose a portable file name without reserved names or path traversal.')
    return value


def checked_path(value):
    try:
        return valid_path(value)
    except ValueError as error:
        raise HTTPException(422, str(error))


def git(repo, *args, data=None, check=True, env=None):
    if not GIT:
        raise HTTPException(503, 'Git is not installed on the server.')
    result = subprocess.run([GIT, '-C', str(repo), *args], input=data, capture_output=True,
                            env=env, timeout=120)
    if check and result.returncode:
        raise HTTPException(409, 'Git could not complete the operation: ' +
                            result.stderr.decode('utf-8', errors='replace')[-1500:])
    return result


def repo_lock(root, pid):
    key = (str(root), pid)
    with _locks_guard:
        return _locks.setdefault(key, threading.RLock())


def ensure_repo(root, pid):
    repo = root / str(pid)
    if not (repo / '.git' / 'HEAD').exists():
        repo.mkdir(parents=True, exist_ok=True)
        git(repo, 'init', '--initial-branch=main')
        for key, value in {
            'user.name':'Project files', 'user.email':'files@localhost',
            'core.autocrlf':'false', 'core.symlinks':'false', 'commit.gpgsign':'false',
            'receive.denyCurrentBranch':'updateInstead', 'receive.denyNonFastForwards':'true',
            'receive.denyDeleteCurrent':'true', 'http.receivepack':'true',
            'http.getanyfile':'false',
            'core.hooksPath':str((repo / '.git' / 'hooks').resolve()).replace('\\','/'),
        }.items():
            git(repo, 'config', key, value)
        git(repo, 'commit', '--allow-empty', '-m', 'Initialize project files')
    hook = repo / '.git' / 'hooks' / 'pre-receive'
    # Existing repositories may have been copied from Windows or another mount.
    hooks_path = str(hook.parent.resolve()).replace('\\', '/')
    if git(repo, 'config', '--get', 'core.hooksPath', check=False).stdout.decode().strip() != hooks_path:
        git(repo, 'config', 'core.hooksPath', hooks_path)
    # The hook lives outside the tracked tree and validates every pushed tree.
    command = ('#!/bin/sh\nexec ' + shlex.quote(sys.executable.replace('\\','/')) +
               ' ' + shlex.quote(str(Path(__file__).resolve()).replace('\\','/')) + ' --check-push\n')
    if not hook.exists() or hook.read_text(encoding='utf-8') != command:
        hook.write_text(command, encoding='utf-8', newline='\n')
        hook.chmod(0o755)
    recover_file_save(repo)
    return repo


def entries(repo):
    head = git(repo, 'rev-parse', 'HEAD').stdout.decode().strip()
    tree = git(repo, 'write-tree').stdout.decode().strip()
    result, folders = [], set()
    for record in git(repo, 'ls-tree', '-rlz', tree).stdout.split(b'\0'):
        if not record:
            continue
        metadata, raw_path = record.split(b'\t', 1)
        mode, kind, oid, size = metadata.split()
        path = raw_path.decode('utf-8')
        if kind != b'blob' or mode not in (b'100644', b'100755'):
            continue
        parts = path.split('/')
        folders.update('/'.join(parts[:i]) for i in range(1, len(parts)))
        if parts[-1] == '.gitkeep' and int(size) == 0:
            continue
        result.append({'path':path, 'kind':'file', 'size':int(size),
                       'etag':'"blob:' + oid.decode() + '"'})
    result.extend({'path':path, 'kind':'folder', 'size':0, 'etag':'"tree:'+tree+'"'}
                  for path in folders)
    return sorted(result, key=lambda entry:entry['path'].casefold()), head


def disk_path(repo, path):
    path = checked_path(path)
    target = repo.joinpath(*path.split('/'))
    for candidate in [target, *target.parents]:
        if candidate == repo:
            break
        if candidate.is_symlink():
            raise HTTPException(422, 'Symbolic links are not supported in project files.')
    return target


def ensure_parents(repo, path):
    # Match the portable, case-insensitive tree rule enforced for Git pushes.
    for part in path.split('/')[:-1]:
        candidate = next((p for p in repo.iterdir() if p.name.casefold()==part.casefold()), None)
        if candidate is not None and (candidate.name != part or candidate.is_symlink() or not candidate.is_dir()):
            raise HTTPException(409, 'A parent path conflicts with an existing file or folder.')
        repo = repo / part
        repo.mkdir(exist_ok=True)


def clean_repo(repo):
    journal = local_journal(repo)
    expected = journal.get('tree') or git(repo, 'rev-parse', 'HEAD^{tree}').stdout.decode().strip()
    if (git(repo, 'diff', '--quiet', check=False).returncode
            or git(repo, 'ls-files', '--others', '--exclude-standard', '-z').stdout
            or git(repo, 'write-tree').stdout.decode().strip() != expected):
        raise HTTPException(409, 'Files changed outside the app. Reconcile the server working tree first.')


def local_journal(repo):
    path = repo / '.git' / 'browser-history.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'pending':[], 'batches':[]}


def save_journal(repo, journal):
    path = repo / '.git' / 'browser-history.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(journal, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def recover_file_save(repo):
    """Replay a write-through save before allowing another project operation."""
    operation = repo / '.git' / 'file-save.json'
    if not operation.exists():
        return
    saved = json.loads(operation.read_text(encoding='utf-8'))
    path = checked_path(saved['path'])
    ensure_parents(repo, path)
    temporary = repo / '.git' / 'file-save-bytes'
    temporary.write_bytes(base64.b64decode(saved['data']))
    temporary.replace(disk_path(repo, path))
    git(repo, 'add', '-f', '--', path)
    journal = saved['journal']
    tree = git(repo, 'write-tree').stdout.decode().strip()
    if tree != saved['before']:
        journal['tree'] = tree
        event = saved['event']
        existing = next((e for e in journal['pending'] if event.get('window_id') and
                         e.get('window_id') == event['window_id'] and not e.get('closed')), None)
        if existing:
            existing['files'] = sorted(set(existing['files'] + [path]))
            existing['message'] = 'Edit ' + ', '.join(existing['files'])
            existing['date'] = event['date']
        else:
            journal['pending'].append(event)
    save_journal(repo, journal)
    if saved.get('editor_documents') is not None:
        atomic_json(repo/'.git'/'editor-documents.json', saved['editor_documents'])
    operation.unlink()


def save_file_bytes(repo, path, data, person, *, window_id=None, editor_documents=None):
    """All content writes share durability, the index, and the pending history."""
    clean_repo(repo)
    # Reject invalid/case-conflicting paths before persisting a recovery record.
    # A rejected operation must not be replayed on every later repository access.
    disk_path(repo, path)
    ensure_parents(repo, path)
    journal = local_journal(repo)
    stamp = datetime.now(timezone.utc).isoformat(timespec='microseconds')
    event = {'author':person['name'], 'message':('Update ' if disk_path(repo,path).exists() else 'Add ')+path, 'date':stamp}
    if window_id:
        event.update(window_id=window_id, files=[path], started_at=stamp, closed=False,
                     message='Edit '+path, actor=person['actor'])
    atomic_json(repo/'.git'/'file-save.json', {
        'path':path, 'data':base64.b64encode(data).decode(), 'journal':journal,
        'before':git(repo, 'write-tree').stdout.decode().strip(), 'event':event,
        'editor_documents':editor_documents})
    recover_file_save(repo)


def close_edit_window(repo, window_id=None, reason='git-sync'):
    journal = local_journal(repo)
    changed = False
    for event in journal['pending']:
        if event.get('window_id') and not event.get('closed') and (window_id is None or event['window_id']==window_id):
            event.update(closed=True, ended_at=datetime.now(timezone.utc).isoformat(timespec='microseconds'),
                         close_reason=reason)
            changed = True
    if changed:
        save_journal(repo, journal)


def invalidate_editor_documents(repo, path):
    """A deleted/recreated path must never accept an older editor generation."""
    state_path=repo/'.git'/'editor-documents.json'
    if state_path.exists():
        states=json.loads(state_path.read_text(encoding='utf-8'))
        filtered={name:value for name,value in states.items() if name!=path and not name.startswith(path+'/')}
        if filtered!=states:
            atomic_json(state_path,filtered)


def record_local(repo, person, message):
    journal = local_journal(repo)
    before = journal.get('tree') or git(repo, 'rev-parse', 'HEAD^{tree}').stdout.decode().strip()
    git(repo, 'add', '-A', '-f', '--', '.')
    tree = git(repo, 'write-tree').stdout.decode().strip()
    if tree == before:
        return
    journal['tree'] = tree
    journal['pending'].append({'author':person['name'], 'message':message,
        'date':datetime.now(timezone.utc).isoformat(timespec='microseconds')})
    save_journal(repo, journal)


def commit_batch(repo, message=None):
    clean_repo(repo)
    close_edit_window(repo, reason='git-sync')
    journal = local_journal(repo)
    events = journal['pending']
    if not events:
        return None
    title = message or 'Update project files ('+str(len(events))+' changes)'
    oid = None
    if git(repo, 'diff', '--cached', '--quiet', check=False).returncode:
        name = re.sub(r'[\r\n<>]', '', events[-1]['author']) or 'Project collaborator'
        git(repo, '-c', 'user.name='+name, 'commit', '-m', title)
        oid = git(repo, 'rev-parse', 'HEAD').stdout.decode().strip()
    journal['batches'].append({'commit':oid, 'message':title if oid else 'Local changes reverted',
        'author':events[-1]['author'], 'date':datetime.now(timezone.utc).isoformat(timespec='microseconds'),
        'events':events})
    journal['pending'] = []
    journal.pop('tree', None)
    save_journal(repo, journal)
    return oid


def file_history(repo, limit=50):
    journal = local_journal(repo)
    batches = {batch['commit']:batch for batch in journal['batches'] if batch['commit']}
    refs = {}
    for line in git(repo, 'for-each-ref', '--format=%(objectname)%00%(*objectname)%00%(refname)',
                    'refs/heads', 'refs/remotes', 'refs/tags').stdout.decode('utf-8').splitlines():
        oid, peeled, full_name = line.split('\0')
        for prefix, kind in [('refs/heads/', 'branch'), ('refs/remotes/', 'remote'), ('refs/tags/', 'tag')]:
            if full_name.startswith(prefix):
                refs.setdefault(peeled or oid, []).append({'name':full_name[len(prefix):], 'kind':kind})
                break
    raw = git(repo, 'log', '--all', '--topo-order', '-z',
              '--format=%H%x00%P%x00%an%x00%cI%x00%s', '-'+str(limit+1)).stdout
    fields = raw.decode('utf-8', errors='replace').split('\0')
    history = []
    local_only = sorted((batch for batch in journal['batches'] if not batch['commit']),
                        key=lambda item:datetime.fromisoformat(item['date']), reverse=True)
    for index in range(0, len(fields)-1, 5):
        oid, parents, author, date, message = fields[index:index+5]
        # Insert local-only activity without changing the Git graph's topological order.
        while local_only and datetime.fromisoformat(local_only[0]['date']) >= datetime.fromisoformat(date):
            history.append({**local_only.pop(0), 'source':'local', 'parents':[], 'refs':[]})
        batch = batches.get(oid)
        history.append({'commit':oid, 'parents':parents.split(), 'refs':refs.get(oid, []),
            'author':author, 'date':date, 'message':message,
            'source':'browser' if batch else 'git', 'events':batch['events'] if batch else []})
    history.extend({**batch, 'source':'local', 'parents':[], 'refs':[]} for batch in local_only)
    return {'pending':journal['pending'], 'items':history[:limit],
            'has_more':len(history)>limit}


def check_expected(request, current):
    if request.headers.get('if-none-match') == '*':
        if current:
            raise HTTPException(412, 'That path already exists. Open it to replace the file.')
    elif request.headers.get('if-match'):
        if not current or request.headers['if-match'] != current['etag']:
            raise HTTPException(412, 'The file changed. Reload it before saving.')
    else:
        raise HTTPException(428, 'A file version or create-only precondition is required.')


def find_entry(tree, path):
    exact = next((e for e in tree if e['path']==path), None)
    if exact is None and any(e['path'].casefold()==path.casefold() for e in tree):
        raise HTTPException(409, 'That path already exists with different capitalization.')
    return exact


def import_notes(db, root):
    """One-time, non-destructive import; deleting a file never resurrects a note."""
    rows = db.execute('SELECT n.* FROM project_notes n LEFT JOIN file_note_imports f ON f.note_id=n.id '
                      'WHERE f.note_id IS NULL ORDER BY n.id').fetchall()
    for note in rows:
        pid = note['project_id']
        with repo_lock(root, pid):
            repo = ensure_repo(root, pid)
            clean_repo(repo)
            name = note['filename'] or (note['title']+'.md')
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', name).strip(' .')[:180] or 'note'
            try:
                valid_path(name)
            except ValueError:
                name = 'note-'+str(note['id'])+Path(name).suffix
            path, index = 'notes/'+name, 1
            tree, _ = entries(repo)
            while any(e['path'].casefold()==path.casefold() for e in tree):
                index += 1
                path = 'notes/'+Path(name).stem+' ('+str(index)+')'+Path(name).suffix
            ensure_parents(repo, path)
            disk_path(repo, path).write_bytes(note['content'] if note['content'] is not None else note['body'].encode('utf-8'))
            record_local(repo, {'name':'Notes import'}, 'Import existing note '+name)
            db.execute('INSERT INTO file_note_imports VALUES (?,?,?)', (note['id'], pid, path))


def migrate_files(db, root):
    db.execute('CREATE TABLE IF NOT EXISTS file_note_imports (note_id INTEGER PRIMARY KEY '
               'REFERENCES project_notes(id), project_id INTEGER NOT NULL REFERENCES projects(id), path TEXT NOT NULL)')
    import_notes(db, root)


def activity(root, pid):
    repo = root / str(pid)
    paths = [repo/'.git'/'logs'/'refs'/'heads'/'main', repo/'.git'/'browser-history.json']
    times = [path.stat().st_mtime for path in paths if path.exists()]
    return datetime.fromtimestamp(max(times), timezone.utc).isoformat(timespec='microseconds') if times else None


def search_files(root, pid, title, query):
    repo = root / str(pid)
    if not (repo/'.git'/'HEAD').exists():
        return []
    results = []
    with repo_lock(root, pid):
        for entry in entries(repo)[0]:
            if entry['kind']!='file':
                continue
            text = ''
            if entry['size'] <= 2*1024*1024:
                data = disk_path(repo,entry['path']).read_bytes()
                try:
                    if b'\0' not in data:
                        text = data.decode('utf-8')
                except UnicodeDecodeError:
                    pass
            if query.casefold() in entry['path'].casefold() or query.casefold() in text.casefold():
                results.append({'kind':'file','id':entry['path'],'file_path':entry['path'],
                    'project_id':pid,'project_title':title,'topic_id':None,'topic_title':'',
                    'title':entry['path'],'snippet':text[:300]})
    return results


def export_files(root, pid):
    repo = root / str(pid)
    if not (repo/'.git'/'HEAD').exists():
        return []
    with repo_lock(root,pid):
        return [{**entry, **({'content_base64':base64.b64encode(disk_path(repo,entry['path']).read_bytes()).decode()}
                             if entry['kind']=='file' else {})} for entry in entries(repo)[0]]


class FolderInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = Field(min_length=1, max_length=1000)


class MoveFileInput(FolderInput):
    new_path: str = Field(min_length=1, max_length=1000)


class CommitInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(default='', max_length=500)


def install_files(app, *, root, DB, Person, project_access, key_person, project_event):
    def repo_for(db, pid, person):
        project_access(db, pid, person)
        return ensure_repo(root, pid)

    def listing(repo, pid, request, history_limit=50):
        tree, head = entries(repo)
        return {'entries':tree, 'head':head, 'branch':'main', 'history':file_history(repo, history_limit), 'max_file_bytes':MAX_FILE_BYTES,
                'git_url':str(request.base_url).rstrip('/')+'/git/projects/'+str(pid)+'.git'}

    @app.get('/api/v1/projects/{project_id}/files')
    def list_files(project_id: int, request: Request, person: Person, db: DB, history_limit: int = Query(default=50, ge=1, le=500)):
        with repo_lock(root, project_id):
            result = listing(repo_for(db, project_id, person), project_id, request, history_limit)
            result['legacy_notes'] = {row['note_id']:row['path'] for row in db.execute(
                'SELECT note_id,path FROM file_note_imports WHERE project_id=?',(project_id,))}
            return result

    @app.post('/api/v1/projects/{project_id}/files/commit')
    def commit_files(project_id: int, payload: CommitInput, person: Person, db: DB):
        with repo_lock(root, project_id):
            repo = repo_for(db, project_id, person)
            oid = commit_batch(repo, payload.message.strip() or None)
            return {'commit':oid, 'history':file_history(repo)}

    @app.get('/api/v1/projects/{project_id}/files/content')
    def get_file(project_id: int, request: Request, person: Person, db: DB, path: str = Query(min_length=1)):
        path = checked_path(path)
        with repo_lock(root, project_id):
            repo = repo_for(db, project_id, person)
            current = find_entry(entries(repo)[0], path)
            if not current or current['kind']!='file':
                raise HTTPException(404, 'File not found.')
            data = disk_path(repo, path).read_bytes()
            return Response(data, media_type='application/octet-stream', headers={
                'ETag':current['etag'], 'Content-Disposition':"attachment; filename*=UTF-8''"+quote(Path(path).name,safe='')})

    @app.get('/api/v1/projects/{project_id}/files/preview')
    def preview(project_id: int, person: Person, db: DB, path: str = Query(min_length=1)):
        path = checked_path(path)
        with repo_lock(root, project_id):
            repo = repo_for(db, project_id, person)
            current = find_entry(entries(repo)[0], path)
            if not current or current['kind']!='file':
                raise HTTPException(404, 'File not found.')
            text = None
            if current['size'] <= 2*1024*1024:
                data = disk_path(repo, path).read_bytes()
                try:
                    if b'\0' not in data:
                        text = data.decode('utf-8')
                except UnicodeDecodeError:
                    pass
            return {**current, 'text':text}

    @app.put('/api/v1/projects/{project_id}/files/content')
    async def put_file(project_id: int, request: Request, person: Person, db: DB, path: str = Query(min_length=1)):
        path = checked_path(path)
        project_access(db, project_id, person)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>MAX_FILE_BYTES:
                raise HTTPException(413, 'Files are limited to 100 MiB each.')
        def save():
            with repo_lock(root, project_id):
                repo = repo_for(db, project_id, person)
                clean_repo(repo)
                current = find_entry(entries(repo)[0], path)
                check_expected(request, current)
                if current and current['kind']!='file':
                    raise HTTPException(409, 'That path is a folder.')
                save_file_bytes(repo, path, bytes(data), person)
                return find_entry(entries(repo)[0], path)
        return await asyncio.to_thread(save)

    @app.post('/api/v1/projects/{project_id}/files/folders', status_code=201)
    def create_folder(project_id: int, payload: FolderInput, request: Request, person: Person, db: DB):
        path = checked_path(payload.path.rstrip('/'))
        with repo_lock(root, project_id):
            repo = repo_for(db, project_id, person)
            clean_repo(repo)
            current = find_entry(entries(repo)[0], path)
            if current:
                raise HTTPException(409, 'That path already exists.')
            ensure_parents(repo, path+'/.gitkeep')
            (disk_path(repo, path)/'.gitkeep').write_bytes(b'')
            record_local(repo, person, 'Create folder '+path)
            return find_entry(entries(repo)[0], path)

    @app.patch('/api/v1/projects/{project_id}/files/entry')
    def move_file(project_id: int, payload: MoveFileInput, request: Request, person: Person, db: DB):
        path, target = checked_path(payload.path), checked_path(payload.new_path)
        if target==path or target.startswith(path+'/'):
            raise HTTPException(422, 'Choose a different path outside the source folder.')
        with repo_lock(root, project_id):
            repo = repo_for(db, project_id, person)
            clean_repo(repo)
            tree, _ = entries(repo)
            current = find_entry(tree, path)
            check_expected(request, current)
            if find_entry(tree, target):
                raise HTTPException(409, 'The destination already exists.')
            ensure_parents(repo, target)
            invalidate_editor_documents(repo, path)
            disk_path(repo, path).rename(disk_path(repo, target))
            record_local(repo, person, 'Move '+path+' to '+target)
            return find_entry(entries(repo)[0], target)

    @app.delete('/api/v1/projects/{project_id}/files/entry', status_code=204)
    def delete_file(project_id: int, request: Request, person: Person, db: DB, path: str = Query(min_length=1)):
        path = checked_path(path)
        with repo_lock(root, project_id):
            repo = repo_for(db, project_id, person)
            clean_repo(repo)
            current = find_entry(entries(repo)[0], path)
            check_expected(request, current)
            invalidate_editor_documents(repo, path)
            target = disk_path(repo, path)
            if current['kind']=='folder':
                children = list(target.iterdir())
                if any(p.name!='.gitkeep' or p.stat().st_size for p in children):
                    raise HTTPException(409, 'Move or delete the files in this folder first.')
                for child in children:
                    child.unlink()
                target.rmdir()
            else:
                target.unlink()
            record_local(repo, person, 'Delete '+path)
        return Response(status_code=204)

    @app.api_route('/git/projects/{project_id}.git/{git_path:path}', methods=['GET','POST'])
    async def git_remote(project_id: int, git_path: str, request: Request, db: DB):
        service = request.query_params.get('service')
        if (git_path=='info/refs' and request.method=='GET' and service in ('git-upload-pack','git-receive-pack')):
            write = service=='git-receive-pack'
        elif git_path in ('git-upload-pack','git-receive-pack') and request.method=='POST':
            write = git_path=='git-receive-pack'
        else:
            raise HTTPException(404, 'Git service not found.')
        authorization = request.headers.get('authorization','')
        token = ''
        if authorization.lower().startswith('bearer '):
            token = authorization[7:].strip()
        elif authorization.lower().startswith('basic '):
            try:
                token = base64.b64decode(authorization[6:],validate=True).decode('utf-8').split(':',1)[1]
            except (ValueError,UnicodeError,IndexError):
                pass
        if not token:
            raise HTTPException(401, 'Use a project key as the Git password.',
                                headers={'WWW-Authenticate':'Basic realm="Project Git"'})
        try:
            person = key_person(db, token, write=write)
        except HTTPException as error:
            if error.status_code==401:
                error.headers = {'WWW-Authenticate':'Basic realm="Project Git"'}
            raise
        project_access(db, project_id, person)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>MAX_PACK_BYTES:
                raise HTTPException(413, 'Git requests are limited to 256 MiB.')
        def serve():
            with repo_lock(root, project_id):
                repo = ensure_repo(root, project_id)
                commit_batch(repo)
                env = os.environ.copy()
                env.update({'GIT_PROJECT_ROOT':str(root.resolve()),'GIT_HTTP_EXPORT_ALL':'1',
                    'PATH_INFO':'/'+str(project_id)+'/.git/'+git_path,
                    'QUERY_STRING':request.url.query,'REQUEST_METHOD':request.method,
                    'CONTENT_TYPE':request.headers.get('content-type',''),
                    'CONTENT_LENGTH':str(len(data)),'REMOTE_USER':person['actor'],
                    'REMOTE_ADDR':request.client.host if request.client else '127.0.0.1',
                    'SERVER_PROTOCOL':'HTTP/1.1'})
                if request.headers.get('git-protocol'):
                    env['HTTP_GIT_PROTOCOL'] = request.headers['git-protocol']
                result = subprocess.run([GIT,'http-backend'],input=bytes(data),capture_output=True,env=env,timeout=180)
                output = result.stdout
                separator = b'\r\n\r\n' if b'\r\n\r\n' in output else b'\n\n'
                if separator not in output:
                    raise HTTPException(502, 'The Git service could not complete the request.')
                raw_headers, body = output.split(separator,1)
                headers, status = {}, 200
                for line in raw_headers.decode('latin-1').splitlines():
                    name, value = line.split(':',1)
                    if name.lower()=='status':
                        status = int(value.strip().split()[0])
                    else:
                        headers[name] = value.strip()
                return Response(body,status_code=status,headers=headers)
        return await asyncio.to_thread(serve)


def check_push():
    """Git pre-receive hook: validate names, file modes, and sizes before checkout."""
    try:
        for line in sys.stdin:
            old, new, ref = line.split()
            if set(new)=={'0'}:
                continue
            result = subprocess.run([GIT,'ls-tree','-rlz',new+'^{tree}'],capture_output=True,check=True)
            seen = set()
            for record in result.stdout.split(b'\0'):
                if not record:
                    continue
                metadata, raw_path = record.split(b'\t',1)
                mode, kind, oid, size = metadata.split()
                path = valid_path(raw_path.decode('utf-8'))
                if mode not in (b'100644',b'100755') or kind!=b'blob':
                    raise ValueError('Project files do not support symbolic links or submodules.')
                if int(size)>MAX_FILE_BYTES:
                    raise ValueError('Project files are limited to 100 MiB each.')
                parts = path.split('/')
                for i in range(1,len(parts)+1):
                    prefix = '/'.join(parts[:i])
                    key = prefix.casefold()
                    previous = next((name for name in seen if name.casefold()==key),None)
                    if previous is not None and previous!=prefix:
                        raise ValueError('Paths differing only in capitalization are not supported.')
                    seen.add(prefix)
        return 0
    except (ValueError,UnicodeError,subprocess.SubprocessError) as error:
        print(str(error),file=sys.stderr)
        return 1


if __name__=='__main__' and '--check-push' in sys.argv:
    sys.exit(check_push())
