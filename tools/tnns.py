#!/usr/bin/env python3
"""Lector de TNNS (tnnslive.com) con un navegador automático (Playwright + Chromium, sin ventana).

Dónde está el dato: en la lista de partidos NO hay porcentajes. Hay que entrar en el partido,
abrir la pestaña PREVIEW y leer "Pre-Match Predictor  63%  Hercog" (el % del jugador que TNNS
da como favorito). Este lector hace eso para cada partido que el bot le pide.

Pruebas:
    ~/aa-venv/bin/python tools/tnns.py "Polona Hercog" "Sofia Costoulas"
    ~/aa-venv/bin/python tools/tnns.py diagnostico      (foto + texto de la lista en tools/tnns_debug)

En bot_config.txt puedes cambiar la página que se abre:  TNNS_URL=https://tnnslive.com
"""
import os, re, sys, time, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from playwright.sync_api import sync_playwright   # si falta, tennis_bot.py desactiva TNNS

try:
    import pc_bot as base
    URL = (base.CFG.get('TNNS_URL') or '').strip() or 'https://tnnslive.com'
except Exception:
    URL = 'https://tnnslive.com'

DEBUG = os.path.join(HERE, 'tnns_debug')
_pw = _browser = None
_lines, _when = [], 0.0
_cache = {}                                   # (home, away) -> (resultado, hora)
PRED = re.compile(r'Pre-?Match Predictor\s*\n\s*(\d{1,3})\s?%\s*\n\s*([^\n]+)', re.I)


def norm(s):
    s = unicodedata.normalize('NFD', s or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z ]', ' ', s)


def tokens(name):
    """'Jannik Sinner' / 'Sinner J.' -> {'sinner', 'jannik'} (sin iniciales)."""
    return {t for t in norm(name).split() if len(t) >= 3}


def _browser_():
    global _pw, _browser
    if _browser is None:
        _pw = sync_playwright().start()
        _browser = _pw.chromium.launch(headless=True)
    return _browser


def _open_list():
    page = _browser_().new_page(viewport={'width': 1280, 'height': 2400},
                                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36')
    try:
        page.goto(URL, wait_until='networkidle', timeout=45000)
        for _ in range(8):                      # baja para que cargue toda la lista
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(500)
        return page
    except Exception:
        page.close()
        raise


def refresh():
    """Lee la lista de TNNS una vez (al empezar cada scan). Devuelve True si se pudo leer."""
    global _lines, _when
    try:
        page = _open_list()
        text = page.inner_text('body')
        page.close()
        _lines = [l.strip() for l in text.splitlines() if l.strip()]
        _when = time.time()
        return True
    except Exception as ex:
        print('  TNNS no carga:', str(ex)[:120])
        _lines = []
        return False


def _find_line(name):
    """Línea exacta de la lista de TNNS que corresponde a ese jugador (sin dobles)."""
    t = tokens(name)
    best = None
    for l in _lines:
        if '/' in l:
            continue
        w = set(norm(l).split())
        common = len(w & t)
        if common and (best is None or common > best[0]):
            best = (common, l)
    return best[1] if best else None


def parse_pred(text, home, away):
    """Texto de la pestaña PREVIEW -> (p_home, p_away) o None."""
    m = PRED.search(text)
    if not m:
        return None
    p = int(m.group(1)) / 100
    who = set(norm(m.group(2)).split())
    if who & tokens(home) and not who & tokens(away):
        return p, 1 - p
    if who & tokens(away) and not who & tokens(home):
        return 1 - p, p
    return None


def prob(home, away, debug=False):
    """(p_home, p_away) entre 0 y 1 según el Pre-Match Predictor de TNNS, o None."""
    key = (home, away)
    if key in _cache and time.time() - _cache[key][1] < 3600:
        return _cache[key][0]
    if not _lines or time.time() - _when > 900:
        refresh()
    line = _find_line(home) or _find_line(away)
    if not line:
        print('  TNNS no tiene el partido:', home, '-', away)
        return None
    res, page = None, None
    try:
        page = _open_list()
        page.get_by_text(line, exact=True).first.click(timeout=10000)
        page.wait_for_timeout(2500)
        page.get_by_text('Preview', exact=False).first.click(timeout=10000)
        try:
            page.get_by_text(re.compile('Pre-?Match Predictor', re.I)).first.wait_for(timeout=10000)
        except Exception:
            pass
        page.wait_for_timeout(800)
        text = page.inner_text('body')
        res = parse_pred(text, home, away)
        if debug or res is None:
            os.makedirs(DEBUG, exist_ok=True)
            page.screenshot(path=os.path.join(DEBUG, 'partido.png'), full_page=True)
            open(os.path.join(DEBUG, 'partido_texto.txt'), 'w', encoding='utf-8').write(page.url + '\n\n' + text)
        if res is None:
            print('  TNNS sin Pre-Match Predictor:', home, '-', away, '(mira tools/tnns_debug/partido.png)')
    except Exception as ex:
        print('  TNNS error en', home, '-', away, ':', str(ex)[:120])
    finally:
        if page:
            page.close()
    _cache[key] = (res, time.time())
    return res


def diagnostico():
    os.makedirs(DEBUG, exist_ok=True)
    page = _open_list()
    text = page.inner_text('body')
    page.screenshot(path=os.path.join(DEBUG, 'tnns.png'), full_page=True)
    open(os.path.join(DEBUG, 'tnns_texto.txt'), 'w', encoding='utf-8').write(text)
    page.close()
    print(f'Lista guardada en {DEBUG}: {len(text)} caracteres')


if __name__ == '__main__':
    if len(sys.argv) >= 3:
        r = prob(sys.argv[1], sys.argv[2], debug=True)
        if r:
            print(f'{sys.argv[1]} {100 * r[0]:.0f}%  ·  {sys.argv[2]} {100 * r[1]:.0f}%')
        else:
            print('Sin dato. Mira tools/tnns_debug/partido.png y partido_texto.txt')
    else:
        diagnostico()
