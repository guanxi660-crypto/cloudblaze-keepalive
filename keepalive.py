#!/root/ouipanel/venv/bin/python
# -*- coding: utf-8 -*-
"""CloudBlaze 实例保活：探测 + 离线自动拉起
复用 cloudblaze_api.py 的 ddos-guard 挑战 + cookie 逻辑。
cron 每 5 分钟: */5 * * * * /root/ouipanel/venv/bin/python /root/cloudblaze/keepalive.py >> /root/cloudblaze/keepalive-cron.log 2>&1
"""
import json, os, re, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cloudblaze_api as cb

SERVER_ID_FILE = os.path.join(cb.BASE_DIR, 'server_id')
LOG_FILE = os.path.join(cb.BASE_DIR, 'keepalive.log')

# Telegram 通知（可选）
TG_API_KEY = ''
_tgkey = '/root/cloudblaze/.tgkey'
if os.path.exists(_tgkey):
    TG_API_KEY = open(_tgkey).read().strip()
elif os.path.exists('/root/ouipanel/keepalive.py'):
    m = re.search(r"TG_API_KEY\s*=\s*'([^']+)'", open('/root/ouipanel/keepalive.py').read())
    if m:
        TG_API_KEY = m.group(1)
TG_CHAT_ID = '8600129634'
TG_API = 'https://api.telegram.org/bot' + TG_API_KEY + '/sendMessage'

def log(msg):
    line = '[%s] %s' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg)
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(line + '\n')
    except Exception:
        pass

def tg_notify(text):
    if not TG_API_KEY:
        return False
    try:
        req = urllib.request.Request(TG_API, method='POST',
            headers={'Content-Type': 'application/json'},
            data=json.dumps({'chat_id': TG_CHAT_ID, 'text': text,
                             'disable_web_page_preview': True}).encode())
        r = urllib.request.urlopen(req, timeout=15)
        return r.status == 200
    except Exception as ex:
        log('TG 通知失败: %s' % ex)
        return False

def main():
    if not os.path.exists(cb.TOKEN_FILE):
        log('缺少 API key：%s' % cb.TOKEN_FILE)
        return 1
    if not os.path.exists(SERVER_ID_FILE):
        log('缺少服务器 UUID：%s' % SERVER_ID_FILE)
        return 1
    sid = open(SERVER_ID_FILE).read().strip()
    cb.load_cookies()

    try:
        st, body = None, None
        try:
            resp = cb.api('/api/client/servers/' + sid + '/resources')
            body = resp.read().decode('utf-8', 'replace')
        except Exception as ex:
            st = getattr(ex, 'code', -1)
            body = '%s: %s' % (type(ex).__name__, ex)
        if st is None:
            st = 200
        if st != 200:
            log('探测失败 HTTP %s: %s' % (st, body[:200]))
            tg_notify('[CloudBlaze] 探测失败 HTTP %s' % st)
            return 1
        d = json.loads(body)
        attrs = d.get('attributes') or d.get('data', {}).get('attributes', {})
        state = attrs.get('current_state')
        suspended = attrs.get('is_suspended', False)
    except Exception as e:
        log('解析响应失败: %s %s' % (e, body[:200]))
        return 1

    # ---- TCP 端口探测（主依据）----
    # FAKE_MC_STARTUP=false 时 NanoLimbo 输出原版日志，面板状态恒为 starting，
    # 用面板 current_state 探测会永远判定离线 -> 盲目 start。
    # 改为直接 TCP 探测 MC 端口：通 = 在线。
    import socket
    MC_HOST, MC_PORT = 'free.cloudblaze.org', 36193
    def _port_open():
        try:
            s = socket.create_connection((MC_HOST, MC_PORT), timeout=6)
            s.close()
            return True
        except Exception:
            return False
    if _port_open():
        log('在线 (TCP %s:%s 可连)，无需操作' % (MC_HOST, MC_PORT))
        return 0
    if state == 'starting':
        log('端口 %s:%s 不通但面板 starting（可能仍在启动），跳过本次' % (MC_HOST, MC_PORT))
        return 0
    if state == 'running':
        log('面板 running 但端口 %s:%s 不通（异常），跳过本次' % (MC_HOST, MC_PORT))
        return 0
    if suspended:
        log('实例被 suspend，start 无效，跳过（需人工处理）')
        tg_notify('[CloudBlaze] 实例被 suspend，自动拉起无效，需人工处理')
        return 2

    log('状态=%s，尝试拉起 start ...' % state)
    try:
        resp = cb.api('/api/client/servers/' + sid + '/power', method='POST',
                      data={'signal': 'start'})
        st2 = resp.status
        ok = st2 in (200, 201, 202, 204)
    except Exception as ex:
        st2 = getattr(ex, 'code', -1)
        ok = False
    if ok:
        log('start 响应 HTTP %s 成功' % st2)
        tg_notify('[CloudBlaze] 实例离线，已自动拉起成功 (start -> HTTP %s)' % st2)
        return 0
    else:
        log('start 响应 HTTP %s 失败' % st2)
        tg_notify('[CloudBlaze] 实例离线，拉起失败 (start -> HTTP %s)' % st2)
        return 3

if __name__ == '__main__':
    sys.exit(main())
