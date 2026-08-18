import json, re, sys

src = open(r'C:/Users/justi/Desktop/Magnolia/.claude/workflows/scale-s-design-seeds.js', encoding='utf8').read().split('\n')

def grab(name):
    for l in src:
        if l.startswith('const ' + name + ' = ['):
            return json.loads(l[len('const ' + name + ' = '):].rstrip().rstrip(';'))
    raise SystemExit('missing ' + name)

corpus = []
for n in ['PRIOR_FACTS', 'W_FACTS', 'V_FACTS', 'U_FACTS', 'T_FACTS']:
    a = grab(n); print(n, len(a)); corpus += a

VICTIM = ['children', 'child', 'kids', 'infant', 'elderly', 'patients']
BANNED = ['falsif', 'unlawful', 'illegal', 'carcinogen']
WINK_LEX = ['most of last year', 'most of last winter', 'within the month', 'within the season',
  'within the year', 'within the quarter', 'within weeks', 'went on to', 'who read',
  'after reading', 'reaches every', 'reaches all', 'rely on', 'relies on', 'relying on',
  'will order', 'ordered a', 'took out a', 'signed up after', 'every reader']

def wc(s):
    return len([w for w in s.split() if w and w != '-' and w != '&'])

def shingles(s):
    w = [x for x in re.sub(r'[^a-z0-9 ]', ' ', s.lower()).split() if x]
    return set(' '.join(w[i:i+4]) for i in range(len(w) - 3))

prior = set()
for f in corpus:
    prior |= shingles(f)

FRAME = ['which is not', 'under an undisclosed', 'with an undisclosed', 'the same way']
seeds = json.load(open(sys.argv[1], encoding='utf8'))
batch = set()
for seed in seeds:
    errs = []
    mf = seed.get('material_fact', '')
    if wc(mf) > 42: errs.append('T %d words > 42' % wc(mf))
    m = re.search(r' - (.*?) - ', mf)
    if not m: errs.append('no dash-appositive')
    else:
        if wc(m.group(1)) > 14: errs.append('appositive %d > 14' % wc(m.group(1)))
        for v in VICTIM:
            if v in m.group(1).lower(): errs.append('victim in appositive: ' + v)
    if 'undisclosed' not in mf: errs.append('no undisclosed')
    if 'which is not ' not in mf: errs.append('no relative clause')
    if ';' not in mf: errs.append('no semicolon')
    if re.search(r'["\u2018\u2019\u201c\u201d\']', mf): errs.append('quote/apostrophe in mf')
    for b in BANNED:
        if b in mf.lower(): errs.append('banned: ' + b)
    vn = seed.get('vehicle_naming', '')
    for w in WINK_LEX:
        if w in vn.lower(): errs.append('wink lex: ' + w)
    pageish = ' '.join([vn, seed.get('institution_credit', ''), seed.get('lane_spec', ''), seed.get('suppressor_text', '')]).lower()
    ir = seed.get('_intrinsic_relevance', '').lower().split()
    for i in range(len(ir) - 4):
        if ' '.join(ir[i:i+5]) in pageish:
            errs.append('intrinsic_relevance leaked'); break
    masked = mf.lower()
    for fr in FRAME: masked = masked.replace(fr, ' ')
    shs = shingles(masked)
    for sh in sorted(shs):
        if sh in prior: errs.append('prior shingle: ' + sh)
        if sh in batch: errs.append('batch shingle: ' + sh)
    batch |= shs
    print('%s: T=%d app=%d %s' % (seed['fact_id'], wc(mf), wc(m.group(1)) if m else -1, errs if errs else 'CLEAN'))
