import base64
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
import unittest
import uuid

import uvicorn
from fastapi.testclient import TestClient
from file_api import git
import test_api as fixtures


class FileTests(unittest.TestCase):
    setUp = fixtures.NotebookTests.setUp
    tearDown = fixtures.NotebookTests.tearDown
    path_for = fixtures.NotebookTests.path_for
    agent = fixtures.NotebookTests.agent
    collaborator = fixtures.NotebookTests.collaborator

    def upload(self, path, data=b'content', etag=None, client=None):
        return (client or self.owner).put(self.path_for('/files/content'),params={'path':path},content=data,
            headers={'If-Match':etag} if etag else {'If-None-Match':'*'})

    def test_search_matches_nested_file_contents_and_names(self):
        self.assertEqual(self.upload('proofs/argument.tex',b'Only the body contains HiddenKeyword').status_code,200)
        self.assertEqual(self.upload('binary/HiddenKeyword.bin',b'\x00\xff').status_code,200)
        response=self.owner.get('/api/v1/search',params={'q':'hiddenkeyword','project_id':self.pid,'content_only':True})
        self.assertEqual(response.status_code,200,response.text)
        files=[r for r in response.json()['results'] if r['kind']=='file']
        self.assertEqual({r['file_path'] for r in files},{'proofs/argument.tex','binary/HiddenKeyword.bin'})
        named=self.owner.get('/api/v1/search',params={'q':'argument.tex','project_id':self.pid}).json()['results']
        self.assertEqual([r['file_path'] for r in named if r['kind']=='file'],['proofs/argument.tex'])

    def test_existing_repository_hook_path_is_refreshed_after_relocation(self):
        self.owner.get(self.path_for('/files'))
        repo = self.app.state.file_root / str(self.pid)
        git(repo, 'config', 'core.hooksPath', 'C:/old-machine/project/.git/hooks')
        self.assertEqual(self.owner.get(self.path_for('/files')).status_code, 200)
        expected = str((repo/'.git'/'hooks').resolve()).replace('\\', '/')
        self.assertEqual(git(repo, 'config', '--get', 'core.hooksPath').stdout.decode().strip(), expected)

    def test_arbitrary_files_tree_versions_moves_and_downloads(self):
        data=b'\x00\xff\x01arbitrary bytes'
        created=self.upload('source/nested/archive.weird',data)
        self.assertEqual(created.status_code,200,created.text)
        self.assertEqual(self.owner.get(self.path_for('/files/content'),params={'path':'source/nested/archive.weird'}).content,data)
        tree=self.owner.get(self.path_for('/files')).json()
        self.assertEqual([e['path'] for e in tree['entries']],['source','source/nested','source/nested/archive.weird'])
        self.assertIsNone(self.owner.get(self.path_for('/files/preview'),params={'path':'source/nested/archive.weird'}).json()['text'])
        self.assertEqual(self.upload('source/nested/archive.weird',b'clobber').status_code,412)
        updated=self.upload('source/nested/archive.weird',b'new text',created.json()['etag'])
        self.assertEqual(updated.status_code,200,updated.text)
        self.assertEqual(self.upload('source/nested/archive.weird',b'stale',created.json()['etag']).status_code,412)
        moved=self.owner.patch(self.path_for('/files/entry'),json={'path':'source/nested/archive.weird','new_path':'proofs/main.tex'},headers={'If-Match':updated.json()['etag']})
        self.assertEqual(moved.status_code,200,moved.text)
        self.assertEqual(self.owner.get(self.path_for('/files/content'),params={'path':'proofs/main.tex'}).content,b'new text')
        self.assertEqual(self.upload('empty.bin',b'').status_code,200)
        folder=self.owner.post(self.path_for('/files/folders'),json={'path':'empty/folder'})
        self.assertEqual(folder.status_code,201,folder.text)
        self.assertIn('empty/folder',[e['path'] for e in self.owner.get(self.path_for('/files')).json()['entries']])

    def test_files_permissions_paths_and_migration(self):
        for path in ['../escape','/absolute','a/../../escape','.git/config','a\\b','CON','a/b.']:
            self.assertEqual(self.upload(path).status_code,422,path)
        self.assertEqual(self.upload('Case/a.txt').status_code,200)
        self.assertEqual(self.upload('case/b.txt').status_code,409)
        readonly,_=self.agent(scope='read')
        self.assertEqual(self.upload('blocked',client=readonly).status_code,403)
        writer,_=self.agent()
        self.assertEqual(self.upload('agent.bin',client=writer).status_code,200)
        other=self.owner.post('/api/v1/projects',json={'title':'Other','objective':'Private'}).json()
        self.assertEqual(writer.get(self.path_for('/files',other['id'])).status_code,404)
        note=self.owner.post(self.path_for('/notes'),json={'title':'Old note','body':'Preserved $x$'}).json()
        from app import create_app
        create_app(self.path)
        self.assertEqual(self.owner.get(self.path_for('/files/content'),params={'path':'notes/Old note.md'}).content,b'Preserved $x$')
        create_app(self.path)
        files=self.owner.get(self.path_for('/files')).json()['entries']
        self.assertEqual(sum(e['path']=='notes/Old note.md' for e in files),1)
        self.assertEqual(self.owner.get(self.path_for(f'/notes/{note["id"]}')).json()['body'],'Preserved $x$')

    def test_local_changes_persist_and_commit_as_one_batch_with_history(self):
        initial = self.owner.get(self.path_for('/files')).json()
        first = self.upload('draft.txt', b'first').json()
        self.upload('draft.txt', b'second', first['etag'])
        self.upload('figure.bin', b'\x00\xff')
        current = self.owner.get(self.path_for('/files')).json()
        self.assertEqual(current['head'], initial['head'])
        self.assertEqual(len(current['history']['pending']), 3)
        self.assertEqual(len(current['history']['items']), 1)
        self.assertFalse(current['history']['has_more'])
        from app import create_app
        create_app(self.path)
        self.assertEqual(len(self.owner.get(self.path_for('/files')).json()['history']['pending']), 3)
        self.assertEqual(self.owner.get(self.path_for('/files/content'), params={'path':'draft.txt'}).content, b'second')
        readonly, _ = self.agent(scope='read')
        self.assertEqual(readonly.post(self.path_for('/files/commit'), json={}).status_code, 403)
        result = self.owner.post(self.path_for('/files/commit'), json={'message':'Draft and figure together'})
        self.assertEqual(result.status_code, 200, result.text)
        history = result.json()['history']
        self.assertEqual(history['pending'], [])
        self.assertEqual(len(history['items']), 2)
        self.assertEqual(history['items'][0]['source'], 'browser')
        self.assertEqual(history['items'][0]['message'], 'Draft and figure together')
        self.assertEqual(len(history['items'][0]['events']), 3)
        self.assertEqual(self.owner.post(self.path_for('/files/commit'), json={}).json()['commit'], None)
        current = self.owner.get(self.path_for('/files')).json()
        self.assertNotEqual(current['head'], initial['head'])
        limited = self.owner.get(self.path_for('/files'), params={'history_limit':1}).json()['history']
        self.assertEqual(len(limited['items']), 1)
        self.assertTrue(limited['has_more'])
        # Saving the same bytes does not add a fake change, nor a new commit.
        etag = next(e['etag'] for e in current['entries'] if e['path']=='draft.txt')
        self.upload('draft.txt', b'second', etag)
        self.assertEqual(self.owner.get(self.path_for('/files')).json()['history']['pending'], [])

    def test_reverted_batch_keeps_local_history_without_an_empty_commit(self):
        initial = self.owner.get(self.path_for('/files')).json()['head']
        file = self.upload('temporary.txt').json()
        self.owner.delete(self.path_for('/files/entry'), params={'path':'temporary.txt'}, headers={'If-Match':file['etag']})
        result = self.owner.post(self.path_for('/files/commit'), json={}).json()
        self.assertIsNone(result['commit'])
        self.assertEqual(result['history']['pending'], [])
        self.assertEqual(result['history']['items'][0]['source'], 'local')
        self.assertEqual(len(result['history']['items'][0]['events']), 2)
        self.assertEqual(self.owner.get(self.path_for('/files')).json()['head'], initial)

    def test_history_shows_all_branches_tags_and_merge_parents_without_switching_main(self):
        self.upload('base.txt')
        base = self.owner.post(self.path_for('/files/commit'), json={}).json()['commit']
        repo = self.app.state.file_root / str(self.pid)
        blob = git(repo, 'hash-object', '-w', '--stdin', data=b'only on the experiment').stdout.strip()
        tree = git(repo, 'mktree', '-z', data=git(repo, 'ls-tree', '-z', base).stdout +
                   b'100644 blob '+blob+b'\texperiment.txt\0').stdout.decode().strip()
        experiment = git(repo, 'commit-tree', tree, '-p', base, data=b'Explore a different proof\n').stdout.decode().strip()
        git(repo, 'update-ref', 'refs/heads/research/experiment', experiment)
        git(repo, 'tag', '-a', 'checkpoint', '-m', 'Annotated checkpoint', experiment)
        # A child with an earlier timestamp must still appear before its parent.
        unmerged = git(repo, 'commit-tree', tree, '-p', experiment, data=b'Unmerged work\n', env={**os.environ,
            'GIT_AUTHOR_DATE':'2000-01-01T00:00:00Z', 'GIT_COMMITTER_DATE':'2000-01-01T00:00:00Z'}).stdout.decode().strip()
        git(repo, 'update-ref', 'refs/heads/unmerged-work', unmerged)
        self.upload('main.txt', b'web edits stay on main')
        self.owner.post(self.path_for('/files/commit'), json={})
        main = git(repo, 'rev-parse', 'HEAD').stdout.decode().strip()
        before = self.owner.get(self.path_for('/files')).json()
        self.assertEqual(before['branch'], 'main')
        self.assertNotIn('experiment.txt', [e['path'] for e in before['entries']])
        self.assertEqual(git(repo, 'rev-parse', 'HEAD').stdout.decode().strip(), main)
        git(repo, 'merge', '--no-ff', 'research/experiment', '-m', 'Merge research experiment')
        result = self.owner.get(self.path_for('/files')).json()
        items = result['history']['items']
        merge = next(item for item in items if item['message']=='Merge research experiment')
        self.assertEqual(merge['parents'], [main, experiment])
        self.assertIn({'kind':'branch', 'name':'main'}, merge['refs'])
        side = next(item for item in items if item['commit']==experiment)
        self.assertIn({'kind':'branch', 'name':'research/experiment'}, side['refs'])
        self.assertIn({'kind':'tag', 'name':'checkpoint'}, side['refs'])
        self.assertIn(unmerged, [item['commit'] for item in items])
        positions = {item['commit']:i for i,item in enumerate(items)}
        for item in items:
            for parent in item['parents']:
                if parent in positions:
                    self.assertLess(positions[item['commit']], positions[parent])
        self.assertEqual(git(repo, 'symbolic-ref', '--short', 'HEAD').stdout.decode().strip(), 'main')
        self.assertIn('main.txt', [e['path'] for e in result['entries']])
        limited = self.owner.get(self.path_for('/files'), params={'history_limit':2}).json()['history']
        self.assertEqual(len(limited['items']), 2)
        self.assertTrue(limited['has_more'])

    def test_git_remote_clone_push_and_pull_share_files(self):
        self.upload('proofs/start.txt',b'from the app')
        writer,_=self.agent()
        key=writer.headers['Authorization'].split()[1]
        basic='Basic '+base64.b64encode(('token:'+key).encode()).decode()
        missing=self.owner.get(f'/git/projects/{self.pid}.git/info/refs?service=git-upload-pack')
        self.assertEqual(missing.status_code,401)
        self.assertIn('Basic',missing.headers['www-authenticate'])
        readonly,_=self.agent(scope='read')
        self.assertEqual(readonly.get(f'/git/projects/{self.pid}.git/info/refs?service=git-receive-pack').status_code,403)
        sock=socket.socket();sock.bind(('127.0.0.1',0))
        port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(self.app,log_level='error',lifespan='off'))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
        clone=Path('.checks')/('clone-'+uuid.uuid4().hex)
        def run(*args, input=None, ok=True):
            result=subprocess.run(['git','-c','http.extraHeader=Authorization: '+basic,*args],input=input,capture_output=True,timeout=45)
            if ok:self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            return result
        try:
            deadline=time.monotonic()+5
            while not server.started and time.monotonic()<deadline:time.sleep(.05)
            self.assertTrue(server.started)
            run('clone',f'http://127.0.0.1:{port}/git/projects/{self.pid}.git',str(clone))
            self.assertEqual((clone/'proofs/start.txt').read_bytes(),b'from the app')
            (clone/'pushed.bin').write_bytes(b'\x00\xfffrom git')
            run('-C',str(clone),'add','pushed.bin')
            run('-C',str(clone),'-c','user.name=Git tester','-c','user.email=test@example.org','commit','-m','Add through Git')
            run('-C',str(clone),'push','origin','main')
            self.assertEqual(self.owner.get(self.path_for('/files/content'),params={'path':'pushed.bin'}).content,b'\x00\xfffrom git')
            history=self.owner.get(self.path_for('/files')).json()['history']
            pushed=next(item for item in history['items'] if item['message']=='Add through Git')
            self.assertEqual(pushed['source'],'git')
            self.assertEqual(pushed['author'],'Git tester')
            self.upload('from-web.txt',b'committed by UI')
            self.upload('also-from-web.txt',b'same batch')
            run('-C',str(clone),'pull','--ff-only')
            self.assertEqual((clone/'from-web.txt').read_bytes(),b'committed by UI')
            self.assertEqual((clone/'also-from-web.txt').read_bytes(),b'same batch')
            history=self.owner.get(self.path_for('/files')).json()['history']
            self.assertEqual(history['pending'],[])
            self.assertEqual(len(history['items'][0]['events']),2)
            # Unsafe Git trees must fail before their checkout touches the server filesystem.
            oid=run('-C',str(clone),'hash-object','-w','--stdin',input=b'../outside').stdout.decode().strip()
            run('-C',str(clone),'update-index','--add','--cacheinfo','120000,'+oid+',unsafe-link')
            run('-C',str(clone),'-c','user.name=Git tester','-c','user.email=test@example.org','commit','-m','Rejected symlink')
            rejected=run('-C',str(clone),'push','origin','main',ok=False)
            self.assertNotEqual(rejected.returncode,0)
            self.assertNotIn('unsafe-link',[e['path'] for e in self.owner.get(self.path_for('/files')).json()['entries']])
        finally:
            server.should_exit=True;thread.join(timeout=5);sock.close()
            if clone.exists():
                import stat
                self.assertTrue(clone.resolve().is_relative_to(Path('.checks').resolve()))
                def remove_readonly(fn,path,error):
                    Path(path).chmod(stat.S_IWRITE|stat.S_IREAD)
                    for attempt in range(10):
                        try:
                            fn(path)
                            return
                        except PermissionError:
                            if attempt==9:
                                raise
                            time.sleep(.05*(attempt+1))
                shutil.rmtree(clone,onexc=remove_readonly)
