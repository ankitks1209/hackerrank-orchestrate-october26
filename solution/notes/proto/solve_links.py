"""Critic prototype: global constraint propagation to bind account-delete rows (and their worker rows)
to cases. Inputs: dataset activity + requests + analyzer observation files (notes/*). stdlib only."""
import csv, json, os, re, collections
from datetime import datetime as D
HERE = os.path.dirname(os.path.abspath(__file__)); NOTES = os.path.dirname(HERE)
DS = os.path.join(os.path.dirname(os.path.dirname(NOTES)), 'dataset')
p = lambda s: D.strptime(s, '%Y-%m-%dT%H:%M:%SZ')
acts = list(csv.DictReader(open(os.path.join(DS, 'system_activity.csv'))))
reqs = list(csv.DictReader(open(os.path.join(DS, 'sample_deletion_requests.csv')))) + list(csv.DictReader(open(os.path.join(DS, 'deletion_requests.csv'))))
# --- user resolution
email2u = {}
for u in csv.DictReader(open(os.path.join(DS, 'user_identities.csv'))): email2u[u['email'].lower()] = u['user_id']
for a in csv.DictReader(open(os.path.join(DS, 'user_audit_log.csv'))):
    if a['field_name'] == 'email': email2u[a['old_value'].lower()] = a['user_id']; email2u[a['new_value'].lower()] = a['user_id']
case_user = {r['case_id']: email2u[r['email'].lower()] for r in reqs}
# --- resource -> users from evidence observations (any capture time; only for linking)
res_users = collections.defaultdict(set)
for line in open(os.path.join(NOTES, '01_sql_rows_annotated.txt')):
    m = re.match(r'\s+(\w+_\d+)\s.*\| users=([\w,]+)', line)
    if m and m.group(2) != '-':
        for u in m.group(2).split(','): res_users[m.group(1)].add(u)
for r in csv.DictReader(open(os.path.join(NOTES, 'records_observations.tsv')), delimiter='\t'):
    for u in filter(None, r['matched_users'].split(',')): res_users[r['resource_id']].add(u)
for o in json.load(open(os.path.join(NOTES, 'scripts', 'log_observations.json'))):
    for l in o['links']:
        if l[2]: res_users[o['resource_id']].add(l[2])
for a in acts:
    if a['event_type'] == 'LINK_RESOURCE_IDENTITY':
        res_users[a['resource_id']].add(re.search(r'(user_\d+)\.?', a['details']).group(1))
# --- candidates
MAP = {'COMPLETE': 'SUCCESS', 'PARTIALLY_COMPLETE': 'PARTIAL', 'NOT_STARTED': 'FAILED'}
acc = [a for a in acts if a['details'].startswith('Deletion worker submitted primary profile')]
others = [a for a in acts if (a['source_system'] == 'deletion_worker' and not a['details'].startswith('Deletion worker submitted') and 'Target resource' not in a['details'])]
OK = {39, 40, 41, 9, 10, 11}; VI = {20, 21, 22, 50, 51, 52}
def fp(o, a):
    d = (p(o['event_time']) - p(a['event_time'])).total_seconds()
    if o['details'].startswith('Policy action'): return 1000 <= d <= 4200 and int(d) % 60 in OK
    return 4800 <= d <= 10800 and int(d) % 60 in VI
row_acc = {o['activity_id']: {a['activity_id'] for a in acc if fp(o, a)} for o in others}
acc_rows = collections.defaultdict(set)
for o, s in row_acc.items():
    for a in s: acc_rows[a].add(o)
actid = {a['activity_id']: a for a in acts}
acc_case = {}
for a in acc:
    cs = set()
    for r in reqs:
        d = (p(a['event_time']) - p(r['reported_at'])).total_seconds() / 3600
        if -1.3 <= d <= -0.7 and a['reported_result'] == MAP[r['reported_status']]: cs.add(r['case_id'])
    acc_case[a['activity_id']] = cs
# evidence filter: if the account resource itself is linked to users, keep only those users' cases
for aid, cs in acc_case.items():
    us = res_users.get(actid[aid]['resource_id'])
    if us: acc_case[aid] = {c for c in cs if case_user[c] in us}
# worker-row evidence: an account candidate for a case is dropped if some uniquely-linked row of that account belongs to another user
def propagate():
    changed = True
    while changed:
        changed = False
        # rows with evidence users restrict their account candidates
        for o, s in row_acc.items():
            us = res_users.get(actid[o]['resource_id'])
            if not us: continue
            keep = {a for a in s if any(case_user[c] in us for c in acc_case[a])}
            if keep and keep != s: row_acc[o] = keep; changed = True
        # account uniquely owning a row with users -> restrict account cases
        for o, s in row_acc.items():
            us = res_users.get(actid[o]['resource_id'])
            if us and len(s) == 1:
                a = next(iter(s)); keep = {c for c in acc_case[a] if case_user[c] in us}
                if keep and keep != acc_case[a]: acc_case[a] = keep; changed = True
        # each case has exactly one account: unique assignment elimination
        case_accs = collections.defaultdict(set)
        for a, cs in acc_case.items():
            for c in cs: case_accs[c].add(a)
        for c, as_ in case_accs.items():
            if len(as_) == 1:
                a = next(iter(as_))
                if acc_case[a] != {c}: acc_case[a] = {c}; changed = True
        fixed = {next(iter(cs)): a for a, cs in acc_case.items() if len(cs) == 1}
        for a, cs in acc_case.items():
            if len(cs) > 1:
                keep = {c for c in cs if fixed.get(c, a) == a}
                if keep and keep != cs: acc_case[a] = keep; changed = True
propagate()
h = collections.Counter(len(cs) for cs in acc_case.values())
print('account rows -> #case candidates:', sorted(h.items()))
case2acc = collections.defaultdict(set)
for a, cs in acc_case.items():
    for c in cs: case2acc[c].add(actid[a]['resource_id'])
gold = {r['case_id']: json.loads(r['steps_json']) for r in csv.DictReader(open(os.path.join(DS, 'sample_output.csv')))}
right = wrong = amb = none = 0
for cid, st in gold.items():
    g = {s['resource_id'] for s in st if s['system_id'] == 'account_service'}
    got = case2acc.get(cid, set())
    if not got: none += 1
    elif len(got) > 1: amb += 1; print('  ambiguous', cid, got, 'gold', g)
    elif got == g: right += 1
    else: wrong += 1; print('  WRONG', cid, got, 'gold', g)
print(f'sample accounts: right={right} ambiguous={amb} wrong={wrong} none={none}')
ev = [r['case_id'] for r in reqs[32:]]
hh = collections.Counter(min(len(case2acc.get(c, ())), 3) for c in ev)
print('eval cases -> #account candidates (0,1,2,3+):', sorted(hh.items()))
json.dump({c: sorted(v) for c, v in case2acc.items()}, open(os.path.join(HERE, 'case_account_candidates.json'), 'w'), indent=0)

# ---- worker rows -> case
acc_by_rid = collections.defaultdict(set)
for a, cs in acc_case.items(): acc_by_rid[a] = cs
row_case = {}
for o, s in row_acc.items():
    cs = set()
    for a in s: cs |= acc_case[a]
    us = res_users.get(actid[o]['resource_id'])
    if us:
        cs = {c for c in cs if case_user[c] in us}  # evidence owner must match; else decoy row
    row_case[o] = cs
print('worker rows -> #case candidates:', sorted(collections.Counter(min(len(v), 3) for v in row_case.values()).items()))
case_rows = collections.defaultdict(list)
for o, cs in row_case.items():
    if len(cs) == 1: case_rows[next(iter(cs))].append(o)
tp = fn = fp_ = 0
for cid, st in gold.items():
    if cid not in case2acc: continue
    g = {s['resource_id'] for s in st if s['system_id'] not in ('account_service', 'security_service')}
    got = set()
    for o in case_rows.get(cid, []):
        if p(actid[o]['event_time']) <= p([r for r in reqs if r['case_id'] == cid][0]['audit_at']): got.add(actid[o]['resource_id'])
    tp += len(g & got); fn += len(g - got); fp_ += len(got - g)
    if g != got: print('  diff', cid, 'missing', g - got, 'extra', got - g)
print(f'sample worker-resource recall: tp={tp} fn={fn} fp={fp_}')
print('ambiguous eval cases:', sorted(c for c in ev if len(case2acc.get(c, ())) > 1))
json.dump({c: sorted(actid[o]['resource_id'] for o in v) for c, v in case_rows.items()}, open(os.path.join(HERE, 'case_worker_resources.json'), 'w'), indent=0)

# ---- hypothesis: row template (not result) encodes violation vs compliant, event_type encodes treatment
print('== template hypothesis check on samples')
TT = {'DELETE_RECORD': 'DELETE', 'REDACT_RECORD': 'REDACT', 'ANONYMIZE_RECORD': 'ANONYMIZE', 'CHECK_DATA_FLOW': 'FLOW', 'DISABLE_DATA_FLOW': 'FLOW',
      'CHECK_RESTORE_ACCESS': 'RESTORE', 'BLOCK_RESTORE': 'RESTORE'}
GT = {'VERIFY_RECORD_ABSENT': 'DELETE', 'VERIFY_RECORD_REDACTED': 'REDACT', 'VERIFY_RECORD_ANONYMIZED': 'ANONYMIZE', 'VERIFY_DATA_FLOW_DISABLED': 'FLOW', 'VERIFY_RESTORE_BLOCKED': 'RESTORE'}
agree = dis = 0
for cid, st in gold.items():
    finds = {s['resource_id'] for s in st if s['phase'] == 'FINDING'}
    ver = {s['resource_id']: GT.get(s['operation']) for s in st if s['phase'] == 'VERIFICATION'}
    for o in case_rows.get(cid, []):
        a = actid[o]; rid = a['resource_id']
        viol = not a['details'].startswith('Policy action')
        ok = (viol == (rid in finds)) and TT[a['event_type']] == ver.get(rid)
        agree += ok; dis += (not ok)
        if not ok: print('  disagree', cid, o, a['event_type'], rid, a['reported_result'], a['details'][:40], 'gold-find' if rid in finds else 'gold-ok', ver.get(rid))
print(f'template hypothesis: agree={agree} disagree={dis}')
# account rows: is "account remains" encoded by replication checkpoint?
for cid, st in gold.items():
    accf = [s['resource_id'] for s in st if s['phase'] == 'FINDING' and s['system_id'] == 'account_service']
    accs = case2acc.get(cid, set())
    rep = [a['activity_id'] for a in acts if a['resource_id'] in accs and a['event_type'] == 'SYNC_RECORD']
    if accf or rep: print('  account', cid, 'gold-finding', accf, 'replication rows', rep)

# ---- tie-break: generator never mixes compliant 'Policy action' rows with violations in one case (except legal holds).
repl_acc = {a['resource_id'] for a in acts if a['details'].startswith('Replication worker')}
def has_viol(c):
    if any(x in repl_acc for x in case2acc.get(c, ())) and len(case2acc.get(c, ())) == 1: return True
    return any(not actid[o]['details'].startswith('Policy action') for o in case_rows.get(c, []))
def has_ok(c):
    return any(actid[o]['details'].startswith('Policy action') and not actid[o]['resource_id'].startswith('legal_hold') for o in case_rows.get(c, []))
fixed_n = 0
for o, cs in row_case.items():
    if len(cs) < 2: continue
    a = actid[o]; okrow = a['details'].startswith('Policy action')
    if a['resource_id'].startswith('legal_hold'): continue
    keep = {c for c in cs if (not has_viol(c)) } if okrow else {c for c in cs if not has_ok(c)}
    if len(keep) == 1:
        c = next(iter(keep)); case_rows[c].append(o); row_case[o] = keep; fixed_n += 1
print('tie-break resolved rows:', fixed_n, 'still ambiguous:', sum(1 for v in row_case.values() if len(v) > 1))
json.dump({c: sorted(actid[o]['resource_id'] for o in v) for c, v in case_rows.items()}, open(os.path.join(HERE, 'case_worker_resources.json'), 'w'), indent=0)
