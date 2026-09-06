import json, ssl, re, hashlib, time, urllib.request, urllib.error

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) Gecko/20100101 Firefox/155.0'
BASE = 'https://panel.cloudblaze.org'
CTX = ssl.create_default_context()
jar = {}

def grab_set_cookie(resp):
    for k, v in resp.headers.items():
        if k.lower() == 'set-cookie':
            name = v.split(';')[0].split('=', 1)[0]
            val = v.split(';')[0].split('=', 1)[1]
            if val.lower() != 'deleted':
                jar[name] = val
                print('  set-cookie:', name, '=', val[:40])

def req(path, headers=None, data=None, cookie=True):
    h = {'User-Agent': UA, 'Accept': 'application/json'}
    if headers: h.update(headers)
    if cookie and jar: h['Cookie'] = '; '.join(f'{k}={v}' for k, v in jar.items())
    r = urllib.request.Request(BASE + path, headers=h, data=data)
    return urllib.request.urlopen(r, context=CTX, timeout=30)

def sha256_hex(s):
    return hashlib.sha256(s.encode()).hexdigest()

def get_challenge():
    try:
        req('/api/client/servers')
        print('no challenge!')
        return None
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')
        grab_set_cookie(e)
        m = re.search(r"window\.__BPC=\{(.*?)\};", body)
        if not m:
            print('no BPC. body head:', body[:200].replace(chr(10),' '))
            return None
        raw = m.group(1)
        kv = {
            'sid': re.search(r"sid:'([^']*)'", raw).group(1),
            'non': re.search(r"non:'([^']*)'", raw).group(1),
            'dif': int(re.search(r"dif:(\d+)", raw).group(1)),
            'ts': re.search(r"ts:(\d+)", raw).group(1),
        }
        print('challenge:', kv)
        return kv

kv = get_challenge()
if kv is None:
    raise SystemExit

payload = {
    'sid': kv['sid'],
    'sw':'1920','sh':'1080','aw':'1920','ah':'1040','cd':'24','pr':'1',
    'cf':'8f4a2b1c', 'af':'3c9d7e2a', 'ff':'1b6e5a9d',
    'wr':'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)',
    'wv':'Google Inc. (NVIDIA)',
    'pl':'Win32', 'hc':'16', 'dm':'8', 'mt':'0',
    'tz':'Asia/Shanghai', 'to':'-480', 'ln':'en-US,en',
    'ss':'1','ls':'1','id':'1','wg':'1','ck':'1','dn':'','hp':'1','pc':'5',
    'cr':'1','pm':'1','wd':'0','ph':'0','nm':'0','se':'0','pp':'0','pw':'0','hl':'0',
    'ct':'1','nc':'0','bp':'0','nl':'0','mb':'0',
}
order = ['cf','wv','wr','ff','af','pl','tz','sw','sh','cd','hc']
commit = sha256_hex('|'.join(str(payload[k]) for k in order))
print('commit:', commit[:16], '...')

dif = int(kv['dif'])
prefix = '0' * dif
n = 0
t0 = time.time()
while True:
    h = sha256_hex(f"{kv['sid']}:{kv['non']}:{commit}:{n}")
    if h.startswith(prefix):
        break
    n += 1
print('pow solved n=%d hash=%s... in %.2fs' % (n, h[:16], time.time() - t0))
payload['pow'] = h
payload['pn'] = str(n)
payload['et'] = '900'
payload['tm'] = '0'; payload['oe'] = '0'; payload['tp'] = '0'

body = json.dumps(payload).encode()
try:
    r = req('/__bp_verify', headers={
        'Content-Type': 'application/json', 'Origin': BASE, 'Referer': BASE + '/',
        'Accept': '*/*', 'X-Requested-With': 'XMLHttpRequest',
    }, data=body)
    print('verify status:', r.status)
    grab_set_cookie(r)
    print('verify body:', r.read(200)[:120])
except urllib.error.HTTPError as e:
    print('verify HTTP', e.code)
    grab_set_cookie(e)
    print('verify body:', e.read(300)[:200])

# ---- 5. 带新 cookies 访问 API ----
time.sleep(1)
try:
    r = req('/api/client/servers')
    d = json.loads(r.read())
    data = d.get('data', [])
    print('API OK', r.status, '| 服务器数:', len(data))
    for s in data:
        a = s['attributes']
        print(' ', a['uuid'], '|', a['name'], '|', a['node'], '|', a.get('status'))
except urllib.error.HTTPError as e:
    print('API HTTP', e.code)
    grab_set_cookie(e)
    print('API body:', e.read(300)[:200])

cookies = [{'name': k, 'value': v} for k, v in jar.items()]
json.dump(cookies, open('/root/cloudblaze/cookies_server.txt', 'w'), indent=2)
print('saved', len(cookies), 'cookies ->', [c['name'] for c in cookies])
