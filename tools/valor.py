#!/usr/bin/env python3
"""Apuestas de VALOR (lo único que el estudio histórico da en positivo).

Idea: las cuotas de la bolsa de apuestas (Betfair Exchange) son las más "afinadas"; quitándoles el pequeño
margen sale la cuota justa de cada resultado. Solo vale la pena apostar cuando una casa paga AL MENOS un 5 %
más que esa cuota justa (en el estudio de 6 temporadas, reports/backtest.md F2 margen 5 %, fue lo único con
ROI positivo). Acierta poco y tiene rachas largas sin acertar: se mide por beneficio, no por % de acierto.

Para cada pronóstico se calcula además una OPCIÓN DE UN SOLO PARTIDO (crear apuesta en 22Bet):
  resultado del pronóstico (o con doble oportunidad) + una línea de goles (total, local o visitante; más o menos),
la más probable con cuota justa 1,70-2,60, con un modelo de Poisson ajustado a las cuotas 1X2 y +/-2,5 de la bolsa.

Datos: https://www.football-data.co.uk/fixtures.csv (partidos próximos con cuotas; se actualiza ~2 veces/semana).
"""
import csv, math, os, time, urllib.request
from datetime import datetime

from history import LEAGUES

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(ROOT, 'data', 'fixtures.csv')
URL = 'https://www.football-data.co.uk/fixtures.csv'
MARGEN = 0.05          # la casa tiene que pagar ≥ 5 % más que la cuota justa
CUOTA_MAX = 8.0        # por encima de esto la varianza es enorme: fuera
MIN_PROB = 0.45        # solo pronósticos con al menos un 45 % de probabilidad (cuotas ~1,80-2,20)
MAXG = 10


def fetch(max_age_h=3):
    """Descarga fixtures.csv si la copia local tiene más de max_age_h horas."""
    # en GitHub Actions el checkout pone la fecha de ahora a todos los ficheros: allí se descarga siempre
    if not os.environ.get('GITHUB_ACTIONS') and os.path.exists(FIX) and \
            time.time() - os.path.getmtime(FIX) < max_age_h * 3600:
        return
    try:
        req = urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read().decode('utf-8-sig', 'replace')
        if 'HomeTeam' in text:
            with open(FIX, 'w', encoding='utf-8', newline='') as f:
                f.write(text)
    except Exception as ex:
        print('fixtures.csv no disponible:', ex)


def f(v):
    try:
        x = float(v)
        return x if x > 1 else None
    except (TypeError, ValueError):
        return None


def parse_date(s):
    for fmt in ('%d/%m/%Y', '%d/%m/%y'):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except (ValueError, AttributeError):
            pass
    return None


def first(r, *groups):
    """Primer grupo de columnas con todas las cuotas válidas."""
    for g in groups:
        v = [f(r.get(k)) for k in g]
        if None not in v:
            return v
    return None


# ---------------- Poisson ----------------
def pmf(lam):
    return [math.exp(-lam) * lam ** k / math.factorial(k) for k in range(MAXG + 1)]


def grid(lh, la):
    a, b = pmf(lh), pmf(la)
    return [[a[i] * b[j] for j in range(MAXG + 1)] for i in range(MAXG + 1)]


def probs(g):
    ph = sum(g[i][j] for i in range(MAXG + 1) for j in range(MAXG + 1) if i > j)
    pa = sum(g[i][j] for i in range(MAXG + 1) for j in range(MAXG + 1) if i < j)
    po = sum(g[i][j] for i in range(MAXG + 1) for j in range(MAXG + 1) if i + j >= 3)
    return ph, pa, po


def fit(ph, pa, po):
    """Goles esperados (local, visitante) que mejor reproducen P(1), P(2) y P(más de 2,5)."""
    def err(lh, la):
        h, a, o = probs(grid(lh, la))
        return (h - ph) ** 2 + (a - pa) ** 2 + (o - po) ** 2
    best = min(((err(x / 10, y / 10), x / 10, y / 10) for x in range(2, 41, 2) for y in range(2, 41, 2)))
    _, lh, la = best
    for step in (0.05, 0.01):
        for _ in range(30):
            cand = min(((err(lh + dx, la + dy), lh + dx, la + dy)
                        for dx in (-step, 0, step) for dy in (-step, 0, step) if lh + dx > 0.05 and la + dy > 0.05))
            if cand[1:] == (lh, la):
                break
            _, lh, la = cand
    return lh, la


OP_MIN, OP_MAX = 1.70, 2.60   # cuota justa buscada para la opción de un solo partido


def opcion(mercado, local, visitante, g):
    """Mejor opción de UN solo partido: el resultado del pronóstico (o con doble oportunidad) + una línea de
    goles (total, del local o del visitante; más o menos). Se elige la más probable con cuota justa 1,70-2,60.
    Devuelve (texto, probabilidad, código para comprobar el resultado)."""
    n = MAXG + 1
    if mercado == 'Empate':
        res = [('X', 'Empate')]
    elif mercado == f'Gana {local}':
        res = [('1', f'Gana {local}'), ('1X', f'{local} o empate')]
    else:
        res = [('2', f'Gana {visitante}'), ('X2', f'{visitante} o empate')]
    goles = []
    for line in (1.5, 2.5, 3.5, 4.5):
        goles += [('T+', line, f'más de {line:.1f} goles'.replace('.', ',')),
                  ('T-', line, f'menos de {line:.1f} goles'.replace('.', ','))]
    for who, eq in (('L', local), ('V', visitante)):
        for line in (0.5, 1.5, 2.5):
            goles += [(who + '+', line, f'{eq} más de {line:.1f} goles'.replace('.', ',')),
                      (who + '-', line, f'{eq} menos de {line:.1f} goles'.replace('.', ','))]
    cands = []
    for rc, rt in res:
        pr = sum(g[i][j] for i in range(n) for j in range(n) if check(rc, 'T+', -1, i, j))
        for gc, line, gt in goles:
            p = sum(g[i][j] for i in range(n) for j in range(n) if check(rc, gc, line, i, j))
            if 0 < p < pr - 0.02:   # fuera las líneas que no añaden nada (p. ej. "gana X y X marca")
                cands.append((p, f'{rt} y {gt}', (rc, gc, line)))
    ok = [c for c in cands if OP_MIN <= 1 / c[0] <= OP_MAX]
    if ok:
        return max(ok)
    return min(cands, key=lambda c: abs(1 / c[0] - OP_MIN))


def check(rc, gc, line, i, j):
    r = {'1': i > j, 'X': i == j, '2': j > i, '1X': i >= j, 'X2': j >= i}[rc]
    v = {'T': i + j, 'L': i, 'V': j}[gc[0]]
    return r and (v > line if gc[1] == '+' else v < line)


def picks(day):
    """Apuestas de valor 1X2 del día `day` (date). Una por partido como máximo (la de más ventaja)."""
    fetch()
    if not os.path.exists(FIX):
        return []
    out = []
    with open(FIX, encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            div = (r.get('Div') or '').strip()
            if div not in LEAGUES or parse_date(r.get('Date', '')) != day:
                continue
            ref = first(r, ('BFEH', 'BFED', 'BFEA'), ('PSH', 'PSD', 'PSA'))      # cuota "afinada"
            casa = first(r, ('MaxH', 'MaxD', 'MaxA'), ('B365H', 'B365D', 'B365A'))  # mejor cuota de casas
            if not ref or not casa:
                continue
            inv = [1 / x for x in ref]
            s = sum(inv)
            best = None
            for i, name in enumerate((f"Gana {r['HomeTeam']}", 'Empate', f"Gana {r['AwayTeam']}")):
                p = inv[i] / s
                justa = 1 / p
                c = casa[i]
                if c > CUOTA_MAX or p < MIN_PROB:
                    continue
                edge = c / justa - 1
                if edge > 0.25:   # diferencia absurda = cuota mal puesta en los datos
                    continue
                if edge >= MARGEN and (best is None or edge > best['edge']):
                    best = {'Hora': (r.get('Time') or '').strip(), 'Liga': LEAGUES[div],
                            'Local': r['HomeTeam'], 'Visitante': r['AwayTeam'], 'Mercado': name,
                            'p': p, 'justa': justa, 'minima': justa * (1 + MARGEN), 'casa': c, 'edge': edge}
            if not best:
                continue
            ou = first(r, ('BFE>2.5', 'BFE<2.5'), ('P>2.5', 'P<2.5'), ('Avg>2.5', 'Avg<2.5'))
            po = (1 / ou[0]) / (1 / ou[0] + 1 / ou[1]) if ou else 0.52
            g = grid(*fit(inv[0] / s, inv[2] / s, po))
            p2, txt, code = opcion(best['Mercado'], r['HomeTeam'], r['AwayTeam'], g)
            best.update({'opcion': txt, 'p_op': p2, 'justa_op': 1 / p2, 'minima_op': (1 + MARGEN) / p2,
                         'op_code': '|'.join(map(str, code))})
            out.append(best)
    out.sort(key=lambda x: (x['Hora'], -x['edge']))
    return out


def resultado(pick, hist_idx):
    """(acertado, texto) con el resultado final de history.csv; (None, '') si aún no está."""
    h = hist_idx.get((pick['Fecha'], pick['Local'], pick['Visitante']))
    if not h or h.get('gl', '') == '':
        return None, ''
    gl, gv = int(h['gl']), int(h['gv'])
    m = pick['Mercado']
    ok = gl == gv if m == 'Empate' else (gl > gv if m == f"Gana {pick['Local']}" else gv > gl)
    return ok, f'{gl} - {gv}'


def resultado_opcion(pick, hist_idx):
    h = hist_idx.get((pick['Fecha'], pick['Local'], pick['Visitante']))
    if not h or h.get('gl', '') == '' or not pick.get('op_code'):
        return None
    rc, gc, line = pick['op_code'].split('|')
    return check(rc, gc, float(line), int(h['gl']), int(h['gv']))
