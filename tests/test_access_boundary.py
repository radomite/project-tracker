"""Probe authentication before parsing, all live API routes, assets, and sockets."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import test_api as fixtures


class AccessBoundaryTests(unittest.TestCase):
    setUp=fixtures.NotebookTests.setUp
    tearDown=fixtures.NotebookTests.tearDown
    path_for=fixtures.NotebookTests.path_for
    collaborator=fixtures.NotebookTests.collaborator
    agent=fixtures.NotebookTests.agent

    def anonymous(self):
        client=TestClient(self.app);self.clients.append(client);return client

    def test_public_page_is_only_login_and_application_assets_require_a_session(self):
        client=self.anonymous()
        response=client.get('/')
        self.assertEqual(response.status_code,200)
        self.assertIn('/static/login.js',response.text)
        self.assertNotIn('/static/app.js',response.text)
        self.assertNotIn('First project',response.text)
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertIn("frame-ancestors 'none'",response.headers['content-security-policy'])
        for path in ['/static/login.js','/static/login.css']:
            self.assertEqual(client.get(path).status_code,200,path)
        for path in ['/static/app.js','/static/index.html','/static/agents.js',
                     '/static/editor-assets/editor.js','/static/vendor/katex.js']:
            denied=client.get(path)
            self.assertEqual(denied.status_code,401,path)
            self.assertEqual(denied.headers['cache-control'],'no-store')
        self.assertIn('/static/app.js',self.owner.get('/').text)
        self.assertEqual(self.owner.get('/static/app.js').status_code,200)

    def test_every_remaining_api_route_rejects_anonymous_before_parsing(self):
        client=self.anonymous()
        public={('GET','/api/v1/status'),('POST','/api/v1/auth/setup'),
                ('POST','/api/v1/auth/login'),('POST','/api/v1/auth/register')}
        for route in self.app.routes:
            if not isinstance(route,APIRoute) or not route.path.startswith('/api/'):continue
            for method in route.methods:
                if (method,route.path) in public:continue
                path=route.path
                for parameter in route.param_convertors:
                    path=path.replace('{'+parameter+'}','astra' if parameter=='role' else '1')
                with self.subTest(method=method,path=path):
                    response=client.request(method,path,content=b'{',headers={'Content-Type':'application/json'})
                    self.assertEqual(response.status_code,401,response.text)

    def test_future_api_routes_are_protected_by_default(self):
        @self.app.get('/api/v1/future-feature')
        def future():return {'private':'content'}
        self.assertEqual(self.anonymous().get('/api/v1/future-feature').status_code,401)
        self.assertEqual(self.owner.get('/api/v1/future-feature').status_code,200)

    def test_documentation_and_legacy_routes_are_absent(self):
        for path in ['/docs','/docs/oauth2-redirect','/redoc','/openapi.json']:
            self.assertEqual(self.anonymous().get(path).status_code,404,path)
        for method,suffix in [('GET','/items'),('POST','/items'),('GET','/items/1'),
                ('PATCH','/items/1'),('GET','/items/1/history'),('PUT','/main-questions'),
                ('GET','/linked-projects'),('GET','/notes'),('POST','/notes'),
                ('POST','/notes/upload'),('GET','/notes/1'),('GET','/notes/1/download'),
                ('GET','/questions/1/open-ends'),('POST','/questions/1/open-ends'),
                ('PATCH','/open-ends/1'),('PUT','/open-ends/1/rating'),('GET','/open-ends/1/ratings')]:
            self.assertIn(self.owner.request(method,self.path_for(suffix),json={}).status_code,(404,405),suffix)

    def test_expired_and_logged_out_sessions_cannot_read_assets_or_data(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE sessions SET expires_at='2000-01-01'");db.commit()
        self.assertEqual(self.owner.get('/api/v1/projects').status_code,401)
        self.assertEqual(self.owner.get('/static/app.js').status_code,401)
        self.assertIn('/static/login.js',self.owner.get('/').text)
        login=self.owner.post('/api/v1/auth/login',json={'email':'ada@example.org','password':'a secure password'})
        self.owner.headers['X-CSRF-Token']=login.json()['csrf']
        self.assertEqual(self.owner.post('/api/v1/auth/logout').status_code,200)
        self.assertEqual(self.owner.get('/static/app.js').status_code,401)

    def test_a_valid_account_cannot_read_any_other_projects_get_route(self):
        bob,_=self.collaborator()
        foreign=bob.post('/api/v1/projects',json={'title':'Private Bob project'}).json()['id']
        for route in self.app.routes:
            if not isinstance(route,APIRoute) or 'GET' not in route.methods or '{project_id}' not in route.path:continue
            path=route.path
            for parameter in route.param_convertors:
                value=str(foreign) if parameter=='project_id' else 'astra' if parameter=='role' else '1'
                path=path.replace('{'+parameter+'}',value)
            with self.subTest(path=path):
                response=self.owner.get(path,params={'path':'secret.txt'})
                self.assertEqual(response.status_code,404,response.text)
                self.assertNotIn('Private Bob project',response.text)

    def test_registration_requires_an_invitation_and_setup_cannot_be_reused(self):
        client=self.anonymous()
        payload={'name':'Uninvited','email':'intruder@example.org','password':'long-password'}
        self.assertEqual(client.post('/api/v1/auth/register',json=payload).status_code,422)
        self.assertEqual(client.post('/api/v1/auth/register',json={**payload,'token':'x'*43}).status_code,400)
        self.assertEqual(client.post('/api/v1/auth/setup',json=payload).status_code,409)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0],1)

    def test_invalid_bearer_cannot_fall_back_to_an_authenticated_cookie(self):
        self.assertEqual(self.owner.get('/api/v1/projects',headers={'Authorization':'Bearer wrong'}).status_code,401)
        self.assertEqual(self.owner.get('/api/v1/projects',headers={'Authorization':'Basic wrong'}).status_code,401)
        agent,_=self.agent(scope='read')
        self.assertEqual(agent.get('/static/app.js').status_code,401)
        self.assertEqual(agent.get(self.path_for('/export')).status_code,403)

    def test_internal_service_needs_its_own_credential_before_parsing(self):
        with tempfile.TemporaryDirectory(dir='.checks') as folder:
            key=Path(folder)/'service-key';key.write_text('s'*64)
            with patch.dict(os.environ,{'RESEARCH_AGENT_SECRET_FILE':str(key)}):
                for client in [self.anonymous(),self.owner]:
                    response=client.post('/internal/agents/runs/1/tool',content=b'{',headers={'Content-Type':'application/json'})
                    self.assertEqual(response.status_code,401)
                self.assertEqual(self.anonymous().get('/api/v1/projects',headers={'Authorization':'Bearer '+'s'*64}).status_code,401)
                self.assertEqual(self.anonymous().post('/internal/agents/claim',headers={'Authorization':'s'*64}).status_code,401)

    def test_websocket_rejects_anonymous_or_nonmember_before_handshake_and_null_csrf(self):
        path=self.path_for('/editor/ws')
        client=self.anonymous()
        with self.assertRaises(WebSocketDisconnect):
            with client.websocket_connect(path,headers={'origin':'http://testserver'}):pass
        bob,_=self.collaborator()
        foreign=bob.post('/api/v1/projects',json={'title':'Private'}).json()['id']
        with self.assertRaises(WebSocketDisconnect):
            with self.owner.websocket_connect(self.path_for('/editor/ws',foreign),headers={'origin':'http://testserver'}):pass
        with self.owner:
            with self.owner.websocket_connect(path,headers={'origin':'http://testserver'}) as ws:
                ws.send_json({'csrf':None})
                self.assertEqual(ws.receive_json()['type'],'error')
