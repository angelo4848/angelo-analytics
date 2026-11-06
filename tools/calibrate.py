#!/usr/bin/env python3
"""Comprueba el modelo con las 2 últimas temporadas (solo con datos anteriores a cada partido) y
guarda data/calibracion.csv: para cada mercado del filtro, cuántas veces se habría apostado y el
acierto REAL frente al previsto. Corre en GitHub junto al histórico, sin Claude."""
import collections, csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model as m


def main():
    hist = m.load_csv(m.HIST)
    L = m.league_stats(hist, [])
    T = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(list)))
    res = collections.defaultdict(lambda: [0, 0, 0.0])
    seasons = sorted({r['temporada'] for r in hist})[-2:]
    for r in hist:
        if r['htl'] == '':
            continue
        lg, h, a = r['liga'], r['local'], r['visitante']
        tm = T[lg]
        if r['temporada'] in seasons and lg in L and tm[h]['h_gf'] and tm[a]['a_gf']:
            pr = m.predict({'Liga': lg, 'Local': h, 'Visitante': a}, L, {lg: tm})
            g = int(r['htl']) + int(r['htv'])
            cand = [('Menos de 1,5 goles 1.ª parte', pr['p_le1'], g <= 1),
                    ('Más de 0,5 goles 1.ª parte', 1 - pr['p00'], g >= 1),
                    ('Menos de 0,5 goles 1.ª parte', pr['p00'], g == 0)]
            if r['cl'] != '' and 'c_exp' in pr:
                c = int(r['cl']) + int(r['cv'])
                cand += [('Menos de 10,5 córners', pr['c_u105'], c <= 10), ('Más de 7,5 córners', pr['c_o75'], c >= 8)]
            for mk, p, ok in cand:
                if p >= m.BEST[mk]:
                    x = res[mk]; x[0] += 1; x[1] += ok; x[2] += p
        tm[h]['h_gf'].append(int(r['htl'])); tm[h]['h_ga'].append(int(r['htv']))
        tm[a]['a_gf'].append(int(r['htv'])); tm[a]['a_ga'].append(int(r['htl']))
        if r['cl'] != '':
            tm[h]['h_cf'].append(int(r['cl'])); tm[h]['h_ca'].append(int(r['cv']))
            tm[a]['a_cf'].append(int(r['cv'])); tm[a]['a_ca'].append(int(r['cl']))
        for t in (h, a):
            for v in tm[t].values():
                if len(v) > 38:
                    del v[0]
    with open(os.path.join(m.D, 'calibracion.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['Mercado', 'Apuestas simuladas', 'Acierto real', 'Acierto previsto', 'Cuota justa real', 'Temporadas'])
        for mk, (n, k, s) in sorted(res.items(), key=lambda x: -x[1][1] / max(x[1][0], 1)):
            w.writerow([mk, n, f'{100 * k / n:.1f}%', f'{100 * s / n:.1f}%', f'{n / k:.2f}' if k else '',
                        ' y '.join(seasons)])
            print(mk, n, f'{100 * k / n:.1f}%', f'previsto {100 * s / n:.1f}%')


if __name__ == '__main__':
    main()
