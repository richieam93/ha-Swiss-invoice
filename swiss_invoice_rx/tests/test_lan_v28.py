"""Swiss-invoice-RX 2.8: direkte LAN-Anmeldung und Ingress laufen parallel."""
import asyncio
import os
import re
import tempfile
import unittest
from unittest.mock import patch

import httpx


class LanAccessTests(unittest.TestCase):
    def test_direct_lan_setup_and_separate_login(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {'SWISS_INVOICE_INGRESS': '1', 'SWISS_INVOICE_DATA_DIR': root}):
                from app.main import create_app
                app = create_app(root)

                async def test():
                    first = httpx.ASGITransport(app=app, client=('192.168.1.25', 15123))
                    async with httpx.AsyncClient(transport=first,
                            base_url='http://192.168.1.10:8765', follow_redirects=False) as c:
                        index = await c.get('/')
                        self.assertEqual(index.status_code, 303)
                        self.assertEqual(index.headers['location'], '/setup')
                        setup = await c.get('/setup')
                        self.assertEqual(setup.status_code, 200)
                        self.assertIn('href="/static/app.css"', setup.text)
                        self.assertIn('action="/setup"', setup.text)
                        csrf = re.search(r'name="_csrf" value="([a-z0-9]+)"', setup.text).group(1)
                        created = await c.post('/setup', data={
                            '_csrf': csrf, 'company_name': 'Heimnetz AG',
                            'full_name': 'Administrator', 'email': 'lan@example.ch',
                            'password': 'SicheresPasswort987!', 'password2': 'SicheresPasswort987!'
                        })
                        self.assertEqual(created.status_code, 303)
                        self.assertEqual(created.headers['location'], '/settings')
                        dash = await c.get('/dashboard')
                        self.assertEqual(dash.status_code, 200)
                        self.assertIn('Heimnetz AG', dash.text)
                        self.assertNotIn('/api/hassio_ingress/', dash.text)
                        self.assertEqual((await c.get('/static/app.css')).status_code, 200)
                        self.assertEqual((await c.get('/static/app.js')).status_code, 200)

                    another = httpx.ASGITransport(app=app, client=('192.168.1.31', 21212))
                    async with httpx.AsyncClient(transport=another,
                            base_url='http://192.168.1.10:8765', follow_redirects=False) as c:
                        blocked = await c.get('/dashboard')
                        self.assertEqual(blocked.status_code, 303)
                        self.assertEqual(blocked.headers['location'], '/login')
                        login = await c.get('/login')
                        self.assertEqual(login.status_code, 200)
                        csrf = re.search(r'name="_csrf" value="([a-z0-9]+)"', login.text).group(1)
                        entered = await c.post('/login', data={
                            '_csrf': csrf, 'email': 'lan@example.ch', 'password': 'SicheresPasswort987!'
                        })
                        self.assertEqual(entered.status_code, 303)
                        self.assertEqual(entered.headers['location'], '/dashboard')
                        self.assertEqual((await c.get('/dashboard')).status_code, 200)
                        spoof = await c.get('/dashboard', headers={
                            'X-Ingress-Path': '/api/hassio_ingress/fake_token'
                        })
                        self.assertEqual(spoof.status_code, 403)

                asyncio.run(test())

    def test_nonprivate_sources_denied(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {'SWISS_INVOICE_INGRESS': '1', 'SWISS_INVOICE_DATA_DIR': root}):
                from app.main import create_app
                app = create_app(root)

                async def test():
                    for client_ip in ('8.8.8.8', '2001:4860:4860::8888'):
                        transport = httpx.ASGITransport(app=app, client=(client_ip, 1000))
                        async with httpx.AsyncClient(transport=transport,
                                base_url='http://example.net', follow_redirects=False) as c:
                            self.assertEqual((await c.get('/health')).status_code, 403)
                    for client_ip in ('127.0.0.1', '192.168.178.9', '10.12.13.2', 'fd00::abcd'):
                        transport = httpx.ASGITransport(app=app, client=(client_ip, 1000))
                        async with httpx.AsyncClient(transport=transport,
                                base_url='http://example.net', follow_redirects=False) as c:
                            self.assertEqual((await c.get('/health')).status_code, 200)

                asyncio.run(test())

if __name__ == '__main__':
    unittest.main()
