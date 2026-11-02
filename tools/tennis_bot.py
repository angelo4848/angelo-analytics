#!/usr/bin/env python3
"""A. Analytics – bot de alertas de TENIS en vivo (datos de SofaScore, corre en tu PC).

Filtros (solo ATP y WTA, sin dobles, sin ITF/UTR):
  1) FAVORITO GANA EL 1.er SET: al empezar el partido (1.er set, máx. 2 juegos jugados)
     si el favorito pagaba ≤ 1,35 antes del partido. Si su cuota de partido está entre
     1,40 y 1,90 también te sugiere la victoria del partido.
  2) FAVORITO EN VIVO: el favorito (≤ 1,50 antes del partido) PERDIÓ el 1.er set, va al
     principio del 2.º (máx. 2 juegos) y sus estadísticas de saque son mejores que las del
     rival -> "Favorito gana el 2.º set" si la cuota del set es ≥ 1,40.

Usa el mismo bot_config.txt (token) que el bot de fútbol. Guarda su memoria en
tennis_state.json. Respondiendo a una alerta con una cuota (ej. 1.62) te devuelve la
imagen con esa cuota (lo gestiona el bot de fútbol si está abierto; si no, este).
"""
import json, os, re, sys, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pc_bot as base            # reutiliza conexión a SofaScore, Telegram y config
try:
    import aa_image
except Exception:
    aa_image = None

STATE = os.path.join(HERE, 'tennis_state.json')
OK_CATS = {'ATP', 'WTA'}
INCLUDE_CHALLENGER = False      # pon True si quieres también Challenger / WTA 125
if INCLUDE_CHALLENGER:
    OK_CATS |= {'Challenger', 'WTA 125'}


def load():
    try:
        return json.load(open(STATE))
    except Exception:
        return {'sent': {}}


def save(s):
    cut = time.time() - 3 * 86400
    s['sent'] = {k: v for k, v in s['sent'].items() if v > cut}
    json.dump(s, open(STATE, 'w'))


def frac(v):
    return base.frac(v)


def odds(eid):
    d = base.sget(f'/event/{eid}/odds/1/all') or {}
    res = {}
    for m in d.get('markets', []):
        name, live = m.get('marketName'), m.get('isLive')
        ch = {c['name']: (frac(c.get('fractionalValue')), frac(c.get('initialFractionalValue')))
              for c in m.get('choices', [])}
        if name == 'Full time' and not live:
            res['pre'] = {k: v[1] or v[0] for k, v in ch.items()}
        elif name == 'Full time' and live:
            res['live'] = {k: v[0] for k, v in ch.items()}
        elif name in ('Current set winner', 'First set winner') and live:
            res['set'] = {k: v[0] for k, v in ch.items()}
    return res


def pct(v):
    """'27/37 (73%)' -> 73.0"""
    m = re.search(r'\((\d+)%\)', str(v or ''))
    return float(m.group(1)) if m else None


def stats(eid):
    d = base.sget(f'/event/{eid}/statistics') or {}
    out = {}
    for p in d.get('statistics', []):
        if p.get('period') != 'ALL':
            continue
        for g in p.get('groups', []):
            for i in g.get('statisticsItems', []):
                out.setdefault(i['key'], (i.get('home'), i.get('away')))
    return out


def link(e):
    return f"https://www.sofascore.com/pt/tennis/match/{e.get('slug','')}/{e.get('customId','')}#id:{e['id']}"


def score_txt(e):
    h, a = e.get('homeScore', {}), e.get('awayScore', {})
    sets = []
    for k in ('period1', 'period2', 'period3', 'period4', 'period5'):
        if k in h and k in a:
            sets.append(f"{h[k]}-{a[k]}")
    return ' · '.join(sets) or '0-0'


def message(kind, e, fav, rk, pre, live, setodd, st, extra=''):
    h, a = e['homeTeam'], e['awayTeam']
    favn = (h if fav == 0 else a)['name']
    t = e['tournament']['name']
    cat = (e['tournament'].get('category') or {}).get('name', '')
    surf = e.get('groundType') or ''
    title = '🎾 <b>FAVORITO GANA EL 1.er SET</b>' if kind == 'set1' else '🎾 <b>FAVORITO EN VIVO · 2.º SET</b>'
    mercado = f"Gana el 1.er set {favn}" if kind == 'set1' else f"Gana el 2.º set {favn}"
    sline = ''
    if st:
        fs = st.get('firstServePointsAccuracy', (None, None))
        sw = st.get('servicePointsScored', (None, None))
        sline = (f"\n📊 Puntos ganados con 1.er saque: {(pct(fs[0]) or 0):.0f}% - {(pct(fs[1]) or 0):.0f}%"
                 f"\n🎯 Puntos ganados al saque: {sw[0] or '–'} - {sw[1] or '–'}")
    oddl = f" · cuota ≈ {setodd:.2f}" if setodd else ''
    return (f"{title}\n\n🎾 <b>{h['name']} – {a['name']}</b>\n🏆 {cat} · {t}{(' · ' + surf) if surf else ''}\n"
            f"⏱️ Marcador: {score_txt(e)}\n\n"
            f"📈 Ranking: {rk[0] or '–'} vs {rk[1] or '–'}\n"
            f"💰 Antes del partido {favn} pagaba <b>{pre:.2f}</b>" + (f"; ahora paga <b>{live:.2f}</b>" if live else '') +
            f"{sline}{extra}\n\n✅ <b>{mercado}</b>{oddl}\n💶 Stake 10 € · revisa la cuota en BetLabel\n"
            f"🔗 <a href=\"{link(e)}\">Ver en SofaScore</a>"), mercado


def deliver(cid, e, msg, mercado, cuota):
    if aa_image:
        try:
            png = aa_image.make_live_image(
                f"{(e['tournament'].get('category') or {}).get('name','')} · {e['tournament']['name']}",
                (e.get('status') or {}).get('description', '').replace('1st set', '1.er set').replace('2nd set', '2.º set'),
                score_txt(e), e['homeTeam']['name'], e['awayTeam']['name'], mercado, cuota)
            # el texto lleva "⚽ A – B" para que la respuesta con cuota funcione en el bot de fútbol
            cap = msg.replace(f"🎾 <b>{e['homeTeam']['name']} – {e['awayTeam']['name']}</b>",
                              f"⚽ <b>{e['homeTeam']['name']} – {e['awayTeam']['name']}</b>", 1)
            if aa_image.send_photo(base.CFG['TELEGRAM_TOKEN'], cid, png, cap).get('ok'):
                return
        except Exception as ex:
            print('Imagen no enviada:', ex)
    base.send(cid, msg)


def games(e, period):
    return (e.get('homeScore', {}).get(period) or 0) + (e.get('awayScore', {}).get(period) or 0)


def scan(state, cid):
    data = base.sget('/sport/tennis/events/live')
    if not data:
        print(datetime.now().strftime('%H:%M'), 'SofaScore no responde')
        return
    for e in data.get('events', []):
        cat = (e.get('tournament', {}).get('category') or {}).get('name', '')
        tname = e.get('tournament', {}).get('name', '')
        if cat not in OK_CATS or re.search(r'doubles|dobles|mixed', tname, re.I):
            continue
        if (e['homeTeam'].get('type') or 1) != 1 or '/' in e['homeTeam'].get('name', ''):
            continue  # dobles
        status = (e.get('status') or {}).get('description', '')
        kind = None
        if status == '1st set' and games(e, 'period1') <= 2:
            kind = 'set1'
        elif status == '2nd set' and games(e, 'period2') <= 2:
            kind = 'set2'
        if not kind:
            continue
        key = f"{kind}:{e['id']}"
        if key in state['sent']:
            continue
        od = odds(e['id'])
        pre, live, sset = od.get('pre') or {}, od.get('live') or {}, od.get('set') or {}
        if not pre:
            continue
        fav = 0 if (pre.get('1') or 99) < (pre.get('2') or 99) else 1
        k = '1' if fav == 0 else '2'
        p = pre.get(k)
        rk = (e['homeTeam'].get('ranking'), e['awayTeam'].get('ranking'))
        msg = None
        if kind == 'set1' and p and p <= 1.35:
            extra = ''
            if live.get(k) and 1.40 <= live[k] <= 1.90:
                extra = f"\n➕ Victoria del partido también con valor: ≈ {live[k]:.2f}"
            msg, mercado = message('set1', e, fav, rk, p, live.get(k), sset.get(k), None, extra)
        elif kind == 'set2' and p and p <= 1.50:
            h1, a1 = e['homeScore'].get('period1', 0), e['awayScore'].get('period1', 0)
            lost_first = (h1 < a1) if fav == 0 else (a1 < h1)
            if not lost_first:
                state['sent'][key] = time.time()
                continue
            st = stats(e['id'])
            fs = st.get('firstServePointsAccuracy', (None, None))
            mine, theirs = pct(fs[fav]), pct(fs[1 - fav])
            if mine is None or theirs is None or mine < theirs:
                continue  # el favorito no está sacando mejor
            if sset.get(k) and sset[k] < 1.40:
                continue
            msg, mercado = message('set2', e, fav, rk, p, live.get(k), sset.get(k), st)
        if msg:
            deliver(cid, e, msg, mercado, sset.get(k))
            state['sent'][key] = time.time()
            print(datetime.now().strftime('%H:%M'), 'ENVIADO', kind, e['homeTeam']['name'], '-', e['awayTeam']['name'])
        time.sleep(0.4)


def main():
    if not base.CFG.get('TELEGRAM_TOKEN'):
        sys.exit('Falta TELEGRAM_TOKEN en bot_config.txt')
    state = load()
    bstate = base.load_state()
    cid = base.get_chat(bstate)
    if not cid:
        sys.exit('Escribe "hola" a tu bot en Telegram y vuelve a abrir el programa.')
    if base.sget('/sport/tennis/events/live') is None:
        print('SofaScore no responde en este PC (en un VPS suele estar bloqueado). El bot de tenis necesita SofaScore.')
    base.send(cid, '🎾 <b>Bot de TENIS activado</b>\nVigilo ATP y WTA: favorito gana el 1.er set y favorito en vivo '
                   '(gana el 2.º set tras perder el 1.º).')
    print('Bot de TENIS en marcha. Deja esta ventana abierta. (Ctrl+C para parar)')
    while True:
        try:
            scan(state, cid)
            save(state)
        except Exception as ex:
            print('Error:', ex)
        time.sleep(60)


if __name__ == '__main__':
    main()
