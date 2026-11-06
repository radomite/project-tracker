"""Persistent project agents, cluster permissions, and a leased Codex work queue.

Only the trusted Compose supervisor uses internal routes. Model-facing tools have
no project selector: the active lease determines the project and agent identity.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from file_api import (checked_path, repo_lock, ensure_repo, entries, find_entry,
                      disk_path, clean_repo, save_file_bytes)

ROLES = {
    'astra': ('Astra', 'Research', 'gpt-6-astra'),
    'sol': ('Sol', 'Editing', 'gpt-6.1-sol'),
}


def ensure_agents(db, project_id):
    for role in ROLES:
        db.execute('INSERT OR IGNORE INTO project_agents(project_id,role,identity) VALUES (?,?,?)',
                   (project_id, role, secrets.token_hex(16)))


def migrate_agents(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS project_agents (
      id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
      role TEXT NOT NULL CHECK(role IN ('astra','sol')), UNIQUE(project_id,role));
    CREATE TABLE IF NOT EXISTS agent_clusters (
      id INTEGER PRIMARY KEY, name TEXT NOT NULL, owner_id INTEGER NOT NULL REFERENCES users(id));
    CREATE TABLE IF NOT EXISTS agent_cluster_projects (
      cluster_id INTEGER NOT NULL REFERENCES agent_clusters(id),
      project_id INTEGER NOT NULL REFERENCES projects(id),
      cluster_approved INTEGER NOT NULL DEFAULT 0, project_approved INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(cluster_id,project_id));
    CREATE TABLE IF NOT EXISTS agent_runs (
      id INTEGER PRIMARY KEY, agent_id INTEGER NOT NULL REFERENCES project_agents(id),
      requested_by INTEGER NOT NULL REFERENCES users(id), prompt TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'queued', output TEXT NOT NULL DEFAULT '',
      error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, finished_at TEXT,
      lease_hash TEXT, lease_until REAL, started_at TEXT);
    CREATE UNIQUE INDEX IF NOT EXISTS one_active_agent_run ON agent_runs(agent_id)
      WHERE status IN ('queued','running');
    CREATE TABLE IF NOT EXISTS agent_mail (
      id INTEGER PRIMARY KEY, sender_id INTEGER NOT NULL REFERENCES project_agents(id),
      recipient_id INTEGER NOT NULL REFERENCES project_agents(id),
      body TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS agent_permission_events (
      id INTEGER PRIMARY KEY, cluster_id INTEGER NOT NULL, project_id INTEGER,
      actor_id INTEGER NOT NULL, action TEXT NOT NULL, created_at TEXT NOT NULL);
    ''')
    if 'identity' not in {row['name'] for row in db.execute('PRAGMA table_info(project_agents)')}:
        db.execute('ALTER TABLE project_agents ADD COLUMN identity TEXT')
    for row in db.execute('SELECT id FROM project_agents WHERE identity IS NULL').fetchall():
        db.execute('UPDATE project_agents SET identity=? WHERE id=?',(secrets.token_hex(16),row['id']))
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS agent_identity ON project_agents(identity)')
    for row in db.execute('SELECT id FROM projects').fetchall():
        ensure_agents(db, row['id'])


def can_talk(db, source, target):
    if source == target:
        return False
    return bool(db.execute('''SELECT 1 FROM project_agents a JOIN project_agents b ON b.id=?
      WHERE a.id=? AND (a.project_id=b.project_id OR EXISTS (
        SELECT 1 FROM agent_cluster_projects x JOIN agent_cluster_projects y ON y.cluster_id=x.cluster_id
        WHERE x.project_id=a.project_id AND y.project_id=b.project_id
          AND x.cluster_approved=1 AND x.project_approved=1
          AND y.cluster_approved=1 AND y.project_approved=1))''', (target, source)).fetchone())


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class RunInput(Model):
    prompt: str = Field(min_length=1, max_length=50000)


class ClusterInput(Model):
    name: str = Field(min_length=1, max_length=100)


class FinishInput(Model):
    status: Literal['completed', 'failed']
    output: str = Field(default='', max_length=100000)
    error: str = Field(default='', max_length=2000)


class ToolInput(Model):
    operation: Literal['context', 'files', 'read_file', 'write_file', 'peers', 'send', 'inbox']
    arguments: dict = Field(default_factory=dict)


def install_agents(app, *, root, DB, Person, project_access, human, now):
    def available():
        path = os.environ.get('RESEARCH_AGENT_SECRET_FILE', '')
        return bool(path and Path(path).is_file())

    def service(request):
        if not available():
            raise HTTPException(503, 'Codex service is not configured. Start the agents Compose profile after storage recovery.')
        expected = Path(os.environ['RESEARCH_AGENT_SECRET_FILE']).read_text(encoding='utf-8').strip()
        scheme,_,actual=request.headers.get('authorization', '').partition(' ')
        if scheme.casefold()!='bearer' or len(expected)<32 or not hmac.compare_digest(expected.encode(),actual.encode()):
            raise HTTPException(401, 'Invalid Codex service credential.')

    app.state.authenticate_service=service

    def agent(db, pid, role):
        row = db.execute('SELECT * FROM project_agents WHERE project_id=? AND role=?', (pid, role)).fetchone()
        if not row:
            raise HTTPException(404, 'Agent not found.')
        return row

    def expire(db):
        db.execute("UPDATE agent_runs SET status='failed',error='Codex worker disconnected; run was not replayed.',"
                   'finished_at=?,lease_hash=NULL WHERE status=\'running\' AND lease_until<?', (now(), time.time()))

    def runs(db, aid):
        return [dict(row) for row in db.execute('SELECT id,prompt,status,output,error,created_at,finished_at '
                                              'FROM agent_runs WHERE agent_id=? ORDER BY id DESC LIMIT 30', (aid,))]

    def cluster_event(db, cid, pid, person, action):
        db.execute('INSERT INTO agent_permission_events(cluster_id,project_id,actor_id,action,created_at) '
                   'VALUES (?,?,?,?,?)', (cid, pid, person['user_id'], action, now()))

    @app.get('/api/v1/projects/{project_id}/agents')
    def list_agents(project_id: int, person: Person, db: DB):
        human(person)
        project_access(db, project_id, person)
        ensure_agents(db, project_id)
        expire(db)
        return {'available': available(), 'online': time.time()-getattr(app.state,'agent_seen',0)<30, 'agents': [
            {**dict(row), 'name': ROLES[row['role']][0], 'purpose': ROLES[row['role']][1],
             'model': ROLES[row['role']][2], 'runs': runs(db, row['id'])}
            for row in db.execute('SELECT * FROM project_agents WHERE project_id=? ORDER BY id', (project_id,))]}

    @app.get('/api/v1/projects/{project_id}/agents/{role}/mail')
    def mail(project_id: int, role: str, person: Person, db: DB):
        human(person)
        project_access(db, project_id, person)
        aid = agent(db, project_id, role)['id']
        return [dict(m) for m in db.execute('''SELECT m.*,s.role AS sender_role,sp.title AS sender_project,
          r.role AS recipient_role,rp.title AS recipient_project FROM agent_mail m
          JOIN project_agents s ON s.id=m.sender_id JOIN projects sp ON sp.id=s.project_id
          JOIN project_agents r ON r.id=m.recipient_id JOIN projects rp ON rp.id=r.project_id
          WHERE sender_id=? OR recipient_id=? ORDER BY m.id DESC LIMIT 50''',(aid,aid))
          if can_talk(db,m['sender_id'],m['recipient_id'])]

    @app.post('/api/v1/projects/{project_id}/agents/{role}/runs', status_code=201)
    def start_run(project_id: int, role: str, payload: RunInput, person: Person, db: DB):
        human(person)
        project_access(db, project_id, person)
        aid = agent(db, project_id, role)['id']
        if not available():
            raise HTTPException(503, 'Codex service is not configured yet.')
        expire(db)
        try:
            rid = db.execute('INSERT INTO agent_runs(agent_id,requested_by,prompt,created_at) VALUES (?,?,?,?)',
                             (aid, person['user_id'], payload.prompt, now())).lastrowid
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'This agent already has an active request.')
        return {'id': rid, 'status': 'queued'}

    @app.delete('/api/v1/projects/{project_id}/agents/{role}/runs/{run_id}')
    def cancel_run(project_id: int, role: str, run_id: int, person: Person, db: DB):
        human(person)
        project_access(db, project_id, person)
        aid = agent(db, project_id, role)['id']
        row = db.execute('SELECT * FROM agent_runs WHERE id=? AND agent_id=?', (run_id, aid)).fetchone()
        if not row:
            raise HTTPException(404, 'Run not found.')
        if row['status'] in ('queued', 'running'):
            db.execute("UPDATE agent_runs SET status='cancelled',lease_hash=NULL,finished_at=? WHERE id=?", (now(), run_id))
        return {'ok': True}

    @app.get('/api/v1/agent-clusters')
    def clusters(person: Person, db: DB):
        human(person)
        result = []
        for row in db.execute('''SELECT DISTINCT c.* FROM agent_clusters c
          LEFT JOIN agent_cluster_projects cp ON cp.cluster_id=c.id
          LEFT JOIN members m ON m.project_id=cp.project_id AND m.user_id=?
          WHERE c.owner_id=? OR m.user_id IS NOT NULL ORDER BY c.name,c.id''', (person['user_id'], person['user_id'])):
            # A cluster assignment explicitly discloses its project names to cluster participants.
            projects = [dict(p) for p in db.execute('''SELECT p.id,p.title,cp.cluster_approved,cp.project_approved,
              p.owner_id=? AS is_owner FROM agent_cluster_projects cp JOIN projects p ON p.id=cp.project_id
              WHERE cp.cluster_id=? ORDER BY p.title''', (person['user_id'], row['id']))]
            result.append({**dict(row), 'is_owner': row['owner_id']==person['user_id'], 'projects': projects})
        return result

    @app.post('/api/v1/agent-clusters', status_code=201)
    def create_cluster(payload: ClusterInput, person: Person, db: DB):
        human(person)
        cid = db.execute('INSERT INTO agent_clusters(name,owner_id) VALUES (?,?)', (payload.name, person['user_id'])).lastrowid
        cluster_event(db, cid, None, person, 'create')
        return {'id': cid, 'name': payload.name}

    @app.put('/api/v1/agent-clusters/{cluster_id}/projects/{project_id}')
    def join_cluster(cluster_id: int, project_id: int, person: Person, db: DB):
        human(person)
        project = project_access(db, project_id, person)
        cluster = db.execute('SELECT * FROM agent_clusters WHERE id=?', (cluster_id,)).fetchone()
        if not cluster:
            raise HTTPException(404, 'Cluster not found.')
        co, po = cluster['owner_id']==person['user_id'], project['owner_id']==person['user_id']
        pending = db.execute('SELECT 1 FROM agent_cluster_projects WHERE cluster_id=? AND project_id=?', (cluster_id, project_id)).fetchone()
        if not co and (not po or not pending):
            raise HTTPException(403, 'The cluster owner must invite this project; its owner must also approve.')
        db.execute('''INSERT INTO agent_cluster_projects VALUES (?,?,?,?)
          ON CONFLICT(cluster_id,project_id) DO UPDATE SET
          cluster_approved=MAX(cluster_approved,excluded.cluster_approved),
          project_approved=MAX(project_approved,excluded.project_approved)''', (cluster_id, project_id, int(co), int(po)))
        cluster_event(db, cluster_id, project_id, person, 'approve')
        return {'ok': True}

    @app.delete('/api/v1/agent-clusters/{cluster_id}/projects/{project_id}')
    def leave_cluster(cluster_id: int, project_id: int, person: Person, db: DB):
        human(person)
        row = db.execute('SELECT c.owner_id AS co,p.owner_id AS po FROM agent_clusters c '
                         'JOIN projects p ON p.id=? WHERE c.id=?', (project_id, cluster_id)).fetchone()
        if not row or person['user_id'] not in (row['co'], row['po']):
            raise HTTPException(403, 'A project or cluster owner must remove this assignment.')
        db.execute('DELETE FROM agent_cluster_projects WHERE cluster_id=? AND project_id=?', (cluster_id, project_id))
        cluster_event(db, cluster_id, project_id, person, 'remove')
        return {'ok': True}

    @app.post('/internal/agents/claim')
    def claim(request: Request, db: DB):
        service(request)
        app.state.agent_seen = time.time()
        db.execute('BEGIN IMMEDIATE')
        expire(db)
        # A removed member's queued work must never acquire a fresh capability.
        db.execute("UPDATE agent_runs SET status='cancelled',finished_at=? WHERE status='queued' AND NOT EXISTS ("
                   'SELECT 1 FROM project_agents a JOIN members m ON m.project_id=a.project_id '
                   'WHERE a.id=agent_runs.agent_id AND m.user_id=agent_runs.requested_by)', (now(),))
        row = db.execute("SELECT r.*,a.project_id,a.role,a.identity FROM agent_runs r JOIN project_agents a ON a.id=r.agent_id "
                         "WHERE r.status='queued' ORDER BY r.id LIMIT 1").fetchone()
        if not row:
            return {'job': None}
        token = secrets.token_urlsafe(48)
        db.execute("UPDATE agent_runs SET status='running',lease_hash=?,lease_until=?,started_at=? WHERE id=?",
                   (hashlib.sha256(token.encode()).hexdigest(), time.time()+90, now(), row['id']))
        return {'job': {'id':row['id'], 'agent_id':row['agent_id'], 'project_id':row['project_id'],
                        'identity':row['identity'], 'role':row['role'], 'model':ROLES[row['role']][2],
                        'prompt':row['prompt'], 'lease':token}}

    def leased(request, db, rid):
        service(request)
        row = db.execute('SELECT r.*,a.project_id,a.role,p.owner_id FROM agent_runs r '
                         'JOIN project_agents a ON a.id=r.agent_id JOIN projects p ON p.id=a.project_id '
                         'WHERE r.id=?', (rid,)).fetchone()
        value = hashlib.sha256(request.headers.get('x-agent-lease', '').encode()).hexdigest()
        if (not row or row['status']!='running' or not row['lease_hash'] or row['lease_until']<time.time()
                or not hmac.compare_digest(row['lease_hash'], value)):
            raise HTTPException(403, 'Run lease is no longer active.')
        if not db.execute('SELECT 1 FROM members WHERE project_id=? AND user_id=?',
                          (row['project_id'], row['requested_by'])).fetchone():
            raise HTTPException(403, 'Requester no longer has project access.')
        return row

    @app.post('/internal/agents/runs/{run_id}/heartbeat')
    def heartbeat(run_id: int, request: Request, db: DB):
        leased(request, db, run_id)
        db.execute('UPDATE agent_runs SET lease_until=? WHERE id=?', (time.time()+90, run_id))
        return {'ok': True}

    @app.post('/internal/agents/runs/{run_id}/finish')
    def finish(run_id: int, payload: FinishInput, request: Request, db: DB):
        leased(request, db, run_id)
        db.execute('UPDATE agent_runs SET status=?,output=?,error=?,finished_at=?,lease_hash=NULL WHERE id=?',
                   (payload.status, payload.output, payload.error, now(), run_id))
        return {'ok': True}

    @app.post('/internal/agents/runs/{run_id}/tool')
    def tool(run_id: int, payload: ToolInput, request: Request, db: DB):
        run = leased(request, db, run_id)
        pid, aid, args, op = run['project_id'], run['agent_id'], payload.arguments, payload.operation
        allowed = {'context':set(), 'files':set(), 'read_file':{'path'},
                   'write_file':{'path','text','etag'}, 'peers':set(), 'send':{'recipient_id','body'}, 'inbox':set()}
        if set(args)-allowed[op]:
            raise HTTPException(422, 'Unexpected tool arguments.')
        if op=='context':
            p = dict(db.execute('SELECT id,title,objective,description FROM projects WHERE id=?', (pid,)).fetchone())
            p['messages'] = [dict(m) for m in db.execute('SELECT id,topic_id,title,body,tags,created_at FROM items '
                'WHERE project_id=? AND archived=0 ORDER BY id DESC LIMIT 100', (pid,))]
            p['questions'] = [dict(q) for q in db.execute('SELECT body FROM dashboard_questions WHERE project_id=? ORDER BY position,id', (pid,))]
            return p
        if op=='peers':
            return [dict(a) for a in db.execute('SELECT a.id,a.project_id,a.role,p.title AS project_title '
                    'FROM project_agents a JOIN projects p ON p.id=a.project_id') if can_talk(db, aid, a['id'])]
        if op=='send':
            target, body = args.get('recipient_id'), args.get('body')
            if type(target)!=int or not isinstance(body,str) or not 1<=len(body.strip())<=20000:
                raise HTTPException(422, 'Provide a recipient_id and a message of at most 20000 characters.')
            if not can_talk(db, aid, target):
                raise HTTPException(403, 'These agents do not share a project or an approved cluster.')
            mid = db.execute('INSERT INTO agent_mail(sender_id,recipient_id,body,created_at) VALUES (?,?,?,?)',
                             (aid, target, body, now())).lastrowid
            return {'id': mid, 'delivered': True}
        if op=='inbox':
            # Check permissions again when reading: removal also hides unread old mail.
            return [dict(m) for m in db.execute('SELECT m.*,a.role,a.project_id FROM agent_mail m '
                    'JOIN project_agents a ON a.id=m.sender_id WHERE recipient_id=? ORDER BY m.id DESC LIMIT 100', (aid,))
                    if can_talk(db, aid, m['sender_id'])]
        if op!='files' and not isinstance(args.get('path'),str):
            raise HTTPException(422, 'Provide a relative file path.')
        path = checked_path(args.get('path','')) if op!='files' else None
        with repo_lock(root, pid):
            repo = ensure_repo(root, pid)
            tree, _ = entries(repo)
            if op=='files':
                return tree
            current = find_entry(tree, path)
            if op=='read_file':
                if not current or current['kind']!='file':
                    raise HTTPException(404, 'File not found.')
                if current['size']>2*1024*1024:
                    raise HTTPException(413, 'Use a text file of at most 2 MiB.')
                try:
                    return {**current, 'text':disk_path(repo,path).read_text(encoding='utf-8')}
                except UnicodeDecodeError:
                    raise HTTPException(422, 'This tool reads UTF-8 text files.')
            text = args.get('text')
            if not isinstance(text,str) or len(text.encode())>2*1024*1024:
                raise HTTPException(422, 'Provide text of at most 2 MiB.')
            if current and (current['kind']!='file' or args.get('etag')!=current['etag']):
                raise HTTPException(409, 'Read the latest file and supply its etag before editing.')
            if not current and args.get('etag'):
                raise HTTPException(409, 'The file has been removed.')
            clean_repo(repo)
            person = {'name':ROLES[run['role']][0], 'actor':f'project-agent:{aid}',
                      'kind':'agent', 'user_id':run['owner_id'], 'agent_id':None}
            save_file_bytes(repo,path,text.encode('utf-8'),person)
            return find_entry(entries(repo)[0],path)
