#!/usr/bin/env python3
"""Trace sample cases: resolve identity, grep every text evidence file + system_activity
for the subject's identifiers and for gold resource ids. Usage: trace_cases.py case_13 case_14 ..."""
import csv, json, os, re, sys, hashlib
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
D = os.path.join(ROOT, 'dataset')
def rd(n): return list(csv.DictReader(open(os.path.join(D, n), encoding='utf-8')))
reqs = {r['case_id']: r for r in rd('sample_deletion_requests.csv') + rd('deletion_requests.csv')}
gold = {r['case_id']: r for r in rd('sample_output.csv')}
ids = rd('user_identities.csv'); aud = rd('user_audit_log.csv'); act = rd('system_activity.csv')
man = rd('evidence_files.csv')
def resolve(email):
    e = email.strip().lower()
    for u in ids:
        if u['email'].lower() == e: return u, 'current'
    for a in aud:
        if a['field_name'] == 'email' and a['old_value'].lower() == e:
            return next(u for u in ids if u['user_id'] == a['user_id']), 'historical'
    return None, None
def idents(u):
    s = {('user_id', u['user_id']), ('email', u['email']), ('phone', u['phone']), ('hash', u['email_hash']), ('name', u['name'])}
    for a in aud:
        if a['user_id'] == u['user_id']:
            s.add(('old_' + a['field_name'], a['old_value']))
            if a['field_name'] == 'email':
                s.add(('old_hash', hashlib.sha256(a['old_value'].lower().encode()).hexdigest()))
    return s
texts = {}
for m in man:
    p = os.path.join(D, m['file_path'])
    if p.endswith(('.png', '.pdf')): continue
    texts[m['file_id']] = (m, open(p, encoding='utf-8').read().splitlines())
def uid_re(uid): return re.compile(r'(?<![\w])' + re.escape(uid) + r'(?![\w])')
for cid in sys.argv[1:]:
    r = reqs[cid]; u, how = resolve(r['email'])
    print('=' * 100); print(cid, r['email'], 'requested', r['requested_at'], 'audit', r['audit_at'], 'reported', r['reported_status'])
    print('  user', u['user_id'], how, '|', u['name'], '|', u['phone'])
    I = idents(u)
    for k, v in sorted(I): print('   id', k, v)
    g = json.loads(gold[cid]['steps_json']) if cid in gold else []
    gres = sorted({s['resource_id'] for s in g})
    print('  GOLD', gold.get(cid, {}).get('deletion_status'), gres)
    pats = [(k, uid_re(v) if k == 'user_id' else re.compile(re.escape(v), re.I)) for k, v in I if v]
    for fid, (m, lines) in texts.items():
        hits = []
        traces = set()
        for i, ln in enumerate(lines):
            ks = [k for k, p in pats if p.search(ln)]
            rs = [x for x in gres if re.search(r'(?<![\w])' + re.escape(x) + r'(?![\w])', ln)]
            if ks or rs:
                hits.append((i, ks, rs, ln))
                t = re.search(r'trace_id=(\S+)', ln)
                if t: traces.add(t.group(1))
        # add trace siblings
        if traces:
            seen = {h[0] for h in hits}
            for i, ln in enumerate(lines):
                t = re.search(r'trace_id=(\S+)', ln)
                if t and t.group(1) in traces and i not in seen and ('resource_id=' in ln or 'event=' in ln):
                    hits.append((i, ['trace'], [], ln))
        if hits:
            late = ' LATE' if m['captured_at'] > r['audit_at'] else ''
            print(f"  -- {fid} {m['file_path']} cap={m['captured_at']}{late}")
            for i, ks, rs, ln in sorted(hits):
                print(f"     L{i+1} {','.join(ks)} {','.join(rs)} :: {ln[:330]}")
    print('  -- system_activity')
    for a in act:
        blob = ' '.join(a.values())
        ks = [k for k, p in pats if p.search(blob)]
        if a['resource_id'] in gres or ks:
            late = ' LATE' if a['event_time'] > r['audit_at'] else ''
            print(f"     {a['activity_id']} {a['event_time']}{late} {a['event_type']} {a['source_system']}->{a['target_system']} {a['resource_id']} {a['reported_result']} {','.join(ks)} :: {a['details'][:200]}")
