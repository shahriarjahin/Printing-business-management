import io
import json
import sqlite3
import uuid
from pathlib import Path
import test_workflow


class RecordTests(test_workflow.WorkflowTests):
    def delete(self,kind,rid,client=None):
        client=client or self.client
        preview=client.get('/api/delete-preview/'+kind+'/'+str(rid))
        self.assertEqual(preview.status_code,200,preview.json)
        result=self.api('/api/records/'+kind+'/'+str(rid),{'fingerprint':preview.json['fingerprint'],'reason':'Test duplicate correction'},method='DELETE',client=client)
        return result

    def restore(self,result):
        self.assertEqual(result.status_code,200,result.json)
        restored=self.api('/api/recycle-bin/'+str(result.json['trash_id'])+'/restore',{})
        self.assertEqual(restored.status_code,200,restored.json)

    def test_delete_invoice_and_linked_payments_restore_exact_totals(self):
        cid=self.customer();inv=self.invoice(cid)
        self.api('/api/transactions',{'customer_id':cid,'kind':'Payment','date':'2026-10-08','paid':'100','related_id':inv['id'],'request_key':str(uuid.uuid4())})
        before=self.totals()
        preview=self.client.get('/api/delete-preview/transactions/'+str(inv['id'])).json
        self.assertEqual(preview['counts']['ledger'],2)
        deleted=self.delete('transactions',inv['id'])
        self.assertEqual(self.totals()['sales'],before['sales']-100000)
        self.assertEqual(self.totals()['collected'],before['collected']-70000)
        self.assertEqual(self.client.get(inv['invoice_url']).status_code,404)
        self.restore(deleted)
        self.assertEqual(self.totals(),before)
        self.assertEqual(self.client.get(inv['invoice_url']).status_code,200)

    def test_delete_customer_with_history_then_restore_and_reserve_id(self):
        cid=self.customer();self.invoice(cid);before=self.totals()
        deleted=self.delete('customers',cid)
        self.assertEqual(self.totals()['customers'],before['customers']-1)
        added=self.api('/api/customers',{'name':'Another','phone':'01800000000'}).json['id']
        self.assertGreater(int(added[1:]),int(cid[1:]))
        self.restore(deleted)
        self.assertEqual(self.totals()['sales'],before['sales'])

    def test_delete_investment_and_restore_keeps_profit_separate(self):
        before=self.totals()
        eid=self.api('/api/expenses',{'kind':'Investment','amount':'5000','date':'2026-10-08','method':'Cash','category':'Other'}).json['id']
        deleted=self.delete('expenses',eid)
        self.assertEqual(self.totals(),before)
        self.restore(deleted)
        self.assertEqual(self.totals()['net_profit'],before['net_profit'])
        self.assertEqual(self.totals()['investment'],before['investment']+500000)

    def test_stock_delete_cash_sync_reserve_ids_and_historical_validation(self):
        iid=self.api('/api/inventory',{'name':'A4','unit':'sheet'}).json['id']
        self.api('/api/inventory/movement',{'item_id':iid,'kind':'Purchased','quantity':'10','unit_cost':'2','date':'2026-10-08'})
        inv=self.client.get('/api/inventory').json
        self.assertTrue(inv['movements'])
        move=inv['movements'][0];before=self.totals()
        deleted=self.delete('movements',move['id'])
        self.assertEqual(self.totals()['stock_purchase'],before['stock_purchase']-2000)
        self.api('/api/inventory/movement',{'item_id':iid,'kind':'Purchased','quantity':'5','unit_cost':'1','date':'2026-10-08'})
        self.assertNotEqual(self.client.get('/api/inventory').json['movements'][0]['id'],move['id'])
        self.restore(deleted)
        self.api('/api/inventory/movement',{'item_id':iid,'kind':'Used','quantity':'12','unit_cost':'0','date':'2026-10-08'})
        result=self.delete('movements',move['id'])
        self.assertEqual(result.status_code,400)
        self.assertIn('negative',result.json['error'])

    def test_order_delete_retains_invoice_and_restores_files(self):
        public=self.public_client();r=self.order(public).json
        order=self.client.get('/api/orders').json[0]
        inv=self.api('/api/orders/'+str(order['id'])+'/confirm',{'quote':'90','paid':'10'}).json
        before=self.totals();deleted=self.delete('orders',order['id'])
        self.assertEqual(self.totals(),before)
        self.assertEqual(self.client.get('/api/orders').json,[])
        self.restore(deleted)
        self.assertEqual(self.client.get('/api/orders').json[0]['invoice_url'],inv['invoice_url'])

    def test_deleted_invoice_reopens_order_and_restore_detects_conflict(self):
        self.order(self.public_client())
        o=self.client.get('/api/orders').json[0]
        invoice=self.api('/api/orders/'+str(o['id'])+'/confirm',{'quote':'90'}).json
        invoice['id']=self.client.get('/api/orders').json[0]['invoice_id']
        deleted=self.delete('transactions',invoice['id'])
        reopened=self.client.get('/api/orders').json[0]
        self.assertIsNone(reopened['invoice_id']);self.assertEqual(reopened['status'],'New')
        self.restore(deleted)
        self.assertEqual(self.client.get('/api/orders').json[0]['invoice_id'],invoice['id'])
        deleted=self.delete('transactions',invoice['id'])
        self.api('/api/orders/'+str(o['id'])+'/confirm',{'quote':'100'})
        response=self.api('/api/recycle-bin/'+str(deleted.json['trash_id'])+'/restore',{})
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.client.get('/api/transactions').json['total'],68)

    def test_delete_permissions_csrf_stale_preview_and_own_account(self):
        cid=self.customer()
        preview=self.client.get('/api/delete-preview/customers/'+cid).json
        self.invoice(cid)
        stale=self.api('/api/records/customers/'+cid,{'reason':'duplicate','fingerprint':preview['fingerprint']},method='DELETE')
        self.assertEqual(stale.status_code,409)
        self.assertEqual(self.client.delete('/api/records/customers/'+cid,json={}).status_code,403)
        self.assertEqual(self.client.get('/api/delete-preview/users/1').status_code,400)
        self.api('/api/users',{'username':'helper','password':'Valid-staff-password','role':'staff'})
        staff=self.app.test_client();self.login('helper','Valid-staff-password',staff)
        self.assertEqual(staff.get('/api/recycle-bin').status_code,403)
        self.assertEqual(self.api('/api/records/customers/'+cid,{},method='DELETE',client=staff).status_code,403)

    def test_customer_id_sort_and_transaction_balance_ignore_search(self):
        customers=self.client.get('/api/customers').json
        self.assertEqual([c['id'] for c in customers],sorted([c['id'] for c in customers],key=lambda x:int(x[1:])))
        cid=self.customer();inv=self.invoice(cid)
        payment=self.api('/api/transactions',{'customer_id':cid,'kind':'Payment','date':'2026-10-08','paid':'400','description':'Exact balance test','request_key':str(uuid.uuid4())})
        data=self.client.get('/api/transactions?q=Exact%20balance%20test').json['rows'][0]
        self.assertEqual(data['balance'],0)
        invoice=next(r for r in self.client.get('/api/transactions').json['rows'] if r['id']==inv['id'])
        self.assertEqual(invoice['remaining'],0)

    def test_branded_qr_and_invoice_header_layout(self):
        from qr_pay import crc16
        payload='0002010102112611TESTACCOUNT5204599953030505802BD5908DigitXBD6005Dhaka6304'
        payload+=crc16(payload)
        self.api('/api/settings',{'merchant_qr':payload},method='PUT')
        inv=self.invoice(self.customer())
        html=self.client.get(inv['invoice_url']).text
        self.assertNotIn('Bangla QR · Merchant payment',html)
        self.assertNotIn('Your original merchant QR',html)
        self.assertLess(html.index('Invoice verification QR'),html.index('BILL TO'))
        qr=self.client.get('/qr/invoice/'+inv['invoice_url'].rsplit('/',1)[1]+'.svg?payment=1&original=1&brand=1')
        self.assertEqual(qr.status_code,200)
        self.assertIn(b'data:image/svg+xml;base64,',qr.data)

    def test_restore_deleted_file_after_retention_marks_unavailable(self):
        public=self.public_client();self.order(public,files=(io.BytesIO(b'%PDF-1.4 fake'),'test.pdf'))
        o=self.client.get('/api/orders').json[0];self.assertTrue(o['files'])
        deleted=self.delete('orders',o['id'])
        conn=sqlite3.connect(Path(self.temp.name)/'digitxbd.sqlite')
        conn.execute("UPDATE recycle_bin SET created='2000-01-01T00:00:00Z'");conn.commit();conn.close()
        self.client.get('/api/orders')
        self.restore(deleted)
        self.assertEqual(self.client.get('/api/files/'+str(o['files'][0]['id'])).status_code,410)

    def test_paid_watermark_due_method_and_statement_label(self):
        cid=self.customer();invoice=self.invoice(cid,paid='0')
        unpaid=self.client.get(invoice['invoice_url']).text
        self.assertNotIn('Payment method</dt>',unpaid)
        self.assertNotIn('class="paid-watermark"',unpaid)
        self.api('/api/transactions',{'customer_id':cid,'kind':'Payment','date':'2026-10-08','paid':'1000','method':'bKash','related_id':invoice['id'],'request_key':str(uuid.uuid4())})
        paid=self.client.get(invoice['invoice_url']).text
        self.assertIn('class="paid-watermark"',paid)
        self.assertIn('bKash',paid)
        self.assertNotIn('<dd>Cash</dd>',paid)
        reminder=self.client.get('/api/reminder/'+cid).json
        statement=self.client.get('/'+reminder['statement_url'].split('/',3)[3]).text
        self.assertIn('Current due',statement)
        self.assertNotIn('Current balance',statement)

    def test_service_inventory_user_delete_restore_and_id_reservation(self):
        for kind,path,data in [('services','/api/services',{'name':'Photo','price':'5','cost':'1'}),('inventory','/api/inventory',{'name':'Toner','unit':'piece'})]:
            rid=self.api(path,data).json['id'];deleted=self.delete(kind,rid)
            newer=self.api(path,{**data,'name':'Second'}).json['id']
            self.assertGreater(newer,rid)
            self.restore(deleted)
        self.api('/api/users',{'username':'temporary','password':'Valid-preview-password','role':'staff'})
        uid=self.client.get('/api/users').json[-1]['id']
        deleted=self.delete('users',uid)
        self.assertFalse(any(u['id']==uid for u in self.client.get('/api/users').json))
        self.restore(deleted)
        self.assertTrue(any(u['id']==uid for u in self.client.get('/api/users').json))

    def upload_merchant(self,color='white',client=None):
        from PIL import Image
        stream=io.BytesIO();Image.new('RGB',(90,120),color).save(stream,'PNG');original=stream.getvalue();stream.seek(0)
        response=(client or self.client).post('/api/merchant-qr',data={'image':(stream,'original.png')},headers={'X-CSRF-Token':self.token(client)})
        return response,original

    def test_original_merchant_image_byte_preservation_invoice_and_restore(self):
        from unittest.mock import patch
        response,original=self.upload_merchant();self.assertEqual(response.status_code,201,response.json)
        url=response.json['url'];served=self.client.get(url);self.assertEqual(served.data,original);served.close()
        invoice=self.invoice(self.customer())
        html=self.client.get(invoice['invoice_url']).text
        self.assertIn(url,html);self.assertIn('Invoice verification QR',html)
        self.assertNotIn('svg?payment=1',html)
        with patch('app.qrcode.make') as qr:
            served=self.client.get(url);self.assertEqual(served.data,original);served.close();qr.assert_not_called()
        first=self.client.get('/api/merchant-qr/history').json[0]['id']
        newer,_=self.upload_merchant('red');self.assertEqual(newer.status_code,201)
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.api('/api/merchant-qr/'+str(first)+'/restore',{}).status_code,200)
        self.assertEqual(self.api('/api/merchant-qr',{},method='DELETE').status_code,200)
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.api('/api/merchant-qr/'+str(first)+'/restore',{}).status_code,200)
        served=self.client.get(url);self.assertEqual(served.data,original);served.close()

    def test_original_merchant_image_backup_and_validation_permissions(self):
        import zipfile
        response,original=self.upload_merchant();self.assertEqual(response.status_code,201)
        backup=self.client.get('/api/backup')
        with zipfile.ZipFile(io.BytesIO(backup.data)) as archive:
            self.assertEqual(archive.read('uploads/'+response.json['url'].rsplit('/',1)[1]),original)
        backup.close()
        invalid=self.client.post('/api/merchant-qr',data={'image':(io.BytesIO(b'<svg>bad</svg>'),'bad.png')},headers={'X-CSRF-Token':self.token()})
        self.assertEqual(invalid.status_code,400)
        self.assertEqual(self.client.get('/merchant-qr/../app.py').status_code,404)
        self.assertEqual(self.client.post('/api/merchant-qr',data={}).status_code,403)
        self.api('/api/users',{'username':'helper','password':'Valid-staff-password','role':'staff'})
        staff=self.app.test_client();self.login('helper','Valid-staff-password',staff)
        response,_=self.upload_merchant(client=staff);self.assertEqual(response.status_code,403)
        self.assertEqual(staff.get('/api/merchant-qr/history').status_code,403)


if __name__=='__main__':
    import unittest
    unittest.main()
