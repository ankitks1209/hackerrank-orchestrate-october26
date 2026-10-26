"""Classify each log observation into a normalized resource state, then build per-case log evidence."""
import json, csv, collections, sys
obs = json.load(open('solution/notes/scripts/log_observations.json'))
def classify(o):
    s, ev, sv = o['state'], o['event'], o['service']
    g = lambda k: s.get(k)
    if sv == 'profile_service': return ('account_service?', 'NOISE_PROFILE_SERVICE')
    if ev == 'profile_lookup_completed':
        return ('account_service', 'PRESENT' if g('rows') == '1' else 'ABSENT')
    if ev == 'index_query_completed': return ('search_service', 'PRESENT' if g('result') == 'hit' else 'ABSENT')
    if ev == 'audit_record_read_completed': return ('security_service', 'RETAINED_PRESENT' if g('rows') == '1' else 'ABSENT')
    if ev == 'analytics_identity_scan': return ('analytics_platform', 'EXPOSED')
    if ev == 'analytics_profile_read': return ('analytics_platform', 'ANONYMIZED' if g('direct_identifiers') == '0' else 'EXPOSED')
    if ev == 'analytics_profile_read_completed':
        return ('analytics_platform', 'ANONYMIZED' if all(g(k) in (None, 'null') for k in ('email', 'phone', 'email_hash', 'customer_reference')) else 'EXPOSED')
    if ev == 'contact_lookup_completed': return ('analytics_platform', 'PRESENT_MARKETING_CONTACT')
    if ev == 'message_pii_scan': return ('support_platform', 'EXPOSED')
    if ev == 'attachment_pii_scan': return ('support_platform', 'ATTACHMENT_PRESENT')
    if ev == 'message_read': return ('support_platform', 'REDACTED' if g('message_text') == '[REDACTED]' else 'EXPOSED')
    if ev == 'support_ticket_read_completed':
        return ('support_platform', 'REDACTED' if all(g(k) in (None, 'null') for k in ('requester_email', 'requester_name', 'requester_phone')) else 'EXPOSED')
    if ev in ('connector_heartbeat', 'connector_config_loaded', 'connector_config_read_completed'):
        return ('integration_service', 'ACTIVE' if g('enabled') == 'true' else 'DISABLED')
    if ev == 'restore_candidate_evaluated':
        return ('backup_service', 'RESTORE_ACTIVE' if g('eligible') == 'true' and g('deletion_block') == 'false' else 'BLOCKED')
    if ev == 'restore_authorization_completed': return ('backup_service', 'BLOCKED' if g('decision') == 'deny' else 'RESTORE_ACTIVE')
    if ev == 'restore_policy_read_completed': return ('backup_service', 'RESTORE_ACTIVE' if g('restore_allowed') == 'true' else 'BLOCKED')
    if ev in ('export_download_check_completed', 'export_metadata_read_completed'):
        return ('export_service', 'PRESENT' if g('available') == 'true' else 'ABSENT')
    if ev == 'retained_order_loaded': return ('legal_service', 'RETAINED_PRESENT')
    if ev == 'record_lookup':
        r = g('result'); return (g('system'), {'FOUND': 'PRESENT', 'NOT_FOUND': 'ABSENT', 'IDENTIFIABLE': 'EXPOSED', 'ACTIVE': 'ACTIVE_OR_RESTORE', 'ANONYMIZED': 'ANONYMIZED'}[r] + '/' + g('record_type'))
    if ev in ('contact_query_completed',): return ('support_platform', 'PRESENT' if g('rows') == '1' else 'ABSENT')
    if ev == 'deletion_marker_check': return ('support_platform', 'PRESENT_NO_DELETION_MARKER' if g('marker_found') == 'false' else 'MARKED')
    if ev == 'thumbnail_failed': return ('support_platform', 'NOISE')
    return (None, None)
if __name__ == '__main__':
    c = collections.Counter()
    for o in obs:
        if o['event'] and o['event'].endswith('_started'): continue
        sysid, st = classify(o); o['sys'] = sysid; o['cls'] = st
        c[(o['service'], o['event'], sysid, st)] += 1
    for k, n in sorted(c.items(), key=lambda x: str(x)): print(n, k)
    json.dump(obs, open('solution/notes/scripts/log_observations.json', 'w'), indent=0, ensure_ascii=False)
