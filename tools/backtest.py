#!/usr/bin/env python3
"""Estudio histórico (backtest) para encontrar un MODELO FIJO con beneficio real.

Corre en GitHub Actions (allí hay acceso a football-data.co.uk y tennis-data.co.uk).
Escribe el informe en reports/backtest.md y los números en reports/backtest.json.

Estrategias que compara (stake fijo de 1 unidad, cuota de casa "blanda" = Bet365):
  FÚTBOL
    F1  Favorito a cuota baja (lo que hacemos ahora): apostar al favorito si paga ≤ 1,50
    F2  Valor 1X2: Bet365 paga más que la cuota JUSTA de Pinnacle (sin margen) + margen e
    F3  Valor más/menos de 2,5 goles, igual que F2
    +   % de partidos 0-0 al descanso por liga (para el Filtro 2)
  TENIS (ATP y WTA)
    T1  Favorito ≤ 1,35
    T2  Valor: Bet365 paga más que la cuota justa de Pinnacle + margen e
"""
import io, json, math, os, sys, urllib.request
from collections import defaultdict

import pandas as pd

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'reports')
SEASONS = ['2122', '2223', '2324', '2425', '2526', '2627']
LEAGUES = {'E0': 'Inglaterra 1', 'E1': 'Inglaterra 2', 'E2': 'Inglaterra 3', 'E3': 'Inglaterra 4',
           'SC0': 'Escocia 1', 'D1': 'Alemania 1', 'D2': 'Alemania 2', 'I1': 'Italia 1', 'I2': 'Italia 2',
           'SP1': 'España 1', 'SP2': 'España 2', 'F1': 'Francia 1', 'F2': 'Francia 2', 'N1': 'Holanda 1',
           'B1': 'Bélgica 1', 'P1': 'Portugal 1', 'T1': 'Turquía 1', 'G1': 'Grecia 1'}
TENNIS_YEARS = ['2021', '2022', '2023', '2024', '2025', '2026']
EDGES = [0.0, 0.02, 0.05, 0.08]


def fetch(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
        'Accept': '*/*', 'Referer': 'http://www.tennis-data.co.uk/alldata.php'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def col(df, *names):
    for n in names:
        if n in df.columns:
            return pd.to_numeric(df[n], errors='coerce')
    return pd.Series([float('nan')] * len(df), index=df.index)


# ---------- métricas ----------
def summary(bets):
    """bets: lista de (cuota, ganada_bool) en orden cronológico."""
    n = len(bets)
    if not n:
        return {'n': 0}
    profit, peak, dd, streak, worst = 0.0, 0.0, 0.0, 0, 0
    wins = 0
    for o, w in bets:
        profit += (o - 1) if w else -1
        wins += w
        peak = max(peak, profit)
        dd = max(dd, peak - profit)
        streak = 0 if w else streak + 1
        worst = max(worst, streak)
    return {'n': n, 'acierto': round(100 * wins / n, 1), 'cuota_media': round(sum(o for o, _ in bets) / n, 2),
            'roi': round(100 * profit / n, 2), 'beneficio_u': round(profit, 1),
            'max_caida_u': round(dd, 1), 'peor_racha': worst}


def fair(odds):
    """Cuotas justas (sin margen) a partir de una lista de cuotas de Pinnacle."""
    inv = [1 / o for o in odds]
    s = sum(inv)
    return [s / i for i in inv]


# ---------- fútbol ----------
def football():
    frames = []
    for s in SEASONS:
        for code, name in LEAGUES.items():
            try:
                raw = fetch(f'https://www.football-data.co.uk/mmz4281/{s}/{code}.csv')
                df = pd.read_csv(io.BytesIO(raw), encoding='latin-1', on_bad_lines='skip')
            except Exception as ex:
                print('sin datos', s, code, ex)
                continue
            if 'FTHG' not in df.columns:
                continue
            df = df.dropna(subset=['FTHG', 'FTAG'])
            df['liga'], df['temporada'] = name, s
            df['fecha'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
            frames.append(df)
            print('ok', s, code, len(df))
    if not frames:
        return {}
    df = pd.concat(frames, ignore_index=True).sort_values('fecha')
    # cuotas: Bet365 (cierre si hay, si no apertura) y Pinnacle (cierre si hay, si no apertura)
    bH, bD, bA = col(df, 'B365CH', 'B365H'), col(df, 'B365CD', 'B365D'), col(df, 'B365CA', 'B365A')
    pH, pD, pA = col(df, 'PSCH', 'PSH'), col(df, 'PSCD', 'PSD'), col(df, 'PSCA', 'PSA')
    bO, bU = col(df, 'B365C>2.5', 'B365>2.5'), col(df, 'B365C<2.5', 'B365<2.5')
    pO, pU = col(df, 'PC>2.5', 'P>2.5'), col(df, 'PC<2.5', 'P<2.5')
    hg, ag = df['FTHG'].astype(float), df['FTAG'].astype(float)
    res = {'partidos': int(len(df)), 'temporadas': sorted(df['temporada'].unique().tolist())}

    f1 = defaultdict(list)
    f2 = {e: [] for e in EDGES}
    f2_band = {e: defaultdict(list) for e in EDGES}
    f2_liga = defaultdict(list)
    f3 = {e: [] for e in EDGES}
    for i in range(len(df)):
        h, a = hg.iat[i], ag.iat[i]
        out = {'H': h > a, 'D': h == a, 'A': h < a}
        b = {'H': bH.iat[i], 'D': bD.iat[i], 'A': bA.iat[i]}
        p = [pH.iat[i], pD.iat[i], pA.iat[i]]
        # F1 favorito ≤ 1,50
        fav = min(('H', 'A'), key=lambda k: b[k] if b[k] == b[k] else 99)
        if b[fav] == b[fav] and b[fav] <= 1.50:
            band = '≤1,20' if b[fav] <= 1.2 else '1,21-1,35' if b[fav] <= 1.35 else '1,36-1,50'
            f1[band].append((b[fav], out[fav]))
            f1['todos'].append((b[fav], out[fav]))
        # F2 valor 1X2
        if all(x == x and x > 1 for x in p) and all(b[k] == b[k] for k in b):
            fo = dict(zip('HDA', fair(p)))
            for e in EDGES:
                for k in 'HDA':
                    if b[k] > fo[k] * (1 + e):
                        f2[e].append((b[k], out[k]))
                        band = '<1,80' if b[k] < 1.8 else '1,80-2,99' if b[k] < 3 else '3,00+'
                        f2_band[e][band].append((b[k], out[k]))
                        if e == 0.02:
                            f2_liga[df['liga'].iat[i]].append((b[k], out[k]))
        # F3 valor goles
        q = [pO.iat[i], pU.iat[i]]
        bb = {'O': bO.iat[i], 'U': bU.iat[i]}
        if all(x == x and x > 1 for x in q) and all(v == v for v in bb.values()):
            fo = dict(zip('OU', fair(q)))
            go = {'O': h + a > 2.5, 'U': h + a < 2.5}
            for e in EDGES:
                for k in 'OU':
                    if bb[k] > fo[k] * (1 + e):
                        f3[e].append((bb[k], go[k]))
    res['F1_favorito'] = {k: summary(v) for k, v in f1.items()}
    res['F2_valor_1x2'] = {f'margen {int(e*100)}%': summary(v) for e, v in f2.items()}
    res['F2_por_cuota_margen2'] = {k: summary(v) for k, v in f2_band[0.02].items()}
    res['F2_por_liga_margen2'] = {k: summary(v) for k, v in sorted(f2_liga.items())}
    res['F3_valor_goles'] = {f'margen {int(e*100)}%': summary(v) for e, v in f3.items()}
    # 0-0 al descanso por liga (Filtro 2)
    if 'HTHG' in df.columns:
        ht = df.dropna(subset=['HTHG', 'HTAG'])
        z = ht.assign(z=(ht['HTHG'] + ht['HTAG'] == 0)).groupby('liga')['z'].agg(['mean', 'count'])
        res['descanso_0_0'] = {k: {'pct': round(100 * r['mean'], 1), 'n': int(r['count'])}
                               for k, r in z.sort_values('mean', ascending=False).iterrows()}
    return res


# ---------- tenis ----------
def tennis():
    frames = []
    for y in TENNIS_YEARS:
        for tour, path in (('ATP', f'{y}/{y}.xlsx'), ('WTA', f'{y}w/{y}.xlsx')):
            df = None
            for base in ('https://www.tennis-data.co.uk/', 'http://www.tennis-data.co.uk/', 'http://tennis-data.co.uk/'):
                try:
                    df = pd.read_excel(io.BytesIO(fetch(base + path)))
                    break
                except Exception as ex:
                    print('sin datos tenis', tour, y, base, ex)
            if df is None:
                continue
            df['tour'] = tour
            frames.append(df)
            print('ok tenis', tour, y, len(df))
    if not frames:
        return {}
    df = pd.concat(frames, ignore_index=True)
    if 'Comment' in df.columns:
        df = df[df['Comment'].astype(str).str.contains('Completed', na=False)]
    df = df.sort_values('Date') if 'Date' in df.columns else df
    bW, bL, pW, pL = col(df, 'B365W'), col(df, 'B365L'), col(df, 'PSW'), col(df, 'PSL')
    res = {'partidos': int(len(df))}
    for tour in ('ATP', 'WTA', 'todos'):
        m = (df['tour'] == tour) if tour != 'todos' else pd.Series(True, index=df.index)
        t1, t2 = [], {e: [] for e in EDGES}
        for i in df.index[m]:
            w, l, pw, pl = bW[i], bL[i], pW[i], pL[i]
            if w != w or l != l:
                continue
            # T1 favorito ≤ 1,35 (el favorito puede ser el que ganó o el que perdió)
            if min(w, l) <= 1.35:
                t1.append((min(w, l), w <= l))
            if pw == pw and pl == pl and pw > 1 and pl > 1:
                fw, fl = fair([pw, pl])
                for e in EDGES:
                    if w > fw * (1 + e):
                        t2[e].append((w, True))
                    if l > fl * (1 + e):
                        t2[e].append((l, False))
        res[tour] = {'T1_favorito_1_35': summary(t1),
                     'T2_valor': {f'margen {int(e*100)}%': summary(v) for e, v in t2.items()}}
    return res


def table(d):
    rows = ['| | Apuestas | Acierto | Cuota media | ROI | Beneficio (u) | Peor caída (u) | Peor racha |',
            '|---|---|---|---|---|---|---|---|']
    for k, v in d.items():
        if v.get('n'):
            rows.append(f"| {k} | {v['n']} | {v['acierto']}% | {v['cuota_media']} | **{v['roi']}%** | "
                        f"{v['beneficio_u']} | {v['max_caida_u']} | {v['peor_racha']} |")
    return '\n'.join(rows)


def main():
    os.makedirs(OUT, exist_ok=True)
    fb, tn = football(), tennis()
    json.dump({'futbol': fb, 'tenis': tn}, open(os.path.join(OUT, 'backtest.json'), 'w'), ensure_ascii=False, indent=1)
    md = ['# Estudio histórico A. Analytics', '',
          'Stake fijo de 1 unidad · cuota de apuesta = Bet365 (cierre) · cuota justa = Pinnacle sin margen.',
          'ROI > 0 = la estrategia gana dinero a largo plazo.', '']
    if fb:
        md += [f"## Fútbol ({fb['partidos']} partidos, temporadas {', '.join(fb['temporadas'])})", '',
               '### F1 · Favorito ≤ 1,50 (estrategia actual)', table(fb['F1_favorito']), '',
               '### F2 · Valor 1X2 (Bet365 > cuota justa Pinnacle + margen)', table(fb['F2_valor_1x2']), '',
               '#### F2 con margen 2 %, por cuota', table(fb['F2_por_cuota_margen2']), '',
               '#### F2 con margen 2 %, por liga', table(fb['F2_por_liga_margen2']), '',
               '### F3 · Valor más/menos de 2,5 goles', table(fb['F3_valor_goles']), '']
        if 'descanso_0_0' in fb:
            md += ['### 0-0 al descanso por liga', '| Liga | % 0-0 al descanso | Partidos |', '|---|---|---|']
            md += [f"| {k} | {v['pct']}% | {v['n']} |" for k, v in fb['descanso_0_0'].items()]
            md += ['']
    if tn:
        md += [f"## Tenis ({tn['partidos']} partidos)", '']
        for tour in ('ATP', 'WTA', 'todos'):
            if tour in tn:
                md += [f'### {tour}', table({'T1 favorito ≤ 1,35': tn[tour]['T1_favorito_1_35'],
                                             **{f'T2 valor {k}': v for k, v in tn[tour]['T2_valor'].items()}}), '']
    open(os.path.join(OUT, 'backtest.md'), 'w').write('\n'.join(md))
    print('\n'.join(md))


if __name__ == '__main__':
    main()
