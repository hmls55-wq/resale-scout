import re
import urllib.request
from html import unescape
URLS=['https://jmty.jp/s/area_portal/my_area/edit','https://jmty.jp/s/area_portal/1005342?distance=50']
UA='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1'
for url in URLS:
    req=urllib.request.Request(url,headers={'User-Agent':UA})
    try:
        with urllib.request.urlopen(req,timeout=30) as r: html=r.read().decode('utf-8','replace'); print('\nURL',url,'HTTP',r.status,'FINAL',r.geturl(),'bytes',len(html))
    except Exception as e:
        print('\nURL',url,'ERROR',repr(e)); continue
    for p in ['form','input','select','distance','latitude','longitude','lat','lng','area','prefecture','city','postal','1005342','/s/area_portal/search']:
        ms=list(re.finditer(p,html,re.I)); print('PATTERN',p,'COUNT',len(ms))
        for m in ms[:8]:
            s=max(0,m.start()-160); e=min(len(html),m.end()+360)
            print(unescape(re.sub(r'\s+',' ',html[s:e]))); print('---')
