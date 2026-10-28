#!/usr/bin/env python3
"""Actualiza data.json de A. Analytics con los pronósticos ★★★ de OddSlot.

Uso:
  python3 tools/update.py results   -> marca resultados y ✓/✗ de los partidos de HOY
  python3 tools/update.py close     -> cierre diario: resultados de AYER, historial,
                                       limpieza y carga de partidos de HOY y MAÑANA
Necesita: pip install beautifulsoup4 (y acceso de red a oddslot.com).
Las patas de los picks NO se evalúan aquí (lo hace quien ejecuta la tarea).
"""
import json, re, sys, unicodedata, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

ROOT = __file__.rsplit('/tools/', 1)[0]
DATA = ROOT + '/data.json'
TZ = ZoneInfo('Europe/Lisbon')
EXCL_TEAM = re.compile(r'\bU1\d\b|\bU2\d\b|\bII\b|Res\.|\bReserves?\b')
EXCL_LEAGUE = re.compile(r'U19|U20|U21|U23|Premier League 2|Development|Reserve|Non League|Women|Youth', re.I)


def fetch(day):
    req = urllib.request.Request('https://oddslot.com/odds/?day=' + day,
                                 headers={'User-Agent': 'Mozilla/5.0'})
    html = urllib.request.urlopen(req, timeout=150).read().decode('utf-8', 'replace')
    soup = BeautifulSoup(html, 'html.parser')
    m = re.search(r'BEST BETTING ODDS[A-Z ]*?\w+DAY,\s*(\d{1,2} [A-Z]+ \d{4})', re.sub(r'\s+', ' ', soup.get_text(' ')).upper())
    page_date = datetime.strptime(m.group(1).title(), '%d %B %Y').date() if m else None
    rows = []
    for r in soup.select('.odds-match'):
        league = ''
        box = r.find_parent(class_='drop-league')
        hd = box.select_one('.drop-league__header') if box else None
        if hd:
            league = re.sub(r'\s+', ' ', hd.get_text(' ', strip=True))
            league = re.sub(r'\s*:\s*', ': ', league, count=1)
            league = re.sub(r'\(\s*(\d+)\s*\)$', r'(\1)', league)
        node = r
        while node is not None and not league:
            sib = node.find_previous_sibling()
            while sib is not None:
                t = sib.get_text(' ', strip=True)
                if re.search(r'\(\d+\)$', t) and len(t) < 80:
                    league = t
                    break
                sib = sib.find_previous_sibling()
            node = node.parent
        league = re.sub(r'\s*\(\d+\)$', '', league)
        league = re.sub(r'^World:\s*', '', league)

        def team(sel):
            el = r.select_one(sel)
            if not el:
                return ''
            span = el.find('span')
            name = span.get_text(strip=True) if span else el.get_text(' ', strip=True)
            return re.sub(r'(FAVOURITE|DOUBLE CHANCE).*$', '', name).strip()
        home, away = team('.odds-match__team--home'), team('.odds-match__team--away')
        odds = []
        for o in r.select('.odds-match__odd'):
            sp = o.find('span')
            try:
                odds.append(float(sp.get_text(strip=True)))
            except Exception:
                pass
        tip_el = r.select_one('.odds-pred-short')
        tip = tip_el.get_text(' ', strip=True) if tip_el else ''
        time_el = r.select_one('.odds-match__time')
        tm = time_el.get_text(' ', strip=True) if time_el else ''
        ft = re.search(r'FT\s*(\d+)\s*-\s*(\d+)', tm)
        hm = re.match(r'^(\d\d):(\d\d)$', tm)
        rows.append(dict(league=league, home=home, away=away, odds=odds, tip=tip,
                         time=hm.group(0) if hm else None,
                         score=f'{ft.group(1)} - {ft.group(2)}' if ft else None,
                         ok=1 if '✓' in tip else (0 if '✗' in tip else None)))
    return page_date, rows


def norm(s):
    s = unicodedata.normalize('NFD', s).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    return re.sub(r'\b(fc|sc|cf|ac|club|de|the)\b', ' ', s).split()


def same(a, b):
    A, B = norm(a), norm(b)
    return bool(A) and bool(B) and (A == B or set(A) <= set(B) or set(B) <= set(A))


def find(rows, m):
    for x in rows:
        if same(x['home'], m['local']) and same(x['away'], m['visitante']):
            return x
    return None


def mark(m, x):
    if not x or not x['score']:
        return False
    t = re.sub(r' · [✓✗] (acertado|fallado)$', '', m['tendencia'])
    ok = x['ok']
    if ok is None:  # decidir con el marcador
        h, a = map(int, x['score'].split(' - '))
        body = t.replace('★★★ ', '')
        if body.startswith('Gana '):
            team_ = body[5:].split(' · ')[0]
            ok = int((h > a and same(team_, m['local'])) or (a > h and same(team_, m['visitante'])))
        elif ' o empate' in body:
            team_ = body.split(' o empate')[0]
            ok = int((h >= a and same(team_, m['local'])) or (a >= h and same(team_, m['visitante'])))
    if ok is not None:
        t += ' · ✓ acertado' if ok == 1 else ' · ✗ fallado'
    changed = m.get('resultado') != x['score'] or m['tendencia'] != t
    m['resultado'], m['tendencia'] = x['score'], t
    return changed


def to_match(x, day, pick_names):
    if not re.search(r'WIN|DC', x['tip']) or len(x['odds']) < 3 or not x['time']:
        return None
    if EXCL_TEAM.search(x['home'] + ' ' + x['away']) or EXCL_LEAGUE.search(x['league']):
        return None
    f = lambda v: f'{v:.2f}'.replace('.', ',')
    o1, ox, o2 = x['odds'][:3]
    if 'HOME WIN' in x['tip']:
        k = f"Gana {x['home']} · cuota {f(o1)}"
    elif 'AWAY WIN' in x['tip']:
        k = f"Gana {x['away']} · cuota {f(o2)}"
    elif 'HOME DC' in x['tip']:
        k = f"{x['home']} o empate · cuota ~{f(1 / (1 / o1 + 1 / ox))}"
    elif 'AWAY DC' in x['tip']:
        k = f"{x['away']} o empate · cuota ~{f(1 / (1 / o2 + 1 / ox))}"
    else:
        return None
    hh = int(x['time'][:2])
    d = day + timedelta(days=1) if hh < 6 else day
    m = dict(liga=x['league'], local=x['home'], visitante=x['away'], tendencia='★★★ ' + k,
             inicio=f"{d.isoformat()}T{x['time']}:00+00:00")
    if any(same(x['home'], n) for n in pick_names):
        m['pick'] = True
    return m


def add_day(d, rows, day):
    names = [l['partido'].split(' vs ')[0] for p in d['picks'] if p['estado'] == 'pendiente' for l in p['patas']]
    have = {(tuple(norm(m['local'])), tuple(norm(m['visitante']))) for m in d['partidos']}
    n = 0
    for x in rows:
        m = to_match(x, day, names)
        if m and (tuple(norm(m['local'])), tuple(norm(m['visitante']))) not in have:
            d['partidos'].append(m)
            n += 1
    return n


def main(mode):
    d = json.load(open(DATA, encoding='utf-8'))
    d.setdefault('historial_pronosticos', [])
    today = datetime.now(TZ).date()
    report = []
    if mode == 'results':
        pdate, rows = fetch('today')
        report.append(f'OddSlot today = {pdate}, filas = {len(rows)}')
        ch = sum(mark(m, find(rows, m)) for m in d['partidos'] if m['inicio'][:10] == today.isoformat())
        report.append(f'resultados nuevos/actualizados: {ch}')
    elif mode == 'close':
        yday = datetime.fromisoformat(d.get('actualizado', (today - timedelta(days=1)).isoformat())).date()
        if yday >= today:
            yday = today - timedelta(days=1)
        for key in ('yesterday', 'today'):
            pdate, rows = fetch(key)
            if pdate == yday:
                break
        report.append(f'AYER = {yday}, página usada = {pdate}')
        for m in d['partidos']:
            if m['inicio'][:10] == yday.isoformat():
                mark(m, find(rows, m))
        ps = [m for m in d['partidos'] if m['inicio'][:10] == yday.isoformat()]
        ok = sum('✓' in m['tendencia'] for m in ps)
        ko = sum('✗' in m['tendencia'] for m in ps)
        d['historial_pronosticos'] = [h for h in d['historial_pronosticos'] if h['fecha'] != yday.isoformat()]
        if ok + ko:
            d['historial_pronosticos'].append({'fecha': yday.isoformat(), 'ok': ok, 'ko': ko})
        d['historial_pronosticos'].sort(key=lambda h: h['fecha'], reverse=True)
        report.append(f'historial {yday}: {ok} ✓ / {ko} ✗')
        d['partidos'] = [m for m in d['partidos'] if m['inicio'][:10] > yday.isoformat()]
        _, rows_t = fetch('today')
        report.append(f'añadidos HOY: {add_day(d, rows_t, today)}')
        _, rows_m = fetch('tomorrow')
        report.append(f'añadidos MAÑANA: {add_day(d, rows_m, today + timedelta(days=1))}')
        d['actualizado'] = today.isoformat()
    json.dump(d, open(DATA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n'.join(report))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'results')
