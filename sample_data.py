"""Optional, explicitly illustrative projects for exploring the interface."""
import json
from datetime import datetime, timedelta, timezone


def seed(db, user_id, insert_item):
    from app import ItemInput

    user = db.execute('SELECT name FROM users WHERE id=?', (user_id,)).fetchone()
    person = {'user_id': user_id, 'name': user['name'], 'agent_id': None}
    projects = []
    for title, objective, description in [
        ('Graph invariants & counting',
         'Understand which structural information a family of counting invariants can recover.',
         'Illustrative project. Explore the workflow by adding questions, recording approaches, and linking evidence. These entries are examples, not research claims.'),
        ('Algebraic methods',
         'Collect algebraic tools that might help with exact counting problems.',
         'Illustrative project. A shared notebook for techniques, examples, and obstacles.'),
        ('Small-instance experiments',
         'Use carefully bounded experiments to test conjectures and find counterexamples.',
         'Illustrative project. Finite checks provide evidence; they do not establish a general theorem.'),
    ]:
        cur = db.execute('INSERT INTO projects(title,objective,description,sample,owner_id,created_at) VALUES (?,?,?,1,?,?)',
                         (title, objective, description, user_id, datetime.now(timezone.utc).isoformat()))
        projects.append(cur.lastrowid)
        db.execute('INSERT INTO members VALUES (?,?)', (cur.lastrowid, user_id))
    p, algebra, experiments = projects

    def add(project, **kwargs):
        return insert_item(db, project, ItemInput(**kwargs), person)['id']

    q1 = add(p, kind='question', title='Which invariants distinguish the examples?',
             body='Start with a precise family of invariants and a small collection of graphs.\n\nWhat information does equality of these invariants preserve? Record assumptions explicitly.', status='in_progress')
    q2 = add(p, kind='question', title='Can we turn the counting identity into an algorithm?',
             body='Look for an exact procedure with a clearly stated input model and running-time bound.\n\nA useful identity is a starting point; we still need to account for the cost of evaluating it.')
    t = add(p, kind='technique', title='Organize the calculation by a change of basis',
            body='**Illustrative approach.** Write the quantities as vectors indexed by the chosen test objects. A change of basis may expose dependencies.\n\nFor a candidate matrix $M$, first check whether $\\det(M) \\ne 0$ under the stated assumptions.',
            labels=['promising'], links=[{'target_id': q1, 'relation': 'follows_up'}])
    add(p, kind='observation', title='The argument needs a uniform invertibility bound',
        body='Checking invertibility on a few examples does not prove it for the full family.\n\nRecord the missing hypothesis here before extending the argument.',
        labels=['roadblock'], links=[{'target_id': t, 'relation': 'follows_up'}])
    add(p, kind='experiment', title='A small test suite for candidate identities',
        body='Plan: enumerate small instances, compute both sides exactly, and save counterexamples.\n\n- Specify the enumeration bound.\n- Keep exact arithmetic.\n- Record scripts and commit references.\n\nNo experiments have actually been run for this sample entry.', links=[{'target_id': q1, 'relation': 'follows_up'}])
    add(p, kind='solution', title='A direct interpolation attempt',
        body='**Illustrative failed approach.** The proposed interpolation uses more evaluation points than the available information supports.\n\nThe missing evaluations are the reason this attempt does not settle the question.',
        labels=['failed'], assessment='refuted', status='closed', links=[{'target_id': q2, 'relation': 'answers'}])
    aq = add(algebra, kind='question', title='Which algebraic tools preserve an exact complexity bound?',
             body='Track degree, coefficient size, and evaluation cost separately.')
    add(algebra, kind='technique', title='Keep a coefficient-size ledger', body='For each transformation, record the number of variables, the degree, and coefficient bit lengths.', labels=['promising'])
    eq = add(experiments, kind='question', title='What is the smallest informative test family?',
             body='Choose examples that separate hypotheses rather than simply increasing the number of tests.')
    for project, ids in [(p, [q1, q2]), (algebra, [aq]), (experiments, [eq])]:
        db.executemany('INSERT INTO main_questions VALUES (?,?,?)', [(project, item, i) for i, item in enumerate(ids)])
        for position, item in enumerate(ids):
            row = db.execute('SELECT * FROM items WHERE id=?', (item,)).fetchone()
            body = row['title'] + ('\n\n' + row['body'] if row['body'] else '')
            db.execute('INSERT INTO dashboard_questions(project_id,body,position,created_at,updated_at) VALUES (?,?,?,?,?)',
                       (project,body,position,row['created_at'],row['updated_at']))
    db.executemany('INSERT INTO project_links VALUES (?,?)', [(p, algebra), (p, experiments)])
    # Give the sample feed a readable chronology without implying actual research activity.
    for i, row in enumerate(db.execute('SELECT id FROM items ORDER BY id').fetchall()):
        stamp = (datetime.now(timezone.utc) - timedelta(hours=20 - i * 2)).isoformat(timespec='microseconds')
        db.execute('UPDATE items SET created_at=?,updated_at=? WHERE id=?', (stamp, stamp, row['id']))
        snapshot = json.loads(db.execute('SELECT snapshot FROM history WHERE item_id=?', (row['id'],)).fetchone()[0])
        snapshot.update(created_at=stamp, updated_at=stamp)
        db.execute('UPDATE history SET snapshot=?,created_at=? WHERE item_id=?', (json.dumps(snapshot), stamp, row['id']))
