"""Universal parser for dataset/evidence/logs/*.log (stdlib only).
Returns dicts: ts, level, service, trace, event, kv(dict), fmt, raw."""
import re, json, os, sys, glob
KV = re.compile(r'([A-Za-z_][\w.]*)=("((?:[^"\\]|\\.)*)"|\S+)')
def kvparse(s):
    d = {}
    for m in KV.finditer(s):
        k = m.group(1)
        v = m.group(3) if m.group(3) is not None else m.group(2)
        d[k] = v.replace('\\"', '"')
    return d
def parse_line(line):
    line = line.rstrip('\n')
    if not line.strip(): return None
    ts, rest = line.split(' ', 1)
    r = {'ts': ts, 'raw': line}
    if rest.startswith('{'):                                   # structured JSON
        j = json.loads(rest); r.update(fmt='json', level=j.pop('severity', None),
            service=j.get('service') or j.get('logger'), trace=j.get('trace_id') or j.get('instance'),
            event=j.get('event'), kv=j); return r
    if rest.startswith('<'):                                   # RFC5424 syslog
        m = re.match(r'<(\d+)>1 (\S+) (\S+) (\S+) - - (.*)', rest)
        kv = kvparse(m.group(5)); r.update(fmt='syslog', pri=m.group(1), host=m.group(2), service=m.group(3),
            trace=m.group(4), level=kv.get('level'), event=kv.get('event'), kv=kv); return r
    if rest.startswith('| '):                                  # pipe-delimited
        p = [x.strip() for x in rest.split(' | ')]
        p[0] = p[0].lstrip('| ').strip()
        lvl, svc, tr, ev, body = p[0], p[1], p[2], p[3], ' | '.join(p[4:])
        r.update(fmt='pipe', level=lvl, service=svc, trace=tr, event=ev, kv=kvparse(body)); return r
    if rest.startswith('['):                                   # bracketed app trace
        m = re.match(r'\[(\w+)\] \[([^\]]+)\] \[([^\]]+)\] (\w+): ?(.*)', rest)
        r.update(fmt='bracket', level=m.group(1), service=m.group(2), trace=m.group(3), event=m.group(4),
            kv=kvparse(m.group(5))); return r
    if rest.startswith('requestId='):                          # cloud runtime, nested message
        outer = kvparse(rest); inner = kvparse(outer.get('message', ''))
        kv = dict(inner); r.update(fmt='cloud', level=outer.get('level'), service=outer.get('function'),
            trace=outer.get('requestId'), event=inner.get('event'), kv=kv); return r
    m = re.match(r'(INFO|DEBUG|WARN|ERROR) (.*)', rest)
    if m:                                                      # 'INFO service=... ' diagnostic
        kv = kvparse(m.group(2)); r.update(fmt='diag', level=m.group(1), service=kv.get('service'),
            trace=kv.get('seq'), event=kv.get('event'), kv=kv); return r
    kv = kvparse(rest)                                         # logfmt
    r.update(fmt='logfmt', level=kv.get('level'), service=kv.get('service'), trace=kv.get('trace_id') or kv.get('instance'),
        event=kv.get('event'), kv=kv); return r
def parse_file(p):
    return [x for x in (parse_line(l) for l in open(p, encoding='utf-8')) if x]
if __name__ == '__main__':
    for p in sorted(glob.glob(sys.argv[1] + '/*.log')):
        rows = parse_file(p)
        print(os.path.basename(p), len(rows), {r['fmt'] for r in rows})
