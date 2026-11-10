#!/usr/bin/env python3
"""Tenis: ¿cuántas veces gana el FAVORITO el 1.er set según su cuota de partido?

Descarga ATP y WTA de tennis-data.co.uk (mismo origen que backtest.py), calcula la probabilidad
justa del favorito (cuotas Pinnacle sin margen; si no, Bet365) y cuenta si ganó el 1.er set.
Guarda data/tenis_calib.csv por circuito, superficie y tramo de probabilidad. Corre en GitHub
(workflow "Estudio histórico"), sin Claude. Lo usa model.py para la pestaña "Tenis 1.er set".
"""
import csv, io, os, sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest import TENNIS_YEARS, col, fetch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'tenis_calib.csv')
EDGES = [0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00]
SURF = {'Hard': 'Dura', 'Clay': 'Tierra', 'Grass': 'Hierba', 'Carpet': 'Dura'}


def load():
    frames = []
    for y in TENNIS_YEARS:
        for tour, path in (('ATP', f'{y}/{y}.xlsx'), ('WTA', f'{y}w/{y}.xlsx')):
            for base in ('https://www.tennis-data.co.uk/', 'http://www.tennis-data.co.uk/'):
                try:
                    df = pd.read_excel(io.BytesIO(fetch(base + path)))
                    df['tour'] = tour
                    frames.append(df)
                    print('ok', tour, y, len(df))
                    break
                except Exception as ex:
                    print('sin datos', tour, y, base, ex)
    return pd.concat(frames, ignore_index=True) if frames else None


def main():
    df = load()
    if df is None:
        sys.exit('Sin datos de tenis: no toco tenis_calib.csv')
    if 'Comment' in df.columns:
        df = df[df['Comment'].astype(str).str.contains('Completed', na=False)]
    pw, pl = col(df, 'PSW'), col(df, 'PSL')
    bw, bl = col(df, 'B365W'), col(df, 'B365L')
    w1, l1 = col(df, 'W1'), col(df, 'L1')
    rows = []
    for i in df.index:
        ow, ol = (pw[i], pl[i]) if pw[i] == pw[i] and pl[i] == pl[i] and pw[i] > 1 and pl[i] > 1 else (bw[i], bl[i])
        if not (ow == ow and ol == ol and ow > 1 and ol > 1) or w1[i] != w1[i] or l1[i] != l1[i] or w1[i] == l1[i]:
            continue
        iw, il = 1 / ow, 1 / ol
        p_w = iw / (iw + il)                       # probabilidad justa de que gane el que ganó
        fav_is_winner = p_w >= 0.5
        p_fav = p_w if fav_is_winner else 1 - p_w
        winner_took_set1 = w1[i] > l1[i]
        rows.append((df.at[i, 'tour'], SURF.get(str(df.at[i, 'Surface']), 'Dura'), p_fav,
                     winner_took_set1 == fav_is_winner))
    out = []
    for tour in ('ATP', 'WTA', 'Todos'):
        for surf in ('Dura', 'Tierra', 'Hierba', 'Todas'):
            sel = [r for r in rows if (tour == 'Todos' or r[0] == tour) and (surf == 'Todas' or r[1] == surf)]
            for lo, hi in zip(EDGES, EDGES[1:]):
                b = [r for r in sel if lo <= r[2] < hi]
                if b:
                    out.append({'Circuito': tour, 'Superficie': surf, 'Prob min': lo, 'Prob max': hi, 'Partidos': len(b),
                                'Prob media partido': round(sum(r[2] for r in b) / len(b), 4),
                                'Fav gana 1.er set': round(sum(r[3] for r in b) / len(b), 4)})
    with open(OUT, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f'tenis_calib.csv: {len(rows)} partidos, {len(out)} tramos')


if __name__ == '__main__':
    main()
