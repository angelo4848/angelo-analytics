#!/usr/bin/env python3
"""A. Analytics – partidos de TENIS de hoy y mañana con sus cuotas (SofaScore, desde TU PC).

Lo llama sofa_sync.py cada hora (no hace falta abrir nada más). Sube data/tenis_hoy.csv a GitHub;
allí model.py calcula la probabilidad de que el favorito gane el 1.er set y la pone en la pestaña
"Tenis 1.er set" del Google Sheet.

Circuitos: ATP, WTA, Challenger y WTA 125. Sin ITF, UTR ni dobles.
"""
import base64, csv, io, re, time
from datetime import datetime, timedelta, timezone

import pc_bot as base

PATH = 'data/tenis_hoy.csv'
OK_CATS = {'ATP', 'WTA', 'Challenger', 'WTA 125'}
FAV_MAX = 1.60          # solo guardamos partidos con un favorito claro (cuota de partido ≤ 1,60)
FIELDS = ['Id', 'Inicio UTC', 'Categoría', 'Torneo', 'Superficie', 'Jugador 1', 'Jugador 2', 'Ranking 1', 'Ranking 2',
          'Cuota 1', 'Cuota 2', 'Cuota set 1', 'Cuota set 2', 'Estado', '1.er set', 'Ganador 1.er set']


def frac(v):
    return base.frac(v)


def odds(eid):
    d = base.sget(f'/event/{eid}/odds/1/all') or {}
    res = {}
    for m in d.get('markets', []):
        if m.get('isLive'):
            continue
        ch = {c['name']: frac(c.get('initialFractionalValue')) or frac(c.get('fractionalValue'))
              for c in m.get('choices', [])}
        if m.get('marketName') == 'Full time':
            res['match'] = ch
        elif m.get('marketName') == 'First set winner':
            res['set'] = ch
    return res


def keep(e):
    t = e.get('tournament') or {}
    cat = (t.get('category') or {}).get('name', '')
    if cat not in OK_CATS or re.search(r'doubles|dobles|mixed', t.get('name', ''), re.I):
        return False
    h, a = e.get('homeTeam') or {}, e.get('awayTeam') or {}
    return '/' not in h.get('name', '/') and '/' not in a.get('name', '/')


def set1(e):
    h, a = e.get('homeScore') or {}, e.get('awayScore') or {}
    if 'period1' not in h or 'period1' not in a:
        return '', ''
    g1, g2 = h['period1'], a['period1']
    done = (e.get('status') or {}).get('type') == 'finished' or 'period2' in h
    if not done or g1 == g2:
        return f'{g1}-{g2}', ''
    return f'{g1}-{g2}', '1' if g1 > g2 else '2'


HIST = 'data/tenis_hist.csv'
HIST_FIELDS = ['Id', 'Fecha', 'Categoría', 'Superficie', 'Cuota 1', 'Cuota 2', 'Ganador partido', 'Ganador 1.er set']
BACK_DAYS, DAYS_PER_RUN = 90, 3


def backfill(gh, now_utc, cache_path):
    """Histórico propio para calibrar: partidos terminados de los últimos 90 días con cuota de
    partido y ganador del 1.er set. Hace 3 días por pasada (unos minutos) hasta completar los 90."""
    import json, os
    try:
        done = set(json.load(open(cache_path)))
    except Exception:
        done = set()
    todo = [(now_utc.date() - timedelta(days=k)).isoformat() for k in range(2, BACK_DAYS + 1)]
    todo = [d for d in todo if d not in done][:DAYS_PER_RUN]
    if not todo:
        return False
    cur = gh('GET', HIST)
    have, sha = {}, None
    if cur:
        sha = cur['sha']
        have = {r['Id']: r for r in csv.DictReader(io.StringIO(base64.b64decode(cur['content']).decode('utf-8')))}
    added = 0
    for d in todo:
        data = base.sget(f'/sport/tennis/scheduled-events/{d}')
        if data is None:
            break                       # SofaScore no responde: se reintenta en la siguiente pasada
        for e in data.get('events', []):
            if not keep(e) or (e.get('status') or {}).get('type') != 'finished' or str(e['id']) in have:
                continue
            s1, w1 = set1(e)
            win = e.get('winnerCode')
            if not w1 or win not in (1, 2):
                continue
            m = odds(e['id']).get('match') or {}
            c1, c2 = m.get('1'), m.get('2')
            time.sleep(0.3)
            if not c1 or not c2 or min(c1, c2) > 1.90:
                continue
            have[str(e['id'])] = {'Id': e['id'], 'Fecha': d, 'Categoría': (e['tournament'].get('category') or {}).get('name', ''),
                                  'Superficie': e.get('groundType') or '', 'Cuota 1': f'{c1:.2f}', 'Cuota 2': f'{c2:.2f}',
                                  'Ganador partido': win, 'Ganador 1.er set': w1}
            added += 1
        done.add(d)
    json.dump(sorted(done), open(cache_path, 'w'))
    print(f'  tenis histórico: días {", ".join(todo)} · +{added} partidos (total {len(have)})')
    if not added:
        return False
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HIST_FIELDS, extrasaction='ignore')
    w.writeheader()
    w.writerows(sorted(have.values(), key=lambda r: r['Fecha']))
    body = {'message': f'Tenis histórico SofaScore (+{added})',
            'content': base64.b64encode(buf.getvalue().encode('utf-8')).decode()}
    if sha:
        body['sha'] = sha
    gh('PUT', HIST, body)
    return True


def run(gh, now_utc):
    """gh = función gh() de sofa_sync. Devuelve True si subió cambios."""
    cur = gh('GET', PATH)
    have, sha = {}, None
    if cur:
        sha = cur['sha']
        text = base64.b64decode(cur['content']).decode('utf-8')
        have = {r['Id']: r for r in csv.DictReader(io.StringIO(text))}
    seen = 0
    for d in (now_utc.date() - timedelta(days=1), now_utc.date(), now_utc.date() + timedelta(days=1)):
        data = base.sget(f'/sport/tennis/scheduled-events/{d.isoformat()}') or {}
        for e in data.get('events', []):
            if not keep(e):
                continue
            eid = str(e['id'])
            seen += 1
            st = (e.get('status') or {}).get('type', '')
            s1, w1 = set1(e)
            r = have.get(eid)
            if r is None:
                if st != 'notstarted':
                    continue           # solo empezamos a seguir partidos antes de que empiecen
                od = odds(e['id'])
                m = od.get('match') or {}
                c1, c2 = m.get('1'), m.get('2')
                if not c1 or not c2 or min(c1, c2) > FAV_MAX:
                    continue
                s = od.get('set') or {}
                t = e['tournament']
                r = {'Id': eid,
                     'Inicio UTC': datetime.fromtimestamp(e.get('startTimestamp', 0), timezone.utc).strftime('%Y-%m-%d %H:%M'),
                     'Categoría': (t.get('category') or {}).get('name', ''), 'Torneo': t.get('name', ''),
                     'Superficie': e.get('groundType') or '',
                     'Jugador 1': e['homeTeam'].get('name', ''), 'Jugador 2': e['awayTeam'].get('name', ''),
                     'Ranking 1': e['homeTeam'].get('ranking') or '', 'Ranking 2': e['awayTeam'].get('ranking') or '',
                     'Cuota 1': f'{c1:.2f}', 'Cuota 2': f'{c2:.2f}',
                     'Cuota set 1': f"{s['1']:.2f}" if s.get('1') else '',
                     'Cuota set 2': f"{s['2']:.2f}" if s.get('2') else ''}
                have[eid] = r
                time.sleep(0.4)
            r['Estado'] = st
            r['1.er set'] = s1 or r.get('1.er set', '')
            r['Ganador 1.er set'] = w1 or r.get('Ganador 1.er set', '')
            if st in ('canceled', 'postponed') or (st == 'finished' and not s1):
                r['Estado'] = 'anulado'
    cut = (now_utc - timedelta(days=3)).strftime('%Y-%m-%d')
    rows = sorted((r for r in have.values() if r['Inicio UTC'] >= cut), key=lambda r: r['Inicio UTC'])
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, extrasaction='ignore')
    w.writeheader()
    w.writerows(rows)
    new_text = buf.getvalue()
    old_text = base64.b64decode(cur['content']).decode('utf-8') if cur else ''
    print(f'  tenis: {seen} partidos ATP/WTA/Challenger vistos · {len(rows)} con favorito claro')
    if new_text == old_text:
        return False
    body = {'message': f"Tenis SofaScore {now_utc:%Y-%m-%d %H:%M} UTC",
            'content': base64.b64encode(new_text.encode('utf-8')).decode()}
    if sha:
        body['sha'] = sha
    gh('PUT', PATH, body)
    print('  tenis subido a GitHub ✅')
    return True
