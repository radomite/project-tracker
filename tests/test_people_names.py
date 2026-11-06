from contextlib import closing
import sqlite3
import unittest
from fastapi.testclient import TestClient
import test_api as fixtures


class PeopleNameTests(unittest.TestCase):
    setUp=fixtures.NotebookTests.setUp
    tearDown=fixtures.NotebookTests.tearDown
    path_for=fixtures.NotebookTests.path_for
    collaborator=fixtures.NotebookTests.collaborator

    def test_people_are_project_members_only(self):
        colleague,uid=self.collaborator()
        people=self.owner.get(self.path_for()).json()['people']
        self.assertEqual({p['name'] for p in people},{'Ada','Bob'})
        self.assertEqual(sum(p['is_owner'] for p in people),1)
        self.assertTrue(all('email' not in p for p in people))
        other=self.owner.post('/api/v1/projects',json={'title':'Separate'}).json()
        self.assertEqual([p['name'] for p in other['people']],['Ada'])
        self.assertEqual(colleague.get(self.path_for(pid=other['id'])).status_code,404)
        self.owner.delete(self.path_for('/members/'+str(uid)))
        self.assertEqual([p['name'] for p in self.owner.get(self.path_for()).json()['people']],['Ada'])

    def test_login_updates_name_after_authentication_and_validates_it(self):
        client=TestClient(self.app);self.clients.append(client)
        credentials={'email':'ada@example.org','password':'a secure password'}
        result=client.post('/api/v1/auth/login',json={**credentials,'name':'Ada Lovelace'})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['user']['name'],'Ada Lovelace')
        self.assertEqual(self.owner.get(self.path_for()).json()['people'][0]['name'],'Ada Lovelace')
        self.assertEqual(client.post('/api/v1/auth/login',json={**credentials,'password':'wrong','name':'Wrong Name'}).status_code,401)
        for name in ['','   ','ada@example.org','12345','<Ada>','Ada\nLovelace']:
            self.assertEqual(client.post('/api/v1/auth/login',json={**credentials,'name':name}).status_code,422,name)
        self.assertEqual(self.owner.get('/api/v1/auth/me').json()['user']['name'],'Ada Lovelace')
        self.assertEqual(client.post('/api/v1/auth/login',json=credentials).status_code,200)

    def test_legacy_invalid_name_needs_correction_and_registration_rejects_email_names(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE users SET name='ada@example.org' WHERE email='ada@example.org'")
            db.commit()
        client=TestClient(self.app);self.clients.append(client)
        credentials={'email':'ada@example.org','password':'a secure password'}
        self.assertEqual(client.post('/api/v1/auth/login',json=credentials).status_code,422)
        self.assertEqual(client.post('/api/v1/auth/login',json={**credentials,'name':'Ada'}).status_code,200)
        token=self.owner.post(self.path_for('/invitations'),json={'email':'eva@example.org'}).json()['token']
        registration={'token':token,'email':'eva@example.org','password':'a strong password'}
        self.assertEqual(client.post('/api/v1/auth/register',json={**registration,'name':'eva@example.org'}).status_code,422)
        self.assertEqual(client.post('/api/v1/auth/register',json={**registration,'name':'Éva Nagy'}).status_code,201)
