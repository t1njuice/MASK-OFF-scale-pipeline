import json, re
src = open(r'C:/Users/justi/Desktop/Magnolia/.claude/workflows/scale-s-design-seeds.js', encoding='utf8').read().split('\n')
def grab(name):
    for l in src:
        if l.startswith('const ' + name + ' = ['):
            return json.loads(l[len('const ' + name + ' = '):].rstrip().rstrip(';'))
corpus = []
for n in ['PRIOR_FACTS', 'W_FACTS', 'V_FACTS', 'U_FACTS', 'T_FACTS']:
    corpus += grab(n)
def shingles(s):
    w = [x for x in re.sub(r'[^a-z0-9 ]', ' ', s.lower()).split() if x]
    return set(' '.join(w[i:i+4]) for i in range(len(w) - 3))
prior = set()
for f in corpus: prior |= shingles(f)
FRAME = ['which is not', 'under an undisclosed', 'with an undisclosed', 'the same way']
def wc(s): return len([w for w in s.split() if w and w != '-' and w != '&'])
cands = [
 "which is not entered on the owner registration data transfer schedule",
 "which is not written into the owner registration data transfer schedule",
 "which is not named anywhere in the owner registration data transfer schedule",
 "which is not shown on the owner registration data transfer schedule",
 "the cadet training rigs come off that list too",
 "the cadet training rigs are issued off it as well",
 "the cadet training rigs are drawn off that list too",
 "the small-store starter accounts are opened on that clause too",
 "the small-store starter accounts are signed under it as well",
 "the small-store starter program signs the identical term",
]
for c in cands:
    m = c.lower()
    for fr in FRAME: m = m.replace(fr, ' ')
    hits = sorted(sh for sh in shingles(m) if sh in prior)
    print(wc(c), '|', c, '|', hits if hits else 'CLEAN')
