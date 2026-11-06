#!/usr/bin/env python3
"""A. Analytics – completa el registro con SofaScore desde TU PORTÁTIL (arranca solo al encender).

Cada hora:
  1. descarga el registro (app.csv) de GitHub;
  2. busca en SofaScore los partidos ya terminados de los últimos 3 días a los que les falte el
     descanso, los córners o el resultado (ESPN no cubre muchas ligas);
  3. sube lo que encuentra a GitHub (data/sofa_stats.csv). Desde ahí, GitHub lo mete en la app,
     en el Google Sheet y en el modelo en la siguiente actualización.

Necesita en bot_config.txt (la misma carpeta que el bot):
  GITHUB_TOKEN=...   (token "fine-grained" de GitHub con permiso Contents: Read and write SOLO para
                      el repositorio angelo-analytics; lo creas tú, nadie más lo ve)
Usa la conexión a SofaScore de pc_bot.py (curl_cffi / truststore).
"""
import base64, csv, io, json, os, re, sys, time, unicodedata, urllib.request
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pc_bot as base   # conexión SofaScore + bot_config.txt

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo('Europe/Lisbon')
except Exception:          # Windows sin tzdata
    TZ = timezone.utc

REPO = 'angelo4848/angelo-analytics'
RAW = f'https://raw.githubusercontent.com/{REPO}/main/'
PATH = 'data/sofa_stats.csv'
CACHE = os.path.join(HERE, 'sofa_sync_cache.json')
FIELDS = ['Fecha', 'Local', 'Visitante', 'Resultado', 'Descanso', 'Gol 1.ª parte', 'Goles 1.ª parte',
          'Córners L', 'Córners V', 'Córners total', 'Tiros L', 'Tiros V', 'A puerta L', 'A puerta V',
          'Posesión L %', 'Posesión V %', 'Amarillas L', 'Amarillas V', 'Rojas L', 'Rojas V']
MAX_PER_RUN = 150
DIAG = {}
EVERY_MIN = 60


def norm(s):
    s = unicodedata.normalize('NFD', s or '').encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    return re.sub(r'\b(fc|sc|cf|ac|club|de|the|cd|fk|sk)\b', ' ', s).split()


def same(a, b):
    A, B = norm(a), norm(b)
    return bool(A) and bool(B) and (A == B or set(A) <= set(B) or set(B) <= set(A))


# ---------- GitHub ----------
def gh(method, path, body=None):
    token = (base.CFG.get('GITHUB_TOKEN') or '').strip()
    req = urllib.request.Request(f'https://api.github.com/repos/{REPO}/contents/{path}', method=method,
                                 data=json.dumps(body).encode() if body else None,
                                 headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
                                          'User-Agent': 'aa-sofa-sync'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def raw(path):
    req = urllib.request.Request(RAW + path + f'?t={int(time.time())}', headers={'User-Agent': 'aa-sofa-sync'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode('utf-8')


# ---------- SofaScore ----------
def load_cache():
    try:
        return json.load(open(CACHE))
    except Exception:
        return {'teams': {}, 'days': {}}


def api_get(path):
    """Igual que pc_bot.sget pero contra api.sofascore.com (algunas rutas solo existen ahí)."""
    try:
        items = ([base._GOOD[0]] if base._GOOD[0] else []) + list(base._sessions())
    except Exception:
        return None
    for name, ses in items:
        try:
            r = ses.get('https://api.sofascore.com/api/v1' + path, timeout=20,
                        headers={'Referer': 'https://www.sofascore.com/', 'Accept': 'application/json'})
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
        except Exception:
            continue
    return None


def day_events(day, cache):
    """Partidos de fútbol de un día (SofaScore). Primero la lista del día; si no, nada."""
    k = day.isoformat()
    if k in cache['days'] and cache['days'][k]['t'] > time.time() - 3000:
        return cache['days'][k]['ev']
    d = base.sget(f'/sport/football/scheduled-events/{k}') or {}
    if not d.get('events'):
        d = api_get(f'/sport/football/scheduled-events/{k}') or d
    ev = [{'id': e['id'], 'h': e['homeTeam']['name'], 'a': e['awayTeam']['name'],
           'st': (e.get('status') or {}).get('type'), 'hs': e.get('homeScore', {}), 'as': e.get('awayScore', {}),
           'ts': e.get('startTimestamp', 0)} for e in d.get('events', [])]
    cache['days'][k] = {'t': time.time(), 'ev': ev}
    if not DIAG.get(k):
        DIAG[k] = True
        print(f'  SofaScore lista del día {k}: {len(ev)} partidos')
    return ev


def search_team(name):
    """Id de SofaScore de un equipo de FÚTBOL (prueba el nombre completo y sin 'FC', 'SC'...)."""
    base_name = re.sub(r'\b(FC|SC|CF|AFC|BC|FK|SK|CD|CA|AC|SD|UD|Club|Calcio)\b\.?', ' ', name, flags=re.I)
    variants = list(dict.fromkeys([name, ' '.join(base_name.split())]))
    for q in variants:
        for path in ('/search/all?q=', '/search/teams?q='):
            res = base.sget(path + urllib.request.quote(q)) or {}
            items = list(res.get('teams') or []) + [(x.get('entity') or x) for x in res.get('results') or []
                                                    if x.get('type') in (None, 'team')]
            foot = [t for t in items if t.get('id') and (t.get('sport') or {}).get('slug') == 'football'
                    and t.get('gender') != 'F']
            if foot:
                exact = [t for t in foot if same(name, t.get('name', '')) or same(name, t.get('shortName', ''))]
                return (exact or foot)[0]['id']
    return 0


def team_events(name, cache):
    """Busca el equipo y devuelve sus últimos partidos."""
    tid = cache['teams'].get(name)
    if not tid:
        tid = search_team(name)
        if tid:
            cache['teams'][name] = tid
        elif not DIAG.get('search'):
            DIAG['search'] = True
            print(f'  no encontré en SofaScore el equipo de fútbol "{name}"')
    if not tid:
        return []
    d = base.sget(f'/team/{tid}/events/last/0') or {}
    return [{'id': e['id'], 'h': e['homeTeam']['name'], 'a': e['awayTeam']['name'],
             'st': (e.get('status') or {}).get('type'), 'hs': e.get('homeScore', {}), 'as': e.get('awayScore', {}),
             'ts': e.get('startTimestamp', 0)} for e in d.get('events', [])]


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


def iv(v):
    try:
        return str(int(float(str(v).replace('%', ''))))
    except (TypeError, ValueError):
        return ''


def build_row(r, e):
    swap = same(r['Local'], e['a']) and same(r['Visitante'], e['h']) and not same(r['Local'], e['h'])
    hs, as_ = e['hs'], e['as']
    if 'current' not in hs or 'current' not in as_:
        return None
    gl, gv = hs['current'], as_['current']
    p1l, p1v = hs.get('period1'), as_.get('period1')
    st = stats(e['id'])
    pair = lambda k: (iv(st[k][0]), iv(st[k][1])) if k in st else ('', '')
    co, sh, so, po, ye, re_ = (pair('cornerKicks'), pair('totalShotsOnGoal'), pair('shotsOnGoal'),
                               pair('ballPossession'), pair('yellowCards'), pair('redCards'))
    if swap:
        gl, gv, p1l, p1v = gv, gl, p1v, p1l
        co, sh, so, po, ye, re_ = [(b, a) for a, b in (co, sh, so, po, ye, re_)]
    row = {'Fecha': r['Fecha'], 'Local': r['Local'], 'Visitante': r['Visitante'], 'Resultado': f'{gl} - {gv}'}
    if p1l is not None and p1v is not None:
        row.update({'Descanso': f'{p1l} - {p1v}', 'Gol 1.ª parte': 'Sí' if p1l + p1v else 'No',
                    'Goles 1.ª parte': str(p1l + p1v)})
    if co[0] and co[1]:
        row.update({'Córners L': co[0], 'Córners V': co[1], 'Córners total': str(int(co[0]) + int(co[1]))})
    row.update({'Tiros L': sh[0], 'Tiros V': sh[1], 'A puerta L': so[0], 'A puerta V': so[1],
                'Posesión L %': po[0], 'Posesión V %': po[1], 'Amarillas L': ye[0], 'Amarillas V': ye[1],
                'Rojas L': re_[0], 'Rojas V': re_[1]})
    return row


def run_once():
    if not (base.CFG.get('GITHUB_TOKEN') or '').strip():
        print('Falta GITHUB_TOKEN en bot_config.txt (mira el archivo LEEME_sofa_sync.txt)')
        return
    now = datetime.now(TZ)
    reg = list(csv.DictReader(io.StringIO(raw('app.csv'))))
    cur = gh('GET', PATH)
    have, sha = {}, None
    if cur:
        sha = cur['sha']
        text = base64.b64decode(cur['content']).decode('utf-8')
        have = {(r['Fecha'], r['Local'], r['Visitante']): r for r in csv.DictReader(io.StringIO(text))}
    first = (now.date() - timedelta(days=2)).isoformat()
    todo = []
    for r in reg:
        if not (first <= r['Fecha'] <= now.date().isoformat()):
            continue
        if (r['Fecha'], r['Local'], r['Visitante']) in have:
            continue
        if r.get('Descanso') and r.get('Córners total') and r.get('Resultado'):
            continue
        try:
            start = datetime.strptime(f"{r['Fecha']} {r['Hora']}", '%Y-%m-%d %H:%M').replace(tzinfo=TZ)
        except ValueError:
            continue
        if start + timedelta(minutes=125) > now:
            continue  # todavía jugándose
        todo.append(r)
    todo = todo[:MAX_PER_RUN]
    print(now.strftime('%H:%M'), f'Partidos por completar: {len(todo)}')
    cache, new = load_cache(), []
    cache['teams'] = {k: v for k, v in cache.get('teams', {}).items() if v}
    miss = 0
    for r in todo:
        try:
            d = date.fromisoformat(r['Fecha'])
            evs = day_events(d, cache) + day_events(d - timedelta(days=1), cache)
            e = next((x for x in evs if x['st'] == 'finished' and
                      ((same(r['Local'], x['h']) and same(r['Visitante'], x['a'])) or
                       (same(r['Local'], x['a']) and same(r['Visitante'], x['h'])))), None)
            for side, other in ((r['Local'], r['Visitante']), (r['Visitante'], r['Local'])):
                if e:
                    break
                for x in team_events(side, cache):
                    when = datetime.fromtimestamp(x['ts'], TZ).date() if x['ts'] else None
                    if x['st'] == 'finished' and when and abs((when - d).days) <= 1 and \
                            (same(other, x['a']) or same(other, x['h'])):
                        e = x
                        break
            if not e:
                miss += 1
                continue
            row = build_row(r, e)
            if row:
                new.append(row)
            time.sleep(0.5)
        except Exception as ex:
            print('  error con', r['Local'], '-', r['Visitante'], ':', str(ex)[:80])
    json.dump(cache, open(CACHE, 'w'))
    print(f'  encontrados en SofaScore: {len(new)} · sin encontrar: {miss}')
    if not new:
        print('  nada nuevo que subir')
        return
    rows = list(have.values()) + new
    cut = (now.date() - timedelta(days=10)).isoformat()   # el registro ya guarda lo antiguo
    rows = [x for x in rows if x['Fecha'] >= cut]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, extrasaction='ignore')
    w.writeheader()
    w.writerows(rows)
    body = {'message': f"SofaScore portátil {now:%Y-%m-%d %H:%M} (+{len(new)})",
            'content': base64.b64encode(buf.getvalue().encode('utf-8')).decode()}
    if sha:
        body['sha'] = sha
    gh('PUT', PATH, body)
    print(f'  subidos {len(new)} partidos a GitHub ✅')
    try:  # pedir a GitHub que los meta ya en la app y el Google Sheet (si el token tiene permiso Actions)
        import github_reloj
        github_reloj.dispatch('app-update.yml', {'modo': 'results'})
    except Exception:
        pass


def main():
    print('A. Analytics · SofaScore → GitHub. Deja esta ventana abierta (Ctrl+C para parar).')
    while True:
        try:
            run_once()
        except Exception as ex:
            print('Error:', str(ex)[:200])
        if '--once' in sys.argv:
            break
        time.sleep(EVERY_MIN * 60)


if __name__ == '__main__':
    main()
