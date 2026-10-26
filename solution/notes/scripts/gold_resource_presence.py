#!/usr/bin/env python3
"""For every sample gold step, list which participant sources mention its resource_id (text evidence + system_activity)."""
import csv, json, os, re
D = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'dataset')
man = {m['file_id']: m for m in csv.DictReader(open(os.path.join(D, 'evidence_files.csv')))}
txt = {}
for fid, m in man.items():
    if not m['file_path'].endswith(('.png', '.pdf')):
        txt[fid] = open(os.path.join(D, m['file_path']), encoding='utf-8').read()
act = list(csv.DictReader(open(os.path.join(D, 'system_activity.csv'))))
req = {r['case_id']: r for r in csv.DictReader(open(os.path.join(D, 'sample_deletion_requests.csv')))}
for g in csv.DictReader(open(os.path.join(D, 'sample_output.csv'))):
    r = req[g['case_id']]
    print(g['case_id'], g['deletion_status'], 'audit', r['audit_at'])
    seen = set()
    for s in json.loads(g['steps_json']):
        rid = s['resource_id']
        if rid in seen: continue
        seen.add(rid)
        pat = re.compile(r'(?<![\w])' + re.escape(rid) + r'(?![\w])')
        fs = [f"{fid}{'(LATE)' if man[fid]['captured_at'] > r['audit_at'] else ''}" for fid, t in txt.items() if pat.search(t)]
        acts = [f"{a['activity_id']}:{a['event_type']}:{a['reported_result']}{'(LATE)' if a['event_time'] > r['audit_at'] else ''}" for a in act if a['resource_id'] == rid or pat.search(a['details'])]
        print(f"   {s['system_id']:20s} {rid:20s} files={fs} acts={acts}")
