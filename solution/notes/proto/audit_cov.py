"""Critic prototype: how many eval cases have a discoverable security audit record (any capture time)."""
import json, os, csv, collections, re, glob
HERE = os.path.dirname(os.path.abspath(__file__)); NOTES = os.path.dirname(HERE)
DS = os.path.join(os.path.dirname(os.path.dirname(NOTES)), 'dataset')
email2u = {u['email'].lower(): u['user_id'] for u in csv.DictReader(open(os.path.join(DS, 'user_identities.csv')))}
for a in csv.DictReader(open(os.path.join(DS, 'user_audit_log.csv'))):
    if a['field_name'] == 'email': email2u[a['old_value'].lower()] = a['user_id']
reqs = list(csv.DictReader(open(os.path.join(DS, 'deletion_requests.csv'))))
man = {r['file_id']: r for r in csv.DictReader(open(os.path.join(DS, 'evidence_files.csv')))}
aud = collections.defaultdict(set)  # user -> {(audit_id, file, captured)}
for fid, r in man.items():
    pth = os.path.join(DS, r['file_path'])
    if pth.endswith(('png', 'pdf')): continue
    for line in open(pth, errors='ignore'):
        for m in re.finditer(r'audit_record_\d+', line):
            us = set(re.findall(r'user_\d+', line))
            for u in us: aud[u].add((m.group(0), fid, r['captured_at']))
# log traces: audit record lines keyed by trace -> use analyzer observations
for o in json.load(open(os.path.join(NOTES, 'scripts', 'log_observations.json'))):
    if o['resource_id'].startswith('audit_record'):
        for l in o['links']:
            if l[2]: aud[l[2]].add((o['resource_id'], o['file_id'], o['captured_at']))
for r in csv.DictReader(open(os.path.join(NOTES, 'records_observations.tsv')), delimiter='\t'):
    if r['resource_id'].startswith('audit_record'):
        for u in filter(None, r['matched_users'].split(',')): aud[u].add((r['resource_id'], r['file_id'], r['file_captured_at']))
for line in open(os.path.join(NOTES, '01_sql_rows_annotated.txt')):
    m = re.match(r'\s+(audit_record_\d+)\s.*\| users=([\w,]+)', line)
    cur = None
st = collections.Counter(); multi = []
for r in reqs:
    u = email2u[r['email'].lower()]
    s = aud.get(u, set()); ids = {x[0] for x in s}
    pre = {x[0] for x in s if r['reported_at'] <= x[2] <= r['audit_at']}
    st[('n_ids=%d' % min(len(ids), 2), 'citable' if pre else 'late-only' if ids else 'none')] += 1
    if len(ids) > 1: multi.append((r['case_id'], u, sorted(s)))
print(sorted(st.items()))
for m in multi[:12]: print(' ', m)
none = [r for r in reqs if not aud.get(email2u[r['email'].lower()])]
byaudit = collections.defaultdict(list)
for r in none: byaudit[r['audit_at']].append(r['case_id'])
for k in sorted(byaudit): print(' none', k, byaudit[k])
