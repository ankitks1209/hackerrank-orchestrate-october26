#!/usr/bin/env python3
"""List evidence emails/phones that are near-duplicates (decoys) of a case subject's identifiers."""
import csv, os, re, sys, difflib
D = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'dataset')
man = list(csv.DictReader(open(os.path.join(D, 'evidence_files.csv'))))
ids = {u['email'].lower(): u for u in csv.DictReader(open(os.path.join(D, 'user_identities.csv')))}
req = {r['case_id']: r for r in csv.DictReader(open(os.path.join(D, 'sample_deletion_requests.csv')))}
em = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+')
ph = re.compile(r'\+\d[\d \-]{7,16}\d')
occ = {}
for m in man:
    if m['file_path'].endswith(('.png', '.pdf')): continue
    t = open(os.path.join(D, m['file_path']), encoding='utf-8').read()
    for x in set(em.findall(t)) | set(ph.findall(t)):
        occ.setdefault(x.lower(), set()).add(m['file_id'])
act = open(os.path.join(D, 'system_activity.csv'), encoding='utf-8').read()
for x in set(em.findall(act)): occ.setdefault(x.lower(), set()).add('system_activity')
for cid in sys.argv[1:]:
    r = req[cid]; u = ids[r['email'].lower()]
    print(cid, u['user_id'], u['email'], u['phone'])
    for tgt in (u['email'].lower(), u['phone']):
        for x, fs in sorted(occ.items()):
            if x == tgt.lower(): continue
            if difflib.SequenceMatcher(None, x, tgt.lower()).ratio() >= 0.8:
                owner = ids.get(x, {}).get('user_id', 'UNKNOWN/not-current')
                print(f"   near {tgt} ~ {x} owner={owner} in {sorted(fs)}")
