#!/usr/bin/env python3
"""Check whether sample gold step order == (phase, operation-table order, system_id, resource_id)."""
import csv, json, os, re
D = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'dataset')
PH = ['FINDING', 'REMEDIATION', 'VERIFICATION']
OPS = ['REPORT_REMAINING_RECORD', 'REPORT_EXPOSED_PII', 'REPORT_ACTIVE_DATA_FLOW', 'REPORT_RESTORE_RISK',
       'DISABLE_DATA_FLOW', 'BLOCK_RESTORE', 'DELETE_RECORD', 'REDACT_RECORD', 'ANONYMIZE_RECORD',
       'VERIFY_RECORD_ABSENT', 'VERIFY_RECORD_PRESENT', 'VERIFY_RECORD_REDACTED', 'VERIFY_RECORD_ANONYMIZED',
       'VERIFY_DATA_FLOW_DISABLED', 'VERIFY_RESTORE_BLOCKED']
num = lambda r: (re.sub(r'\d+$', '', r), int(re.search(r'(\d+)$', r).group(1)))
for name, key in [('lexical', lambda s: (PH.index(s['phase']), OPS.index(s['operation']), s['system_id'], s['resource_id'])),
                  ('numeric', lambda s: (PH.index(s['phase']), OPS.index(s['operation']), s['system_id'], num(s['resource_id'])))]:
    bad = []
    for g in csv.DictReader(open(os.path.join(D, 'sample_output.csv'))):
        st = json.loads(g['steps_json'])
        if st != sorted(st, key=key): bad.append(g['case_id'])
        assert [s['step_no'] for s in st] == list(range(1, len(st) + 1))
    print(name, 'mismatches:', bad)
# ties: same phase+op+system with >1 resource
for g in csv.DictReader(open(os.path.join(D, 'sample_output.csv'))):
    st = json.loads(g['steps_json']); c = {}
    for s in st: c.setdefault((s['phase'], s['operation'], s['system_id']), []).append(s['resource_id'])
    for k, v in c.items():
        if len(v) > 1: print('tie', g['case_id'], k, v)
