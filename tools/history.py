#!/usr/bin/env python3
"""Descarga el histórico de football-data.co.uk (5 temporadas + la actual) de las ligas que traen
resultado al descanso y córners, y lo guarda compacto en data/history.csv.

Corre en GitHub Actions cada semana (football-data se actualiza ~2 veces por semana). Sin Claude.
"""
import csv, io, os, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'history.csv')
SEASONS = ['2122', '2223', '2324', '2425', '2526', '2627']
# código football-data -> nombre de la liga tal como sale en OddSlot (nuestro registro)
LEAGUES = {
    'E0': 'England: Premier League', 'E1': 'England: Championship', 'E2': 'England: League One',
    'E3': 'England: League Two', 'EC': 'England: National League',
    'SC0': 'Scotland: Premiership', 'SC1': 'Scotland: Championship', 'SC2': 'Scotland: League One',
    'SC3': 'Scotland: League Two', 'D1': 'Germany: Bundesliga', 'D2': 'Germany: 2. Bundesliga',
    'I1': 'Italy: Serie A', 'I2': 'Italy: Serie B', 'SP1': 'Spain: La Liga', 'SP2': 'Spain: Segunda División',
    'F1': 'France: Ligue 1', 'F2': 'France: Ligue 2', 'N1': 'Netherlands: Eredivisie',
    'B1': 'Belgium: Jupiler Pro League', 'P1': 'Portugal: Primeira Liga', 'T1': 'Turkey: Süper Lig',
    'G1': 'Greece: Super League 1',
}
FIELDS = ['fecha', 'temporada', 'liga', 'local', 'visitante', 'gl', 'gv', 'htl', 'htv', 'cl', 'cv',
          'tl', 'tv', 'pl', 'pv', 'p1', 'px', 'p2']


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode('latin-1')


def num(v):
    try:
        return str(int(float(v)))
    except (TypeError, ValueError):
        return ''


def odd(v):
    try:
        f = float(v)
        return f'{f:.2f}' if f > 1 else ''
    except (TypeError, ValueError):
        return ''


def main():
    rows = []
    for s in SEASONS:
        for code, liga in LEAGUES.items():
            try:
                text = fetch(f'https://www.football-data.co.uk/mmz4281/{s}/{code}.csv')
            except Exception as ex:
                print('sin datos', s, code, ex)
                continue
            n = 0
            for r in csv.DictReader(io.StringIO(text)):
                if not r.get('HomeTeam') or num(r.get('FTHG')) == '':
                    continue
                d = r.get('Date', '')
                try:
                    dd, mm, yy = d.split('/')
                    fecha = f"{'20' + yy if len(yy) == 2 else yy}-{mm}-{dd}"
                except ValueError:
                    continue
                rows.append({'fecha': fecha, 'temporada': s, 'liga': liga, 'local': r['HomeTeam'].strip(),
                             'visitante': r['AwayTeam'].strip(), 'gl': num(r.get('FTHG')), 'gv': num(r.get('FTAG')),
                             'htl': num(r.get('HTHG')), 'htv': num(r.get('HTAG')), 'cl': num(r.get('HC')),
                             'cv': num(r.get('AC')), 'tl': num(r.get('HS')), 'tv': num(r.get('AS')),
                             'pl': num(r.get('HST')), 'pv': num(r.get('AST')),
                             'p1': odd(r.get('PSCH') or r.get('PSH') or r.get('AvgH')),
                             'px': odd(r.get('PSCD') or r.get('PSD') or r.get('AvgD')),
                             'p2': odd(r.get('PSCA') or r.get('PSA') or r.get('AvgA'))})
                n += 1
            print('ok', s, code, n)
    if len(rows) < 1000:
        raise SystemExit('Muy pocos datos descargados; no sobrescribo el histórico')
    rows.sort(key=lambda r: (r['fecha'], r['liga'], r['local']))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print('history.csv:', len(rows), 'partidos')


if __name__ == '__main__':
    main()
