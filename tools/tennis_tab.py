#!/usr/bin/env python3
"""Pestaña "Tenis 1.er set" del Google Sheet (corre en GitHub cada hora, sin Claude).

Lee data/tenis_hoy.csv (partidos con cuotas que sube tu PC desde SofaScore) y data/tenis_calib.csv
(histórico ATP/Challenger/WTA: % de 1.er set del favorito según su % de partido). Escribe:
  data/tab_tenis_1set.csv   favoritos claros de hoy y mañana, de más a menos probable
  data/tenis_1set_log.csv   todos los favoritos claros con su resultado (para el % de acierto real)
"""
import csv, os
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'data')
TZ, UTC = ZoneInfo('Europe/Lisbon'), ZoneInfo('UTC')
CLEAR = 0.70            # favorito claro: ≥ 70 % de ganar el partido (cuota justa ≤ 1,43)
MIN_BIN = 150           # mínimo de partidos en un tramo del histórico para fiarse de él


def load(name):
    p = os.path.join(D, name)
    if not os.path.exists(p):
        return []
    with open(p, encoding='utf-8') as f:
        return list(csv.DictReader(f))


def write(name, fields, rows):
    with open(os.path.join(D, name), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def set_from_match(p):
    """Probabilidad de ganar un set si P(partido a 3 sets) = p, con sets independientes: p = s²(3 − 2s)."""
    lo, hi = 0.5, 1.0
    for _ in range(40):
        s = (lo + hi) / 2
        if s * s * (3 - 2 * s) < p:
            lo = s
        else:
            hi = s
    return (lo + hi) / 2


def surface(g):
    g = (g or '').lower()
    return 'Tierra' if 'clay' in g else 'Hierba' if 'grass' in g else 'Dura'


def prob_set1(p, circ, surf, calib):
    """Curva real del histórico (partido % -> 1.er set %) del circuito y superficie; si no hay, la fórmula."""
    theory = set_from_match(p)
    for c in (circ, 'ATP' if circ == 'Challenger' else circ, 'Todos'):
        for s in (surf, 'Todas'):
            pts = sorted((float(r['Fav gana partido']), float(r['Fav gana 1.er set'])) for r in calib
                         if r['Circuito'] == c and r['Superficie'] == s and int(r['Partidos']) >= MIN_BIN)
            if len(pts) < 5:
                continue
            pts = [(0.5, 0.5)] + [q for q in pts if q[0] > 0.5]
            n = sum(int(r['Partidos']) for r in calib if r['Circuito'] == c and r['Superficie'] == s)
            src = f'Histórico {c} · {s} ({n} partidos)'
            if p >= pts[-1][0]:     # más allá del último tramo: se sigue la forma de la fórmula
                m, v = pts[-1]
                return min(v + theory - set_from_match(m), 0.97), src
            for (m0, v0), (m1, v1) in zip(pts, pts[1:]):
                if m0 <= p <= m1:
                    return v0 + (v1 - v0) * (p - m0) / (m1 - m0 or 1), src
    return theory, 'Fórmula (sin histórico)'


def main():
    rows, calib = load('tenis_hoy.csv'), load('tenis_calib.csv')
    now = datetime.now(TZ)
    today = now.date()
    log = {r['Id']: r for r in load('tenis_1set_log.csv')}
    out = []
    for r in rows:
        if r.get('Estado') == 'anulado':
            continue
        try:
            c1, c2 = float(r['Cuota 1']), float(r['Cuota 2'])
            start = datetime.strptime(r['Inicio UTC'], '%Y-%m-%d %H:%M').replace(tzinfo=UTC).astimezone(TZ)
        except (ValueError, KeyError):
            continue
        fav = 1 if c1 <= c2 else 2
        cf = c1 if fav == 1 else c2
        p = (1 / cf) / (1 / c1 + 1 / c2)
        if p < CLEAR:
            continue
        tour = 'WTA' if r['Categoría'].startswith('WTA') else 'Challenger' if r['Categoría'] == 'Challenger' else 'ATP'
        surf = surface(r['Superficie'])
        ps, fuente = prob_set1(p, tour, surf, calib)
        casa = r.get(f'Cuota set {fav}', '')
        valor = ''
        if casa:
            valor = 'Sí' if float(casa) > 1 / ps else 'No'
        s1, wset = r.get('1.er set', ''), r.get('Ganador 1.er set', '')
        if s1 and fav == 2:
            s1 = '-'.join(reversed(s1.split('-')))     # marcador desde el lado del favorito
        acierto = ('Acertado' if wset == str(fav) else 'Fallado') if wset else ''
        x = {'Fecha': 'Hoy' if start.date() == today else 'Mañana' if start.date() > today else 'Ayer', 'Hora': start.strftime('%H:%M'), 'Circuito': r['Categoría'],
             'Torneo': r['Torneo'], 'Superficie': surf,
             'Favorito': r[f'Jugador {fav}'], 'Rival': r[f'Jugador {3 - fav}'],
             'Ranking fav.': r[f'Ranking {fav}'], 'Ranking rival': r[f'Ranking {3 - fav}'],
             'Cuota partido': f'{cf:.2f}', 'Prob. 1.er set': f'{100 * ps:.0f}%', 'Cuota justa 1.er set': f'{1 / ps:.2f}',
             'Cuota casa 1.er set': casa, 'Valor': valor, '1.er set': s1, 'Acierto': acierto, 'Fuente': fuente,
             '_d': start.date(), '_p': ps}
        if start.date() >= today:
            out.append(x)
        log[r['Id']] = {**{k: v for k, v in x.items() if not k.startswith('_')}, 'Id': r['Id'],
                        'Fecha': start.strftime('%Y-%m-%d')}
    out.sort(key=lambda x: (x['_d'], -x['_p']))
    F = ['Fecha', 'Hora', 'Circuito', 'Torneo', 'Superficie', 'Favorito', 'Rival', 'Ranking fav.', 'Ranking rival',
         'Cuota partido', 'Prob. 1.er set', 'Cuota justa 1.er set', 'Cuota casa 1.er set', 'Valor', '1.er set',
         'Acierto', 'Fuente']
    done = [r for r in log.values() if r.get('Acierto')]
    if not out:
        out = [{'Torneo': 'Sin favoritos claros todavía (los partidos llegan cuando tu PC está encendido)'}]
    if done:
        ok = sum(r['Acierto'] == 'Acertado' for r in done)
        out += [{}, {'Torneo': 'ACIERTO REAL DEL FILTRO', 'Favorito': f'{ok} de {len(done)}',
                     'Prob. 1.er set': f'{100 * ok / len(done):.0f}%'}]
    write('tab_tenis_1set.csv', F, out)
    write('tenis_1set_log.csv', ['Id'] + F, sorted(log.values(), key=lambda r: (r['Fecha'], r['Hora']), reverse=True))
    print(f'Tenis 1.er set: {len([x for x in out if x.get("Favorito")])} filas · registro {len(log)} · histórico {len(calib)} tramos')


if __name__ == '__main__':
    main()
