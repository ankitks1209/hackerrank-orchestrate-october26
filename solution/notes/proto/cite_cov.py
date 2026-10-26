"""Critic prototype: predicted status from activity oracle + citability of each step (text mention by id in a
file captured within [reported_at, audit_at]). Rough coverage estimate for eval."""
import json, os, csv, collections, re
HERE = os.path.dirname(os.path.abspath(__file__)); NOTES = os.path.dirname(HERE)
DS = os.path.join(os.path.dirname(os.path.dirname(NOTES)), 'dataset')
ca = json.load(open(os.path.join(HERE, 'case_account_candidates.json')))
cw = json.load(open(os.path.join(HERE, 'case_worker_resources.json')))
acts = list(csv.DictReader(open(os.path.join(DS, 'system_activity.csv'))))
first = {}
for a in acts:
    if a['source_system'] == 'deletion_worker' and not a['details'].startswith('Deletion worker submitted'): first.setdefault(a['resource_id'], a)
repl = {a['resource_id'] for a in acts if a['details'].startswith('Replication worker')}
man = list(csv.DictReader(open(os.path.join(DS, 'evidence_files.csv'))))
text = {}
for r in man:
    if not r['file_path'].endswith(('png', 'pdf')): text[r['file_id']] = open(os.path.join(DS, r['file_path']), errors='ignore').read()
reqs = [r for r in csv.DictReader(open(os.path.join(DS, 'deletion_requests.csv')))]
st = collections.Counter(); per = collections.Counter()
for r in reqs:
    c = r['case_id']
    if 'non-deletion' in r['request_text'] or c in ('case_%d' % i for i in range(533, 543)):
        st['NOT_APPLICABLE'] += 1; continue
    accs = ca.get(c, [])
    if len(accs) != 1: st['unresolved-account(%d)' % len(accs)] += 1; continue
    acc = accs[0]
    rows = [first[x] for x in cw.get(c, []) if x in first and first[x]['event_time'] <= r['audit_at']]
    viol = [x for x in rows if not x['details'].startswith('Policy action')] or (acc in repl)
    status = 'INCOMPLETE' if viol else 'COMPLETE'
    st[status] += 1
    if status == 'COMPLETE':
        win = [f['file_id'] for f in man if r['reported_at'] <= f['captured_at'] <= r['audit_at'] and f['file_id'] in text]
        for rid in [acc] + [x['resource_id'] for x in rows]:
            ok = any(re.search(r'\b%s\b' % rid, text[f]) for f in win)
            per[(rid.split('_')[0], 'cited' if ok else ('no-window-file' if not win else 'not-mentioned'))] += 1
print(sorted(st.items())); print(sorted(per.items()))

print('== violating resources citability (text mention by id)')
img = {'account_5762','search_428','data_flow_1121','analytics_7438','export_1260','support_1034','backup_9287','object_19','marketing_001','export_1842','audit_record_003','tombstone_17'}
vc = collections.Counter(); miss = []
for r in reqs:
    c = r['case_id']; accs = ca.get(c, [])
    rows = [first[x] for x in cw.get(c, []) if x in first and first[x]['event_time'] <= r['audit_at']]
    vrs = [x['resource_id'] for x in rows if not x['details'].startswith('Policy action')]
    if len(accs) == 1 and accs[0] in repl: vrs.append(accs[0])
    for rid in vrs:
        inwin = [f['file_id'] for f in man if f['file_id'] in text and r['reported_at'] <= f['captured_at'] <= r['audit_at'] and re.search(r'\b%s\b' % rid, text[f['file_id']])]
        early = [f['file_id'] for f in man if f['file_id'] in text and f['captured_at'] < r['reported_at'] and re.search(r'\b%s\b' % rid, text[f['file_id']])]
        late = [f['file_id'] for f in man if f['file_id'] in text and f['captured_at'] > r['audit_at'] and re.search(r'\b%s\b' % rid, text[f['file_id']])]
        k = 'in-window' if inwin else ('early-only' if early else ('late-only' if late else 'nowhere'))
        vc[k] += 1
        if k != 'in-window': miss.append((c, rid, k, early, late))
print(sorted(vc.items()))
for m in miss[:25]: print(' ', m)
print('cases affected:', len({m[0] for m in miss}))
multi = collections.Counter(); ex = []
for r in reqs:
    c = r['case_id']
    for rid in cw.get(c, []) + ca.get(c, [])[:1]:
        inwin = [f['file_id'] for f in man if f['file_id'] in text and r['reported_at'] <= f['captured_at'] <= r['audit_at'] and re.search(r'\b%s\b' % rid, text[f['file_id']])]
        multi[len(inwin)] += 1
        if len(inwin) > 1: ex.append((c, rid, inwin))
print('in-window files per resource:', sorted(multi.items())); print(ex[:15])
wc = collections.Counter(); exs = collections.defaultdict(list)
allman = list(csv.DictReader(open(os.path.join(DS, 'evidence_files.csv'))))
for r in reqs:
    win = [f['file_id'] for f in allman if r['reported_at'] <= f['captured_at'] <= r['audit_at']]
    wc[len(win)] += 1; exs[len(win)].append((r['case_id'], win))
print('window files per eval case:', sorted(wc.items()))
for k in sorted(exs):
    if k != 1: print(k, exs[k][:14])
