import concurrent.futures
from contextlib import closing
from pathlib import Path
import sqlite3
import shutil
import stat
import time
import uuid
import unittest

from fastapi.testclient import TestClient
from app import create_app, now


class NotebookTests(unittest.TestCase):
    def setUp(self):
        Path('.checks').mkdir(exist_ok=True)
        self.path = Path('.checks') / f'test-{uuid.uuid4().hex}.db'
        self.app = create_app(self.path)
        self.owner = TestClient(self.app)
        self.clients = [self.owner]
        result = self.owner.post('/api/v1/auth/setup', json={
            'name': 'Ada', 'email': 'ada@example.org', 'password': 'a secure password', 'sample_projects': False})
        self.assertEqual(result.status_code, 201, result.text)
        self.owner.headers['X-CSRF-Token'] = result.json()['csrf']
        self.project = self.owner.post('/api/v1/projects', json={'title': 'First project', 'objective': 'Explore the first question.'}).json()
        self.pid = self.project['id']

    def tearDown(self):
        for client in self.clients:
            client.close()
        for suffix in ('', '-wal', '-shm'):
            Path(str(self.path) + suffix).unlink(missing_ok=True)
        files = self.app.state.file_root.resolve()
        self.assertTrue(files.is_relative_to(Path('.checks').resolve()))
        if files.exists():
            def remove_readonly(function, path, error):
                Path(path).chmod(stat.S_IWRITE | stat.S_IREAD)
                # Git and Windows file watchers can briefly retain a directory handle.
                for attempt in range(10):
                    try:
                        function(path)
                        return
                    except PermissionError:
                        if attempt == 9:
                            raise
                        time.sleep(.05 * (attempt + 1))
            shutil.rmtree(files, onexc=remove_readonly)

    def path_for(self, suffix='', pid=None):
        return f'/api/v1/projects/{pid or self.pid}' + suffix

    def collaborator(self):
        token = self.owner.post(self.path_for('/invitations'), json={'email': 'bob@example.org'}).json()['token']
        client = TestClient(self.app)
        self.clients.append(client)
        response = client.post('/api/v1/auth/register', json={'token': token, 'name': 'Bob', 'email': 'bob@example.org', 'password': 'another password'})
        self.assertEqual(response.status_code, 201, response.text)
        client.headers['X-CSRF-Token'] = response.json()['csrf']
        return client, response.json()['user']['id']

    def agent(self, client=None, scope='write'):
        result = (client or self.owner).post(self.path_for('/keys'), json={'name': 'Proof assistant', 'scope': scope})
        self.assertEqual(result.status_code, 201, result.text)
        agent = TestClient(self.app, headers={'Authorization': 'Bearer ' + result.json()['token']})
        self.clients.append(agent)
        return agent, result.json()['id']

    def item(self, client=None, **kwargs):
        kind=kwargs.pop('kind','note')
        labels=kwargs.pop('labels',[])
        data = {'title': 'An entry', 'body': 'Assumptions and evidence.',
                'tags':([] if kind=='note' else [kind])+labels, **kwargs}
        client=client or self.owner
        tid=client.get(self.path_for('/topics')).json()[0]['id']
        result = client.post(self.path_for(f'/topics/{tid}/messages'), json=data)
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()

    def update(self, item, **kwargs):
        keys = ('title', 'body', 'tags', 'model', 'run_id', 'revision', 'archived')
        return {**{key: item[key] for key in keys}, **kwargs}

    def legacy_note(self,title,body):
        with closing(sqlite3.connect(self.path)) as db:
            nid=db.execute('INSERT INTO project_notes(project_id,title,body,author_id,created_at) VALUES (?,?,?,?,?)',
                (self.pid,title,body,1,now())).lastrowid
            db.commit()
        return {'id':nid,'title':title,'body':body}

    def test_setup_is_single_use_and_password_login_logout(self):
        self.assertEqual(self.owner.post('/api/v1/auth/setup', json={'name': 'X', 'email': 'x@example.org', 'password': 'hello-world'}).status_code, 409)
        self.assertEqual(self.owner.post('/api/v1/auth/logout').status_code, 200)
        self.assertEqual(self.owner.get('/api/v1/projects').status_code, 401)
        self.assertEqual(self.owner.post('/api/v1/auth/login', json={'email': 'ada@example.org', 'password': 'wrong'}).status_code, 401)
        result = self.owner.post('/api/v1/auth/login', json={'email': 'ADA@EXAMPLE.ORG', 'password': 'a secure password'})
        self.assertEqual(result.status_code, 200)
        self.assertTrue(self.owner.get('/api/v1/auth/me').json()['csrf'])

    def test_csrf_origin_and_unauthenticated_access(self):
        self.assertEqual(TestClient(self.app).get(self.path_for()).status_code, 401)
        self.owner.headers.pop('X-CSRF-Token')
        self.assertEqual(self.owner.post('/api/v1/projects', json={'title': 'X', 'objective': 'Y'}).status_code, 403)
        self.assertEqual(self.owner.post('/api/v1/auth/login', headers={'Origin': 'https://evil.example'}, json={'email': 'ada@example.org', 'password': 'a secure password'}).status_code, 403)

    def test_collaborator_can_read_and_contribute_questions(self):
        bob, _ = self.collaborator()
        self.assertEqual(bob.get(self.path_for()).status_code, 200)
        question = self.item(bob, kind='question', title='A human question')
        self.assertEqual(question['author']['name'], 'Bob')
        self.assertEqual(bob.post(self.path_for('/invitations'), json={'email': 'eve@example.org'}).status_code, 403)

    def test_invitation_email_expiry_and_single_use(self):
        invitation = self.owner.post(self.path_for('/invitations'), json={'email': 'bob@example.org'}).json()
        other = TestClient(self.app)
        self.clients.append(other)
        payload = {'token': invitation['token'], 'name': 'Bob', 'email': 'wrong@example.org', 'password': 'another password'}
        self.assertEqual(other.post('/api/v1/auth/register', json=payload).status_code, 403)
        payload['email'] = 'bob@example.org'
        self.assertEqual(other.post('/api/v1/auth/register', json=payload).status_code, 201)
        self.assertEqual(other.post('/api/v1/auth/register', json=payload).status_code, 400)
        expired = self.owner.post(self.path_for('/invitations'), json={'email': 'eve@example.org'}).json()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE invitations SET expires_at='2000-01-01' WHERE used=0")
            db.commit()
        payload.update(token=expired['token'], email='eve@example.org')
        self.assertEqual(other.post('/api/v1/auth/register', json=payload).status_code, 400)

    def test_existing_human_can_accept_a_second_project_invitation(self):
        bob, _ = self.collaborator()
        project = self.owner.post('/api/v1/projects', json={'title': 'Private project', 'objective': 'Not inherited'}).json()
        self.assertEqual(bob.get(self.path_for(pid=project['id'])).status_code, 404)
        token = self.owner.post(self.path_for('/invitations', project['id']), json={'email': 'bob@example.org'}).json()['token']
        self.assertEqual(bob.post('/api/v1/invitations/accept', json={'token': token}).status_code, 200)
        self.assertEqual(bob.get(self.path_for(pid=project['id'])).status_code, 200)

    def test_create_private_project_with_invitations_and_no_objective(self):
        bob, _ = self.collaborator()
        created = self.owner.post('/api/v1/projects', json={
            'title': 'Private workspace',
            'collaborator_emails': [' BOB@example.org ', 'bob@example.org', 'ada@example.org', 'eve@example.org']})
        self.assertEqual(created.status_code, 201, created.text)
        project = created.json()
        self.assertEqual(project['objective'], '')
        self.assertEqual(project['member_count'], 1)
        self.assertEqual([i['email'] for i in project['invitations']], ['bob@example.org', 'eve@example.org'])
        private_path = self.path_for(pid=project['id'])
        for suffix in ('', '/topics', '/overview', '/files', '/members', '/export'):
            self.assertEqual(bob.get(private_path + suffix).status_code, 404, suffix)
        self.assertNotIn(project['id'], [p['id'] for p in bob.get('/api/v1/projects').json()])
        invitation = project['invitations'][0]
        self.assertEqual(bob.post('/api/v1/invitations/accept', json={'token': invitation['token']}).status_code, 200)
        self.assertEqual(bob.get(private_path).status_code, 200)
        self.assertNotIn('invitations', self.owner.get(private_path).json())
        self.assertNotIn(invitation['token'], self.owner.get('/api/v1/projects').text)

    def test_invalid_creation_invitation_does_not_create_project(self):
        before = self.owner.get('/api/v1/projects').json()
        response = self.owner.post('/api/v1/projects', json={
            'title': 'Invalid project', 'collaborator_emails': ['bob@example.org', 'invalid']})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.owner.get('/api/v1/projects').json(), before)

    def test_create_project_with_name_only(self):
        response = self.owner.post('/api/v1/projects', json={'title': 'Just a name'})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['invitations'], [])
        self.assertEqual(response.json()['objective'], '')

    def test_agent_cannot_create_reclassify_or_edit_questions(self):
        agent, _ = self.agent()
        tid=self.owner.get(self.path_for('/topics')).json()[0]['id']
        path=self.path_for(f'/topics/{tid}/messages')
        self.assertEqual(agent.post(path, json={'body': '?', 'tags':['question']}).status_code, 403)
        item = self.item(agent, kind='technique')
        self.assertEqual(agent.patch(self.path_for(f'/messages/{item["id"]}'), json=self.update(item, tags=['question'])).status_code, 403)
        question = self.item(kind='question')
        self.assertEqual(agent.patch(self.path_for(f'/messages/{question["id"]}'), json=self.update(question)).status_code, 403)
        self.assertEqual(agent.post(self.path_for('/dashboard-questions'), json={'body':'Blocked'}).status_code, 403)
        self.assertEqual(agent.post(path, json={'body': 'Claim', 'assessment': 'supported'}).status_code, 422)

    def test_agent_scope_revocation_and_attribution(self):
        agent, key_id = self.agent()
        item = self.item(agent, kind='technique', model='self-reported model')
        self.assertEqual(item['author'], {'name': 'Proof assistant', 'kind': 'agent'})
        second = self.owner.post('/api/v1/projects', json={'title': 'Second', 'objective': 'Separate access'}).json()
        self.assertEqual(agent.get(self.path_for(pid=second['id'])).status_code, 404)
        self.assertEqual(len(agent.get('/api/v1/projects').json()), 1)
        readonly, _ = self.agent(scope='read')
        tid=self.owner.get(self.path_for('/topics')).json()[0]['id']
        self.assertEqual(readonly.get(self.path_for(f'/topics/{tid}/messages')).status_code, 200)
        self.assertEqual(readonly.post(self.path_for(f'/topics/{tid}/messages'), json={'body': 'Y'}).status_code, 403)
        self.owner.delete(self.path_for(f'/keys/{key_id}'))
        self.assertEqual(agent.get(self.path_for('/topics')).status_code, 401)

    def test_member_removal_revokes_agent_access_and_preserves_items(self):
        bob, uid = self.collaborator()
        agent, _ = self.agent(bob)
        item = self.item(agent)
        self.assertEqual(self.owner.delete(self.path_for(f'/members/{uid}')).status_code, 200)
        self.assertEqual(bob.get(self.path_for()).status_code, 404)
        self.assertEqual(agent.get(self.path_for()).status_code, 401)
        self.assertEqual(self.owner.get(self.path_for(f'/messages/{item["id"]}')).status_code, 200)
        self.assertEqual(self.owner.delete(self.path_for('/members/1')).status_code, 422)

    def test_linked_projects_are_symmetric_and_do_not_leak_private_targets(self):
        bob, _ = self.collaborator()
        other = self.owner.post('/api/v1/projects', json={'title': 'Secret title', 'objective': 'Secret objective'}).json()
        self.owner.post(self.path_for('/linked-projects'), json={'project_id': other['id']})
        self.assertEqual(self.owner.get(self.path_for(pid=other['id'])).json()['linked_projects'][0]['id'], self.pid)
        visible = bob.get(self.path_for()).json()
        self.assertEqual(visible['linked_projects'], [])
        self.assertNotIn('Secret', str(visible))
        self.assertEqual(bob.post(self.path_for('/linked-projects'), json={'project_id': other['id']}).status_code, 404)
        self.assertEqual(self.owner.post(self.path_for('/linked-projects'), json={'project_id': self.pid}).status_code, 422)


    def test_idempotent_submission_and_concurrent_retries(self):
        payload = {'title': 'A retried submission', 'body': 'Only one item'}
        tid=self.owner.get(self.path_for('/topics')).json()[0]['id']
        path=self.path_for(f'/topics/{tid}/messages')
        def submit(_):
            return self.owner.post(path, json=payload, headers={'Idempotency-Key': 'same-key'})
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            replies = list(pool.map(submit, range(3)))
        self.assertEqual([r.status_code for r in replies], [201]*3)
        self.assertEqual(len({r.json()['id'] for r in replies}), 1)
        self.assertEqual(len(self.owner.get(path).json()['messages']), 1)
        self.assertEqual(self.owner.post(path, json={**payload, 'title': 'Changed'}, headers={'Idempotency-Key': 'same-key'}).status_code, 409)



    def test_revision_history_edit_permissions_and_conflict(self):
        entry = self.item()
        bob, _ = self.collaborator()
        path = self.path_for(f'/messages/{entry["id"]}')
        self.assertEqual(bob.patch(path, json=self.update(entry, title='Tampered')).status_code, 403)
        self.assertEqual(self.owner.patch(path, json=self.update(entry, title='Revised')).status_code, 200)
        self.assertEqual(self.owner.patch(path, json=self.update(entry, title='Stale')).status_code, 409)
        self.assertEqual(self.owner.get(path).json()['title'],'Revised')
        self.assertEqual(self.owner.get(self.path_for(f'/items/{entry["id"]}/history')).status_code,404)

    def test_reopening_database_preserves_data_and_export_excludes_secrets(self):
        self.item()
        agent, _ = self.agent()
        with TestClient(create_app(self.path)) as client:
            login = client.post('/api/v1/auth/login', json={'email': 'ada@example.org', 'password': 'a secure password'})
            self.assertEqual(login.status_code, 200)
            data = client.get(self.path_for('/export')).json()
            self.assertEqual(len(data['items']), 1)
            self.assertNotIn('token_hash', str(data))
            self.assertNotIn('password', str(data))

    def test_password_whitespace_is_preserved(self):
        bob_token = self.owner.post(self.path_for('/invitations'), json={'email': 'space@example.org'}).json()['token']
        client = TestClient(self.app)
        self.clients.append(client)
        password = '  significant spaces  '
        self.assertEqual(client.post('/api/v1/auth/register', json={'name': 'Space', 'email': 'space@example.org', 'password': password, 'token': bob_token}).status_code, 201)
        self.assertEqual(client.post('/api/v1/auth/login', json={'email': 'space@example.org', 'password': password.strip()}).status_code, 401)
        self.assertEqual(client.post('/api/v1/auth/login', json={'email': 'space@example.org', 'password': password}).status_code, 200)


if __name__ == '__main__':
    unittest.main()
