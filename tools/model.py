#!/usr/bin/env python3
"""Modelo estadístico de A. Analytics (corre en GitHub cada hora, sin Claude).

Combina:
  · data/history.csv  -> 5 temporadas de 22 ligas europeas (descanso, córners, tiros) por liga y por equipo
  · app.csv           -> nuestro registro diario (resultados + estadísticas ESPN/SofaScore) para el resto de ligas
Escribe en data/ (los importa el Google Sheet):
  tab_menos05.csv     partidos de HOY ordenados por probabilidad de 0-0 al descanso
  tab_mas05.csv       partidos de HOY ordenados por probabilidad de gol antes del descanso
  tab_corners.csv     partidos de HOY ordenados de menos a más córners esperados
  pronosticos.csv     el filtro "lo mejor de lo mejor" de HOY (+ el pick del día arriba)
  pronosticos_log.csv todos los pronósticos del filtro, con su resultado (para el % de acierto)
"""
import csv, json, math, os, re, sys, unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
TZ = ZoneInfo('Europe/Lisbon')
D = os.path.join(ROOT, 'data')
HIST, APP = os.path.join(D, 'history.csv'), os.path.join(ROOT, 'app.csv')
LOG = os.path.join(D, 'pronosticos_log.csv')
TEAM_DAYS = 550          # forma de los equipos: últimos ~18 meses
SHRINK = 10              # partidos "virtuales" de media de liga para no fiarse de pocas muestras
BLEND = 0.6              # peso del ajuste por equipos; el resto es la media real de la liga (más prudente)
MIN_HIST, MIN_REG, MIN_SHOW = 100, 12, 5   # MIN_REG: para el filtro · MIN_SHOW: para salir en las pestañas

# ---- umbrales del filtro "lo mejor de lo mejor" ----
BEST = {
    'Menos de 1,5 goles 1.ª parte': 0.72,
    'Más de 0,5 goles 1.ª parte': 0.76,
    'Menos de 0,5 goles 1.ª parte': 0.42,
    'Menos de 10,5 córners': 0.76,
    'Más de 7,5 córners': 0.76,
    'Ganador / doble oportunidad': 0.85,
}

ALIAS = {'man': 'manchester', 'utd': 'united', 'ath': 'atletico', 'sp': 'sporting', 'st': 'saint',
         'nott m': 'nottingham', "nott'm": 'nottingham', 'wolves': 'wolverhampton', 'spurs': 'tottenham',
         'qpr': 'queens park rangers', 'mgladbach': 'monchengladbach', "m'gladbach": 'monchengladbach',
         'ein': 'eintracht', 'psg': 'paris saint germain', 'paris sg': 'paris saint germain',
         'sheffield weds': 'sheffield wednesday', 'espanol': 'espanyol', 'vallecano': 'rayo vallecano',
         'sociedad': 'real sociedad', 'betis': 'real betis', 'koln': 'cologne', 'hamburger sv': 'hamburg',
         'rvs': 'rovers'}


def norm(s):
    s = unicodedata.normalize('NFD', s or '').encode('ascii', 'ignore').decode().lower()
    s = re.sub(r"[^a-z0-9' ]", ' ', s)
    for k, v in ALIAS.items():
        s = re.sub(rf'\b{re.escape(k)}\b', v, s)
    s = re.sub(r"'", '', s)
    s = re.sub(r'\b(fc|sc|cf|ac|afc|club|de|the|cd|ud|sd|rc|fk|sk|as|ss|us|calcio|1|2)\b', ' ', s)
    return ' '.join(s.split())


def match_team(name, teams):
    """Busca el nombre de football-data que corresponde a un equipo de OddSlot (misma liga)."""
    n = norm(name)
    if not n:
        return None
    best, score = None, 0.0
    for t in teams:
        m = norm(t)
        if m == n:
            return t
        a, b = set(n.split()), set(m.split())
        s = SequenceMatcher(None, n, m).ratio()
        if a and b and (a <= b or b <= a):
            s = max(s, 0.9)
        if s > score:
            best, score = t, s
    return best if score >= 0.78 else None


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# ---------------- estadísticas ----------------
def load_csv(p):
    if not os.path.exists(p):
        return []
    with open(p, encoding='utf-8') as f:
        return list(csv.DictReader(f))


def league_stats(hist, reg):
    """Por liga: muestra, % 0-0 al descanso, goles al descanso (local/visitante), córners media/varianza."""
    L = {}
    by = defaultdict(list)
    for r in hist:
        by[r['liga']].append(r)
    for liga, rs in by.items():
        ht = [r for r in rs if r['htl'] != '' and r['htv'] != '']
        co = [r for r in rs if r['cl'] != '' and r['cv'] != '']
        if len(ht) < MIN_HIST:
            continue
        tot = [int(r['cl']) + int(r['cv']) for r in co]
        mc = mean(tot)
        L[liga] = {'fuente': f'Histórico 5 años', 'n_ht': len(ht),
                   'p00': sum(int(r['htl']) + int(r['htv']) == 0 for r in ht) / len(ht),
                   'hh': mean([int(r['htl']) for r in ht]), 'ha': mean([int(r['htv']) for r in ht]),
                   'n_c': len(co), 'c_mean': mc,
                   'c_var': mean([(t - mc) ** 2 for t in tot]) if co else None,
                   'ch': mean([int(r['cl']) for r in co]), 'ca': mean([int(r['cv']) for r in co]),
                   'e_le1': sum(int(r['htl']) + int(r['htv']) <= 1 for r in ht) / len(ht),
                   'e_u105': mean([t <= 10 for t in tot]), 'e_u95': mean([t <= 9 for t in tot]),
                   'e_o75': mean([t >= 8 for t in tot]), 'e_o85': mean([t >= 9 for t in tot])}
    # ligas sin histórico: nuestro registro (ESPN / SofaScore)
    rb = defaultdict(list)
    for r in reg:
        if r['Liga'] not in L:
            rb[r['Liga']].append(r)
    for liga, rs in rb.items():
        ht = [r for r in rs if re.match(r'\d+ - \d+', r.get('Descanso', ''))]
        co = [int(r['Córners total']) for r in rs if (r.get('Córners total') or '').isdigit()]
        if len(ht) < MIN_SHOW and len(co) < MIN_SHOW:
            continue
        hh = [int(r['Descanso'].split(' - ')[0]) for r in ht]
        ha = [int(r['Descanso'].split(' - ')[1]) for r in ht]
        mc = mean(co)
        okh, okc = len(ht) >= MIN_SHOW, len(co) >= MIN_SHOW
        p00 = (sum(h + a == 0 for h, a in zip(hh, ha)) / len(ht)) if okh else None
        if p00 is not None:  # con pocas muestras se acerca a la media general (≈30 %) para no exagerar
            p00 = (len(ht) * p00 + SHRINK * 0.30) / (len(ht) + SHRINK)
        L[liga] = {'fuente': 'Registro ESPN/SofaScore' + ('' if len(ht) >= MIN_REG else ' (muestra baja)'),
                   'n_ht': len(ht) if okh else 0, 'p00': p00,
                   'hh': mean(hh), 'ha': mean(ha), 'n_c': len(co) if okc else 0,
                   'c_mean': mc if okc else None,
                   'c_var': (mean([(t - mc) ** 2 for t in co]) or mc) if okc else None,
                   'ch': None, 'ca': None}
    return L


def team_stats(hist, today):
    """Por liga y equipo: en casa / fuera, goles al descanso a favor y en contra, córners a favor y en contra."""
    cut = (today - timedelta(days=TEAM_DAYS)).isoformat()
    T = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for r in hist:
        if r['fecha'] < cut or r['htl'] == '':
            continue
        h, a, lg = r['local'], r['visitante'], r['liga']
        T[lg][h]['h_gf'].append(int(r['htl'])); T[lg][h]['h_ga'].append(int(r['htv']))
        T[lg][a]['a_gf'].append(int(r['htv'])); T[lg][a]['a_ga'].append(int(r['htl']))
        if r['cl'] != '':
            T[lg][h]['h_cf'].append(int(r['cl'])); T[lg][h]['h_ca'].append(int(r['cv']))
            T[lg][a]['a_cf'].append(int(r['cv'])); T[lg][a]['a_ca'].append(int(r['cl']))
    return T


def ratio(xs, base):
    """Factor del equipo respecto a la media de la liga, encogido hacia 1 con pocas muestras."""
    if not xs or not base:
        return 1.0, 0
    r = (sum(xs) / len(xs)) / base
    n = len(xs)
    return (n * r + SHRINK) / (n + SHRINK), n


def predict(row, L, T):
    """Probabilidades del partido: goles al descanso y córners."""
    lg = L.get(row['Liga'])
    if not lg:
        return None
    teams = T.get(row['Liga'], {})
    th = match_team(row['Local'], teams) if teams else None
    ta = match_team(row['Visitante'], teams) if teams else None
    out = {'fuente': lg['fuente'], 'n_liga': lg['n_ht'], 'equipos': 'Sí' if th and ta else 'No'}
    if lg.get('p00') and lg.get('hh') is not None:
        lam_l = (lg['hh'] or 0) + (lg['ha'] or 0)
        lh, la = lg['hh'], lg['ha']
        if th and ta:
            att_h, _ = ratio(teams[th]['h_gf'], lg['hh']); def_a, _ = ratio(teams[ta]['a_ga'], lg['hh'])
            att_a, _ = ratio(teams[ta]['a_gf'], lg['ha']); def_h, _ = ratio(teams[th]['h_ga'], lg['ha'])
            lh, la = lg['hh'] * att_h * def_a, lg['ha'] * att_a * def_h
        lam = lh + la
        p00 = lg['p00'] ** (lam / lam_l) if lam_l else lg['p00']
        leff = -math.log(max(p00, 1e-6))
        ple1 = min(p00 * (1 + leff), 0.999)
        if th and ta:  # mezcla prudente con la frecuencia real de la liga
            p00 = BLEND * p00 + (1 - BLEND) * lg['p00']
            if lg.get('e_le1'):
                ple1 = BLEND * ple1 + (1 - BLEND) * lg['e_le1']
        # calibración medida con 2 temporadas (tools/calibrate.py): el modelo se pasaba de optimista arriba
        if ple1 > 0.70:
            ple1 = 0.70 + (ple1 - 0.70) * 0.4
        if 1 - p00 > 0.75:
            p00 = 1 - (0.75 + (1 - p00 - 0.75) * 0.5)
        out.update({'p00': p00, 'p_le1': ple1, 'xg_ht': lam})
    if lg.get('c_mean') and lg.get('c_var'):
        mu = lg['c_mean']
        if th and ta and lg.get('ch') and lg.get('ca'):
            f_h, _ = ratio(teams[th]['h_cf'], lg['ch']); g_a, _ = ratio(teams[ta]['a_ca'], lg['ch'])
            f_a, _ = ratio(teams[ta]['a_cf'], lg['ca']); g_h, _ = ratio(teams[th]['h_ca'], lg['ca'])
            mu = lg['ch'] * f_h * g_a + lg['ca'] * f_a * g_h
        sd = math.sqrt(lg['c_var'] * mu / lg['c_mean'])
        c = {'c_u105': phi((10.5 - mu) / sd), 'c_u95': phi((9.5 - mu) / sd),
             'c_o75': 1 - phi((7.5 - mu) / sd), 'c_o85': 1 - phi((8.5 - mu) / sd)}
        if th and ta and lg.get('e_u105') is not None:
            c = {k: BLEND * v + (1 - BLEND) * lg['e' + k[1:]] for k, v in c.items()}
        out.update({'c_exp': mu, 'n_c': lg['n_c'], **c})
    return out


# ---------------- salida ----------------
def pct(p):
    return f'{100 * p:.0f}%' if p is not None else ''


def fair(p):
    return f'{1 / p:.2f}' if p else ''


def write(name, fields, rows):
    with open(os.path.join(D, name), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def kind(p):
    return 'gana' if p.startswith('Gana ') else 'doble'


def reg_rates(reg):
    st = {}
    for r in reg:
        if r.get('Ganado (1/0)') in ('0', '1'):
            for k in (r['Liga'], (r['Liga'], kind(r['Pronóstico']))):
                n, g = st.get(k, (0, 0))
                st[k] = (n + 1, g + int(r['Ganado (1/0)']))
    return {k: (n, g / n) for k, (n, g) in st.items() if n >= 8}


def judge(market, r):
    """Resultado de un pronóstico con los datos del registro (None = todavía sin dato)."""
    ht = re.match(r'(\d+) - (\d+)', r.get('Descanso', '') or '')
    if '1.ª parte' in market:
        if not ht:
            return None, ''
        g = int(ht.group(1)) + int(ht.group(2))
        ok = {'Menos de 1,5 goles 1.ª parte': g <= 1, 'Más de 0,5 goles 1.ª parte': g >= 1,
              'Menos de 0,5 goles 1.ª parte': g == 0}[market]
        return ok, f"Descanso {r['Descanso']}"
    if 'córners' in market:
        c = r.get('Córners total', '')
        if not c.isdigit():
            return None, ''
        ok = int(c) <= 10 if market.startswith('Menos') else int(c) >= 8
        return ok, f'{c} córners'
    if r.get('Acierto') in ('Acertado', 'Fallado'):
        return r['Acierto'] == 'Acertado', r.get('Resultado', '')
    return None, ''


def main():
    os.makedirs(D, exist_ok=True)
    now = datetime.now(TZ)
    today = now.date()
    hist, reg = load_csv(HIST), load_csv(APP)
    L, T = league_stats(hist, reg), team_stats(hist, today)
    rates = reg_rates(reg)
    hoy = [r for r in reg if r['Fecha'] == today.isoformat()]
    m05, p05, cor, best = [], [], [], []
    for r in hoy:
        pr = predict(r, L, T) or {}
        base = {'Hora': r['Hora'], 'Liga': r['Liga'], 'Local': r['Local'], 'Visitante': r['Visitante'],
                'Resultado': r.get('Resultado', ''), 'Descanso': r.get('Descanso', '')}
        src = pr.get('fuente', 'Sin datos')
        if 'p00' in pr:
            m05.append({**base, 'Prob 0-0 descanso': pct(pr['p00']), 'Cuota justa −0,5': fair(pr['p00']),
                        'Prob −1,5 1.ª parte': pct(pr['p_le1']), 'Cuota justa −1,5': fair(pr['p_le1']),
                        'Goles esperados 1.ª parte': f"{pr['xg_ht']:.2f}", 'Muestra liga': pr['n_liga'],
                        'Datos de equipos': pr['equipos'], 'Fuente': src, '_k': pr['p00']})
            p05.append({**base, 'Prob gol 1.ª parte': pct(1 - pr['p00']), 'Cuota justa +0,5': fair(1 - pr['p00']),
                        'Prob +1,5 1.ª parte': pct(1 - pr['p_le1']), 'Cuota justa +1,5': fair(1 - pr['p_le1']),
                        'Goles esperados 1.ª parte': f"{pr['xg_ht']:.2f}", 'Muestra liga': pr['n_liga'],
                        'Datos de equipos': pr['equipos'], 'Fuente': src, '_k': 1 - pr['p00']})
            for mk, p in (('Menos de 1,5 goles 1.ª parte', pr['p_le1']), ('Más de 0,5 goles 1.ª parte', 1 - pr['p00']),
                          ('Menos de 0,5 goles 1.ª parte', pr['p00'])):
                if p >= BEST[mk] and pr['n_liga'] >= MIN_REG:
                    best.append({**base, 'Mercado': mk, 'p': p, 'Muestra': pr['n_liga'], 'Fuente': src,
                                 'Equipos': pr['equipos']})
        if 'c_exp' in pr:
            cor.append({**base, 'Córners esperados': f"{pr['c_exp']:.1f}", 'Prob menos 9,5': pct(pr['c_u95']),
                        'Prob menos 10,5': pct(pr['c_u105']), 'Prob más 7,5': pct(pr['c_o75']),
                        'Prob más 8,5': pct(pr['c_o85']), 'Muestra liga': pr['n_c'],
                        'Datos de equipos': pr['equipos'], 'Fuente': src, '_k': pr['c_exp']})
            for mk, p in (('Menos de 10,5 córners', pr['c_u105']), ('Más de 7,5 córners', pr['c_o75'])):
                if p >= BEST[mk] and pr.get('equipos') == 'Sí':
                    best.append({**base, 'Mercado': mk, 'p': p, 'Muestra': pr['n_c'], 'Fuente': src,
                                 'Equipos': pr['equipos']})
        # ganador / doble oportunidad: acierto real del modelo ★★★ en esa liga
        k = (r['Liga'], kind(r['Pronóstico']))
        n, rate = rates.get(k) or rates.get(r['Liga']) or (0, 0)
        if n >= MIN_REG and rate >= BEST['Ganador / doble oportunidad']:
            mk = 'Victoria ' + r['Pronóstico'][5:] if r['Pronóstico'].startswith('Gana ') else r['Pronóstico']
            best.append({**base, 'Mercado': mk, 'p': rate, 'Muestra': n, 'Fuente': 'Acierto ★★★ en la liga',
                         'Equipos': '', 'Cuota casa': r.get('Cuota', '')})
    key = lambda x: (-x['_k'], x['Hora'])
    m05.sort(key=key); p05.sort(key=key); cor.sort(key=lambda x: (x['_k'], x['Hora']))
    for rows in (m05, p05, cor):
        for x in rows:
            x.pop('_k')
    base_f = ['Hora', 'Liga', 'Local', 'Visitante']
    write('tab_menos05.csv', base_f + ['Prob 0-0 descanso', 'Cuota justa −0,5', 'Prob −1,5 1.ª parte', 'Cuota justa −1,5',
                                       'Goles esperados 1.ª parte', 'Muestra liga', 'Datos de equipos', 'Fuente',
                                       'Descanso', 'Resultado'], m05)
    write('tab_mas05.csv', base_f + ['Prob gol 1.ª parte', 'Cuota justa +0,5', 'Prob +1,5 1.ª parte', 'Cuota justa +1,5',
                                     'Goles esperados 1.ª parte', 'Muestra liga', 'Datos de equipos', 'Fuente',
                                     'Descanso', 'Resultado'], p05)
    write('tab_corners.csv', base_f + ['Córners esperados', 'Prob menos 9,5', 'Prob menos 10,5', 'Prob más 7,5',
                                       'Prob más 8,5', 'Muestra liga', 'Datos de equipos', 'Fuente', 'Resultado'], cor)

    # ---- filtro: lo mejor de lo mejor (máx. 1 mercado de goles y 1 de córners por partido) ----
    best.sort(key=lambda x: -x['p'])
    seen, top = set(), []
    for b in best:
        fam = 'goles' if '1.ª parte' in b['Mercado'] else 'corners' if 'córners' in b['Mercado'] else 'ganador'
        k = (b['Local'], b['Visitante'], fam)
        if k in seen:
            continue
        seen.add(k)
        top.append(b)
    top = top[:40]
    rows = []
    try:
        bp = json.load(open(os.path.join(ROOT, 'bot_pick.json')))
        if bp.get('fecha') == today.isoformat() and bp.get('legs'):
            for l in bp['legs']:
                rows.append({'Tipo': '⭐ PICK DEL DÍA', 'Hora': '', 'Liga': l['Liga'],
                             'Partido': f"{l['Local']} vs {l['Visitante']}", 'Mercado': l['Pronóstico'],
                             'Probabilidad': '', 'Cuota justa': '', 'Cuota casa': l['Cuota'], 'Muestra': '',
                             'Fuente': f"Combinada {str(bp.get('cuota', '')).replace('.', ',')}", 'Resultado': '', 'Acierto': ''})
    except Exception:
        pass
    idx = {(r['Fecha'], r['Local'], r['Visitante']): r for r in reg}
    for b in sorted(top, key=lambda x: (x['Hora'], -x['p'])):
        ok, res = judge(b['Mercado'], idx.get((today.isoformat(), b['Local'], b['Visitante']), {}))
        rows.append({'Tipo': 'Filtro', 'Hora': b['Hora'], 'Liga': b['Liga'], 'Partido': f"{b['Local']} vs {b['Visitante']}",
                     'Mercado': b['Mercado'], 'Probabilidad': pct(b['p']), 'Cuota justa': fair(b['p']),
                     'Cuota casa': b.get('Cuota casa', ''), 'Muestra': b['Muestra'], 'Fuente': b['Fuente'],
                     'Resultado': res, 'Acierto': '' if ok is None else 'Acertado' if ok else 'Fallado'})
    PF = ['Tipo', 'Hora', 'Liga', 'Partido', 'Mercado', 'Probabilidad', 'Cuota justa', 'Cuota casa', 'Muestra',
          'Fuente', 'Resultado', 'Acierto']
    write('pronosticos.csv', PF, rows)

    # ---- registro acumulado del filtro, con resultados ----
    LF = ['Fecha', 'Hora', 'Liga', 'Local', 'Visitante', 'Mercado', 'Probabilidad', 'Cuota justa', 'Muestra',
          'Resultado', 'Acierto', 'Ganado (1/0)']
    log = {(r['Fecha'], r['Local'], r['Visitante'], r['Mercado']): r for r in load_csv(LOG)}
    if True:  # se guarda lo seleccionado ANTES de que empiece cada partido
        for b in top:
            k = (today.isoformat(), b['Local'], b['Visitante'], b['Mercado'])
            start = datetime.strptime(f"{today.isoformat()} {b['Hora']}", '%Y-%m-%d %H:%M').replace(tzinfo=TZ)
            if k not in log and start > now:
                log[k] = {'Fecha': k[0], 'Hora': b['Hora'], 'Liga': b['Liga'], 'Local': b['Local'],
                          'Visitante': b['Visitante'], 'Mercado': b['Mercado'], 'Probabilidad': pct(b['p']),
                          'Cuota justa': fair(b['p']), 'Muestra': b['Muestra'], 'Resultado': '', 'Acierto': '',
                          'Ganado (1/0)': ''}
    for k, r in log.items():
        if r['Acierto']:
            continue
        ok, res = judge(r['Mercado'], idx.get((r['Fecha'], r['Local'], r['Visitante']), {}))
        if ok is not None:
            r['Resultado'], r['Acierto'], r['Ganado (1/0)'] = res, 'Acertado' if ok else 'Fallado', '1' if ok else '0'
    write('pronosticos_log.csv', LF, sorted(log.values(), key=lambda r: (r['Fecha'], r['Hora']), reverse=True))
    print(f'Ligas con datos: {len(L)} · hoy: {len(hoy)} partidos · −0,5: {len(m05)} · córners: {len(cor)} · '
          f'filtro: {len(top)} · registro filtro: {len(log)}')


if __name__ == '__main__':
    main()
