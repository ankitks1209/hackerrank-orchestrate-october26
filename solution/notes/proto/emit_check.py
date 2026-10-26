"""Critic prototype: (1) re-emit gold steps from an abstract resource list to test
mapping/order/evidence rules; (2) check activity coverage of gold resources.
Reads only dataset/ participant files + sample_output for comparison. stdlib only."""
import csv, json, os
from datetime import datetime as D, timedelta as T
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DS = os.path.join(ROOT, 'dataset')
OPS = {'FINDING': ['REPORT_REMAINING_RECORD','REPORT_EXPOSED_PII','REPORT_ACTIVE_DATA_FLOW','REPORT_RESTORE_RISK'],
       'REMEDIATION': ['DISABLE_DATA_FLOW','BLOCK_RESTORE','DELETE_RECORD','REDACT_RECORD','ANONYMIZE_RECORD'],
       'VERIFICATION': ['VERIFY_RECORD_ABSENT','VERIFY_RECORD_PRESENT','VERIFY_RECORD_REDACTED','VERIFY_RECORD_ANONYMIZED','VERIFY_DATA_FLOW_DISABLED','VERIFY_RESTORE_BLOCKED']}
PH = ['FINDING','REMEDIATION','VERIFICATION']
# treatment -> (finding op, remediation op, verify op)
TREAT = {'DELETE': ('REPORT_REMAINING_RECORD','DELETE_RECORD','VERIFY_RECORD_ABSENT'),
         'REDACT': ('REPORT_EXPOSED_PII','REDACT_RECORD','VERIFY_RECORD_REDACTED'),
         'ANONYMIZE': ('REPORT_EXPOSED_PII','ANONYMIZE_RECORD','VERIFY_RECORD_ANONYMIZED'),
         'FLOW': ('REPORT_ACTIVE_DATA_FLOW','DISABLE_DATA_FLOW','VERIFY_DATA_FLOW_DISABLED'),
         'RESTORE': ('REPORT_RESTORE_RISK','BLOCK_RESTORE','VERIFY_RESTORE_BLOCKED'),
         'RETAIN': (None, None, 'VERIFY_RECORD_PRESENT')}
STATE = {'REPORT_REMAINING_RECORD':'PRESENT','REPORT_EXPOSED_PII':'PRESENT','REPORT_ACTIVE_DATA_FLOW':'ACTIVE','REPORT_RESTORE_RISK':'ACTIVE',
         'DISABLE_DATA_FLOW':'DISABLED','BLOCK_RESTORE':'BLOCKED','DELETE_RECORD':'ABSENT','REDACT_RECORD':'REDACTED','ANONYMIZE_RECORD':'ANONYMIZED',
         'VERIFY_RECORD_ABSENT':'ABSENT','VERIFY_RECORD_PRESENT':'PRESENT','VERIFY_RECORD_REDACTED':'REDACTED','VERIFY_RECORD_ANONYMIZED':'ANONYMIZED',
         'VERIFY_DATA_FLOW_DISABLED':'DISABLED','VERIFY_RESTORE_BLOCKED':'BLOCKED'}
V2T = {v[2]: k for k, v in TREAT.items()}

def emit(resources):
    """resources: list of dict(system, rid, treat, violating(bool), cite)"""
    viol = [r for r in resources if r['violating']]
    steps = []
    for r in resources:
        f, m, v = TREAT[r['treat']]
        if r['violating']:
            steps.append(('FINDING', f, r['system'], r['rid'], r['cite']))
            steps.append(('REMEDIATION', m, r['system'], r['rid'], ''))
        steps.append(('VERIFICATION', v, r['system'], r['rid'], '' if viol else r['cite']))
    steps.sort(key=lambda s: (PH.index(s[0]), OPS[s[0]].index(s[1]), s[2], s[3]))
    out = [dict(step_no=i+1, phase=p, system_id=s, resource_id=rid, operation=op, state=STATE[op], evidence_id=e)
           for i, (p, op, s, rid, e) in enumerate(steps)]
    return ('INCOMPLETE' if viol else 'COMPLETE'), out

def main():
    gold = {r['case_id']: (r['deletion_status'], json.loads(r['steps_json'])) for r in csv.DictReader(open(os.path.join(DS,'sample_output.csv')))}
    ok = 0
    for cid, (st, steps) in sorted(gold.items()):
        # abstract the gold into resource list
        res = {}
        for s in steps:
            k = (s['system_id'], s['resource_id'])
            d = res.setdefault(k, dict(system=k[0], rid=k[1], violating=False, cite='', treat=None))
            if s['phase'] == 'FINDING':
                d['violating'] = True; d['cite'] = s['evidence_id']
            if s['phase'] == 'VERIFICATION':
                d['treat'] = V2T[s['operation']]
                if s['evidence_id']: d['cite'] = s['evidence_id']
        st2, out = emit(list(res.values()))
        same = st2 == st and out == steps
        ok += same
        if not same: print('MISMATCH', cid)
    print(f'emitter reproduces {ok}/{len(gold)} sample cases exactly')

if __name__ == '__main__':
    main()
