"""Critic prototype: link every deletion-worker resource row to an account-delete row using
window + seconds fingerprint; then link account rows to cases via reported_at window + result mirror.
Reports ambiguity counts and checks against sample gold."""
import csv, json, os, collections
from datetime import datetime as D
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DS = os.path.join(ROOT, 'dataset')
p = lambda s: D.strptime(s, '%Y-%m-%dT%H:%M:%SZ')
acts = list(csv.DictReader(open(os.path.join(DS, 'system_activity.csv'))))
acc = [a for a in acts if a['details'].startswith('Deletion worker submitted primary profile')]
others = [a for a in acts if a['source_system'] == 'deletion_worker' and not a['details'].startswith('Deletion worker submitted') and 'Target resource' not in a['details']]
others += [a for a in acts if a['details'].startswith(('Connector status check', 'Restore-access check'))  and a['source_system'] != 'deletion_worker']
OK = {39, 40, 41, 9, 10, 11}; VI = {20, 21, 22, 50, 51, 52}
link = {}; amb = collections.Counter()
for o in others:
    t = p(o['event_time']); isok = o['details'].startswith('Policy action')
    c = []
    for a in acc:
        d = (t - p(a['event_time'])).total_seconds()
        if isok and 1000 <= d <= 4200 and int(d) % 60 in OK: c.append(a)
        if not isok and 4800 <= d <= 10800 and int(d) % 60 in VI: c.append(a)
    amb[len(c)] += 1
    link[o['activity_id']] = [a['resource_id'] for a in c]
print('worker rows:', len(others), 'candidate-account histogram:', sorted(amb.items()))
gold = {r['case_id']: json.loads(r['steps_json']) for r in csv.DictReader(open(os.path.join(DS, 'sample_output.csv')))}
good = bad = 0
for cid, steps in gold.items():
    accs = {s['resource_id'] for s in steps if s['system_id'] == 'account_service'}
    for o in others:
        if o['resource_id'] in {s['resource_id'] for s in steps}:
            if link[o['activity_id']] == list(accs) or (len(link[o['activity_id']]) == 1 and link[o['activity_id']][0] in accs): good += 1
            else: bad += 1; print('  sample mislink', cid, o['activity_id'], o['resource_id'], link[o['activity_id']], accs)
print('sample gold rows uniquely linked to right account:', good, 'wrong/ambiguous:', bad)
json.dump(link, open(os.path.join(os.path.dirname(__file__), 'worker_row_to_account.json'), 'w'), indent=0)
