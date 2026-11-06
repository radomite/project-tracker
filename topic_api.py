"""Authenticated topics/messages, search, and read-only legacy data export."""
import base64
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from fastapi import HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Literal
from file_api import search_files


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def unread_count(db, person, project_id, topic_id=None):
    if person['kind'] != 'human':
        return 0
    return db.execute('SELECT COUNT(*) FROM items i WHERE i.project_id=? AND i.archived=0 '
        'AND (? IS NULL OR i.topic_id=?) AND (i.author_id!=? OR i.agent_id IS NOT NULL) '
        'AND NOT EXISTS (SELECT 1 FROM message_reads r WHERE r.message_id=i.id AND r.user_id=?)',
        (project_id, topic_id, topic_id, person['user_id'], person['user_id'])).fetchone()[0]


def ensure_general(db, project_id):
    row = db.execute("SELECT id FROM topics WHERE project_id=? AND title_key='general'", (project_id,)).fetchone()
    if row:
        return row['id']
    return db.execute('INSERT INTO topics(project_id,title,title_key,created_at) VALUES (?,?,?,?)',
                      (project_id, 'General', 'general', stamp())).lastrowid


def migrate_topics(db, db_path):
    old = 'topic_id' not in {row['name'] for row in db.execute('PRAGMA table_info(items)')}
    if old and db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
        backup = Path(db_path).with_name(Path(db_path).stem + '-before-topics-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.db')
        with closing(sqlite3.connect(backup)) as target:
            db.backup(target)
    db.executescript('''
    CREATE TABLE IF NOT EXISTS topics (
      id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
      title TEXT NOT NULL, title_key TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL, UNIQUE(project_id,title_key));
    CREATE TABLE IF NOT EXISTS topic_forks (
      topic_id INTEGER PRIMARY KEY REFERENCES topics(id), source_message_id INTEGER NOT NULL REFERENCES items(id),
      source_topic_id INTEGER NOT NULL REFERENCES topics(id), actor TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS message_replies (
      message_id INTEGER PRIMARY KEY REFERENCES items(id),
      reply_to_id INTEGER NOT NULL REFERENCES items(id), CHECK(message_id != reply_to_id));
    CREATE TABLE IF NOT EXISTS message_reads (
      user_id INTEGER NOT NULL REFERENCES users(id), message_id INTEGER NOT NULL REFERENCES items(id),
      PRIMARY KEY(user_id,message_id));
    CREATE TABLE IF NOT EXISTS topic_events (
      id INTEGER PRIMARY KEY, topic_id INTEGER NOT NULL REFERENCES topics(id),
      kind TEXT NOT NULL, other_topic_id INTEGER NOT NULL REFERENCES topics(id),
      message_ids TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS open_ends (
      id INTEGER PRIMARY KEY, question_id INTEGER NOT NULL REFERENCES items(id),
      message_id INTEGER NOT NULL REFERENCES items(id), state TEXT NOT NULL DEFAULT 'open',
      created_at TEXT NOT NULL, UNIQUE(question_id,message_id));
    CREATE TABLE IF NOT EXISTS viability_ratings (
      open_end_id INTEGER NOT NULL REFERENCES open_ends(id), actor TEXT NOT NULL,
      user_id INTEGER NOT NULL REFERENCES users(id), agent_id INTEGER REFERENCES agent_keys(id),
      score INTEGER NOT NULL CHECK(score BETWEEN 1 AND 5), reason TEXT NOT NULL,
      model TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL, PRIMARY KEY(open_end_id,actor));
    CREATE TABLE IF NOT EXISTS project_notes (
      id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
      title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', filename TEXT NOT NULL DEFAULT '',
      content BLOB, author_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL);
    ''')
    db.execute('BEGIN IMMEDIATE')
    if old:
        db.execute('ALTER TABLE items ADD COLUMN topic_id INTEGER REFERENCES topics(id)')
        db.execute("ALTER TABLE items ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'")
    for project in db.execute('SELECT id FROM projects').fetchall():
        pending = db.execute('SELECT id,kind,labels FROM items WHERE project_id=? AND topic_id IS NULL', (project['id'],)).fetchall()
        if not pending and db.execute('SELECT 1 FROM topics WHERE project_id=?', (project['id'],)).fetchone():
            continue
        topic_id = ensure_general(db, project['id'])
        for item in pending:
            tags = list(dict.fromkeys(([item['kind']] if item['kind'] != 'note' else []) + json.loads(item['labels'])))
            db.execute('UPDATE items SET topic_id=?,tags=? WHERE id=?', (topic_id, json.dumps(tags), item['id']))
    db.execute('CREATE INDEX IF NOT EXISTS topic_messages ON items(topic_id,created_at,id)')
    db.execute('PRAGMA user_version=2')
    db.commit()


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class TopicInput(Model):
    title: str = Field(min_length=1, max_length=160)


class TopicUpdate(TopicInput):
    revision: int = Field(gt=0)


class MessageInput(Model):
    body: str = Field(min_length=1, max_length=50000)
    title: str = Field(default='', max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=20)
    model: str = Field(default='', max_length=120)
    run_id: str = Field(default='', max_length=200)
    reply_to_id: int | None = Field(default=None, gt=0)

    @field_validator('tags')
    @classmethod
    def clean_tags(cls, values):
        tags = list(dict.fromkeys(value.strip().casefold().replace('_', ' ') for value in values if value.strip()))
        if any(len(tag) > 50 for tag in tags):
            raise ValueError('Tags must be at most 50 characters.')
        return list(dict.fromkeys('solution' if tag == 'proposed solution' else tag for tag in tags))


class MessageUpdate(MessageInput):
    revision: int = Field(gt=0)
    archived: bool = False


class TagsInput(Model):
    tags: list[str] = Field(max_length=20)
    revision: int = Field(gt=0)
    _clean_tags = field_validator('tags')(MessageInput.clean_tags.__func__)


class ReadMessages(Model):
    message_ids: list[int] = Field(min_length=1, max_length=200)


class MoveInput(Model):
    target_topic_id: int | None = Field(default=None, gt=0)
    new_topic_title: str | None = Field(default=None, min_length=1, max_length=160)
    mode: Literal['single', 'following', 'all'] = 'single'
    revision: int = Field(gt=0)

    @model_validator(mode='after')
    def target(self):
        if (self.target_topic_id is None) == (self.new_topic_title is None):
            raise ValueError('Select an existing topic or enter one new topic title.')
        return self


class SelectedMessage(Model):
    id: int = Field(gt=0)
    revision: int = Field(gt=0)


class SelectedMove(Model):
    messages: list[SelectedMessage] = Field(min_length=1, max_length=200)
    target_topic_id: int | None = Field(default=None, gt=0)
    new_topic_title: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode='after')
    def target(self):
        if (self.target_topic_id is None) == (self.new_topic_title is None):
            raise ValueError('Select an existing topic or enter one new topic title.')
        if len({message.id for message in self.messages}) != len(self.messages):
            raise ValueError('Select each message only once.')
        return self


def topic_export(db, project_id):
    notes = []
    for row in db.execute('SELECT * FROM project_notes WHERE project_id=? ORDER BY id', (project_id,)):
        note = dict(row)
        note['content_base64'] = base64.b64encode(note.pop('content')).decode() if row['content'] is not None else None
        notes.append(note)
    return {
        'topics':[dict(row) for row in db.execute('SELECT * FROM topics WHERE project_id=? ORDER BY id', (project_id,))],
        'forks':[dict(row) for row in db.execute('SELECT f.* FROM topic_forks f JOIN topics t ON t.id=f.topic_id WHERE t.project_id=?', (project_id,))],
        'replies':[dict(row) for row in db.execute('SELECT r.* FROM message_replies r JOIN items i ON i.id=r.message_id WHERE i.project_id=?', (project_id,))],
        'topic_events':[dict(row) for row in db.execute('SELECT e.* FROM topic_events e JOIN topics t ON t.id=e.topic_id WHERE t.project_id=?', (project_id,))],
        'open_ends':[dict(row) for row in db.execute('SELECT e.* FROM open_ends e JOIN items q ON q.id=e.question_id WHERE q.project_id=?', (project_id,))],
        'viability_ratings':[dict(row) for row in db.execute('SELECT r.* FROM viability_ratings r JOIN open_ends e ON e.id=r.open_end_id JOIN items q ON q.id=e.question_id WHERE q.project_id=?', (project_id,))],
        'notes':notes,
    }


def install_topics(app, *, DB, Person, project_access, human, item_dict, get_item,
                   record, project_dict, project_event):
    def topic_access(db, pid, tid, person):
        project_access(db, pid, person)
        row = db.execute('SELECT * FROM topics WHERE id=? AND project_id=?', (tid, pid)).fetchone()
        if not row:
            raise HTTPException(404, 'Topic not found.')
        return row

    def topic_dict(db, row, person):
        result = dict(row)
        latest = db.execute('SELECT MAX(updated_at) FROM items WHERE topic_id=?', (row['id'],)).fetchone()[0]
        result['last_activity'] = max(row['created_at'], latest or row['created_at'])
        result['unread_count'] = unread_count(db, person, row['project_id'], row['id'])
        fork = db.execute('SELECT f.source_message_id,i.topic_id,t.title,f.source_topic_id AS original_topic_id,original.title AS original_title FROM topic_forks f '
                          'JOIN items i ON i.id=f.source_message_id JOIN topics t ON t.id=i.topic_id '
                          'JOIN topics original ON original.id=f.source_topic_id WHERE f.topic_id=?', (row['id'],)).fetchone()
        result['forked_from'] = dict(fork) if fork else None
        return result

    def new_topic(db, pid, title):
        if db.execute('SELECT 1 FROM topics WHERE project_id=? AND title_key=?', (pid, title.casefold())).fetchone():
            raise HTTPException(409, 'A topic with that name already exists.')
        tid = db.execute('INSERT INTO topics(project_id,title,title_key,created_at) VALUES (?,?,?,?)', (pid, title, title.casefold(), stamp())).lastrowid
        return db.execute('SELECT * FROM topics WHERE id=?', (tid,)).fetchone()

    def message_dict(db, row):
        result = item_dict(db, row)
        result['forks'] = [dict(f) for f in db.execute('SELECT t.id,t.title FROM topic_forks f JOIN topics t ON t.id=f.topic_id WHERE f.source_message_id=?', (row['id'],))]
        result['open_ends'] = [dict(end) for end in db.execute('SELECT e.id,e.question_id,e.state,q.title,q.body FROM open_ends e JOIN items q ON q.id=e.question_id WHERE e.message_id=?', (row['id'],))]
        result['reply_to'] = None
        if result['reply_to_id']:
            source = item_dict(db, get_item(db, row['project_id'], result['reply_to_id']))
            result['reply_to'] = {key:source[key] for key in ('id','topic_id','author','title','body','archived')}
        return result

    def check_tags(person, tags):
        if person['kind'] == 'agent' and 'question' in tags:
            raise HTTPException(403, 'Only humans can create question messages.')

    def sync_tags(db, row, tags, person):
        check_tags(person, tags)
        old_tags = json.loads(row['tags'])
        if person['kind'] == 'agent' and 'question' in old_tags:
            raise HTTPException(403, 'Only humans can change question messages.')
        kind = 'question' if 'question' in tags else next((tag for tag in tags if tag in ('solution', 'technique', 'observation', 'experiment')), 'note')
        labels = [tag for tag in tags if tag != kind]
        db.execute('UPDATE items SET tags=?,kind=?,labels=? WHERE id=?', (json.dumps(tags), kind, json.dumps(labels), row['id']))
        if kind != 'question':
            if db.execute('DELETE FROM main_questions WHERE item_id=?', (row['id'],)).rowcount:
                db.execute('UPDATE projects SET revision=revision+1 WHERE id=?', (row['project_id'],))
                project_event(db, row['project_id'], person, 'main_question_removed', {'item_id': row['id']})

    def add_message(db, pid, tid, payload, person):
        check_tags(person, payload.tags)
        if payload.reply_to_id:
            source = get_item(db, pid, payload.reply_to_id)
            if source['archived']:
                raise HTTPException(422, 'Choose an active message to reply to.')
        ts = stamp()
        kind = 'question' if 'question' in payload.tags else 'note'
        mid = db.execute('INSERT INTO items(project_id,topic_id,author_id,agent_id,title,body,kind,labels,tags,status,assessment,model,run_id,created_at,updated_at) '
                         "VALUES (?,?,?,?,?,?,?,?,?,'open','unreviewed',?,?,?,?)",
                         (pid, tid, person['user_id'], person['agent_id'], payload.title, payload.body, kind, '[]', json.dumps(payload.tags), payload.model, payload.run_id, ts, ts)).lastrowid
        row = get_item(db, pid, mid)
        sync_tags(db, row, payload.tags, person)
        if payload.reply_to_id:
            db.execute('INSERT INTO message_replies VALUES (?,?)', (mid, payload.reply_to_id))
        db.execute('UPDATE topics SET revision=revision+1 WHERE id=?', (tid,))
        record(db, mid, person)
        return message_dict(db, get_item(db, pid, mid))

    def touch(db, mid, tid):
        db.execute('UPDATE items SET revision=revision+1,updated_at=? WHERE id=?', (stamp(), mid))
        db.execute('UPDATE topics SET revision=revision+1 WHERE id=?', (tid,))

    def move_messages(db, pid, source, target_id, mode, person, selected_ids=None):
        if target_id == source['topic_id']:
            raise HTTPException(422, 'Choose a different topic.')
        if person['kind'] == 'agent' and (mode != 'single' or source['agent_id'] != person['agent_id'] or source['kind'] == 'question'):
            raise HTTPException(403, 'Agents can move only their own non-question messages individually.')
        where, args = 'topic_id=?', [source['topic_id']]
        if mode == 'single':
            where += ' AND id=?'
            args.append(source['id'])
        elif mode == 'selected':
            where += ' AND id IN ('+','.join('?' for _ in selected_ids)+')'
            args += selected_ids
        elif mode == 'following':
            where += ' AND (created_at>? OR (created_at=? AND id>=?))'
            args += [source['created_at'], source['created_at'], source['id']]
        rows = db.execute('SELECT * FROM items WHERE '+where+' ORDER BY created_at,id', args).fetchall()
        ids = [row['id'] for row in rows]
        for row in rows:
            db.execute('UPDATE items SET topic_id=?,revision=revision+1,updated_at=? WHERE id=?', (target_id, stamp(), row['id']))
            record(db, row['id'], person)
        ts = stamp()
        for tid, other, kind in [(source['topic_id'], target_id, 'moved_out'), (target_id, source['topic_id'], 'moved_in')]:
            db.execute('INSERT INTO topic_events(topic_id,kind,other_topic_id,message_ids,actor,created_at) VALUES (?,?,?,?,?,?)',
                       (tid, kind, other, json.dumps(ids), person['name'], ts))
            db.execute('UPDATE topics SET revision=revision+1 WHERE id=?', (tid,))
        return ids


    @app.get('/api/v1/search')
    def search(person: Person, db: DB, q: str = Query(min_length=1, max_length=200),
               project_id: int | None = Query(default=None, gt=0),
               content_only: bool = False,
               limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0)):
        if project_id is not None:
            project_access(db, project_id, person)
        query = q.strip()
        if not query:
            return {'results':[], 'has_more':False}
        rows = db.execute('''
            WITH accessible AS (
              SELECT p.* FROM projects p JOIN members m ON m.project_id=p.id
              WHERE m.user_id=:uid AND (:pid IS NULL OR p.id=:pid)
              AND (:agent_pid IS NULL OR p.id=:agent_pid)
            ), note_text AS (
              SELECT n.*,p.title AS project_title,
                CASE WHEN n.filename!='' AND lower(substr(n.filename,-4))!='.pdf'
                  THEN CAST(n.content AS TEXT) ELSE n.body END AS searchable
              FROM project_notes n JOIN accessible p ON p.id=n.project_id
              WHERE NOT EXISTS (SELECT 1 FROM file_note_imports f WHERE f.note_id=n.id)
            ), matches AS (
              SELECT 'project' AS kind,p.id,p.id AS project_id,p.title AS project_title,
                NULL AS topic_id,'' AS topic_title,p.title,
                substr(p.objective,1,300) AS snippet,p.created_at,1 AS priority
              FROM accessible p WHERE instr(lower(p.title),lower(:q))>0
                OR instr(lower(p.objective),lower(:q))>0 OR instr(lower(p.description),lower(:q))>0
              UNION ALL
              SELECT 'topic',t.id,p.id,p.title,t.id,t.title,t.title,'',t.created_at,2
              FROM topics t JOIN accessible p ON p.id=t.project_id
              WHERE instr(lower(t.title),lower(:q))>0
              UNION ALL
              SELECT 'message',i.id,p.id,p.title,i.topic_id,t.title,i.title,substr(i.body,1,300),i.created_at,3
              FROM items i JOIN accessible p ON p.id=i.project_id JOIN topics t ON t.id=i.topic_id
              WHERE i.archived=0 AND (instr(lower(i.title),lower(:q))>0
                OR instr(lower(i.body),lower(:q))>0 OR instr(lower(i.tags),lower(:q))>0)
              UNION ALL
              SELECT 'note',n.id,n.project_id,n.project_title,NULL,'',
                CASE WHEN n.filename!='' THEN n.filename ELSE n.title END,
                substr(n.searchable,1,300),n.created_at,4
              FROM note_text n WHERE instr(lower(n.title),lower(:q))>0
                OR instr(lower(n.filename),lower(:q))>0 OR instr(lower(n.searchable),lower(:q))>0
            ) SELECT kind,id,project_id,project_title,topic_id,topic_title,title,snippet
              FROM matches WHERE (:content_only=0 OR kind IN ('message','note')) ORDER BY priority,created_at DESC,id DESC LIMIT :limit
            ''', {'uid':person['user_id'], 'pid':project_id,
                  'agent_pid':person['project_id'] if person['kind']=='agent' else None,
                  'q':query, 'content_only':content_only, 'limit':limit+offset+1}).fetchall()
        results = [dict(row) for row in rows]
        for project in db.execute('SELECT p.id,p.title FROM projects p JOIN members m ON m.project_id=p.id '
            'WHERE m.user_id=? AND (? IS NULL OR p.id=?) ORDER BY p.id',
            (person['user_id'],project_id,project_id)):
            if person['kind']=='agent' and project['id']!=person['project_id']:
                continue
            results.extend(search_files(app.state.file_root,project['id'],project['title'],query))
        return {'results':results[offset:offset+limit], 'has_more':len(results)>offset+limit}

    @app.get('/api/v1/projects/{project_id}/topics')
    def topics(project_id: int, person: Person, db: DB):
        project_access(db, project_id, person)
        results = [topic_dict(db, row, person) for row in db.execute('SELECT * FROM topics WHERE project_id=?', (project_id,))]
        return sorted(results, key=lambda topic:(topic['last_activity'],topic['id']), reverse=True)

    @app.post('/api/v1/projects/{project_id}/read')
    def read_messages(project_id: int, payload: ReadMessages, person: Person, db: DB):
        human(person)
        db.execute('BEGIN IMMEDIATE')
        project = project_access(db, project_id, person)
        ids = list(dict.fromkeys(payload.message_ids))
        placeholders = ','.join('?' for _ in ids)
        valid = db.execute(f'SELECT id FROM items WHERE project_id=? AND id IN ({placeholders})', [project_id,*ids]).fetchall()
        if len(valid) != len(ids):
            raise HTTPException(404, 'Message not found in this project.')
        db.executemany('INSERT OR IGNORE INTO message_reads(user_id,message_id) VALUES (?,?)',
                       [(person['user_id'], mid) for mid in ids])
        return {'project':project_dict(db, project, person), 'topics':topics(project_id, person, db)}

    @app.post('/api/v1/projects/{project_id}/topics', status_code=201)
    def create_topic(project_id: int, payload: TopicInput, person: Person, db: DB):
        db.execute('BEGIN IMMEDIATE')
        project_access(db, project_id, person)
        return topic_dict(db, new_topic(db, project_id, payload.title), person)

    @app.patch('/api/v1/projects/{project_id}/topics/{topic_id}')
    def rename_topic(project_id: int, topic_id: int, payload: TopicUpdate, person: Person, db: DB):
        human(person)
        db.execute('BEGIN IMMEDIATE')
        row = topic_access(db, project_id, topic_id, person)
        if row['revision']!=payload.revision:
            raise HTTPException(409, 'The topic changed. Reopen it and try again.')
        if db.execute('SELECT 1 FROM topics WHERE project_id=? AND title_key=? AND id!=?', (project_id, payload.title.casefold(), topic_id)).fetchone():
            raise HTTPException(409, 'A topic with that name already exists.')
        db.execute('UPDATE topics SET title=?,title_key=?,revision=revision+1 WHERE id=?', (payload.title, payload.title.casefold(), topic_id))
        project_event(db, project_id, person, 'topic_renamed', {'topic_id':topic_id,'title':payload.title})
        return topic_dict(db, db.execute('SELECT * FROM topics WHERE id=?', (topic_id,)).fetchone(), person)

    @app.get('/api/v1/projects/{project_id}/topics/{topic_id}/messages')
    def list_messages(project_id: int, topic_id: int, person: Person, db: DB,
                      limit: int = Query(60, ge=1, le=200), before: str | None = None,
                      anchor: int | None = None, q: str = Query('', max_length=200), tag: str | None = None):
        topic = topic_access(db, project_id, topic_id, person)
        where, args = ['topic_id=?', 'archived=0'], [topic_id]
        if q:
            where.append('(instr(lower(body),lower(?))>0 OR instr(lower(title),lower(?))>0)')
            args += [q, q]
        if tag:
            where.append('EXISTS (SELECT 1 FROM json_each(items.tags) WHERE value=?)')
            args.append(tag.casefold())
        if before:
            try:
                ts, mid = json.loads(base64.urlsafe_b64decode(before).decode())
                if not isinstance(ts, str) or type(mid) is not int or not 0 < mid < 2**63:
                    raise ValueError()
            except (ValueError, TypeError, UnicodeError):
                raise HTTPException(422, 'Invalid message cursor.')
            where.append('(created_at<? OR (created_at=? AND id<?))')
            args += [ts, ts, mid]
        if anchor:
            source = get_item(db, project_id, anchor)
            if source['topic_id'] != topic_id:
                raise HTTPException(409, 'That message moved to another topic.')
            where.append('(created_at<? OR (created_at=? AND id<=?))')
            args += [source['created_at'],source['created_at'],source['id']]
        rows = db.execute('SELECT * FROM items WHERE '+' AND '.join(where)+' ORDER BY created_at DESC,id DESC LIMIT ?', args+[limit+1]).fetchall()
        more, rows = len(rows)>limit, rows[:limit]
        cursor = base64.urlsafe_b64encode(json.dumps([rows[-1]['created_at'], rows[-1]['id']]).encode()).decode() if more else None
        events = [{**dict(row), 'message_ids': json.loads(row['message_ids'])} for row in db.execute(
            'SELECT e.*,t.title AS other_topic_title FROM topic_events e JOIN topics t ON t.id=e.other_topic_id WHERE e.topic_id=? ORDER BY e.id DESC LIMIT 50', (topic_id,))]
        return {'topic': topic_dict(db, topic, person), 'messages': [message_dict(db, row) for row in reversed(rows)], 'next_before': cursor, 'events': list(reversed(events))}

    @app.post('/api/v1/projects/{project_id}/topics/{topic_id}/messages', status_code=201)
    def create_message(project_id: int, topic_id: int, payload: MessageInput, request: Request, response: Response, person: Person, db: DB):
        db.execute('BEGIN IMMEDIATE')
        topic_access(db, project_id, topic_id, person)
        check_tags(person, payload.tags)
        key = request.headers.get('idempotency-key')
        fingerprint = hashlib.sha256(json.dumps({'topic_id':topic_id, **payload.model_dump()}, sort_keys=True).encode()).hexdigest()
        if key:
            if len(key)>180:
                raise HTTPException(422, 'Idempotency key is too long.')
            key = 'chat:'+key
            previous = db.execute('SELECT * FROM idempotency WHERE actor=? AND project_id=? AND key=?', (person['actor'], project_id, key)).fetchone()
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise HTTPException(409, 'That idempotency key was used with different content.')
                response.headers['Idempotency-Replayed'] = 'true'
                return json.loads(previous['response'])
        message = add_message(db, project_id, topic_id, payload, person)
        if key:
            db.execute('INSERT INTO idempotency VALUES (?,?,?,?,?)', (person['actor'], project_id, key, fingerprint, json.dumps(message)))
        return message

    @app.get('/api/v1/projects/{project_id}/messages/{message_id}')
    def message(project_id: int, message_id: int, person: Person, db: DB):
        project_access(db, project_id, person)
        return message_dict(db, get_item(db, project_id, message_id))

    @app.patch('/api/v1/projects/{project_id}/messages/{message_id}')
    def edit_message(project_id: int, message_id: int, payload: MessageUpdate, person: Person, db: DB):
        db.execute('BEGIN IMMEDIATE')
        project = project_access(db, project_id, person)
        row = get_item(db, project_id, message_id)
        if person['kind']=='agent':
            allowed = row['agent_id']==person['agent_id'] and row['kind']!='question' and row['assessment']=='unreviewed'
        else:
            allowed = project['owner_id']==person['user_id'] or (row['author_id']==person['user_id'] and row['agent_id'] is None)
        if not allowed:
            raise HTTPException(403, 'You can edit your own messages. Owners can edit all messages.')
        if payload.revision != row['revision']:
            raise HTTPException(409, 'The message changed. Reopen it and try again.')
        if 'reply_to_id' in payload.model_fields_set and payload.reply_to_id != item_dict(db, row)['reply_to_id']:
            raise HTTPException(422, 'The reply target cannot be changed after sending.')
        sync_tags(db, row, payload.tags, person)
        db.execute('UPDATE items SET body=?,title=?,model=?,run_id=?,archived=? WHERE id=?',
                   (payload.body, payload.title, payload.model, payload.run_id, int(payload.archived), message_id))
        if payload.archived and db.execute('DELETE FROM main_questions WHERE item_id=?', (message_id,)).rowcount:
            db.execute('UPDATE projects SET revision=revision+1 WHERE id=?', (project_id,))
        touch(db, message_id, row['topic_id'])
        record(db, message_id, person)
        return message_dict(db, get_item(db, project_id, message_id))

    @app.patch('/api/v1/projects/{project_id}/messages/{message_id}/tags')
    def tag_message(project_id: int, message_id: int, payload: TagsInput, person: Person, db: DB):
        db.execute('BEGIN IMMEDIATE')
        project_access(db, project_id, person)
        row = get_item(db, project_id, message_id)
        if person['kind']=='agent' and row['agent_id']!=person['agent_id']:
            raise HTTPException(403, 'Agents can tag only their own messages.')
        if row['revision'] != payload.revision:
            raise HTTPException(409, 'The message changed. Reopen it and try again.')
        sync_tags(db, row, payload.tags, person)
        touch(db, message_id, row['topic_id'])
        record(db, message_id, person)
        return message_dict(db, get_item(db, project_id, message_id))

    @app.post('/api/v1/projects/{project_id}/messages/{message_id}/move')
    def move(project_id: int, message_id: int, payload: MoveInput, person: Person, db: DB):
        db.execute('BEGIN IMMEDIATE')
        project_access(db, project_id, person)
        source = get_item(db, project_id, message_id)
        if source['revision'] != payload.revision:
            raise HTTPException(409, 'The message changed. Reopen it and try again.')
        target = topic_access(db, project_id, payload.target_topic_id, person) if payload.target_topic_id else new_topic(db, project_id, payload.new_topic_title)
        ids = move_messages(db, project_id, source, target['id'], payload.mode, person)
        return {'topic_id': target['id'], 'message_ids': ids}

    @app.post('/api/v1/projects/{project_id}/topics/{topic_id}/move-messages')
    def move_selected(project_id: int, topic_id: int, payload: SelectedMove, person: Person, db: DB):
        human(person)
        db.execute('BEGIN IMMEDIATE')
        topic_access(db, project_id, topic_id, person)
        for selected in payload.messages:
            row = get_item(db, project_id, selected.id)
            if row['topic_id']!=topic_id or row['revision']!=selected.revision:
                raise HTTPException(409, 'A selected message changed or moved. Refresh and select again.')
        target = topic_access(db, project_id, payload.target_topic_id, person) if payload.target_topic_id else new_topic(db, project_id, payload.new_topic_title)
        source = get_item(db, project_id, payload.messages[0].id)
        ids = move_messages(db, project_id, source, target['id'], 'selected', person, [m.id for m in payload.messages])
        return {'topic_id':target['id'],'message_ids':ids}


    @app.get('/api/v1/projects/{project_id}/overview')
    def overview(project_id: int, person: Person, db: DB):
        project = project_dict(db, project_access(db, project_id, person), person, True)
        latest = db.execute('SELECT * FROM items WHERE project_id=? AND archived=0 ORDER BY created_at DESC,id DESC LIMIT 15', (project_id,)).fetchall()
        grouped = {}
        for row in latest:
            tid = row['topic_id']
            if tid not in grouped:
                title = db.execute('SELECT title FROM topics WHERE id=?', (tid,)).fetchone()['title']
                grouped[tid] = {'topic_id':tid, 'title':title, 'messages':[]}
            grouped[tid]['messages'].insert(0, message_dict(db, row))
        return {'project':project,'recent_topics':list(grouped.values())}
