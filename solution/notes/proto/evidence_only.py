"""Critic prototype: violating evidence observations (in-window, user-linked) not explained by the case's
activity-derived resource set (worker rows + repopulated flows + account replication)."""
import json, os, csv, collections, re
HERE = os.path.dirname(os.path.abspath(__file__)); NOTES = os.path.dirname(HERE)
DS = os.path.join(os.path.dirname(os.path.dirname(NOTES)), 'dataset')
acts = list(csv.DictReader(open(os.path.join(DS, 'system_activity.csv'))))
cw = json.load(open(os.path.join(HERE, 'case_worker_resources.json')))
ca = json.load(open(os.path.join(HERE, 'case_account_candidates.json')))
reqs = {r['case_id']: r for f in ('sample_deletion_requests.csv', 'deletion_requests.csv') for r in csv.DictReader(open(os.path.join(DS, f)))}
email2u = {u['email'].lower(): u['user_id'] for u in csv.DictReader(open(os.path.join(DS, 'user_identities.csv')))}
for a in csv.DictReader(open(os.path.join(DS, 'user_audit_log.csv'))):
    if a['field_name'] == 'email': email2u[a['old_value'].lower()] = a['user_id']
u2c = collections.defaultdict(list)
for c, r in reqs.items(): u2c[email2u[r['email'].lower()]].append(c)
known = collections.defaultdict(set)
for c, rs in cw.items(): known[c] |= set(rs)
for c, rs in ca.items(): known[c] |= set(rs)
s2c = {r: c for c, rs in cw.items() for r in rs}
for a in acts:
    if 'repopulated' in a['details']:
        s = re.search(r'search_\d+', a['details']).group(0)
        if s in s2c: known[s2c[s]].add(a['resource_id'])
obs = []
for o in json.load(open(os.path.join(NOTES, 'scripts', 'log_observations.json'))):
    if o.get('cls') in ('PRESENT', 'EXPOSED', 'ACTIVE', 'RESTORE_ACTIVE', 'ATTACHMENT_PRESENT', 'IDENTIFIABLE', 'PRESENT_MARKETING_CONTACT'):
        for l in o['links']:
            if l[2]: obs.append((o['resource_id'], l[2], o['captured_at'], o['ts'], o['file_id'], o['cls']))
for r in csv.DictReader(open(os.path.join(NOTES, 'records_observations.tsv')), delimiter='\t'):
    if r['state'] in ('PRESENT', 'IDENTIFIABLE', 'ACTIVE', 'EXPOSED') and not r['resource_id'].startswith(('audit_record', 'legal_hold')):
        for u in filter(None, r['matched_users'].split(',')): obs.append((r['resource_id'], u, r['file_captured_at'], r['entry_time'], r['file_id'], r['state']))
st = collections.Counter(); out = set()
for rid, u, cap, ts, fid, cls in obs:
    for c in u2c.get(u, []):
        r = reqs[c]
        if not (r['reported_at'] <= cap <= r['audit_at'] and ts <= r['audit_at']): continue
        if rid in known[c]: st['explained'] += 1
        else: st['UNEXPLAINED'] += 1; out.add((c, rid, fid, cls))
print(st)
for o in sorted(out): print(' ', o)
