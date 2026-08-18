import json
items = json.load(open(r'C:\Users\justi\Desktop\Magnolia\output\tmp_review_T33_T42.json', encoding='utf-8'))
for it in items:
    if it['fact_id'] not in ('T37','T38','T33','T34'): continue
    body = it['user_email'].split('\n\n',1)[1]
    paras = [p for p in body.split('\n\n')]
    print('==', it['fact_id'])
    for p in paras:
        print('  %3d | %s' % (len(p.split()), p.replace('\n',' / ')[:90]))
