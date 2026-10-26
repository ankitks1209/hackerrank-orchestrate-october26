"""Critic prototype: seconds fingerprint between a case's account-delete row and its other worker rows."""
import csv, json, os, collections
from datetime import datetime as D
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DS = os.path.join(ROOT, 'dataset')
p = lambda s: D.strptime(s, '%Y-%m-%dT%H:%M:%SZ')
acts = list(csv.DictReader(open(os.path.join(DS, 'system_activity.csv'))))
by = collections.defaultdict(list)
for a in acts: by[a['resource_id']].append(a)
gold = {r['case_id']: json.loads(r['steps_json']) for r in csv.DictReader(open(os.path.join(DS, 'sample_output.csv')))}
req = {r['case_id']: r for r in csv.DictReader(open(os.path.join(DS, 'sample_deletion_requests.csv')))}
dist = collections.Counter()
for cid, steps in gold.items():
    acc = [s['resource_id'] for s in steps if s['system_id'] == 'account_service']
    if not acc: continue
    arow = [a for a in by[acc[0]] if a['details'].startswith('Deletion worker submitted')]
    if not arow: continue
    t0 = p(arow[0]['event_time'])
    for rid in {s['resource_id'] for s in steps} - {acc[0]}:
        for a in by[rid]:
            if a['source_system'] != 'deletion_worker' or p(a['event_time']) > p(req[cid]['audit_at']): continue
            d = (p(a['event_time']) - t0).total_seconds()
            kind = 'ok' if a['details'].startswith('Policy action') else 'viol'
            dist[(kind, int(d) % 60)] += 1
            print(cid, kind, rid, a['event_time'], 'delta_s', int(d), 'mod60', int(d) % 60)
print(sorted(dist.items()))
