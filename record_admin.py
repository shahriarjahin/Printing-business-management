"""Recoverable owner deletion, dependency previews, and record restoration."""
import hashlib
import json
import secrets
from flask import abort, jsonify, request, g

KINDS = {'customers':'customers', 'transactions':'ledger', 'expenses':'expenses',
         'inventory':'inventory', 'movements':'stock', 'orders':'orders',
         'files':'files', 'services':'services', 'users':'users'}
TABLES = ['customers','expenses','inventory','services','users','ledger','orders','stock','files']


def register(app, core):
    db, rows, audit, owner, stamp = [core[k] for k in ('db','rows','audit','owner_required','timestamp')]

    def plan(kind, rid):
        if kind not in KINDS:
            abort(404)
        table = KINDS[kind]
        target = db().execute('SELECT * FROM '+table+' WHERE id=?',(rid,)).fetchone()
        if not target:
            abort(404)
        if table == 'users' and target['id'] == g.user['id']:
            raise ValueError('You cannot delete your own signed-in account.')
        selected = {t:{} for t in TABLES}
        patches = []
        def add(t, record):
            selected[t][str(record['id'])] = dict(record)
        add(table, target)
        if table == 'customers':
            for t, key in [('ledger','customer_id'),('orders','customer_id')]:
                for r in rows('SELECT * FROM '+t+' WHERE '+key+'=?',(rid,)):
                    add(t,r)
        if table == 'inventory':
            for r in rows('SELECT * FROM stock WHERE item_id=?',(rid,)):
                add('stock',r)
        # Linked payments/refunds must travel with their invoice.
        for r in list(selected['ledger'].values()):
            for child in rows('SELECT * FROM ledger WHERE related_id=?',(r['id'],)):
                add('ledger',child)
        for r in list(selected['ledger'].values()):
            for order in rows('SELECT * FROM orders WHERE invoice_id=?',(r['id'],)):
                if str(order['id']) not in selected['orders']:
                    before={k:order[k] for k in ('invoice_id','quote','status')}
                    patches.append({'id':order['id'],'before':before,
                                    'after':{'invoice_id':None,'quote':None,'status':'New'}})
        for r in list(selected['stock'].values()):
            if r['expense_id']:
                expense=db().execute('SELECT * FROM expenses WHERE id=?',(r['expense_id'],)).fetchone()
                if expense: add('expenses',expense)
        for r in list(selected['expenses'].values()):
            for move in rows('SELECT * FROM stock WHERE expense_id=?',(r['id'],)):
                add('stock',move)
        for r in list(selected['orders'].values()):
            for f in rows('SELECT * FROM files WHERE order_id=?',(r['id'],)):
                add('files',f)
        payload={'rows':{t:list(v.values()) for t,v in selected.items() if v},'patches':patches}
        fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        label=target['name'] if 'name' in target.keys() else target['username'] if 'username' in target.keys() else target['number'] if 'number' in target.keys() and target['number'] else kind+' #'+str(rid)
        return payload,fingerprint,label

    def summary(payload):
        return {t:len(v) for t,v in payload['rows'].items()}

    @app.get('/api/delete-preview/<kind>/<rid>')
    @owner
    def preview(kind,rid):
        payload,fingerprint,label=plan(kind,rid)
        return jsonify(label=label,counts=summary(payload),reopened_orders=len(payload['patches']),fingerprint=fingerprint)

    @app.delete('/api/records/<kind>/<rid>')
    @owner
    def remove(kind,rid):
        data=request.get_json() or {}
        reason=core['text'](data.get('reason'),500)
        if not reason: raise ValueError('Enter a reason for deleting this record.')
        with db():
            db().execute('BEGIN IMMEDIATE')
            payload,fingerprint,label=plan(kind,rid)
            if fingerprint != data.get('fingerprint'):
                return jsonify(error='The record changed. Reopen Delete to review the latest affected records.'),409
            for patch in payload['patches']:
                db().execute("UPDATE orders SET invoice_id=NULL,quote=NULL,status='New' WHERE id=?",(patch['id'],))
            db().execute('PRAGMA defer_foreign_keys=ON')
            for t in reversed(TABLES):
                for record in payload['rows'].get(t,[]):
                    db().execute('DELETE FROM '+t+' WHERE id=?',(record['id'],))
            for iid in {r['item_id'] for r in payload['rows'].get('stock',[])}:
                core['validate_stock_history'](iid)
            cur=db().execute('INSERT INTO recycle_bin(kind,record_id,label,payload,reason,actor,created) VALUES(?,?,?,?,?,?,?)',
                (kind,str(rid),label,json.dumps(payload,ensure_ascii=False),reason,core['actor'](),stamp()))
            audit('record.delete',{'trash_id':cur.lastrowid,'kind':kind,'id':rid,'counts':summary(payload),'reason':reason})
        return jsonify(ok=True,trash_id=cur.lastrowid)

    @app.get('/api/recycle-bin')
    @owner
    def trash():
        return jsonify(rows('SELECT id,kind,record_id,label,reason,actor,created,restored_at FROM recycle_bin WHERE restored_at IS NULL ORDER BY id DESC'))

    def clear_plan():
        archived=rows('SELECT id,payload FROM recycle_bin WHERE restored_at IS NULL ORDER BY id')
        fingerprint=hashlib.sha256(json.dumps(archived,sort_keys=True).encode()).hexdigest()
        return archived,fingerprint

    @app.get('/api/recycle-bin/clear-preview')
    @owner
    def clear_preview():
        archived,fingerprint=clear_plan()
        return jsonify(count=len(archived),fingerprint=fingerprint)

    @app.post('/api/recycle-bin/clear')
    @owner
    def clear_trash():
        data=request.get_json() or {}
        if data.get('confirmation')!='CLEAR':
            raise ValueError('Type CLEAR to permanently remove deleted records.')
        candidates=set()
        with db():
            db().execute('BEGIN IMMEDIATE')
            archived,fingerprint=clear_plan()
            if not secrets.compare_digest(str(data.get('fingerprint','')),fingerprint):
                raise ValueError('Recycle Bin changed. Review the current items before clearing it.')
            for entry in archived:
                candidates.update(f['stored'] for f in json.loads(entry['payload'])['rows'].get('files',[]))
            db().execute('DELETE FROM recycle_bin WHERE restored_at IS NULL')
            live={f['stored'] for f in rows('SELECT stored FROM files')}
            live.update(f['stored'] for f in rows('SELECT stored FROM merchant_qr_images'))
            audit('recycle-bin.clear',{'count':len(archived)})
        # Shared/live documents are preserved. Files are removed only after the archive deletion commits.
        import re
        from pathlib import Path
        for stored in candidates-live:
            if re.fullmatch(r'[a-f0-9]{40}\.[a-z0-9]+',stored):
                try:
                    (Path(app.config['DATA_DIR'])/'uploads'/stored).unlink(missing_ok=True)
                except OSError:
                    app.logger.warning('Could not remove an orphaned upload after clearing the recycle bin.')
        return jsonify(ok=True,count=len(archived))

    @app.post('/api/recycle-bin/<int:tid>/restore')
    @owner
    def restore(tid):
        with db():
            db().execute('BEGIN IMMEDIATE')
            archived=db().execute('SELECT * FROM recycle_bin WHERE id=? AND restored_at IS NULL',(tid,)).fetchone()
            if not archived: abort(404)
            payload=json.loads(archived['payload'])
            db().execute('PRAGMA defer_foreign_keys=ON')
            for patch in payload['patches']:
                current=db().execute('SELECT invoice_id,quote,status FROM orders WHERE id=?',(patch['id'],)).fetchone()
                if not current or dict(current)!=patch['after']:
                    raise ValueError('A linked order changed after deletion. Restore its original state or delete its replacement invoice first.')
            for t in TABLES:
                for record in payload['rows'].get(t,[]):
                    columns=list(record)
                    db().execute('INSERT INTO '+t+'('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',list(record.values()))
            for patch in payload['patches']:
                db().execute('UPDATE orders SET invoice_id=?,quote=?,status=? WHERE id=?',
                    (*[patch['before'][k] for k in ('invoice_id','quote','status')],patch['id']))
            for iid in {r['item_id'] for r in payload['rows'].get('stock',[])}:
                core['validate_stock_history'](iid)
            for cid in {r['id'] for r in payload['rows'].get('customers',[])}:
                c=db().execute('SELECT phone FROM customers WHERE id=?',(cid,)).fetchone()
                if c['phone'] and any(core['phone'](r['phone'])==core['phone'](c['phone']) for r in rows('SELECT phone FROM customers WHERE id<>?',(cid,))):
                    raise ValueError('This phone now belongs to another customer. Correct that duplicate before restoring.')
            # Restoring an invoice-linked refund cannot exceed a corrected invoice.
            bad=db().execute("SELECT l.id FROM ledger l JOIN ledger r ON r.related_id=l.id AND r.kind='Refund' GROUP BY l.id HAVING SUM(-r.bill)>l.bill OR SUM(-r.cost)>l.cost").fetchone()
            if bad: raise ValueError('Restoration would exceed a corrected invoice refund limit. Correct the invoice first.')
            db().execute('UPDATE recycle_bin SET restored_at=? WHERE id=?',(stamp(),tid))
            audit('record.restore',{'trash_id':tid,'counts':summary(payload)})
        return jsonify(ok=True)


def reserve_id(db, table):
    """Keep deleted IDs reserved so restoration and public links remain stable."""
    last=db.execute('SELECT value FROM record_sequences WHERE name=?',(table,)).fetchone()
    live=db.execute('SELECT COALESCE(MAX(id),0) FROM '+table).fetchone()[0]
    value=max(live,int(last[0]) if last else 0)+1
    db.execute('INSERT INTO record_sequences(name,value) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',(table,value))
    return value
