import concurrent.futures
from contextlib import closing
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import create_app
from codex_service import Rpc, sandbox, agent_uid
import test_api as notebook_tests


class ProjectAgentTests(unittest.TestCase):
    path_for = notebook_tests.NotebookTests.path_for
    collaborator = notebook_tests.NotebookTests.collaborator
    agent = notebook_tests.NotebookTests.agent

    def setUp(self):
        notebook_tests.NotebookTests.setUp(self)
        self.secret_path = self.path.with_suffix('.secret')
        self.secret_path.write_text('test-service-secret-'+'x'*40, encoding='utf-8')
        self.environment = patch.dict(os.environ, {'RESEARCH_AGENT_SECRET_FILE':str(self.secret_path)})
        self.environment.start()
        self.service = TestClient(self.app, headers={'Authorization':'Bearer '+self.secret_path.read_text(encoding='utf-8')})
        self.clients.append(self.service)

    def tearDown(self):
        self.environment.stop()
        self.secret_path.unlink(missing_ok=True)
        notebook_tests.NotebookTests.tearDown(self)

    def agents(self, pid=None):
        return self.owner.get(self.path_for('/agents',pid)).json()['agents']

    def start(self, role='astra', client=None, pid=None):
        response = (client or self.owner).post(self.path_for(f'/agents/{role}/runs',pid),json={'prompt':'Research this question.'})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()['id']

    def claim(self):
        response = self.service.post('/internal/agents/claim')
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['job']

    def tool(self, job, op, arguments=None):
        return self.service.post(f'/internal/agents/runs/{job["id"]}/tool',
            headers={'X-Agent-Lease':job['lease']},json={'operation':op,'arguments':arguments or {}})

    def finish(self, job):
        return self.service.post(f'/internal/agents/runs/{job["id"]}/finish',
            headers={'X-Agent-Lease':job['lease']},json={'status':'completed','output':'Answer'})

    def other_project(self, client=None):
        return (client or self.owner).post('/api/v1/projects',json={'title':'Private second project'}).json()['id']

    def cluster(self, *pids):
        cid = self.owner.post('/api/v1/agent-clusters',json={'name':'Research group'}).json()['id']
        for pid in pids:
            result = self.owner.put(f'/api/v1/agent-clusters/{cid}/projects/{pid}')
            self.assertEqual(result.status_code,200,result.text)
        return cid

    def test_two_persistent_role_identities_without_automatic_runs(self):
        identities = self.agents()
        self.assertEqual([(a['name'],a['model']) for a in identities],
                         [('Astra','gpt-6-astra'),('Sol','gpt-6.1-sol')])
        self.assertTrue(all(not a['runs'] for a in identities))
        self.assertIsNone(self.claim())
        with TestClient(create_app(self.path)) as other:
            login = other.post('/api/v1/auth/login',json={'email':'ada@example.org','password':'a secure password'})
            self.assertEqual(login.status_code,200)
            self.assertEqual(identities,other.get(self.path_for('/agents')).json()['agents'])

    def test_regular_agent_keys_cannot_control_agents_or_clusters(self):
        client,_ = self.agent()
        self.assertEqual(client.get(self.path_for('/agents')).status_code,403)
        self.assertEqual(client.post(self.path_for('/agents/astra/runs'),json={'prompt':'x'}).status_code,403)
        self.assertEqual(client.post('/api/v1/agent-clusters',json={'name':'x'}).status_code,403)
        outsider = TestClient(self.app)
        self.clients.append(outsider)
        self.assertEqual(outsider.get(self.path_for('/agents')).status_code,401)
        self.assertEqual(outsider.post('/internal/agents/claim').status_code,401)

    def test_concurrent_claim_is_unique_and_both_roles_have_their_models(self):
        self.start()
        self.start('sol')
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            jobs = list(pool.map(lambda _: self.claim(),range(3)))
        jobs = [job for job in jobs if job]
        self.assertEqual(len(jobs),2)
        self.assertEqual(len({job['id'] for job in jobs}),2)
        self.assertEqual({job['model'] for job in jobs},{'gpt-6-astra','gpt-6.1-sol'})

    def test_busy_cancel_and_capability_revocation(self):
        rid = self.start()
        self.assertEqual(self.owner.post(self.path_for('/agents/astra/runs'),json={'prompt':'Duplicate'}).status_code,409)
        job = self.claim()
        self.assertEqual(self.owner.delete(self.path_for(f'/agents/sol/runs/{rid}')).status_code,404)
        self.assertEqual(self.owner.delete(self.path_for(f'/agents/astra/runs/{rid}')).status_code,200)
        self.assertEqual(self.tool(job,'context').status_code,403)
        self.assertEqual(self.finish(job).status_code,403)
        self.start()

    def test_expired_worker_is_failed_without_automatic_replay(self):
        rid = self.start()
        job = self.claim()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE agent_runs SET lease_until=? WHERE id=?',(time.time()-1,rid))
        self.assertIsNone(self.claim())
        self.assertEqual(self.agents()[0]['runs'][0]['status'],'failed')
        self.assertEqual(self.tool(job,'context').status_code,403)

    def test_context_has_no_other_project_and_lease_cannot_be_substituted(self):
        other = self.other_project()
        self.owner.post(self.path_for('/dashboard-questions'),json={'body':'Our question'})
        self.owner.post(self.path_for('/dashboard-questions',other),json={'body':'SECRET other question'})
        self.start()
        self.start('sol',pid=other)
        first,second = self.claim(),self.claim()
        data = self.tool(first,'context')
        self.assertEqual(data.status_code,200,data.text)
        self.assertEqual(data.json()['questions'],[{'body':'Our question'}])
        self.assertNotIn('SECRET',data.text)
        substituted = {**first,'lease':second['lease']}
        self.assertEqual(self.tool(substituted,'context').status_code,403)
        self.assertEqual(self.tool(first,'context',{'project_id':other}).status_code,422)

    def test_same_project_talks_other_project_requires_cluster_and_removal_hides_mail(self):
        other = self.other_project()
        ours,theirs = self.agents(),self.agents(other)
        self.start()
        source = self.claim()
        self.assertEqual([a['id'] for a in self.tool(source,'peers').json()],[ours[1]['id']])
        self.assertEqual(self.tool(source,'send',{'recipient_id':ours[1]['id'],'body':'Edit this'}).status_code,200)
        message = {'recipient_id':theirs[0]['id'],'body':'Shared research'}
        self.assertEqual(self.tool(source,'send',message).status_code,403)
        cid = self.cluster(self.pid,other)
        self.assertEqual(self.tool(source,'send',message).status_code,200)
        self.start(pid=other)
        target = self.claim()
        self.assertEqual(len(self.tool(target,'inbox').json()),1)
        self.owner.delete(f'/api/v1/agent-clusters/{cid}/projects/{other}')
        self.assertEqual(self.tool(target,'inbox').json(),[])
        self.assertEqual(self.tool(source,'send',message).status_code,403)
        self.assertIsNone(self.claim())  # Mail never starts uncontrolled inference loops.

    def test_clusters_overlap_without_transitive_access(self):
        second,third = self.other_project(),self.other_project()
        self.cluster(self.pid,second)
        self.cluster(second,third)
        self.start()
        job = self.claim()
        projects = {a['project_id'] for a in self.tool(job,'peers').json()}
        self.assertEqual(projects,{self.pid,second})

    def test_different_project_owner_must_approve_cluster_invitation(self):
        bob,_ = self.collaborator()
        other = self.other_project(bob)
        cid = bob.post('/api/v1/agent-clusters',json={'name':'Bob cluster'}).json()['id']
        self.assertEqual(bob.put(f'/api/v1/agent-clusters/{cid}/projects/{self.pid}').status_code,200)
        bob.put(f'/api/v1/agent-clusters/{cid}/projects/{other}')
        self.start()
        job = self.claim()
        self.assertEqual({a['project_id'] for a in self.tool(job,'peers').json()},{self.pid})
        self.assertEqual(self.owner.put(f'/api/v1/agent-clusters/{cid}/projects/{self.pid}').status_code,200)
        self.assertEqual({a['project_id'] for a in self.tool(job,'peers').json()},{self.pid,other})
        # A collaborator who owns neither the project nor cluster cannot remove it.
        cid2 = self.cluster(self.pid)
        self.assertEqual(bob.delete(f'/api/v1/agent-clusters/{cid2}/projects/{self.pid}').status_code,403)

    def test_member_removal_revokes_running_and_queued_work(self):
        bob,bid = self.collaborator()
        self.start(client=bob)
        job = self.claim()
        self.start('sol',client=bob)
        self.owner.delete(self.path_for(f'/members/{bid}'))
        self.assertEqual(self.tool(job,'files').status_code,403)
        self.assertIsNone(self.claim())

    def test_file_edits_use_etags_preserve_other_projects_and_batch_git(self):
        other = self.other_project()
        self.start('sol')
        job = self.claim()
        result = self.tool(job,'write_file',{'path':'draft.txt','text':'Original'})
        self.assertEqual(result.status_code,200,result.text)
        etag = result.json()['etag']
        conflict = self.tool(job,'write_file',{'path':'draft.txt','text':'Changed','etag':'old'})
        self.assertEqual(conflict.status_code,409)
        self.assertEqual(self.tool(job,'write_file',{'path':'draft.txt','text':'Edited','etag':etag}).status_code,200)
        self.assertEqual(self.tool(job,'read_file',{'path':'draft.txt'}).json()['text'],'Edited')
        self.assertEqual(self.tool(job,'read_file',{'path':'../secret'}).status_code,422)
        self.assertEqual(self.owner.get(self.path_for('/files',other)).json()['entries'],[])
        history = self.owner.get(self.path_for('/files')).json()['history']
        self.assertEqual(len([h for h in history['items'] if h.get('source')=='git']),1)
        self.assertEqual(self.finish(job).status_code,200)
        self.assertEqual(self.tool(job,'files').status_code,403)

    def test_service_not_configured_is_explicit(self):
        self.secret_path.unlink()
        self.assertFalse(self.owner.get(self.path_for('/agents')).json()['available'])
        self.assertEqual(self.owner.post(self.path_for('/agents/astra/runs'),json={'prompt':'Hi'}).status_code,503)


class CodexProtocolTests(unittest.TestCase):
    def test_agent_uid_allocation_is_persistent_unique_and_concurrent(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory(dir='.checks') as folder:
            state = Path(folder)
            (state/'control').mkdir()
            identities = ['a'*32,'b'*32,'c'*32,'a'*32]
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                values = list(pool.map(lambda identity:agent_uid(state,identity),identities))
            self.assertEqual(values[0],values[3])
            self.assertEqual(len(set(values)),3)
            self.assertEqual(agent_uid(state,'b'*32),values[1])
            with self.assertRaises(ValueError):
                agent_uid(state,'../other-agent')

    def test_rpc_initialization_callbacks_and_completion(self):
        script = '''import json,sys
def emit(value):
 print(json.dumps(value),flush=True)
for line in sys.stdin:
 msg=json.loads(line)
 method=msg.get('method')
 if method=='initialize': emit({'id':msg['id'],'result':{}})
 elif method=='thread/start': emit({'id':msg['id'],'result':{'thread':{'id':'thread-test'}}})
 elif method=='turn/start':
  emit({'id':900,'method':'item/tool/call','params':{'threadId':'thread-test','tool':'project_tool','arguments':{'operation':'context','arguments':{}}}})
  turn_id=msg['id']
 elif msg.get('id')==900:
  assert msg['result']['success'] and msg['result']['contentItems'][0]['type']=='inputText'
  emit({'id':turn_id,'result':{'turn':{'id':'turn-test'}}})
  emit({'method':'turn/completed','params':{'threadId':'thread-test','turn':{'id':'turn-test','status':'completed'}}})
'''
        process = subprocess.Popen([sys.executable,'-u','-c',script],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                   text=True,encoding='utf-8')
        seen = []
        try:
            rpc = Rpc(process,lambda args:seen.append(args) or {'title':'Only our project'})
            rpc.call('initialize',{})
            rpc.write({'method':'initialized','params':{}})
            rpc.thread_id = rpc.call('thread/start',{})['thread']['id']
            result = rpc.call('turn/start',{'threadId':rpc.thread_id})
            self.assertEqual(result['turn']['id'],'turn-test')
            self.assertEqual(seen,[{'operation':'context','arguments':{}}])
            self.assertEqual(rpc.message()['params']['turn']['status'],'completed')
            policy = sandbox('/private/work')
            self.assertFalse(policy['networkAccess'])
            self.assertEqual(policy['readOnlyAccess']['readableRoots'],['/private/work'])
        finally:
            process.kill()
            process.wait()
            process.stdin.close()
            process.stdout.close()
