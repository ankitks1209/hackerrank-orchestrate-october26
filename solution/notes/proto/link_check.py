"""Critic prototype: link deletion-worker activity rows to cases by timing; measure ambiguity."""
import csv, json, os, re, collections
from datetime import datetime as D, timedelta as T
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DS = os.path.join(ROOT, 'dataset')
p = lambda s: D.strptime(s, '%Y-%m-%dT%H:%M:%SZ')
acts = list(csv.DictReader(open(os.path.join(DS, 'system_activity.csv'))))
reqs = list(csv.DictReader(open(os.path.join(DS, 'sample_deletion_requests.csv')))) + list(csv.DictReader(open(os.path.join(DS, 'deletion_requests.csv'))))
gold = {r['case_id']: json.loads(r['steps_json']) for r in csv.DictReader(open(os.path.join(DS, 'sample_output.csv')))}
MAP = {'COMPLETE': 'SUCCESS', 'PARTIALLY_COMPLETE': 'PARTIAL', 'NOT_STARTED': 'FAILED'}
accrows = [a for a in acts if a['target_system'] == 'account_service' and a['event_type'] == 'DELETE_RECORD' and a['source_system'] == 'deletion_worker']
worker = [a for a in acts if a['source_system'] == 'deletion_worker' or a['details'].startswith(('Connector status check', 'Restore-access check', 'Replication worker'))]
def offs(r, a): return (p(a['event_time']) - p(r['reported_at'])).total_seconds() / 3600
# 1. offsets of gold-linked rows in samples
print('== sample: activity rows for gold resources, offset hours vs reported_at')
for r in reqs[:32]:
    rids = {s['resource_id'] for s in gold[r['case_id']]}
    hits = [(a['activity_id'], a['event_type'], a['resource_id'], a['reported_result'], round(offs(r, a), 2)) for a in acts if a['resource_id'] in rids and p(a['event_time']) <= p(r['audit_at']) and a['event_type'] != 'LINK_RESOURCE_IDENTITY']
    print(r['case_id'], r['reported_status'], hits)
# 2. account candidate ambiguity
print('== account candidates by window [-1.25h,-0.75h] + result mirror')
cnt = collections.Counter(); amb = []
for r in reqs:
    if 'non-deletion' in r['request_text']: pass
    c = [a for a in accrows if -1.26 <= offs(r, a) <= -0.74 and a['reported_result'] == MAP[r['reported_status']]]
    c2 = [a for a in accrows if -1.26 <= offs(r, a) <= -0.74]
    cnt[len(c)] += 1
    if r['case_id'] <= 'case_32' and len(r['case_id']) == 7 and int(r['case_id'][5:]) <= 32:
        g = [s['resource_id'] for s in gold[r['case_id']] if s['system_id'] == 'account_service']
        print(r['case_id'], 'gold', g, 'cands', [a['resource_id'] for a in c], 'nomirror', [a['resource_id'] for a in c2])
print('candidate-count histogram (all 550):', sorted(cnt.items()))
