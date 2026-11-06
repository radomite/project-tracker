"""Local research notebook. Run with: python -m uvicorn app:app --reload."""
import base64
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from topic_api import ensure_general, install_topics, migrate_topics, topic_export, unread_count
from project_questions import migrate_questions, list_questions, install_questions
from file_api import migrate_files, install_files, activity as file_activity, export_files
from editor_api import install_editor
from project_agents import migrate_agents, ensure_agents, install_agents

ROOT = Path(__file__).resolve().parent
Kind = Literal['question', 'solution', 'technique', 'observation', 'experiment', 'note']
State = Literal['open', 'in_progress', 'closed']
Assessment = Literal['unreviewed', 'supported', 'refuted']
Password = Annotated[str, StringConstraints(strip_whitespace=False)]


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f'{salt}:{value}'


def password_matches(password, stored):
    return hmac.compare_digest(password_hash(password, stored.split(':')[0]), stored)


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


def person_name(value):
    if not any(c.isalpha() for c in value) or any(c in value for c in '@<>') or any(ord(c)<32 for c in value):
        raise ValueError('Enter your name, not an email address or a number.')
    return ' '.join(value.split())


class Login(Model):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    password: Password = Field(min_length=1, max_length=1024)

    @field_validator('name')
    @classmethod
    def normalize_name(cls, value):
        return person_name(value) if value is not None else value

    @field_validator('email')
    @classmethod
    def normalize_email(cls, value):
        value = value.casefold()
        if '@' not in value or any(c.isspace() for c in value):
            raise ValueError('Enter a valid email address.')
        return value

class Setup(Login):
    name: str = Field(min_length=1, max_length=100)
    password: Password = Field(min_length=10, max_length=1024)
    sample_projects: bool = True
    setup_token: Password = Field(default='', max_length=256)


class Registration(Login):
    name: str = Field(min_length=1, max_length=100)
    password: Password = Field(min_length=10, max_length=1024)
    token: str = Field(min_length=20, max_length=200)


class ProjectInput(Model):
    title: str = Field(min_length=1, max_length=160)
    objective: str = Field(default='', max_length=3000)
    description: str = Field(default='', max_length=10000)
    collaborator_emails: list[str] = Field(default_factory=list, max_length=50)

    @field_validator('collaborator_emails')
    @classmethod
    def normalize_collaborators(cls, values):
        emails = [Login.normalize_email(value.strip()) for value in values]
        if any(not 3 <= len(email) <= 254 for email in emails):
            raise ValueError('Enter email addresses of at most 254 characters.')
        return list(dict.fromkeys(emails))


class ItemLink(Model):
    target_id: int = Field(gt=0)
    relation: Literal['answers', 'uses', 'follows_up', 'refutes']


class ItemInput(Model):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=50000)
    kind: Kind = 'note'
    labels: list[str] = Field(default_factory=list, max_length=20)
    status: State = 'open'
    assessment: Assessment = 'unreviewed'
    links: list[ItemLink] = Field(default_factory=list, max_length=30)
    model: str = Field(default='', max_length=120)
    run_id: str = Field(default='', max_length=200)

    @field_validator('labels')
    @classmethod
    def clean_labels(cls, labels):
        result = list(dict.fromkeys(label.strip().casefold() for label in labels if label.strip()))
        if any(len(label) > 50 for label in result):
            raise ValueError('Labels must be at most 50 characters.')
        return result


class ItemUpdate(ItemInput):
    revision: int = Field(gt=0)
    archived: bool = False


class MainQuestions(Model):
    question_ids: list[int] = Field(max_length=100)
    revision: int = Field(gt=0)


class ProjectLink(Model):
    project_id: int = Field(gt=0)


class Invitation(Model):
    email: str = Field(min_length=3, max_length=254)

    @field_validator('email')
    @classmethod
    def email_address(cls, value):
        return Login.normalize_email(value)


class TokenInput(Model):
    token: str = Field(min_length=20, max_length=200)


class KeyInput(Model):
    name: str = Field(min_length=1, max_length=100)
    scope: Literal['read', 'write'] = 'write'


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
 password TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 csrf TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, objective TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '', sample INTEGER NOT NULL DEFAULT 0,
 owner_id INTEGER NOT NULL REFERENCES users(id), revision INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS members (
 project_id INTEGER NOT NULL REFERENCES projects(id), user_id INTEGER NOT NULL REFERENCES users(id),
 PRIMARY KEY(project_id,user_id));
CREATE TABLE IF NOT EXISTS agent_keys (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
 user_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL,
 token_hash TEXT NOT NULL UNIQUE, scope TEXT NOT NULL, created_at TEXT NOT NULL,
 revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS items (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
 author_id INTEGER NOT NULL REFERENCES users(id), agent_id INTEGER REFERENCES agent_keys(id),
 title TEXT NOT NULL, body TEXT NOT NULL, kind TEXT NOT NULL, labels TEXT NOT NULL,
 status TEXT NOT NULL, assessment TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
 run_id TEXT NOT NULL DEFAULT '', archived INTEGER NOT NULL DEFAULT 0,
 revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS project_items ON items(project_id,id DESC);
CREATE TABLE IF NOT EXISTS item_links (
 item_id INTEGER NOT NULL REFERENCES items(id), target_id INTEGER NOT NULL REFERENCES items(id),
 relation TEXT NOT NULL, PRIMARY KEY(item_id,target_id,relation));
CREATE TABLE IF NOT EXISTS main_questions (
 project_id INTEGER NOT NULL REFERENCES projects(id), item_id INTEGER NOT NULL REFERENCES items(id),
 position INTEGER NOT NULL, PRIMARY KEY(project_id,item_id));
CREATE TABLE IF NOT EXISTS project_links (
 a INTEGER NOT NULL REFERENCES projects(id), b INTEGER NOT NULL REFERENCES projects(id),
 PRIMARY KEY(a,b), CHECK(a<b));
CREATE TABLE IF NOT EXISTS invitations (
 token_hash TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
 email TEXT NOT NULL, expires_at TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS history (
 id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES items(id), actor TEXT NOT NULL,
 snapshot TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS project_history (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
 actor TEXT NOT NULL, action TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS idempotency (
 actor TEXT NOT NULL, project_id INTEGER NOT NULL, key TEXT NOT NULL,
 fingerprint TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(actor,project_id,key));
"""


def create_app(database=None):
    setup_token_file = os.environ.get('RESEARCH_SETUP_TOKEN_FILE')
    setup_token = Path(setup_token_file).read_text(encoding='utf-8').strip() if setup_token_file else ''
    if setup_token_file and len(setup_token) < 32:
        raise ValueError('The initial setup key file must contain at least 32 characters.')
    public_origin = os.environ.get('RESEARCH_PUBLIC_ORIGIN', '').rstrip('/')
    db_path = Path(database or os.environ.get('RESEARCH_DB', ROOT / 'data' / 'research.db'))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    file_root = db_path.parent / (db_path.stem+'-files')

    @contextmanager
    def connect():
        # FastAPI can run a request's dependency and handler on different worker
        # threads. Each request still owns its connection and transaction.
        db = sqlite3.connect(db_path, timeout=15, check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript(SCHEMA)
        migrate_topics(db, db_path)
        migrate_files(db, file_root)
        migrate_questions(db)
        migrate_agents(db)

    app = FastAPI(title='Research project API', version='0.2.0')
    app.state.database = db_path
    app.state.file_root = file_root
    security = HTTPBearer(auto_error=False)
    attempts = defaultdict(deque)

    def db_dependency():
        with connect() as db:
            yield db

    DB = Annotated[sqlite3.Connection, Depends(db_dependency, scope='function')]

    @app.middleware('http')
    async def browser_protection(request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            expected = public_origin or str(request.base_url).rstrip('/')
            if (origin and origin != expected) or request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse({'detail': 'Cross-origin writes are not allowed.'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def key_person(db, token, write=False):
        row = db.execute('SELECT k.*,u.name AS owner_name FROM agent_keys k JOIN users u ON u.id=k.user_id '
                         'JOIN members m ON m.project_id=k.project_id AND m.user_id=k.user_id '
                         'WHERE k.token_hash=? AND k.revoked=0', (digest(token),)).fetchone()
        if not row:
            raise HTTPException(401, 'Invalid or revoked agent key.')
        if write and row['scope'] != 'write':
            raise HTTPException(403, 'This key has read-only scope.')
        return {'user_id': row['user_id'], 'name': row['name'], 'kind': 'agent',
                'agent_id': row['id'], 'project_id': row['project_id'], 'actor': f'agent:{row["id"]}'}

    def principal(request: Request, db: DB, credential: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]):
        if credential is not None:
            return key_person(db, credential.credentials, write=request.method not in ('GET','HEAD'))
        token = request.cookies.get('research_session', '')
        row = db.execute('SELECT s.*,u.name,u.email FROM sessions s JOIN users u ON u.id=s.user_id '
                         'WHERE s.token_hash=? AND s.expires_at>?', (digest(token), now())).fetchone()
        if not row:
            raise HTTPException(401, 'Please sign in.')
        if request.method not in ('GET', 'HEAD') and not hmac.compare_digest(request.headers.get('x-csrf-token', ''), row['csrf']):
            raise HTTPException(403, 'Refresh the page and try again (session token mismatch).')
        return {'user_id': row['user_id'], 'name': row['name'], 'email': row['email'],
                'kind': 'human', 'agent_id': None, 'actor': f'human:{row["user_id"]}', 'csrf': row['csrf']}

    Person = Annotated[dict, Depends(principal)]

    def human(person):
        if person['kind'] != 'human':
            raise HTTPException(403, 'This action is reserved for human collaborators.')

    def project_access(db, project_id, person, owner=False):
        row = db.execute('SELECT p.* FROM projects p JOIN members m ON m.project_id=p.id '
                         'WHERE p.id=? AND m.user_id=?', (project_id, person['user_id'])).fetchone()
        if not row or (person['kind'] == 'agent' and person['project_id'] != project_id):
            raise HTTPException(404, 'Project not found.')
        if owner and (person['kind'] != 'human' or row['owner_id'] != person['user_id']):
            raise HTTPException(403, 'Only the project owner can do that.')
        return row

    def item_dict(db, row):
        result = dict(row)
        result['labels'] = json.loads(result['labels'])
        result['archived'] = bool(result['archived'])
        result['tags'] = json.loads(result.get('tags', '[]'))
        topic = db.execute('SELECT title FROM topics WHERE id=?', (result.get('topic_id'),)).fetchone()
        result['topic_title'] = topic['title'] if topic else None
        reply = db.execute('SELECT reply_to_id FROM message_replies WHERE message_id=?', (row['id'],)).fetchone()
        result['reply_to_id'] = reply['reply_to_id'] if reply else None
        author = db.execute('SELECT name FROM users WHERE id=?', (row['author_id'],)).fetchone()
        agent = db.execute('SELECT name FROM agent_keys WHERE id=?', (row['agent_id'],)).fetchone() if row['agent_id'] else None
        result['author'] = {'name': agent['name'] if agent else author['name'], 'kind': 'agent' if agent else 'human'}
        result['links'] = [dict(link) for link in db.execute(
            'SELECT l.target_id,l.relation,i.title,i.kind FROM item_links l JOIN items i ON i.id=l.target_id WHERE l.item_id=?', (row['id'],))]
        return result

    def get_item(db, project_id, item_id):
        row = db.execute('SELECT * FROM items WHERE project_id=? AND id=?', (project_id, item_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Item not found.')
        return row

    def related(db, project_id, person):
        if person['kind'] == 'agent':
            return []  # A key is explicitly scoped to one project.
        return [dict(row) for row in db.execute(
            'SELECT p.id,p.title,p.objective FROM project_links l JOIN projects p '
            'ON p.id=CASE WHEN l.a=? THEN l.b ELSE l.a END '
            'JOIN members m ON m.project_id=p.id AND m.user_id=? WHERE l.a=? OR l.b=? '
            'ORDER BY p.title', (project_id, person['user_id'], project_id, project_id))]

    def project_dict(db, row, person, detail=False):
        result = dict(row)
        result['sample'] = bool(result['sample'])
        result['is_owner'] = person['kind'] == 'human' and result['owner_id'] == person['user_id']
        result['item_count'] = db.execute('SELECT COUNT(*) FROM items WHERE project_id=? AND archived=0', (row['id'],)).fetchone()[0]
        result['open_questions'] = db.execute("SELECT COUNT(*) FROM items WHERE project_id=? AND archived=0 AND kind='question' AND status!='closed'", (row['id'],)).fetchone()[0]
        result['member_count'] = db.execute('SELECT COUNT(*) FROM members WHERE project_id=?', (row['id'],)).fetchone()[0]
        result['unread_count'] = unread_count(db, person, row['id'])
        activity = db.execute(
            'SELECT MAX(updated_at) FROM items WHERE project_id=? UNION ALL '
            'SELECT MAX(created_at) FROM topics WHERE project_id=? UNION ALL '
            'SELECT MAX(created_at) FROM project_notes WHERE project_id=? UNION ALL '
            'SELECT MAX(updated_at) FROM dashboard_questions WHERE project_id=?',
            (row['id'], row['id'], row['id'], row['id'])).fetchall()
        file_stamp = file_activity(file_root,row['id'])
        result['last_activity'] = max([row['created_at']] + [stamp[0] for stamp in activity if stamp[0]] +
                                      ([file_stamp] if file_stamp else []))
        if detail:
            result['people'] = [{'id':user['id'],'name':user['name'],'is_owner':user['id']==row['owner_id']} for user in db.execute('SELECT u.id,u.name FROM users u JOIN members m ON m.user_id=u.id WHERE m.project_id=? ORDER BY u.name COLLATE NOCASE,u.id',(row['id'],))] if person['kind']=='human' else []
            result['available_tags'] = sorted({tag for item in db.execute('SELECT tags FROM items WHERE project_id=? AND archived=0', (row['id'],)) for tag in json.loads(item['tags'])})
            result['dashboard_questions'] = list_questions(db, row['id'])
            result['main_questions'] = [item_dict(db, item) for item in db.execute(
                'SELECT i.* FROM main_questions q JOIN items i ON i.id=q.item_id WHERE q.project_id=? ORDER BY q.position', (row['id'],))]
            result['linked_projects'] = related(db, row['id'], person)
        return result

    def session(db, user_id, response):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        db.execute('INSERT INTO sessions VALUES (?,?,?,?)',
                   (digest(token), user_id, csrf, (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()))
        response.set_cookie('research_session', token, httponly=True, samesite='strict',
                            secure=os.environ.get('RESEARCH_SECURE_COOKIE') == '1', max_age=604800)
        user = db.execute('SELECT id,name,email FROM users WHERE id=?', (user_id,)).fetchone()
        return {'user': dict(user), 'csrf': csrf}

    def throttle(request, email):
        key = (request.client.host if request.client else 'local', email)
        recent = attempts[key]
        cutoff = time.monotonic() - 60
        while recent and recent[0] < cutoff:
            recent.popleft()
        if len(recent) >= 10:
            raise HTTPException(429, 'Too many attempts. Please wait a minute.')
        recent.append(time.monotonic())
        if len(attempts) > 2000:
            attempts.clear()

    def record(db, item_id, person):
        item = item_dict(db, db.execute('SELECT * FROM items WHERE id=?', (item_id,)).fetchone())
        db.execute('INSERT INTO history(item_id,actor,snapshot,created_at) VALUES (?,?,?,?)',
                   (item_id, person['name'], json.dumps(item), now()))
        return item

    def project_event(db, project_id, person, action, details):
        db.execute('INSERT INTO project_history(project_id,actor,action,details,created_at) VALUES (?,?,?,?,?)',
                   (project_id, person['name'], action, json.dumps(details), now()))

    def validate_item(db, project_id, payload, person, item_id=None):
        if payload.kind != 'question' and 'question' in payload.labels:
            raise HTTPException(422, 'Use the question kind for question items.')
        if item_id and payload.kind != 'question' and db.execute('SELECT 1 FROM open_ends WHERE question_id=?', (item_id,)).fetchone():
            raise HTTPException(422, 'This question has linked open ends. Keep its question kind.')
        if person['kind'] == 'agent' and (payload.kind == 'question' or payload.assessment != 'unreviewed'):
            raise HTTPException(403, 'Agents cannot create questions or verify results.')
        for link in payload.links:
            if link.target_id == item_id:
                raise HTTPException(422, 'An item cannot link to itself.')
            get_item(db, project_id, link.target_id)
        if len({(link.target_id, link.relation) for link in payload.links}) != len(payload.links):
            raise HTTPException(422, 'Duplicate item links.')

    def insert_item(db, project_id, payload, person):
        stamp = now()
        topic_id = ensure_general(db, project_id)
        tags = list(dict.fromkeys(([payload.kind] if payload.kind != 'note' else []) + payload.labels))
        cur = db.execute('INSERT INTO items(project_id,author_id,agent_id,title,body,kind,labels,status,assessment,model,run_id,created_at,updated_at,topic_id,tags) '
                         'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         (project_id, person['user_id'], person['agent_id'], payload.title, payload.body, payload.kind,
                          json.dumps(payload.labels), payload.status, payload.assessment, payload.model, payload.run_id, stamp, stamp, topic_id, json.dumps(tags)))
        db.execute('UPDATE topics SET revision=revision+1 WHERE id=?', (topic_id,))
        for link in payload.links:
            db.execute('INSERT INTO item_links VALUES (?,?,?)', (cur.lastrowid, link.target_id, link.relation))
        return record(db, cur.lastrowid, person)

    @app.get('/api/v1/status')
    def status(db: DB):
        required = not bool(db.execute('SELECT 1 FROM users LIMIT 1').fetchone())
        return {'setup_required': required, 'setup_token_required': required and bool(setup_token)}

    @app.get('/health')
    def health(db: DB):
        db.execute('SELECT 1').fetchone()
        return {'status': 'ok'}

    @app.post('/api/v1/auth/setup', status_code=201)
    def setup(payload: Setup, request: Request, response: Response, db: DB):
        throttle(request, payload.email)
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            raise HTTPException(409, 'Setup is complete. Please sign in or use a project invitation.')
        if setup_token and not hmac.compare_digest(payload.setup_token.encode(), setup_token.encode()):
            raise HTTPException(403, 'Enter the initial setup key from your server administrator.')
        cur = db.execute('INSERT INTO users(name,email,password,created_at) VALUES (?,?,?,?)',
                         (payload.name, payload.email, password_hash(payload.password), now()))
        if payload.sample_projects:
            from sample_data import seed
            seed(db, cur.lastrowid, insert_item)
            for project in db.execute('SELECT id FROM projects WHERE owner_id=?', (cur.lastrowid,)).fetchall():
                ensure_agents(db, project['id'])
        return session(db, cur.lastrowid, response)

    @app.post('/api/v1/auth/login')
    def login(payload: Login, request: Request, response: Response, db: DB):
        throttle(request, payload.email)
        user = db.execute('SELECT * FROM users WHERE email=?', (payload.email,)).fetchone()
        stored = user['password'] if user else password_hash('unused-password', '0' * 32)
        if not password_matches(payload.password, stored) or not user:
            raise HTTPException(401, 'Email or password is incorrect.')
        try:
            name = person_name(payload.name if payload.name is not None else user['name'])
        except ValueError as error:
            raise HTTPException(422, str(error))
        if name != user['name']:
            db.execute('UPDATE users SET name=? WHERE id=?', (name, user['id']))
        old = request.cookies.get('research_session')
        if old:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(old),))
        return session(db, user['id'], response)

    @app.get('/api/v1/auth/me')
    def me(person: Person):
        human(person)
        return {'user': {'id': person['user_id'], 'name': person['name'], 'email': person['email']}, 'csrf': person['csrf']}

    @app.post('/api/v1/auth/logout')
    def logout(request: Request, response: Response, person: Person, db: DB):
        human(person)
        db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(request.cookies.get('research_session', '')),))
        response.delete_cookie('research_session')
        return {'ok': True}

    def check_invitation(db, token):
        row = db.execute('SELECT * FROM invitations WHERE token_hash=? AND used=0 AND expires_at>?', (digest(token), now())).fetchone()
        if not row:
            raise HTTPException(400, 'This invitation is invalid, expired, or already used.')
        return row

    @app.post('/api/v1/auth/register', status_code=201)
    def register(payload: Registration, request: Request, response: Response, db: DB):
        throttle(request, payload.email)
        db.execute('BEGIN IMMEDIATE')
        invitation = check_invitation(db, payload.token)
        if invitation['email'] != payload.email:
            raise HTTPException(403, 'Use the email address this invitation was sent to.')
        if db.execute('SELECT 1 FROM users WHERE email=?', (payload.email,)).fetchone():
            raise HTTPException(409, 'You already have an account. Sign in to accept this invitation.')
        cur = db.execute('INSERT INTO users(name,email,password,created_at) VALUES (?,?,?,?)',
                         (payload.name, payload.email, password_hash(payload.password), now()))
        db.execute('INSERT INTO members VALUES (?,?)', (invitation['project_id'], cur.lastrowid))
        db.execute('UPDATE invitations SET used=1 WHERE token_hash=?', (digest(payload.token),))
        return session(db, cur.lastrowid, response)

    @app.get('/api/v1/projects')
    def projects(person: Person, db: DB):
        rows = db.execute('SELECT p.* FROM projects p JOIN members m ON m.project_id=p.id WHERE m.user_id=? ORDER BY p.id', (person['user_id'],))
        return [project_dict(db, row, person) for row in rows if person['kind'] != 'agent' or row['id'] == person['project_id']]

    @app.post('/api/v1/projects', status_code=201)
    def create_project(payload: ProjectInput, person: Person, db: DB):
        human(person)
        cur = db.execute('INSERT INTO projects(title,objective,description,owner_id,created_at) VALUES (?,?,?,?,?)',
                         (payload.title, payload.objective, payload.description, person['user_id'], now()))
        db.execute('INSERT INTO members VALUES (?,?)', (cur.lastrowid, person['user_id']))
        ensure_general(db, cur.lastrowid)
        ensure_agents(db, cur.lastrowid)
        invitations = []
        for email in payload.collaborator_emails:
            if email == person['email']:
                continue
            token = secrets.token_urlsafe(32)
            expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
            db.execute('INSERT INTO invitations VALUES (?,?,?,?,0)', (digest(token), cur.lastrowid, email, expires))
            invitations.append({'email': email, 'token': token, 'expires_at': expires})
        return {**project_dict(db, project_access(db, cur.lastrowid, person), person, True),
                'invitations': invitations}

    @app.get('/api/v1/projects/{project_id}')
    def project(project_id: int, person: Person, db: DB):
        return project_dict(db, project_access(db, project_id, person), person, True)

    @app.put('/api/v1/projects/{project_id}/main-questions')
    def main_questions(project_id: int, payload: MainQuestions, person: Person, db: DB):
        human(person)
        db.execute('BEGIN IMMEDIATE')
        row = project_access(db, project_id, person)
        if row['revision'] != payload.revision:
            raise HTTPException(409, 'The project changed. Refresh and try again.')
        if len(set(payload.question_ids)) != len(payload.question_ids):
            raise HTTPException(422, 'Choose each question only once.')
        for item_id in payload.question_ids:
            item = get_item(db, project_id, item_id)
            if item['kind'] != 'question' or item['archived']:
                raise HTTPException(422, 'Main questions must be active question items in this project.')
        db.execute('DELETE FROM main_questions WHERE project_id=?', (project_id,))
        db.executemany('INSERT INTO main_questions VALUES (?,?,?)', [(project_id, item_id, i) for i, item_id in enumerate(payload.question_ids)])
        db.execute('UPDATE projects SET revision=revision+1 WHERE id=?', (project_id,))
        project_event(db, project_id, person, 'main_questions', payload.question_ids)
        return project_dict(db, project_access(db, project_id, person), person, True)

    @app.get('/api/v1/projects/{project_id}/linked-projects')
    def linked_projects(project_id: int, person: Person, db: DB):
        project_access(db, project_id, person)
        return related(db, project_id, person)

    @app.post('/api/v1/projects/{project_id}/linked-projects', status_code=201)
    def link_project(project_id: int, payload: ProjectLink, person: Person, db: DB):
        human(person)
        project_access(db, project_id, person)
        project_access(db, payload.project_id, person)
        if project_id == payload.project_id:
            raise HTTPException(422, 'Choose a different project.')
        db.execute('INSERT OR IGNORE INTO project_links VALUES (?,?)', tuple(sorted((project_id, payload.project_id))))
        return related(db, project_id, person)

    @app.delete('/api/v1/projects/{project_id}/linked-projects/{target_id}')
    def unlink_project(project_id: int, target_id: int, person: Person, db: DB):
        human(person)
        project_access(db, project_id, person)
        project_access(db, target_id, person)
        db.execute('DELETE FROM project_links WHERE a=? AND b=?', tuple(sorted((project_id, target_id))))
        return {'ok': True}

    @app.get('/api/v1/projects/{project_id}/members')
    def members(project_id: int, person: Person, db: DB):
        human(person)
        row = project_access(db, project_id, person)
        return [{**dict(user), 'is_owner': user['id'] == row['owner_id']} for user in db.execute(
            'SELECT u.id,u.name,u.email FROM users u JOIN members m ON m.user_id=u.id WHERE m.project_id=? ORDER BY u.name', (project_id,))]

    @app.delete('/api/v1/projects/{project_id}/members/{user_id}')
    def remove_member(project_id: int, user_id: int, person: Person, db: DB):
        row = project_access(db, project_id, person, owner=True)
        if user_id == row['owner_id']:
            raise HTTPException(422, 'The project owner cannot be removed.')
        db.execute('DELETE FROM members WHERE project_id=? AND user_id=?', (project_id, user_id))
        db.execute('UPDATE agent_keys SET revoked=1 WHERE project_id=? AND user_id=?', (project_id, user_id))
        return {'ok': True}

    @app.post('/api/v1/projects/{project_id}/invitations', status_code=201)
    def invite(project_id: int, payload: Invitation, person: Person, db: DB):
        project_access(db, project_id, person, owner=True)
        token = secrets.token_urlsafe(32)
        expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        db.execute('INSERT INTO invitations VALUES (?,?,?,?,0)', (digest(token), project_id, payload.email, expires))
        return {'token': token, 'expires_at': expires}

    @app.post('/api/v1/invitations/accept')
    def accept_invite(payload: TokenInput, person: Person, db: DB):
        human(person)
        db.execute('BEGIN IMMEDIATE')
        invitation = check_invitation(db, payload.token)
        if invitation['email'] != person['email']:
            raise HTTPException(403, 'This invitation is for a different email address.')
        db.execute('INSERT OR IGNORE INTO members VALUES (?,?)', (invitation['project_id'], person['user_id']))
        db.execute('UPDATE invitations SET used=1 WHERE token_hash=?', (digest(payload.token),))
        return {'project_id': invitation['project_id']}

    @app.get('/api/v1/projects/{project_id}/keys')
    def keys(project_id: int, person: Person, db: DB):
        human(person)
        row = project_access(db, project_id, person)
        return [dict(key) for key in db.execute('SELECT k.id,k.name,k.scope,k.user_id,k.created_at,k.revoked,u.name AS owner '
            'FROM agent_keys k JOIN users u ON u.id=k.user_id WHERE k.project_id=? AND (k.user_id=? OR ?=?) ORDER BY k.id DESC',
            (project_id, person['user_id'], row['owner_id'], person['user_id']))]

    @app.post('/api/v1/projects/{project_id}/keys', status_code=201)
    def create_key(project_id: int, payload: KeyInput, person: Person, db: DB):
        human(person)
        project_access(db, project_id, person)
        token = 'rn_' + secrets.token_urlsafe(36)
        cur = db.execute('INSERT INTO agent_keys(project_id,user_id,name,token_hash,scope,created_at) VALUES (?,?,?,?,?,?)',
                         (project_id, person['user_id'], payload.name, digest(token), payload.scope, now()))
        return {'id': cur.lastrowid, 'token': token, 'name': payload.name, 'scope': payload.scope}

    @app.delete('/api/v1/projects/{project_id}/keys/{key_id}')
    def revoke_key(project_id: int, key_id: int, person: Person, db: DB):
        human(person)
        row = project_access(db, project_id, person)
        key = db.execute('SELECT * FROM agent_keys WHERE id=? AND project_id=?', (key_id, project_id)).fetchone()
        if not key or (key['user_id'] != person['user_id'] and row['owner_id'] != person['user_id']):
            raise HTTPException(404, 'Key not found.')
        db.execute('UPDATE agent_keys SET revoked=1 WHERE id=?', (key_id,))
        return {'ok': True}

    @app.post('/api/v1/projects/{project_id}/items', status_code=201)
    def create_item(project_id: int, payload: ItemInput, request: Request, response: Response, person: Person, db: DB):
        db.execute('BEGIN IMMEDIATE')
        project_access(db, project_id, person)
        validate_item(db, project_id, payload, person)
        key = request.headers.get('idempotency-key')
        fingerprint = digest(json.dumps(payload.model_dump(), sort_keys=True))
        if key:
            if len(key) > 200:
                raise HTTPException(422, 'Idempotency key is too long.')
            previous = db.execute('SELECT * FROM idempotency WHERE actor=? AND project_id=? AND key=?', (person['actor'], project_id, key)).fetchone()
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise HTTPException(409, 'That idempotency key was used with different content.')
                response.headers['Idempotency-Replayed'] = 'true'
                return json.loads(previous['response'])
        item = insert_item(db, project_id, payload, person)
        if key:
            db.execute('INSERT INTO idempotency VALUES (?,?,?,?,?)', (person['actor'], project_id, key, fingerprint, json.dumps(item)))
        return item

    @app.get('/api/v1/projects/{project_id}/items')
    def list_items(project_id: int, person: Person, db: DB, kind: Kind | None = None,
                   label: str | None = None, status: State | None = None, q: str = '',
                   author_id: int | None = None, updated_since: datetime | None = None,
                   include_archived: bool = False, limit: int = Query(30, ge=1, le=100), cursor: str | None = None):
        project_access(db, project_id, person)
        where, values = ['project_id=?'], [project_id]
        if not include_archived and updated_since is None:
            where.append('archived=0')
        for column, value in [('kind', kind), ('status', status), ('author_id', author_id)]:
            if value is not None:
                where.append(f'{column}=?')
                values.append(value)
        if label:
            where.append('EXISTS (SELECT 1 FROM json_each(items.labels) WHERE value=?)')
            values.append(label.strip().casefold())
        if q:
            where.append('(instr(lower(title),lower(?))>0 OR instr(lower(body),lower(?))>0)')
            values.extend([q, q])
        if updated_since:
            if updated_since.tzinfo is None:
                raise HTTPException(422, 'updated_since must include a timezone.')
            where.append('updated_at>?')
            values.append(updated_since.astimezone(timezone.utc).isoformat(timespec='microseconds'))
        if cursor:
            try:
                before = int(base64.urlsafe_b64decode(cursor.encode()).decode())
                if before <= 0:
                    raise ValueError()
            except (ValueError, UnicodeError):
                raise HTTPException(422, 'Invalid pagination cursor.')
            where.append('id<?')
            values.append(before)
        rows = db.execute('SELECT * FROM items WHERE ' + ' AND '.join(where) + ' ORDER BY id DESC LIMIT ?', values + [limit + 1]).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = base64.urlsafe_b64encode(str(rows[-1]['id']).encode()).decode() if more else None
        return {'items': [item_dict(db, row) for row in rows], 'next_cursor': next_cursor}

    @app.get('/api/v1/projects/{project_id}/items/{item_id}')
    def read_item(project_id: int, item_id: int, person: Person, db: DB):
        project_access(db, project_id, person)
        result = item_dict(db, get_item(db, project_id, item_id))
        result['incoming_links'] = [dict(row) for row in db.execute('SELECT l.item_id,l.relation,i.title,i.kind FROM item_links l '
            'JOIN items i ON i.id=l.item_id WHERE l.target_id=? AND i.archived=0', (item_id,))]
        return result

    @app.patch('/api/v1/projects/{project_id}/items/{item_id}')
    def update_item(project_id: int, item_id: int, payload: ItemUpdate, person: Person, db: DB):
        db.execute('BEGIN IMMEDIATE')
        row = project_access(db, project_id, person)
        item = get_item(db, project_id, item_id)
        if person['kind'] == 'agent':
            if item['agent_id'] != person['agent_id'] or item['kind'] == 'question' or item['assessment'] != 'unreviewed':
                raise HTTPException(403, 'Agents can only edit their own unreviewed, non-question items.')
        elif row['owner_id'] != person['user_id'] and (item['author_id'] != person['user_id'] or item['agent_id'] is not None):
            raise HTTPException(403, 'You can edit your own entries. The project owner can edit all entries.')
        if item['revision'] != payload.revision:
            raise HTTPException(409, 'This item changed. Reopen it before saving your revision.')
        validate_item(db, project_id, payload, person, item_id)
        db.execute('UPDATE items SET title=?,body=?,kind=?,labels=?,status=?,assessment=?,model=?,run_id=?,archived=?,revision=revision+1,updated_at=? WHERE id=?',
                   (payload.title, payload.body, payload.kind, json.dumps(payload.labels), payload.status, payload.assessment,
                    payload.model, payload.run_id, int(payload.archived), now(), item_id))
        tags = list(dict.fromkeys(([payload.kind] if payload.kind != 'note' else []) + payload.labels))
        db.execute('UPDATE items SET tags=? WHERE id=?', (json.dumps(tags), item_id))
        db.execute('UPDATE topics SET revision=revision+1 WHERE id=?', (item['topic_id'],))
        db.execute('DELETE FROM item_links WHERE item_id=?', (item_id,))
        db.executemany('INSERT INTO item_links VALUES (?,?,?)', [(item_id, link.target_id, link.relation) for link in payload.links])
        if payload.archived or payload.kind != 'question':
            removed = db.execute('DELETE FROM main_questions WHERE item_id=?', (item_id,)).rowcount
            if removed:
                db.execute('UPDATE projects SET revision=revision+1 WHERE id=?', (project_id,))
                project_event(db, project_id, person, 'main_question_removed', {'item_id': item_id})
        return record(db, item_id, person)

    @app.get('/api/v1/projects/{project_id}/items/{item_id}/history')
    def history(project_id: int, item_id: int, person: Person, db: DB):
        project_access(db, project_id, person)
        get_item(db, project_id, item_id)
        return [{'actor': row['actor'], 'created_at': row['created_at'], 'item': json.loads(row['snapshot'])}
                for row in db.execute('SELECT * FROM history WHERE item_id=? ORDER BY id DESC', (item_id,))]

    @app.get('/api/v1/projects/{project_id}/export')
    def export(project_id: int, person: Person, db: DB):
        project = project_dict(db, project_access(db, project_id, person), person, True)
        return JSONResponse({'format_version': 2, 'exported_at': now(), 'project': project,
            'items': [item_dict(db, row) for row in db.execute('SELECT * FROM items WHERE project_id=? ORDER BY id', (project_id,))],
            'files':export_files(file_root,project_id), **topic_export(db, project_id)},
            headers={'Content-Disposition': f'attachment; filename="research-project-{project_id}.json"'})

    install_questions(app, DB=DB, Person=Person, project_access=project_access, human=human,
                      project_event=project_event, now=now)
    install_topics(app, DB=DB, Person=Person, project_access=project_access,
                   human=human, item_dict=item_dict, get_item=get_item, record=record,
                   project_dict=project_dict, project_event=project_event)
    install_files(app, root=file_root, DB=DB, Person=Person, project_access=project_access,
                  key_person=key_person, project_event=project_event)
    install_editor(app, root=file_root, connect=connect, DB=DB, Person=Person, project_access=project_access)
    install_agents(app, root=file_root, DB=DB, Person=Person, project_access=project_access,
                   human=human, now=now)

    app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

    @app.get('/', include_in_schema=False)
    def index():
        return FileResponse(ROOT / 'static' / 'index.html', headers={'Cache-Control': 'no-cache'})

    return app


app = create_app()
