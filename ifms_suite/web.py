import hashlib,json,sqlite3
from pathlib import Path
from flask import Blueprint,current_app,jsonify,request,render_template,send_file
from .storage import database,initialize
from .calculation import calculate_claim
from . import exports

suite=Blueprint('suite',__name__,template_folder='templates',static_folder='static',url_prefix='/suite')

@suite.errorhandler(ValueError)
def bad_input(error):return jsonify(error=str(error)),400

@suite.get('/')
def home():return render_template('suite.html')

@suite.route('/api/employees',methods=['GET','POST'])
def employees():
    with database() as db:
        if request.method=='GET':return jsonify([json.loads(r['payload']) for r in db.execute('SELECT payload FROM suite_employees ORDER BY name')])
        p=request.get_json() or {};code=str(p.get('employee_code','')).strip().upper()
        if not code or not p.get('name'):raise ValueError('Employee code and name required')
        p['employee_code']=code
        existing=db.execute('SELECT payload FROM suite_employees WHERE employee_code=?',(code,)).fetchone()
        if existing:
            if json.loads(existing['payload'])==p:return jsonify(p)
            return jsonify(error='Conflicting employee record. Resolve identity before replacing history.',existing=json.loads(existing['payload'])),409
        db.execute('INSERT INTO suite_employees VALUES(?,?,?)',(code,p['name'],json.dumps(p)))
        return jsonify(p),201

@suite.route('/api/rates',methods=['GET','POST'])
def rates():
    from datetime import date
    from .calculation import money
    with database() as db:
        if request.method=='GET':return jsonify([dict(id=r['id'],**json.loads(r['payload'])) for r in db.execute('SELECT * FROM suite_rates')])
        p=request.get_json() or {}
        for k in ['allowance','effective_from','rate','reference']:
            if p.get(k) in ('',None):raise ValueError('Required: '+k)
        date.fromisoformat(p['effective_from']);money(p['rate'])
        p['verification']='manual';p['basis']=p.get('basis','basic')
        id=db.execute('INSERT INTO suite_rates(payload) VALUES(?)',(json.dumps(p),)).lastrowid
        return jsonify(id=id,**p),201

@suite.route('/api/claims',methods=['GET','POST'])
def claims():
    with database() as db:
        if request.method=='GET':
            return jsonify([dict(id=r['id'],status=r['status'],payload=json.loads(r['payload']),calculation=json.loads(r['calculation'])) for r in db.execute('SELECT * FROM suite_claims ORDER BY id DESC')])
        p=request.get_json() or {}
        if not p.get('employee_code') or not p.get('allowance'):raise ValueError('Employee and allowance required')
        from datetime import date
        p['employee_code']=str(p['employee_code']).strip().upper()
        p['allowance']=str(p['allowance']).strip().upper()
        p['start']=date.fromisoformat(p['start']).isoformat()
        p['end']=date.fromisoformat(p['end']).isoformat()
        try:r=calculate_claim(p['start'],p['end'],p['segments'])
        except KeyError as e:raise ValueError('Missing claim input: '+str(e)) from None
        id=db.execute('INSERT INTO suite_claims(payload,calculation) VALUES(?,?)',(json.dumps(p),json.dumps(r))).lastrowid
        return jsonify(id=id,calculation=r),201

@suite.post('/api/claims/<int:id>/finalize')
def finalize(id):
    p=request.get_json() or {}
    if p.get('reviewed') is not True or not p.get('rule_reference') or not p.get('drawn_reference'):
        raise ValueError('Confirm reviewed inputs and provide rate/order and drawn-payment references')
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM suite_claims WHERE id=?',(id,)).fetchone()
        if not row:return jsonify(error='Claim not found'),404
        if row['status']=='finalized':return jsonify(status='finalized')
        payload=json.loads(row['payload'])
        for other in db.execute("SELECT payload FROM suite_claims WHERE status='finalized'"):
            q=json.loads(other['payload'])
            if str(q['employee_code']).strip().upper()==payload['employee_code'] and str(q['allowance']).strip().upper()==payload['allowance'] and q['start']<=payload['end'] and payload['start']<=q['end']:
                raise ValueError('Overlapping finalized claim: review prior claim before finalizing')
        db.execute("UPDATE suite_claims SET status='finalized',review=? WHERE id=?",(json.dumps(p),id))
    return jsonify(status='finalized')

@suite.get('/api/claims/<int:id>/<kind>')
def export_claim(id,kind):
    with database() as db:r=db.execute('SELECT * FROM suite_claims WHERE id=?',(id,)).fetchone()
    if not r:return jsonify(error='Claim not found'),404
    p,c=json.loads(r['payload']),json.loads(r['calculation'])
    review=json.loads(r['review'] or '{}')
    p.update({k:review[k] for k in ('rule_reference','drawn_reference') if k in review});p['status']=r['status']
    if kind=='excel':b=exports.excel(p,c);ext='xlsx';mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    elif kind=='pdf':b=exports.pdf(p,c);ext='pdf';mime='application/pdf'
    else:return jsonify(error='Unknown export format'),404
    return send_file(b,as_attachment=True,download_name=f'claim-{id}-{r["status"]}.{ext}',mimetype=mime)

@suite.route('/api/imports',methods=['GET','POST'])
def imports():
    with database() as db:
        if request.method=='GET':return jsonify([dict(id=r['id'],filename=r['filename'],status=r['status'],payload=json.loads(r['payload'])) for r in db.execute('SELECT * FROM suite_imports ORDER BY id DESC')])
        f=request.files.get('file')
        if not f:raise ValueError('Select a PDF')
        data=f.read(50*1024*1024+1)
        if len(data)>50*1024*1024:raise ValueError('PDF exceeds 50 MB')
        if not data.startswith(b'%PDF'):raise ValueError('Expected PDF file')
        digest=hashlib.sha256(data).hexdigest()
        existing=db.execute('SELECT id FROM suite_imports WHERE sha256=?',(digest,)).fetchone()
        if existing:return jsonify(id=existing['id'],duplicate=True)
        import pymupdf
        doc=pymupdf.open(stream=data,filetype='pdf');pages=[p.get_text() for p in doc];doc.close()
        kind=request.form.get('kind','ga55');payload=dict(kind=kind,pages=pages,requires_review=True)
        folder=Path(current_app.config['UPLOAD_FOLDER'])/'suite';folder.mkdir(parents=True,exist_ok=True);path=folder/(digest+'.pdf');path.write_bytes(data)
        if kind=='outer':
            from outer_engine.parser import extract_pdf_data
            payload['extracted']=extract_pdf_data(str(path),f.filename)
        if kind=='ga55':
            from .documents import parse_ga55
            payload['ga55']=parse_ga55(pages)
        payload['scan_pages']=[i+1 for i,t in enumerate(pages) if len(t.strip())<20]
        if payload['scan_pages']:payload['notice']='Scanned pages require OCR and review; no amounts inferred.'
        id=db.execute('INSERT INTO suite_imports(sha256,filename,payload) VALUES(?,?,?)',(digest,Path(f.filename).name,json.dumps(payload))).lastrowid
        return jsonify(id=id,payload=payload),201

@suite.post('/api/group_import')
def group_import():
    p=request.get_json() or {};records=p.get('records',[])
    if not isinstance(records,list) or len(records)>100000:raise ValueError('Invalid group records')
    groups={}
    for row in records:
        code=str(row.get('employeeCode') or row.get('employee_code') or '').strip()
        if code:groups.setdefault(code,[]).append(row)
    conflicts=sum(len({json.dumps(r,sort_keys=True) for r in rows})>1 for rows in groups.values())
    with database() as db:
        id=db.execute('INSERT INTO suite_group_imports(payload) VALUES(?)',(json.dumps(p),)).lastrowid
    return jsonify(id=id,rows=len(records),identified=len(groups),conflicts=conflicts,status='needs_review'),201

@suite.post('/api/imports/<int:id>/ocr')
def ocr_import(id):
    from .documents import ocr_pages,parse_ga55
    with database() as db:
        row=db.execute('SELECT * FROM suite_imports WHERE id=?',(id,)).fetchone()
        if not row:return jsonify(error='Import not found'),404
        if row['status']=='reviewed':raise ValueError('Reviewed imports are immutable; OCR cannot replace approved evidence')
        path=Path(current_app.config['UPLOAD_FOLDER'])/'suite'/(row['sha256']+'.pdf')
        pages=ocr_pages(path.read_bytes(),(request.get_json() or {}).get('language','eng'))
        payload=json.loads(row['payload']);payload['pages']=pages;payload['ocr_used']=True
        if payload['kind']=='ga55':payload['ga55']=parse_ga55(pages)
        payload['notice']='OCR output requires source review, including digits, signs and dates.'
        db.execute("UPDATE suite_imports SET payload=?,status='needs_review' WHERE id=?",(json.dumps(payload),id))
    return jsonify(payload)

@suite.post('/api/imports/<int:id>/review')
def review_import(id):
    from .calculation import money
    from datetime import date
    p=request.get_json() or {};payments=p.get('payments',[])
    if p.get('reviewed') is not True or not payments or not p.get('employee_code'):
        raise ValueError('Employee identity, reviewed payments and explicit source confirmation are required')
    for payment in payments:
        if not payment.get('bill_no') or not payment.get('pay_month') or not payment.get('bill_type'):
            raise ValueError('Payment requires bill number, month and type')
        date.fromisoformat(payment['pay_month']+'-01')
        for amounts in [payment.get('allowances',{}),payment.get('deductions',{})]:
            for v in amounts.values():money(v)
    with database() as db:
        row=db.execute('SELECT status FROM suite_imports WHERE id=?',(id,)).fetchone()
        if not row:return jsonify(error='Import not found'),404
        if row['status']=='reviewed':raise ValueError('Import already reviewed; preserve existing payment history')
        for payment in payments:
            db.execute('INSERT INTO suite_payments(import_id,employee_code,payload) VALUES(?,?,?)',(id,p['employee_code'],json.dumps(payment,sort_keys=True)))
        db.execute("UPDATE suite_imports SET status='reviewed' WHERE id=?",(id,))
    return jsonify(status='reviewed',payments=len(payments))

@suite.get('/api/payments')
def payments():
    with database() as db:
        rows=db.execute('SELECT * FROM suite_payments WHERE employee_code=?',(request.args.get('employee_code',''),)).fetchall()
    return jsonify([dict(id=r['id'],import_id=r['import_id'],employee_code=r['employee_code'],**json.loads(r['payload'])) for r in rows])


def register_suite(app):
    with app.app_context():initialize()
    app.register_blueprint(suite)
