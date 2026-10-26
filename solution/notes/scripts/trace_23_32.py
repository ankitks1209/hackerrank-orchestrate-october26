import csv, os, re, sys, json, zlib
ROOT=os.path.join(os.path.dirname(__file__),'..','..','..','dataset')
ROOT=os.path.abspath(ROOT)
man={r['file_path']:r for r in csv.DictReader(open(os.path.join(ROOT,'evidence_files.csv')))}
texts={}
for p,r in man.items():
    fp=os.path.join(ROOT,p)
    if p.endswith(('.png',)): continue
    b=open(fp,'rb').read()
    if p.endswith('.pdf'):
        out=[]
        for m in re.finditer(rb'stream\r?\n(.*?)\r?\nendstream',b,re.S):
            try: out.append(zlib.decompress(m.group(1)).decode('latin1'))
            except Exception: pass
        t='\n'.join(out)
        # extract text in parens Tj
        t=' '.join(re.findall(r'\((.*?)\)\s*Tj',t)) or t
    else:
        t=b.decode('utf-8','replace')
    texts[r['file_id']]=(p,r['captured_at'],t)
acts=list(csv.DictReader(open(os.path.join(ROOT,'system_activity.csv'))))
terms=sys.argv[1:]
for term in terms:
    print('#### TERM',term)
    pat=re.compile(r'(?<![A-Za-z0-9_.])'+re.escape(term)+r'(?![0-9A-Za-z_])',re.I) if re.match(r'^[a-z_]+_\d+$',term) else re.compile(re.escape(term),re.I)
    for fid,(p,cap,t) in sorted(texts.items(),key=lambda x:int(x[0].split('_')[1])):
        lines=[l for l in t.splitlines() if pat.search(l)]
        if lines:
            print(f'  {fid} {p} cap={cap} hits={len(lines)}')
            for l in lines[:6]: print('     ',l.strip()[:220])
    for a in acts:
        if any(pat.search(v or '') for v in a.values()):
            print('  ACT',a['activity_id'],a['event_time'],a['event_type'],a['source_system'],'->',a['target_system'],a['resource_id'],a['reported_result'],'|',a['details'][:160])
