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
MIN_FROM, MIN_TO = 25, 34


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


def send(cid, text):
    return tg('sendMessage', chat_id=cid, text=text, parse_mode='HTML',
              disable_web_page_preview='true')


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
                'id': e['id'], 'liga': (LOW if low else MED)[lid], 'nivel': 'baja' if low else 'media',
                'local': home['team']['displayName'], 'visit': away['team']['displayName'],
                'min': mn, 'sot': (int(sot[hi]), int(sot[ai])), 'sh': (int(sh[hi]), int(sh[ai])),
                'co': (int(co[hi]), int(co[ai])),
            })
    return out


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
            f"✍️ Responde a esta alerta con la cuota (ej. 1.62) y te mando la imagen con cuota")


def deliver(cid, p):
    """Envía la alerta como imagen lista para Telegram (o solo texto si falla la imagen)."""
    try:
        import aa_image
        png = aa_image.make_live_image(p['liga'], p['min'], '0-0', p['local'], p['visit'],
                                       'Menos de 0,5 goles 1.ª parte')
        r = aa_image.send_photo(TOKEN, cid, png, message(p))
        if r.get('ok'):
            return
    except Exception as e:
        print('Imagen no enviada:', e)
    send(cid, message(p))


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
        for p in candidates():
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
