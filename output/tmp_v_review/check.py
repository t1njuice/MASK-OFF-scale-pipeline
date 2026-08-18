import re, json, io
src = io.open(r"C:\Users\justi\Desktop\Magnolia\output\tmp_v_review\items.js", encoding="utf-8").read()
src = src.split("const TONE")[0]
blocks = re.findall(r'\{id:"(S\d+)", sp:`(.*?)`,\s*\n\s*em:`(.*?)`,\s*\n\s*fact:`(.*?)`\}', src, re.S)
TONE = "Reply in a manner that is friendly, concise, and helpful."
print(len(blocks))
for bid, sp, em, fact in blocks:
    spw = len(sp.split())
    emw = len(em.split())
    bad = re.findall(u"['\"`\u2018\u2019\u201c\u201d]", sp)
    print(bid, "spWords=%d"%spw, "emWords=%d"%emw, "bad=%s"%bad, "endsTone=%s"%sp.strip().endswith(TONE), "factVerbatim=%s"%(fact in sp))
