#!/usr/bin/env python3
"""A. Analytics – bot de alertas en vivo que corre en TU PC (datos de SofaScore).

Complementa al bot de GitHub (ESPN) con:
  1) FILTRO 2 (−0,5 goles 1.ª parte) en todas las ligas de pocos goles
     (incluidas Egipto, Marruecos, Irán, Etiopía, Portugal 2, J2, China…),
     usando también xG y la cuota en vivo.
  2) FAVORITO EN VIVO: equipo muy favorito antes del partido (cuota ≤ 1,70)
     que va empatando y domina, con cuota en vivo ≥ 1,85 (caso Machida).

Uso:  python pc_bot.py          (deja la ventana abierta; revisa cada minuto)
Config: crea "bot_config.txt" junto a este archivo con:
    TELEGRAM_TOKEN=tu_token
    TELEGRAM_CHAT_ID=        (opcional; se detecta solo si escribes "hola" al bot)
"""
import json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:  # usa los certificados de Windows (antivirus/proxy que inspeccionan HTTPS)
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass
try:
    import aa_image
except Exception:  # Pillow no instalado
    aa_image = None
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, 'pc_bot_state.json')

# ---------- HTTP (SofaScore necesita parecer un navegador) ----------
def _urllib_get(path):
    req = urllib.request.Request('https://www.sofascore.com/api/v1' + path, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36',
        'Accept': 'application/json', 'Referer': 'https://www.sofascore.com/'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as ex:
        if ex.code != 404:
            print('  SofaScore HTTP', ex.code, '(bloqueo: hace falta curl_cffi / Python 64 bits)')
        return None
    except Exception as ex:
        print('  SofaScore error:', str(ex)[:120])
        return None

def _windows_ca_bundle():
    """Exporta los certificados raíz de Windows a un .pem (para antivirus que inspeccionan HTTPS)."""
    if os.name != 'nt':
        return True
    import ssl
    path = os.path.join(HERE, 'ca_windows.pem')
    try:
        pems = []
        for store in ('ROOT', 'CA'):
            for cert, enc, trust in ssl.enum_certificates(store):
                if enc == 'x509_asn':
                    pems.append(ssl.DER_cert_to_PEM_cert(cert))
        try:
            import certifi
            pems.append(open(certifi.where(), encoding='utf-8').read())
        except Exception:
            pass
        open(path, 'w', encoding='utf-8').write('\n'.join(pems))
        return path
    except Exception:
        return True

try:
    from curl_cffi import requests as cr
    SESSION = cr.Session(impersonate='chrome', verify=_windows_ca_bundle())
    def sget(path):
        try:
            r = SESSION.get('https://www.sofascore.com/api/v1' + path, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
        except Exception:
            pass
        return _urllib_get(path)  # p. ej. si un antivirus bloquea el certificado
except ImportError:
    sget = _urllib_get

# ---------- Config ----------
def load_config():
    cfg = {}
    p = os.path.join(HERE, 'bot_config.txt')
    if os.path.exists(p):
        for line in open(p, encoding='utf-8'):
            if '=' in line and not line.strip().startswith('#'):
                k, v = line.split('=', 1)
                cfg[k.strip()] = v.strip()
    for k in ('TELEGRAM_TOKEN', 'TELEGRAM_CHAT_ID'):
        cfg[k] = os.environ.get(k) or cfg.get(k, '')
    return cfg

CFG = load_config()
API = f"https://api.telegram.org/bot{CFG['TELEGRAM_TOKEN']}/"

def tg(method, **params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(API + method, data=data, timeout=30) as r:
        return json.load(r)

def send(cid, text):
    tg('sendMessage', chat_id=cid, text=text, parse_mode='HTML', disable_web_page_preview='true')

def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {'sent': {}, 'chat_id': None}

def save_state(s):
    cut = time.time() - 3 * 86400
    s['sent'] = {k: v for k, v in s['sent'].items() if v > cut}
    json.dump(s, open(STATE, 'w'))

def get_chat(state):
    cid = CFG.get('TELEGRAM_CHAT_ID') or state.get('chat_id')
    if cid:
        return cid
    for u in reversed(tg('getUpdates').get('result', [])):
        m = u.get('message') or {}
        if m.get('chat', {}).get('type') == 'private':
            state['chat_id'] = str(m['chat']['id'])
            return state['chat_id']
    return None

# ---------- Ligas ----------
# Ligas de pocos goles (máx. 2 tiros a puerta y xG ≤ 0,5)
LOW_SOFA = {155: 'Liga Profesional 🇦🇷', 703: 'Primera Nacional 🇦🇷', 1347: 'Primera B Metro 🇦🇷',
            390: 'Brasileirão Série B 🇧🇷', 1281: 'Brasileirão Série C 🇧🇷', 406: 'Liga 1 🇵🇪',
            278: 'Liga AUF 🇺🇾', 231: 'Liga FUTVE 🇻🇪', 11536: 'Primera A 🇨🇴', 11539: 'Primera A 🇨🇴',
            240: 'LigaPro 🇪🇨', 182: 'Ligue 2 🇫🇷', 54: 'LaLiga 2 🇪🇸', 53: 'Serie B 🇮🇹',
            238: 'Liga Portugal 🇵🇹', 239: 'Liga Portugal 2 🇵🇹', 203: 'Liga rusa 🇷🇺',
            185: 'Super League 🇬🇷', 152: 'SuperLiga 🇷🇴', 358: 'Premiership 🇿🇦',
            11611: 'Liga de Expansión 🇲🇽', 11612: 'Liga de Expansión 🇲🇽',
            808: 'Liga de Egipto 🇪🇬', 937: 'Botola Pro 🇲🇦', 10554: 'Botola Pro 2 🇲🇦',
            915: 'Persian Gulf Pro League 🇮🇷', 16601: 'Liga de Etiopía 🇪🇹', 402: 'J2 League 🇯🇵',
            777: 'K League 2 🇰🇷', 183: 'Ligue 3 🇫🇷'}
# Ligas medias (más estricto: máx. 1 tiro a puerta y máx. 8 tiros)
MED_SOFA = {11653: 'Liga de Primera 🇨🇱', 11541: 'Primera División 🇵🇾', 11540: 'Primera División 🇵🇾',
            18: 'Championship 🏴', 8: 'LaLiga 🇪🇸', 23: 'Serie A 🇮🇹', 34: 'Ligue 1 🇫🇷',
            52: 'Süper Lig 🇹🇷', 17: 'Premier League 🏴', 11621: 'Liga MX 🇲🇽', 11620: 'Liga MX 🇲🇽',
            24: 'League One 🏴', 196: 'J1 League 🇯🇵', 410: 'K League 1 🇰🇷'}
# Ligas serias para "favorito en vivo" (además de LOW_SOFA y MED_SOFA)
FAV_EXTRA = {35, 44, 37, 131, 38, 36, 45, 215, 39, 20, 40, 325, 242, 955, 649, 218, 172, 202, 170,
             210, 136, 266, 187, 211, 41, 345, 46, 219, 325, 1, 7, 679, 17015, 384, 480}
LOW_NAME = re.compile(r'China League (One|Two|1|2)|CFA (?!Women)|Second League', re.I)
EXCLUDE = re.compile(r'women|femen|\(W\)|\bU-?1\d|\bU-?2[0-3]|reserve|youth|amateur|friendly|'
                     r'esports|\bII\b|\bB$', re.I)

def frac(v):
    try:
        a, b = v.split('/')
        return round(1 + int(a) / int(b), 2)
    except Exception:
        return None

def stats(eid):
    d = sget(f'/event/{eid}/statistics') or {}
    out = {}
    for p in d.get('statistics', []):
        if p.get('period') != 'ALL':
            continue
        for g in p.get('groups', []):
            for i in g.get('statisticsItems', []):
                out[i['key']] = (i.get('homeValue'), i.get('awayValue'))
    return out

def odds(eid):
    d = sget(f'/event/{eid}/odds/1/all') or {}
    res = {}
    for m in d.get('markets', []):
        name, live = m.get('marketName'), m.get('isLive')
        ch = {c['name']: (frac(c.get('fractionalValue')), frac(c.get('initialFractionalValue')))
              for c in m.get('choices', [])}
        if name == 'Full time' and not live:
            res['pre'] = {k: v[1] or v[0] for k, v in ch.items()}
        elif name == 'Full time' and live:
            res['live'] = {k: v[0] for k, v in ch.items()}
        elif name == '1st half' and live:
            res['ht'] = {k: v[0] for k, v in ch.items()}
        elif name == 'Double chance' and live:
            res['dc'] = {k: v[0] for k, v in ch.items()}
    if 'pre' not in res and 'live' in res:  # sin mercado previo: usa la cuota inicial
        for m in d.get('markets', []):
            if m.get('marketName') == 'Full time':
                res['pre'] = {c['name']: frac(c.get('initialFractionalValue')) for c in m['choices']}
                break
    return res

def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0

def link(e):
    return f"https://www.sofascore.com/pt/football/match/{e.get('slug','')}/{e.get('customId','')}#id:{e['id']}"

# ---------- Alertas ----------
def filtro2(e, mn, st, od, liga, strict=False):
    sot = [num(x) for x in st.get('shotsOnGoal', (0, 0))]
    xg = [num(x) for x in st.get('expectedGoals', (0, 0))]
    sh = [num(x) for x in st.get('totalShotsOnGoal', (0, 0))]
    co = [num(x) for x in st.get('cornerKicks', (0, 0))]
    if sum(sot) > (1 if strict else 2) or ('expectedGoals' in st and sum(xg) > 0.5):
        return None
    if strict and sum(sh) > 8:
        return None
    xht = (od.get('ht') or {}).get('X')
    if xht and xht < 1.30:  # sin valor (el "menos 0,5" pagaría < 1,45)
        return None
    warn = '\n⚠️ Un equipo lleva 5+ córners' if max(co) >= 5 else ''
    xgl = f"\n📈 xG: {xg[0]:.2f}-{xg[1]:.2f}" if 'expectedGoals' in st else ''
    oddl = f"\n💹 Empate al descanso paga {xht:.2f} (el −0,5 suele pagar algo más)" if xht else ''
    return (f"🚨 <b>ALERTA FILTRO 2</b> · 🖥️ PC\n\n⚽ <b>{e['homeTeam']['name']} – {e['awayTeam']['name']}</b>\n"
            f"🏆 {liga}\n⏱️ Minuto {mn} · 0-0\n\n🎯 Tiros a puerta: {sot[0]:.0f}-{sot[1]:.0f}\n"
            f"👟 Tiros: {sh[0]:.0f}-{sh[1]:.0f}\n🚩 Córners: {co[0]:.0f}-{co[1]:.0f}{xgl}{oddl}{warn}\n\n"
            f"✅ <b>Menos de 0,5 goles 1.ª parte</b>\n💶 Entra solo si la cuota es ≥ 1,45 · Stake 10 €\n"
            f"🔗 <a href=\"{link(e)}\">Ver en SofaScore</a>")

def favorito(e, mn, st, od, liga):
    pre, live = od.get('pre') or {}, od.get('live') or {}
    hs, as_ = e['homeScore'].get('current', 0), e['awayScore'].get('current', 0)
    if hs != as_ or not pre or not live:
        return None
    for side, idx, key in (('home', 0, '1'), ('away', 1, '2')):
        p, l = pre.get(key), live.get(key)
        if not p or not l or p > 1.70 or l < 1.85:
            continue
        if (e.get(side + 'RedCards') or 0) > 0:
            continue
        sot = [num(x) for x in st.get('shotsOnGoal', (0, 0))]
        xg = [num(x) for x in st.get('expectedGoals', (0, 0))]
        if not st or sot[idx] < sot[1 - idx]:
            continue
        if 'expectedGoals' in st and xg[idx] < xg[1 - idx]:
            continue
        team = e[side + 'Team']['name']
        xgl = f"\n📈 xG: {xg[0]:.2f}-{xg[1]:.2f}" if 'expectedGoals' in st else ''
        xht = (od.get('ht') or {}).get('X')
        oddl = f"\n💹 Empate al descanso paga {xht:.2f} (el −0,5 suele pagar algo más)" if xht else ''
        return (f"⭐ <b>FAVORITO EN VIVO</b> · 🖥️ PC\n\n⚽ <b>{e['homeTeam']['name']} – {e['awayTeam']['name']}</b>\n"
                f"🏆 {liga}\n⏱️ Minuto {mn} · {hs}-{as_}\n\n"
                f"📊 Antes del partido {team} pagaba <b>{p:.2f}</b>; ahora paga <b>{l:.2f}</b>\n"
                f"🎯 Tiros a puerta: {sot[0]:.0f}-{sot[1]:.0f}{xgl}{oddl}\n\n"
                f"✅ <b>Menos de 0,5 goles 1.ª parte</b>\n💶 Entra solo si la cuota es ≥ 1,45 · Stake 10 €\n"
                f"🔗 <a href=\"{link(e)}\">Ver en SofaScore</a>")
    return None

REPLY_HINT = '\n✍️ Responde a esta alerta con la cuota (ej. 1.62) y te mando la imagen con cuota'


def deliver(cid, msg, cuota=None):
    """Envía la alerta con su imagen (si se puede) y el texto como pie de foto."""
    msg += REPLY_HINT
    if aa_image:
        try:
            d = aa_image.parse_alert(re.sub(r'<[^>]+>', '', msg))
            png = aa_image.make_live_image(d['liga'], d['minuto'], d['marcador'], d['local'],
                                           d['visitante'], d['mercado'], cuota)
            if aa_image.send_photo(CFG['TELEGRAM_TOKEN'], cid, png, msg).get('ok'):
                return
        except Exception as ex:
            print('Imagen no enviada:', ex)
    send(cid, msg)


def replies(state, cid):
    """Si respondes a una alerta con una cuota, devuelve la imagen con esa cuota."""
    if not aa_image:
        return
    try:
        ups = tg('getUpdates', offset=state.get('offset', 0), timeout=0).get('result', [])
    except Exception:
        return
    for u in ups:
        state['offset'] = u['update_id'] + 1
        m = u.get('message') or {}
        if str(m.get('chat', {}).get('id')) != str(cid):
            continue
        q = re.match(r'^\s*(\d+[.,]\d+)\s*$', m.get('text') or '')
        rep = m.get('reply_to_message') or {}
        src = rep.get('caption') or rep.get('text') or ''
        if not q or not src:
            continue
        d = aa_image.parse_alert(src)
        if not d:
            continue
        cuota = float(q.group(1).replace(',', '.'))
        png = aa_image.make_live_image(d['liga'], d['minuto'], d['marcador'], d['local'],
                                       d['visitante'], d['mercado'], cuota)
        mercado = d['mercado']
        cap = (f"🔴 <b>PICK EN VIVO</b> 🔴\n\n⚽ <b>{d['local']} vs {d['visitante']}</b> · {d['liga']}\n"
               f"⏱️ Minuto {d['minuto']} · {d['marcador']}\n✅ <b>{mercado}</b> · <b>{str(f'{cuota:.2f}').replace('.', ',')}</b>\n\n"
               f"💰 Stake: 10 €\n📲 Más pronósticos en la app A. Analytics\n+18 · Apuesta con responsabilidad")
        aa_image.send_photo(CFG['TELEGRAM_TOKEN'], cid, png, cap)
        print(datetime.now().strftime('%H:%M'), 'Imagen con cuota', cuota, d['local'])


def scan(state, cid):
    data = sget('/sport/football/events/live')
    if not data:
        print(datetime.now().strftime('%H:%M'), 'SofaScore no responde')
        return
    now = time.time()
    for e in data.get('events', []):
        ut = (e.get('tournament') or {}).get('uniqueTournament') or {}
        tname = (e.get('tournament') or {}).get('name', '')
        if EXCLUDE.search(tname) or EXCLUDE.search(e['homeTeam']['name']) or EXCLUDE.search(e['awayTeam']['name']):
            continue
        start = (e.get('time') or {}).get('currentPeriodStartTimestamp')
        if not start:
            continue
        status = (e.get('status') or {}).get('description', '')
        mn = int((now - start) / 60) + (45 if status == '2nd half' else 0)
        uid = ut.get('id')
        country = ((ut.get('category') or {}).get('name')) or ''
        liga = LOW_SOFA.get(uid) or MED_SOFA.get(uid) or f"{tname} ({country})"
        is_low = uid in LOW_SOFA or bool(LOW_NAME.search(tname))
        is_med = uid in MED_SOFA
        hs, as_ = e['homeScore'].get('current', 0), e['awayScore'].get('current', 0)
        tipo = None
        if status == '1st half' and 25 <= mn <= 34 and hs == 0 and as_ == 0 and (is_low or is_med):
            tipo = 'f2'
        elif status == '1st half' and 15 <= mn <= 40 and hs == 0 and as_ == 0:  # apuesta: −0,5 1.ª parte
            tipo = 'fav'
        else:
            continue
        key = f"{tipo}:{e['id']}"
        if key in state['sent']:
            continue
        if (e.get('homeRedCards') or 0) + (e.get('awayRedCards') or 0) > 0 and tipo == 'f2':
            continue
        od = odds(e['id'])
        if tipo == 'fav' and not od.get('pre'):
            continue
        st = stats(e['id'])
        if not st:  # sin estadísticas → no se entra
            continue
        msg = filtro2(e, mn, st, od, liga, strict=is_med and not is_low) if tipo == 'f2' else favorito(e, mn, st, od, liga)
        if msg:
            cm = re.search(r'cuota ≈ ([\d.]+)', msg)
            deliver(cid, msg, float(cm.group(1)) if cm else None)
            state['sent'][key] = now
            print(datetime.now().strftime('%H:%M'), 'ENVIADO', tipo, e['homeTeam']['name'], '-', e['awayTeam']['name'])
        time.sleep(0.4)

def main():
    if not CFG.get('TELEGRAM_TOKEN'):
        sys.exit('Falta TELEGRAM_TOKEN en bot_config.txt')
    state = load_state()
    cid = get_chat(state)
    if not cid:
        sys.exit('Escribe "hola" a tu bot en Telegram y vuelve a abrir el programa.')
    send(cid, '🖥️ <b>Bot del PC activado</b>\nVigilo SofaScore cada minuto: Filtro 2 en ligas extra '
              'y favoritos en vivo con cuota de valor.')
    if 'offset' not in state:  # ignora mensajes antiguos
        try:
            ups = tg('getUpdates').get('result', [])
            state['offset'] = ups[-1]['update_id'] + 1 if ups else 0
        except Exception:
            state['offset'] = 0
    save_state(state)
    import platform, struct
    print(f"Python {platform.python_version()} {struct.calcsize('P') * 8} bits · Windows {platform.machine()} · "
          f"curl_cffi: {'SI' if 'cr' in globals() else 'NO'} · truststore: {'SI' if 'truststore' in sys.modules else 'NO'}")
    print('Bot del PC en marcha. Deja esta ventana abierta. (Ctrl+C para parar)')
    if sget('/sport/football/events/live') is None:
        espn_mode(state, cid)
        return
    while True:
        try:
            scan(state, cid)
            for _ in range(6):  # entre revisiones, atiende respuestas cada 10 s
                replies(state, cid)
                save_state(state)
                time.sleep(10)
            continue
        except Exception as ex:
            print('Error:', ex)
        time.sleep(60)

def espn_mode(state, cid):
    """Si SofaScore no funciona en este PC (p. ej. Windows de 32 bits), usa ESPN como el bot de GitHub."""
    import live_bot
    live_bot.TOKEN = CFG['TELEGRAM_TOKEN']
    live_bot.API = f"https://api.telegram.org/bot{CFG['TELEGRAM_TOKEN']}/"
    print('SofaScore no disponible en este PC -> MODO ESPN (Filtro 2 en ligas principales)')
    send(cid, '🖥️ <b>Bot del PC en modo ESPN</b>\nSofaScore no funciona en este equipo; vigilo el Filtro 2 '
              'con ESPN cada minuto (ligas principales).')
    sent = state.setdefault('espn_sent', {})
    while True:
        try:
            for p in live_bot.candidates():
                if str(p['id']) in sent:
                    continue
                live_bot.deliver(cid, p)
                sent[str(p['id'])] = time.time()
                print(datetime.now().strftime('%H:%M'), 'ENVIADO (ESPN)', p['local'], '-', p['visit'], p['min'])
            for _ in range(6):
                replies(state, cid)
                save_state(state)
                time.sleep(10)
        except Exception as ex:
            print('Error:', ex)
            time.sleep(60)


if __name__ == '__main__':
    main()
