#!/usr/bin/env python3
"""Mantiene app.csv: registro acumulado, partido a partido, de los ★★★ y su pronóstico.

Uso:
  python3 tools/export_csv.py            -> añade/actualiza con data.json + estadísticas de ESPN
  python3 tools/export_csv.py --backfill -> además recorre el historial de git (una vez)
  python3 tools/export_csv.py --days N   -> busca estadísticas ESPN de los últimos N días (def. 4)
El Google Sheet "APP" lo importa con IMPORTDATA. Todo corre en GitHub Actions, sin Claude.
"""
import csv, json, os, re, subprocess, sys, urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from update import same  # noqa: E402

ROOT = os.path.dirname(HERE)
DATA, OUT = os.path.join(ROOT, 'data.json'), os.path.join(ROOT, 'app.csv')
TZ = ZoneInfo('Europe/Lisbon')
STAKE = 10
FIELDS = ['Fecha', 'Hora', 'Liga', 'Local', 'Visitante', 'Pronóstico', 'Tipo', 'Cuota',
          'Cuota 1', 'Cuota X', 'Cuota 2', 'Prob. implícita %', 'Rango cuota',
          'Resultado', 'Acierto', 'Ganado (1/0)', 'Beneficio 10€',
          'Descanso', 'Gol 1.ª parte', 'Goles 1.ª parte', 'Goles 2.ª parte', 'Total goles',
          'Más de 2,5', 'Ambos marcan', 'Minutos goles',
          'Córners L', 'Córners V', 'Córners total', 'Tiros L', 'Tiros V', 'A puerta L', 'A puerta V',
          'Posesión L %', 'Posesión V %', 'Amarillas L', 'Amarillas V', 'Rojas L', 'Rojas V',
          'Forma L', 'Forma V', 'Estadio']
ESPN_FIELDS = FIELDS[FIELDS.index('Descanso'):]


def f2(v):
    return f'{v:.2f}' if v else ''


def row(m):
    t = datetime.fromisoformat(m['inicio']).astimezone(TZ)
    ten = m.get('tendencia', '').replace('★★★ ', '')
    ac = 'Acertado' if '✓' in ten else 'Fallado' if '✗' in ten else ''
    ten = re.sub(r' · [✓✗].*$', '', ten)
    cu = re.search(r'cuota ~?([\d,]+)', ten)
    pron = re.sub(r' · cuota.*$', '', ten).strip()
    o = m.get('cuotas') or [None, None, None]
    r = {k: '' for k in FIELDS}
    r.update({'Fecha': t.strftime('%Y-%m-%d'), 'Hora': t.strftime('%H:%M'), 'Liga': m.get('liga', ''),
              'Local': m.get('local', ''), 'Visitante': m.get('visitante', ''), 'Pronóstico': pron,
              'Cuota': cu.group(1).replace(',', '.') if cu else '',
              'Cuota 1': f2(o[0]), 'Cuota X': f2(o[1]), 'Cuota 2': f2(o[2]),
              'Resultado': m.get('resultado', '') or '', 'Acierto': ac})
    return r


def derive(r):
    """Columnas calculadas a partir de las demás."""
    p = r['Pronóstico']
    if p.endswith(' o empate'):
        r['Tipo'] = 'Doble oport. local' if same(p[:-9], r['Local']) else 'Doble oport. visitante'
    elif p.startswith('Gana '):
        r['Tipo'] = 'Gana local' if same(p[5:], r['Local']) else 'Gana visitante'
    try:
        c = float(r['Cuota'])
        r['Prob. implícita %'] = f'{100 / c:.0f}'
        r['Rango cuota'] = '1,01-1,20' if c < 1.2 else '1,20-1,35' if c < 1.35 else '1,35-1,50' if c < 1.5 else '1,50+'
    except ValueError:
        c = None
    if r['Acierto']:
        r['Ganado (1/0)'] = '1' if r['Acierto'] == 'Acertado' else '0'
        if c:
            r['Beneficio 10€'] = f'{STAKE * (c - 1):.2f}' if r['Acierto'] == 'Acertado' else f'{-STAKE:.2f}'
    mm = re.match(r'(\d+) - (\d+)', r['Resultado'])
    if mm:
        h, a = map(int, mm.groups())
        r['Total goles'] = str(h + a)
        r['Más de 2,5'] = 'Sí' if h + a > 2 else 'No'
        r['Ambos marcan'] = 'Sí' if h and a else 'No'
        if r['Goles 1.ª parte'] != '':
            r['Goles 2.ª parte'] = str(h + a - int(r['Goles 1.ª parte']))


def key(r):
    return (r['Fecha'], r['Local'].lower(), r['Visitante'].lower())


def merge(rows, partidos):
    for m in partidos:
        if not m.get('inicio') or '★★★' not in m.get('tendencia', ''):
            continue
        r = row(m)
        old = rows.get(key(r))
        if old:  # no perder datos ya conocidos
            for f in FIELDS:
                r[f] = r[f] or old.get(f, '')
        rows[key(r)] = r


# ---------- ESPN ----------
def espn_day(day):
    url = f'https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard?dates={day:%Y%m%d}&limit=900'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    out = []
    for e in json.load(urllib.request.urlopen(req, timeout=90)).get('events', []):
        c = e['competitions'][0]
        if not c['status']['type'].get('completed'):
            continue
        t = {x['homeAway']: x for x in c['competitors']}
        if 'home' not in t or 'away' not in t:
            continue
        hid = t['home']['team']['id']
        st = {side: {s['name']: s.get('displayValue', '') for s in t[side].get('statistics', [])} for side in t}
        g = {'home': [], 'away': []}
        cards = {('home', 'Y'): 0, ('away', 'Y'): 0, ('home', 'R'): 0, ('away', 'R'): 0}
        ht = [0, 0]
        for d in c.get('details', []):
            side = 'home' if (d.get('team') or {}).get('id') == hid else 'away'
            disp = (d.get('clock') or {}).get('displayValue', '')
            if d.get('scoringPlay') and not d.get('shootout'):
                g[side].append(disp)
                val = (d.get('clock') or {}).get('value') or 0
                if val <= 2700 or disp.startswith("45'+"):
                    ht[0 if side == 'home' else 1] += 1
            if d.get('yellowCard'):
                cards[(side, 'Y')] += 1
            if d.get('redCard'):
                cards[(side, 'R')] += 1
        try:
            hs, as_ = int(t['home']['score']), int(t['away']['score'])
        except (KeyError, ValueError):
            continue
        has_details = bool(c.get('details'))
        info = {'Resultado': f'{hs} - {as_}'}
        if has_details or hs + as_ == 0:
            info.update({'Descanso': f'{ht[0]} - {ht[1]}', 'Gol 1.ª parte': 'Sí' if sum(ht) else 'No',
                         'Goles 1.ª parte': str(sum(ht)),
                         'Minutos goles': ' · '.join([f"{m} L" for m in g['home']] + [f"{m} V" for m in g['away']])})
        if has_details:
            info.update({'Amarillas L': str(cards[('home', 'Y')]), 'Amarillas V': str(cards[('away', 'Y')]),
                         'Rojas L': str(cards[('home', 'R')]), 'Rojas V': str(cards[('away', 'R')])})
        if st['home'].get('totalShots'):
            cl, cv = st['home'].get('wonCorners', ''), st['away'].get('wonCorners', '')
            info.update({'Córners L': cl, 'Córners V': cv,
                         'Córners total': str(int(cl) + int(cv)) if cl.isdigit() and cv.isdigit() else '',
                         'Tiros L': st['home'].get('totalShots', ''), 'Tiros V': st['away'].get('totalShots', ''),
                         'A puerta L': st['home'].get('shotsOnTarget', ''),
                         'A puerta V': st['away'].get('shotsOnTarget', ''),
                         'Posesión L %': st['home'].get('possessionPct', ''),
                         'Posesión V %': st['away'].get('possessionPct', '')})
        info.update({'Forma L': t['home'].get('form', ''), 'Forma V': t['away'].get('form', ''),
                     'Estadio': (c.get('venue') or {}).get('fullName', '')})
        out.append((t['home']['team']['displayName'], t['away']['team']['displayName'], info))
    return out


def judge(pron, local, visit, hs, ws):
    if pron.startswith('Gana '):
        t = pron[5:]
        return hs > ws if same(t, local) else ws > hs if same(t, visit) else None
    if pron.endswith(' o empate'):
        t = pron[:-9]
        return hs >= ws if same(t, local) else ws >= hs if same(t, visit) else None
    return None


def fill_espn(rows, days):
    today = datetime.now(TZ).date()
    first = (today - timedelta(days=days)).isoformat()
    pend = [r for r in rows.values() if first <= r['Fecha'] <= today.isoformat()
            and not r['Forma L'] and not r.get('_sin_espn')]
    games, n = {}, 0
    for r in pend:
        f = date.fromisoformat(r['Fecha'])
        g = []
        for d in (f - timedelta(days=1), f, f + timedelta(days=1)):   # ESPN agrupa por fecha de EE. UU.
            if d > today:
                continue
            if d not in games:
                try:
                    games[d] = espn_day(d)
                except Exception as ex:
                    print('ESPN', d, ex)
                    games[d] = []
            g += games[d]
        for h, a, info in g:
            if same(r['Local'], h) and same(r['Visitante'], a):
                if not r['Resultado']:
                    r['Resultado'] = info['Resultado']
                for k, v in info.items():
                    if k != 'Resultado' and v != '':
                        r[k] = v
                if not r['Acierto']:
                    hs, ws = map(int, info['Resultado'].split(' - '))
                    ok = judge(r['Pronóstico'], r['Local'], r['Visitante'], hs, ws)
                    if ok is not None:
                        r['Acierto'] = 'Acertado' if ok else 'Fallado'
                n += 1
                break
    print(f'ESPN: {n}/{len(pend)} partidos con estadísticas')


def main():
    rows = {}
    if os.path.exists(OUT):
        with open(OUT, encoding='utf-8') as f:
            for r in csv.DictReader(f):
                rows[key(r)] = {k: r.get(k, '') or '' for k in FIELDS}
    if '--backfill' in sys.argv:
        revs = subprocess.run(['git', 'log', '--reverse', '--format=%H', '--', 'data.json'], cwd=ROOT,
                              capture_output=True, text=True).stdout.split()
        for h in revs:
            try:
                merge(rows, json.loads(subprocess.run(['git', 'show', f'{h}:data.json'], cwd=ROOT,
                                                      capture_output=True, text=True).stdout).get('partidos', []))
            except Exception:
                pass
    merge(rows, json.load(open(DATA, encoding='utf-8')).get('partidos', []))
    days = int(sys.argv[sys.argv.index('--days') + 1]) if '--days' in sys.argv else 4
    fill_espn(rows, days)
    for r in rows.values():
        derive(r)
    out = sorted(rows.values(), key=lambda r: (r['Fecha'], r['Hora'], r['Local']), reverse=True)
    with open(OUT, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        w.writeheader()
        w.writerows(out)
    print(f'app.csv: {len(out)} partidos')


if __name__ == '__main__':
    main()
