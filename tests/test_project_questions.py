import unittest
from contextlib import closing
from fastapi.testclient import TestClient
from app import create_app
import test_api as fixtures


class ProjectQuestionTests(unittest.TestCase):
    setUp=fixtures.NotebookTests.setUp
    tearDown=fixtures.NotebookTests.tearDown
    path_for=fixtures.NotebookTests.path_for
    agent=fixtures.NotebookTests.agent
    collaborator=fixtures.NotebookTests.collaborator
    item=fixtures.NotebookTests.item
    update=fixtures.NotebookTests.update

    def questions(self):
        return self.owner.get(self.path_for()).json()['dashboard_questions']

    def test_independent_crud_permissions_conflicts_and_export(self):
        path=self.path_for('/dashboard-questions')
        self.assertEqual(self.owner.post(path,json={'body':'   '}).status_code,422)
        agent,_=self.agent()
        self.assertEqual(agent.post(path,json={'body':'Blocked'}).status_code,403)
        collaborator,_=self.collaborator()
        response=collaborator.post(path,json={'body':'Can $x$ be bounded?'})
        self.assertEqual(response.status_code,201,response.text)
        q=response.json()
        tid=self.owner.get(self.path_for('/topics')).json()[0]['id']
        self.assertEqual(self.owner.get(self.path_for(f'/topics/{tid}/messages')).json()['messages'],[])
        self.assertEqual(self.questions()[0]['body'],q['body'])
        self.assertEqual(self.owner.get(self.path_for('/overview')).json()['project']['dashboard_questions'],self.questions())
        self.assertEqual(self.owner.get(self.path_for('/export')).json()['project']['dashboard_questions'],self.questions())
        other=self.owner.post('/api/v1/projects',json={'title':'Other'}).json()
        self.assertEqual(self.owner.patch(self.path_for('/dashboard-questions/'+str(q['id']),other['id']),json={'body':'Wrong project','revision':1}).status_code,404)
        self.assertEqual(collaborator.post(self.path_for('/dashboard-questions',other['id']),json={'body':'No access'}).status_code,404)
        changed=self.owner.patch(path+'/'+str(q['id']),json={'body':'Independent edit','revision':1})
        self.assertEqual(changed.status_code,200,changed.text)
        self.assertEqual(self.owner.patch(path+'/'+str(q['id']),json={'body':'Stale','revision':1}).status_code,409)
        self.assertEqual(self.owner.delete(path+'/'+str(q['id'])+'?revision=1').status_code,409)
        self.assertEqual(self.owner.delete(path+'/'+str(q['id'])+'?revision=2').status_code,204)
        self.assertEqual(self.questions(),[])

    def test_legacy_pins_copy_once_and_survive_message_changes(self):
        message=self.item(kind='question',title='Legacy title',body='Legacy body')
        import sqlite3
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('INSERT INTO main_questions VALUES (?,?,?)',(self.pid,message['id'],0))
            db.execute("DELETE FROM question_migrations WHERE name='independent-questions'")
            db.commit()
        client=TestClient(create_app(self.path));self.clients.append(client)
        copied=self.questions()
        self.assertEqual(len(copied),1)
        self.assertEqual(copied[0]['body'],'Legacy title\n\nLegacy body')
        self.owner.patch(self.path_for('/messages/'+str(message['id'])),json=self.update(message,archived=True))
        self.assertEqual(self.questions(),copied)
        client2=TestClient(create_app(self.path));self.clients.append(client2)
        self.assertEqual(self.questions(),copied)
