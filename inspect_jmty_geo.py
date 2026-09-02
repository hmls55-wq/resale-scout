import re, urllib.request
from html import unescape
url='https://jmty.jp/s/area_portal/1005342?distance=50'
req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1'})
with urllib.request.urlopen(req,timeout=30) as r: html=r.read().decode('utf-8','replace')
print('TITLE',re.search(r'<title>(.*?)</title>',html,re.S).group(1).strip())
forms=re.findall(r'<form[^>]+action=[\"\']([^\"\']*area_portal/search[^\"\']*)[\"\'][^>]*>(.*?)</form>',html,re.S|re.I)
print('CATEGORY_FORMS',len(forms))
for action,body in forms:
    print('ACTION',action)
    for tag in re.findall(r'<input[^>]+>',body,re.I):
        n=re.search(r'name=[\"\']([^\"\']+)',tag,re.I); v=re.search(r'value=[\"\']([^\"\']*)',tag,re.I); t=re.search(r'type=[\"\']([^\"\']+)',tag,re.I)
        if n: print('INPUT',n.group(1),'VALUE',v.group(1) if v else '','TYPE',t.group(1) if t else '')
    for tag in re.findall(r'<button[^>]*>|<select[^>]*>',body,re.I): print('CONTROL',unescape(tag))
    print('BODY_SNIPPET',unescape(re.sub(r'\s+',' ',body))[:5000])
