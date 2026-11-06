import base64
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pycrdt import Doc, Text
import test_api as fixtures
from file_api import (atomic_json, close_edit_window, ensure_repo, git, local_journal,
                      repo_lock, save_file_bytes)
from editor_api import apply_update, document


class EditorTests(unittest.TestCase):
    setUp = fixtures.NotebookTests.setUp
    tearDown = fixtures.NotebookTests.tearDown
    path_for = fixtures.NotebookTests.path_for
    collaborator = fixtures.NotebookTests.collaborator
    agent = fixtures.NotebookTests.agent

    def upload(self, path='main.typ', text='= Manuscript\n', etag=None):
        r=self.owner.put(self.path_for('/files/content'),params={'path':path},content=text.encode(),
                         headers={'If-Match':etag} if etag else {'If-None-Match':'*'})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def repo(self):
        return ensure_repo(self.app.state.file_root,self.pid)

    def state(self):
        return document(self.repo(),'main.typ')

    def edit(self, state, text, window='one', author='Ada'):
        doc=Doc();doc.apply_update(base64.b64decode(state['update']))
        source=doc.get('source',type=Text);source+=text
        return apply_update(self.repo(),'main.typ',state['generation'],base64.b64encode(doc.get_update()).decode(),
                            {'name':author,'actor':'human:1'},window)

    def pending(self):
        return self.owner.get(self.path_for('/files')).json()['history']['pending']

    def test_edit_windows_group_saves_without_creating_commits(self):
        self.upload();self.owner.post(self.path_for('/files/commit'),json={})
        head=git(self.repo(),'rev-parse','HEAD').stdout
        state=self.state()
        for text in ['one','two','three']:
            state=self.edit(state,text)
        self.assertEqual(len(self.pending()),1)
        self.assertEqual(self.pending()[0]['files'],['main.typ'])
        self.assertEqual(git(self.repo(),'rev-parse','HEAD').stdout,head)
        close_edit_window(self.repo(),'one','focus')
        self.edit(state,'four','two')
        self.assertEqual(len(self.pending()),2)
        self.assertTrue(self.pending()[0]['closed'])
        self.assertEqual(self.pending()[0]['close_reason'],'focus')
        self.owner.post(self.path_for('/files/commit'),json={})
        self.assertFalse(self.pending())

    def test_concurrent_crdt_updates_and_external_replacement(self):
        self.upload();state=self.state()
        first=self.edit(state,'A','ada')
        second=self.edit(state,'B','bob','Bob')
        content=self.owner.get(self.path_for('/files/content'),params={'path':'main.typ'}).text
        self.assertIn('A',content);self.assertIn('B',content)
        self.upload(text='= External\n',etag=second['etag'])
        with self.assertRaises(HTTPException) as caught:
            self.edit(first,'late')
        self.assertEqual(caught.exception.status_code,409)
        self.assertEqual(self.owner.get(self.path_for('/files/content'),params={'path':'main.typ'}).text,'= External\n')

    def test_snapshot_includes_pending_files_without_committing(self):
        self.upload();self.upload('sections/proof.typ','Proof')
        head=git(self.repo(),'rev-parse','HEAD').stdout
        snapshot=self.owner.get(self.path_for('/editor/snapshot')).json()
        self.assertEqual({x['path'] for x in snapshot['files']},{'main.typ','sections/proof.typ'})
        self.assertEqual(git(self.repo(),'rev-parse','HEAD').stdout,head)
        self.assertEqual(snapshot['tree'],git(self.repo(),'write-tree').stdout.decode().strip())
        self.assertEqual(len(self.pending()),2)
        other=self.owner.post('/api/v1/projects',json={'title':'Other'}).json()['id']
        agent,_=self.agent(scope='read')
        self.assertEqual(agent.get(self.path_for('/editor/snapshot',other)).status_code,404)

    def test_interrupted_save_recovers_before_next_file_operation(self):
        self.upload();repo=self.repo()
        with patch('file_api.recover_file_save',side_effect=RuntimeError('crash')):
            with self.assertRaises(RuntimeError):
                save_file_bytes(repo,'main.typ',b'= Recovered',{'name':'Ada','actor':'human:1'},window_id='recover')
        self.assertTrue((repo/'.git/file-save.json').exists())
        content=self.owner.get(self.path_for('/files/content'),params={'path':'main.typ'})
        self.assertEqual(content.content,b'= Recovered')
        self.assertFalse((repo/'.git/file-save.json').exists())
        self.assertEqual(sum(x.get('window_id')=='recover' for x in self.pending()),1)

    def socket(self):
        return self.owner.websocket_connect(self.path_for('/editor/ws'),headers={'origin':'http://testserver'})

    def read_until(self, ws, kind):
        for _ in range(30):
            message=ws.receive_json()
            if message['type']=='ping':ws.send_json({'type':'pong'})
            if message['type']==kind:return message
        self.fail('Expected WebSocket message '+kind)

    def join(self, ws):
        ws.send_json({'csrf':self.owner.headers['X-CSRF-Token']});self.read_until(ws,'ready')
        ws.send_json({'type':'join','path':'main.typ'});return self.read_until(ws,'document')

    def send_edit(self, ws, state, suffix, seq=1):
        doc=Doc();doc.apply_update(base64.b64decode(state['update']))
        text=doc.get('source',type=Text);text+=suffix
        ws.send_json({'type':'update','path':'main.typ','generation':state['generation'],
                      'update':base64.b64encode(doc.get_update()).decode(),'seq':seq})
        return self.read_until(ws,'saved')

    def test_websocket_focus_disconnect_and_read_only_activity(self):
        self.upload();self.owner.post(self.path_for('/files/commit'),json={})
        with self.owner:
            with self.socket() as ws:
                state=self.join(ws)
                ws.send_json({'type':'activity'})
                self.assertFalse(self.pending())
                self.send_edit(ws,state,'first')
                ws.send_json({'type':'end-window','reason':'focus'});self.read_until(ws,'window-ended')
                self.assertEqual(self.pending()[0]['close_reason'],'focus')
                ws.send_json({'type':'join','path':'main.typ'});state=self.read_until(ws,'document')
                self.send_edit(ws,state,'second',2)
            deadline=time.monotonic()+3
            while not self.pending()[-1].get('closed') and time.monotonic()<deadline:time.sleep(.05)
            self.assertEqual(self.pending()[-1]['close_reason'],'disconnect')
            self.assertEqual(len(self.pending()),2)

    def test_idle_cooldown_extends_on_scroll_activity(self):
        self.upload();self.owner.post(self.path_for('/files/commit'),json={})
        self.app.state.editor.idle_seconds=.7
        with self.owner:
            with self.socket() as ws:
                state=self.join(ws);self.send_edit(ws,state,'text')
                for _ in range(3):
                    time.sleep(.3);ws.send_json({'type':'activity'})
                self.assertFalse(self.pending()[0].get('closed'))
                message=self.read_until(ws,'window-ended')
                self.assertEqual(message['reason'],'idle')

    def test_websocket_rejects_wrong_origin_and_csrf(self):
        self.upload()
        with self.assertRaises(Exception):
            with self.owner.websocket_connect(self.path_for('/editor/ws'),headers={'origin':'https://foreign.test'}):pass
        with self.socket() as ws:
            ws.send_json({'csrf':'wrong'})
            self.assertEqual(ws.receive_json()['type'],'error')


if __name__=='__main__':unittest.main()
