#!/usr/bin/env python3
"""A. Analytics – RELOJ para GitHub (corre en el VPS, 24/7).

GitHub (plan gratis) retrasa o se salta las tareas programadas. Este programa, en el VPS, le dice a
GitHub cuándo actualizar (hora de Lisboa):
  · cada hora, a los :50  -> resultados + estadísticas + modelo + Google Sheet
  · 01:20                 -> cierre del día
  · 01:45                 -> pick del día (Telegram + app)
  · lunes y jueves 04:17  -> histórico de 5 años y calibración
Necesita en bot_config.txt: GITHUB_TOKEN=... con permisos del repositorio angelo-analytics:
  Contents: Read and write  +  Actions: Read and write
"""
import json, os, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = 'angelo4848/angelo-analytics'
STATE = os.path.join(HERE, 'github_reloj_state.json')
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo('Europe/Lisbon')
except Exception:
    TZ = timezone.utc


def token():
    p = os.path.join(HERE, 'bot_config.txt')
    if os.path.exists(p):
        for line in open(p, encoding='utf-8'):
            if line.strip().startswith('GITHUB_TOKEN='):
                return line.split('=', 1)[1].strip()
    return os.environ.get('GITHUB_TOKEN', '')


def dispatch(workflow, inputs=None):
    body = {'ref': 'main'}
    if inputs:
        body['inputs'] = inputs
    req = urllib.request.Request(f'https://api.github.com/repos/{REPO}/actions/workflows/{workflow}/dispatches',
                                 data=json.dumps(body).encode(), method='POST',
                                 headers={'Authorization': f'Bearer {token()}', 'User-Agent': 'aa-reloj',
                                          'Accept': 'application/vnd.github+json'})
    try:
        urllib.request.urlopen(req, timeout=30)
        return True
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            print('  ❌ GitHub rechazó la orden: el token necesita "Actions: Read and write" '
                  '(y "Contents: Read and write") para angelo-analytics.')
        else:
            print('  ❌ GitHub error', e.code)
    except Exception as ex:
        print('  ❌ sin conexión:', str(ex)[:80])
    return False


JOBS = [  # (nombre, condición(hora local), workflow, inputs)
    ('cierre', lambda t: t.hour == 1 and t.minute >= 20, 'app-update.yml', {'modo': 'close'}),
    ('pick', lambda t: t.hour == 1 and t.minute >= 45, 'daily-pick.yml', None),
    ('pick-respaldo', lambda t: t.hour == 7 and t.minute >= 0, 'daily-pick.yml', None),
    ('historico', lambda t: t.weekday() in (0, 3) and t.hour == 4 and t.minute >= 17, 'backtest.yml', None),
]


def main():
    if not token():
        sys.exit('Falta GITHUB_TOKEN en bot_config.txt')
    print('A. Analytics · Reloj de GitHub en marcha. Deja esta ventana abierta (Ctrl+C para parar).')
    try:
        st = json.load(open(STATE))
    except Exception:
        st = {}
    while True:
        t = datetime.now(TZ)
        day, hour = t.strftime('%Y-%m-%d'), t.strftime('%Y-%m-%d %H')
        if t.minute >= 50 and st.get('resultados') != hour:   # cada hora
            ok = dispatch('app-update.yml', {'modo': 'results'})
            print(t.strftime('%H:%M'), 'resultados', '✅' if ok else '')
            st['resultados'] = hour
        for name, cond, wf, inputs in JOBS:
            if cond(t) and st.get(name) != day:
                ok = dispatch(wf, inputs)
                print(t.strftime('%H:%M'), name, '✅' if ok else '')
                st[name] = day
        json.dump(st, open(STATE, 'w'))
        time.sleep(60)


if __name__ == '__main__':
    main()
