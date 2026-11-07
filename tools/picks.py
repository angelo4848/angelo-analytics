#!/usr/bin/env python3
"""Evalúa solo las patas de los picks pendientes de data.json con marcadores de ESPN (sin Claude).

Uso: python3 tools/picks.py
Mercados que entiende (combinables con " + "):
  "Victoria X" · "X o empate" · "Empate" · "menos/más de N,5 goles" · "ambos marcan (sí/no)"
Si no encuentra el partido terminado o no entiende el mercado, deja la pata pendiente.
"""
import json, re, sys, urllib.request
from datetime import date, timedelta

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from update import DATA, TZ, same, norm  # noqa: E402
from datetime import datetime


def espn(day):
    url = f'https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard?dates={day:%Y%m%d}&limit=900'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    out = []
    for e in json.load(urllib.request.urlopen(req, timeout=60)).get('events', []):
        c = e['competitions'][0]
        if not c['status']['type'].get('completed'):
            continue
        t = {x['homeAway']: x for x in c['competitors']}
        try:
            out.append((t['home']['team']['displayName'], t['away']['team']['displayName'],
                        int(t['home']['score']), int(t['away']['score'])))
        except (KeyError, ValueError):
            pass
    return out


def find(games, partido):
    if ' vs ' not in partido:
        return None
    a, b = [s.strip() for s in partido.split(' vs ', 1)]
    for h, w, hs, ws in games:
        if same(a, h) and same(b, w):
            return hs, ws
    for h, w, hs, ws in games:          # basta con que coincida uno si el otro se parece
        if (same(a, h) or same(b, w)) and (set(norm(a)) & set(norm(h)) or set(norm(b)) & set(norm(w))):
            return hs, ws
    return None


def judge(mercado, local, visit, hs, ws):
    tot = hs + ws
    for part in [p.strip() for p in mercado.split('+')]:
        low = part.lower()
        m = re.search(r'(menos|más|mas) de (\d+)[,.]5 goles', low)
        if m:
            n = int(m.group(2))
            ok = tot <= n if m.group(1) == 'menos' else tot > n
        elif 'ambos marcan' in low:
            yes = 'no' not in low.split('ambos marcan', 1)[1]
            ok = (hs > 0 and ws > 0) == yes
        elif low.startswith('victoria '):
            team = part[9:].strip()
            if same(team, local):
                ok = hs > ws
            elif same(team, visit):
                ok = ws > hs
            else:
                return None
        elif ' o empate' in low:
            team = part[:low.index(' o empate')].strip()
            if same(team, local):
                ok = hs >= ws
            elif same(team, visit):
                ok = ws >= hs
            else:
                return None
        elif low == 'empate':
            ok = hs == ws
        else:
            return None
        if not ok:
            return False
    return True


def from_registry(fecha, partido):
    import csv, os, re
    path = os.path.join(os.path.dirname(DATA), 'app.csv')
    if ' vs ' not in partido or not os.path.exists(path):
        return None
    a, b = [x.strip() for x in partido.split(' vs ', 1)]
    with open(path, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if row['Fecha'] == fecha and same(a, row['Local']) and same(b, row['Visitante']):
                m = re.match(r'(\d+) - (\d+)', row.get('Resultado') or '')
                return (int(m.group(1)), int(m.group(2))) if m else None
    return None


def main():
    d = json.load(open(DATA, encoding='utf-8'))
    today = datetime.now(TZ).date()
    cache, report, changed = {}, [], False
    for p in d.get('picks', []):
        if p.get('estado') != 'pendiente':
            continue
        f = date.fromisoformat(p['fecha'])
        if f >= today + timedelta(days=1):
            continue
        games = []
        for day in (f, f + timedelta(days=1)):
            if day not in cache:
                try:
                    cache[day] = espn(day)
                except Exception as ex:
                    report.append(f'ESPN {day}: {ex}')
                    cache[day] = []
            games += cache[day]
        for l in p['patas']:
            if l.get('estado') in ('ganada', 'perdida'):
                continue
            r = find(games, l['partido'])
            if not r:  # ligas sin ESPN: resultado del registro (OddSlot / SofaScore del portátil)
                r = from_registry(p['fecha'], l['partido'])
            if not r:
                continue
            local, visit = [s.strip() for s in l['partido'].split(' vs ', 1)]
            ok = judge(l['mercado'], local, visit, *r)
            if ok is None:
                report.append(f"no entiendo el mercado: {l['mercado']}")
                continue
            l['resultado'] = f'{r[0]} - {r[1]}'
            l['estado'] = 'ganada' if ok else 'perdida'
            changed = True
            report.append(f"{p['fecha']} {l['partido']} {l['resultado']} → {l['estado']}")
        est = [l.get('estado') for l in p['patas']]
        if 'perdida' in est:
            p['estado'] = 'perdida'
        elif all(e == 'ganada' for e in est):
            p['estado'] = 'ganada'
        if p['estado'] != 'pendiente':
            report.append(f"pick {p['fecha']}: {p['estado']}")
    if changed:
        json.dump(d, open(DATA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n'.join(report) or 'picks: nada que actualizar')


if __name__ == '__main__':
    main()
