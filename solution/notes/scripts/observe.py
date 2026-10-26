"""Extract per-resource observations from all log evidence and link them to users/cases."""
import sys, os, csv, glob, collections, hashlib, json
sys.path.insert(0, os.path.dirname(__file__))
from logparse import parse_file
D = 'dataset'
man = {r['file_path']: r for r in csv.DictReader(open(f'{D}/evidence_files.csv'))}
# identity index: key -> (user_id, kind)
idx = {}
for r in csv.DictReader(open(f'{D}/user_identities.csv')):
    u = r['user_id']; idx[u] = (u, 'user_id')
    idx[r['email'].lower()] = (u, 'cur_email'); idx[r['email_hash']] = (u, 'cur_hash'); idx[r['phone']] = (u, 'cur_phone')
for r in csv.DictReader(open(f'{D}/user_audit_log.csv')):
    u = r['user_id']; f = r['field_name']
    for v, t in ((r['old_value'], 'old'), (r['new_value'], 'new')):
        k = v.lower() if f == 'email' else v
        if k and k not in idx: idx[k] = (u, f'{t}_{f}')
        if f == 'email' and v:
            h = hashlib.sha256(v.lower().encode()).hexdigest()
            if h not in idx: idx[h] = (u, f'{t}_email_hash')
cases = collections.defaultdict(list)
for fn in ('deletion_requests.csv', 'sample_deletion_requests.csv'):
    for r in csv.DictReader(open(f'{D}/{fn}')):
        e = r['email'].lower(); u = idx.get(e, (None,))[0]
        cases[u].append((r['case_id'], r['audit_at']))
KEYS = ('lookup_key', 'subject_key', 'match_key', 'owner_key', 'scan_key', 'subject_ref', 'correlation_key',
        'matched_value', 'customer_email', 'email', 'requester_email', 'owner_email', 'subject_reference', 'customer_reference', 'phone', 'requester_phone', 'email_hash', 'requester_name')
out = []
for p in sorted(glob.glob(f'{D}/evidence/logs/*.log')):
    rel = os.path.relpath(p, D); m = man[rel]
    rows = parse_file(p)
    tracekeys = collections.defaultdict(set)
    for r in rows:
        for k in ('lookup_key', 'subject_key', 'match_key', 'owner_key', 'scan_key', 'subject_ref'):
            v = r['kv'].get(k)
            if v and v != 'null' and r['trace']: tracekeys[r['trace']].add((k, v))
    for i, r in enumerate(rows, 1):
        rid = r['kv'].get('resource_id')
        if not rid: continue
        keys = set(tracekeys.get(r['trace'], set()))
        for k in KEYS:
            v = r['kv'].get(k)
            if v and v != 'null' and v != '[REDACTED]': keys.add((k, v))
        links = []
        for k, v in sorted(keys):
            hit = idx.get(v.lower() if '@' in v else v)
            links.append((k, v, hit[0] if hit else None, hit[1] if hit else None))
        state = {k: v for k, v in r['kv'].items() if k in ('rows', 'http_status', 'result', 'enabled', 'scheduler_registered', 'last_run', 'eligible', 'deletion_block', 'decision', 'policy', 'available', 'direct_identifiers', 'detector', 'message_text', 'email_opt_in', 'integrity_check', 'access', 'reason', 'archive_present', 'restore_allowed', 'last_delivery_status', 'connector_name', 'event_code', 'retention_until', 'marker_found', 'last_write', 'record_type', 'system', 'total_hits', 'file', 'email', 'phone', 'email_hash', 'customer_reference', 'customer_email', 'requester_email', 'requester_name', 'requester_phone', 'owner_email', 'audience_cohort', 'object_key', 'archive_key', 'subject_reference')}
        out.append(dict(file_id=m['file_id'], file=os.path.basename(p), captured_at=m['captured_at'], line=i, ts=r['ts'],
                        service=r['service'], event=r['event'], level=r['level'], resource_id=rid, trace=r['trace'], state=state, links=links))
json.dump(out, open('solution/notes/scripts/log_observations.json', 'w'), indent=0, ensure_ascii=False)
print(len(out), 'observations')
# summaries
unlinked = [o for o in out if not any(l[2] for l in o['links'])]
print('unlinked to any known user:', len(unlinked))
print(collections.Counter((o['file'][:22], o['service'], o['event']) for o in unlinked).most_common(40))
multi = [o for o in out if len({l[2] for l in o['links'] if l[2]}) > 1]
print('linked to >1 user:', len(multi))
for o in multi[:20]: print(o['file_id'], o['line'], o['resource_id'], o['links'])
kinds = collections.Counter(l[3] for o in out for l in o['links'])
print('link kinds:', kinds)
unknown_keys = collections.Counter((l[0]) for o in out for l in o['links'] if not l[2])
print('unknown key fields:', unknown_keys)
