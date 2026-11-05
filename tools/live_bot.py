#!/usr/bin/env python3
"""Bot de alertas en vivo de A. Analytics – Filtro 2 (−0,5 goles 1.ª parte).

Revisa ESPN cada minuto durante ~4,5 min (el workflow lo lanza cada 5 min)
y envía por Telegram los partidos que cumplen el filtro. Cada partido se
avisa una sola vez (estado en bot_state.json, guardado con actions/cache).

Variables de entorno:
  TELEGRAM_TOKEN    token del bot (secreto de GitHub)          [obligatorio]
  TELEGRAM_CHAT_ID  chat al que enviar (opcional: si falta, se toma del
                    primer chat que escriba al bot)
  BOT_LOOPS         nº de revisiones por ejecución (defecto 5)
  BOT_TEST          "1" para enviar un mensaje de prueba y salir
"""
import datetime as dt, json, os, re, sys, time, urllib.parse, urllib.request

STATE_FILE = os.environ.get('BOT_STATE', 'bot_state.json')
TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
API = f'https://api.telegram.org/bot{TOKEN}/'

# Ligas de pocos goles (máx. 2 tiros a puerta entre los dos)
LOW = {
    745: 'Liga Profesional 🇦🇷', 3903: 'Primera Nacional 🇦🇷', 3904: 'Primera B 🇦🇷',
    4007: 'Brasileirão Série B 🇧🇷', 11088: 'Brasileirão Série C 🇧🇷',
    670: 'Liga 1 🇵🇪', 680: 'Liga AUF 🇺🇾', 3949: 'Liga FUTVE 🇻🇪', 650: 'Primera A 🇨🇴',
    660: 'LigaPro 🇪🇨', 3926: 'Ligue 2 🇫🇷', 3921: 'LaLiga 2 🇪🇸', 3931: 'Serie B 🇮🇹',
    715: 'Liga Portugal 🇵🇹', 3939: 'Liga rusa 🇷🇺', 3955: 'Super League 🇬🇷',
    10747: 'Liga 1 🇷🇴', 3937: 'Premiership 🇿🇦', 3932: 'Liga de Expansión 🇲🇽',
}
# Ligas medias (más exigente: máx. 1 tiro a puerta y máx. 8 tiros)
MED = {
    640: 'Primera División 🇨🇱', 3934: 'Primera División 🇵🇾', 3914: 'Championship 🏴',
    740: 'LaLiga 🇪🇸', 730: 'Serie A 🇮🇹', 710: 'Ligue 1 🇫🇷', 3946: 'Süper Lig 🇹🇷',
    700: 'Premier League 🏴', 760: 'Liga MX 🇲🇽', 3915: 'League One 🏴',
}
# Ligas de muchos goles (aviso a los 5' y filtro +0,5 goles 1.ª parte)
HIGH = {
    720: 'Bundesliga 🇩🇪', 3927: '2. Bundesliga 🇩🇪', 725: 'Eredivisie 🇳🇱', 3933: 'Eerste Divisie 🇳🇱',
    3901: 'Pro League 🇧🇪', 3944: 'Super League 🇨🇭', 3907: 'Bundesliga 🇦🇹', 3960: 'Eliteserien 🇳🇴',
    3945: 'Allsvenskan 🇸🇪', 3913: 'Superliga 🇩🇰', 770: 'MLS 🇺🇸', 4002: 'USL Championship 🇺🇸',
    3906: 'A-League 🇦🇺', 21231: 'Saudi Pro League 🇸🇦', 735: 'Premiership 🏴', 3963: 'Cymru Premier 🏴',
}
MIN_FROM, MIN_TO = 25, 34
OVER_FROM, OVER_TO = 20, 32

# Mercados para la imagen (botones de Telegram)
MARKETS = {'u05': 'Menos de 0,5 goles 1.ª parte', 'u1': 'Menos de 1 gol 1.ª parte',
           'u15': 'Menos de 1,5 goles 1.ª parte', 'o05': 'Más de 0,5 goles 1.ª parte',
           'o15': 'Más de 1,5 goles 1.ª parte'}
LABELS = {'u05': '−0,5', 'u1': '−1', 'u15': '−1,5', 'o05': '+0,5', 'o15': '+1,5'}
UNDER_KEYS, OVER_KEYS = ('u05', 'u1', 'u15'), ('o05', 'o15')


def keyboard(ref, keys):
    """Botones 📸 para elegir el mercado de la imagen. ref = 's123' (SofaScore) o 'e123' (ESPN)."""
    return json.dumps({'inline_keyboard': [[{'text': f'📸 {LABELS[k]}', 'callback_data': f'img|{k}|{ref}'}
                                            for k in keys]]})


def get(url, timeout=40):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def tg(method, **params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(API + method, data=data, timeout=30) as r:
        return json.load(r)


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {'sent': {}, 'chat_id': None}


def save_state(s):
    cutoff = time.time() - 3 * 86400
    s['sent'] = {k: v for k, v in s['sent'].items() if v > cutoff}
    with open(STATE_FILE, 'w') as f:
        json.dump(s, f)


def chat_id(state):
    cid = os.environ.get('TELEGRAM_CHAT_ID', '').strip() or state.get('chat_id')
    if cid:
        return cid
    try:
        for u in reversed(tg('getUpdates').get('result', [])):
            m = u.get('message') or u.get('edited_message') or {}
            if m.get('chat', {}).get('type') == 'private':
                state['chat_id'] = str(m['chat']['id'])
                send(state['chat_id'], '✅ <b>Bot A. Analytics activado</b>\n'
                     'Te avisaré aquí de los partidos que cumplan el Filtro 2 '
                     '(−0,5 goles en la 1.ª parte).')
                return state['chat_id']
    except Exception as e:
        print('getUpdates error:', e)
    return None


def send(cid, text, markup=None):
    extra = {'reply_markup': markup} if markup else {}
    return tg('sendMessage', chat_id=cid, text=text, parse_mode='HTML',
              disable_web_page_preview='true', **extra)


def minute(clock):
    m = re.match(r"(\d+)'", clock or '')
    return int(m.group(1)) if m else None


def stat(team, key):
    for s in team.get('statistics', []):
        if s.get('name') == key:
            try:
                return float(s.get('displayValue') or 0)
            except ValueError:
                return 0.0
    return None


def candidates():
    now = dt.datetime.now(dt.timezone.utc)
    seen, out = set(), []
    for d in {now.strftime('%Y%m%d'), (now - dt.timedelta(hours=6)).strftime('%Y%m%d')}:
        try:
            data = get('https://site.api.espn.com/apis/site/v2/sports/soccer/all/'
                       f'scoreboard?dates={d}&limit=500')
        except Exception as e:
            print('ESPN error:', e)
            continue
        for e in data.get('events', []):
            if e['id'] in seen:
                continue
            seen.add(e['id'])
            m = re.search(r'~l:(\d+)~', e.get('uid', ''))
            lid = int(m.group(1)) if m else None
            if lid not in LOW and lid not in MED:
                continue
            c = e['competitions'][0]
            st = c['status']
            if st['type'].get('state') != 'in' or st.get('period') != 1:
                continue
            mn = minute(st.get('displayClock'))
            if mn is None or not (MIN_FROM <= mn <= MIN_TO) or '+' in st.get('displayClock', ''):
                continue
            t = c['competitors']
            if any(x.get('score') != '0' for x in t):
                continue
            pos = sum(stat(x, 'possessionPct') or 0 for x in t)
            if pos <= 0:  # sin estadísticas reales → no se entra
                continue
            if any('red' in (dd.get('type', {}).get('text', '').lower()) for dd in c.get('details', [])):
                continue
            sot = [stat(x, 'shotsOnTarget') or 0 for x in t]
            sh = [stat(x, 'totalShots') or 0 for x in t]
            co = [stat(x, 'wonCorners') or 0 for x in t]
            low = lid in LOW
            if sum(sot) > (2 if low else 1):
                continue
            if not low and sum(sh) > 8:
                continue
            home = next(x for x in t if x.get('homeAway') == 'home')
            away = next(x for x in t if x.get('homeAway') == 'away')
            hi, ai = t.index(home), t.index(away)
            out.append({
                'id': e['id'], 'kind': 'f2', 'liga': (LOW if low else MED)[lid], 'nivel': 'baja' if low else 'media',
                'local': home['team']['displayName'], 'visit': away['team']['displayName'],
                'min': mn, 'sot': (int(sot[hi]), int(sot[ai])), 'sh': (int(sh[hi]), int(sh[ai])),
                'co': (int(co[hi]), int(co[ai])),
            })
    return out


def scoreboard_events():
    now = dt.datetime.now(dt.timezone.utc)
    seen = set()
    for d in {now.strftime('%Y%m%d'), (now - dt.timedelta(hours=6)).strftime('%Y%m%d')}:
        try:
            data = get('https://site.api.espn.com/apis/site/v2/sports/soccer/all/'
                       f'scoreboard?dates={d}&limit=500')
        except Exception as e:
            print('ESPN error:', e)
            continue
        for e in data.get('events', []):
            if e['id'] not in seen:
                seen.add(e['id'])
                yield e


def prealerts():
    """Minuto 5-12 y 0-0: ligas de pocos goles (candidato −0,5) y de muchos goles (candidato +0,5)."""
    out = []
    for e in scoreboard_events():
        m = re.search(r'~l:(\d+)~', e.get('uid', ''))
        lid = int(m.group(1)) if m else None
        if lid not in LOW and lid not in HIGH:
            continue
        c = e['competitions'][0]
        st = c['status']
        mn = minute(st.get('displayClock'))
        if st['type'].get('state') != 'in' or st.get('period') != 1 or mn is None or not (5 <= mn <= 12):
            continue
        t = c['competitors']
        if any(x.get('score') != '0' for x in t):
            continue
        home = next(x for x in t if x.get('homeAway') == 'home')
        away = next(x for x in t if x.get('homeAway') == 'away')
        kind = 'low' if lid in LOW else 'high'
        out.append({'id': ('pre' if kind == 'low' else 'preo') + e['id'], 'eid': e['id'], 'kind': kind,
                    'liga': (LOW if kind == 'low' else HIGH)[lid], 'local': home['team']['displayName'],
                    'visit': away['team']['displayName'], 'min': mn})
    return out


def premessage(p):
    if p.get('kind') == 'high':
        return (f"👀 <b>PARTIDO A VIGILAR</b> · liga de muchos goles\n\n⚽ <b>{p['local']} – {p['visit']}</b>\n"
                f"🏆 {p['liga']}\n⏱️ Minuto {p['min']} · 0-0\n\n"
                f"Candidato a +0,5 goles 1.ª parte. Si aprieta (tiros a puerta), te aviso entre el 20' y el 32'.\n"
                f"📸 Pulsa un botón para crear la imagen para Telegram")
    return (f"👀 <b>PARTIDO A VIGILAR</b> · liga de pocos goles\n\n⚽ <b>{p['local']} – {p['visit']}</b>\n"
            f"🏆 {p['liga']}\n⏱️ Minuto {p['min']} · 0-0\n\n"
            f"Candidato al Filtro 2 (−0,5 1.ª parte). Si sigue 0-0 y cerrado, te aviso en el 25'.\n"
            f"📸 Pulsa un botón para crear la imagen para Telegram")


def prekb(p):
    return keyboard('e' + p['eid'], OVER_KEYS if p.get('kind') == 'high' else UNDER_KEYS)


def over_candidates():
    """Filtro +0,5 goles 1.ª parte: liga de muchos goles, 20'-32', 0-0 y partido abierto."""
    out = []
    for e in scoreboard_events():
        m = re.search(r'~l:(\d+)~', e.get('uid', ''))
        lid = int(m.group(1)) if m else None
        if lid not in HIGH:
            continue
        c = e['competitions'][0]
        st = c['status']
        if st['type'].get('state') != 'in' or st.get('period') != 1:
            continue
        mn = minute(st.get('displayClock'))
        if mn is None or not (OVER_FROM <= mn <= OVER_TO) or '+' in st.get('displayClock', ''):
            continue
        t = c['competitors']
        if any(x.get('score') != '0' for x in t):
            continue
        if sum(stat(x, 'possessionPct') or 0 for x in t) <= 0:
            continue
        sot = [stat(x, 'shotsOnTarget') or 0 for x in t]
        sh = [stat(x, 'totalShots') or 0 for x in t]
        co = [stat(x, 'wonCorners') or 0 for x in t]
        if not ((sum(sot) >= 3 and sum(sh) >= 8) or sum(sot) >= 4):
            continue
        home = next(x for x in t if x.get('homeAway') == 'home')
        away = next(x for x in t if x.get('homeAway') == 'away')
        hi, ai = t.index(home), t.index(away)
        out.append({'id': 'o' + e['id'], 'eid': e['id'], 'kind': 'over', 'liga': HIGH[lid],
                    'local': home['team']['displayName'], 'visit': away['team']['displayName'], 'min': mn,
                    'sot': (int(sot[hi]), int(sot[ai])), 'sh': (int(sh[hi]), int(sh[ai])),
                    'co': (int(co[hi]), int(co[ai]))})
    return out


def overmessage(p):
    return (f"🔥 <b>ALERTA +0,5 GOLES 1.ª PARTE</b>\n\n"
            f"⚽ <b>{p['local']} – {p['visit']}</b>\n🏆 {p['liga']}\n"
            f"⏱️ Minuto {p['min']} · 0-0\n\n"
            f"🎯 Tiros a puerta: {p['sot'][0]}-{p['sot'][1]}\n"
            f"👟 Tiros: {p['sh'][0]}-{p['sh'][1]}\n"
            f"🚩 Córners: {p['co'][0]}-{p['co'][1]}\n🔴 Liga de muchos goles y partido abierto\n\n"
            f"✅ <b>Más de 0,5 goles 1.ª parte</b>\n"
            f"💶 Entra solo si la cuota es ≥ 1,60 · Stake 10 €\n"
            f"📸 Pulsa un botón o responde con la cuota (ej. 1.75) para la imagen")


def message(p):
    warn = ''
    if max(p['co']) >= 5:
        warn = '\n⚠️ Un equipo lleva 5+ córners: cuidado con el balón parado'
    nivel = '🟢 Liga de pocos goles' if p['nivel'] == 'baja' else '🟡 Liga media (filtro más estricto)'
    return (f"🚨 <b>ALERTA FILTRO 2</b>\n\n"
            f"⚽ <b>{p['local']} – {p['visit']}</b>\n🏆 {p['liga']}\n"
            f"⏱️ Minuto {p['min']} · 0-0\n\n"
            f"🎯 Tiros a puerta: {p['sot'][0]}-{p['sot'][1]}\n"
            f"👟 Tiros: {p['sh'][0]}-{p['sh'][1]}\n"
            f"🚩 Córners: {p['co'][0]}-{p['co'][1]}\n{nivel}{warn}\n\n"
            f"✅ <b>Menos de 0,5 goles 1.ª parte</b>\n"
            f"💶 Entra solo si la cuota es ≥ 1,45 · Stake 10 €\n"
            f"📸 Pulsa un botón o responde con la cuota (ej. 1.62) para la imagen")


def deliver(cid, p):
    """Envía la alerta como imagen lista para Telegram (o solo texto si falla la imagen)."""
    over = p.get('kind') == 'over'
    text = overmessage(p) if over else message(p)
    mk = keyboard('e' + str(p.get('eid', p['id'])), OVER_KEYS if over else UNDER_KEYS)
    try:
        import aa_image
        png = aa_image.make_live_image(p['liga'], p['min'], '0-0', p['local'], p['visit'],
                                       MARKETS['o05' if over else 'u05'])
        r = aa_image.send_photo(TOKEN, cid, png, text, mk)
        if r.get('ok'):
            return
    except Exception as e:
        print('Imagen no enviada:', e)
    send(cid, text, mk)


def main():
    if not TOKEN:
        print('Falta TELEGRAM_TOKEN: añade el secreto en GitHub.')
        return
    state = load_state()
    cid = chat_id(state)
    if not cid:
        print('Aún no hay chat: escribe "hola" al bot en Telegram.')
        save_state(state)
        return
    if os.environ.get('BOT_TEST') == '1':
        send(cid, '🧪 <b>EJEMPLO</b> – así te llegarán las alertas (partido de muestra, no apostar):')
        deliver(cid, {'id': 'demo', 'liga': 'Primera Nacional 🇦🇷', 'nivel': 'baja', 'local': 'Colón',
                      'visit': 'Defensores de Belgrano', 'min': 27, 'sot': (0, 1), 'sh': (2, 3), 'co': (1, 0)})
        save_state(state)
        return
    loops = int(os.environ.get('BOT_LOOPS', '5'))
    for i in range(loops):
        for p in prealerts():
            if p['id'] not in state['sent']:
                try:
                    send(cid, premessage(p), prekb(p))
                    state['sent'][p['id']] = time.time()
                except Exception as e:
                    print('Telegram error:', e)
        for p in candidates() + over_candidates():
            if p['id'] in state['sent']:
                continue
            try:
                deliver(cid, p)
                state['sent'][p['id']] = time.time()
                print('Enviado:', p['local'], '-', p['visit'], p['min'])
            except Exception as e:
                print('Telegram error:', e)
        save_state(state)
        if i < loops - 1:
            time.sleep(55)


if __name__ == '__main__':
    main()
