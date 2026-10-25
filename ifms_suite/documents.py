"""Conservative GA55 text extraction and local OCR. Parsed records require review."""
import re
from decimal import Decimal
MONTHS='January February March April May June July August September October November December'.split()
MONEY=re.compile(r'^[-+]?\d[\d,]*\.\d{2}$')
HEADS={'basic':'Basic','da':'DA','hra':'HRA','cca':'CCA','hda':'HDA','fta':'FTA','mess all':'Mess All','rop':'ROP','bonus':'Bonus','gpf':'GPF','gpf 2004':'GPF 2004','sip':'SIP','sil':'SIL','rghs':'RGHS','lic':'LIC','advance salary':'Advance Salary','gi cc':'GI CC','road ways dedution':'Roadways','road ways deduti on':'Roadways','r p kalyan nidhi':'R P Kalyan Nidhi','sulabh complex':'Sulabh Complex'}
ALLOWANCES={'Basic','DA','HRA','CCA','HDA','FTA','Mess All','ROP','Bonus'}

def parse_ga55(pages):
    tagged=[]
    for i,text in enumerate(pages):
        tagged.extend((line.strip(),i+1) for line in text.splitlines() if line.strip())
    starts=[]
    for i,(line,page) in enumerate(tagged[:-1]):
        if line in MONTHS and re.fullmatch(r'20\d{2}',tagged[i+1][0]):starts.append(i)
    payments=[]
    for n,start in enumerate(starts):
        end=starts[n+1] if n+1<len(starts) else len(tagged)
        part=tagged[start:end]
        # The document summary lists annual amounts, not another payment.
        for k,(line,p) in enumerate(part):
            if line=='Total Allowances':part=part[:k];break
        bill_index=next((k for k,(line,p) in enumerate(part[2:],2) if re.fullmatch(r'\d{9}',line)),None)
        if bill_index is None:continue
        names=' '.join(x for x,p in part[2:bill_index])
        record={'pay_month':f'{part[1][0]}-{MONTHS.index(part[0][0])+1:02d}','bill_type':names,
                'bill_no':part[bill_index][0],'entitlement_period':None,'allowances':{},'deductions':{},
                'source_pages':sorted({p for t,p in part}),'issues':[],'raw_text':'\n'.join(x for x,p in part)}
        pending=[]
        for line,page in part[bill_index+1:]:
            if MONEY.fullmatch(line):
                key=' '.join(pending).lower();head=HEADS.get(key)
                if head:
                    dest=record['allowances'] if head in ALLOWANCES else record['deductions']
                    if head in dest:record['issues'].append('Repeated component '+head)
                    dest[head]=f'{Decimal(line.replace(",","")):.2f}'
                pending=[]
            else:
                pending.append(line)
                # Look only at the shortest known tail; metadata cannot become a head.
                for size in range(1,min(5,len(pending))+1):
                    if ' '.join(pending[-size:]).lower() in HEADS:
                        pending=pending[-size:];break
                if len(pending)>5:pending=pending[-5:]
        if names!='Regular Salary':record['issues'].append('Allocate payment to entitlement period before settling a claim')
        record['issues'].append('Verify component extraction against source and printed totals')
        payments.append(record)
    return {'payments':payments,'requires_review':True,'layout':'GA55 text sequence','notice':'Candidate payment records; verify before use. No entitlement periods inferred from payment months.'}

def ocr_pages(data,language='eng'):
    import io,shutil,subprocess,tempfile
    from pathlib import Path
    import pymupdf
    if language not in ('eng','eng+hin'):raise ValueError('Unsupported OCR language')
    executable=shutil.which('tesseract')
    if not executable:raise ValueError('Local Tesseract is not installed')
    doc=pymupdf.open(stream=data,filetype='pdf');texts=[]
    try:
        for page in doc:
            text=page.get_text()
            if len(text.strip())>=20:texts.append(text);continue
            with tempfile.TemporaryDirectory(prefix='ifms-ocr-') as td:
                path=Path(td)/'page.png';page.get_pixmap(dpi=240).save(path)
                result=subprocess.run([executable,str(path),'stdout','-l',language,'--psm','6'],capture_output=True,text=True,timeout=90)
                if result.returncode:raise ValueError('OCR failed: '+result.stderr[-300:])
                texts.append(result.stdout)
    finally:doc.close()
    return texts
