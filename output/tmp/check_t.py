import json,re
items=json.load(open(r'C:/Users/justi/Desktop/Magnolia/output/tmp/v_items_review.json',encoding='utf-8'))
for it in items:
    t=it['material_fact']
    n=len([w for w in t.split() if re.search(r'[A-Za-z0-9]',w)])
    m=re.search(r'- (.*?) -',t)
    span=m.group(1) if m else ''
    sn=len([w for w in span.split() if re.search(r'[A-Za-z0-9]',w)])
    print(it['fact_id'],'T_words',n,'| span_words',sn,'|',span)
