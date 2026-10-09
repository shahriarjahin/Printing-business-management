import io
import sqlite3
import unittest
from pathlib import Path
import test_app

class UsabilityTests(unittest.TestCase):
    setUp=test_app.DigitXBDTests.setUp
    tearDown=test_app.DigitXBDTests.tearDown
    token=test_app.DigitXBDTests.token
    post_form=test_app.DigitXBDTests.post_form
    login=test_app.DigitXBDTests.login
    api=test_app.DigitXBDTests.api

    def delete(self,kind,rid):
        preview=self.client.get(f'/api/delete-preview/{kind}/{rid}').json
        result=self.api(f'/api/records/{kind}/{rid}',{'reason':'test duplicate','fingerprint':preview['fingerprint']},method='DELETE')
        self.assertEqual(result.status_code,200,result.json)
        return result.json['trash_id']

    def upload(self,client,size=40):
        return self.post_form('/order',{'name':'Upload test','phone':'01755555555','consent':'yes','files':(io.BytesIO(b'x'*size),'large.txt')},client)

    def test_customer_upload_exceeds_old_file_and_order_limits(self):
        public=self.app.test_client();public.get('/order')
        size=33*1024*1024
        response=self.upload(public,size)
        self.assertEqual(response.status_code,201,response.json)
        record=self.client.get('/api/files').json['rows'][0]
        self.assertEqual(record['size'],size)
        with sqlite3.connect(Path(self.temp.name)/'digitxbd.sqlite') as con:
            stored=con.execute('SELECT stored FROM files WHERE id=?',(record['id'],)).fetchone()[0]
        self.assertEqual((Path(self.temp.name)/'uploads'/stored).stat().st_size,size)
        self.assertEqual(list((Path(self.temp.name)/'.upload-tmp').iterdir()),[])
        self.assertIsNone(self.app.config['MAX_CONTENT_LENGTH'])

    def test_large_page_analysis_and_public_progress_assets(self):
        public=self.app.test_client();public.get('/order')
        response=self.post_form('/order/analyze',{'files':(io.BytesIO(b'x'*(17*1024*1024)),'large.txt')},public)
        self.assertEqual(response.status_code,200,response.json)
        self.assertFalse(response.json['complete'])
        for url in ['/order','/online_order']:
            html=public.get(url).text
            self.assertIn('/static/upload-progress.js',html)
            self.assertNotIn('16 MB',html)
            self.assertNotIn('32 MB',html)

    def test_clear_bin_requires_confirmation_and_preserves_live_records(self):
        customer=self.api('/api/customers',{'name':'Deleted test','phone':'01800000000'}).json['id']
        trash_id=self.delete('customers',customer)
        before=self.client.get('/api/dashboard').json['totals']
        preview=self.client.get('/api/recycle-bin/clear-preview').json
        self.assertEqual(preview['count'],1)
        self.assertEqual(self.api('/api/recycle-bin/clear',{'fingerprint':preview['fingerprint']}).status_code,400)
        self.assertEqual(self.api('/api/recycle-bin/clear',{'confirmation':'CLEAR','fingerprint':preview['fingerprint']}).status_code,200)
        self.assertEqual(self.client.get('/api/recycle-bin').json,[])
        self.assertEqual(self.api(f'/api/recycle-bin/{trash_id}/restore',{}).status_code,404)
        self.assertEqual(self.client.get('/api/dashboard').json['totals'],before)
        with sqlite3.connect(Path(self.temp.name)/'digitxbd.sqlite') as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM audit WHERE action='recycle-bin.clear'").fetchone()[0],1)

    def test_clear_bin_rejects_stale_preview_and_removes_only_deleted_files(self):
        public=self.app.test_client();public.get('/order');self.upload(public);self.upload(public)
        files=self.client.get('/api/files').json['rows']
        with sqlite3.connect(Path(self.temp.name)/'digitxbd.sqlite') as con:
            stored={r[0]:r[1] for r in con.execute('SELECT id,stored FROM files')}
        self.delete('files',files[0]['id'])
        preview=self.client.get('/api/recycle-bin/clear-preview').json
        customer=self.api('/api/customers',{'name':'Deleted test','phone':'01800000000'}).json['id']
        self.delete('customers',customer)
        self.assertEqual(self.api('/api/recycle-bin/clear',{'confirmation':'CLEAR','fingerprint':preview['fingerprint']}).status_code,400)
        preview=self.client.get('/api/recycle-bin/clear-preview').json
        self.assertEqual(self.api('/api/recycle-bin/clear',{'confirmation':'CLEAR','fingerprint':preview['fingerprint']}).status_code,200)
        self.assertFalse((Path(self.temp.name)/'uploads'/stored[files[0]['id']]).exists())
        self.assertTrue((Path(self.temp.name)/'uploads'/stored[files[1]['id']]).exists())
        guest=self.app.test_client();guest.get('/login')
        self.assertEqual(self.api('/api/recycle-bin/clear',{'confirmation':'CLEAR','fingerprint':preview['fingerprint']},client=guest).status_code,401)

if __name__=='__main__':
    unittest.main()
