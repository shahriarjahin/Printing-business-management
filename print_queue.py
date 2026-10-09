"""Owner-approved PDF queue. The Windows helper connects outbound using a scoped token."""
import hashlib
import io
import json
import re
import secrets
import time
from functools import wraps
from pathlib import Path

from flask import abort, g, jsonify, request, send_file

SCHEMA = '''
CREATE TABLE IF NOT EXISTS print_agent(id INTEGER PRIMARY KEY CHECK(id=1),token_hash TEXT NOT NULL,owner_id INTEGER NOT NULL,helper_id TEXT NOT NULL DEFAULT '',printer TEXT NOT NULL DEFAULT '',printers TEXT NOT NULL DEFAULT '[]',last_seen REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS print_jobs(id INTEGER PRIMARY KEY AUTOINCREMENT,file_id INTEGER NOT NULL,file_stored TEXT NOT NULL,file_name TEXT NOT NULL,customer TEXT NOT NULL,options TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',created TEXT NOT NULL,updated TEXT NOT NULL,claimed_at REAL,claim_key TEXT,detail TEXT NOT NULL DEFAULT '',request_key TEXT UNIQUE NOT NULL);
CREATE INDEX IF NOT EXISTS idx_print_queue ON print_jobs(status,id);
'''


def authenticate(core):
    token = request.headers.get('Authorization', '')
    if not token.startswith('Bearer ') or len(token) > 200:
        abort(401)
    agent = core['db']().execute('''SELECT a.* FROM print_agent a JOIN users u ON u.id=a.owner_id
        WHERE a.id=1 AND u.active=1 AND u.role='owner' ''').fetchone()
    digest = hashlib.sha256(token[7:].encode()).hexdigest()
    if not agent or not secrets.compare_digest(agent['token_hash'], digest):
        abort(401)
    helper_id = request.headers.get('X-Print-Helper', '')
    if not re.fullmatch(r'[a-f0-9-]{36}', helper_id):
        abort(401)
    if (agent['helper_id'] and agent['helper_id'] != helper_id) or (not agent['helper_id'] and request.path != '/api/print-agent/heartbeat'):
        abort(403)
    g.print_agent = dict(agent)


def register(app, core):
    db, owner, stamp = core['db'], core['owner_required'], core['timestamp']

    def age_claims():
        # Never automatically reprint a job after losing acknowledgement.
        db().execute("UPDATE print_jobs SET status='uncertain',updated=?,detail='Connection interrupted. Check the printer before sending again.' WHERE status='claimed' AND claimed_at<?", (stamp(), time.time()-600))

    def source(fid):
        app.extensions['cleanup_files']()
        row = db().execute('''SELECT f.*,o.name customer FROM files f JOIN orders o ON o.id=f.order_id WHERE f.id=?''', (fid,)).fetchone()
        if not row or row['deleted_at']:
            raise ValueError('This document was deleted or expired. Upload it again before printing.')
        path = Path(app.config['DATA_DIR']) / 'uploads' / row['stored']
        if not path.is_file() or Path(row['name']).suffix.lower() != '.pdf':
            raise ValueError('Automatic printing supports available PDF files only. Convert other documents to PDF first.')
        return dict(row), path

    def agent_only(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            authenticate(core)
            return fn(*args, **kwargs)
        return wrapped

    def claimed(jid):
        row = db().execute('SELECT * FROM print_jobs WHERE id=?', (jid,)).fetchone()
        key = request.headers.get('X-Print-Claim', '')
        if not row or not row['claim_key'] or not secrets.compare_digest(row['claim_key'], key):
            abort(409)
        return dict(row)

    @app.get('/api/printing')
    @owner
    def overview():
        with db():
            age_claims()
        a = db().execute('SELECT printer,printers,last_seen FROM print_agent WHERE id=1').fetchone()
        agent = dict(a) if a else {'printer': '', 'printers': '[]', 'last_seen': 0}
        agent['printers'] = json.loads(agent['printers'])
        agent['paired'] = a is not None
        agent['online'] = time.time()-agent['last_seen'] < 60
        jobs = [dict(r) for r in db().execute('SELECT id,file_id,file_name,customer,options,status,created,updated,detail FROM print_jobs ORDER BY id DESC LIMIT 200')]
        for j in jobs:
            j['options'] = json.loads(j['options'])
        return jsonify(agent=agent, jobs=jobs)

    @app.post('/api/printing/pair')
    @owner
    def pair():
        token = secrets.token_urlsafe(40)
        with db():
            db().execute("UPDATE print_jobs SET status='uncertain',updated=?,detail='Printer helper was replaced. Check the printer before sending again.' WHERE status='claimed'", (stamp(),))
            # Clear old claims so a revoked helper cannot acknowledge new pairings.
            db().execute("UPDATE print_jobs SET claim_key=NULL WHERE claim_key IS NOT NULL")
            db().execute('INSERT OR REPLACE INTO print_agent(id,token_hash,owner_id) VALUES(1,?,?)', (hashlib.sha256(token.encode()).hexdigest(), g.user['id']))
            core['audit']('printing.pair', {'owner_id': g.user['id']})
        return jsonify(token=token)

    @app.post('/api/printing/disconnect')
    @owner
    def disconnect():
        with db():
            db().execute('DELETE FROM print_agent')
            db().execute("UPDATE print_jobs SET status='uncertain',claim_key=NULL,updated=?,detail='Helper disconnected; check printer.' WHERE status='claimed'", (stamp(),))
            db().execute("UPDATE print_jobs SET status='cancelled',updated=? WHERE status='queued'", (stamp(),))
            core['audit']('printing.disconnect', {})
        return jsonify(ok=True)

    @app.post('/api/printing/jobs')
    @owner
    def enqueue():
        data = request.get_json() or {}
        key = str(data.get('request_key', ''))
        if not re.fullmatch(r'[a-zA-Z0-9_-]{16,100}', key):
            raise ValueError('Refresh the print form and try again.')
        existing = db().execute('SELECT id FROM print_jobs WHERE request_key=?', (key,)).fetchone()
        if existing:
            return jsonify(id=existing['id']), 200
        agent = db().execute('SELECT * FROM print_agent WHERE id=1').fetchone()
        if not agent or not agent['printer']:
            raise ValueError('Connect the Windows printer helper first from Print queue.')
        record, path = source(data.get('file_id'))
        pages_total = core['file_pages'](record['name'], path.read_bytes())
        if pages_total is None:
            raise ValueError('The PDF is damaged or password protected. Upload an unlocked PDF.')
        copies = str(data.get('copies', '1'))
        if not re.fullmatch(r'\d{1,2}', copies) or not 1 <= int(copies) <= 50:
            raise ValueError('Copies must be between 1 and 50.')
        pages = str(data.get('pages', '')).replace(' ', '')
        count = pages_total
        if pages:
            if len(pages) > 300 or not re.fullmatch(r'\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*', pages):
                raise ValueError('Use page numbers such as 1-3,5,8-10 or leave blank for all pages.')
            selected = set()
            for part in pages.split(','):
                limits = [int(n) for n in part.split('-')]
                first, last = limits[0], limits[-1]
                if not 1 <= first <= last <= pages_total:
                    raise ValueError('Page range is outside this PDF.')
                page_set = set(range(first, last+1))
                if selected & page_set:
                    raise ValueError('Page ranges overlap. Choose each page once.')
                selected.update(page_set)
            count = len(selected)
        if count * int(copies) > 5000:
            raise ValueError('Send large documents in batches of at most 5,000 printed pages.')
        mode, paper, scale = data.get('mode'), data.get('paper'), data.get('scale')
        if mode not in ('monochrome', 'color') or paper not in ('A4', 'A5', 'letter', 'legal') or scale not in ('fit', 'shrink', 'noscale'):
            raise ValueError('Choose valid color, paper and sizing options.')
        options = {'printer': agent['printer'], 'copies': int(copies), 'pages': pages, 'mode': mode, 'paper': paper, 'scale': scale, 'page_count': count}
        with db():
            cur = db().execute('INSERT INTO print_jobs(file_id,file_stored,file_name,customer,options,created,updated,request_key) VALUES(?,?,?,?,?,?,?,?)', (record['id'], record['stored'], record['name'], record['customer'], json.dumps(options), stamp(), stamp(), key))
            core['audit']('printing.queue', {'id': cur.lastrowid, 'file_id': record['id'], 'options': options})
        return jsonify(id=cur.lastrowid), 201

    @app.post('/api/printing/jobs/<int:jid>/cancel')
    @owner
    def cancel(jid):
        with db():
            result = db().execute("UPDATE print_jobs SET status='cancelled',updated=? WHERE id=? AND status='queued'", (stamp(), jid))
            if not result.rowcount:
                raise ValueError('Only waiting jobs can be cancelled. Check Windows printer queue for jobs already sent.')
            core['audit']('printing.cancel', {'id': jid})
        return jsonify(ok=True)

    @app.post('/api/print-agent/heartbeat')
    @agent_only
    def heartbeat():
        data = request.get_json() or {}
        printers = data.get('printers', [])
        printer = data.get('printer', '')
        if not isinstance(printers, list) or len(printers) > 100 or any(not isinstance(p, str) or not 1 <= len(p) <= 200 or re.search(r'["\r\n]', p) for p in printers) or printer not in printers:
            raise ValueError('Choose an installed Windows printer in the helper setup.')
        with db():
            db().execute('BEGIN IMMEDIATE')
            current = db().execute('SELECT helper_id FROM print_agent WHERE id=1').fetchone()
            helper_id = request.headers['X-Print-Helper']
            if current['helper_id'] and current['helper_id'] != helper_id:
                abort(403)
            age_claims()
            db().execute('UPDATE print_agent SET printer=?,printers=?,last_seen=?,helper_id=? WHERE id=1', (printer, json.dumps(printers), time.time(), helper_id))
        return jsonify(ok=True)

    @app.post('/api/print-agent/next')
    @agent_only
    def next_job():
        with db():
            db().execute('BEGIN IMMEDIATE')
            age_claims()
            # A helper restarts safely by consulting its local journal for this claim.
            job = db().execute("SELECT * FROM print_jobs WHERE status='claimed' ORDER BY id LIMIT 1").fetchone()
            if not job:
                job = db().execute("SELECT * FROM print_jobs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
                if job:
                    db().execute("UPDATE print_jobs SET status='claimed',claimed_at=?,claim_key=?,updated=? WHERE id=?", (time.time(), secrets.token_urlsafe(32), stamp(), job['id']))
                    job = db().execute('SELECT * FROM print_jobs WHERE id=?', (job['id'],)).fetchone()
        if not job:
            return jsonify(job=None)
        return jsonify(job={'id': job['id'], 'claim_key': job['claim_key'], 'options': json.loads(job['options']), 'file_name': job['file_name']})

    @app.get('/api/print-agent/jobs/<int:jid>/file')
    @agent_only
    def document(jid):
        job = claimed(jid)
        if job['status'] != 'claimed':
            abort(409)
        record, path = source(job['file_id'])
        if record['stored'] != job['file_stored']:
            raise ValueError('Original document is no longer available. Upload and review it again.')
        return send_file(path, mimetype='application/pdf', as_attachment=True, download_name='print-job.pdf')

    @app.post('/api/print-agent/jobs/<int:jid>/result')
    @agent_only
    def result(jid):
        job = claimed(jid)
        data = request.get_json() or {}
        status = data.get('status')
        if status not in ('submitted', 'failed', 'uncertain'):
            raise ValueError('Invalid printer result.')
        if job['status'] == status:
            return jsonify(ok=True)
        if job['status'] not in ('claimed', 'uncertain'):
            abort(409)
        with db():
            db().execute('UPDATE print_jobs SET status=?,updated=?,detail=? WHERE id=?', (status, stamp(), str(data.get('detail', ''))[:500], jid))
        return jsonify(ok=True)

    @app.get('/api/printing/helper.zip')
    @owner
    def helper_package():
        import zipfile
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in (Path(__file__).parent / 'printer-helper').glob('*.ps1'):
                archive.write(path, path.name)
            archive.write(Path(__file__).parent / 'PRINTING.md', 'READ-ME.md')
        stream.seek(0)
        return send_file(stream, mimetype='application/zip', as_attachment=True, download_name='DigitXBD-Printer-Helper.zip')
