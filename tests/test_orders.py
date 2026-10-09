import io
import json
import sqlite3
from pathlib import Path
from pypdf import PdfWriter
from PIL import Image
import test_app


class OrderFeatureTests(test_app.DigitXBDTests):
    # Inherit the accounting regression tests as well.
    def public_client(self):
        client = self.app.test_client()
        client.get('/online_order')
        return client

    def pdf(self, count):
        writer = PdfWriter()
        for _ in range(count):
            writer.add_blank_page(width=595, height=842)
        stream = io.BytesIO()
        writer.write(stream)
        stream.seek(0)
        return stream

    def order(self, client, **changes):
        data = dict(name='Test student', phone='01700000000', service='Document Printing', details='Print all pages', quantity='2', pages='10', color='Color', binding='Spiral', consent='yes')
        data.update(changes)
        return self.post_form('/online_order', data, client)

    def test_pdf_count_and_multiple_files(self):
        client = self.public_client()
        image = io.BytesIO()
        Image.new('RGB', (20,20)).save(image, 'PNG')
        image.seek(0)
        result = self.post_form('/order/analyze', {'files': [(self.pdf(3), 'one.pdf'), (self.pdf(2), 'two.pdf'), (image, 'photo.png')]}, client)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['total_pages'], 6)
        self.assertTrue(result.json['complete'])
        self.assertEqual(self.client.get('/api/orders').json, [])

    def test_unknown_or_encrypted_pages_require_manual_count(self):
        client = self.public_client()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.encrypt('secret')
        stream = io.BytesIO(); writer.write(stream); stream.seek(0)
        result = self.post_form('/order/analyze', {'files': [(stream, 'locked.pdf'), (io.BytesIO(b'PKtest'), 'report.docx')]}, client)
        self.assertFalse(result.json['complete'])
        self.assertIsNone(result.json['total_pages'])
        self.assertTrue(all(f['pages'] is None for f in result.json['files']))

    def test_quotes_count_copies_pages_and_binding_without_billing(self):
        client = self.public_client()
        self.assertEqual(self.order(client, files=(self.pdf(10), 'report.pdf')).status_code, 201)
        order = self.client.get('/api/orders').json[0]
        options = json.loads(order['options'])
        self.assertEqual(options['detected_pages'], 10)
        self.assertEqual(options['minimum_quote'], 11000)
        self.assertIsNone(order['quote'])
        self.assertIsNone(order['invoice_id'])
        self.assertEqual(self.order(client, color='Black & White', minimum_quote='1').status_code, 201)
        self.assertEqual(json.loads(self.client.get('/api/orders').json[0]['options'])['minimum_quote'], 7000)

    def test_stamp_photo_minimum_enforced_by_server(self):
        client = self.public_client()
        self.assertEqual(self.order(client, service='Stamp Size Photo', quantity='7').status_code, 400)
        self.assertEqual(self.order(client, service='Stamp Size Photo', quantity='8', binding='None').status_code, 201)
        self.assertEqual(json.loads(self.client.get('/api/orders').json[0]['options'])['minimum_quote'], 4000)

    def test_customer_id_lookup_and_repeat_order_link(self):
        cid = self.customer()
        client = self.public_client()
        for number in ['01700000000', '+8801700000000']:
            result = self.api('/order/customer', {'phone': number}, client=client)
            self.assertEqual(result.json, {'customer_id': cid, 'multiple': False})
        self.assertEqual(self.order(client).status_code, 201)
        self.assertEqual(self.client.get('/api/orders').json[0]['customer_id'], cid)
        duplicate = self.api('/api/customers', {'name': 'Duplicate', 'phone': '+8801700000000'})
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(self.api('/order/customer', {'phone': '01711111111'}, client=client).json['customer_id'], None)

    def test_expired_delivered_files_deleted_but_active_files_retained(self):
        client = self.public_client()
        for _ in range(2):
            self.assertEqual(self.order(client, files=(self.pdf(2), 'job.pdf')).status_code, 201)
        orders = self.client.get('/api/orders').json
        path = Path(self.temp.name) / 'digitxbd.sqlite'
        with sqlite3.connect(path) as con:
            con.execute("UPDATE orders SET status='Delivered',completed_at='2020-01-01T00:00:00Z' WHERE id=?", (orders[0]['id'],))
            con.execute("UPDATE orders SET created='2020-01-01T00:00:00Z' WHERE id=?", (orders[1]['id'],))
        con.close()
        refreshed = self.client.get('/api/orders').json
        self.assertIsNotNone(refreshed[0]['files'][0]['deleted_at'])
        self.assertIsNone(refreshed[1]['files'][0]['deleted_at'])
        self.assertEqual(self.client.get('/api/files/'+str(orders[0]['files'][0]['id'])).status_code, 410)
        response = self.client.get('/api/files/'+str(orders[1]['files'][0]['id']))
        self.assertEqual(response.status_code, 200)
        response.close()
        self.assertEqual(len(list((Path(self.temp.name)/'uploads').iterdir())), 1)
        self.assertEqual(self.api('/api/settings', {'file_retention_days': '0'}, method='PUT').status_code, 400)
        self.assertEqual(self.api('/api/settings', {'file_retention_days': '30', 'file_retention_basis': 'upload'}, method='PUT').status_code, 200)
        self.assertIsNotNone(self.client.get('/api/orders').json[1]['files'][0]['deleted_at'])
