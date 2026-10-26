import json, csv, sys, collections
obs = json.load(open('solution/notes/scripts/log_observations.json'))
idn = {}
for r in csv.DictReader(open('dataset/user_identities.csv')): idn[r['email'].lower()] = r['user_id']
for r in csv.DictReader(open('dataset/user_audit_log.csv')):
    if r['field_name'] == 'email': idn.setdefault(r['old_value'].lower(), r['user_id']); idn.setdefault(r['new_value'].lower(), r['user_id'])
byuser = collections.defaultdict(list)
for o in obs:
    if o['event'] and o['event'].endswith('_started'): continue
    for u in {l[2] for l in o['links'] if l[2]}: byuser[u].append(o)
gold = {}
for r in csv.DictReader(open('dataset/sample_output.csv')): gold[r['case_id']] = (r['deletion_status'], json.loads(r['steps_json']))
fn = sys.argv[1]; only = sys.argv[2:] 
for r in csv.DictReader(open('dataset/' + fn)):
    if only and r['case_id'] not in only: continue
    u = idn.get(r['email'].lower()); A = r['audit_at']
    os_ = sorted(byuser.get(u, []), key=lambda o: o['ts'])
    if not os_ and not only: continue
    print(f"== {r['case_id']} {r['email']} {u} req={r['requested_at']} audit={A} reported={r['reported_status']}")
    if r['case_id'] in gold:
        st, steps = gold[r['case_id']]
        print('   GOLD', st, ' | '.join(f"{s['operation']}:{s['resource_id']}:{s['evidence_id']}" for s in steps if s['phase'] != 'REMEDIATION'))
    for o in os_:
        flag = 'OK ' if o['captured_at'] <= A else 'LATE'
        pre = 'preReq' if o['ts'] < r['requested_at'] else ''
        lk = ','.join(f"{l[0]}={l[3]}" for l in o['links'] if l[2] == u)
        print(f"   {flag} {o['file_id']} L{o['line']} {o['ts']} {o['sys']} {o['resource_id']} {o['cls']} via[{lk}] {pre}")
