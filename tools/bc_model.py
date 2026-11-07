#!/usr/bin/env python3
"""Modelo "Bet Consulting" (copiado de 222 picks de su canal, mar-nov 2026).

Su forma de trabajar:
  · 1 combinada de 2 partidos al día, pre-live, cuota total 1,60-2,10 (media 1,82)
  · casi solo favoritos claros de ligas grandes (Real, Barça, Arsenal, PSG, Bayern, City, Porto, Benfica, Sporting...)
  · patas siempre del mismo tipo:
        "X vence e -5,5 golos"   (≈ gana X)
        "X vence e +1,5 golos"
        "X/empate e +1,5 golos"
        "X ou empate"
        "+2,5 golos" / "Ambas marcam"
  · cada pata ronda 1,25-1,45 para que 2 juntas den ~1,70-1,90

Aquí: para cada partido de HOY de las ligas grandes con favorito claro, se calcula la probabilidad de cada mercado
(Poisson ajustado a las cuotas de la bolsa) y se elige el mercado cuya cuota queda más cerca de 1,35.
Las cuotas de casa son aproximadas: hay que mirar la cuota real en 22Bet.
"""
import csv, os

import valor
from history import LEAGUES

LIGAS = {'E0', 'SP1', 'I1', 'D1', 'F1', 'P1', 'N1'}   # ligas donde juegan sus equipos
P_FAV = 0.55          # favorito claro: al menos 55 % de ganar
OBJ, LO, HI = 1.35, 1.22, 1.50   # cuota justa buscada por pata
MARGEN_SIMPLE, MARGEN_CREAR = 0.94, 0.89   # cuota casa ≈ cuota justa × esto (simple / crear apuesta)


def mercados(fav, loc, vis, g):
    n = valor.MAXG + 1
    home = fav == loc
    W = (lambda i, j: i > j) if home else (lambda i, j: j > i)
    WD = (lambda i, j: i >= j) if home else (lambda i, j: j >= i)
    P = lambda f: sum(g[i][j] for i in range(n) for j in range(n) if f(i, j))
    return [
        (f'{fav} vence e -5,5 golos', P(lambda i, j: W(i, j) and i + j <= 5), MARGEN_CREAR),
        (f'{fav} vence e +1,5 golos', P(lambda i, j: W(i, j) and i + j >= 2), MARGEN_CREAR),
        (f'{fav}/empate e +1,5 golos', P(lambda i, j: WD(i, j) and i + j >= 2), MARGEN_CREAR),
        (f'{fav} ou empate', P(WD), MARGEN_SIMPLE),
        ('+2,5 golos', P(lambda i, j: i + j >= 3), MARGEN_SIMPLE),
        ('Ambas marcam', P(lambda i, j: i >= 1 and j >= 1), MARGEN_SIMPLE),
    ]


def picks(day):
    valor.fetch()
    if not os.path.exists(valor.FIX):
        return []
    out = []
    with open(valor.FIX, encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            div = (r.get('Div') or '').strip()
            if div not in LIGAS or valor.parse_date(r.get('Date', '')) != day:
                continue
            ref = valor.first(r, ('BFEH', 'BFED', 'BFEA'), ('PSH', 'PSD', 'PSA'), ('AvgH', 'AvgD', 'AvgA'))
            if not ref:
                continue
            inv = [1 / x for x in ref]
            s = sum(inv)
            ph, pa = inv[0] / s, inv[2] / s
            loc, vis = r['HomeTeam'], r['AwayTeam']
            if max(ph, pa) < P_FAV:
                continue
            fav = loc if ph >= pa else vis
            ou = valor.first(r, ('BFE>2.5', 'BFE<2.5'), ('P>2.5', 'P<2.5'), ('Avg>2.5', 'Avg<2.5'))
            po = (1 / ou[0]) / (1 / ou[0] + 1 / ou[1]) if ou else 0.52
            g = valor.grid(*valor.fit(ph, pa, po))
            ms = [(name, p, m) for name, p, m in mercados(fav, loc, vis, g) if LO <= 1 / p <= HI]
            equipo = [x for x in ms if x[0].startswith(fav)]   # como él: primero mercados del favorito
            ms = equipo or ms
            if not ms:
                continue
            name, p, m = min(ms, key=lambda x: abs(1 / x[1] - OBJ))
            out.append({'Hora': (r.get('Time') or '').strip(), 'Liga': LEAGUES[div], 'Local': loc, 'Visitante': vis,
                        'Favorito': fav, 'p_fav': max(ph, pa), 'Mercado': name, 'p': p, 'justa': 1 / p,
                        'casa': m / p})
    out.sort(key=lambda x: (x['Hora'], -x['p']))
    return out


def resultado(pick, hist_idx):
    h = hist_idx.get((pick['Fecha'], pick['Local'], pick['Visitante']))
    if not h or h.get('gl', '') == '':
        return None, ''
    i, j = int(h['gl']), int(h['gv'])
    m = pick['Mercado']
    home = m.startswith(pick['Local'])
    w = i > j if home else j > i
    wd = i >= j if home else j >= i
    ok = {'vence e -5,5 golos': w and i + j <= 5, 'vence e +1,5 golos': w and i + j >= 2,
          '/empate e +1,5 golos': wd and i + j >= 2, 'ou empate': wd}
    for k, v in ok.items():
        if m.endswith(k):
            return v, f'{i} - {j}'
    if m == '+2,5 golos':
        return i + j >= 3, f'{i} - {j}'
    if m == 'Ambas marcam':
        return i >= 1 and j >= 1, f'{i} - {j}'
    return None, ''
