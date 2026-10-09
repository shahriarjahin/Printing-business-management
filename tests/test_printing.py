import io
import sqlite3
import time
import unittest
import uuid
from pathlib import Path
from pypdf import PdfWriter
from werkzeug.security import generate_password_hash
import test_app

class PrintingTests(unittest.TestCase):
    setUp = test_app.DigitXBDTests.setUp
    tearDown = test_app.DigitXBDTests.tearDown
    token = test_app.DigitXBDTests.token
    post_form = test_app.DigitXBDTests.post_form
    login = test_app.DigitXBDTests.login
    api = test_app.DigitXBDTests.api

    def prepare(self, encrypted=False):
        public = self.app.test_client(); public.get('/order')
        pdf = PdfWriter()
        for _ in range(3):
            pdf.add_blank_page(width=595, height=842)
        if encrypted:
            pdf.encrypt('secret')
        content = io.BytesIO(); pdf.write(content); content.seek(0)
        upload = self.post_form('/order', {'name': 'Print customer', 'phone': '01755555555', 'consent': 'yes', 'files': (content, 'document.pdf')}, public)
        self.assertEqual(upload.status_code, 201, upload.json)
        self.fid = self.client.get('/api/files').json['rows'][0]['id']
        self.key = self.api('/api/printing/pair', {}).json['token']
        self.agent = self.app.test_client()
        self.auth = {'Authorization': 'Bearer '+self.key, 'X-Print-Helper': str(uuid.uuid4())}
        heartbeat = self.agent.post('/api/print-agent/heartbeat', headers=self.auth, json={'printer': 'Canon G3010 series', 'printers': ['Canon G3010 series']})
        self.assertEqual(heartbeat.status_code, 200, heartbeat.json)

    def queue(self, **changes):
        payload = {'file_id': self.fid, 'copies': 2, 'pages': '1-2', 'mode': 'monochrome', 'paper': 'A4', 'scale': 'fit', 'request_key': str(uuid.uuid4())}
        payload.update(changes)
        return self.api('/api/printing/jobs', payload)

    def claim(self):
        return self.agent.post('/api/print-agent/next', headers=self.auth, json={}).json['job']

    def test_queue_claim_download_result_and_money_unchanged(self):
        self.prepare()
        before = self.client.get('/api/dashboard').json['totals']
        request_key = str(uuid.uuid4())
        first = self.queue(request_key=request_key); second = self.queue(request_key=request_key)
        self.assertEqual(first.status_code, 201, first.json)
        self.assertEqual(second.json['id'], first.json['id'])
        job = self.claim(); self.assertEqual(job, self.claim())
        headers = {**self.auth, 'X-Print-Claim': job['claim_key']}
        downloaded = self.agent.get(f"/api/print-agent/jobs/{job['id']}/file", headers=headers)
        self.assertEqual(downloaded.status_code, 200)
        self.assertTrue(downloaded.data.startswith(b'%PDF-')); downloaded.close()
        url = f"/api/print-agent/jobs/{job['id']}/result"
        for _ in range(2):
            self.assertEqual(self.agent.post(url, headers=headers, json={'status': 'submitted'}).status_code, 200)
        self.assertIsNone(self.claim())
        self.assertEqual(self.agent.post(url, headers=headers, json={'status': 'failed'}).status_code, 409)
        self.assertEqual(self.client.get('/api/dashboard').json['totals'], before)

    def test_auth_csrf_scope_and_staff_restriction(self):
        self.prepare(); public = self.app.test_client()
        self.assertEqual(public.post('/api/print-agent/next', json={}).status_code, 401)
        self.assertEqual(public.post('/api/printing/pair', json={}, headers=self.auth).status_code, 403)
        with sqlite3.connect(Path(self.temp.name)/'digitxbd.sqlite') as con:
            con.execute('INSERT INTO users(username,password,role) VALUES(?,?,?)', ('staff', generate_password_hash('A-valid-test-password'), 'staff'))
        staff = self.app.test_client(); self.login('staff', client=staff)
        self.assertEqual(self.api('/api/printing/pair', {}, client=staff).status_code, 403)
        self.assertEqual(staff.get('/api/printing').status_code, 403)
        self.assertEqual(self.agent.get('/api/files/'+str(self.fid), headers=self.auth).status_code, 401)
        self.assertEqual(self.agent.post('/api/print-agent/next', json={}, headers={**self.auth, 'X-Print-Helper': str(uuid.uuid4())}).status_code, 403)
        replacement = self.api('/api/printing/pair', {}).json['token']
        self.assertNotEqual(replacement, self.key)
        self.assertEqual(self.agent.post('/api/print-agent/next', json={}, headers=self.auth).status_code, 401)

    def test_page_validation_and_pdf_encryption(self):
        self.prepare()
        for changes in [{'pages': '4'}, {'pages': '2-1'}, {'pages': '1-2,2'}, {'pages': '1;calc'}, {'copies': 51}, {'mode': 'color,100x'}, {'paper': 'A3'}, {'scale': 'other'}]:
            self.assertEqual(self.queue(**changes).status_code, 400, changes)
        self.assertEqual(self.queue(pages='1,3').status_code, 201)
        self.prepare(encrypted=True)
        self.assertEqual(self.queue().status_code, 400)

    def test_expired_documents_and_claim_secret(self):
        self.prepare(); self.queue(); job = self.claim()
        url = f"/api/print-agent/jobs/{job['id']}/file"
        self.assertEqual(self.agent.get(url, headers=self.auth).status_code, 409)
        with sqlite3.connect(Path(self.temp.name)/'digitxbd.sqlite') as con:
            con.execute("UPDATE files SET deleted_at='2020-01-01' WHERE id=?", (self.fid,))
        self.assertEqual(self.agent.get(url, headers={**self.auth, 'X-Print-Claim': job['claim_key']}).status_code, 400)
        self.assertEqual(self.queue().status_code, 400)

    def test_cancel_and_stale_claim_never_reprints(self):
        self.prepare(); cancel_id = self.queue().json['id']
        self.assertEqual(self.api(f'/api/printing/jobs/{cancel_id}/cancel', {}).status_code, 200)
        self.assertIsNone(self.claim())
        self.queue(); job = self.claim()
        self.assertEqual(self.api(f"/api/printing/jobs/{job['id']}/cancel", {}).status_code, 400)
        with sqlite3.connect(Path(self.temp.name)/'digitxbd.sqlite') as con:
            con.execute('UPDATE print_jobs SET claimed_at=? WHERE id=?', (time.time()-1000, job['id']))
        self.assertIsNone(self.claim())
        self.assertEqual(self.client.get('/api/printing').json['jobs'][0]['status'], 'uncertain')
        self.queue(); self.assertNotEqual(self.claim()['id'], job['id'])

    def test_helper_package_and_disconnect(self):
        self.prepare(); self.queue()
        response = self.client.get('/api/printing/helper.zip')
        import zipfile
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertIn('Setup-Printer.ps1', archive.namelist())
        self.assertEqual(self.api('/api/printing/disconnect', {}).status_code, 200)
        self.assertEqual(self.agent.post('/api/print-agent/next', headers=self.auth, json={}).status_code, 401)
        self.assertEqual(self.client.get('/api/printing').json['jobs'][0]['status'], 'cancelled')

    def test_restore_revokes_helper_and_cancels_pending_jobs(self):
        self.prepare(); self.queue(); self.claim()
        backup = self.client.get('/api/backup')
        path = Path(self.temp.name)/'test-backup.zip'
        path.write_bytes(backup.data); backup.close()
        import os
        import subprocess
        import sys
        response = subprocess.run([sys.executable, str(Path(__file__).parents[1]/'restore_backup.py'), str(path)], env={**os.environ, 'DATA_DIR': self.temp.name}, capture_output=True, text=True)
        self.assertEqual(response.returncode, 0, response.stderr)
        with sqlite3.connect(Path(self.temp.name)/'digitxbd.sqlite') as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM print_agent').fetchone()[0], 0)
            self.assertEqual(con.execute('SELECT status FROM print_jobs').fetchone()[0], 'cancelled')

if __name__ == '__main__':
    unittest.main()
