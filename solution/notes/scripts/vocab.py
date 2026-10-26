import sys, glob, os, collections
sys.path.insert(0, os.path.dirname(__file__))
from logparse import parse_file
groups = collections.defaultdict(list)
for p in sorted(glob.glob('dataset/evidence/logs/*.log')):
    b = os.path.basename(p)
    g = 'central' if not (b.startswith('resource_lookup') or b in ('support_replica.log',) or b.startswith('search_index') or b.startswith('notification')) else b.split('_2026')[0]
    groups[g] += parse_file(p)
for g, rows in groups.items():
    print('########', g, len(rows))
    c = collections.Counter((r['service'], r['event'], r['level']) for r in rows)
    keys = collections.defaultdict(set); vals = collections.defaultdict(collections.Counter)
    for r in rows:
        keys[(r['service'], r['event'])] |= set(r['kv'])
        for k, v in r['kv'].items():
            if k in ('result','rows','http_status','enabled','state','status','integrity_check','restore','restore_enabled','last_delivery_status','record_type','system','mode','scope','action','outcome','redacted','field','sources','connector_name','index','cache','pool','destination','event_code','audience_cohort','job','schedule','restore_scope','backup_status','sync_enabled','pending','export_status','total_hits'):
                vals[(r['service'], r['event'], k)][v] += 1
    for (s, e, l), n in sorted(c.items(), key=lambda x: (str(x[0][0]), str(x[0][1]))):
        print(f'  {n:4d} {l:5s} {s} / {e}')
    print('  -- keys per (service,event)')
    for k, ks in sorted(keys.items(), key=lambda x: str(x)):
        print('   ', k, sorted(ks))
    print('  -- values')
    for k, cnt in sorted(vals.items(), key=lambda x: str(x)):
        print('   ', k, dict(cnt.most_common(8)))
