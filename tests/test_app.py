import io
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from qr_pay import crc16, parse, with_amount


class DigitXBDTests(unittest.TestCase):
    def setUp(self):
        self.test_root = Path(__file__).resolve().parent / '.runs'
        self.test_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.test_root)
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-secret', 'SETUP_TOKEN': 'test-setup', 'DATA_DIR': self.temp.name, 'MIGRATE_TRACKER': True})
        self.client = self.app.test_client()
        self.client.get('/setup')
        self.assertEqual(self.post_form('/setup', {'setup_token': 'test-setup', 'username': 'owner', 'password': 'A-valid-test-password'}).status_code, 302)
        self.login()

    def tearDown(self):
        Path(self.temp.name).resolve().relative_to(self.test_root.resolve())
        self.temp.cleanup()

    def token(self, client=None):
        with (client or self.client).session_transaction() as session:
            return session['csrf']

    def post_form(self, path, data, client=None):
        client = client or self.client
        return client.post(path, data={**data, 'csrf': self.token(client)})

    def login(self, username='owner', password='A-valid-test-password', client=None):
        client = client or self.client
        client.get('/login')
        return self.post_form('/login', {'username': username, 'password': password}, client)

    def api(self, path, data=None, method='POST', client=None):
        client = client or self.client
        return client.open(path, method=method, json=data, headers={'X-CSRF-Token': self.token(client)})

    def totals(self):
        return self.client.get('/api/dashboard').json['totals']

    def customer(self, opening='0'):
        response = self.api('/api/customers', {'name': 'Test customer', 'phone': '01700000000', 'opening': opening, 'credit_limit': '0'})
        self.assertEqual(response.status_code, 201)
        return response.json['id']

    def invoice(self, cid, bill='1000', cost='400', paid='600'):
        result = self.api('/api/transactions', {'customer_id': cid, 'kind': 'Invoice', 'date': '2026-10-08', 'items': [{'description': 'Thesis printing', 'quantity': '1', 'price': bill, 'cost': cost}], 'paid': paid, 'request_key': str(uuid.uuid4())})
        self.assertEqual(result.status_code, 201, result.json)
        return result.json

    def test_new_install_is_empty(self):
        totals = self.totals()
        for field in ['customers', 'orders', 'sales', 'collected', 'receivables', 'expenses', 'gross_profit', 'net_profit', 'investment']:
            self.assertEqual(totals[field], 0, field)
        self.assertEqual(self.client.get('/api/transactions').json['total'], 0)

    def test_partial_and_old_dues_payment_do_not_change_profit(self):
        cid = self.customer()
        before = self.totals()
        invoice = self.invoice(cid)
        after = self.totals()
        self.assertEqual(after['sales']-before['sales'], 100000)
        self.assertEqual(after['cost']-before['cost'], 40000)
        self.assertEqual(after['gross_profit']-before['gross_profit'], 60000)
        self.assertEqual(after['collected']-before['collected'], 60000)
        self.assertEqual(self.client.get('/api/customers/'+cid+'/statement').json['customer']['due'], 40000)
        payment = self.api('/api/transactions', {'customer_id': cid, 'kind': 'Payment', 'paid': '400', 'date': '2026-10-09', 'related_id': invoice['id'], 'request_key': str(uuid.uuid4())})
        self.assertEqual(payment.status_code, 201)
        final = self.totals()
        self.assertEqual(final['sales'], after['sales'])
        self.assertEqual(final['gross_profit'], after['gross_profit'])
        self.assertEqual(final['collected']-after['collected'], 40000)
        self.assertEqual(self.client.get('/api/customers/'+cid+'/statement').json['customer']['due'], 0)
        self.assertIn('Settled', self.client.get(invoice['invoice_url']).text)

    def test_repeat_orders_and_running_statement(self):
        cid = self.customer('10')
        self.invoice(cid, '500', '200', '200')
        self.invoice(cid, '100', '25', '0')
        response = self.api('/api/transactions', {'customer_id': cid, 'kind': 'Payment', 'paid': '310', 'date': '2026-10-10', 'request_key': str(uuid.uuid4())})
        self.assertEqual(response.status_code, 201)
        statement = self.client.get('/api/customers/'+cid+'/statement').json
        self.assertEqual(statement['customer']['orders'], 2)
        self.assertEqual([t['balance'] for t in statement['history']], [31000, 41000, 10000])
        self.assertEqual(sum(statement['customer']['aging'].values()), 10000)

    def test_financial_request_is_idempotent(self):
        cid = self.customer()
        data = {'customer_id': cid, 'kind': 'Payment', 'paid': '5', 'request_key': 'same-request'}
        first = self.api('/api/transactions', data)
        before = self.totals()
        second = self.api('/api/transactions', data)
        self.assertEqual(first.json['id'], second.json['id'])
        self.assertEqual(before, self.totals())

    def test_investment_and_withdrawal_do_not_reduce_profit(self):
        before = self.totals()
        for kind, amount in [('Investment', '50000'), ('Owner Withdrawal', '5000')]:
            response = self.api('/api/expenses', {'kind': kind, 'amount': amount, 'category': 'Other', 'method': 'Cash'})
            self.assertEqual(response.status_code, 201)
        after = self.totals()
        self.assertEqual(after['net_profit'], before['net_profit'])
        self.assertEqual(after['cash']-before['cash'], 4500000)
        self.api('/api/expenses', {'kind': 'Expense', 'amount': '100', 'category': 'Electricity', 'method': 'Cash'})
        self.assertEqual(self.totals()['net_profit'], before['net_profit']-10000)

    def test_adjustment_changes_due_not_sales(self):
        cid = self.customer()
        before = self.totals()
        result = self.api('/api/transactions', {'customer_id': cid, 'kind': 'Adjustment', 'amount': '-15', 'description': 'Opening balance correction', 'request_key': str(uuid.uuid4())})
        self.assertEqual(result.status_code, 201)
        after = self.totals()
        self.assertEqual(after['sales'], before['sales'])
        self.assertEqual(after['net_profit'], before['net_profit'])
        self.assertEqual(after['net_due'], before['net_due']-1500)

    def test_refund_reverses_sales_cost_and_cash_separately(self):
        cid = self.customer()
        inv = self.invoice(cid)
        before = self.totals()
        result = self.api('/api/transactions', {'customer_id': cid, 'kind': 'Refund', 'related_id': inv['id'], 'amount': '200', 'paid': '100', 'cost_reversal': '50', 'description': 'Returned pages', 'request_key': str(uuid.uuid4())})
        self.assertEqual(result.status_code, 201)
        after = self.totals()
        self.assertEqual(after['sales'], before['sales']-20000)
        self.assertEqual(after['collected'], before['collected']-10000)
        self.assertEqual(after['gross_profit'], before['gross_profit']-15000)
        self.assertEqual(after['net_due'], before['net_due']-10000)
        self.assertEqual(self.api('/api/transactions/'+str(inv['id'])+'/cost', {'cost':'40'}, method='PUT').status_code, 400)
        result = self.api('/api/transactions', {'customer_id': cid, 'kind': 'Refund', 'related_id': inv['id'], 'amount': '900', 'request_key': str(uuid.uuid4())})
        self.assertEqual(result.status_code, 400)

    def test_stock_purchase_is_cash_not_operating_expense(self):
        before = self.totals()
        item = self.api('/api/inventory', {'name': 'A4 paper', 'unit': 'sheet', 'reorder': 50}).json['id']
        self.assertEqual(self.api('/api/inventory/movement', {'item_id': item, 'kind': 'Purchased', 'quantity': '100', 'unit_cost': '1', 'record_cash': True}).status_code, 201)
        self.assertEqual(self.totals()['cash'], before['cash']-10000)
        self.assertEqual(self.totals()['expenses'], before['expenses'])
        self.assertEqual(self.totals()['net_profit'], before['net_profit'])
        self.assertEqual(self.api('/api/inventory/movement', {'item_id': item, 'kind': 'Used', 'quantity': '101'}).status_code, 400)
        self.api('/api/inventory/movement', {'item_id': item, 'kind': 'Used', 'quantity': '30'})
        self.assertEqual(self.client.get('/api/inventory').json['items'][0]['stock'], 70)

    def test_missing_cost_correction_only_changes_profit(self):
        cid = self.customer()
        inv = self.invoice(cid, cost='')
        before = self.totals()
        result = self.api('/api/transactions/'+str(inv['id'])+'/cost', {'cost': '20'}, method='PUT')
        self.assertEqual(result.status_code, 200)
        after = self.totals()
        self.assertEqual(after['missing_cost'], 0)
        self.assertEqual(after['net_profit'], before['net_profit']-2000)
        self.assertEqual(after['sales'], before['sales'])
        self.assertEqual(after['cash'], before['cash'])

    def test_csrf_and_public_unauthorized_access(self):
        outsider = self.app.test_client()
        self.assertEqual(outsider.get('/api/customers').status_code, 401)
        self.assertEqual(self.client.post('/api/customers', json={'name': 'bad'}).status_code, 403)
        self.assertEqual(outsider.get('/api/backup').status_code, 401)
        self.assertEqual(outsider.get('/api/files/1').status_code, 401)

    def test_staff_permissions(self):
        self.api('/api/users', {'username': 'staff', 'password': 'A-staff-test-password', 'role': 'staff'})
        staff = self.app.test_client()
        self.login('staff', 'A-staff-test-password', staff)
        self.assertEqual(self.api('/api/settings', {'business_name': 'Changed'}, method='PUT', client=staff).status_code, 403)
        self.assertEqual(self.api('/api/expenses', {'kind': 'Investment', 'amount': '100'}, client=staff).status_code, 403)
        self.assertEqual(staff.get('/api/backup').status_code, 403)
        self.assertNotIn('merchant_qr', staff.get('/api/bootstrap').json['settings'])
        self.assertEqual(self.api('/api/customers', {'name': 'Staff customer'}, client=staff).status_code, 201)
        uid = self.client.get('/api/users').json[-1]['id']
        self.api('/api/users/'+str(uid), {'active': False}, method='PUT')
        self.assertEqual(staff.get('/api/customers').status_code, 401)

    def test_upload_tracking_and_billing_order(self):
        public = self.app.test_client()
        public.get('/online_order')
        result = self.post_form('/online_order', {'name': 'Test student', 'phone': '01700000000', 'service': 'Thesis Printing', 'details': 'Print pages 1–10', 'quantity': '2', 'consent': 'yes', 'files': (io.BytesIO(b'%PDF-1.7\nTest only'), '../../test.pdf')}, public)
        self.assertEqual(result.status_code, 201, result.json)
        self.assertIn('We’ve got your request.', public.get(result.json['tracking_url']).text)
        order = self.client.get('/api/orders').json[0]
        self.assertEqual(len(order['files']), 1)
        fid = order['files'][0]['id']
        self.assertEqual(public.get('/api/files/'+str(fid)).status_code, 401)
        download = self.client.get('/api/files/'+str(fid))
        self.assertIn('attachment', download.headers['Content-Disposition'])
        download.close()
        cid = order['customer_id']
        response = self.api('/api/transactions', {'customer_id': cid, 'kind': 'Invoice', 'order_id': order['id'], 'items': [{'description': 'Printing', 'quantity': '1', 'price': '100', 'cost': '30'}], 'request_key': str(uuid.uuid4())})
        self.assertEqual(response.status_code, 201)
        self.assertIsNotNone(self.client.get('/api/orders').json[0]['invoice_id'])

    def test_disallowed_upload_is_rejected_without_order(self):
        public = self.app.test_client()
        public.get('/online_order')
        result = self.post_form('/online_order', {'name': 'Test', 'phone': '01700000000', 'service': 'Other', 'details': 'Please print', 'quantity': '1', 'consent': 'yes', 'files': (io.BytesIO(b'bad'), 'bad.exe')}, public)
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.client.get('/api/orders').json, [])

    def test_qr_crc_amount_and_invoice_html(self):
        fields = [('00', '01'), ('01', '11'), ('26', '0004TEST'), ('52', '5999'), ('53', '050'), ('58', 'BD'), ('59', 'DigitXBD'), ('60', 'DHAKA')]
        base = ''.join(k+f'{len(v):02d}'+v for k,v in fields)+'6304'
        payload = base+crc16(base)
        dynamic = with_amount(payload, 12345)
        values = dict(parse(dynamic))
        self.assertEqual(values['54'], '123.45')
        self.assertEqual(values['01'], '12')
        with self.assertRaises(ValueError):
            parse(payload[:-4]+'0000')
        self.assertEqual(self.api('/api/settings', {'merchant_qr': payload, 'dynamic_qr_enabled': '1'}, method='PUT').status_code, 200)
        inv = self.invoice(self.customer())
        page = self.client.get(inv['invoice_url'])
        self.assertIn('Bangla QR', page.text)
        token = inv['invoice_url'].split('/')[-1]
        self.assertEqual(self.client.get('/qr/invoice/'+token+'.svg?payment=1').mimetype, 'image/svg+xml')
        self.assertEqual(self.client.get('/qr/order.svg').status_code, 200)

    def test_monthly_reconciliation_and_aging(self):
        cid = self.customer()
        self.invoice(cid, '1000', '400', '600')
        dashboard = self.client.get('/api/dashboard').json
        month = next(row for row in dashboard['monthly'] if row['month'] == '2026-10')
        self.assertEqual(month['sales'], 100000)
        self.assertEqual(month['collected'], 60000)
        self.assertEqual(month['net_profit'], 60000)
        self.assertEqual(sum(sum(row['aging'].values()) for row in dashboard['receivables']), 40000)

    def test_backup_and_export(self):
        self.customer()
        import zipfile
        backup = self.client.get('/api/backup')
        self.assertEqual(backup.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(backup.data)) as z:
            self.assertIn('digitxbd.sqlite', z.namelist())
        backup.close()
        response = self.client.get('/api/export/customers.csv')
        self.assertEqual(response.status_code, 200)
        self.assertIn('amounts-in-paisa', response.headers['Content-Disposition'])
        self.assertIn("8801700000000", response.data.decode('utf-8-sig'))

    def test_invalid_overpayment_rejected(self):
        cid = self.customer()
        result = self.api('/api/transactions', {'customer_id': cid, 'kind': 'Invoice', 'items': [{'description':'Print', 'quantity':'1', 'price':'100','cost':'10'}], 'paid':'101','request_key':str(uuid.uuid4())})
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.client.get('/api/customers/'+cid+'/statement').json['customer']['orders'], 0)

    def test_unlinked_payment_settles_old_invoices_and_preserves_credits(self):
        cid = self.customer()
        inv = self.invoice(cid, '100', '40', '0')
        result = self.api('/api/transactions', {'customer_id':cid,'kind':'Payment','paid':'150','date':'2026-10-09','request_key':str(uuid.uuid4())})
        self.assertEqual(result.status_code, 201)
        statement = self.client.get('/api/customers/'+cid+'/statement').json
        self.assertEqual(statement['customer']['due'], -5000)
        self.assertIn('Settled', self.client.get(inv['invoice_url']).text)

    def test_offline_backup_restore(self):
        cid = self.customer()
        self.invoice(cid, paid="0")
        import os
        import sqlite3
        import subprocess
        backup = self.client.get('/api/backup')
        archive = Path(self.temp.name)/'snapshot.zip'
        archive.write_bytes(backup.data)
        backup.close()
        restore_dir = Path(self.temp.name)/'restore-target'
        restore_dir.mkdir()
        script = Path(__file__).resolve().parents[1]/'restore_backup.py'
        result = subprocess.run([sys.executable,str(script),str(archive)],env={**os.environ,'DATA_DIR':str(restore_dir)},capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        with sqlite3.connect(restore_dir/'digitxbd.sqlite') as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM customers').fetchone()[0],1)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM ledger').fetchone()[0],1)
            self.assertEqual(connection.execute('PRAGMA quick_check').fetchone()[0],'ok')
        connection.close()

    def test_complete_missing_customer_dates_without_changing_balance(self):
        import sqlite3
        cid = self.customer('10')
        with sqlite3.connect(Path(self.temp.name)/'digitxbd.sqlite') as connection:
            connection.execute('UPDATE customers SET joined=NULL,opening_date=NULL WHERE id=?', (cid,))
        before = self.totals()
        customer = self.client.get('/api/customers/'+cid+'/statement').json['customer']
        response = self.api('/api/customers/'+cid, {'name': customer['name'], 'phone': customer['phone'], 'type': customer['type'], 'status': customer['status'], 'joined': '2026-10-01', 'opening_date': '2026-10-01', 'credit_limit': '0', 'department': 'Agriculture', 'alternate': '01800000000'}, method='PUT')
        self.assertEqual(response.status_code, 200, response.json)
        statement = self.client.get('/api/customers/'+cid+'/statement').json
        self.assertEqual(statement['customer']['due'], 1000)
        self.assertEqual(statement['customer']['department'], 'Agriculture')
        self.assertEqual(statement['customer']['oldest_due'], '2026-10-01')
        self.assertEqual(self.totals(), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)

