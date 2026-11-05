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
    _SESSIONS = []          # (nombre, sesión) en orden de prueba
    _GOOD = [None]          # la combinación que funcionó
    _DIAG = [False]

    def _sessions():
        if not _SESSIONS:
            win = _windows_ca_bundle()
            for imp in ('chrome', 'chrome124', 'safari17_0', 'edge101'):
                for ver, vname in ((True, 'certs curl'), (win, 'certs Windows')):
                    try:
                        _SESSIONS.append((f'{imp} / {vname}', cr.Session(impersonate=imp, verify=ver)))
                    except Exception:
                        pass
        return _SESSIONS

    def sget(path):
        url = 'https://www.sofascore.com/api/v1' + path
        order = ([_GOOD[0]] if _GOOD[0] else []) + [x for x in _sessions() if x is not _GOOD[0]]
        errs = []
        for item in order:
            name, ses = item
            try:
                r = ses.get(url, timeout=20, headers={'Referer': 'https://www.sofascore.com/',
                                                      'Accept': 'application/json'})
                if r.status_code == 200:
                    if _GOOD[0] is not item:
                        print('  SofaScore OK con', name)
                    _GOOD[0] = item
                    return r.json()
                if r.status_code == 404:
                    return None
                errs.append(f'{name}: HTTP {r.status_code}')
            except Exception as ex:
                errs.append(f'{name}: {str(ex)[:80]}')
            if _GOOD[0]:
                break  # ya sabíamos cuál funciona; no probar todas cada vez
        if not _DIAG[0]:
            _DIAG[0] = True
            print('  curl_cffi no pudo con SofaScore:')
            for e in errs[:8]:
                print('   -', e)
        return _urllib_get(path)
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

def send(cid, text, markup=None, **extra):
    if markup:
        extra['reply_markup'] = markup
    return tg('sendMessage', chat_id=cid, text=text, parse_mode='HTML', disable_web_page_preview='true', **extra)

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
# Ligas de muchos goles (aviso a los 5' y filtro +0,5 goles 1.ª parte) – "Torneo (País)"
HIGH_NAME = re.compile(r'^(Bundesliga|2\. Bundesliga) \((Germany|Alemanha)|^(Eredivisie|Eerste Divisie|Keuken Kampioen Divisie) \('
                       r'|^(Pro League|Challenger Pro League) \((Belgium|Bélgica)|^(Super League|Challenge League) \((Switzerland|Suíça)'
                       r'|^(Bundesliga|2\. Liga) \((Austria|Áustria)|^(Eliteserien|OBOS-ligaen|1\. divisjon) \('
                       r'|^Allsvenskan \(|^Superliga \((Denmark|Dinamarca)|^MLS \(|^USL Championship \(|^A-League Men \('
                       r'|^(Saudi Pro League|Pro League) \((Saudi|Arábia)|^Premiership \((Scotland|Escócia)|^Besta deild'
                       r'|^Stars League \(|^Cymru Premier|^Premier League \((Singapore|Singapura|Hong Kong)', re.I)
LOW_NAME = re.compile(r'China League (One|Two|1|2)|CFA (?!Women)|Second League', re.I)
EXCLUDE = re.compile(r'women|femen|frauen|vrouwen|NWSL|USL Super League|WE League|Liga F\b|\(W\)|\bU-?1\d|\bU-?2[0-3]|reserve|youth|amateur|friendly|'
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

def filtro_over(e, mn, st, od, liga):
    """+0,5 goles 1.ª parte: liga de muchos goles, 0-0 y partido abierto."""
    sot = [num(x) for x in st.get('shotsOnGoal', (0, 0))]
    xg = [num(x) for x in st.get('expectedGoals', (0, 0))]
    sh = [num(x) for x in st.get('totalShotsOnGoal', (0, 0))]
    co = [num(x) for x in st.get('cornerKicks', (0, 0))]
    abierto = (sum(sot) >= 3 and sum(sh) >= 8) or sum(sot) >= 4 or ('expectedGoals' in st and sum(xg) >= 0.9)
    if not abierto:
        return None
    xht = (od.get('ht') or {}).get('X')
    if xht and xht > 2.6:  # el mercado ya ve el gol casi seguro: el +0,5 pagaría muy poco
        return None
    xgl = f"\n📈 xG: {xg[0]:.2f}-{xg[1]:.2f}" if 'expectedGoals' in st else ''
    oddl = f"\n💹 Empate al descanso paga {xht:.2f}" if xht else ''
    return (f"🔥 <b>ALERTA +0,5 GOLES 1.ª PARTE</b> · 🖥️ PC\n\n⚽ <b>{e['homeTeam']['name']} – {e['awayTeam']['name']}</b>\n"
            f"🏆 {liga}\n⏱️ Minuto {mn} · 0-0\n\n🎯 Tiros a puerta: {sot[0]:.0f}-{sot[1]:.0f}\n"
            f"👟 Tiros: {sh[0]:.0f}-{sh[1]:.0f}\n🚩 Córners: {co[0]:.0f}-{co[1]:.0f}{xgl}{oddl}\n\n"
            f"✅ <b>Más de 0,5 goles 1.ª parte</b>\n💶 Entra solo si la cuota es ≥ 1,60 · Stake 10 €\n"
            f"🔗 <a href=\"{link(e)}\">Ver en SofaScore</a>")


# ---------- Imagen a elegir (botones) ----------
MARKETS = {'u05': 'Menos de 0,5 goles 1.ª parte', 'u1': 'Menos de 1 gol 1.ª parte',
           'u15': 'Menos de 1,5 goles 1.ª parte', 'o05': 'Más de 0,5 goles 1.ª parte',
           'o15': 'Más de 1,5 goles 1.ª parte'}
LABELS = {'u05': '−0,5', 'u1': '−1', 'u15': '−1,5', 'o05': '+0,5', 'o15': '+1,5'}
UNDER_KEYS, OVER_KEYS = ('u05', 'u1', 'u15'), ('o05', 'o15')
QUICK = {'-0.5': 'u05', '-05': 'u05', '-1': 'u1', '-1.0': 'u1', '-1.5': 'u15', '-15': 'u15',
         '+0.5': 'o05', '+05': 'o05', '+1.5': 'o15', '+15': 'o15'}


def keyboard(ref, keys):
    return json.dumps({'inline_keyboard': [[{'text': f'📸 {LABELS[k]}', 'callback_data': f'img|{k}|{ref}'}
                                            for k in keys]]})


def refresh(ref):
    """Minuto y marcador actuales del partido (para que la imagen salga al día)."""
    try:
        if ref.startswith('s'):
            ev = (sget(f'/event/{ref[1:]}') or {}).get('event') or {}
            start = (ev.get('time') or {}).get('currentPeriodStartTimestamp')
            status = (ev.get('status') or {}).get('description', '')
            mn = ''
            if start and status in ('1st half', '2nd half'):
                mn = str(int((time.time() - start) / 60) + (45 if status == '2nd half' else 0))
            elif status == 'Halftime':
                mn = 'Descanso'
            sc = f"{ev['homeScore'].get('current', 0)}-{ev['awayScore'].get('current', 0)}"
            return mn, sc
        if ref.startswith('e'):
            import live_bot
            d = live_bot.get(f'https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary?event={ref[1:]}')
            c = d['header']['competitions'][0]
            t = {x['homeAway']: x.get('score', '0') for x in c['competitors']}
            m = re.match(r"(\d+)'", c['status'].get('displayClock', ''))
            return (m.group(1) if m else ''), f"{t.get('home', '0')}-{t.get('away', '0')}"
    except Exception as ex:
        print('No pude actualizar el minuto:', ex)
    return None, None


def make_and_send(cid, d, mercado, cuota):
    png = aa_image.make_live_image(d['liga'], d['minuto'], d['marcador'], d['local'], d['visitante'], mercado, cuota)
    cap = (f"🔴 <b>PICK EN VIVO</b> 🔴\n\n⚽ <b>{d['local']} vs {d['visitante']}</b> · {d['liga']}\n"
           f"⏱️ Minuto {d['minuto']} · {d['marcador']}\n✅ <b>{mercado}</b> · <b>{f'{cuota:.2f}'.replace('.', ',')}</b>\n\n"
           f"💰 Stake: 10 €\n📲 Más pronósticos en la app A. Analytics\n+18 · Apuesta con responsabilidad")
    aa_image.send_photo(CFG['TELEGRAM_TOKEN'], cid, png, cap)
    print(datetime.now().strftime('%H:%M'), 'Imagen', mercado, cuota, d['local'])


REPLY_HINT = '\n📸 Pulsa un botón o responde con la cuota (ej. 1.62) para la imagen'


def deliver(cid, msg, cuota=None, markup=None):
    """Envía la alerta con su imagen (si se puede) y el texto como pie de foto."""
    msg += REPLY_HINT
    if aa_image:
        try:
            d = aa_image.parse_alert(re.sub(r'<[^>]+>', '', msg))
            png = aa_image.make_live_image(d['liga'], d['minuto'], d['marcador'], d['local'],
                                           d['visitante'], d['mercado'], cuota)
            if aa_image.send_photo(CFG['TELEGRAM_TOKEN'], cid, png, msg, markup).get('ok'):
                return
        except Exception as ex:
            print('Imagen no enviada:', ex)
    send(cid, msg, markup)


def replies(state, cid):
    """Botones 📸 y respuestas con cuota -> imagen lista para publicar en Telegram.

    · Botón 📸 −0,5 / −1 / −1,5 / +0,5 / +1,5 -> te pregunto la cuota.
    · Responder a una alerta con "1.62" -> imagen con el mercado de la alerta.
    · Responder a una alerta con "-1.5 1.62" -> imagen con ese mercado y esa cuota.
    """
    if not aa_image:
        return
    try:
        ups = tg('getUpdates', offset=state.get('offset', 0), timeout=0).get('result', [])
    except Exception:
        return
    for u in ups:
        state['offset'] = u['update_id'] + 1
        try:
            cb = u.get('callback_query')
            if cb:
                msg = cb.get('message') or {}
                if str(msg.get('chat', {}).get('id')) != str(cid):
                    continue
                parts = (cb.get('data') or '').split('|')
                try:
                    tg('answerCallbackQuery', callback_query_id=cb['id'], text='Escribe la cuota 👇')
                except Exception:
                    pass
                if len(parts) != 3 or parts[0] != 'img' or parts[1] not in MARKETS:
                    continue
                d = aa_image.parse_alert(msg.get('caption') or msg.get('text') or '')
                if not d:
                    continue
                mn, sc = refresh(parts[2])
                if mn is not None:
                    d['minuto'], d['marcador'] = mn or d['minuto'], sc or d['marcador']
                send(cid, (f"📸 <b>Imagen para publicar</b>\n\n⚽ <b>{d['local']} – {d['visitante']}</b>\n"
                           f"🏆 {d['liga']}\n⏱️ Minuto {d['minuto']} · {d['marcador']}\n"
                           f"✅ <b>{MARKETS[parts[1]]}</b>\n🔎 ref {parts[2]}\n\n"
                           f"✍️ Responde a ESTE mensaje con la cuota (ej. 1.62)"),
                     reply_markup=json.dumps({'force_reply': True, 'input_field_placeholder': 'Cuota, ej. 1.62'}))
                continue
            m = u.get('message') or {}
            if str(m.get('chat', {}).get('id')) != str(cid):
                continue
            txt = (m.get('text') or '').strip().replace(',', '.')
            q = re.match(r'^(?:([+-]\s*\d+(?:\.\d+)?)\s+)?(\d+\.\d+)$', txt)
            rep = m.get('reply_to_message') or {}
            src = rep.get('caption') or rep.get('text') or ''
            if not q or not src:
                continue
            d = aa_image.parse_alert(src)
            if not d:
                continue
            mercado = d['mercado']
            if '✅' not in src and 'muchos goles' in src:  # aviso de 5' de liga de muchos goles
                mercado = MARKETS['o05']
            if q.group(1):
                k = QUICK.get(q.group(1).replace(' ', ''))
                if not k:
                    send(cid, 'Mercados: -0.5 · -1 · -1.5 · +0.5 · +1.5 (ej. "-1.5 1.62")')
                    continue
                mercado = MARKETS[k]
            ref = re.search(r'ref ([se]\d+)', src)
            if ref and not rep.get('caption'):
                pass  # el aviso de botón ya trae el minuto del momento en que lo pulsaste
            elif ref or re.search(r'#id:(\d+)', src):
                mn, sc = refresh(ref.group(1) if ref else 's' + re.search(r'#id:(\d+)', src).group(1))
                if mn:
                    d['minuto'], d['marcador'] = mn, sc or d['marcador']
            make_and_send(cid, d, mercado, float(q.group(2)))
        except Exception as ex:
            print('Error respuesta:', ex)


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
        is_high = bool(HIGH_NAME.search(f"{ut.get('name', tname)} ({country})")) and not is_low and not is_med
        if is_high:
            liga = f"{ut.get('name', tname)} ({country})"
        hs, as_ = e['homeScore'].get('current', 0), e['awayScore'].get('current', 0)
        ref = f"s{e['id']}"
        if status == '1st half' and 5 <= mn <= 12 and hs == 0 and as_ == 0 and (is_low or is_high):
            key = f"pre:{e['id']}" if is_low else f"preo:{e['id']}"
            if key not in state['sent']:
                if is_low:
                    txt = (f"👀 <b>PARTIDO A VIGILAR</b> · liga de pocos goles\n\n"
                           f"⚽ <b>{e['homeTeam']['name']} – {e['awayTeam']['name']}</b>\n🏆 {liga}\n"
                           f"⏱️ Minuto {mn} · 0-0\n\n"
                           f"Candidato al Filtro 2 (−0,5 1.ª parte). Si sigue 0-0 y cerrado, te aviso en el 25'.\n")
                else:
                    txt = (f"👀 <b>PARTIDO A VIGILAR</b> · liga de muchos goles\n\n"
                           f"⚽ <b>{e['homeTeam']['name']} – {e['awayTeam']['name']}</b>\n🏆 {liga}\n"
                           f"⏱️ Minuto {mn} · 0-0\n\n"
                           f"Candidato a +0,5 goles 1.ª parte. Si aprieta, te aviso entre el 20' y el 32'.\n")
                send(cid, txt + f"📸 Pulsa un botón para crear la imagen para Telegram\n"
                                f"🔗 <a href=\"{link(e)}\">Ver en SofaScore</a>",
                     keyboard(ref, UNDER_KEYS if is_low else OVER_KEYS))
                state['sent'][key] = now
                print(datetime.now().strftime('%H:%M'), 'AVISO 5\'', 'pocos' if is_low else 'muchos',
                      e['homeTeam']['name'], '-', e['awayTeam']['name'])
            continue
        if status != '1st half' or hs != 0 or as_ != 0:
            continue
        tipos = []
        if 25 <= mn <= 34 and (is_low or is_med):
            tipos.append('f2')
        if 20 <= mn <= 32 and is_high:
            tipos.append('over')
        if 15 <= mn <= 40:  # favorito: −0,5 1.ª parte (todas las ligas)
            tipos.append('fav')
        tipos = [t for t in tipos if f"{t}:{e['id']}" not in state['sent']]
        if not tipos:
            continue
        od, st = None, None
        for tipo in tipos:
            key = f"{tipo}:{e['id']}"
            if (e.get('homeRedCards') or 0) + (e.get('awayRedCards') or 0) > 0 and tipo == 'f2':
                continue
            if od is None:
                od = odds(e['id'])
            if tipo == 'fav' and not od.get('pre'):
                continue
            if st is None:
                st = stats(e['id'])
            if not st:  # sin estadísticas → no se entra
                break
            if tipo == 'f2':
                msg = filtro2(e, mn, st, od, liga, strict=is_med and not is_low)
            elif tipo == 'over':
                msg = filtro_over(e, mn, st, od, liga)
            else:
                msg = favorito(e, mn, st, od, liga)
            if msg:
                deliver(cid, msg, None, keyboard(ref, OVER_KEYS if tipo == 'over' else UNDER_KEYS))
                state['sent'][key] = now
                if tipo == 'over':  # no mandar después un −0,5 contradictorio en el mismo partido
                    state['sent'][f"fav:{e['id']}"] = now
                if tipo == 'fav' and is_high:  # ni un +0,5 después de recomendar −0,5
                    state['sent'][f"over:{e['id']}"] = now
                print(datetime.now().strftime('%H:%M'), 'ENVIADO', tipo, e['homeTeam']['name'], '-', e['awayTeam']['name'])
                break
        time.sleep(0.4)

def main():
    if not CFG.get('TELEGRAM_TOKEN'):
        sys.exit('Falta TELEGRAM_TOKEN en bot_config.txt')
    state = load_state()
    cid = get_chat(state)
    if not cid:
        sys.exit('Escribe "hola" a tu bot en Telegram y vuelve a abrir el programa.')
    send(cid, '🖥️ <b>Bot del PC activado</b>\nVigilo SofaScore cada minuto: Filtro 2 (−0,5), +0,5 goles 1.ª parte, '
              'favoritos en vivo y partidos a vigilar a los 5\'. 📸 Botones para crear la imagen.')
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
            for p in live_bot.prealerts():
                if p['id'] not in sent:
                    send(cid, live_bot.premessage(p), live_bot.prekb(p))
                    sent[p['id']] = time.time()
            for p in live_bot.candidates() + live_bot.over_candidates():
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
