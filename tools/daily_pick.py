#!/usr/bin/env python3
"""Pick del día automático para el bot de Telegram (corre en GitHub Actions, sin Claude).

  python3 tools/daily_pick.py send    -> arma el pick de hoy desde app.csv y lo manda al bot
  python3 tools/daily_pick.py check   -> si el pick ya terminó, manda el resultado (una vez)
  python3 tools/daily_pick.py preview -> muestra el pick en pantalla sin mandarlo

AHORA usa el modelo BC (tools/bc_model.py, copiado de Bet Consulting): 2 favoritos claros de ligas grandes,
cuota total 1,70-1,95, la combinación de mayor probabilidad. build() de abajo es el método antiguo (ya no se usa).

Reglas antiguas:
  · partidos de HOY de ligas distintas que empiecen dentro de ≥ 45 min
  · "Gana X" o doble oportunidad, lo que sea más seguro según el % de acierto del registro
    (por liga y tipo de pronóstico; mín. 5 partidos)
  · cuota combinada entre 1,80 y 2,10 · 2 partidos (3 solo si con 2 no se llega)
  · se elige la combinación con mayor probabilidad conjunta
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
MIN_N, MIN_TOTAL, MAX_TOTAL = 5, 1.80, 2.10
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


def kind(r):
    return 'gana' if r['Pronóstico'].startswith('Gana ') else 'doble'


def league_stats(rs):
    """Acierto por liga y por liga+tipo (gana / doble oportunidad)."""
    st = {}
    for r in rs:
        if r['Ganado (1/0)'] in ('0', '1'):
            for k in (r['Liga'], (r['Liga'], kind(r))):
                n, g = st.get(k, (0, 0))
                st[k] = (n + 1, g + int(r['Ganado (1/0)']))
    return {k: (n, g / n) for k, (n, g) in st.items() if n >= MIN_N}


def build(rs, now=None):
    """La combinación MÁS SEGURA (mayor probabilidad conjunta) con cuota total entre 1,80 y el máximo.
    Vale "Gana X" o doble oportunidad. 2 partidos; 3 solo si con 2 no se llega a 1,80."""
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
        # si hay datos suficientes de ese tipo de pronóstico en la liga, se usa ese %; si no, el de la liga
        n, rate = stats.get((r['Liga'], kind(r))) or stats[r['Liga']]
        cands.append(dict(r, n=n, rate=rate, cuota=float(r['Cuota'])))
    best = None
    for size in (2, 3):
        for legs in combinations(cands, size):
            if len({l['Liga'] for l in legs}) < size:
                continue
            tot, prob = 1.0, 1.0
            for l in legs:
                tot *= l['cuota']
                prob *= l['rate']
            if not (MIN_TOTAL <= tot <= MAX_TOTAL):
                continue
            score = (prob, min(l['n'] for l in legs))
            if not best or score > best[0]:
                best = (score, list(legs), tot)
        if best:
            break
    return best


BC_MIN, BC_MAX = 1.70, 1.95   # cuota total de la combinada (como Bet Consulting: 2 patas, ~1,70-1,90)


def es_market(m):
    """Mercado del modelo BC (portugués) -> texto de la app (lo entiende picks.py)."""
    import re
    m2 = re.match(r'(.+) vence e ([+-])(\d),5 golos$', m)
    if m2:
        return f"Victoria {m2.group(1)} + {'más' if m2.group(2) == '+' else 'menos'} de {m2.group(3)},5 goles"
    m2 = re.match(r'(.+)/empate e \+(\d),5 golos$', m)
    if m2:
        return f"{m2.group(1)} o empate + más de {m2.group(2)},5 goles"
    if m.endswith(' ou empate'):
        return m[:-len(' ou empate')] + ' o empate'
    if m == '+2,5 golos':
        return 'Más de 2,5 goles'
    if m == 'Ambas marcam':
        return 'Ambos marcan'
    return m


def build_bc(now=None):
    """Combinada del día con el modelo Bet Consulting: 2 patas de partidos distintos, cuota 1,70-1,95,
    la de mayor probabilidad conjunta. Solo partidos que empiezan dentro de ≥ 45 min."""
    import bc_model
    now = now or datetime.now(TZ)
    today = now.strftime('%Y-%m-%d')
    cands = []
    for v in bc_model.picks(now.date()):
        try:
            start = datetime.strptime(f"{today} {v['Hora']}", '%Y-%m-%d %H:%M').replace(tzinfo=TZ)
        except ValueError:
            continue
        if start < now + timedelta(minutes=45):
            continue
        cands.append({'Fecha': today, 'Hora': v['Hora'], 'Liga': v['Liga'], 'Local': v['LocalN'],
                      'Visitante': v['VisitanteN'], 'Pronóstico': es_market(v['Mercado']),
                      'Cuota': f"{v['casa']:.2f}", 'cuota': round(v['casa'], 2), 'rate': v['p'], 'n': 0, 'bc': True})
    best = None
    for legs in combinations(cands, 2):
        tot = legs[0]['cuota'] * legs[1]['cuota']
        if not (BC_MIN <= tot <= BC_MAX):
            continue
        prob = legs[0]['rate'] * legs[1]['rate']
        if not best or prob > best[0][0]:
            best = ((prob, 0), list(legs), tot)
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
                (f"📊 Probabilidad estimada: {l['rate'] * 100:.0f}%" if l.get('bc') else
                 f"📊 Acierto en esta liga ({'a ganar' if kind(l) == 'gana' else 'doble oportunidad'}): "
                 f"{l['rate'] * 100:.0f}% ({l['n']} partidos)"), '']
    prob = 1.0
    for l in legs:
        prob *= l['rate']
    out += [f"💰 <b>Cuota combinada: {f2(tot)}</b>",
            f"📈 Probabilidad estimada: {prob * 100:.0f}%",
            '💶 Stake 10 € · revisa la cuota en tu casa de apuestas antes de entrar',
            ('🤖 Pick automático · modelo BC (favoritos claros de ligas grandes)' if legs[0].get('bc')
             else '🤖 Pick automático según el acierto por liga del registro APP'),
            '+18 · Apuesta con responsabilidad']
    if not legs[0].get('bc') and min(l['rate'] for l in legs) < 0.8:
        out.insert(3, '⚠️ Una de las ligas está por debajo del 80 %: pick con menos garantías\n')
    return '\n'.join(out)


DATA = os.path.join(ROOT, 'data.json')


def to_app(legs, tot):
    """Publica el pick en la app (data.json -> picks) si ese día aún no tiene uno."""
    d = json.load(open(DATA, encoding='utf-8'))
    fecha = legs[0]['Fecha']
    if any(p['fecha'] == fecha for p in d.get('picks', [])):
        return False
    patas = []
    for l in sorted(legs, key=lambda x: x['Hora']):
        pron = l['Pronóstico']
        mercado = 'Victoria ' + pron[5:] if pron.startswith('Gana ') else pron
        tipo = 'a ganar' if kind(l) == 'gana' else 'doble oportunidad'
        if l.get('bc'):
            mercado = pron
            analisis = [f"Favorito claro de liga grande · probabilidad estimada {l['rate'] * 100:.0f}%",
                        f"Cuota aproximada {f2(float(l['Cuota']))} · revisa la cuota en tu casa",
                        'Elegido por el pick automático: la combinación más segura del día']
        else:
            analisis = [f"En esta liga nuestro modelo acierta el {l['rate'] * 100:.0f}% ({tipo}, {l['n']} partidos)",
                        f"Pronóstico ★★★ del modelo · cuota {f2(float(l['Cuota']))}",
                        'Elegido por el pick automático: la combinación más segura del día']
        patas.append({'liga': l['Liga'], 'hora': l['Hora'], 'partido': f"{l['Local']} vs {l['Visitante']}",
                      'mercado': mercado, 'cuota': round(float(l['Cuota']), 2), 'estado': 'pendiente',
                      'analisis': analisis})
    d['picks'].append({'fecha': fecha, 'titulo': 'Combinada del día', 'estado': 'pendiente',
                       'cuota_total': round(tot, 2), 'patas': patas})
    json.dump(d, open(DATA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return True


def send():
    best = build_bc()   # modelo BC (Bet Consulting)
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
           text='🎯 <b>Pick del día</b>\n\nHoy no hay 2 favoritos claros de ligas grandes que lleguen a cuota 1,70. '
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
        print('Publicado en la app:', to_app(best[1], best[2]))
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
    # el pick publicado en la app (marcado por picks.py con ESPN) manda si ya está resuelto
    app = next((p for p in json.load(open(DATA, encoding='utf-8')).get('picks', [])
                if p['fecha'] == state['fecha']), None)
    if app and app.get('estado') in ('ganada', 'perdida'):
        estado = app['estado']
        res = [{'Acierto': 'Acertado' if l.get('estado') == 'ganada' else 'Fallado' if l.get('estado') == 'perdida' else '',
                'Local': l['partido'].split(' vs ')[0], 'Visitante': l['partido'].split(' vs ')[-1],
                'Resultado': l.get('resultado', ''), 'Pronóstico': l['mercado']} for l in app['patas']]
    elif any(r and r['Acierto'] == 'Fallado' for r in res):
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
        b = build_bc(when)
        print(message(b) if b else 'Sin pick')
