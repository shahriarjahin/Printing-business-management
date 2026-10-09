import csv
import base64
import xml.etree.ElementTree as ET
from record_admin import register as register_records, reserve_id
from print_queue import SCHEMA as PRINT_SCHEMA, register as register_printing, authenticate as authenticate_printer
import io
import json
import os
import re
import secrets
import sqlite3
import tempfile
import time
import zipfile
from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import qrcode
import qrcode.image.svg
from pypdf import PdfReader
from PIL import Image
from flask import Flask, Request, current_app, abort, g, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from qr_pay import parse as parse_qr, with_amount

ROOT = Path(__file__).resolve().parent


class DiskUploadRequest(Request):
    def _get_file_stream(self, total_content_length, content_type, filename=None, content_length=None):
        # Customer documents spool to the data volume, not Docker's small /tmp memory disk.
        return tempfile.TemporaryFile(mode='rb+', dir=Path(current_app.config['DATA_DIR']) / '.upload-tmp')
SERVICES = ['Assignment Printing', 'Thesis Printing', 'Research Paper', 'Notes/Sheet', 'Color Printing', 'Black & White Printing', 'Stamp Size Photo', 'Photo Printing', 'Document Printing', 'PDF/File Printing', 'Binding', 'Lamination', 'Other']
ORDER_PRICES = {'color': 5, 'bw': 3, 'stamp': 5, 'stamp_min': 8, 'binding': 10}


def file_pages(filename, content):
    """Unknown formats remain manual; never guess Word pagination."""
    extension = Path(filename).suffix.lower()
    source = io.BytesIO(content) if isinstance(content, (bytes, bytearray)) else content
    try:
        if extension == '.pdf':
            reader = PdfReader(source)
            if reader.is_encrypted:
                return None
            count = len(reader.pages)
            return count if 1 <= count <= 100000 else None
        if extension in ('.jpg', '.jpeg', '.png'):
            with Image.open(source) as image:
                image.verify()
            return 1
    except Exception:
        pass
    finally:
        if hasattr(source, 'seek') and not getattr(source, 'closed', False):
            source.seek(0)
    return None


def order_estimate(category, quantity, options):
    if options.get('bw_pages') is not None or options.get('color_pages') is not None:
        bw = int(options.get('bw_pages') or 0)
        color = int(options.get('color_pages') or 0)
        if not 0 <= bw <= 100000 or not 0 <= color <= 100000:
            raise ValueError('Page counts must be between 0 and 100,000.')
        options.update(bw_pages=bw, color_pages=color, pages=bw + color, color='Mixed' if bw and color else 'Color' if color else 'Black & White')
    pages = int(options.get('pages') or 1)
    if not 1 <= pages <= 100000 or pages * quantity > 1000000:
        raise ValueError('Enter a valid page count (maximum one million printed pages).')
    options['pages'] = pages
    binding = ORDER_PRICES['binding'] if options.get('binding') not in (None, '', 'None') else 0
    if category == 'Stamp Size Photo':
        if quantity < ORDER_PRICES['stamp_min']:
            raise ValueError('Stamp size photos require at least 8 pieces.')
        amount = quantity * ORDER_PRICES['stamp'] + binding
    elif category == 'Binding':
        amount = ORDER_PRICES['binding']
    elif category in ('Photo Printing', 'Lamination', 'Other'):
        return None
    else:
        color = options.get('color') or 'Black & White'
        if category == 'Color Printing':
            color = 'Color'
        elif category == 'Black & White Printing':
            color = 'Black & White'
        if options.get('bw_pages') is not None:
            if not options['bw_pages'] + options['color_pages']:
                raise ValueError('Enter at least one black-and-white or color page.')
            amount = quantity * (options['bw_pages'] * ORDER_PRICES['bw'] + options['color_pages'] * ORDER_PRICES['color']) + binding
            return amount * 100
        if color not in ('Black & White', 'Color'):
            return None
        options['color'] = color
        amount = pages * quantity * ORDER_PRICES['color' if color == 'Color' else 'bw'] + binding
    return amount * 100
METHODS = ['Cash', 'bKash', 'Nagad', 'Bank', 'Other']
ENTRY_TYPES = ['Expense', 'Investment', 'Owner Withdrawal', 'Stock Purchase']
ORDER_STATUSES = ['New', 'Quoted', 'In Progress', 'Ready', 'Delivered', 'Cancelled']
DEFAULT_SETTINGS = {'business_name': 'DigitXBD', 'owner_name': '', 'phone': '', 'address': '', 'payment_number': '', 'invoice_footer': 'ধন্যবাদ — DigitXBD-র সাথে থাকার জন্য। Thank you for choosing DigitXBD.', 'vip_spend': '5000', 'vip_orders': '20', 'credit_limit': '1000', 'credit_days': '7', 'opening_cash': '0', 'merchant_qr': '', 'dynamic_qr_enabled': '0', 'reminder_template': 'আসসালামু আলাইকুম {name}, DigitXBD-তে আপনার বকেয়া ৳{due}। সুবিধামতো পরিশোধ করার অনুরোধ রইল। ধন্যবাদ।', 'public_url': ''}
DEFAULT_SETTINGS.update(file_retention_days='30', file_retention_basis='completed')
DEFAULT_SETTINGS.update(merchant_qr_image='')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('owner','staff')), active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS merchant_qr_images(id INTEGER PRIMARY KEY AUTOINCREMENT,stored TEXT UNIQUE NOT NULL,name TEXT NOT NULL,created TEXT NOT NULL,actor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS customers(id TEXT PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '', alternate TEXT NOT NULL DEFAULT '', type TEXT NOT NULL DEFAULT 'Student', institution TEXT NOT NULL DEFAULT '', department TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'Active', joined TEXT, opening INTEGER NOT NULL DEFAULT 0, opening_date TEXT, credit_limit INTEGER, notes TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT UNIQUE NOT NULL, customer_id TEXT NOT NULL REFERENCES customers(id), date TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('Invoice','Payment','Adjustment','Refund')), number TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'Other', description TEXT NOT NULL DEFAULT '', bill INTEGER NOT NULL DEFAULT 0, cost INTEGER NOT NULL DEFAULT 0, cost_known INTEGER NOT NULL DEFAULT 1, paid INTEGER NOT NULL DEFAULT 0, method TEXT NOT NULL DEFAULT 'Cash', due_date TEXT, items TEXT NOT NULL DEFAULT '[]', related_id INTEGER REFERENCES ledger(id), actor TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', request_key TEXT UNIQUE, created TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_ledger_customer ON ledger(customer_id,date,id);
CREATE INDEX IF NOT EXISTS idx_ledger_date ON ledger(date);
CREATE TABLE IF NOT EXISTS expenses(id INTEGER PRIMARY KEY AUTOINCREMENT,date TEXT NOT NULL,kind TEXT NOT NULL,category TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',amount INTEGER NOT NULL CHECK(amount>=0),method TEXT NOT NULL,vendor TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',actor TEXT NOT NULL,created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS services(id INTEGER PRIMARY KEY,name TEXT NOT NULL,price INTEGER NOT NULL,cost INTEGER NOT NULL,unit TEXT NOT NULL DEFAULT 'page',active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS inventory(id INTEGER PRIMARY KEY,name TEXT NOT NULL,unit TEXT NOT NULL,supplier TEXT NOT NULL DEFAULT '',reorder REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS stock(id INTEGER PRIMARY KEY,item_id INTEGER NOT NULL REFERENCES inventory(id),date TEXT NOT NULL,kind TEXT NOT NULL,quantity REAL NOT NULL,unit_cost INTEGER NOT NULL DEFAULT 0,notes TEXT NOT NULL DEFAULT '',actor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT,token TEXT UNIQUE NOT NULL,name TEXT NOT NULL,phone TEXT NOT NULL,service TEXT NOT NULL,details TEXT NOT NULL,quantity INTEGER NOT NULL DEFAULT 1,options TEXT NOT NULL DEFAULT '{}',status TEXT NOT NULL DEFAULT 'New',quote INTEGER,customer_id TEXT REFERENCES customers(id),invoice_id INTEGER REFERENCES ledger(id),created TEXT NOT NULL,updated TEXT NOT NULL,staff_notes TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY,order_id INTEGER NOT NULL REFERENCES orders(id),name TEXT NOT NULL,stored TEXT UNIQUE NOT NULL,size INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS record_sequences(name TEXT PRIMARY KEY,value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS recycle_bin(id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,record_id TEXT NOT NULL,label TEXT NOT NULL,payload TEXT NOT NULL,reason TEXT NOT NULL,actor TEXT NOT NULL,created TEXT NOT NULL,restored_at TEXT);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,created TEXT NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,detail TEXT NOT NULL);
'''


def today():
    try:
        return datetime.now(ZoneInfo('Asia/Dhaka')).date().isoformat()
    except Exception:
        return (datetime.utcnow() + timedelta(hours=6)).date().isoformat()


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def cents(value, allow_negative=False):
    try:
        amount = Decimal(str(value or '0'))
        if not amount.is_finite() or abs(amount) > 100000000:
            raise ValueError('Amount is outside the supported range.')
        result = int((amount * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        if result < 0 and not allow_negative:
            raise ValueError('Amount cannot be negative.')
        return result
    except (InvalidOperation, TypeError):
        raise ValueError('Enter a valid amount.')


def valid_date(value, optional=False):
    if not value and optional:
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (ValueError, TypeError):
        raise ValueError('Enter a valid date.')


def text(value, limit=2000):
    return str(value or '').strip()[:limit]


def phone(value):
    digits = re.sub(r'\D', '', str(value or ''))
    if digits.startswith('01') and len(digits) == 11:
        digits = '88' + digits
    return digits


def db():
    if 'db' not in g:
        g.db = sqlite3.connect(Path(g.app_data) / 'digitxbd.sqlite', timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
        g.db.execute('PRAGMA busy_timeout=15000')
    return g.db


def rows(sql, params=()):
    return [dict(r) for r in db().execute(sql, params)]


def settings():
    return {r['key']: r['value'] for r in db().execute('SELECT * FROM settings')}


def validate_stock_history(iid):
    running=0
    for move in db().execute('SELECT kind,quantity FROM stock WHERE item_id=? ORDER BY date,id',(iid,)):
        running+=(-1 if move['kind']=='Used' else 1)*move['quantity']
        if running < -0.0000001:
            raise ValueError('This change would make historical stock negative. Correct the purchase/opening balance first.')


def actor():
    return session.get('username', 'public')


def audit(action, detail):
    db().execute('INSERT INTO audit(created,actor,action,detail) VALUES(?,?,?,?)', (timestamp(), actor(), action, json.dumps(detail, ensure_ascii=False)))


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        user = db().execute('SELECT * FROM users WHERE id=? AND active=1', (session.get('uid'),)).fetchone()
        if not user:
            if request.path.startswith('/api/'):
                return jsonify(error='Please sign in.'), 401
            return redirect('/login')
        g.user = dict(user)
        return fn(*args, **kwargs)
    return wrapped


def owner_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user['role'] != 'owner':
            abort(403)
        return fn(*args, **kwargs)
    return wrapped


def customer_totals():
    config = settings()
    result = rows('''SELECT c.*,COALESCE(l.billed,0) billed,COALESCE(l.paid,0) paid,COALESCE(l.cost,0) cost,COALESCE(l.orders,0) orders,l.last_order,COALESCE(l.missing_cost,0) missing_cost,c.opening+COALESCE(l.balance,0) due
      FROM customers c LEFT JOIN (SELECT customer_id,SUM(CASE WHEN kind IN ('Invoice','Refund') THEN bill ELSE 0 END) billed,SUM(paid) paid,SUM(CASE WHEN kind IN ('Invoice','Refund') THEN cost ELSE 0 END) cost,SUM(bill-paid) balance,SUM(kind='Invoice') orders,MAX(CASE WHEN kind='Invoice' THEN date END) last_order,SUM(kind='Invoice' AND cost_known=0) missing_cost FROM ledger GROUP BY customer_id) l ON c.id=l.customer_id ORDER BY CASE WHEN c.id GLOB 'C[0-9]*' THEN CAST(substr(c.id,2) AS INTEGER) END,c.id COLLATE NOCASE''')
    for c in result:
        c['profit'] = c['billed'] - c['cost']
        c['vip'] = c['billed'] >= cents(config['vip_spend']) or c['orders'] >= int(config['vip_orders']) or c['status'] == 'VIP'
        c['limit'] = c['credit_limit'] if c['credit_limit'] is not None else cents(config['credit_limit'])
        c['credit_status'] = 'Credit' if c['due'] < 0 else 'Over limit' if c['due'] > c['limit'] else 'Due' if c['due'] > 0 else 'Clear'
        c['inactive_days'] = (date.fromisoformat(today()) - date.fromisoformat(c['last_order'])).days if c['last_order'] else None
    return result


def statement_methods(history, customer):
    debts,_=outstanding_debts(customer)
    unpaid={d['invoice_id'] for d in debts if d['invoice_id']}
    for entry in history:
        if not entry['paid'] or (entry['kind']=='Invoice' and entry['id'] in unpaid):
            entry['method']=''


def outstanding_debts(customer):
    # Explicit invoice references take priority; otherwise account payments use
    # FIFO. These are calculated allocations, never rewrites of ledger entries.
    debts, credit = [], max(0, -customer['opening'])
    if customer['opening'] > 0:
        debts.append({'invoice_id': None, 'date': customer['opening_date'], 'amount': customer['opening']})
    def charge(amount, invoice_id, due):
        nonlocal credit
        used = min(credit, amount)
        credit -= used
        if amount > used:
            debts.append({'invoice_id': invoice_id, 'date': due, 'amount': amount-used})
    def settle(amount, invoice_id=None):
        nonlocal credit
        ordered = [d for d in debts if invoice_id and d['invoice_id'] == invoice_id] + [d for d in debts if not invoice_id or d['invoice_id'] != invoice_id]
        for debt in ordered:
            used = min(amount, debt['amount'])
            debt['amount'] -= used
            amount -= used
            if not amount:
                break
        credit += amount
    term = int(settings()['credit_days'])
    for r in db().execute('SELECT * FROM ledger WHERE customer_id=? ORDER BY date,id', (customer['id'],)):
        due = r['due_date'] or (date.fromisoformat(r['date']) + timedelta(days=term)).isoformat()
        if r['kind'] == 'Invoice':
            charge(r['bill'], r['id'], due)
            settle(r['paid'], r['id'])
        elif r['kind'] == 'Payment':
            settle(r['paid'], r['related_id'])
        else:
            change = r['bill'] - r['paid']
            if change > 0:
                charge(change, None, due)
            elif change < 0:
                settle(-change, r['related_id'])
    return [d for d in debts if d['amount'] > 0], credit


def aging(customer):
    debts, credit = outstanding_debts(customer)
    bands = defaultdict(int)
    for debt in debts:
        due, amount = debt['date'], debt['amount']
        days = (date.fromisoformat(today()) - date.fromisoformat(due)).days if due else None
        band = 'Date needed' if days is None else 'Current' if days <= 0 else '1–7 days' if days <= 7 else '8–30 days' if days <= 30 else '31–60 days' if days <= 60 else '61–90 days' if days <= 90 else '90+ days'
        bands[band] += amount
    customer['aging'] = dict(bands)
    known_dates = sorted(d['date'] for d in debts if d['date'])
    unknown = any(d['date'] is None for d in debts)
    customer['oldest_due'] = None if unknown else known_dates[0] if known_dates else None
    customer['days_overdue'] = max(0, (date.fromisoformat(today()) - date.fromisoformat(customer['oldest_due'])).days) if customer['oldest_due'] else None
    return customer


def dashboard():
    customers = customer_totals()
    totals = dict(db().execute("SELECT COALESCE(SUM(CASE WHEN kind IN ('Invoice','Refund') THEN bill ELSE 0 END),0) sales,COALESCE(SUM(paid),0) collected,COALESCE(SUM(CASE WHEN kind IN ('Invoice','Refund') THEN cost ELSE 0 END),0) cost,COALESCE(SUM(kind='Invoice'),0) orders,COALESCE(SUM(kind='Invoice' AND cost_known=0),0) missing_cost FROM ledger").fetchone())
    exp = {r['kind']: r['amount'] for r in db().execute('SELECT kind,SUM(amount) amount FROM expenses GROUP BY kind')}
    totals.update(expenses=exp.get('Expense', 0), investment=exp.get('Investment', 0), withdrawal=exp.get('Owner Withdrawal', 0), stock_purchase=exp.get('Stock Purchase', 0))
    totals.update(receivables=sum(max(c['due'], 0) for c in customers), credits=sum(max(-c['due'], 0) for c in customers), net_due=sum(c['due'] for c in customers), customers=len(customers), active=sum(c['status'] != 'Inactive' for c in customers), vip=sum(c['vip'] for c in customers), owing=sum(c['due'] > 0 for c in customers), repeat=sum(c['orders'] > 1 for c in customers), over_limit=sum(c['due'] > c['limit'] for c in customers))
    totals['gross_profit'] = totals['sales'] - totals['cost']
    totals['net_profit'] = totals['gross_profit'] - totals['expenses']
    totals['cash'] = cents(settings()['opening_cash'], True) + totals['collected'] + totals['investment'] - totals['expenses'] - totals['withdrawal'] - totals['stock_purchase']
    totals['capital'] = totals['investment'] - totals['withdrawal'] + totals['net_profit']
    monthly = defaultdict(lambda: dict(sales=0, collected=0, cost=0, orders=0, expenses=0, investment=0, withdrawal=0, stock_purchase=0))
    for r in db().execute("SELECT substr(date,1,7) month,SUM(CASE WHEN kind IN ('Invoice','Refund') THEN bill ELSE 0 END) sales,SUM(paid) collected,SUM(CASE WHEN kind IN ('Invoice','Refund') THEN cost ELSE 0 END) cost,SUM(kind='Invoice') orders FROM ledger GROUP BY month"):
        monthly[r['month']].update({key: r[key] for key in ('sales', 'collected', 'cost', 'orders')})
    for r in db().execute('SELECT substr(date,1,7) month,kind,SUM(amount) amount FROM expenses GROUP BY month,kind'):
        key = {'Expense': 'expenses', 'Investment': 'investment', 'Owner Withdrawal': 'withdrawal', 'Stock Purchase': 'stock_purchase'}[r['kind']]
        monthly[r['month']][key] = r['amount']
    # Always show the last 12 calendar months, and retain every historical month.
    now = date.fromisoformat(today())
    for offset in range(12):
        serial = now.year * 12 + now.month - 1 - offset
        monthly[f'{serial // 12:04d}-{serial % 12 + 1:02d}']
    performance = []
    for month, values in sorted(monthly.items()):
        values.update(month=month, gross_profit=values['sales'] - values['cost'], net_profit=values['sales'] - values['cost'] - values['expenses'], due_change=values['sales'] - values['collected'])
        values['net_cash'] = values['collected'] + values['investment'] - values['expenses'] - values['withdrawal'] - values['stock_purchase']
        # Adjustments affect due movements but never sales.
        adjustment = db().execute("SELECT COALESCE(SUM(bill),0) FROM ledger WHERE kind='Adjustment' AND substr(date,1,7)=?", (month,)).fetchone()[0]
        values['due_change'] += adjustment
        performance.append(values)
    for c in customers:
        if c['due'] > 0:
            aging(c)
    return {'totals': totals, 'monthly': performance, 'receivables': sorted([c for c in customers if c['due'] > 0], key=lambda c: -c['due']), 'top_customers': sorted(customers, key=lambda c: -c['billed'])[:8], 'new_orders': db().execute("SELECT COUNT(*) FROM orders WHERE status='New' AND source='online'").fetchone()[0]}


def ledger_insert(data, key=None):
    token = secrets.token_urlsafe(24)
    customer = db().execute('SELECT id FROM customers WHERE id=?', (data['customer_id'],)).fetchone()
    if not customer:
        raise ValueError('Select an existing customer.')
    cur = db().execute('''INSERT INTO ledger(token,customer_id,date,kind,number,category,description,bill,cost,cost_known,paid,method,due_date,items,related_id,actor,notes,request_key,created)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (token, data['customer_id'], valid_date(data.get('date', today())), data['kind'], text(data.get('number'), 100), text(data.get('category', 'Other'), 100), text(data.get('description')), data.get('bill', 0), data.get('cost', 0), data.get('cost_known', 1), data.get('paid', 0), data.get('method', 'Cash'), valid_date(data.get('due_date'), True), json.dumps(data.get('items', []), ensure_ascii=False), data.get('related_id'), actor(), text(data.get('notes')), key, timestamp()))
    if data['kind'] == 'Invoice' and not data.get('number'):
        db().execute('UPDATE ledger SET number=? WHERE id=?', (f'DX-{date.fromisoformat(data.get("date", today())).year}-{cur.lastrowid:06d}', cur.lastrowid))
    return cur.lastrowid


def create_customer(data):
    name = text(data.get('name'), 120)
    if not name:
        raise ValueError('Customer name is required.')
    normalized = phone(data.get('phone'))
    if normalized and any(phone(row['phone']) == normalized for row in rows('SELECT phone FROM customers')):
        raise ValueError('This phone number already belongs to a customer. Select the existing customer ID instead.')
    last = db().execute("SELECT COALESCE(MAX(CAST(substr(id,2) AS INTEGER)),0) FROM customers WHERE id GLOB 'C[0-9]*'").fetchone()[0]
    saved=db().execute("SELECT value FROM record_sequences WHERE name='customer_id'").fetchone()
    last=max(last,int(saved[0]) if saved else 0)
    cid = f'C{last + 1:04d}'
    db().execute("INSERT INTO record_sequences(name,value) VALUES('customer_id',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",(last+1,))
    limit = cents(data['credit_limit']) if data.get('credit_limit') not in (None, '') else None
    opening = cents(data.get('opening'), True)
    db().execute('INSERT INTO customers(id,name,phone,alternate,type,institution,department,status,joined,opening,opening_date,credit_limit,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (cid, name, normalized, text(data.get('alternate'), 40), text(data.get('type', 'Student'), 40), text(data.get('institution'), 160), text(data.get('department'), 100), text(data.get('status', 'Active'), 30), valid_date(data.get('joined', today()), True), opening, valid_date(data.get('opening_date'), True), limit, text(data.get('notes'))))
    db().execute('UPDATE customers SET statement_token=? WHERE id=?', (secrets.token_urlsafe(32), cid))
    audit('customer.create', {'id': cid})
    return cid


def seed_tracker():
    if db().execute('SELECT COUNT(*) FROM customers').fetchone()[0] or not (ROOT / 'seed.json').exists():
        return
    seed = json.loads((ROOT / 'seed.json').read_text(encoding='utf-8'))
    for c in seed['customers']:
        db().execute('INSERT INTO customers(id,name,phone,alternate,type,institution,department,status,joined,opening,opening_date,credit_limit,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', tuple(c[k] for k in ['id', 'name', 'phone', 'alternate', 'type', 'institution', 'department', 'status', 'joined', 'opening', 'opening_date', 'credit_limit', 'notes']))
    for t in seed['transactions']:
        ledger_insert(t, 'import-' + t['source_id'])
    for e in seed['expenses']:
        db().execute('INSERT INTO expenses(date,kind,category,description,amount,method,vendor,notes,actor,created) VALUES(?,?,?,?,?,?,?,?,?,?)', (e['date'], e['kind'], e['category'], e['description'], e['amount'], e['method'], e['vendor'], e['notes'], 'tracker-import', timestamp()))
    for c in seed['customers']:
        db().execute('UPDATE customers SET statement_token=? WHERE id=? AND statement_token IS NULL', (secrets.token_urlsafe(32), c['id']))
    audit('tracker.import', {'customers': len(seed['customers']), 'transactions': len(seed['transactions']), 'expenses': len(seed['expenses'])})



def validated_entry(data, editing_id=None):
    kind = data.get('kind', 'Invoice')
    if kind not in ('Invoice', 'Payment', 'Adjustment', 'Refund'):
        raise ValueError('Invalid transaction type.')
    if kind in ('Adjustment', 'Refund') and g.user['role'] != 'owner':
        abort(403)
    if data.get('method', 'Cash') not in METHODS:
        raise ValueError('Invalid payment method.')
    entry = {**data, 'kind': kind, 'bill': 0, 'cost': 0, 'cost_known': 1, 'paid': 0}
    if kind == 'Invoice':
        items = data.get('items', [])
        if not isinstance(items, list) or not 1 <= len(items) <= 50:
            raise ValueError('Add between 1 and 50 invoice items.')
        clean = []
        for item in items:
            try:
                qty = Decimal(str(item.get('quantity', 1)))
                if not qty.is_finite() or not 0 < qty <= 1000000:
                    raise ValueError('Quantity must be positive and no more than 1,000,000.')
            except InvalidOperation:
                raise ValueError('Invalid quantity.')
            title = text(item.get('description'), 180)
            if not title:
                raise ValueError('Each item needs a description.')
            price = cents(item.get('price'))
            cost_value = item.get('cost')
            known = cost_value not in (None, '')
            cost = cents(cost_value) if known else 0
            amount = int((qty * price).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            material = int((qty * cost).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            clean.append({'description': title, 'quantity': str(qty), 'price': price, 'cost': cost, 'amount': amount, 'cost_amount': material, 'cost_known': known})
            entry['bill'] += amount
            entry['cost'] += material
            entry['cost_known'] &= known
        if not 0 < entry['bill'] <= 10000000000:
            raise ValueError('Invoice total must be positive and no greater than ৳100,000,000.')
        entry['items'] = clean
        entry['paid'] = cents(data.get('paid'))
        if entry['paid'] > entry['bill']:
            raise ValueError('Invoice payment exceeds this invoice. Record extra money as a separate customer payment.')
        entry['description'] = '; '.join(x['description'] for x in clean)
        entry['due_date'] = data.get('due_date') or (date.fromisoformat(valid_date(data.get('date', today()))) + timedelta(days=int(settings()['credit_days']))).isoformat()
    elif kind == 'Payment':
        entry['paid'] = cents(data.get('paid'))
        if entry['paid'] <= 0:
            raise ValueError('Payment must be positive.')
    elif kind == 'Adjustment':
        entry['bill'] = cents(data.get('amount'), True)
        if entry['bill'] == 0 or not text(data.get('description')):
            raise ValueError('Enter a nonzero adjustment and a reason. Positive increases due; negative reduces due.')
    else:
        related = db().execute("SELECT * FROM ledger WHERE id=? AND kind='Invoice' AND customer_id=?", (data.get('related_id'), data.get('customer_id'))).fetchone()
        if not related:
            raise ValueError('A refund must reference an invoice for this customer.')
        refund = cents(data.get('amount'))
        previous = db().execute("SELECT COALESCE(SUM(-bill),0),COALESCE(SUM(-cost),0) FROM ledger WHERE related_id=? AND kind='Refund' AND id<>?", (related['id'], editing_id or 0)).fetchone()
        if refund <= 0 or refund + previous[0] > related['bill']:
            raise ValueError('Refund exceeds the remaining invoice value.')
        cost_reversal = cents(data.get('cost_reversal'))
        if previous[1] + cost_reversal > related['cost']:
            raise ValueError('Cost reversal exceeds recorded invoice cost.')
        payout = cents(data.get('paid'))
        if payout > refund:
            raise ValueError('Cash refund cannot exceed this refund value.')
        entry.update(bill=-refund, paid=-payout, cost=-cost_reversal, related_id=related['id'])
    if kind == 'Payment' and data.get('related_id'):
        related = db().execute("SELECT * FROM ledger WHERE id=? AND kind='Invoice' AND customer_id=?", (data['related_id'], data['customer_id'])).fetchone()
        if not related:
            raise ValueError('Payment invoice does not belong to this customer.')
    return entry

def create_app(test_config=None):
    app = Flask(__name__)
    app.request_class = DiskUploadRequest
    app.config.update(SECRET_KEY=os.environ.get('SECRET_KEY'), SETUP_TOKEN=os.environ.get('SETUP_TOKEN'), DATA_DIR=os.environ.get('DATA_DIR', str(ROOT / 'data')), MIGRATE_TRACKER=os.environ.get('MIGRATE_TRACKER', '0') == '1', MAX_CONTENT_LENGTH=None, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE', '0') == '1', PERMANENT_SESSION_LIFETIME=timedelta(hours=12), PUBLIC_URL=os.environ.get('PUBLIC_URL', 'http://localhost:8080'))
    if test_config:
        app.config.update(test_config)
    if not app.config['SECRET_KEY'] or not app.config['SETUP_TOKEN']:
        raise RuntimeError('SECRET_KEY and SETUP_TOKEN are required. Run configure.py and use Docker Compose, or set these environment variables.')
    data_dir = Path(app.config['DATA_DIR'])
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / 'uploads').mkdir(exist_ok=True)
    (data_dir / '.upload-tmp').mkdir(exist_ok=True)
    con = sqlite3.connect(data_dir / 'digitxbd.sqlite')
    con.execute('PRAGMA journal_mode=WAL')
    con.executescript(SCHEMA)
    con.executescript(PRINT_SCHEMA)
    if 'source' not in {r[1] for r in con.execute('PRAGMA table_info(orders)')}:
        con.execute("ALTER TABLE orders ADD COLUMN source TEXT NOT NULL DEFAULT 'online'")
    for table, column in [('files', 'deleted_at'), ('orders', 'completed_at'), ('customers', 'statement_token')]:
        if column not in {row[1] for row in con.execute('PRAGMA table_info(' + table + ')')}:
            con.execute('ALTER TABLE ' + table + ' ADD COLUMN ' + column + ' TEXT')
    if 'expense_id' not in {r[1] for r in con.execute('PRAGMA table_info(stock)')}:
        con.execute('ALTER TABLE stock ADD COLUMN expense_id INTEGER REFERENCES expenses(id)')
    for row in con.execute('SELECT id FROM customers WHERE statement_token IS NULL').fetchall():
        con.execute('UPDATE customers SET statement_token=? WHERE id=?', (secrets.token_urlsafe(32), row[0]))
    con.execute("UPDATE orders SET completed_at=updated WHERE status IN ('Delivered','Cancelled') AND completed_at IS NULL")
    con.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_statement_token ON customers(statement_token)')
    # Link older cash-recorded purchases only where the match is unambiguous.
    for mid,day,qty,unit_cost,operator,name in con.execute("SELECT s.id,s.date,s.quantity,s.unit_cost,s.actor,i.name FROM stock s JOIN inventory i ON i.id=s.item_id WHERE s.kind='Purchased' AND s.expense_id IS NULL").fetchall():
        amount=int((Decimal(str(qty))*unit_cost).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        candidates=con.execute("SELECT e.id FROM expenses e WHERE e.kind='Stock Purchase' AND e.date=? AND e.amount=? AND e.actor=? AND e.description=? AND e.notes='Inventory purchase; not an operating expense. Record consumed cost on invoices.' AND NOT EXISTS(SELECT 1 FROM stock s WHERE s.expense_id=e.id)",(day,amount,operator,name+' stock purchase')).fetchall()
        if len(candidates)==1:
            con.execute('UPDATE stock SET expense_id=? WHERE id=?',(candidates[0][0],mid))
    for key, value in DEFAULT_SETTINGS.items():
        con.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)', (key, value))
    for table in ('users','services','inventory','stock','files'):
        con.execute('INSERT INTO record_sequences(name,value) SELECT ?,COALESCE(MAX(id),0) FROM '+table+' WHERE 1 ON CONFLICT(name) DO UPDATE SET value=MAX(value,excluded.value)',(table,))
    con.execute("INSERT INTO record_sequences(name,value) SELECT 'customer_id',COALESCE(MAX(CAST(substr(id,2) AS INTEGER)),0) FROM customers WHERE id GLOB 'C[0-9]*' ON CONFLICT(name) DO UPDATE SET value=MAX(value,excluded.value)")
    con.commit()
    con.close()
    attempts = defaultdict(deque)

    def cleanup_files():
        config = settings()
        days = int(config['file_retention_days'])
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec='seconds').replace('+00:00', 'Z')
        source = 'o.created' if config['file_retention_basis'] == 'upload' else "CASE WHEN o.source='shop' THEN o.created ELSE o.completed_at END"
        expired = rows('SELECT f.* FROM files f JOIN orders o ON o.id=f.order_id WHERE f.deleted_at IS NULL AND ' + source + ' IS NOT NULL AND ' + source + '<?', (cutoff,))
        with db():
            for record in expired:
                path = (data_dir / 'uploads' / record['stored']).resolve()
                path.relative_to((data_dir / 'uploads').resolve())
                path.unlink(missing_ok=True)
                db().execute('UPDATE files SET deleted_at=? WHERE id=?', (timestamp(), record['id']))
            for archived in rows('SELECT id,payload,created FROM recycle_bin WHERE restored_at IS NULL'):
                payload=json.loads(archived['payload'])
                changed=False
                for record in payload['rows'].get('files',[]):
                    if record.get('deleted_at'):
                        continue
                    order=next((o for o in payload['rows'].get('orders',[]) if o['id']==record['order_id']),None)
                    if not order:
                        found=db().execute('SELECT * FROM orders WHERE id=?',(record['order_id'],)).fetchone()
                        order=dict(found) if found else {}
                    basis=order.get('created') if config['file_retention_basis']=='upload' or order.get('source')=='shop' else order.get('completed_at')
                    # Trashed files expire after deletion even if the job never completed.
                    expiry_start=min(v for v in (basis,archived['created']) if v)
                    if expiry_start < cutoff:
                        path=(data_dir/'uploads'/record['stored']).resolve()
                        path.relative_to((data_dir/'uploads').resolve())
                        path.unlink(missing_ok=True)
                        record['deleted_at']=timestamp();changed=True
                if changed:
                    db().execute('UPDATE recycle_bin SET payload=? WHERE id=?',(json.dumps(payload,ensure_ascii=False),archived['id']))
        return len(expired)

    app.extensions['cleanup_files'] = cleanup_files

    @app.before_request
    def before():
        g.app_data = app.config['DATA_DIR']
        if request.path.startswith('/api/print-agent/'):
            authenticate_printer(globals())
            return
        session.setdefault('csrf', secrets.token_urlsafe(24))
        if request.method in ('POST', 'PUT', 'DELETE'):
            token = request.headers.get('X-CSRF-Token') or request.form.get('csrf')
            if not token or not secrets.compare_digest(str(token), session['csrf']):
                return jsonify(error='Your form expired. Refresh the page and try again.'), 403

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if not request.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.teardown_appcontext
    def close(exc):
        conn = g.pop('db', None)
        if conn:
            conn.close()

    @app.errorhandler(ValueError)
    def invalid(exc):
        return jsonify(error=str(exc)), 400

    @app.errorhandler(413)
    def too_large(exc):
        return jsonify(error='This upload was rejected by the server. Try a smaller upload or contact the shop.'), 413

    @app.errorhandler(sqlite3.IntegrityError)
    def integrity(exc):
        return jsonify(error='This record conflicts with an existing entry. Refresh and try again.'), 409

    @app.get('/health')
    def health():
        db().execute('SELECT 1')
        return jsonify(status='ok', business='DigitXBD')

    @app.route('/setup', methods=['GET', 'POST'])
    def setup():
        if db().execute('SELECT COUNT(*) FROM users').fetchone()[0]:
            return redirect('/login')
        error = None
        if request.method == 'POST':
            if not secrets.compare_digest(request.form.get('setup_token', ''), app.config['SETUP_TOKEN']):
                error = 'Setup token does not match the SETUP_TOKEN in your .env file.'
            elif len(request.form.get('password', '')) < 12 or not re.fullmatch(r'[A-Za-z0-9_.-]{3,40}', request.form.get('username', '')):
                error = 'Use a 3–40 character username and a password of at least 12 characters.'
            else:
                with db():
                    db().execute('INSERT INTO users(id,username,password,role) VALUES(?,?,?,?)', (reserve_id(db(),'users'), request.form['username'], generate_password_hash(request.form['password']), 'owner'))
                    if app.config['MIGRATE_TRACKER']:
                        seed_tracker()
                return redirect('/login')
        return render_template('auth.html', setup=True, error=error, csrf=session['csrf'])

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if not db().execute('SELECT COUNT(*) FROM users').fetchone()[0]:
            return redirect('/setup')
        error = None
        if request.method == 'POST':
            key = request.remote_addr
            now = time.monotonic()
            while attempts[key] and now - attempts[key][0] > 900:
                attempts[key].popleft()
            if len(attempts[key]) >= 10:
                return render_template('auth.html', error='Too many attempts. Try again in 15 minutes.', csrf=session['csrf']), 429
            user = db().execute('SELECT * FROM users WHERE username=? AND active=1', (request.form.get('username', ''),)).fetchone()
            if user and check_password_hash(user['password'], request.form.get('password', '')):
                session.clear()
                session.update(uid=user['id'], username=user['username'], csrf=secrets.token_urlsafe(24))
                session.permanent = True
                attempts.pop(key, None)
                return redirect('/')
            attempts[key].append(now)
            error = 'Username or password is incorrect.'
        return render_template('auth.html', error=error, csrf=session['csrf'])

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect('/login')

    @app.get('/')
    @login_required
    def index():
        return render_template('app.html', csrf=session['csrf'], username=g.user['username'], role=g.user['role'])

    @app.get('/api/bootstrap')
    @login_required
    def bootstrap():
        config = settings()
        public_url = (config['public_url'] or app.config['PUBLIC_URL']).rstrip('/')
        return jsonify(customers=customer_totals(), dashboard=dashboard(), services=rows('SELECT * FROM services WHERE active=1 ORDER BY name'), settings=config if g.user['role'] == 'owner' else {k: config[k] for k in ('business_name', 'phone', 'address', 'payment_number', 'credit_days')}, today=today(), methods=METHODS, categories=SERVICES, role=g.user['role'], order_url=public_url + '/online_order', upload_url=public_url + '/order', csrf=session['csrf'])

    @app.get('/api/dashboard')
    @login_required
    def dashboard_api():
        return jsonify(dashboard())

    @app.get('/api/customers')
    @login_required
    def customers_api():
        return jsonify(customer_totals())

    @app.post('/api/customers')
    @login_required
    def customers_add():
        data = request.get_json() or {}
        if cents(data.get('opening'), True) and g.user['role'] != 'owner':
            abort(403)
        with db():
            cid = create_customer(data)
        return jsonify(id=cid), 201

    @app.put('/api/customers/<cid>')
    @owner_required
    def customers_edit(cid):
        previous = db().execute('SELECT * FROM customers WHERE id=?', (cid,)).fetchone()
        if not previous:
            abort(404)
        data = request.get_json() or {}
        if not text(data.get('name')):
            raise ValueError('Name is required.')
        normalized = phone(data.get('phone', previous['phone']))
        if normalized != phone(previous['phone']) and normalized and any(phone(c['phone']) == normalized for c in rows('SELECT phone FROM customers WHERE id<>?', (cid,))):
            raise ValueError('This phone number already belongs to another customer.')
        data['phone'] = normalized
        limit = None if data.get('credit_limit') in ('', None) else cents(data['credit_limit'])
        with db():
            db().execute('UPDATE customers SET name=?,phone=?,type=?,institution=?,status=?,joined=?,credit_limit=?,notes=?,alternate=?,department=?,opening_date=? WHERE id=?', (text(data['name'], 120), text(data.get('phone'), 40), text(data.get('type', 'Student'), 40), text(data.get('institution'), 160), text(data.get('status', 'Active'), 30), valid_date(data.get('joined'), True), limit, text(data.get('notes')), text(data.get('alternate', previous['alternate']), 40), text(data.get('department', previous['department']), 100), valid_date(data.get('opening_date', previous['opening_date']), True), cid))
            if 'opening' in data:
                db().execute('UPDATE customers SET opening=? WHERE id=?', (cents(data['opening'], True), cid))
            audit('customer.edit', {'id': cid, 'before': dict(previous), 'after': data})
        return jsonify(ok=True)

    @app.get('/api/customers/<cid>/statement')
    @login_required
    def statement_api(cid):
        customer = next((c for c in customer_totals() if c['id'] == cid), None)
        if not customer:
            abort(404)
        history = rows('SELECT * FROM ledger WHERE customer_id=? ORDER BY date,id', (cid,))
        statement_methods(history,customer)
        balance = customer['opening']
        for entry in history:
            balance += entry['bill'] - entry['paid']
            entry['balance'] = balance
        return jsonify(customer=aging(customer), history=history)

    @app.get('/api/transactions')
    @login_required
    def transactions_api():
        query = text(request.args.get('q'), 120)
        kind = request.args.get('kind', '')
        page = max(1, min(100000, int(request.args.get('page', 1))))
        where, params = ['1=1'], []
        if query:
            where.append('(c.name LIKE ? OR l.number LIKE ? OR l.description LIKE ? OR c.id LIKE ?)')
            params += ['%' + query + '%'] * 4
        if kind in ('Invoice', 'Payment', 'Adjustment', 'Refund'):
            where.append('l.kind=?')
            params.append(kind)
        sql = ' FROM ledger l JOIN customers c ON c.id=l.customer_id WHERE ' + ' AND '.join(where)
        total = db().execute('SELECT COUNT(*)' + sql, params).fetchone()[0]
        entries=rows("SELECT l.*,c.name customer_name,c.opening+COALESCE((SELECT SUM(h.bill-h.paid) FROM ledger h WHERE h.customer_id=l.customer_id AND (h.date<l.date OR (h.date=l.date AND h.id<=l.id))),0) balance" + sql + ' ORDER BY l.date DESC,l.id DESC LIMIT 100 OFFSET ?', params + [(page - 1) * 100])
        remaining={}
        for cid in {r['customer_id'] for r in entries if r['kind']=='Invoice'}:
            customer=dict(db().execute('SELECT * FROM customers WHERE id=?',(cid,)).fetchone())
            debts,_=outstanding_debts(customer)
            remaining.update({d['invoice_id']:d['amount'] for d in debts if d['invoice_id']})
        for entry in entries:
            entry['remaining']=remaining.get(entry['id'],0) if entry['kind']=='Invoice' else None
        return jsonify(total=total,page=page,rows=entries)

    @app.post('/api/transactions')
    @login_required
    def transactions_add():
        data = request.get_json() or {}
        key = text(data.get('request_key'), 100)
        if not key:
            raise ValueError('Request key missing. Refresh this page.')
        existing = db().execute('SELECT id,token FROM ledger WHERE request_key=?', (key,)).fetchone()
        if existing:
            return jsonify(id=existing['id'], invoice_url='/invoice/' + existing['token'])
        entry = validated_entry(data)
        kind = entry['kind']
        with db():
            tid = ledger_insert(entry, key)
            audit('ledger.create', {'id': tid, 'kind': kind})
            order_id = data.get('order_id')
            if order_id and kind == 'Invoice':
                order = db().execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
                if not order or order['invoice_id']:
                    raise ValueError('This order already has an invoice or no longer exists.')
                db().execute("UPDATE orders SET invoice_id=?,customer_id=?,status='In Progress',updated=? WHERE id=?", (tid, data['customer_id'], timestamp(), order_id))
        token = db().execute('SELECT token FROM ledger WHERE id=?', (tid,)).fetchone()[0]
        return jsonify(id=tid, invoice_url='/invoice/' + token), 201

    @app.put('/api/transactions/<int:tid>')
    @owner_required
    def transaction_edit(tid):
        with db():
            db().execute('BEGIN IMMEDIATE')
            old = db().execute('SELECT * FROM ledger WHERE id=?', (tid,)).fetchone()
            if not old:
                abort(404)
            data = request.get_json() or {}
            if data.get('kind', old['kind']) != old['kind']:
                raise ValueError('Keep the original transaction type. Its linked records depend on it.')
            data['kind'] = old['kind']
            entry = validated_entry(data, tid)
            if not db().execute('SELECT id FROM customers WHERE id=?', (entry.get('customer_id'),)).fetchone():
                raise ValueError('Select an existing customer.')
            linked = db().execute('SELECT COUNT(*) FROM ledger WHERE related_id=?', (tid,)).fetchone()[0]
            if linked and entry['customer_id'] != old['customer_id']:
                raise ValueError('This invoice has linked payments/refunds. Keep its customer account.')
            if old['kind'] == 'Invoice':
                refunds = db().execute("SELECT COALESCE(SUM(-bill),0),COALESCE(SUM(-cost),0) FROM ledger WHERE related_id=? AND kind='Refund'", (tid,)).fetchone()
                if entry['bill'] < refunds[0] or entry['cost'] < refunds[1]:
                    raise ValueError('Bill/cost cannot be less than values already refunded.')
            db().execute('UPDATE ledger SET customer_id=?,date=?,number=?,category=?,description=?,bill=?,cost=?,cost_known=?,paid=?,method=?,due_date=?,items=?,related_id=?,notes=? WHERE id=?', (entry['customer_id'], valid_date(data.get('date')), text(data.get('number', old['number']),100), text(data.get('category', old['category']),100), text(entry.get('description')), entry['bill'], entry['cost'], entry['cost_known'], entry['paid'], data.get('method','Cash'), valid_date(entry.get('due_date'),True), json.dumps(entry.get('items',[]),ensure_ascii=False), entry.get('related_id') or None, text(data.get('notes')), tid))
            if old['kind'] == 'Invoice':
                db().execute('UPDATE orders SET quote=?,customer_id=?,updated=? WHERE invoice_id=?', (entry['bill'],entry['customer_id'],timestamp(),tid))
            audit('ledger.edit', {'id': tid, 'before': dict(old), 'after': entry})
        return jsonify(ok=True)

    @app.get('/api/transactions/<int:tid>')
    @owner_required
    def transaction_get(tid):
        entry=db().execute('SELECT * FROM ledger WHERE id=?',(tid,)).fetchone()
        if not entry:
            abort(404)
        return jsonify(dict(entry))

    @app.put('/api/transactions/<int:tid>/cost')
    @owner_required
    def record_cost(tid):
        amount = cents((request.get_json() or {}).get('cost'))
        entry = db().execute("SELECT * FROM ledger WHERE id=? AND kind='Invoice'", (tid,)).fetchone()
        if not entry:
            abort(404)
        reversed_cost = db().execute("SELECT COALESCE(SUM(-cost),0) FROM ledger WHERE related_id=? AND kind='Refund'", (tid,)).fetchone()[0]
        if amount < reversed_cost:
            raise ValueError('Production cost cannot be lower than the cost already reversed by refunds.')
        with db():
            db().execute('UPDATE ledger SET cost=?,cost_known=1 WHERE id=?', (amount, tid))
            audit('ledger.cost-correction', {'id': tid, 'old_cost': entry['cost'], 'new_cost': amount})
        return jsonify(ok=True)

    @app.get('/api/expenses')
    @login_required
    def expenses_api():
        return jsonify(rows('SELECT * FROM expenses ORDER BY date DESC,id DESC'))

    @app.post('/api/expenses')
    @login_required
    def expenses_add():
        data = request.get_json() or {}
        kind = data.get('kind', 'Expense')
        if kind not in ENTRY_TYPES or data.get('method', 'Cash') not in METHODS:
            raise ValueError('Select a valid entry type and payment method.')
        if kind != 'Expense' and g.user['role'] != 'owner':
            abort(403)
        amount = cents(data.get('amount'))
        if amount <= 0:
            raise ValueError('Amount must be positive.')
        with db():
            cur = db().execute('INSERT INTO expenses(date,kind,category,description,amount,method,vendor,notes,actor,created) VALUES(?,?,?,?,?,?,?,?,?,?)', (valid_date(data.get('date', today())), kind, text(data.get('category', 'Other'), 100), text(data.get('description')), amount, data.get('method', 'Cash'), text(data.get('vendor'), 120), text(data.get('notes')), actor(), timestamp()))
            audit('cash-entry.create', {'id': cur.lastrowid, 'kind': kind})
        return jsonify(id=cur.lastrowid), 201

    @app.put('/api/expenses/<int:eid>')
    @owner_required
    def expense_edit(eid):
        data = request.get_json() or {}
        if data.get('kind') not in ENTRY_TYPES or data.get('method') not in METHODS:
            raise ValueError('Select a valid entry type and payment method.')
        amount = cents(data.get('amount'))
        if amount <= 0:
            raise ValueError('Amount must be positive.')
        with db():
            old = db().execute('SELECT * FROM expenses WHERE id=?',(eid,)).fetchone()
            if not old:
                abort(404)
            linked = db().execute('SELECT id,quantity,item_id FROM stock WHERE expense_id=?',(eid,)).fetchone()
            if linked and data['kind'] != 'Stock Purchase':
                raise ValueError('This entry is linked to stock. Keep its Stock Purchase type.')
            db().execute('UPDATE expenses SET date=?,kind=?,category=?,description=?,amount=?,method=?,vendor=?,notes=? WHERE id=?', (valid_date(data.get('date')),data['kind'],text(data.get('category'),100),text(data.get('description')),amount,data['method'],text(data.get('vendor'),120),text(data.get('notes')),eid))
            if linked:
                unit = int((Decimal(amount)/Decimal(str(linked['quantity']))).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
                # Keep the stock valuation and its cash entry consistent.
                if int((Decimal(str(linked['quantity']))*unit).quantize(Decimal('1'),rounding=ROUND_HALF_UP)) != amount:
                    raise ValueError('Edit this stock movement to set its unit cost; this amount does not divide exactly into its quantity.')
                db().execute('UPDATE stock SET date=?,unit_cost=? WHERE id=?',(valid_date(data.get('date')),unit,linked['id']))
                validate_stock_history(linked['item_id'])
            audit('cash-entry.edit',{'id':eid,'before':dict(old),'after':data})
        return jsonify(ok=True)

    @app.get('/api/cashflow')
    @login_required
    def cashflow():
        daily = defaultdict(lambda: dict(collection=0, investment=0, expense=0, withdrawal=0, stock=0))
        for r in db().execute('SELECT date,SUM(paid) amount FROM ledger GROUP BY date'):
            daily[r['date']]['collection'] = r['amount']
        for r in db().execute('SELECT date,kind,SUM(amount) amount FROM expenses GROUP BY date,kind'):
            daily[r['date']][{'Expense': 'expense', 'Investment': 'investment', 'Owner Withdrawal': 'withdrawal', 'Stock Purchase': 'stock'}[r['kind']]] = r['amount']
        balance = cents(settings()['opening_cash'], True)
        result = []
        for day, values in sorted(daily.items()):
            values['net'] = values['collection'] + values['investment'] - values['expense'] - values['withdrawal'] - values['stock']
            balance += values['net']
            result.append({'date': day, **values, 'balance': balance})
        return jsonify(result)

    @app.get('/api/inventory')
    @login_required
    def inventory_api():
        return jsonify(items=rows("SELECT i.*,COALESCE(SUM(CASE WHEN s.kind='Used' THEN -s.quantity ELSE s.quantity END),0) stock FROM inventory i LEFT JOIN stock s ON s.item_id=i.id GROUP BY i.id ORDER BY i.name"), movements=rows('SELECT s.*,i.name FROM stock s JOIN inventory i ON i.id=s.item_id ORDER BY s.id DESC'))

    @app.post('/api/inventory')
    @owner_required
    def inventory_add():
        data = request.get_json() or {}
        if not text(data.get('name')):
            raise ValueError('Item name is required.')
        reorder = float(data.get('reorder') or 0)
        if not 0 <= reorder <= 10000000:
            raise ValueError('Invalid reorder level.')
        with db():
            cur = db().execute('INSERT INTO inventory(id,name,unit,supplier,reorder) VALUES(?,?,?,?,?)', (reserve_id(db(),'inventory'), text(data['name'], 100), text(data.get('unit', 'sheet'), 40), text(data.get('supplier'), 120), reorder))
            audit('inventory.create', {'id': cur.lastrowid})
        return jsonify(id=cur.lastrowid), 201

    @app.put('/api/inventory/<int:iid>')
    @owner_required
    def inventory_edit(iid):
        data = request.get_json() or {}
        level = float(data.get('reorder') or 0)
        if not text(data.get('name')) or not text(data.get('unit')) or not 0 <= level <= 10000000:
            raise ValueError('Enter a name, unit and valid reorder level.')
        with db():
            old = db().execute('SELECT * FROM inventory WHERE id=?',(iid,)).fetchone()
            if not old:
                abort(404)
            db().execute('UPDATE inventory SET name=?,unit=?,supplier=?,reorder=? WHERE id=?',(text(data['name'],100),text(data['unit'],40),text(data.get('supplier'),120),level,iid))
            audit('inventory.edit',{'id':iid,'before':dict(old),'after':data})
        return jsonify(ok=True)

    @app.post('/api/inventory/movement')
    @login_required
    def stock_add():
        data = request.get_json() or {}
        item = db().execute('SELECT * FROM inventory WHERE id=?', (data.get('item_id'),)).fetchone()
        kind = data.get('kind')
        if not item or kind not in ('Opening', 'Purchased', 'Used'):
            raise ValueError('Select an item and movement type.')
        if kind != 'Used' and g.user['role'] != 'owner':
            abort(403)
        quantity = float(data.get('quantity') or 0)
        if not 0 < quantity <= 10000000:
            raise ValueError('Quantity must be positive.')
        cost = cents(data.get('unit_cost'))
        with db():
            db().execute('BEGIN IMMEDIATE')
            if kind == 'Used':
                available = db().execute("SELECT COALESCE(SUM(CASE WHEN kind='Used' THEN -quantity ELSE quantity END),0) FROM stock WHERE item_id=?", (item['id'],)).fetchone()[0]
                if quantity > available:
                    raise ValueError('Not enough stock available.')
            movement = db().execute('INSERT INTO stock(id,item_id,date,kind,quantity,unit_cost,notes,actor) VALUES(?,?,?,?,?,?,?,?)', (reserve_id(db(),'stock'), item['id'], valid_date(data.get('date', today())), kind, quantity, cost, text(data.get('notes')), actor()))
            if kind == 'Purchased' and data.get('record_cash', True):
                amount = int((Decimal(str(quantity)) * cost).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
                cash_entry = db().execute('INSERT INTO expenses(date,kind,category,description,amount,method,vendor,notes,actor,created) VALUES(?,?,?,?,?,?,?,?,?,?)', (valid_date(data.get('date', today())), 'Stock Purchase', 'Materials', item['name'] + ' stock purchase', amount, 'Cash', item['supplier'], 'Inventory purchase; not an operating expense. Record consumed cost on invoices.', actor(), timestamp()))
                db().execute('UPDATE stock SET expense_id=? WHERE id=?', (cash_entry.lastrowid, movement.lastrowid))
            audit('stock.movement', data)
        return jsonify(ok=True), 201

    @app.put('/api/inventory/movement/<int:mid>')
    @owner_required
    def stock_edit(mid):
        data = request.get_json() or {}
        quantity = float(data.get('quantity') or 0)
        kind = data.get('kind')
        cost = cents(data.get('unit_cost'))
        if kind not in ('Opening','Purchased','Used') or not 0 < quantity <= 10000000:
            raise ValueError('Enter a valid movement type and positive quantity.')
        with db():
            db().execute('BEGIN IMMEDIATE')
            old = db().execute('SELECT * FROM stock WHERE id=?',(mid,)).fetchone()
            item = db().execute('SELECT * FROM inventory WHERE id=?',(data.get('item_id'),)).fetchone()
            if not old or not item:
                raise ValueError('Select an existing stock movement and material.')
            if old['expense_id'] and kind != 'Purchased':
                raise ValueError('This movement has a purchase cash entry. Keep its Purchased type.')
            db().execute('UPDATE stock SET item_id=?,date=?,kind=?,quantity=?,unit_cost=?,notes=? WHERE id=?',(item['id'],valid_date(data.get('date')),kind,quantity,cost,text(data.get('notes')),mid))
            for iid in {old['item_id'], item['id']}:
                validate_stock_history(iid)
            if old['expense_id']:
                amount = int((Decimal(str(quantity))*cost).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
                db().execute('UPDATE expenses SET date=?,amount=?,description=?,vendor=? WHERE id=?',(valid_date(data.get('date')),amount,item['name']+' stock purchase',item['supplier'],old['expense_id']))
            audit('stock.edit',{'id':mid,'before':dict(old),'after':data})
        return jsonify(ok=True)

    @app.get('/api/orders')
    @login_required
    def orders_api():
        cleanup_files()
        orders = rows("SELECT * FROM orders WHERE source='online' ORDER BY id DESC LIMIT 1000")
        for order in orders:
            order['files'] = rows('SELECT id,name,size,deleted_at FROM files WHERE order_id=?', (order['id'],))
            matches = [c['id'] for c in rows('SELECT id,phone FROM customers') if phone(c['phone']) == phone(order['phone'])]
            order['matched_customer_id'] = matches[0] if len(matches) == 1 else None
            invoice = db().execute('SELECT token FROM ledger WHERE id=?',(order['invoice_id'],)).fetchone() if order['invoice_id'] else None
            order['invoice_url'] = '/invoice/'+invoice['token'] if invoice else None
        return jsonify(orders)

    @app.put('/api/orders/<int:oid>')
    @login_required
    def orders_update(oid):
        data = request.get_json() or {}
        if data.get('status') not in ORDER_STATUSES:
            raise ValueError('Invalid order status.')
        if not db().execute('SELECT id FROM orders WHERE id=?', (oid,)).fetchone():
            abort(404)
        quote_value = cents(data['quote']) if data.get('quote') not in (None, '') else None
        if data['status']=='Quoted' and quote_value is not None and quote_value > 0:
            return confirm_order(oid)
        with db():
            invoiced = db().execute('SELECT invoice_id,quote FROM orders WHERE id=?',(oid,)).fetchone()
            if invoiced['invoice_id'] and quote_value != invoiced['quote']:
                raise ValueError('Edit the linked invoice to change its confirmed bill.')
            terminal = timestamp() if data['status'] in ('Delivered', 'Cancelled') else None
            db().execute('UPDATE orders SET completed_at=CASE WHEN ? IS NULL THEN NULL ELSE COALESCE(completed_at,?) END,status=?,quote=?,staff_notes=?,updated=? WHERE id=?', (terminal, terminal, data['status'], quote_value, text(data.get('staff_notes')), timestamp(), oid))
            audit('order.update', {'id': oid, **data})
        return jsonify(ok=True)

    @app.post('/api/orders/<int:oid>/confirm')
    @login_required
    def confirm_order(oid):
        data = request.get_json() or {}
        amount = cents(data.get('quote'))
        paid = cents(data.get('paid'))
        cost_value = data.get('cost')
        cost = cents(cost_value)
        if amount <= 0 or paid > amount or data.get('method','Cash') not in METHODS:
            raise ValueError('Enter a positive reviewed price and payment no greater than the bill.')
        with db():
            db().execute('BEGIN IMMEDIATE')
            order = db().execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
            if not order:
                abort(404)
            if order['source'] == 'shop':
                raise ValueError('Shop uploads are billed manually from Counter & billing.')
            if order['invoice_id']:
                token = db().execute('SELECT token FROM ledger WHERE id=?',(order['invoice_id'],)).fetchone()[0]
                return jsonify(ok=True,already_confirmed=True,invoice_url='/invoice/'+token,customer_id=order['customer_id'])
            if order['status']=='Cancelled':
                raise ValueError('Reopen this cancelled order before confirming its price.')
            matches = [c['id'] for c in rows('SELECT id,phone FROM customers') if phone(c['phone'])==phone(order['phone'])]
            cid = data.get('customer_id') or (matches[0] if len(matches)==1 else None)
            if len(matches)>1 and not cid:
                raise ValueError('Multiple customer accounts use this phone. Select the correct customer ID.')
            if cid and cid not in matches:
                raise ValueError('Select a customer account matching this order phone number.')
            if not cid:
                cid = create_customer({'name':order['name'],'phone':order['phone'],'notes':'Registered from confirmed online order.'})
            entry = {'customer_id':cid,'date':today(),'kind':'Invoice','category':order['service'],'description':order['details'],'bill':amount,'cost':cost,'cost_known':cost_value not in (None,''),'paid':paid,'method':data.get('method','Cash'),'due_date':(date.fromisoformat(today())+timedelta(days=int(settings()['credit_days']))).isoformat(),'items':[{'description':order['service']+' · '+order['details'][:130],'quantity':'1','price':amount,'amount':amount,'cost':cost,'cost_amount':cost,'cost_known':cost_value not in (None,'')}],'notes':text(data.get('staff_notes'))}
            tid = ledger_insert(entry,'online-order-confirm-'+str(oid))
            db().execute("UPDATE orders SET quote=?,invoice_id=?,customer_id=?,status='In Progress',staff_notes=?,updated=? WHERE id=?",(amount,tid,cid,text(data.get('staff_notes')),timestamp(),oid))
            audit('order.confirm-invoice',{'order_id':oid,'invoice_id':tid,'customer_id':cid,'bill':amount,'paid':paid})
            token = db().execute('SELECT token FROM ledger WHERE id=?',(tid,)).fetchone()[0]
        return jsonify(ok=True,invoice_url='/invoice/'+token,customer_id=cid),201

    @app.put('/api/orders/<int:oid>/details')
    @owner_required
    def order_details_edit(oid):
        data=request.get_json() or {}
        contact=phone(data.get('phone'))
        quantity=int(data.get('quantity') or 1)
        if not text(data.get('name')) or not re.fullmatch(r'8801\d{9}',contact) or data.get('service') not in SERVICES or not text(data.get('details')) or not 1<=quantity<=100000:
            raise ValueError('Enter valid customer details, service, instructions and quantity.')
        with db():
            db().execute('BEGIN IMMEDIATE')
            old=db().execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
            if not old:
                abort(404)
            options=json.loads(old['options'])
            for key in ('paper','sides','binding','deadline','bw_pages','color_pages'):
                if key in data:
                    options[key]=data[key]
            if data['service'] in ('Stamp Size Photo','Binding'):
                options.pop('bw_pages',None);options.pop('color_pages',None);options['pages']=1
            options['minimum_quote']=order_estimate(data['service'],quantity,options)
            cid=old['customer_id']
            if not old['invoice_id']:
                matches=[c['id'] for c in rows('SELECT id,phone FROM customers') if phone(c['phone'])==contact]
                if not matches:
                    matches=[create_customer({'name':data['name'],'phone':contact})]
                cid=matches[0] if len(matches)==1 else None
            db().execute('UPDATE orders SET name=?,phone=?,service=?,details=?,quantity=?,options=?,customer_id=?,updated=? WHERE id=?',(text(data['name'],120),contact,data['service'],text(data['details'],4000),quantity,json.dumps(options),cid,timestamp(),oid))
            audit('order.details-edit',{'id':oid,'before':dict(old),'after':data})
        return jsonify(ok=True)

    @app.post('/order/customer')
    def public_customer_lookup():
        key = 'lookup:' + str(request.remote_addr)
        now = time.monotonic()
        while attempts[key] and now - attempts[key][0] > 900:
            attempts[key].popleft()
        if len(attempts[key]) >= 30:
            return jsonify(error='Too many lookups. The shop can match your customer account.'), 429
        attempts[key].append(now)
        contact = phone((request.get_json() or {}).get('phone'))
        if not re.fullmatch(r'8801\d{9}', contact):
            raise ValueError('Enter a valid Bangladesh mobile number.')
        matches = [c['id'] for c in rows('SELECT id,phone FROM customers') if phone(c['phone']) == contact]
        # Show only the requested ID; balances, names and histories stay private.
        return jsonify(customer_id=matches[0] if len(matches) == 1 else None, multiple=len(matches) > 1)

    @app.post('/order/analyze')
    def analyze_order_files():
        key = 'analyze:' + str(request.remote_addr)
        now = time.monotonic()
        while attempts[key] and now - attempts[key][0] > 3600:
            attempts[key].popleft()
        if len(attempts[key]) >= 60:
            return jsonify(error='Too many page-count requests. Enter the page count manually.'), 429
        attempts[key].append(now)
        uploaded = [f for f in request.files.getlist('files') if f.filename]
        if not 1 <= len(uploaded) <= 5:
            raise ValueError('Select between one and five files.')
        results = []
        for f in uploaded:
            f.stream.seek(0, os.SEEK_END)
            if not f.stream.tell():
                raise ValueError('Uploaded files must not be empty.')
            f.stream.seek(0)
            results.append({'name': text(f.filename, 200), 'pages': file_pages(f.filename, f.stream)})
        complete = all(f['pages'] is not None for f in results)
        return jsonify(files=results, complete=complete, total_pages=sum(f['pages'] or 0 for f in results) if complete else None)

    @app.route('/order', methods=['GET', 'POST'])
    def shop_upload():
        return public_order(shop=True)

    @app.route('/online_order', methods=['GET', 'POST'])
    def public_order(shop=False):
        config = settings()
        if request.method == 'GET':
            notice = 'Files are automatically deleted ' + config['file_retention_days'] + ' days after ' + ('upload.' if config['file_retention_basis'] == 'upload' else 'delivery or cancellation.')
            if shop:
                notice = 'Files are automatically deleted ' + config['file_retention_days'] + ' days after upload.'
            if int(config['file_retention_days']) <= 0:
                notice = 'Automatic file deletion is currently disabled.'
            return render_template('upload.html' if shop else 'order.html', config=config, categories=SERVICES, prices=ORDER_PRICES, retention_notice=notice, csrf=session['csrf'])
        form = request.form.to_dict()
        if shop:
            form.update({'service':'Document Printing', 'quantity':'1', 'details':text(form.get('details'),4000) or 'Instructions given at the shop.', 'pages':'1', 'binding':'None'})
        key = ('shop-upload:' if shop else 'order:') + str(request.remote_addr)
        now = time.monotonic()
        while attempts[key] and now - attempts[key][0] > 3600:
            attempts[key].popleft()
        if len(attempts[key]) >= (120 if shop else 10):
            return jsonify(error='Order limit reached. Contact the business to place another order.'), 429
        if request.form.get('website'):
            abort(400)
        name = text(form.get('name'), 120)
        contact = phone(form.get('phone'))
        if not name or not re.fullmatch(r'8801\d{9}', contact):
            raise ValueError('Enter your name and a valid Bangladesh mobile number.')
        category = form.get('service')
        if category not in SERVICES:
            raise ValueError('Select a service.')
        details = text(form.get('details'), 4000)
        if not details:
            raise ValueError('Tell us what you need printed.')
        quantity = int(form.get('quantity') or 1)
        if not 1 <= quantity <= 100000:
            raise ValueError('Enter a valid number of copies.')
        if request.form.get('consent') != 'yes':
            raise ValueError('Please accept the file-processing notice.')
        uploaded = [f for f in request.files.getlist('files') if f.filename]
        if shop and not uploaded:
            raise ValueError('Choose at least one document to upload.')
        if len(uploaded) > 5:
            raise ValueError('Upload no more than five files.')
        checked = []
        allowed = {'.pdf', '.doc', '.docx', '.odt', '.jpg', '.jpeg', '.png', '.txt', '.pptx', '.xlsx'}
        for f in uploaded:
            filename = secure_filename(f.filename) or 'document'
            extension = Path(filename).suffix.lower()
            if extension not in allowed:
                raise ValueError('Supported files: PDF, Word, ODT, JPG, PNG, TXT, PPTX and XLSX.')
            f.stream.seek(0, os.SEEK_END)
            size = f.stream.tell()
            f.stream.seek(0)
            if not size:
                raise ValueError('Uploaded files must not be empty.')
            signature = f.stream.read(8)
            f.stream.seek(0)
            if extension == '.pdf' and not signature.startswith(b'%PDF-'):
                raise ValueError('One uploaded PDF does not have a valid PDF header.')
            if extension in ('.docx', '.pptx', '.xlsx', '.odt') and not signature.startswith(b'PK'):
                raise ValueError('Invalid office document.')
            checked.append((filename, secrets.token_hex(20) + extension, f, size))
        token = secrets.token_urlsafe(24)
        options = {k: text(request.form.get(k), 100) for k in ('paper', 'color', 'sides', 'binding', 'deadline')}
        counts = [{'name': filename, 'pages': file_pages(filename, upload.stream)} for filename, stored, upload, size in checked]
        options['file_pages'] = counts
        options['detected_pages'] = sum(f['pages'] for f in counts) if counts and all(f['pages'] is not None for f in counts) else None
        # A customer can choose fewer pages for a selected-page print request.
        # Keep both the detected original count and the requested print count.
        options['pages'] = request.form.get('pages') or options['detected_pages'] or 1
        if 'bw_pages' in request.form or 'color_pages' in request.form:
            options.update(bw_pages=request.form.get('bw_pages') or 0,color_pages=request.form.get('color_pages') or 0)
            if category in ('Stamp Size Photo','Binding'):
                options.pop('bw_pages',None)
                options.pop('color_pages',None)
                options['pages']=1
        options['minimum_quote'] = None if shop else order_estimate(category, quantity, options)
        options['minimum_rates'] = ORDER_PRICES
        if shop:
            options.pop('minimum_quote', None)
            options['source'] = 'shop'
        saved = []
        try:
            with db():
                db().execute('BEGIN IMMEDIATE')
                cur = db().execute('INSERT INTO orders(token,name,phone,service,details,quantity,options,created,updated) VALUES(?,?,?,?,?,?,?,?,?)', (token, name, contact, category, details, quantity, json.dumps(options), timestamp(), timestamp()))
                if shop:
                    db().execute("UPDATE orders SET source='shop' WHERE id=?", (cur.lastrowid,))
                matches = [c['id'] for c in rows('SELECT id,phone FROM customers') if phone(c['phone']) == contact]
                if not matches:
                    matches = [create_customer({'name': name, 'phone': contact, 'notes': 'Registered through shop upload.' if shop else 'Registered through online order portal.'})]
                if len(matches) == 1:
                    db().execute('UPDATE orders SET customer_id=? WHERE id=?', (matches[0], cur.lastrowid))
                for filename, stored, upload, size in checked:
                    path = data_dir / 'uploads' / stored
                    saved.append(path)
                    upload.save(path)
                    db().execute('INSERT INTO files(id,order_id,name,stored,size) VALUES(?,?,?,?,?)', (reserve_id(db(),'files'), cur.lastrowid, filename, stored, size))
        except Exception:
            for path in saved:
                path.unlink(missing_ok=True)
            raise
        attempts[key].append(now)
        return jsonify(ok=True, tracking_url='/track/' + token, order_number=f'ORD-{cur.lastrowid:05d}',customer_id=matches[0] if len(matches)==1 else None, shop_upload=shop), 201

    @app.get('/api/files')
    @login_required
    def files_list():
        cleanup_files()
        page = max(1, int(request.args.get('page', 1)))
        q = '%' + text(request.args.get('q'), 120) + '%'
        where = '(f.name LIKE ? OR o.name LIKE ? OR o.phone LIKE ? OR o.customer_id LIKE ?)'
        args = (q,q,q,q)
        total = db().execute('SELECT COUNT(*) FROM files f JOIN orders o ON o.id=f.order_id WHERE '+where,args).fetchone()[0]
        records = rows('SELECT f.id,f.name,f.size,f.deleted_at,o.id AS order_id,o.name AS customer_name,o.phone,o.customer_id,o.created,o.source,o.details FROM files f JOIN orders o ON o.id=f.order_id WHERE '+where+' ORDER BY f.id DESC LIMIT 100 OFFSET ?',(*args,(page-1)*100))
        return jsonify(rows=records,total=total,page=page)

    @app.get('/track/<token>')
    def tracking(token):
        order = db().execute('SELECT * FROM orders WHERE token=?', (token,)).fetchone()
        if not order:
            abort(404)
        invoice_token = db().execute('SELECT token FROM ledger WHERE id=?', (order['invoice_id'],)).fetchone() if order['invoice_id'] else None
        return render_template('track.html', order=dict(order), options=json.loads(order['options']), config=settings(), invoice_url='/invoice/' + invoice_token[0] if invoice_token else None)

    @app.get('/api/files/<int:fid>')
    @login_required
    def file_download(fid):
        cleanup_files()
        record = db().execute('SELECT * FROM files WHERE id=?', (fid,)).fetchone()
        if not record:
            abort(404)
        if record['deleted_at']:
            return jsonify(error='This file was deleted under the upload retention policy.'), 410
        inline = request.args.get('view') == '1' and Path(record['name']).suffix.lower() == '.pdf'
        return send_file(data_dir / 'uploads' / record['stored'], as_attachment=not inline, download_name=record['name'], mimetype='application/pdf' if inline else None)

    @app.get('/invoice/<token>')
    def invoice(token):
        entry = db().execute("SELECT * FROM ledger WHERE token=? AND kind='Invoice'", (token,)).fetchone()
        if not entry:
            abort(404)
        entry = dict(entry)
        customer = db().execute('SELECT * FROM customers WHERE id=?', (entry['customer_id'],)).fetchone()
        linked = db().execute("SELECT COALESCE(SUM(paid),0),COALESCE(SUM(CASE WHEN kind='Refund' THEN -bill ELSE 0 END),0) FROM ledger WHERE related_id=?", (entry['id'],)).fetchone()
        entry['total_paid'] = entry['paid'] + linked[0]
        entry['refund'] = linked[1]
        debts, unused_credit = outstanding_debts(dict(customer))
        entry['remaining'] = sum(d['amount'] for d in debts if d['invoice_id'] == entry['id'])
        entry['settled'] = max(0, entry['bill'] - entry['refund'] - entry['remaining'])
        actual_methods={entry['method']} if entry['paid']>0 else set()
        actual_methods.update(r['method'] for r in rows("SELECT method FROM ledger WHERE related_id=? AND kind='Payment' AND paid>0",(entry['id'],)))
        entry['payment_methods']=' / '.join(sorted(actual_methods)) if entry['remaining']==0 else ''
        items = json.loads(entry['items']) or [{'description': entry['description'], 'quantity': 1, 'price': entry['bill'], 'amount': entry['bill']}]
        return render_template('invoice.html', invoice=entry, customer=dict(customer), items=items, config=settings())

    @app.get('/qr/order.svg')
    @login_required
    def order_qr():
        config = settings()
        return svg_qr((config['public_url'] or app.config['PUBLIC_URL']).rstrip('/') + '/order')

    @app.get('/qr/online_order.svg')
    @login_required
    def online_order_qr():
        config = settings()
        return svg_qr((config['public_url'] or app.config['PUBLIC_URL']).rstrip('/') + '/online_order')

    @app.get('/qr/invoice/<token>.svg')
    def invoice_qr(token):
        entry = db().execute("SELECT * FROM ledger WHERE token=? AND kind='Invoice'", (token,)).fetchone()
        if not entry:
            abort(404)
        config = settings()
        if request.args.get('payment') == '1':
            if not config.get('merchant_qr'):
                abort(404)
            # Amount is the original billed total, clearly labelled on the invoice.
            # No scanning or callback marks a payment as received.
            return svg_qr(with_amount(config['merchant_qr'], entry['bill']) if config.get('dynamic_qr_enabled')=='1' and request.args.get('original')!='1' else config['merchant_qr'], branded=request.args.get('brand')=='1')
        return svg_qr((config['public_url'] or app.config['PUBLIC_URL']).rstrip('/') + '/invoice/' + token)

    def svg_qr(value, branded=False):
        stream = io.BytesIO()
        qrcode.make(value, image_factory=qrcode.image.svg.SvgPathImage, box_size=6, border=4, error_correction=qrcode.constants.ERROR_CORRECT_H).save(stream)
        if branded:
            root=ET.fromstring(stream.getvalue())
            size=float(root.attrib['viewBox'].split()[2])
            w,h=size*0.22,size*0.055
            x,y=(size-w)/2,(size-h)/2
            ns='{http://www.w3.org/2000/svg}'
            ET.SubElement(root,ns+'rect',{'x':str(x-size*.009),'y':str(y-size*.009),'width':str(w+size*.018),'height':str(h+size*.018),'fill':'white'})
            logo=base64.b64encode((ROOT/'static/bangla-qr-logo.svg').read_bytes()).decode()
            ET.SubElement(root,ns+'image',{'x':str(x),'y':str(y),'width':str(w),'height':str(h),'href':'data:image/svg+xml;base64,'+logo})
            stream=io.BytesIO(ET.tostring(root,encoding='utf-8',xml_declaration=True))
        stream.seek(0)
        return send_file(stream, mimetype='image/svg+xml')

    @app.get('/api/reminder/<cid>')
    @login_required
    def reminder(cid):
        customer = next((c for c in customer_totals() if c['id'] == cid), None)
        if not customer:
            abort(404)
        contact = phone(customer['phone'])
        if not re.fullmatch(r'8801\d{9}', contact):
            raise ValueError('Add a valid Bangladesh WhatsApp number to this customer first.')
        config=settings()
        statement_url=(config['public_url'] or app.config['PUBLIC_URL']).rstrip('/')+'/statement/'+customer['statement_token']
        message = config['reminder_template'].replace('{name}', customer['name']).replace('{due}', f"{max(customer['due'],0)/100:,.2f}")
        message = message.replace('{statement_url}',statement_url) if '{statement_url}' in message else message+'\n\nআপনার হিসাব / Account statement: '+statement_url
        return jsonify(url='https://wa.me/' + contact + '?text=' + quote(message), message=message,statement_url=statement_url)

    @app.get('/statement/<token>')
    def public_statement(token):
        customer=next((c for c in customer_totals() if c.get('statement_token')==token),None)
        if not customer:
            abort(404)
        history=rows('SELECT id,date,kind,number,description,bill,paid,method FROM ledger WHERE customer_id=? ORDER BY date,id',(customer['id'],))
        statement_methods(history,customer)
        balance=customer['opening']
        for entry in history:
            balance+=entry['bill']-entry['paid']
            entry['balance']=balance
        return render_template('statement.html',customer=customer,history=history,config=settings())

    @app.put('/api/settings')
    @owner_required
    def settings_save():
        data = request.get_json() or {}
        for field in ('vip_spend', 'credit_limit'):
            if field in data:
                cents(data[field])
        if 'opening_cash' in data:
            cents(data['opening_cash'], True)
        if 'file_retention_days' in data and not 1 <= int(data['file_retention_days']) <= 3650:
            raise ValueError('File retention must be between 1 and 3650 days.')
        if data.get('file_retention_basis', 'completed') not in ('completed', 'upload'):
            raise ValueError('Choose delivery/cancellation or upload as the file retention start.')
        for field in ('vip_orders', 'credit_days'):
            if field in data and not 1 <= int(data[field]) <= 10000:
                raise ValueError('VIP orders and credit days must be positive whole numbers.')
        public = text(data.get('public_url'))
        if public and not re.fullmatch(r'https?://[^\s?#]+', public):
            raise ValueError('Public URL must begin with http:// or https:// and have no query or fragment.')
        payload = text(data.get('merchant_qr'), 3000)
        if payload:
            parse_qr(payload)
        if data.get('dynamic_qr_enabled') == '1' and not payload:
            raise ValueError('Paste a valid merchant QR payload before enabling payment QR.')
        with db():
            for key in DEFAULT_SETTINGS:
                if key in data and key != 'merchant_qr_image':
                    db().execute('UPDATE settings SET value=? WHERE key=?', (text(data[key], 3000), key))
            audit('settings.update', {'keys': list(data)})
        return jsonify(ok=True)

    @app.post('/api/merchant-qr')
    @owner_required
    def merchant_image_upload():
        upload=request.files.get('image')
        if not upload or not upload.filename:
            raise ValueError('Choose your original merchant QR image.')
        content=upload.read(8*1024*1024+1)
        if len(content)>8*1024*1024:
            raise ValueError('Choose an image smaller than 8 MB.')
        try:
            with Image.open(io.BytesIO(content)) as image:
                format=image.format
                if format not in ('PNG','JPEG','WEBP') or image.width*image.height>20000000:
                    raise ValueError('Use a PNG, JPEG or WebP image with at most 20 million pixels.')
                image.verify()
        except (Image.DecompressionBombError,Image.DecompressionBombWarning, OSError, SyntaxError):
            raise ValueError('The image could not be read. Choose a valid PNG, JPEG or WebP.')
        extension={'PNG':'png','JPEG':'jpg','WEBP':'webp'}[format]
        stored=secrets.token_hex(20)+'.'+extension
        path=data_dir/'uploads'/stored
        path.write_bytes(content)
        try:
            with db():
                db().execute('INSERT INTO merchant_qr_images(stored,name,created,actor) VALUES(?,?,?,?)',(stored,text(upload.filename,200),timestamp(),actor()))
                db().execute("UPDATE settings SET value=? WHERE key='merchant_qr_image'",(stored,))
                audit('merchant-qr.upload',{'stored':stored,'name':text(upload.filename,200)})
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return jsonify(ok=True,url='/merchant-qr/'+stored),201

    @app.get('/merchant-qr/<stored>')
    def merchant_image(stored):
        if not re.fullmatch(r'[a-f0-9]{40}\.(png|jpg|webp)',stored) or settings().get('merchant_qr_image')!=stored:
            abort(404)
        path=data_dir/'uploads'/stored
        if not path.is_file(): abort(404)
        return send_file(path,conditional=True,max_age=3600)

    @app.get('/api/merchant-qr/history')
    @owner_required
    def merchant_history():
        return jsonify(rows('SELECT id,name,created,stored FROM merchant_qr_images ORDER BY id DESC'))

    @app.post('/api/merchant-qr/<int:image_id>/restore')
    @owner_required
    def merchant_image_restore(image_id):
        record=db().execute('SELECT * FROM merchant_qr_images WHERE id=?',(image_id,)).fetchone()
        if not record or not (data_dir/'uploads'/record['stored']).is_file():
            raise ValueError('This saved merchant image is unavailable.')
        with db():
            db().execute("UPDATE settings SET value=? WHERE key='merchant_qr_image'",(record['stored'],))
            audit('merchant-qr.restore',{'id':image_id})
        return jsonify(ok=True)

    @app.delete('/api/merchant-qr')
    @owner_required
    def merchant_image_remove():
        with db():
            previous=settings().get('merchant_qr_image')
            db().execute("UPDATE settings SET value='' WHERE key IN ('merchant_qr_image','merchant_qr')")
            db().execute("UPDATE settings SET value='0' WHERE key='dynamic_qr_enabled'")
            audit('merchant-qr.remove',{'previous':previous})
        return jsonify(ok=True)

    @app.post('/api/services')
    @owner_required
    def service_add():
        data = request.get_json() or {}
        if not text(data.get('name')):
            raise ValueError('Service name required.')
        with db():
            cur = db().execute('INSERT INTO services(id,name,price,cost,unit) VALUES(?,?,?,?,?)', (reserve_id(db(),'services'), text(data['name'], 120), cents(data.get('price')), cents(data.get('cost')), text(data.get('unit', 'page'), 40)))
            audit('service.create', {'id': cur.lastrowid})
        return jsonify(id=cur.lastrowid), 201

    @app.delete('/api/services/<int:sid>')
    @owner_required
    def service_remove(sid):
        with db():
            db().execute('UPDATE services SET active=0 WHERE id=?', (sid,))
            audit('service.deactivate', {'id': sid})
        return jsonify(ok=True)

    @app.put('/api/services/<int:sid>')
    @owner_required
    def service_edit(sid):
        data=request.get_json() or {}
        if not text(data.get('name')):
            raise ValueError('Enter a service name.')
        with db():
            old=db().execute('SELECT * FROM services WHERE id=?',(sid,)).fetchone()
            if not old:
                abort(404)
            db().execute('UPDATE services SET name=?,price=?,cost=?,unit=? WHERE id=?',(text(data['name'],120),cents(data.get('price')),cents(data.get('cost')),text(data.get('unit','page'),40),sid))
            audit('service.edit',{'id':sid,'before':dict(old),'after':data})
        return jsonify(ok=True)

    @app.get('/api/users')
    @owner_required
    def users_api():
        return jsonify(rows('SELECT id,username,role,active FROM users ORDER BY id'))

    @app.post('/api/users')
    @owner_required
    def users_add():
        data = request.get_json() or {}
        username = text(data.get('username'), 40)
        if not re.fullmatch(r'[A-Za-z0-9_.-]{3,40}', username) or len(data.get('password', '')) < 12:
            raise ValueError('Use a valid username and a password of at least 12 characters.')
        if data.get('role') not in ('owner', 'staff'):
            raise ValueError('Select an owner or staff role.')
        with db():
            db().execute('INSERT INTO users(id,username,password,role) VALUES(?,?,?,?)', (reserve_id(db(),'users'), username, generate_password_hash(data['password']), data['role']))
            audit('user.create', {'username': username, 'role': data['role']})
        return jsonify(ok=True), 201

    @app.put('/api/users/<int:uid>')
    @owner_required
    def users_update(uid):
        data = request.get_json() or {}
        if uid == g.user['id'] and data.get('active') is False:
            raise ValueError('You cannot disable your own account.')
        target = db().execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
        if not target:
            abort(404)
        with db():
            if 'active' in data:
                db().execute('UPDATE users SET active=? WHERE id=?', (bool(data['active']), uid))
            if data.get('password'):
                if len(data['password']) < 12:
                    raise ValueError('Password must be at least 12 characters.')
                db().execute('UPDATE users SET password=? WHERE id=?', (generate_password_hash(data['password']), uid))
            audit('user.update', {'id': uid, 'password_changed': bool(data.get('password')), 'active': data.get('active')})
        return jsonify(ok=True)

    @app.get('/api/audit')
    @owner_required
    def audit_api():
        return jsonify(rows('SELECT * FROM audit ORDER BY id DESC LIMIT 500'))

    @app.get('/api/export/<kind>.csv')
    @owner_required
    def export_csv(kind):
        if kind == 'customers':
            records = customer_totals()
        elif kind == 'transactions':
            records = rows('SELECT l.*,c.name customer_name FROM ledger l JOIN customers c ON c.id=l.customer_id ORDER BY l.date,l.id')
            for record in records:
                record.pop('token', None)
        elif kind == 'expenses':
            records = rows('SELECT * FROM expenses ORDER BY date,id')
        else:
            abort(404)
        output = io.StringIO(newline='')
        if records:
            writer = csv.DictWriter(output, fieldnames=records[0].keys())
            writer.writeheader()
            for record in records:
                safe = {k: ("'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v) for k, v in record.items()}
                writer.writerow(safe)
        return send_file(io.BytesIO(('\ufeff' + output.getvalue()).encode('utf-8')), mimetype='text/csv', as_attachment=True, download_name='digitxbd-' + kind + '-amounts-in-paisa.csv')

    @app.get('/api/backup')
    @owner_required
    def backup():
        # SQLite's backup API gives a consistent database snapshot with WAL enabled.
        snapshot = data_dir / ('backup-' + secrets.token_hex(8) + '.sqlite')
        target = sqlite3.connect(snapshot)
        try:
            db().backup(target)
            target.close()
            stream = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, dir=data_dir, mode='w+b')
            with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.write(snapshot, 'digitxbd.sqlite')
                stored_files={r['stored'] for r in db().execute('SELECT stored FROM files')}
                stored_files.update(r['stored'] for r in db().execute('SELECT stored FROM merchant_qr_images'))
                for archived in rows('SELECT payload FROM recycle_bin WHERE restored_at IS NULL'):
                    stored_files.update(f['stored'] for f in json.loads(archived['payload'])['rows'].get('files',[]) if not f.get('deleted_at'))
                for record in ({'stored':f} for f in stored_files):
                    path = data_dir / 'uploads' / record['stored']
                    if path.exists():
                        archive.write(path, 'uploads/' + record['stored'])
            stream.seek(0)
            return send_file(stream, mimetype='application/zip', as_attachment=True, download_name='digitxbd-backup-' + today() + '.zip')
        finally:
            target.close()
            snapshot.unlink(missing_ok=True)

    @app.template_filter('taka')
    def taka(value):
        return f'৳{(value or 0)/100:,.2f}'

    register_records(app, globals())
    register_printing(app, globals())
    return app


if __name__ == '__main__':
    import threading
    from waitress import serve
    application = create_app()
    # Waitress also spools incoming request bodies. Keep those off /tmp's 64 MB tmpfs.
    tempfile.tempdir = str(Path(application.config['DATA_DIR']) / '.upload-tmp')
    def retention_worker():
        while True:
            try:
                with application.app_context():
                    g.app_data = application.config['DATA_DIR']
                    application.extensions['cleanup_files']()
            except Exception:
                application.logger.exception('Upload retention cleanup failed; will retry.')
            time.sleep(3600)
    threading.Thread(target=retention_worker, daemon=True).start()
    serve(application, host='0.0.0.0', port=int(os.environ.get('PORT', '8080')), threads=8, max_request_body_size=2**63-1)
