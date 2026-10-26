#!/usr/bin/env python3
"""Normalize every JSON/TXT file in dataset/evidence/records into flat observations.

Output: solution/notes/records_observations.tsv  (one row per resource observation)
Columns: file_id, file_name, file_captured_at, entry_time, family, system, collection,
         resource_id, category, state, identifiers(;-sep), matched_users, detail
state vocabulary (normalized):
  PRESENT, ABSENT, IDENTIFIABLE (PII exposed), ANONYMIZED, REDACTED,
  ACTIVE (flow enabled / restore allowed), DISABLED, BLOCKED, RETAINED
"""
import csv, json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DS = os.path.join(ROOT, 'dataset')
REC = os.path.join(DS, 'evidence', 'records')

manifest = {r['file_path'].split('/')[-1]: r for r in csv.DictReader(open(os.path.join(DS, 'evidence_files.csv')))}

# ---------- identity index ----------
ids = list(csv.DictReader(open(os.path.join(DS, 'user_identities.csv'))))
aud = list(csv.DictReader(open(os.path.join(DS, 'user_audit_log.csv'))))
def digits(p): return re.sub(r'\D', '', p or '')
key2users = {}
def add(k, u):
    if k: key2users.setdefault(k, set()).add(u)
for r in ids:
    u = r['user_id']; add(u, u)
    add('e:' + r['email'].lower(), u); add('h:' + r['email_hash'].lower(), u)
    add('p:' + digits(r['phone']), u); add('n:' + r['name'].lower(), u)
for a in aud:
    u = a['user_id']
    for v in (a['old_value'], a['new_value']):
        if not v: continue
        f = a['field_name']
        if f == 'email': add('e:' + v.lower(), u)
        elif f == 'email_hash': add('h:' + v.lower(), u)
        elif f == 'phone': add('p:' + digits(v), u)
        elif f == 'name': add('n:' + v.lower(), u)

EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
def ident_keys(vals):
    out = []
    for v in vals:
        if v is None or v == '': continue
        v = str(v)
        if re.fullmatch(r'user_\d+', v): out.append(v)
        elif '@' in v:
            for e in EMAIL_RE.findall(v): out.append('e:' + e.lower())
        elif re.fullmatch(r'[0-9a-f]{64}', v.lower()): out.append('h:' + v.lower())
        elif re.fullmatch(r'[+\d][\d ()\-]{6,}', v): out.append('p:' + digits(v))
        else: out.append('n:' + v.lower())
    return out
def match(keys):
    us = set()
    for k in keys: us |= key2users.get(k, set())
    return us

rows = []
def emit(fname, entry_time, family, system, coll, rid, cat, state, idvals, detail):
    m = manifest.get(fname, {})
    keys = ident_keys(idvals)
    us = match(keys)
    unmatched = [k for k in keys if k not in key2users]
    rows.append(dict(file_id=m.get('file_id', ''), file_name=fname, file_captured_at=m.get('captured_at', ''),
                     entry_time=entry_time, family=family, system=system, collection=coll, resource_id=rid,
                     category=cat, state=state, identifiers=';'.join(keys), unmatched_identifiers=';'.join(unmatched),
                     matched_users=';'.join(sorted(us, key=lambda x: int(x.split('_')[1]))), detail=detail))

FLAT_STATE = {'FOUND': 'PRESENT', 'NOT_FOUND': 'ABSENT', 'IDENTIFIABLE': 'IDENTIFIABLE', 'ANONYMIZED': 'ANONYMIZED',
              'ACTIVE': 'ACTIVE', 'BLOCKED': 'BLOCKED', 'DISABLED': 'DISABLED', 'REDACTED': 'REDACTED'}

def snapshot_record(fname, t, store, coll, r):
    rid = r.get('resource_id')
    if coll == 'customer_profiles':
        emit(fname, t, 'snapshot', store, coll, rid, 'USER_PROFILE', 'PRESENT',
             [r.get('customer_reference'), r.get('email'), r.get('phone'), r.get('full_name')], 'account_status=%s' % r.get('account_status'))
    elif coll == 'customer_analytics_reports':
        pii = [r.get('user_id'), r.get('email'), r.get('phone'), r.get('email_hash')]
        emit(fname, t, 'snapshot', store, coll, rid, 'ANALYTICS_PROFILE', 'IDENTIFIABLE' if any(pii) else 'ANONYMIZED', pii,
             'metrics=%s' % json.dumps(r.get('metrics')))
    elif coll == 'backup_catalog':
        emit(fname, t, 'snapshot', store, coll, rid, 'BACKUP_ARCHIVE', 'ACTIVE' if r.get('restore_allowed') else 'BLOCKED',
             [r.get('subject_reference')], 'archive=%s' % r.get('archive_path'))
    elif coll == 'customer_export_jobs':
        emit(fname, t, 'snapshot', store, coll, rid, 'USER_EXPORT', 'PRESENT', [r.get('owner_email')],
             'download_available=%s expires=%s' % (r.get('download_available'), r.get('expires_at')))
    elif coll == 'connector_configurations':
        emit(fname, t, 'snapshot', store, coll, rid, 'DATA_FLOW', 'ACTIVE' if r.get('enabled') else 'DISABLED',
             [r.get('subject_selector')], '%s mode=%s' % (r.get('connector_name'), r.get('mode')))
    elif coll == 'customer_search_documents':
        d = r.get('document') or {}
        emit(fname, t, 'snapshot', store, coll, rid, 'SEARCH_INDEX_ENTRY', 'PRESENT',
             [d.get('customer_reference'), d.get('email'), d.get('display_name')], 'index=%s' % r.get('index_name'))
    elif coll == 'security_audit_events':
        emit(fname, t, 'snapshot', store, coll, rid, 'SECURITY_AUDIT_LOG', 'RETAINED', [r.get('subject_reference')], r.get('event_name'))
    elif coll == 'support_conversations':
        txt = r.get('message_text') or ''
        state = 'REDACTED' if txt.strip() == '[REDACTED]' or not EMAIL_RE.search(txt) else 'IDENTIFIABLE'
        emit(fname, t, 'snapshot', store, coll, rid, 'SUPPORT_MESSAGE', state, [r.get('subject_reference')] + EMAIL_RE.findall(txt),
             'ticket=%s text=%s' % (r.get('ticket_id'), txt[:90]))
    elif coll == 'ticket_attachments':
        emit(fname, t, 'snapshot', store, coll, rid, 'SUPPORT_ATTACHMENT', 'PRESENT', [r.get('uploaded_by')],
             'ticket=%s file=%s' % (r.get('ticket_id'), r.get('file_name')))
    elif coll == 'retained_order_records':
        emit(fname, t, 'snapshot', store, coll, rid, 'LEGAL_HOLD_RECORD', 'RETAINED', [r.get('subject_reference')],
             'order=%s until=%s reason=%s' % (r.get('order_reference'), r.get('retained_until'), r.get('retention_reason')))
    elif coll == 'deleted_customer_references':
        pii = [r.get('name'), r.get('email'), r.get('phone'), r.get('email_hash')]
        emit(fname, t, 'snapshot', store, coll, rid, 'ACCOUNT_TOMBSTONE', 'IDENTIFIABLE' if any(pii) else 'REDACTED',
             [r.get('subject_reference')] + pii, 'account_status=%s' % r.get('account_status'))
    elif coll == 'operational_record_history':
        emit(fname, r.get('recorded_at'), 'snapshot_flat', r.get('system'), coll + '@' + store, rid, r.get('record_type'),
             FLAT_STATE.get(r.get('result'), r.get('result')), [r.get('lookup_value')], 'result=%s' % r.get('result'))
    else:
        emit(fname, t, 'snapshot', store, coll, rid, '?', '?', [], json.dumps(r)[:120])

for fname in sorted(os.listdir(REC)):
    p = os.path.join(REC, fname)
    if fname.endswith('.txt'):
        for line in open(p):
            m = re.match(r'- (\S+) \| (\S+) \| (\S+) \| (\S+) \| (\S+) \| (.*)$', line.strip())
            if m:
                t, sysid, rid, cat, res, ref = m.groups()
                emit(fname, t, 'handover_txt', sysid, '', rid, cat, FLAT_STATE.get(res, res),
                     [] if ref == 'no direct identifier' else [ref], 'result=%s' % res)
        continue
    d = json.load(open(p))
    if 'snapshots' in d:
        for s in d['snapshots']:
            if not s['records']:
                emit(fname, s['captured_at'], 'snapshot', s['data_store'], s['collection'], '(EMPTY COLLECTION)', '', 'EMPTY', [], 'collection has zero records')
            for r in s['records']:
                snapshot_record(fname, s['captured_at'], s['data_store'], s['collection'], r)
    elif 'service_exports' in d:
        for svc, v in d['service_exports'].items():
            for lk, lst in v.items():
                for r in lst:
                    t = r.get('observed_at'); rid = r.get('resource_id')
                    if svc == 'account_service':
                        pr = r.get('profile') or {}
                        st = 'ABSENT' if r.get('status_code') == 404 or r.get('profile') is None else 'PRESENT'
                        emit(fname, t, 'service_export', svc, lk, rid, 'USER_PROFILE', st,
                             [pr.get('customer_reference'), pr.get('email'), pr.get('email_hash'), pr.get('full_name'), pr.get('phone')],
                             'status_code=%s' % r.get('status_code'))
                    elif svc == 'analytics_platform':
                        pii = [r.get('customer_reference'), r.get('email'), r.get('email_hash'), r.get('phone')]
                        emit(fname, t, 'service_export', svc, lk, rid, 'ANALYTICS_PROFILE', 'IDENTIFIABLE' if any(pii) else 'ANONYMIZED', pii,
                             'cohort=%s' % r.get('audience_cohort'))
                    elif svc == 'backup_service':
                        emit(fname, t, 'service_export', svc, lk, rid, 'BACKUP_ARCHIVE', 'ACTIVE' if r.get('restore_allowed') else 'BLOCKED',
                             [r.get('customer_reference'), r.get('customer_email')], 'archive=%s' % r.get('archive_key'))
                    elif svc == 'export_service':
                        emit(fname, t, 'service_export', svc, lk, rid, 'USER_EXPORT', 'PRESENT',
                             [r.get('customer_reference'), r.get('owner_email'), r.get('owner_phone')], 'object=%s' % r.get('object_key'))
                    elif svc == 'integration_service':
                        emit(fname, t, 'service_export', svc, lk, rid, 'DATA_FLOW', 'ACTIVE' if r.get('enabled') else 'DISABLED',
                             [r.get('customer_reference'), r.get('customer_email')],
                             '%s last=%s' % (r.get('connector_name'), r.get('last_delivery_status')))
                    elif svc == 'search_service':
                        h = r.get('hits') or {}
                        docs = h.get('documents') or []
                        idv = [r.get('query')]
                        for dd in docs: idv += [dd.get('customer_reference'), dd.get('email'), dd.get('email_hash'), dd.get('display_name'), dd.get('phone')]
                        emit(fname, t, 'service_export', svc, lk, rid, 'SEARCH_INDEX_ENTRY', 'PRESENT' if h.get('total') else 'ABSENT', idv,
                             'query=%s total=%s docs=%s' % (r.get('query'), h.get('total'), [dd.get('resource_id') for dd in docs]))
                    elif svc == 'security_service':
                        emit(fname, t, 'service_export', svc, lk, rid, 'SECURITY_AUDIT_LOG', 'RETAINED', [r.get('subject_reference')],
                             '%s retention_until=%s' % (r.get('event_code'), r.get('retention_until')))
                    elif svc == 'support_platform':
                        pii = [r.get('requester_email'), r.get('requester_name'), r.get('requester_phone')]
                        emit(fname, t, 'service_export', svc, lk, rid, 'SUPPORT_MESSAGE', 'IDENTIFIABLE' if any(pii) else 'REDACTED',
                             [r.get('customer_reference')] + pii, 'excerpt=%s' % r.get('message_excerpt'))
                    else:
                        emit(fname, t, 'service_export', svc, lk, rid, '?', '?', [], json.dumps(r)[:120])
    elif 'records' in d:
        fam = fname.rsplit('_', 1)[0]
        for r in d['records']:
            if 'record_type' in r:
                emit(fname, r.get('recorded_at'), 'flat_ledger', r['system'], '', r['resource_id'], r['record_type'],
                     FLAT_STATE.get(r['result'], r['result']), [r.get('subject_reference')], 'result=%s' % r['result'])
            else:  # collection-style (analytics report / export jobs)
                snapshot_record(fname, d.get('captured_at'), d.get('source'), d.get('collection'), r)

out = os.path.join(ROOT, 'solution', 'notes', 'records_observations.tsv')
cols = ['file_id', 'file_name', 'file_captured_at', 'entry_time', 'family', 'system', 'collection', 'resource_id', 'category',
        'state', 'identifiers', 'unmatched_identifiers', 'matched_users', 'detail']
with open(out, 'w', newline='') as fh:
    w = csv.DictWriter(fh, cols, delimiter='\t'); w.writeheader(); w.writerows(rows)
print(len(rows), 'rows ->', out)
