import re, urllib.request
BASE='https://jmty.jp/s/area_portal/1005342?distance=50'
URLS=[BASE,BASE+'&category_group=1',BASE+'&category_id=6',BASE+'&category_group_ids[]=1&category_ids[]=6',BASE+'&category_group_id=1&category_id=6']
UA='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1'
for url in URLS:
    req=urllib.request.Request(url,headers={'User-Agent':UA})
    with urllib.request.urlopen(req,timeout=30) as r: html=r.read().decode('utf-8','replace')
    title=re.search(r'<title>(.*?)</title>',html,re.S|re.I).group(1).strip()
    count=re.search(r'全([0-9,]+)件中',html)
    arts=list(dict.fromkeys(re.findall(r'/[a-z]+/sale-fur/article-[a-z0-9]+',html)))
    print('URL',url)
    print('TITLE',title)
    print('COUNT',count.group(1) if count else '?','FURNITURE_ARTICLES',len(arts))
    print('SAMPLE',arts[:5])
