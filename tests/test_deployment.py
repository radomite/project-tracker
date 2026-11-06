"""Production setup and HTTPS-origin behavior at the app boundary."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import create_app


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        Path('.checks').mkdir(exist_ok=True)

    def test_first_account_requires_server_key_and_https_cookie(self):
        with tempfile.TemporaryDirectory(dir='.checks') as folder:
            root=Path(folder)
            key=root/'setup-key'
            key.write_text('a'*64,encoding='utf-8')
            with patch.dict(os.environ,{'RESEARCH_SETUP_TOKEN_FILE':str(key),
                    'RESEARCH_PUBLIC_ORIGIN':'https://project.example.org','RESEARCH_SECURE_COOKIE':'1'}):
                client=TestClient(create_app(root/'db.sqlite'),base_url='https://project.example.org')
                with client:
                    status=client.get('/api/v1/status').json()
                    self.assertTrue(status['setup_required'] and status['setup_token_required'])
                    payload={'name':'Owner','email':'owner@example.org','password':'long-password','sample_projects':False}
                    self.assertEqual(client.post('/api/v1/auth/setup',json=payload).status_code,403)
                    self.assertEqual(client.post('/api/v1/auth/setup',json={**payload,'setup_token':'wrong'}).status_code,403)
                    response=client.post('/api/v1/auth/setup',json={**payload,'setup_token':'a'*64},headers={'Origin':'https://project.example.org'})
                    self.assertEqual(response.status_code,201,response.text)
                    self.assertIn('Secure',response.headers['set-cookie'])
                    self.assertNotIn('a'*64,response.text)
                    self.assertEqual(client.get('/api/v1/status').json(),{'setup_required':False,'setup_token_required':False})
                    csrf=response.json()['csrf']
                    self.assertEqual(client.post('/api/v1/projects',json={'title':'Safe'},headers={
                        'Origin':'https://project.example.org','X-CSRF-Token':csrf}).status_code,201)
                    self.assertEqual(client.post('/api/v1/projects',json={'title':'Wrong origin'},headers={
                        'Origin':'https://wrong.example.org','X-CSRF-Token':csrf}).status_code,403)

    def test_configured_empty_or_missing_setup_key_fails_closed(self):
        with tempfile.TemporaryDirectory(dir='.checks') as folder:
            key=Path(folder)/'setup-key'
            key.write_text('',encoding='utf-8')
            with patch.dict(os.environ,{'RESEARCH_SETUP_TOKEN_FILE':str(key)}):
                with self.assertRaises(ValueError):create_app(Path(folder)/'db.sqlite')
                key.unlink()
                with self.assertRaises(FileNotFoundError):create_app(Path(folder)/'db.sqlite')
