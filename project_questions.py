"""Independent dashboard questions, with one-time copies of legacy pins."""
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuestionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    body: str = Field(min_length=1, max_length=50000)

    @field_validator('body')
    @classmethod
    def clean_body(cls, body):
        if not body.strip():
            raise ValueError('Enter a question.')
        return body.strip()


class QuestionUpdate(QuestionInput):
    revision: int = Field(gt=0)


def migrate_questions(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS dashboard_questions (
      id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
      body TEXT NOT NULL, position INTEGER NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS question_migrations (name TEXT PRIMARY KEY);
    """)
    if not db.execute("SELECT 1 FROM question_migrations WHERE name='independent-questions'").fetchone():
        db.execute("""INSERT INTO dashboard_questions(project_id,body,position,created_at,updated_at)
          SELECT q.project_id,CASE WHEN i.title='' THEN i.body WHEN i.body='' THEN i.title
            ELSE i.title || char(10) || char(10) || i.body END,q.position,i.created_at,i.updated_at
          FROM main_questions q JOIN items i ON i.id=q.item_id ORDER BY q.project_id,q.position""")
        db.execute("INSERT INTO question_migrations VALUES ('independent-questions')")


def list_questions(db, project_id):
    return [dict(row) for row in db.execute(
        'SELECT * FROM dashboard_questions WHERE project_id=? ORDER BY position,id', (project_id,))]


def install_questions(app, *, DB, Person, project_access, human, project_event, now):
    def question(db, project_id, question_id):
        row=db.execute('SELECT * FROM dashboard_questions WHERE project_id=? AND id=?',
                       (project_id,question_id)).fetchone()
        if not row:
            raise HTTPException(404,'Question not found.')
        return row

    @app.post('/api/v1/projects/{project_id}/dashboard-questions',status_code=201)
    def create(project_id: int, payload: QuestionInput, person: Person, db: DB):
        human(person)
        db.execute('BEGIN IMMEDIATE')
        project_access(db,project_id,person)
        position=db.execute('SELECT COALESCE(MAX(position),-1)+1 FROM dashboard_questions WHERE project_id=?',(project_id,)).fetchone()[0]
        stamp=now()
        cur=db.execute('INSERT INTO dashboard_questions(project_id,body,position,created_at,updated_at) VALUES (?,?,?,?,?)',
                       (project_id,payload.body,position,stamp,stamp))
        project_event(db,project_id,person,'question_created',{'id':cur.lastrowid,'body':payload.body})
        return dict(question(db,project_id,cur.lastrowid))

    @app.patch('/api/v1/projects/{project_id}/dashboard-questions/{question_id}')
    def update(project_id: int, question_id: int, payload: QuestionUpdate, person: Person, db: DB):
        human(person)
        db.execute('BEGIN IMMEDIATE')
        project_access(db,project_id,person)
        row=question(db,project_id,question_id)
        if row['revision']!=payload.revision:
            raise HTTPException(409,'This question changed. Reopen it and try again.')
        db.execute('UPDATE dashboard_questions SET body=?,revision=revision+1,updated_at=? WHERE id=?',
                   (payload.body,now(),question_id))
        project_event(db,project_id,person,'question_updated',{'id':question_id,'body':payload.body})
        return dict(question(db,project_id,question_id))

    @app.delete('/api/v1/projects/{project_id}/dashboard-questions/{question_id}',status_code=204)
    def delete(project_id: int, question_id: int, revision: int, person: Person, db: DB):
        human(person)
        db.execute('BEGIN IMMEDIATE')
        project_access(db,project_id,person)
        row=question(db,project_id,question_id)
        if row['revision']!=revision:
            raise HTTPException(409,'This question changed. Reopen it and try again.')
        project_event(db,project_id,person,'question_deleted',dict(row))
        db.execute('DELETE FROM dashboard_questions WHERE id=?',(question_id,))
