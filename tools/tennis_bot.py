#!/usr/bin/env python3
"""A. Analytics – bot de TENIS bajo demanda (Linux de casa). Un solo bot, todo por Telegram.

En Telegram tienes dos botones:

  🔍 Scan        Busca partidos que están por empezar o en el 1.er set (como mucho 1-1 en juegos)
                 con un FAVORITO CLARO: ≥ 80 % de ganar el partido en SofaScore Y en TNNS.
                 Cada partido que pasa te llega con el pick "Gana el 1.er set <favorito>" y se
                 apunta solo en el Google Sheet (pestaña "Scan 1.er set").
                 Si no hay nada que valga la pena, te lo dice y no envía nada.

  📊 Resultados  Revisa todos los picks de HOY, mira en SofaScore quién ganó el 1.er set, pone
                 ✅ / ❌ en el Google Sheet y te manda el resumen del día.

Uso (Linux):  ~/aa-venv/bin/python tools/tennis_bot.py      (mira LEEME_tenis_linux.txt)

bot_config.txt (junto a este archivo):
  TELEGRAM_TOKEN=...          token de tu bot
  TELEGRAM_CHAT_ID=           opcional (se detecta solo al escribir "hola")
  SHEET_WEBHOOK=...           URL de la aplicación web del Apps Script (sheet_webhook.gs)
  SHEET_SECRET=...            la misma clave que pongas en el Apps Script
  MIN_PROB=80                 % mínimo de favorito (SofaScore y TNNS)
  TNNS_OBLIGATORIO=1          1 = el partido tiene que pasar también en TNNS; 0 = si TNNS no
                              responde, se envía igual marcado "TNNS sin dato"
  VENTANA_MIN=20              minutos antes del inicio en que un partido cuenta como "por empezar"
"""
import json, os, re, sys, time, urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pc_bot as base            # conexión a SofaScore (curl_cffi), Telegram y bot_config.txt
try:
    import tnns
except Exception as _ex:         # Playwright no instalado
    tnns = None
    print('TNNS desactivado:', _ex)

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo('Europe/Lisbon')
except Exception:
    TZ = timezone.utc

CFG = base.CFG
STATE = os.path.join(HERE, 'tennis_state.json')
PICKS = os.path.join(HERE, 'tennis_scan_picks.json')
MIN_PROB = float(CFG.get('MIN_PROB') or 80) / 100
TNNS_REQ = (CFG.get('TNNS_OBLIGATORIO') or '1').strip() != '0'
VENTANA = int(CFG.get('VENTANA_MIN') or 20)
KB = json.dumps({'keyboard': [[{'text': '🔍 Scan'}, {'text': '📊 Resultados'}]], 'resize_keyboard': True})


# ---------- memoria ----------
def jload(p, default):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return default


def jsave(p, data):
    json.dump(data, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def today():
    return datetime.now(TZ).strftime('%Y-%m-%d')


# ---------- Google Sheet (Apps Script) ----------
def sheet(action, payload):
    url = (CFG.get('SHEET_WEBHOOK') or '').strip()
    if not url:
        return False
    body = json.dumps({'secret': CFG.get('SHEET_SECRET', ''), 'action': action, **payload}).encode()
    req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read().decode() or '{}').get('ok', False)
    except Exception as ex:
        print('  Google Sheet no responde:', str(ex)[:120])
        return False


# ---------- SofaScore ----------
def is_single(e):
    t = e.get('tournament') or {}
    if re.search(r'doubles|dobles|mixed', t.get('name', ''), re.I):
        return False
    h, a = e.get('homeTeam') or {}, e.get('awayTeam') or {}
    return '/' not in h.get('name', '/') and '/' not in a.get('name', '/')


def g(e, side, period):
    return (e.get(f'{side}Score') or {}).get(period) or 0


def momento(e, now_ts):
    """'pre' si está por empezar, 'set1' si va al principio del 1.er set (máx. 1-1), si no None."""
    st = (e.get('status') or {})
    if st.get('type') == 'notstarted':
        start = e.get('startTimestamp') or 0
        return 'pre' if start - now_ts <= VENTANA * 60 and now_ts - start <= 90 * 60 else None
    if st.get('type') == 'inprogress' and st.get('description') == '1st set':
        if g(e, 'home', 'period1') <= 1 and g(e, 'away', 'period1') <= 1:
            return 'set1'
    return None


def odds(eid):
    d = base.sget(f'/event/{eid}/odds/1/all') or {}
    res = {}
    for m in d.get('markets', []):
        name, live = m.get('marketName'), m.get('isLive')
        ch = {c['name']: (base.frac(c.get('fractionalValue')), base.frac(c.get('initialFractionalValue')))
              for c in m.get('choices', [])}
        if name == 'Full time' and not live:
            res['pre'] = {k: v[1] or v[0] for k, v in ch.items()}
        elif name == 'Full time' and live:
            res['live'] = {k: v[0] for k, v in ch.items()}
        elif name in ('First set winner', 'Current set winner'):
            res.setdefault('set', {k: v[0] for k, v in ch.items()})
    return res


def implied(c1, c2):
    """Probabilidad sin margen de la casa: (p1, p2)."""
    if not c1 or not c2:
        return None
    a, b = 1 / c1, 1 / c2
    return a / (a + b), b / (a + b)


def set_from_match(p):
    """Prob. de ganar un set si P(partido a 3 sets) = p:  p = s²(3 − 2s)."""
    lo, hi = 0.5, 1.0
    for _ in range(40):
        s = (lo + hi) / 2
        lo, hi = (s, hi) if s * s * (3 - 2 * s) < p else (lo, s)
    return (lo + hi) / 2


def link(e):
    return f"https://www.sofascore.com/pt/tennis/match/{e.get('slug','')}/{e.get('customId','')}#id:{e['id']}"


def candidates():
    now_ts = time.time()
    seen, out = set(), []
    live = base.sget('/sport/tennis/events/live')
    sched = base.sget(f'/sport/tennis/scheduled-events/{datetime.now(timezone.utc).date().isoformat()}')
    if live is None and sched is None:
        return None
    for src in (live or {}, sched or {}):
        for e in src.get('events', []):
            if e['id'] in seen or not is_single(e):
                continue
            k = momento(e, now_ts)
            if k:
                seen.add(e['id'])
                out.append((k, e))
    return out


# ---------- SCAN ----------
def scan(cid):
    base.send(cid, '🔍 Buscando partidos…')
    if tnns:
        tnns.refresh()                      # una sola carga de TNNS por scan
    cands = candidates()
    if cands is None:
        base.send(cid, '⚠️ SofaScore no responde desde este equipo. Prueba en un minuto.', KB)
        return
    picks = jload(PICKS, [])
    ya = {p['id'] for p in picks if p['fecha'] == today()}
    enviados, sin_tnns, revisados, a_tnns, tnns_no = 0, 0, 0, 0, 0
    for kind, e in cands:
        if e['id'] in ya:
            continue
        od = odds(e['id'])
        time.sleep(0.3)
        pre = od.get('pre') or {}
        pr = implied(pre.get('1'), pre.get('2'))
        if not pr:
            continue
        revisados += 1
        fav = 0 if pr[0] >= pr[1] else 1
        p_sofa = pr[fav]
        if p_sofa < MIN_PROB:
            continue
        h, a = e['homeTeam']['name'], e['awayTeam']['name']
        a_tnns += 1
        p_tnns = tnns.prob(h, a) if tnns else None
        if p_tnns is None:
            sin_tnns += 1
            if TNNS_REQ:
                print('  TNNS sin dato:', h, '-', a)
                continue
        elif p_tnns[fav] < MIN_PROB:
            tnns_no += 1
            continue
        favn, rival = (h, a) if fav == 0 else (a, h)
        k = '1' if fav == 0 else '2'
        cuota_set = (od.get('set') or {}).get(k)
        start = datetime.fromtimestamp(e.get('startTimestamp', 0), TZ)
        t = e['tournament']
        circ = (t.get('category') or {}).get('name', '')
        marcador = 'Por empezar' if kind == 'pre' else f"1.er set {g(e,'home','period1')}-{g(e,'away','period1')}"
        ps1 = set_from_match(p_sofa)
        tn_txt = f"{100 * p_tnns[fav]:.0f}%" if p_tnns else 'sin dato'
        msg = (f"🎾 <b>GANADOR 1.er SET</b>\n\n"
               f"🎾 <b>{h} – {a}</b>\n🏆 {circ} · {t.get('name','')}\n"
               f"🕒 {start:%H:%M} · {marcador}\n\n"
               f"📊 Favorito <b>{favn}</b>\n"
               f"   SofaScore {100 * p_sofa:.0f}% · TNNS {tn_txt}\n"
               f"   Prob. estimada de ganar el 1.er set ≈ {100 * ps1:.0f}%\n\n"
               f"✅ <b>Gana el 1.er set {favn}</b>" + (f" · cuota ≈ {cuota_set:.2f}" if cuota_set else '') +
               f"\n🔗 <a href=\"{link(e)}\">Ver en SofaScore</a>")
        base.send(cid, msg, KB)
        pick = {'id': e['id'], 'fecha': today(), 'hora': f'{start:%H:%M}', 'circuito': circ, 'torneo': t.get('name', ''),
                'favorito': favn, 'rival': rival, 'lado': fav + 1, 'sofa': round(100 * p_sofa),
                'tnns': round(100 * p_tnns[fav]) if p_tnns else '', 'cuota_partido': pre.get(k),
                'cuota_set': cuota_set or '', 'marcador': marcador, 'resultado': ''}
        picks.append(pick)
        ok = sheet('add', {'row': sheet_row(pick)})
        if not ok and CFG.get('SHEET_WEBHOOK'):
            base.send(cid, '⚠️ No se pudo apuntar en el Google Sheet (queda guardado aquí; se reintenta con 📊 Resultados).')
        pick['en_sheet'] = ok
        enviados += 1
        print(datetime.now(TZ).strftime('%H:%M'), 'PICK', favn, 'vs', rival)
    cut = (datetime.now(TZ) - timedelta(days=30)).strftime('%Y-%m-%d')
    jsave(PICKS, [p for p in picks if p['fecha'] >= cut])
    if not enviados:
        pct = f'{100 * MIN_PROB:.0f}%'
        txt = (f'😴 Ahora no hay partidos que valgan la pena.\n\n'
               f'📡 SofaScore: {len(cands)} partidos por empezar o en el 1.er set\n'
               f'💰 Con cuotas: {revisados}\n'
               f'⭐ Favorito ≥ {pct} en SofaScore: {a_tnns}\n'
               f'🎾 TNNS: {a_tnns - sin_tnns - tnns_no} pasan · {tnns_no} no llegan al {pct} · {sin_tnns} sin dato')
        base.send(cid, txt, KB)
    else:
        base.send(cid, f'✅ Scan terminado: {enviados} pick(s) enviados y apuntados.', KB)


def sheet_row(p):
    return {'Id': str(p['id']), 'Fecha': p['fecha'], 'Hora': p['hora'], 'Circuito': p['circuito'], 'Torneo': p['torneo'],
            'Favorito': p['favorito'], 'Rival': p['rival'], 'Prob. SofaScore': f"{p['sofa']}%",
            'Prob. TNNS': f"{p['tnns']}%" if p['tnns'] != '' else 'sin dato',
            'Cuota partido': p['cuota_partido'] or '', 'Cuota 1.er set': p['cuota_set'],
            'Marcador al enviar': p['marcador'], 'Pick': f"Gana el 1.er set {p['favorito']}",
            'Resultado 1.er set': p.get('resultado_set', ''), 'Acierto': p.get('resultado', '')}


# ---------- RESULTADOS ----------
def first_set(eid, lado):
    """('Ganado'|'Perdido'|'Anulado'|'', '6-4') desde el lado del favorito."""
    d = (base.sget(f'/event/{eid}') or {}).get('event')
    if not d:
        return '', ''
    st = (d.get('status') or {}).get('type')
    h, a = d.get('homeScore') or {}, d.get('awayScore') or {}
    if st in ('canceled', 'postponed'):
        return 'Anulado', ''
    if 'period1' not in h or 'period1' not in a:
        return ('Anulado', '') if st == 'finished' else ('', '')
    done = 'period2' in h or st == 'finished'
    g1, g2 = h['period1'], a['period1']
    if not done:
        return '', ''
    if g1 == g2:                            # retirada en mitad del 1.er set
        return 'Anulado', f'{g1}-{g2}'
    mine, theirs = (g1, g2) if lado == 1 else (g2, g1)
    return ('Ganado' if mine > theirs else 'Perdido'), f'{mine}-{theirs}'


def resultados(cid):
    picks = jload(PICKS, [])
    hoy = [p for p in picks if p['fecha'] == today()]
    if not hoy:
        base.send(cid, '📭 Hoy no hay picks del scan todavía.', KB)
        return
    lines, pend = [], 0
    for p in hoy:
        if not p.get('resultado'):
            r, sc = first_set(p['id'], p['lado'])
            time.sleep(0.3)
            if r:
                p['resultado'], p['resultado_set'] = r, sc
                sheet('update', {'id': str(p['id']), 'row': sheet_row(p)})
        if not p.get('en_sheet') and CFG.get('SHEET_WEBHOOK'):
            p['en_sheet'] = sheet('add', {'row': sheet_row(p)})
        icon = {'Ganado': '✅', 'Perdido': '❌', 'Anulado': '↩️'}.get(p.get('resultado'), '⏳')
        if icon == '⏳':
            pend += 1
        lines.append(f"{icon} {p['favorito']} vs {p['rival']} · 1.er set {p.get('resultado_set') or '—'}")
    jsave(PICKS, picks)
    w = sum(p.get('resultado') == 'Ganado' for p in hoy)
    l = sum(p.get('resultado') == 'Perdido' for p in hoy)
    resumen = f"\n\n<b>Hoy: {w} ganados · {l} perdidos</b>" + (f" · {pend} en juego" if pend else '')
    if w + l:
        resumen += f" · acierto {100 * w / (w + l):.0f}%"
    base.send(cid, '📊 <b>Resultados 1.er set</b>\n\n' + '\n'.join(lines) + resumen, KB)


# ---------- Telegram ----------
def main():
    if not CFG.get('TELEGRAM_TOKEN'):
        sys.exit('Falta TELEGRAM_TOKEN en bot_config.txt')
    state = jload(STATE, {})
    cid = CFG.get('TELEGRAM_CHAT_ID') or state.get('chat_id')
    if base.sget('/sport/tennis/events/live') is None:
        print('⚠️ SofaScore no responde desde este equipo.')
    if cid:
        base.send(cid, '🎾 <b>Bot de TENIS listo</b>\nPulsa 🔍 Scan para buscar o 📊 Resultados para cerrar el día.', KB)
    print('Bot de TENIS en marcha (Ctrl+C para parar).')
    while True:
        try:
            ups = base.tg('getUpdates', offset=state.get('offset', 0), timeout=20).get('result', [])
        except Exception as ex:
            print('Telegram:', str(ex)[:100])
            time.sleep(5)
            continue
        for u in ups:
            state['offset'] = u['update_id'] + 1
            m = u.get('message') or {}
            chat = str(m.get('chat', {}).get('id', ''))
            if not chat or m.get('chat', {}).get('type') != 'private':
                continue
            if not cid:
                cid = state['chat_id'] = chat
            if chat != str(cid):
                continue
            txt = (m.get('text') or '').lower()
            try:
                if 'scan' in txt:
                    scan(cid)
                elif 'resultado' in txt:
                    resultados(cid)
                else:
                    base.send(cid, 'Pulsa 🔍 Scan o 📊 Resultados.', KB)
            except Exception as ex:
                print('Error:', ex)
                base.send(cid, f'⚠️ Error: {str(ex)[:150]}', KB)
        jsave(STATE, state)


if __name__ == '__main__':
    main()
