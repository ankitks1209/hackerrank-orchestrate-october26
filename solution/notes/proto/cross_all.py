"""Critic prototype: compare activity-template class with log + records observations (any capture time,
latest observation per resource at or before audit_at)."""
import json, os, csv, collections
HERE = os.path.dirname(os.path.abspath(__file__)); NOTES = os.path.dirname(HERE)
DS = os.path.join(os.path.dirname(os.path.dirname(NOTES)), 'dataset')
acts = {}
for a in csv.DictReader(open(os.path.join(DS, 'system_activity.csv'))):
    if a['source_system'] == 'deletion_worker' and not a['details'].startswith('Deletion worker submitted') or a['details'].startswith('Active connector repopulated'):
        acts.setdefault(a['resource_id'], a)
man = {r['file_id']: r['captured_at'] for r in csv.DictReader(open(os.path.join(DS, 'evidence_files.csv')))}
cw = json.load(open(os.path.join(HERE, 'case_worker_resources.json')))
reqs = {r['case_id']: r for f in ('sample_deletion_requests.csv', 'deletion_requests.csv') for r in csv.DictReader(open(os.path.join(DS, f)))}
rid2case = {}
for c, rs in cw.items():
    for r in rs: rid2case.setdefault(r, set()).add(c)
obs = collections.defaultdict(list)  # rid -> (capture, entry_time, viol?, src)
VIOL_LOG = {'PRESENT', 'EXPOSED', 'ACTIVE', 'RESTORE_ACTIVE', 'ATTACHMENT_PRESENT', 'IDENTIFIABLE'}
OKS = {'REDACTED', 'DISABLED', 'BLOCKED', 'ANONYMIZED', 'ABSENT'}
for o in json.load(open(os.path.join(NOTES, 'scripts', 'log_observations.json'))):
    c = o.get('cls')
    if c in VIOL_LOG: v = True
    elif c in OKS: v = False
    else: continue
    obs[o['resource_id']].append((o['captured_at'], o['ts'], v, o['file_id'] + ':' + c))
for r in csv.DictReader(open(os.path.join(NOTES, 'records_observations.tsv')), delimiter='\t'):
    s = r['state']
    if s in ('PRESENT', 'IDENTIFIABLE', 'ACTIVE', 'EXPOSED', 'FOUND'): v = True
    elif s in ('ABSENT', 'REDACTED', 'ANONYMIZED', 'DISABLED', 'BLOCKED'): v = False
    else: continue
    obs[r['resource_id']].append((r['file_captured_at'], r['entry_time'], v, r['file_id'] + ':' + s))
st = collections.Counter(); bad = []
for rid, a in acts.items():
    if rid not in obs or rid not in rid2case or len(rid2case[rid]) != 1: continue
    case = next(iter(rid2case[rid])); audit = reqs[case]['audit_at']; rep = reqs[case]['reported_at']
    av = not a['details'].startswith('Policy action')
    pre = sorted(x for x in obs[rid] if x[0] <= audit and x[1] <= audit and x[0] >= rep)
    if not pre:
        st['no in-window obs'] += 1; continue
    last = pre[-1]
    st['agree' if last[2] == av else 'disagree'] += 1
    if last[2] != av: bad.append((case, rid, a['details'][:45], pre))
print(st)
for b in bad[:30]: print(' ', b)
