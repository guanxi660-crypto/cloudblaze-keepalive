#!/root/ouipanel/venv/bin/python
"""Cloudblaze API 客户端：自动过 ddos-guard 挑战 + 调用 Pterodactyl API
用法: cloudblaze_api.py status|resources|power [on|off|restart|kill] [uuid]
"""
import json, os, ssl, re, hashlib, time, sys, urllib.request, urllib.error
BASE_DIR = os.environ.get('CB_HOME', '/root/cloudblaze')

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) Gecko/20100101 Firefox/155.0'
BASE = 'https://panel.cloudblaze.org'
CTX = ssl.create_default_context()
COOKIE_FILE = os.path.join(BASE_DIR, 'cookies_server.txt')
TOKEN_FILE = os.path.join(BASE_DIR, '.apitoken')

jar = {}

def load_cookies():
    try:
        for c in json.load(open(COOKIE_FILE)):
            jar[c['name']] = c['value']
    except Exception:
        pass

def save_cookies():
    json.dump([{'name': k, 'value': v} for k, v in jar.items()],
              open(COOKIE_FILE, 'w'), indent=2)

def grab_set_cookie(resp):
    for k, v in resp.headers.items():
        if k.lower() == 'set-cookie':
            name = v.split(';')[0].split('=', 1)[0]
            val = v.split(';')[0].split('=', 1)[1]
            if val.lower() != 'deleted':
                jar[name] = val

def req(path, headers=None, data=None):
    h = {'User-Agent': UA, 'Accept': 'application/json'}
    if headers: h.update(headers)
    if jar: h['Cookie'] = '; '.join(f'{k}={v}' for k, v in jar.items())
    r = urllib.request.Request(BASE + path, headers=h, data=data)
    return urllib.request.urlopen(r, context=CTX, timeout=30)

def sha256_hex(s):
    return hashlib.sha256(s.encode()).hexdigest()

def solve_challenge():
    """当前 cookies 已失效时触发并解决 ddos-guard 挑战。成功返回 True。"""
    try:
        req('/api/client')   # cookies 有效 -> 非 403，无需挑战
        return True
    except urllib.error.HTTPError as e:
        if e.code != 403:
            return True      # 已放行（401/404 等应用层错误）
        body = e.read().decode('utf-8', 'replace')
        grab_set_cookie(e)
        m = re.search(r'window\.__BPC=\{(.*?)\};', body)
        if not m:
            return False
        raw = m.group(1)
        try:
            sid = re.search(r"sid:'([^']*)'", raw).group(1)
            non = re.search(r"non:'([^']*)'", raw).group(1)
            dif = int(re.search(r'dif:(\d+)', raw).group(1))
        except Exception:
            return False
        payload = {
            'sid': sid,
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
        prefix = '0' * dif
        n = 0
        while True:
            h = sha256_hex(f'{sid}:{non}:{commit}:{n}')
            if h.startswith(prefix): break
            n += 1
        payload.update({'pow': h, 'pn': str(n), 'et': '900',
                        'tm': '0', 'oe': '0', 'tp': '0'})
        r = req('/__bp_verify', headers={
            'Content-Type': 'application/json', 'Origin': BASE, 'Referer': BASE + '/',
            'Accept': '*/*', 'X-Requested-With': 'XMLHttpRequest'},
            data=json.dumps(payload).encode())
        grab_set_cookie(r)
        save_cookies()
        return True

def api(path, method='GET', data=None):
    tok = open(TOKEN_FILE).read().strip()
    h = {'Authorization': 'Bearer ' + tok,
         'X-Requested-With': 'XMLHttpRequest'}
    if data is not None:
        h['Content-Type'] = 'application/json'
        body = json.dumps(data).encode()
    else:
        body = None
    try:
        return req(path, headers=h, data=body)
    except urllib.error.HTTPError as e:
        if e.code != 403:
            raise
        if not solve_challenge():   # 403 -> 解挑战 -> 重试一次
            raise
        return req(path, headers=h, data=body)

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    load_cookies()
    uuid = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd == 'status':
        d = json.loads(api('/api/client').read())
        for s in d.get('data', []):
            a = s['attributes']
            print(f"{a['uuid']} | {a['name']} | {a['node']} | status={a.get('status')}")
            try:
                r = json.loads(api(f"/api/client/servers/{a['uuid']}/resources").read())
                at = r.get('attributes', {})
                print('   state:', at.get('current_state'), '| cpu:', at.get('cpu'),
                      '| mem:', at.get('memory'), '/', at.get('memory_limit'),
                      '| disk:', at.get('disk'), '/', at.get('disk_limit'))
            except Exception as ex:
                print('   resources err:', ex)
    elif cmd == 'resources':
        r = json.loads(api(f'/api/client/servers/{uuid}/resources').read())
        print(json.dumps(r.get('attributes', {}), indent=2))
    elif cmd == 'power':
        action = sys.argv[2]
        target = sys.argv[3]
        r = api(f'/api/client/servers/{target}/power', method='POST', data={'signal': action})
        print('power', action, '->', r.status)

if __name__ == '__main__':
    main()
