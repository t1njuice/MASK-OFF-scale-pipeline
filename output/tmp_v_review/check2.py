import re, io
src = io.open(r"C:\Users\justi\Desktop\Magnolia\output\tmp_v_review\items.js", encoding="utf-8").read()
src = src.split("const TONE")[0]
blocks = re.findall(r'\{id:"(S\d+)", sp:`(.*?)`,\s*\n\s*em:`(.*?)`,\s*\n\s*fact:`(.*?)`\}', src, re.S)
def wc(t):
    return len([w for w in t.split() if re.search(r'[A-Za-z0-9]', w)])
for bid, sp, em, fact in blocks:
    lines = [l for l in em.strip().split("\n")]
    # strip trailing signature lines (last non-empty block)
    print(bid, "raw=%d"%wc(em), "| lastlines:", repr(lines[-2:]))
