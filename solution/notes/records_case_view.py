#!/usr/bin/env python3
"""Per-case view of records-family evidence: which observations are citable at audit_at
(file captured_at <= audit_at AND entry_time <= audit_at) vs only visible in later files.
Run after records_normalize.py. Output: records_case_view.txt"""
import csv, collections, os
H = os.path.dirname(os.path.abspath(__file__)); D = os.path.join(H, '..', '..', 'dataset')
rows = list(csv.DictReader(open(os.path.join(H, 'records_observations.tsv')), delimiter='\t'))
ids = {r['user_id']: r for r in csv.DictReader(open(os.path.join(D, 'user_identities.csv')))}
e2u = {r['email'].lower(): u for u, r in ids.items()}
for a in csv.DictReader(open(os.path.join(D, 'user_audit_log.csv'))):
    if a['field_name'] == 'email':
        e2u.setdefault(a['old_value'].lower(), a['user_id']); e2u.setdefault(a['new_value'].lower(), a['user_id'])
gold = {}
if os.path.exists(os.path.join(D, 'sample_output.csv')):
    gold = {r['case_id']: r['deletion_status'] for r in csv.DictReader(open(os.path.join(D, 'sample_output.csv')))}
byuser = collections.defaultdict(list)
for r in rows:
    for u in r['matched_users'].split(';'):
        if u: byuser[u].append(r)
FIND = {('PRESENT', 'USER_PROFILE'): 'REMAINING', ('PRESENT', 'SEARCH_INDEX_ENTRY'): 'REMAINING', ('PRESENT', 'USER_EXPORT'): 'REMAINING',
        ('PRESENT', 'SUPPORT_ATTACHMENT'): 'REMAINING', ('IDENTIFIABLE', 'ANALYTICS_PROFILE'): 'EXPOSED', ('IDENTIFIABLE', 'SUPPORT_MESSAGE'): 'EXPOSED',
        ('IDENTIFIABLE', 'ACCOUNT_TOMBSTONE'): 'EXPOSED', ('ACTIVE', 'DATA_FLOW'): 'ACTIVE_FLOW', ('ACTIVE', 'BACKUP_ARCHIVE'): 'RESTORE_RISK'}
out = []
for fn, kind in [('sample_deletion_requests.csv', 'SAMPLE'), ('deletion_requests.csv', 'EVAL')]:
    for c in csv.DictReader(open(os.path.join(D, fn))):
        u = e2u.get(c['email'].lower()); obs = byuser.get(u, [])
        if not obs: continue
        A = c['audit_at']
        cit, late = {}, []
        for r in sorted(obs, key=lambda r: (r['entry_time'], r['file_captured_at'])):
            ok = r['file_captured_at'] <= A and r['entry_time'] <= A
            if ok: cit[r['resource_id']] = r  # latest citable wins
            else: late.append(r)
        flags = sorted({FIND.get((r['state'], r['category']), '') for r in cit.values()} - {''})
        out.append('%s [%s] %s user=%s email=%s audit=%s reported=%s %s' % (c['case_id'], kind, gold.get(c['case_id'], ''), u, c['email'], A, c['reported_status'],
                   ('violations=' + ','.join(flags)) if flags else 'no-violation-in-records'))
        out.append('   text: ' + c['request_text'][:150])
        for rid, r in sorted(cit.items()):
            out.append('   CITABLE %s %-20s %-18s %-12s %-19s t=%s %s' % (r['file_id'], rid, r['category'], r['state'], r['system'], r['entry_time'], r['detail'][:60]))
        for r in late:
            out.append('   LATER   %s %-20s %-18s %-12s %-19s t=%s (file cap %s) %s' % (r['file_id'], r['resource_id'], r['category'], r['state'], r['system'], r['entry_time'], r['file_captured_at'], r['detail'][:40]))
open(os.path.join(H, 'records_case_view.txt'), 'w').write('\n'.join(out) + '\n')
print(len([l for l in out if not l.startswith('   ')]), 'cases')
