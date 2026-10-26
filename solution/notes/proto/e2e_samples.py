"""Critic prototype: end-to-end reproduction of sample gold for the generated family using
activity-oracle + evidence-mention citation. Hand-crafted family (01,02,04-08,10) is out of scope."""
import json, os, csv, collections, re
HERE = os.path.dirname(os.path.abspath(__file__)); NOTES = os.path.dirname(HERE)
DS = os.path.join(os.path.dirname(os.path.dirname(NOTES)), 'dataset')
import importlib.util
spec = importlib.util.spec_from_file_location('emit', os.path.join(HERE, 'emit_check.py')); E = importlib.util.module_from_spec(spec); spec.loader.exec_module(E)
ca = json.load(open(os.path.join(HERE, 'case_account_candidates.json')))
cw = json.load(open(os.path.join(HERE, 'case_worker_resources.json')))
acts = list(csv.DictReader(open(os.path.join(DS, 'system_activity.csv'))))
first = {}
for a in acts:
    if a['source_system'] == 'deletion_worker' and not a['details'].startswith('Deletion worker submitted'): first.setdefault(a['resource_id'], a)
repl = {a['resource_id'] for a in acts if a['details'].startswith('Replication worker')}
repop = collections.defaultdict(set)
for a in acts:
    if 'repopulated' in a['details']: repop[re.search(r'search_\d+', a['details']).group(0)].add(a['resource_id'])
man = list(csv.DictReader(open(os.path.join(DS, 'evidence_files.csv'))))
text = {f['file_id']: open(os.path.join(DS, f['file_path']), errors='ignore').read() for f in man if not f['file_path'].endswith(('png', 'pdf'))}
email2u = {u['email'].lower(): u['user_id'] for u in csv.DictReader(open(os.path.join(DS, 'user_identities.csv')))}
for a in csv.DictReader(open(os.path.join(DS, 'user_audit_log.csv'))):
    if a['field_name'] == 'email': email2u[a['old_value'].lower()] = a['user_id']
# audit records by user (any capture time) from analyzer observations
aud = collections.defaultdict(set)
for r in csv.DictReader(open(os.path.join(NOTES, 'records_observations.tsv')), delimiter='\t'):
    if r['resource_id'].startswith('audit_record'):
        for u in filter(None, r['matched_users'].split(',')): aud[u].add(r['resource_id'])
for o in json.load(open(os.path.join(NOTES, 'scripts', 'log_observations.json'))):
    if o['resource_id'].startswith('audit_record'):
        for l in o['links']:
            if l[2]: aud[l[2]].add(o['resource_id'])
for line in open(os.path.join(NOTES, '01_sql_rows_annotated.txt')):
    m = re.match(r'\s+(audit_record_\d+)\s.*\| users=([\w,]+)', line)
    if m and m.group(2) != '-':
        for u in m.group(2).split(','): aud[u].add(m.group(1))
TT = {'DELETE_RECORD': 'DELETE', 'REDACT_RECORD': 'REDACT', 'ANONYMIZE_RECORD': 'ANONYMIZE', 'CHECK_DATA_FLOW': 'FLOW', 'DISABLE_DATA_FLOW': 'FLOW',
      'CHECK_RESTORE_ACCESS': 'RESTORE', 'BLOCK_RESTORE': 'RESTORE', 'RETAIN_RECORD': 'RETAIN'}
def build(r):
    c = r['case_id']; u = email2u[r['email'].lower()]
    accs = ca.get(c, [])
    if len(accs) != 1: return None
    win = [f['file_id'] for f in man if f['file_id'] in text and r['reported_at'] <= f['captured_at'] <= r['audit_at']]
    def cite(rid):
        h = [f for f in win if re.search(r'\b%s\b' % rid, text[f])]
        return h[-1] if h else ''
    res = []
    rows = [first[x] for x in cw.get(c, []) if x in first and first[x]['event_time'] <= r['audit_at']]
    for a in rows:
        res.append(dict(system=a['target_system'], rid=a['resource_id'], treat=TT[a['event_type']], violating=not a['details'].startswith('Policy action'), cite=cite(a['resource_id'])))
        for f in repop.get(a['resource_id'], ()):  # flows that repopulated this search
            if not any(x['rid'] == f for x in res): res.append(dict(system='integration_service', rid=f, treat='FLOW', violating=True, cite=cite(f)))
    acc = accs[0]
    used = {x['cite'] for x in res if x['cite']}
    acite = cite(acc) or (sorted(used)[-1] if used else (win[-1] if win else ''))
    res.append(dict(system='account_service', rid=acc, treat='DELETE', violating=acc in repl, cite=acite))
    for a in sorted(aud.get(u, ())):
        res.append(dict(system='security_service', rid=a, treat='RETAIN', violating=False, cite=cite(a)))
    return E.emit(res)
gold = {r['case_id']: (r['deletion_status'], json.loads(r['steps_json'])) for r in csv.DictReader(open(os.path.join(DS, 'sample_output.csv')))}
reqs = list(csv.DictReader(open(os.path.join(DS, 'sample_deletion_requests.csv'))))
ok = 0; tot = 0; st_ok = 0
for r in reqs:
    out = build(r)
    if out is None: continue
    tot += 1; g = gold[r['case_id']]
    st_ok += out[0] == g[0]
    if out == g: ok += 1
    else:
        gs = {(s['phase'], s['operation'], s['resource_id'], s['evidence_id']) for s in g[1]}
        os_ = {(s['phase'], s['operation'], s['resource_id'], s['evidence_id']) for s in out[1]}
        print(r['case_id'], out[0], g[0], 'missing', sorted(gs - os_), 'extra', sorted(os_ - gs))
print(f'generated-family samples: exact {ok}/{tot}, status {st_ok}/{tot}')
ev = list(csv.DictReader(open(os.path.join(DS, 'deletion_requests.csv'))))
dist = collections.Counter(); nocite = 0; unres = []
for r in ev:
    if r['case_id'] in {'case_%d' % i for i in range(533, 543)}: dist['NOT_APPLICABLE'] += 1; continue
    out = build(r)
    if out is None: dist['unresolved'] += 1; unres.append(r['case_id']); continue
    dist[out[0]] += 1
    nocite += sum(1 for s in out[1] if s['phase'] == 'FINDING' and not s['evidence_id']) + (sum(1 for s in out[1] if not s['evidence_id']) if out[0] == 'COMPLETE' else 0)
print('eval predicted:', dict(dist), 'steps needing evidence but uncited:', nocite)
print('unresolved:', unres)
print('== COMPLETE eval cases whose account id is not in any window file (absent by omission)')
cc = collections.Counter()
for r in ev:
    out = build(r)
    if not out or out[0] != 'COMPLETE': continue
    acc = ca[r['case_id']][0]
    win = [f['file_id'] for f in man if f['file_id'] in text and r['reported_at'] <= f['captured_at'] <= r['audit_at']]
    if not any(re.search(r'\b%s\b' % acc, text[f]) for f in win):
        s = [x for x in out[1] if x['resource_id'] == acc][0]
        others = sorted({x['evidence_id'] for x in out[1] if x['resource_id'] != acc})
        cc[(s['evidence_id'], tuple(others))] += 1
for k, v in sorted(cc.items()): print(' ', v, 'account cites', k[0], '| other steps cite', k[1])
