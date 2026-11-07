#!/usr/bin/env python3
"""Apuestas de VALOR (lo único que el estudio histórico da en positivo).

Idea: Pinnacle es la casa más "afinada"; quitándole su margen sale la cuota justa de cada resultado.
Solo vale la pena apostar cuando una casa normal (Bet365 / 22Bet) paga AL MENOS un 5 % más que esa
cuota justa. En el estudio de 6 temporadas (reports/backtest.md, F2 margen 5 %) fue lo único con ROI positivo.
Ojo: acierta poco (~1 de cada 4) y tiene rachas largas sin acertar. Se mide por beneficio, no por % de acierto.

Datos: https://www.football-data.co.uk/fixtures.csv (partidos próximos con cuotas; se actualiza ~2 veces/semana).
"""
import csv, io, os, time, urllib.request
from datetime import datetime

from history import LEAGUES

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(ROOT, 'data', 'fixtures.csv')
URL = 'https://www.football-data.co.uk/fixtures.csv'
MARGEN = 0.05          # la casa tiene que pagar ≥ 5 % más que la cuota justa
CUOTA_MAX = 8.0        # por encima de esto la varianza es enorme: fuera


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
            ps = [f(r.get(k)) for k in ('PSH', 'PSD', 'PSA')]
            casa = [f(r.get(k)) or f(r.get(a)) for k, a in (('B365H', 'AvgH'), ('B365D', 'AvgD'), ('B365A', 'AvgA'))]
            if None in ps:
                continue
            inv = [1 / x for x in ps]
            s = sum(inv)
            best = None
            for i, name in enumerate((f"Gana {r['HomeTeam']}", 'Empate', f"Gana {r['AwayTeam']}")):
                p = inv[i] / s
                justa = 1 / p
                c = casa[i]
                if not c or c > CUOTA_MAX:
                    continue
                edge = c / justa - 1
                if edge >= MARGEN and (best is None or edge > best['edge']):
                    best = {'Hora': (r.get('Time') or '').strip(), 'Liga': LEAGUES[div],
                            'Local': r['HomeTeam'], 'Visitante': r['AwayTeam'], 'Mercado': name,
                            'p': p, 'justa': justa, 'minima': justa * (1 + MARGEN), 'casa': c, 'edge': edge}
            if best:
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
