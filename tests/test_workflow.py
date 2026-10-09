import json
import uuid
from unittest.mock import patch
import qrcode
import test_orders
from qr_pay import crc16


class WorkflowTests(test_orders.OrderFeatureTests):
    def test_online_customer_created_once_and_confirmation_is_idempotent(self):
        client=self.public_client();before=self.totals()
        result=self.order(client,bw_pages='8',color_pages='2',quantity='2')
        self.assertEqual(result.status_code,201,result.json)
        cid=result.json['customer_id']
        self.assertTrue(cid)
        self.assertEqual(self.totals()['customers'],before['customers']+1)
        self.assertEqual(self.totals()['sales'],before['sales'])
        self.assertEqual(self.order(client,bw_pages='8',color_pages='2').json['customer_id'],cid)
        order=self.client.get('/api/orders').json[0]
        self.assertEqual(json.loads(order['options'])['minimum_quote'],7800)
        confirm=self.api('/api/orders/'+str(order['id'])+'/confirm',{'quote':'95','cost':'25','paid':'30','method':'bKash'})
        self.assertEqual(confirm.status_code,201,confirm.json)
        repeat=self.api('/api/orders/'+str(order['id'])+'/confirm',{'quote':'95','paid':'30'})
        self.assertEqual(repeat.status_code,200)
        self.assertEqual(repeat.json['invoice_url'],confirm.json['invoice_url'])
        t=self.totals()
        self.assertEqual(t['sales'],before['sales']+9500)
        self.assertEqual(t['gross_profit'],before['gross_profit']+7000)
        self.assertEqual(t['collected'],before['collected']+3000)
        self.assertEqual(t['customers'],before['customers']+1)
        self.assertEqual(self.client.get('/api/customers/'+cid+'/statement').json['customer']['due'],6500)

    def test_quoted_status_confirms_price_and_creates_invoice(self):
        client=self.public_client();self.order(client)
        oid=self.client.get('/api/orders').json[0]['id']
        response=self.api('/api/orders/'+str(oid),{'status':'Quoted','quote':'100'},method='PUT')
        self.assertEqual(response.status_code,201)
        self.assertTrue(response.json['invoice_url'])
        self.assertIsNotNone(self.client.get('/api/orders').json[0]['invoice_id'])

    def test_customer_statement_reminder_private_link_and_no_internal_notes(self):
        cid=self.customer();inv=self.invoice(cid)
        self.api('/api/transactions',{'customer_id':cid,'kind':'Payment','paid':'100','description':'Later payment','notes':'INTERNAL-NOTE-DO-NOT-SHARE','request_key':str(uuid.uuid4())})
        response=self.client.get('/api/reminder/'+cid)
        url=response.json['statement_url'];self.assertIn(url,response.json['message'])
        self.assertNotIn('/statement/'+cid,url)
        public=self.app.test_client();statement=public.get('/statement/'+url.rsplit('/',1)[1])
        self.assertEqual(statement.status_code,200)
        self.assertIn('Account statement',statement.text)
        self.assertIn('Later payment',statement.text)
        self.assertNotIn('INTERNAL-NOTE-DO-NOT-SHARE',statement.text)
        self.assertEqual(public.get('/statement/'+cid).status_code,404)

    def test_original_merchant_qr_shown_on_paid_invoice_with_verification_qr(self):
        payload='0002010102112611TESTACCOUNT5204599953030505802BD5908DigitXBD6005Dhaka6304'
        payload+=crc16(payload)
        self.assertEqual(self.api('/api/settings',{'merchant_qr':payload,'dynamic_qr_enabled':'0'},method='PUT').status_code,200)
        inv=self.invoice(self.customer(),paid='1000')
        html=self.client.get(inv['invoice_url']).text
        self.assertIn('Invoice verification QR',html)
        self.assertIn('Merchant payment QR',html)
        self.assertNotIn('Your original merchant QR',html)
        token=inv['invoice_url'].rsplit('/',1)[1]
        with patch('app.qrcode.make',wraps=qrcode.make) as make:
            self.assertEqual(self.client.get('/qr/invoice/'+token+'.svg?payment=1').status_code,200)
            self.assertEqual(make.call_args.args[0],payload)
        self.api('/api/settings',{'merchant_qr':payload,'dynamic_qr_enabled':'1'},method='PUT')
        with patch('app.qrcode.make',wraps=qrcode.make) as make:
            self.assertEqual(self.client.get('/qr/invoice/'+token+'.svg?payment=1&original=1').status_code,200)
            self.assertEqual(make.call_args.args[0],payload)

    def test_admin_edits_invoice_payment_and_refund_with_recalculated_totals(self):
        cid=self.customer();inv=self.invoice(cid);before=self.totals()
        data={'customer_id':cid,'kind':'Invoice','date':'2026-10-08','items':[{'description':'Corrected print job','quantity':'1','price':'1200','cost':'500'}],'paid':'600','method':'Cash'}
        self.assertEqual(self.api('/api/transactions/'+str(inv['id']),data,method='PUT').status_code,200)
        after=self.totals();self.assertEqual(after['sales'],before['sales']+20000);self.assertEqual(after['gross_profit'],before['gross_profit']+10000)
        self.assertEqual(self.client.get('/api/transactions/'+str(inv['id'])).json['token'],inv['invoice_url'].rsplit('/',1)[1])
        payment=self.api('/api/transactions',{'customer_id':cid,'kind':'Payment','paid':'300','related_id':inv['id'],'request_key':str(uuid.uuid4())}).json['id']
        self.assertEqual(self.api('/api/transactions/'+str(payment),{'customer_id':cid,'kind':'Payment','date':'2026-10-08','paid':'200','related_id':inv['id']},method='PUT').status_code,200)
        self.assertEqual(self.client.get('/api/customers/'+cid+'/statement').json['customer']['due'],40000)
        refund=self.api('/api/transactions',{'customer_id':cid,'kind':'Refund','related_id':inv['id'],'amount':'100','paid':'100','cost_reversal':'50','request_key':str(uuid.uuid4())}).json['id']
        self.assertEqual(self.api('/api/transactions/'+str(refund),{'customer_id':cid,'kind':'Refund','date':'2026-10-08','related_id':inv['id'],'amount':'80','paid':'80','cost_reversal':'40'},method='PUT').status_code,200)
        data['items'][0]['price']='50'
        self.assertEqual(self.api('/api/transactions/'+str(inv['id']),data,method='PUT').status_code,400)
        audit=self.client.get('/api/audit').json
        self.assertTrue(any(a['action']=='ledger.edit' and 'before' in a['detail'] for a in audit))

    def test_admin_can_edit_investments_without_expensing_capital(self):
        before=self.totals()
        data={'date':'2026-10-08','kind':'Investment','category':'Owner capital','amount':'500','method':'Cash','description':'Capital'}
        eid=self.api('/api/expenses',data).json['id']
        data['amount']='700'
        self.assertEqual(self.api('/api/expenses/'+str(eid),data,method='PUT').status_code,200)
        self.assertEqual(self.totals()['investment'],before['investment']+70000)
        self.assertEqual(self.totals()['net_profit'],before['net_profit'])
        data['kind']='Expense'
        self.assertEqual(self.api('/api/expenses/'+str(eid),data,method='PUT').status_code,200)
        self.assertEqual(self.totals()['investment'],before['investment'])
        self.assertEqual(self.totals()['net_profit'],before['net_profit']-70000)

    def test_admin_stock_edits_sync_cash_and_prevent_negative_history(self):
        before=self.totals()
        iid=self.api('/api/inventory',{'name':'A4 test','unit':'sheet','reorder':'10'}).json['id']
        self.api('/api/inventory/movement',{'item_id':iid,'kind':'Purchased','date':'2026-10-08','quantity':'100','unit_cost':'1'})
        move=self.client.get('/api/inventory').json['movements'][0]
        self.assertTrue(move['expense_id'])
        update={'item_id':iid,'kind':'Purchased','date':'2026-10-08','quantity':'120','unit_cost':'2'}
        self.assertEqual(self.api('/api/inventory/movement/'+str(move['id']),update,method='PUT').status_code,200)
        self.assertEqual(self.totals()['cash'],before['cash']-24000)
        self.assertEqual(self.client.get('/api/inventory').json['items'][0]['stock'],120)
        self.api('/api/inventory/movement',{'item_id':iid,'kind':'Used','date':'2026-10-08','quantity':'100'})
        update['quantity']='90'
        self.assertEqual(self.api('/api/inventory/movement/'+str(move['id']),update,method='PUT').status_code,400)
        self.assertEqual(self.client.get('/api/inventory').json['items'][0]['stock'],20)
        cash=self.client.get('/api/expenses').json[0]
        cash_data={**cash,'amount':'240','date':'2026-10-09'}
        self.assertEqual(self.api('/api/expenses/'+str(move['expense_id']),cash_data,method='PUT').status_code,400)
        self.assertEqual(self.api('/api/inventory/'+str(iid),{'name':'A4 renamed','unit':'sheet','reorder':'5','supplier':'Supplier'},method='PUT').status_code,200)
        self.assertEqual(self.totals()['net_profit'],before['net_profit'])

    def test_staff_cannot_modify_financial_stock_or_opening_records(self):
        self.api('/api/users',{'username':'stafftest','password':'A-valid-test-password','role':'staff'})
        staff=self.app.test_client();self.login('stafftest',client=staff)
        for path in ['/api/transactions/1','/api/expenses/1','/api/inventory/1','/api/inventory/movement/1','/api/services/1','/api/orders/1/details']:
            self.assertEqual(self.api(path,{},method='PUT',client=staff).status_code,403,path)

    def test_theme_and_mixed_order_controls_available(self):
        page=self.app.test_client().get('/online_order')
        self.assertIn('name="bw_pages"',page.text)
        self.assertIn('name="color_pages"',page.text)
        self.assertIn('/static/theme.js',page.text)
        response=self.client.get('/static/theme.js')
        self.assertIn('digitxbd-theme',response.text)
        response.close()
