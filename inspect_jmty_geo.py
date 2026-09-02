import re
import urllib.request
from html import unescape
URLS=['https://jmty.jp/s/area_portal/1005342?distance=50','https://jmty.jp/aichi/sale-fur?distance=50']
UA='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1'
for url in URLS:
    req=urllib.request.Request(url,headers={'User-Agent':UA})
    with urllib.request.urlopen(req,timeout=30) as r: html=r.read().decode('utf-8','replace')
    print('\n'+'='*100+'\nURL '+url+' bytes='+str(len(html)))
    pats=['area_portal','distance','latitude','longitude','lat','lng','geo','location','areaId','area_id','1005342']
    for p in pats:
        ms=list(re.finditer(p,html,re.I)); print('PATTERN',p,'COUNT',len(ms))
        for m in ms[:5]:
            s=max(0,m.start()-180); e=min(len(html),m.end()+300)
            print(unescape(re.sub(r'\s+',' ',html[s:e]))); print('---')
