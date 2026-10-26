"""Critic prototype: account remaining vs replication-checkpoint rows."""
import json, os, csv, collections, re
HERE = os.path.dirname(os.path.abspath(__file__)); NOTES = os.path.dirname(HERE)
DS = os.path.join(os.path.dirname(os.path.dirname(NOTES)), 'dataset')
ca = json.load(open(os.path.join(HERE, 'case_account_candidates.json')))
reqs = {r['case_id']: r for f in ('sample_deletion_requests.csv', 'deletion_requests.csv') for r in csv.DictReader(open(os.path.join(DS, f)))}
rep = {a['resource_id']: a for a in csv.DictReader(open(os.path.join(DS, 'system_activity.csv'))) if a['details'].startswith('Replication worker')}
acc2case = {v[0]: c for c, v in ca.items() if len(v) == 1}
obs = collections.defaultdict(list)
for o in json.load(open(os.path.join(NOTES, 'scripts', 'log_observations.json'))):
    if o['resource_id'].startswith('account_') and o.get('cls') in ('PRESENT', 'ABSENT'): obs[o['resource_id']].append((o['captured_at'], o['ts'], o['cls'], o['file_id']))
for r in csv.DictReader(open(os.path.join(NOTES, 'records_observations.tsv')), delimiter='\t'):
    if r['resource_id'].startswith('account_') and r['state'] in ('PRESENT', 'ABSENT'): obs[r['resource_id']].append((r['file_captured_at'], r['entry_time'], r['state'], r['file_id']))
for line in open(os.path.join(NOTES, '01_sql_case_derivations.txt')):
    for ev, rid in re.findall(r'(evidence_\d+) account_service (account_\d+) REMAINING', line):
        obs[rid].append(('sql', 'sql', 'PRESENT', ev))
st = collections.Counter(); out = []
for acc, case in acc2case.items():
    r = reqs[case]; hasrep = acc in rep and rep[acc]['event_time'] <= r['audit_at']
    pre = sorted(x for x in obs.get(acc, []) if x[0] == 'sql' or (r['reported_at'] <= x[0] <= r['audit_at'] and x[1] <= r['audit_at']))
    last = pre[-1][2] if pre else None
    key = (hasrep, last); st[key] += 1
    if (hasrep and last == 'ABSENT') or (not hasrep and last == 'PRESENT'): out.append((case, acc, hasrep, pre))
print(sorted(st.items(), key=str))
for o in out: print(' ', o)
