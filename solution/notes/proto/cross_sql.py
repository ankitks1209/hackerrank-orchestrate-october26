"""Critic prototype: compare activity-template class with SQL-derived class per eval case."""
import json, re, os, csv, collections
HERE = os.path.dirname(os.path.abspath(__file__)); NOTES = os.path.dirname(HERE)
DS = os.path.join(os.path.dirname(os.path.dirname(NOTES)), 'dataset')
acts = {a['resource_id']: a for a in csv.DictReader(open(os.path.join(DS, 'system_activity.csv'))) if a['source_system'] == 'deletion_worker' and not a['details'].startswith('Deletion worker submitted')}
cw = json.load(open(os.path.join(HERE, 'case_worker_resources.json')))
ca = json.load(open(os.path.join(HERE, 'case_account_candidates.json')))
sql = {}
for line in open(os.path.join(NOTES, '01_sql_case_derivations.txt')):
    m = re.match(r'(case_\d+) ', line)
    if not m: continue
    items = re.findall(r'(evidence_\d+) (\w+) (\w+_\d+) ([^|]+)', line)
    sql[m.group(1)] = {rid: cls.strip() for _, _, rid, cls in items}
VIOL = ('REMAINING', 'EXPOSED', 'ACTIVE_DATA', 'RESTORE_RISK', 'EMAIL-PRESENT')
stats = collections.Counter(); bad = []
for cid, d in sql.items():
    rows = set(cw.get(cid, []))
    for rid, cls in d.items():
        if rid.startswith(('audit_record', 'legal_hold')): continue
        sv = cls.startswith(VIOL)
        if rid.startswith('account_'):
            # account violation should coincide with replication checkpoint row
            continue
        if rid in rows:
            av = not acts[rid]['details'].startswith('Policy action')
            stats['agree' if av == sv else 'disagree'] += 1
            if av != sv: bad.append((cid, rid, cls, acts[rid]['details'][:50]))
        else:
            stats['sql-only'] += 1; bad.append((cid, rid, cls, 'NO linked worker row'))
    for rid in rows - set(d):
        if d: stats['activity-only(case has sql)'] += 1
print(stats)
for b in bad[:40]: print(' ', b)
