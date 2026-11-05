#!/usr/bin/env python3
"""A. Analytics – bot de CÓRNERS en vivo (datos de SofaScore, corre en tu PC).

MODO OBSERVACIÓN: avisa por Telegram y apunta cada señal en corners_log.csv; cuando el
partido termina, comprueba si habría ganado y lo marca. Cada noche (a las 23:30) manda un
resumen con el % de acierto. Sirve para probar los filtros antes de apostar dinero.

Filtros:
  C1 · FAVORITO APRETANDO (minuto 55-70): el favorito de antes del partido (cuota ≤ 1,70)
       va empatando o perdiendo, tiene ≥ 58 % de posesión y al menos el doble de tiros que
       el rival -> "Más de X córners en el partido" (línea en vivo con cuota ≥ 1,60).
  C2 · RITMO ALTO (minuto 20-30): ya hay ≥ 5 córners y ≥ 10 tiros entre los dos
       -> "Más de X córners en el partido" (línea en vivo con cuota ≥ 1,60).

Usa el mismo bot_config.txt (token) que el bot de fútbol.
"""
import csv, json, os, re, sys, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pc_bot as base

STATE = os.path.join(HERE, 'corners_state.json')
LOG = os.path.join(HERE, 'corners_log.csv')
FIELDS = ['fecha', 'hora', 'filtro', 'event_id', 'partido', 'liga', 'minuto', 'marcador',
          'corners_al_avisar', 'linea', 'cuota', 'corners_final', 'resultado']
MIN_ODD = 1.60
EXCLUDE = base.EXCLUDE


def load():
    try:
        return json.load(open(STATE))
    except Exception:
        return {'sent': {}, 'last_summary': ''}


def save(s):
    cut = time.time() - 3 * 86400
    s['sent'] = {k: v for k, v in s['sent'].items() if v > cut}
    json.dump(s, open(STATE, 'w'))


def num(v):
    try:
        return float(str(v).replace('%', ''))
    except (TypeError, ValueError):
        return 0.0


def stats(eid):
    d = base.sget(f'/event/{eid}/statistics') or {}
    out = {}
    for p in d.get('statistics', []):
        if p.get('period') != 'ALL':
            continue
        for g in p.get('groups', []):
            for i in g.get('statisticsItems', []):
                out.setdefault(i['key'], (i.get('homeValue', i.get('home')), i.get('awayValue', i.get('away'))))
    return out


def odds(eid):
    d = base.sget(f'/event/{eid}/odds/1/all') or {}
    pre, lines = {}, []
    for m in d.get('markets', []):
        ch = {c['name']: c for c in m.get('choices', [])}
        if m.get('marketName') == 'Full time' and not m.get('isLive'):
            pre = {k: base.frac(c.get('initialFractionalValue') or c.get('fractionalValue')) for k, c in ch.items()}
        if m.get('marketName', '').startswith('Corners') and m.get('isLive') and not m.get('suspended'):
            try:
                line = float(m.get('choiceGroup'))
            except (TypeError, ValueError):
                continue
            o = base.frac((ch.get('Over') or {}).get('fractionalValue'))
            if o:
                lines.append((line, o))
    return pre, sorted(lines)


def pick_line(lines, current):
    """La línea más baja (por encima de los córners actuales) con cuota de 'Más' ≥ MIN_ODD."""
    for line, o in lines:
        if line > current and o >= MIN_ODD:
            return line, o
    return None, None


def log_row(row):
    new = not os.path.exists(LOG)
    with open(LOG, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def read_log():
    if not os.path.exists(LOG):
        return []
    with open(LOG, encoding='utf-8') as f:
        return list(csv.DictReader(f))


def write_log(rows):
    with open(LOG, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def link(e):
    return f"https://www.sofascore.com/pt/football/match/{e.get('slug','')}/{e.get('customId','')}#id:{e['id']}"


def alert(cid, e, filtro, mn, st, line, o, extra):
    hs, as_ = e['homeScore'].get('current', 0), e['awayScore'].get('current', 0)
    co = [int(num(x)) for x in st.get('cornerKicks', (0, 0))]
    sh = [int(num(x)) for x in st.get('totalShotsOnGoal', (0, 0))]
    po = st.get('ballPossession', ('–', '–'))
    liga = f"{e['tournament']['name']} ({(e['tournament'].get('category') or {}).get('name','')})"
    title = '🚩 <b>CÓRNERS · FAVORITO APRETANDO</b>' if filtro == 'C1' else '🚩 <b>CÓRNERS · RITMO ALTO</b>'
    msg = (f"{title} · 🧪 modo observación\n\n⚽ <b>{e['homeTeam']['name']} – {e['awayTeam']['name']}</b>\n"
           f"🏆 {liga}\n⏱️ Minuto {mn} · {hs}-{as_}\n\n"
           f"🚩 Córners: {co[0]}-{co[1]} (total {sum(co)})\n👟 Tiros: {sh[0]}-{sh[1]}\n"
           f"⚽ Posesión: {po[0]}-{po[1]}{extra}\n\n"
           f"✅ <b>Más de {line:g} córners en el partido</b> · cuota ≈ {o:.2f}\n"
           f"📝 Lo apunto para ver si acierta (no es entrada todavía)\n"
           f"🔗 <a href=\"{link(e)}\">Ver en SofaScore</a>")
    base.send(cid, msg)
    log_row({'fecha': datetime.now().strftime('%Y-%m-%d'), 'hora': datetime.now().strftime('%H:%M'),
             'filtro': filtro, 'event_id': e['id'], 'partido': f"{e['homeTeam']['name']} – {e['awayTeam']['name']}",
             'liga': liga, 'minuto': mn, 'marcador': f'{hs}-{as_}', 'corners_al_avisar': sum(co),
             'linea': line, 'cuota': f'{o:.2f}', 'corners_final': '', 'resultado': ''})
    print(datetime.now().strftime('%H:%M'), 'SEÑAL', filtro, e['homeTeam']['name'], '-', e['awayTeam']['name'], f'+{line}')


def scan(state, cid):
    data = base.sget('/sport/football/events/live')
    if not data:
        print(datetime.now().strftime('%H:%M'), 'SofaScore no responde')
        return
    now = time.time()
    for e in data.get('events', []):
        tname = (e.get('tournament') or {}).get('name', '')
        if EXCLUDE.search(tname) or EXCLUDE.search(e['homeTeam']['name']) or EXCLUDE.search(e['awayTeam']['name']):
            continue
        status = (e.get('status') or {}).get('description', '')
        start = (e.get('time') or {}).get('currentPeriodStartTimestamp')
        if not start or status not in ('1st half', '2nd half'):
            continue
        mn = int((now - start) / 60) + (45 if status == '2nd half' else 0)
        filtro = 'C2' if status == '1st half' and 20 <= mn <= 30 else 'C1' if status == '2nd half' and 55 <= mn <= 70 else None
        if not filtro or f"{filtro}:{e['id']}" in state['sent']:
            continue
        st = stats(e['id'])
        if 'cornerKicks' not in st or 'totalShotsOnGoal' not in st:
            continue  # sin estadísticas no hay señal
        co = [num(x) for x in st['cornerKicks']]
        sh = [num(x) for x in st['totalShotsOnGoal']]
        extra = ''
        if filtro == 'C2':
            if sum(co) < 5 or sum(sh) < 10:
                continue
        else:
            pre, _ = odds(e['id'])
            if not pre:
                continue
            fav = 0 if (pre.get('1') or 99) < (pre.get('2') or 99) else 1
            p = pre.get('1' if fav == 0 else '2')
            hs, as_ = e['homeScore'].get('current', 0), e['awayScore'].get('current', 0)
            fav_goals, opp_goals = (hs, as_) if fav == 0 else (as_, hs)
            po = [num(x) for x in st.get('ballPossession', (0, 0))]
            if not p or p > 1.70 or fav_goals > opp_goals or po[fav] < 58 or sh[fav] < 2 * max(sh[1 - fav], 1):
                continue
            extra = f"\n⭐ Favorito: {(e['homeTeam'] if fav == 0 else e['awayTeam'])['name']} (pagaba {p:.2f})"
        _, lines = odds(e['id'])
        line, o = pick_line(lines, sum(co))
        if not line:
            continue
        alert(cid, e, filtro, mn, st, line, o, extra)
        state['sent'][f"{filtro}:{e['id']}"] = now
        time.sleep(0.4)


def resolve():
    """Marca como ganada/perdida cada señal de partidos ya terminados."""
    rows = read_log()
    changed = False
    for r in rows:
        if r['resultado']:
            continue
        ev = (base.sget(f"/event/{r['event_id']}") or {}).get('event') or {}
        if (ev.get('status') or {}).get('type') != 'finished':
            continue
        st = stats(r['event_id'])
        if 'cornerKicks' not in st:
            continue
        total = int(sum(num(x) for x in st['cornerKicks']))
        r['corners_final'] = total
        r['resultado'] = 'GANADA' if total > float(r['linea']) else 'PERDIDA'
        changed = True
    if changed:
        write_log(rows)
    return rows


def summary(cid, rows, day):
    hoy = [r for r in rows if r['fecha'] == day and r['resultado']]
    if not hoy:
        return
    g = sum(r['resultado'] == 'GANADA' for r in hoy)
    total = [r for r in rows if r['resultado']]
    gt = sum(r['resultado'] == 'GANADA' for r in total)
    lines = '\n'.join(f"{'✅' if r['resultado']=='GANADA' else '❌'} {r['partido']} · +{r['linea']} "
                      f"({r['corners_final']} córners) · {r['filtro']}" for r in hoy[:20])
    base.send(cid, f"🚩 <b>Resumen córners · {day}</b> (modo observación)\n\n{lines}\n\n"
                   f"Hoy: <b>{g}/{len(hoy)}</b> · Acumulado: <b>{gt}/{len(total)}</b> "
                   f"({100*gt/len(total):.0f} %)")


def main():
    if not base.CFG.get('TELEGRAM_TOKEN'):
        sys.exit('Falta TELEGRAM_TOKEN en bot_config.txt')
    state = load()
    cid = base.get_chat(base.load_state())
    if not cid:
        sys.exit('Escribe "hola" a tu bot en Telegram y vuelve a abrir el programa.')
    base.send(cid, '🚩 <b>Bot de CÓRNERS activado</b> · 🧪 modo observación\nAviso señales de córners y apunto '
                   'si habrían ganado. Cada noche te mando el resumen con el % de acierto.')
    print('Bot de CÓRNERS en marcha (modo observación). Deja esta ventana abierta. (Ctrl+C para parar)')
    i = 0
    while True:
        try:
            scan(state, cid)
            if i % 10 == 0:
                rows = resolve()
                day = datetime.now().strftime('%Y-%m-%d')
                if datetime.now().strftime('%H:%M') >= '23:30' and state.get('last_summary') != day:
                    summary(cid, rows, day)
                    state['last_summary'] = day
            save(state)
        except Exception as ex:
            print('Error:', ex)
        i += 1
        time.sleep(60)


if __name__ == '__main__':
    main()
