"""Checks for the Home Assistant wrapper, ingress links, and backup safety."""
import asyncio
import io
import os
import re
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import httpx
import yaml

from app.db import initialize
from import_backup import BackupImportError, import_backup

HERE = Path(__file__).resolve().parents[1]
PREFIX = '/api/hassio_ingress/MockIngress_Token.123'


def _create_backup(path: Path, data: Path):
    initialize(data/'rechnung.sqlite3')
    with zipfile.ZipFile(path,'w') as zf:
        zf.write(data/'rechnung.sqlite3','rechnung.sqlite3')
        zf.writestr('uploads/1/test.jpg', b'hello')
        zf.writestr('archive/1/0001.pdf', b'%PDF-test')
        zf.writestr('README.txt', 'Swiss-invoice-RX demo')


class ConfigTests(unittest.TestCase):
    def test_repo_yaml_and_config(self):
        repo = yaml.safe_load((HERE.parent/'repository.yaml').read_text())
        cfg = yaml.safe_load((HERE/'config.yaml').read_text())
        self.assertIn('richieam93/ha-Swiss-invoice', repo['url'])
        self.assertEqual(cfg['slug'], HERE.name)
        self.assertEqual(cfg['name'], 'Swiss-invoice-RX')
        self.assertEqual(cfg['version'], '2.11.0')
        self.assertTrue(cfg['ingress'])
        self.assertEqual(cfg['ingress_port'], 8765)
        self.assertFalse(cfg['panel_admin'])
        self.assertIsNone(cfg['ports']['8765/tcp'])  # bewusst opt-in nach Home-Assistant-Empfehlung
        self.assertNotIn('webui', cfg)  # Ingress bleibt primaerer Einstieg
        self.assertFalse(cfg.get('host_network', False))
        self.assertEqual(cfg['backup'], 'cold')
        self.assertEqual(set(cfg['arch']), {'amd64','aarch64'})

    def test_template_urls_use_ingress_prefix(self):
        for file in (HERE/'app/templates').glob('*.html'):
            contents=file.read_text()
            for field in ('href','src','action','formaction'):
                self.assertNotIn(field+'="/', contents, file.name)
            # Kein vom Home Assistant ignorierter statischer Root-Pfad.
        js=(HERE/'app/static/app.js').read_text()
        self.assertIn('SWISS_BASE',js)
        self.assertIn('SWISS_BASE + \'/api/search',js)


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.original=self.root/'windows'
        self.original.mkdir()
        self.archive=self.root/'backup.zip'
        _create_backup(self.archive,self.original)
        self.target=self.root/'addon'

    def test_valid_windows_backup(self):
        imported=import_backup(self.archive,self.target)
        self.assertIn('rechnung.sqlite3',imported)
        self.assertEqual((self.target/'uploads/1/test.jpg').read_bytes(), b'hello')
        with sqlite3.connect(self.target/'rechnung.sqlite3') as con:
            self.assertEqual(con.execute('pragma integrity_check').fetchone()[0], 'ok')

    def test_rejects_existing_database(self):
        import_backup(self.archive,self.target)
        with self.assertRaisesRegex(BackupImportError,'nicht ueberschrieben'):
            import_backup(self.archive,self.target)

    def test_rejects_zip_traversal(self):
        malicious=self.root/'bad.zip'
        with zipfile.ZipFile(malicious,'w') as zf:
            zf.write(self.original/'rechnung.sqlite3','rechnung.sqlite3')
            zf.writestr('uploads/../../evil.txt','oops')
        with self.assertRaises(BackupImportError):
            import_backup(malicious,self.target)
        self.assertFalse((self.target/'rechnung.sqlite3').exists())

    def test_rejects_foreign_file(self):
        malicious=self.root/'bad.zip'
        with zipfile.ZipFile(malicious,'w') as zf:
            zf.write(self.original/'rechnung.sqlite3','rechnung.sqlite3')
            zf.writestr('.session_key','secret')
        with self.assertRaises(BackupImportError):
            import_backup(malicious,self.target)
        self.assertFalse((self.target/'rechnung.sqlite3').exists())

    def test_rejects_corrupt_database(self):
        malicious=self.root/'bad.zip'
        with zipfile.ZipFile(malicious,'w') as zf:
            zf.writestr('rechnung.sqlite3',b'not sqlite')
        with self.assertRaises((BackupImportError,sqlite3.DatabaseError)):
            import_backup(malicious,self.target)
        self.assertFalse((self.target/'rechnung.sqlite3').exists())


class IngressTests(unittest.TestCase):
    def test_ingress_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ,{'SWISS_INVOICE_INGRESS':'1','SWISS_INVOICE_DATA_DIR':tmp}):
                from app.main import create_app
                app=create_app(tmp)

                async def run():
                    transport=httpx.ASGITransport(app=app,client=('172.30.32.2',18483))
                    async with httpx.AsyncClient(transport=transport,base_url='http://internal',follow_redirects=False,
                                                 headers={'X-Ingress-Path':PREFIX}) as c:
                        r=await c.get('/')
                        self.assertEqual(r.status_code,303)
                        self.assertEqual(r.headers['location'],PREFIX+'/setup')
                        page=await c.get('/setup')
                        self.assertEqual(page.status_code,200)
                        self.assertIn(f'action="{PREFIX}/setup"',page.text)
                        self.assertIn(f'href="{PREFIX}/static/app.css"',page.text)
                        self.assertEqual(page.headers['x-frame-options'],'SAMEORIGIN')
                        self.assertIn("frame-ancestors 'self'",page.headers['content-security-policy'])
                        csrf=re.search(r'name="_csrf" value="([a-z0-9]+)"',page.text).group(1)
                        submit=await c.post('/setup',data={'_csrf':csrf, 'company_name':'QR AG',
                            'full_name':'Administrator', 'email':'boss@example.ch',
                            'password':'Passwort12345!', 'password2':'Passwort12345!'})
                        self.assertEqual(submit.status_code,303,submit.text[:200])
                        self.assertEqual(submit.headers['location'],PREFIX+'/settings')
                        dash=await c.get('/dashboard')
                        self.assertEqual(dash.status_code,200)
                        self.assertIn('Swiss-invoice-RX', dash.text)
                        self.assertIn(f'href="{PREFIX}/invoices?kind=invoice"',dash.text)
                        self.assertIn(f'action="{PREFIX}/company/switch"',dash.text)
                        css=await c.get('/static/app.css')
                        self.assertEqual(css.status_code,200)
                        js=await c.get('/static/app.js')
                        self.assertEqual(js.status_code,200)
                        health=await c.get('/health')
                        self.assertEqual(health.json()['application'],'Swiss-invoice-RX')
                        bad=await c.get('/help',headers={'X-Ingress-Path':'/evil/path'})
                        self.assertEqual(bad.status_code,400)
                    # Private LAN-IP erlaubt, aber ohne Sitzung keine Firmendaten.
                    outsider=httpx.ASGITransport(app=app,client=('192.168.1.27',12345))
                    async with httpx.AsyncClient(transport=outsider,base_url='http://internal') as c:
                        self.assertEqual((await c.get('/health')).status_code,200)
                        r=await c.get('/dashboard',follow_redirects=False)
                        self.assertEqual(r.status_code,303)
                        self.assertEqual(r.headers['location'],'/login')
                        # Direkte LAN-Benutzer duerfen keinen Supervisor-Header faelschen.
                        spoof=await c.get('/',headers={'X-Ingress-Path':PREFIX})
                        self.assertEqual(spoof.status_code,403)
                    public=httpx.ASGITransport(app=app,client=('8.8.8.8',12345))
                    async with httpx.AsyncClient(transport=public,base_url='http://internal') as c:
                        self.assertEqual((await c.get('/health')).status_code,403)
                asyncio.run(run())


if __name__=='__main__':
    unittest.main()
