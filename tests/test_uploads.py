import io
import sqlite3
from pathlib import Path
from pypdf import PdfWriter
import test_app


class ShopUploadTests(test_app.DigitXBDTests):
    def upload(self, client, phone='01755555555'):
        writer = PdfWriter(); writer.add_blank_page(width=100, height=100)
        content = io.BytesIO(); writer.write(content); content.seek(0)
        return self.post_form('/order', {'name':'Shop test','phone':phone,'consent':'yes','files':(content,'document.pdf')}, client)

    def test_shop_upload_reuses_customer_and_never_bills(self):
        public = self.app.test_client(); public.get('/order')
        before = self.totals()
        first = self.upload(public); second = self.upload(public)
        self.assertEqual(first.status_code,201,first.json)
        self.assertEqual(second.json['customer_id'],first.json['customer_id'])
        self.assertEqual(self.totals()['sales'],before['sales'])
        files = self.client.get('/api/files').json['rows']
        self.assertEqual(len(files),2); self.assertEqual(files[0]['source'],'shop')
        self.assertEqual(self.client.get('/api/orders').json,[])
        response = self.api('/api/orders/'+str(files[0]['order_id'])+'/confirm',{'quote':'100'})
        self.assertEqual(response.status_code,400)

    def test_pdf_inline_is_private_and_download_is_separate(self):
        public = self.app.test_client(); public.get('/order'); self.upload(public)
        file = self.client.get('/api/files').json['rows'][0]
        url = '/api/files/'+str(file['id'])
        self.assertNotEqual(public.get(url+'?view=1').status_code,200)
        viewed = self.client.get(url+'?view=1')
        self.assertEqual(viewed.status_code,200)
        self.assertEqual(viewed.mimetype,'application/pdf')
        self.assertTrue(viewed.headers['Content-Disposition'].startswith('inline'))
        downloaded = self.client.get(url)
        self.assertTrue(downloaded.headers['Content-Disposition'].startswith('attachment'))
        downloaded.close(); viewed.close()

    def test_shop_files_expire_from_upload_even_with_completion_policy(self):
        public = self.app.test_client(); public.get('/order'); self.upload(public)
        file = self.client.get('/api/files').json['rows'][0]
        with sqlite3.connect(Path(self.temp.name)/'digitxbd.sqlite') as con:
            con.execute("UPDATE orders SET created='2000-01-01T00:00:00' WHERE id=?",(file['order_id'],))
        listed = self.client.get('/api/files').json['rows'][0]
        self.assertIsNotNone(listed['deleted_at'])
        self.assertEqual(self.client.get('/api/files/'+str(file['id'])+'?view=1').status_code,410)

    def test_upload_requires_file_and_online_form_remains_separate(self):
        public = self.app.test_client(); page=public.get('/order')
        self.assertIn(b'Upload documents',page.data)
        self.assertNotIn(b'Black &amp; white pages',page.data)
        self.assertIn(b'Black &amp; white pages',public.get('/online_order').data)
        response=self.post_form('/order',{'name':'Shop test','phone':'01755555555','consent':'yes'},public)
        self.assertEqual(response.status_code,400)
