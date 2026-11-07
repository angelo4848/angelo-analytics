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

# nombres de football-data -> nombres completos (para la app, la hoja y los marcadores de ESPN)
NAMES = {
    'Man City': 'Manchester City', 'Man United': 'Manchester United', "Nott'm Forest": 'Nottingham Forest',
    'Newcastle': 'Newcastle United', 'Tottenham': 'Tottenham Hotspur', 'West Ham': 'West Ham United',
    'Wolves': 'Wolverhampton', 'Brighton': 'Brighton', 'Leeds': 'Leeds United', 'Sheffield United': 'Sheffield United',
    'Paris SG': 'Paris Saint-Germain', 'St Etienne': 'Saint-Etienne', 'Ath Madrid': 'Atletico Madrid',
    'Ath Bilbao': 'Athletic Club', 'Sociedad': 'Real Sociedad', 'Betis': 'Real Betis', 'Vallecano': 'Rayo Vallecano',
    'Espanol': 'Espanyol', 'Celta': 'Celta Vigo', 'Alaves': 'Alaves', 'Sevilla': 'Sevilla',
    'Bayern Munich': 'Bayern Munich', 'Dortmund': 'Borussia Dortmund', "M'gladbach": 'Borussia Monchengladbach',
    'Leverkusen': 'Bayer Leverkusen', 'Ein Frankfurt': 'Eintracht Frankfurt', 'FC Koln': 'Koln',
    'RB Leipzig': 'RB Leipzig', 'Mainz': 'Mainz 05', 'Hamburg': 'Hamburger SV', 'Werder Bremen': 'Werder Bremen',
    'Inter': 'Inter Milan', 'Milan': 'AC Milan', 'Roma': 'AS Roma', 'Verona': 'Hellas Verona',
    'Sp Lisbon': 'Sporting CP', 'Sp Braga': 'Braga', 'Porto': 'FC Porto', 'Benfica': 'Benfica',
    'Guimaraes': 'Vitoria Guimaraes', 'PSV Eindhoven': 'PSV', 'Ajax': 'Ajax', 'Feyenoord': 'Feyenoord',
    'AZ Alkmaar': 'AZ Alkmaar', 'For Sittard': 'Fortuna Sittard', 'Nijmegen': 'NEC Nijmegen', 'Twente': 'FC Twente',
}


def name(n):
    return NAMES.get(n, n)


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
            nl, nv = name(loc), name(vis)
            if max(ph, pa) < P_FAV:
                continue
            fav = nl if ph >= pa else nv
            ou = valor.first(r, ('BFE>2.5', 'BFE<2.5'), ('P>2.5', 'P<2.5'), ('Avg>2.5', 'Avg<2.5'))
            po = (1 / ou[0]) / (1 / ou[0] + 1 / ou[1]) if ou else 0.52
            g = valor.grid(*valor.fit(ph, pa, po))
            ms = [(nm, p, m) for nm, p, m in mercados(fav, nl, nv, g) if LO <= 1 / p <= HI]
            equipo = [x for x in ms if x[0].startswith(fav)]   # como él: primero mercados del favorito
            ms = equipo or ms
            if not ms:
                continue
            mk, p, m = min(ms, key=lambda x: abs(1 / x[1] - OBJ))
            out.append({'Hora': (r.get('Time') or '').strip(), 'Liga': LEAGUES[div], 'Local': loc, 'Visitante': vis,
                        'LocalN': nl, 'VisitanteN': nv,
                        'Favorito': fav, 'p_fav': max(ph, pa), 'Mercado': mk, 'p': p, 'justa': 1 / p,
                        'casa': m / p})
    out += uefa(day)
    out.sort(key=lambda x: (x['Hora'], -x['p']))
    return out


# ---- competiciones europeas y selecciones (Champions, Europa, Conference, Nations, Mundial) ----
# football-data no las trae: se usan las cuotas 1X2 de nuestro registro OddSlot (app.csv).
APP = os.path.join(os.path.dirname(valor.HERE), 'app.csv')
UEFA_PO = 0.55   # prob. de +2,5 goles por defecto en estas competiciones (no hay cuota de goles)


def es_uefa(liga):
    l = liga.lower()
    if any(x in l for x in ('women', 'u21', 'u19', 'u17', 'youth', 'afc', 'caf', 'concacaf')):
        return False
    return 'uefa' in l or 'world cup' in l or 'nations league' in l


def app_rows():
    try:
        with open(APP, encoding='utf-8') as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def uefa(day):
    out = []
    for r in app_rows():
        if r.get('Fecha') != day.isoformat() or not es_uefa(r.get('Liga', '')):
            continue
        q = [valor.f(r.get(k)) for k in ('Cuota 1', 'Cuota X', 'Cuota 2')]
        if None not in q:
            inv = [1 / x for x in q]
            s = sum(inv)
            ph, pa = inv[0] / s, inv[2] / s
        else:   # solo hay la cuota del pronóstico: se estima el resto
            c, pr = valor.f(r.get('Cuota')), r.get('Pronóstico', '')
            if not c:
                continue
            if pr.startswith('Gana '):
                pw = 0.95 / c
                pd = (1 - pw) * 0.55
            elif pr.endswith(' o empate'):
                pd = 0.27
                pw = 0.95 / c - pd
            else:
                continue
            pl = max(0.01, 1 - pw - pd)
            team = pr[5:] if pr.startswith('Gana ') else pr[:-len(' o empate')]
            ph, pa = (pw, pl) if team == r['Local'] else (pl, pw)
        if max(ph, pa) < P_FAV:
            continue
        loc, vis = r['Local'], r['Visitante']
        fav = loc if ph >= pa else vis
        g = valor.grid(*valor.fit(ph, pa, UEFA_PO))
        ms = [(nm, p, m) for nm, p, m in mercados(fav, loc, vis, g) if LO <= 1 / p <= HI]
        ms = [x for x in ms if x[0].startswith(fav)] or ms
        if not ms:
            continue
        mk, p, m = min(ms, key=lambda x: abs(1 / x[1] - OBJ))
        out.append({'Hora': r.get('Hora', ''), 'Liga': r['Liga'], 'Local': loc, 'Visitante': vis,
                    'LocalN': loc, 'VisitanteN': vis, 'Favorito': fav, 'p_fav': max(ph, pa), 'Mercado': mk,
                    'p': p, 'justa': 1 / p, 'casa': m / p})
    return out


def resultado(pick, hist_idx):
    h = hist_idx.get((pick['Fecha'], pick['Local'], pick['Visitante']))
    if h and h.get('gl', '') != '':
        i, j = int(h['gl']), int(h['gv'])
    else:   # competiciones europeas: resultado de nuestro registro (app.csv)
        import re
        a = next((r for r in app_rows() if (r['Fecha'], r['Local'], r['Visitante']) ==
                  (pick['Fecha'], pick['Local'], pick['Visitante'])), None)
        mm = re.match(r'(\d+) - (\d+)', (a or {}).get('Resultado', '') or '')
        if not mm:
            return None, ''
        i, j = int(mm.group(1)), int(mm.group(2))
    m = pick['Mercado']
    home = m.startswith(name(pick['Local']))
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
