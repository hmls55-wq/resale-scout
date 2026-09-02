import re, urllib.request
from collections import Counter
import scout
BASE='https://jmty.jp/s/area_portal/1005342?distance=50'
UA='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1'
items={}
for page in range(1,31):
    url=BASE if page==1 else f'{BASE}&page={page}'
    req=urllib.request.Request(url,headers={'User-Agent':UA})
    with urllib.request.urlopen(req,timeout=30) as r: html=r.read().decode('utf-8','replace')
    got=scout.extract_items(html)
    furn=[x for x in got if '/sale-fur/article-' in x.get('url','')]
    for x in furn: items[x['url']]=x
    print('PAGE',page,'ALL_PARSED',len(got),'FURNITURE',len(furn),'UNIQUE_FURN',len(items))
print('TOTAL_UNIQUE_FURNITURE',len(items))
loc=Counter()
unknown=[]
for x in items.values():
    text=' '.join([x.get('title',''),x.get('text','')])
    m=re.search(r'愛知県[　 ]*(名古屋市[^　\s]+|[^　\s]+市|[^　\s]+町|[^　\s]+村)',text)
    if m: loc[m.group(1)]+=1
    else: unknown.append(x['url'])
print('LOCATION_TEXT_FOUND',sum(loc.values()),'UNKNOWN',len(unknown))
print('TOP_LOCATIONS',loc.most_common(20))
print('SAMPLE_UNKNOWN',unknown[:10])
