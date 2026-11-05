#!/usr/bin/env python3
"""Pick del día automático para el bot de Telegram (corre en GitHub Actions, sin Claude).

  python3 tools/daily_pick.py send    -> arma el pick de hoy desde app.csv y lo manda al bot
  python3 tools/daily_pick.py check   -> si el pick ya terminó, manda el resultado (una vez)
  python3 tools/daily_pick.py preview -> muestra el pick en pantalla sin mandarlo

Reglas:
  · 2 partidos de HOY de ligas distintas que empiecen dentro de ≥ 45 min
  · prioridad: "Gana X" en las ligas con mejor % de acierto en el registro (mín. 5 partidos)
  · cuota combinada ≥ 1,80 (y ≤ 2,60); si no hay con "Gana", se permite una doble oportunidad
  · se elige la pareja con mayor probabilidad conjunta (acierto liga × acierto liga)
"""
import csv, io, json, os, sys, urllib.parse, urllib.request
from datetime import datetime, timedelta
from itertools import combinations
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
TZ = ZoneInfo('Europe/Lisbon')
CSV = os.path.join(ROOT, 'app.csv')
STATE = os.path.join(ROOT, 'bot_pick.json')
MIN_N, MIN_TOTAL, MAX_TOTAL = 5, 1.80, 2.60
TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()


def chat_id():
    cid = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if cid:
        return cid
    for p in ('bot_state.json', os.path.join(ROOT, 'bot_state.json')):
        try:
            return json.load(open(p)).get('chat_id')
        except Exception:
            pass
    return None


def tg(method, **params):
    req = urllib.request.Request(f'https://api.telegram.org/bot{TOKEN}/{method}',
                                 data=urllib.parse.urlencode(params).encode())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def rows():
    with open(CSV, encoding='utf-8') as f:
        return list(csv.DictReader(f))


def league_stats(rs):
    st = {}
    for r in rs:
        if r['Ganado (1/0)'] in ('0', '1'):
            n, g = st.get(r['Liga'], (0, 0))
            st[r['Liga']] = (n + 1, g + int(r['Ganado (1/0)']))
    return {k: (n, g / n) for k, (n, g) in st.items() if n >= MIN_N}


def build(rs, now=None):
    now = now or datetime.now(TZ)
    today = now.strftime('%Y-%m-%d')
    stats = league_stats(rs)
    cands = []
    for r in rs:
        if r['Fecha'] != today or r['Liga'] not in stats or not r['Cuota']:
            continue
        start = datetime.strptime(f"{r['Fecha']} {r['Hora']}", '%Y-%m-%d %H:%M').replace(tzinfo=TZ)
        if start < now + timedelta(minutes=45):
            continue
        n, rate = stats[r['Liga']]
        cands.append(dict(r, n=n, rate=rate, cuota=float(r['Cuota']), gana=r['Pronóstico'].startswith('Gana ')))
    best = None
    for only_win in (True, False):
        pool = [c for c in cands if c['gana']] if only_win else cands
        for a, b in combinations(pool, 2):
            tot = a['cuota'] * b['cuota']
            if a['Liga'] == b['Liga'] or not (MIN_TOTAL <= tot <= MAX_TOTAL):
                continue
            if not only_win and not (a['gana'] or b['gana']):
                continue  # al menos una pata "a ganar"
            score = (a['rate'] * b['rate'], min(a['n'], b['n']))
            if not best or score > best[0]:
                best = (score, [a, b], tot)
        if best:
            break
    return best


def f2(v):
    return f'{v:.2f}'.replace('.', ',')


def message(best):
    (_, legs, tot) = best
    out = ['🎯 <b>PICK DEL DÍA · A. Analytics</b>',
           f"📅 {datetime.strptime(legs[0]['Fecha'], '%Y-%m-%d'):%d/%m/%Y}", '']
    for i, l in enumerate(sorted(legs, key=lambda x: x['Hora']), 1):
        out += [f"{i}️⃣ <b>{l['Local']} vs {l['Visitante']}</b>",
                f"🏆 {l['Liga']} · ⏰ {l['Hora']}",
                f"✅ <b>{l['Pronóstico']}</b> · cuota {f2(l['cuota'])}",
                f"📊 Esta liga acierta el {l['rate'] * 100:.0f}% en el registro ({l['n']} partidos)", '']
    prob = legs[0]['rate'] * legs[1]['rate']
    out += [f"💰 <b>Cuota combinada: {f2(tot)}</b>",
            f"📈 Probabilidad estimada: {prob * 100:.0f}%",
            '💶 Stake 10 € · revisa la cuota en tu casa de apuestas antes de entrar',
            '🤖 Pick automático según el acierto por liga del registro APP',
            '+18 · Apuesta con responsabilidad']
    if min(l['rate'] for l in legs) < 0.8:
        out.insert(3, '⚠️ Una de las ligas está por debajo del 80 %: pick con menos garantías\n')
    return '\n'.join(out)


def send():
    rs = rows()
    best = build(rs)
    cid = chat_id()
    if not TOKEN or not cid:
        sys.exit('Falta TELEGRAM_TOKEN o chat_id')
    today = datetime.now(TZ).strftime('%Y-%m-%d')
    try:
        state = json.load(open(STATE))
    except Exception:
        state = {}
    if state.get('fecha') == today:
        print('El pick de hoy ya se envió')
        return
    if not best:
        tg('sendMessage', chat_id=cid, parse_mode='HTML',
           text='🎯 <b>Pick del día</b>\n\nHoy no hay 2 partidos de ligas fiables que lleguen a cuota 1,80. '
                'Mejor no forzar: hoy sin pick. 🧘')
        state = {'fecha': today, 'legs': [], 'avisado': True}
    else:
        msg = message(best)
        sent = False
        try:
            import aa_image
            legs = sorted(best[1], key=lambda x: x['Hora'])
            png = aa_image.make_pick_image(
                [(l['Local'], l['Visitante'], l['Liga'], l['Hora'], l['Pronóstico'], l['cuota']) for l in legs], best[2])
            sent = aa_image.send_photo(TOKEN, cid, png, msg).get('ok')
        except Exception as ex:
            print('Imagen no enviada:', ex)
        if not sent:
            tg('sendMessage', chat_id=cid, text=msg, parse_mode='HTML')
        state = {'fecha': today, 'cuota': round(best[2], 2), 'avisado': False,
                 'legs': [{k: l[k] for k in ('Fecha', 'Local', 'Visitante', 'Liga', 'Pronóstico', 'Cuota')}
                          for l in best[1]]}
        print(msg)
    json.dump(state, open(STATE, 'w'), ensure_ascii=False, indent=1)


def check():
    try:
        state = json.load(open(STATE))
    except Exception:
        return
    if state.get('avisado') or not state.get('legs'):
        return
    idx = {(r['Fecha'], r['Local'], r['Visitante']): r for r in rows()}
    res = [idx.get((l['Fecha'], l['Local'], l['Visitante'])) for l in state['legs']]
    if any(r and r['Acierto'] == 'Fallado' for r in res):
        estado = 'perdida'
    elif all(r and r['Acierto'] == 'Acertado' for r in res):
        estado = 'ganada'
    else:
        return
    cid = chat_id()
    lines = [f"{'✅' if r['Acierto'] == 'Acertado' else '❌' if r['Acierto'] == 'Fallado' else '⏳'} "
             f"{r['Local']} {r['Resultado'] or ''} {r['Visitante']} · {r['Pronóstico']}" for r in res if r]
    head = '✅ <b>PICK DEL DÍA GANADO</b>' if estado == 'ganada' else '❌ <b>Pick del día perdido</b>'
    benef = f"+{10 * (state['cuota'] - 1):.2f} €".replace('.', ',') if estado == 'ganada' else '−10,00 €'
    tg('sendMessage', chat_id=cid, parse_mode='HTML',
       text=f"{head}\n\n" + '\n'.join(lines) + f"\n\n💰 Cuota {f2(state['cuota'])} · {benef} (stake 10 €)")
    state['avisado'], state['estado'] = True, estado
    json.dump(state, open(STATE, 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'preview'
    if mode == 'send':
        send()
    elif mode == 'check':
        check()
    else:
        when = datetime.now(TZ)
        if len(sys.argv) > 2:  # preview AAAA-MM-DD [HH:MM]
            when = datetime.strptime(' '.join(sys.argv[2:4]) if len(sys.argv) > 3 else sys.argv[2] + ' 09:00',
                                     '%Y-%m-%d %H:%M').replace(tzinfo=TZ)
        b = build(rows(), when)
        print(message(b) if b else 'Sin pick')
