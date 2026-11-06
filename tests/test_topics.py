from contextlib import closing
import json
from pathlib import Path
import sqlite3
import uuid
from fastapi.testclient import TestClient

from app import SCHEMA, create_app
import test_api as fixtures
import unittest


class ChatTests(unittest.TestCase):
    setUp = fixtures.NotebookTests.setUp
    tearDown = fixtures.NotebookTests.tearDown
    path_for = fixtures.NotebookTests.path_for
    collaborator = fixtures.NotebookTests.collaborator
    agent = fixtures.NotebookTests.agent
    item = fixtures.NotebookTests.item

    def general(self, client=None, pid=None):
        return next(t['id'] for t in (client or self.owner).get(self.path_for('/topics',pid)).json() if t['title_key']=='general')

    def topic(self, title='Alternative approach', pid=None):
        response=self.owner.post(self.path_for('/topics',pid),json={'title':title})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()['id']

    def message(self, body='A chat message', topic=None, client=None, **kwargs):
        response=(client or self.owner).post(self.path_for(f'/topics/{topic or self.general()}/messages'),json={'body':body,**kwargs})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def end(self, question, **kwargs):
        response=self.owner.post(self.path_for(f'/questions/{question["id"]}/open-ends'),json=kwargs or {'body':'A possible route'})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def pin(self, question):
        revision=self.owner.get(self.path_for()).json()['revision']
        response=self.owner.put(self.path_for('/main-questions'),json={'revision':revision,'question_ids':[question['id']]})
        self.assertEqual(response.status_code,200,response.text)

    def test_search_covers_accessible_projects_topics_tags_messages_and_text_notes(self):
        keyword='searchneedle'
        other=self.owner.post('/api/v1/projects',json={'title':'Searchneedle project','objective':'Find this project.'}).json()
        other_tid=self.topic('Searchneedle topic',pid=other['id'])
        current=self.message('Visible searchneedle message')
        tagged=self.message('A remaining case',tags=[keyword])
        foreign=self.owner.post(self.path_for(f'/topics/{other_tid}/messages',other['id']),json={'body':'Searchneedle from another project'}).json()
        note=self.owner.post(self.path_for('/notes'),json={'title':'A note','body':'searchneedle in a note'}).json()
        upload=self.owner.post(self.path_for('/notes/upload?filename=proof.typ'),content=b'= Proof\nsearchneedle in uploaded source')
        self.assertEqual(upload.status_code,201,upload.text)
        archived=self.message('searchneedle archived')
        self.owner.patch(self.path_for(f'/messages/{archived["id"]}'),json={'body':archived['body'],'revision':1,'archived':True})
        response=self.owner.get('/api/v1/search',params={'q':keyword})
        self.assertEqual(response.status_code,200,response.text)
        results=response.json()['results']
        identities={(r['kind'],r['id']) for r in results}
        for expected in [('project',other['id']),('topic',other_tid),('message',current['id']),('message',tagged['id']),('message',foreign['id']),('file','notes/A note.md'),('file','notes/proof.typ')]:
            self.assertIn(expected,identities)
        self.assertNotIn(('message',archived['id']),identities)
        scoped=self.owner.get('/api/v1/search',params={'q':keyword,'project_id':self.pid}).json()['results']
        self.assertTrue(scoped)
        self.assertTrue(all(r['project_id']==self.pid for r in scoped))
        first=self.owner.get('/api/v1/search',params={'q':keyword,'limit':2}).json()
        second=self.owner.get('/api/v1/search',params={'q':keyword,'limit':2,'offset':2}).json()
        self.assertTrue(first['has_more'])
        self.assertFalse({(r['kind'],r['id']) for r in first['results']}&{(r['kind'],r['id']) for r in second['results']})
        self.assertEqual(self.owner.get('/api/v1/search',params={'q':'searchneedle%'}).json()['results'],[])
        self.assertEqual(self.owner.get('/api/v1/search',params={'q':'   '}).json()['results'],[])

    def test_search_enforces_membership_and_agent_scope(self):
        other=self.owner.post('/api/v1/projects',json={'title':'Hidden needle project','objective':'Private context'}).json()
        self.owner.post(self.path_for('/notes',other['id']),json={'title':'Hidden needle note','body':'private'})
        self.message('Visible needle message')
        collaborator,_=self.collaborator()
        result=collaborator.get('/api/v1/search',params={'q':'needle'})
        self.assertEqual(result.status_code,200,result.text)
        self.assertTrue(result.json()['results'])
        self.assertTrue(all(r['project_id']==self.pid for r in result.json()['results']))
        self.assertEqual(collaborator.get('/api/v1/search',params={'q':'needle','project_id':other['id']}).status_code,404)
        agent,_=self.agent(scope='read')
        results=agent.get('/api/v1/search',params={'q':'needle'}).json()['results']
        self.assertTrue(results)
        self.assertTrue(all(r['project_id']==self.pid for r in results))
        self.assertEqual(agent.get('/api/v1/search',params={'q':'needle','project_id':other['id']}).status_code,404)
        anonymous=TestClient(self.app)
        self.clients.append(anonymous)
        self.assertEqual(anonymous.get('/api/v1/search',params={'q':'needle'}).status_code,401)

    def test_topic_recency_and_per_user_unread_counts_survive_moves_and_restart(self):
        general=self.general()
        own=self.message('Owner message')
        collaborator,_=self.collaborator()
        other=self.message('Collaborator message',client=collaborator)
        agent,_=self.agent()
        generated=self.message('Agent message',client=agent)
        target=self.topic('Newest topic')
        newest=self.message('Another collaborator message',topic=target,client=collaborator)
        topics=self.owner.get(self.path_for('/topics')).json()
        self.assertEqual(topics[0]['id'],target)
        self.assertEqual({t['id']:t['unread_count'] for t in topics},{general:2,target:1})
        self.assertEqual(self.owner.get(self.path_for()).json()['unread_count'],3)
        self.assertEqual(collaborator.get(self.path_for()).json()['unread_count'],2)
        self.owner.get(self.path_for(f'/topics/{general}/messages'))
        self.assertEqual(self.owner.get(self.path_for()).json()['unread_count'],3)
        marked=collaborator.post(self.path_for('/read'),json={'message_ids':[own['id']]}).json()
        self.assertEqual(marked['project']['unread_count'],1)
        result=self.owner.post(self.path_for('/read'),json={'message_ids':[other['id'],generated['id'],generated['id']]})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['project']['unread_count'],1)
        moved=self.owner.post(self.path_for(f'/messages/{newest["id"]}/move'),json={'target_topic_id':general,'revision':1})
        self.assertEqual(moved.status_code,200,moved.text)
        topics=self.owner.get(self.path_for('/topics')).json()
        self.assertEqual(topics[0]['id'],general)
        self.assertEqual({t['id']:t['unread_count'] for t in topics},{general:1,target:0})
        self.owner.post(self.path_for('/read'),json={'message_ids':[newest['id']]})
        self.owner.post(self.path_for(f'/messages/{newest["id"]}/move'),json={'target_topic_id':target,'revision':2})
        create_app(self.path)
        self.assertEqual(self.owner.get(self.path_for()).json()['unread_count'],0)
        self.assertEqual(collaborator.get(self.path_for()).json()['unread_count'],1)
        # New activity in an older topic brings it to the top without counting one's own post.
        self.message('Latest owner activity',topic=general)
        self.assertEqual(self.owner.get(self.path_for('/topics')).json()[0]['id'],general)
        self.assertEqual(self.owner.get(self.path_for()).json()['unread_count'],0)

    def test_read_receipts_are_scoped_atomic_and_exclude_archived_messages(self):
        collaborator,_=self.collaborator()
        first=self.message('Unread one',client=collaborator)
        second=self.message('Unread two',client=collaborator)
        foreign_project=self.owner.post('/api/v1/projects',json={'title':'Private','objective':'Keep isolated'}).json()
        foreign=self.owner.post(self.path_for(f'/topics/{self.general(pid=foreign_project["id"])}/messages',foreign_project['id']),json={'body':'Foreign message'}).json()
        denied=self.owner.post(self.path_for('/read'),json={'message_ids':[first['id'],foreign['id']]})
        self.assertEqual(denied.status_code,404)
        self.assertEqual(self.owner.get(self.path_for()).json()['unread_count'],2)
        self.assertEqual(collaborator.post(self.path_for('/read',foreign_project['id']),json={'message_ids':[foreign['id']]}).status_code,404)
        agent,_=self.agent()
        self.assertEqual(agent.post(self.path_for('/read'),json={'message_ids':[first['id']]}).status_code,403)
        self.owner.patch(self.path_for(f'/messages/{second["id"]}'),json={'body':second['body'],'revision':1,'archived':True})
        self.assertEqual(self.owner.get(self.path_for()).json()['unread_count'],1)
        self.owner.post(self.path_for('/read'),json={'message_ids':[first['id']]})
        self.assertEqual(self.owner.get(self.path_for()).json()['unread_count'],0)

    def test_plain_messages_are_untagged_and_agent_questions_denied(self):
        plain=self.message()
        self.assertEqual(plain['tags'],[])
        agent,_=self.agent()
        own=self.message(client=agent)
        for tags in [['question'],['QUESTION'],[' question ']]:
            self.assertEqual(agent.post(self.path_for(f'/topics/{self.general()}/messages'),json={'body':'Question','tags':tags}).status_code,403)
        self.assertEqual(agent.patch(self.path_for(f'/messages/{own["id"]}/tags'),json={'tags':['question'],'revision':1}).status_code,403)
        self.assertEqual(agent.post(self.path_for('/items'),json={'title':'Bypass','body':'No','labels':['question']}).status_code,422)

    def test_topic_isolation_and_collaborator_reorganization(self):
        bob,_=self.collaborator()
        tid=self.topic()
        message=self.message()
        moved=bob.post(self.path_for(f'/messages/{message["id"]}/move'),json={'target_topic_id':tid,'mode':'single','revision':message['revision']})
        self.assertEqual(moved.status_code,200,moved.text)
        other=bob.post('/api/v1/projects',json={'title':'Other','objective':'Private'}).json()['id']
        self.assertEqual(self.owner.get(self.path_for('/topics',other)).status_code,404)
        foreign=self.general(bob,other)
        self.assertEqual(self.owner.post(self.path_for(f'/messages/{message["id"]}/move'),json={'target_topic_id':foreign,'revision':2}).status_code,404)

    def test_single_following_and_all_moves_preserve_ids_and_history(self):
        first=self.message('First');second=self.message('Second');third=self.message('Third')
        target=self.topic()
        result=self.owner.post(self.path_for(f'/messages/{second["id"]}/move'),json={'target_topic_id':target,'mode':'following','revision':1})
        self.assertEqual(result.json()['message_ids'],[second['id'],third['id']])
        source=self.owner.get(self.path_for(f'/topics/{self.general()}/messages')).json()
        self.assertEqual([m['id'] for m in source['messages']],[first['id']])
        destination=self.owner.get(self.path_for(f'/topics/{target}/messages')).json()
        self.assertEqual(len(destination['events']),1)
        self.assertEqual(destination['events'][0]['message_ids'],[second['id'],third['id']])
        history=self.owner.get(self.path_for(f'/items/{second["id"]}/history')).json()
        self.assertEqual([r['item']['topic_id'] for r in history],[target,self.general()])
        all_move=self.owner.post(self.path_for(f'/messages/{second["id"]}/move'),json={'new_topic_title':'Third topic','mode':'all','revision':2}).json()
        self.assertEqual(all_move['message_ids'],[second['id'],third['id']])
        self.assertEqual(self.owner.get(self.path_for(f'/topics/{target}/messages')).json()['messages'],[])

    def test_selected_moves_are_atomic_and_reject_stale_revisions(self):
        messages=[self.message(str(i)) for i in range(4)]
        target=self.topic()
        selected=[{'id':m['id'],'revision':m['revision']} for m in (messages[0],messages[2])]
        result=self.owner.post(self.path_for(f'/topics/{self.general()}/move-messages'),json={'messages':selected,'target_topic_id':target})
        self.assertEqual(result.json()['message_ids'],[messages[0]['id'],messages[2]['id']])
        unchanged=[messages[1]['id'],messages[3]['id']]
        stale=[{'id':messages[1]['id'],'revision':1},{'id':messages[3]['id'],'revision':99}]
        response=self.owner.post(self.path_for(f'/topics/{self.general()}/move-messages'),json={'messages':stale,'new_topic_title':'Must roll back'})
        self.assertEqual(response.status_code,409)
        self.assertEqual([m['id'] for m in self.owner.get(self.path_for(f'/topics/{self.general()}/messages')).json()['messages']],unchanged)
        self.assertNotIn('Must roll back',[t['title'] for t in self.owner.get(self.path_for('/topics')).json()])

    def test_replies_follow_messages_after_moves_and_are_exported(self):
        source=self.message('Start here')
        reply=self.message('A response',reply_to_id=source['id'])
        self.assertEqual(reply['reply_to_id'],source['id'])
        self.assertEqual(reply['reply_to']['body'],'Start here')
        self.assertEqual(reply['reply_to']['author']['name'],'Ada')
        target=self.topic('Another location')
        self.owner.post(self.path_for(f'/messages/{source["id"]}/move'),json={'target_topic_id':target,'revision':1})
        current=self.owner.get(self.path_for(f'/messages/{reply["id"]}')).json()
        self.assertEqual(current['reply_to']['topic_id'],target)
        self.assertEqual(current['reply_to']['id'],source['id'])
        self.owner.post(self.path_for(f'/messages/{reply["id"]}/move'),json={'target_topic_id':target,'revision':1})
        edited=self.owner.patch(self.path_for(f'/messages/{reply["id"]}'),json={'body':'Edited response','revision':2})
        self.assertEqual(edited.status_code,200,edited.text)
        self.assertEqual(edited.json()['reply_to_id'],source['id'])
        exported=self.owner.get(self.path_for('/export')).json()
        self.assertIn({'message_id':reply['id'],'reply_to_id':source['id']},exported['replies'])
        history=self.owner.get(self.path_for(f'/items/{reply["id"]}/history')).json()
        self.assertEqual(history[0]['item']['reply_to_id'],source['id'])
        create_app(self.path)
        self.assertEqual(self.owner.get(self.path_for(f'/messages/{reply["id"]}')).json()['reply_to_id'],source['id'])
        self.assertEqual(self.owner.post(self.path_for(f'/messages/{source["id"]}/fork'),json={'title':'Removed','revision':2}).status_code,404)

    def test_reply_targets_cannot_cross_projects_or_be_archived_or_reassigned(self):
        source=self.message('Original')
        reply=self.message('Reply',reply_to_id=source['id'])
        changed=self.owner.patch(self.path_for(f'/messages/{reply["id"]}'),json={'body':'Reply','revision':1,'reply_to_id':None})
        self.assertEqual(changed.status_code,422)
        other=self.owner.post('/api/v1/projects',json={'title':'Other','objective':'Isolation'}).json()
        foreign=self.owner.post(self.path_for(f'/topics/{self.general(pid=other["id"])}/messages',other['id']),json={'body':'Private context'}).json()
        path=self.path_for(f'/topics/{self.general()}/messages')
        self.assertEqual(self.owner.post(path,json={'body':'Invalid','reply_to_id':foreign['id']}).status_code,404)
        self.assertEqual(self.owner.post(path,json={'body':'Missing','reply_to_id':999999}).status_code,404)
        self.owner.patch(self.path_for(f'/messages/{source["id"]}'),json={'body':'Original','revision':1,'archived':True})
        self.assertEqual(self.owner.post(path,json={'body':'Archived','reply_to_id':source['id']}).status_code,422)
        current=self.owner.get(self.path_for(f'/messages/{reply["id"]}')).json()
        self.assertTrue(current['reply_to']['archived'])

    def test_reply_idempotency_and_open_end_as_an_ordinary_tag(self):
        source=self.message('A question',tags=['question']);self.pin(source)
        path=self.path_for(f'/topics/{self.general()}/messages')
        payload={'body':'A remaining case','tags':['open end'],'reply_to_id':source['id']}
        first=self.owner.post(path,json=payload,headers={'Idempotency-Key':'reply-test'})
        again=self.owner.post(path,json=payload,headers={'Idempotency-Key':'reply-test'})
        self.assertEqual(first.status_code,201,first.text)
        self.assertEqual(first.json()['id'],again.json()['id'])
        self.assertEqual(first.json()['tags'],['open end'])
        self.assertEqual(self.owner.get(self.path_for('/overview')).json()['questions'][0]['open_ends'],[])
        changed=self.owner.post(path,json={**payload,'reply_to_id':None},headers={'Idempotency-Key':'reply-test'})
        self.assertEqual(changed.status_code,409)
        agent,_=self.agent()
        reply=self.message('Agent reply',client=agent,reply_to_id=source['id'])
        self.assertEqual(reply['reply_to_id'],source['id'])

    def test_individual_ratings_sort_by_named_actor_and_cannot_spoof(self):
        question=self.message('Can we improve the bound?',tags=['question']);self.pin(question)
        end1,end2=self.end(question,body='First approach'),self.end(question,body='Second approach')
        agent,_=self.agent()
        for client,eid,score in [(self.owner,end1['id'],5),(self.owner,end2['id'],2),(agent,end1['id'],1),(agent,end2['id'],4)]:
            result=client.put(self.path_for(f'/open-ends/{eid}/rating'),json={'score':score,'reason':'A stated reason'})
            self.assertEqual(result.status_code,200,result.text)
        overview=self.owner.get(self.path_for('/overview')).json()
        self.assertEqual([e['id'] for e in overview['questions'][0]['open_ends']],[end1['id'],end2['id']])
        ratings=overview['questions'][0]['open_ends'][0]['ratings']
        self.assertEqual({r['name'] for r in ratings},{'Ada','Proof assistant'})
        agent_actor=next(r['actor'] for r in ratings if r['kind']=='agent')
        ranked=self.owner.get(self.path_for('/overview'),params={'rank_by':agent_actor}).json()
        self.assertEqual([e['id'] for e in ranked['questions'][0]['open_ends']],[end2['id'],end1['id']])
        self.assertEqual(agent.put(self.path_for(f'/open-ends/{end1["id"]}/rating'),json={'score':5,'actor':'human:1'}).status_code,422)
        self.assertEqual(agent.put(self.path_for(f'/open-ends/{end1["id"]}/rating'),json={'score':True}).status_code,422)
        self.assertEqual(agent.patch(self.path_for(f'/open-ends/{end1["id"]}'),json={'state':'resolved'}).status_code,403)
        self.owner.patch(self.path_for(f'/open-ends/{end1["id"]}'),json={'state':'resolved'})
        self.assertEqual(len(self.owner.get(self.path_for('/overview')).json()['questions'][0]['open_ends']),1)
        fallback=self.owner.get(self.path_for('/overview'),params={'rank_by':'agent:999999'}).json()
        self.assertEqual(fallback['rank_by'],'human:1')

    def test_overview_chooses_15_globally_then_groups_by_current_topic(self):
        tid=self.topic()
        messages=[self.message(f'Message {i}',topic=tid if i%2 else self.general()) for i in range(19)]
        overview=self.owner.get(self.path_for('/overview')).json()
        recent=[m for topic in overview['recent_topics'] for m in topic['messages']]
        self.assertEqual(len(recent),15)
        self.assertEqual({m['id'] for m in recent},{m['id'] for m in messages[-15:]})
        for group in overview['recent_topics']:
            self.assertTrue(all(m['topic_id']==group['topic_id'] for m in group['messages']))

    def test_notes_upload_download_permissions_and_input_limits(self):
        payload='# A theorem\n$ x^2 $'.encode()
        response=self.owner.post(self.path_for('/notes/upload'),params={'filename':'proof.typ'},content=payload,headers={'Content-Type':'application/octet-stream'})
        self.assertEqual(response.status_code,201,response.text)
        nid=response.json()['id']
        self.assertEqual(self.owner.get(self.path_for(f'/notes/{nid}/download')).content,payload)
        self.assertEqual(self.owner.get(self.path_for(f'/notes/{nid}')).json()['source'],payload.decode())
        agent,_=self.agent()
        self.assertEqual(agent.post(self.path_for('/notes/upload'),params={'filename':'x.typ'},content=payload).status_code,403)
        self.assertEqual(self.owner.post(self.path_for('/notes/upload'),params={'filename':'../x.typ'},content=payload).status_code,422)
        self.assertEqual(self.owner.post(self.path_for('/notes/upload'),params={'filename':'x.typ'},content=b'\xff').status_code,422)
        self.assertEqual(self.owner.post(self.path_for('/notes/upload'),params={'filename':'x.typ'},content=b'a'*(10*1024*1024+1)).status_code,413)
        self.assertEqual(len(self.owner.get(self.path_for('/overview')).json()['notes']),1)

    def test_message_pagination_idempotency_and_revoked_keys(self):
        for i in range(5):self.message(str(i))
        first=self.owner.get(self.path_for(f'/topics/{self.general()}/messages'),params={'limit':2}).json()
        second=self.owner.get(self.path_for(f'/topics/{self.general()}/messages'),params={'limit':2,'before':first['next_before']}).json()
        self.assertFalse({m['id'] for m in first['messages']}&{m['id'] for m in second['messages']})
        agent,key=self.agent();path=self.path_for(f'/topics/{self.general()}/messages')
        a=agent.post(path,json={'body':'Retry'},headers={'Idempotency-Key':'chat-1'})
        b=agent.post(path,json={'body':'Retry'},headers={'Idempotency-Key':'chat-1'})
        self.assertEqual(a.json()['id'],b.json()['id'])
        self.owner.delete(self.path_for(f'/keys/{key}'))
        self.assertEqual(agent.get(path).status_code,401)

    def test_topic_rename_survives_restart_without_recreating_general(self):
        tid=self.general()
        response=self.owner.patch(self.path_for(f'/topics/{tid}'),json={'title':'Discussion','revision':1})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual([t['title'] for t in self.owner.get(self.path_for('/topics')).json()],['Discussion'])
        create_app(self.path)
        self.assertEqual([t['title'] for t in self.owner.get(self.path_for('/topics')).json()],['Discussion'])

    def test_v1_migration_preserves_history_pins_and_creates_one_backup(self):
        path=Path('.checks')/f'legacy-{uuid.uuid4().hex}.db'
        try:
            with closing(sqlite3.connect(path)) as db:
                db.executescript(SCHEMA)
                db.execute("INSERT INTO users VALUES (1,'Legacy','legacy@example.org','not-a-login','2026-01-01')")
                db.execute("INSERT INTO projects(id,title,objective,owner_id,created_at) VALUES (1,'Legacy project','Keep data',1,'2026-01-01')")
                db.execute('INSERT INTO members VALUES (1,1)')
                db.execute("INSERT INTO items(id,project_id,author_id,title,body,kind,labels,status,assessment,created_at,updated_at) VALUES (7,1,1,'Original question','Original text','question','[\"roadblock\"]','open','unreviewed','2026-01-01','2026-01-01')")
                db.execute('INSERT INTO main_questions VALUES (1,7,0)')
                db.execute("INSERT INTO history(item_id,actor,snapshot,created_at) VALUES (7,'Legacy','{\"body\":\"Original text\"}','2026-01-01')")
                db.commit()
            create_app(path);create_app(path)
            with closing(sqlite3.connect(path)) as db:
                row=db.execute('SELECT body,tags,topic_id FROM items WHERE id=7').fetchone()
                self.assertEqual(row[0],'Original text');self.assertEqual(json.loads(row[1]),['question','roadblock']);self.assertIsNotNone(row[2])
                self.assertEqual(db.execute('SELECT item_id FROM main_questions').fetchone()[0],7)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM history').fetchone()[0],1)
            self.assertEqual(len(list(path.parent.glob(path.stem+'-before-topics-*.db'))),1)
        finally:
            for candidate in [path,Path(str(path)+'-wal'),Path(str(path)+'-shm'),*path.parent.glob(path.stem+'-before-topics-*.db')]:candidate.unlink(missing_ok=True)
