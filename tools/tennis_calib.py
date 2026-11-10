#!/usr/bin/env python3
"""Tenis: relación entre la probabilidad de que el favorito gane el PARTIDO y la de que gane el 1.er SET.

Fuente: datos abiertos de Jeff Sackmann en GitHub (ATP, Challenger y WTA, con el marcador de cada set).
tennis-data.co.uk bloquea a GitHub (403), por eso no se usa aquí.

Método: en cada circuito y superficie se ordenan los partidos (a 3 sets, terminados) por la
diferencia de puntos de ranking y se cortan en tramos. En cada tramo se mide cuántas veces ganó el
favorito el partido y cuántas el 1.er set. Esas parejas (partido %, 1.er set %) forman la curva real
que usa tennis_tab.py: con la cuota de partido de la casa sabe qué % de 1.er set esperar.
Guarda data/tenis_calib.csv. Corre en GitHub (workflow "Estudio histórico"), sin Claude.
"""
import csv, io, math, os, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'tenis_calib.csv')
YEARS = range(2018, 2027)
RAW = 'https://raw.githubusercontent.com/JeffSackmann/'
FILES = {'ATP': 'tennis_atp/master/atp_matches_{y}.csv',
         'Challenger': 'tennis_atp/master/atp_matches_qual_chall_{y}.csv',
         'WTA': 'tennis_wta/master/wta_matches_{y}.csv'}
SURF = {'Hard': 'Dura', 'Clay': 'Tierra', 'Grass': 'Hierba', 'Carpet': 'Dura'}
BINS = 10


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'aa-tenis'}), timeout=60) as r:
            return r.read().decode('utf-8', 'replace')
    except Exception as ex:
        print('sin datos', url, ex)
        return None


def first_set(score):
    m = re.match(r'\s*(\d+)-(\d+)', score or '')
    if not m or re.search(r'RET|W/O|DEF|Def|ABN|unfinished', score or '', re.I):
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return None if a == b else a > b          # True = el ganador del partido ganó el 1.er set


def load():
    rows = []
    for circ, pat in FILES.items():
        for y in YEARS:
            txt = get(RAW + pat.format(y=y))
            if not txt:
                continue
            n = 0
            for r in csv.DictReader(io.StringIO(txt)):
                if r.get('best_of') not in ('3', '3.0'):
                    continue
                if circ == 'Challenger' and r.get('tourney_level') != 'C':
                    continue            # el archivo trae también la fase previa (Q)
                s1 = first_set(r.get('score'))
                try:
                    wp, lp = float(r['winner_rank_points']), float(r['loser_rank_points'])
                except (ValueError, KeyError):
                    continue
                if s1 is None or wp <= 0 or lp <= 0 or wp == lp:
                    continue
                fav_won = wp > lp
                rows.append((circ, SURF.get(r.get('surface', ''), 'Dura'), abs(math.log(wp / lp)),
                             fav_won, s1 == fav_won))
                n += 1
            print('ok', circ, y, n)
    return rows


def main():
    rows = load()
    if len(rows) < 5000:
        sys.exit(f'Pocos datos de tenis ({len(rows)}): no toco tenis_calib.csv')
    out = []
    for circ in ('ATP', 'Challenger', 'WTA', 'Todos'):
        for surf in ('Todas', 'Dura', 'Tierra', 'Hierba'):
            sel = sorted((r for r in rows if (circ == 'Todos' or r[0] == circ) and (surf == 'Todas' or r[1] == surf)),
                         key=lambda r: r[2])
            if len(sel) < 1500:
                continue
            size = len(sel) // BINS
            for b in range(BINS):
                part = sel[b * size:(b + 1) * size if b < BINS - 1 else len(sel)]
                out.append({'Circuito': circ, 'Superficie': surf, 'Tramo': b + 1, 'Partidos': len(part),
                            'Fav gana partido': round(sum(r[3] for r in part) / len(part), 4),
                            'Fav gana 1.er set': round(sum(r[4] for r in part) / len(part), 4)})
    with open(OUT, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f'tenis_calib.csv: {len(rows)} partidos, {len(out)} tramos')
    for r in out:
        if r['Superficie'] == 'Todas':
            print(r)


if __name__ == '__main__':
    main()
