import base64
import io
import os
import unittest
import zipfile
from unittest.mock import patch

import httpx
import test_api as fixtures
from latex_worker import CompileRequest, compile_snapshot, safe_path


class LatexTests(unittest.TestCase):
    setUp=fixtures.NotebookTests.setUp
    tearDown=fixtures.NotebookTests.tearDown
    path_for=fixtures.NotebookTests.path_for

    def test_compilation_captures_saved_pending_files_and_keeps_git_history(self):
        source=b'\\documentclass{article}\\begin{document}Hello\\end{document}'
        r=self.owner.put(self.path_for('/files/content'),params={'path':'main.tex'},content=source,headers={'If-None-Match':'*'})
        self.assertEqual(r.status_code,200)
        before=self.owner.get(self.path_for('/files')).json()
        payloads=[]
        def handle(request):
            import json
            data=json.loads(request.content);payloads.append(data)
            return httpx.Response(200,json={'status':0,'log':'Compiled','pdf':base64.b64encode(b'%PDF-test').decode()})
        real=httpx.AsyncClient
        def client(**kwargs):return real(transport=httpx.MockTransport(handle))
        with patch.dict(os.environ,{'RESEARCH_LATEX_URL':'http://latex:8790'}),patch('editor_api.httpx.AsyncClient',side_effect=client):
            result=self.owner.post(self.path_for('/editor/latex'),json={'main':'main.tex'})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(base64.b64decode(payloads[0]['files']['main.tex']),source)
        after=self.owner.get(self.path_for('/files')).json()
        self.assertEqual(before['head'],after['head']);self.assertEqual(before['history'],after['history'])

    def test_missing_worker_and_invalid_paths_are_clear_errors(self):
        with patch.dict(os.environ,{'RESEARCH_LATEX_URL':''}):
            self.assertEqual(self.owner.post(self.path_for('/editor/latex'),json={'main':'main.tex'}).status_code,503)
        self.assertEqual(self.owner.post(self.path_for('/editor/latex'),json={'main':'../bad.tex'}).status_code,422)
        for name in ['../x','/x','a/../../x','.git/config','a\\x']:
            with self.assertRaises(ValueError):safe_path(name)

    def test_source_bundle_excludes_private_data(self):
        result=self.owner.get('/api/v1/editor/source')
        self.assertEqual(result.status_code,200)
        with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
            self.assertIn('editor-src/editor.js',archive.namelist())
            self.assertIn('latex_worker.py',archive.namelist())
            self.assertIn('third-party/texlyre/LICENSE',archive.namelist())
            self.assertFalse(any(x.startswith('data/') or '.env' in x or x.endswith('.db') for x in archive.namelist()))


if __name__=='__main__':unittest.main()
