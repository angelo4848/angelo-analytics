#!/usr/bin/env python3
"""Lector de TNNS (tnnslive.com) con un navegador automático (Playwright + Chromium, sin ventana).

TNNS carga todo con JavaScript, así que se abre como un navegador de verdad, se lee el texto de
la página y se buscan los dos jugadores y sus % de victoria.

Prueba / diagnóstico (haz esto la primera vez y mándale a Claude la carpeta tnns_debug):
    ~/aa-venv/bin/python tools/tnns.py diagnostico
    ~/aa-venv/bin/python tools/tnns.py "Sinner" "Rune"      (prueba un partido)

En bot_config.txt puedes cambiar la página que se abre:
    TNNS_URL=https://tnnslive.com
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

_pw = _browser = None
_lines, _when = [], 0.0
PCT = re.compile(r'(\d{1,3}(?:[.,]\d+)?)\s?%')


def norm(s):
    s = unicodedata.normalize('NFD', s or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z ]', ' ', s)


def tokens(name):
    """'Jannik Sinner' / 'Sinner J.' -> {'sinner', 'jannik'} (sin iniciales)."""
    return {t for t in norm(name).split() if len(t) >= 3}


def _page_text():
    global _pw, _browser
    if _browser is None:
        _pw = sync_playwright().start()
        _browser = _pw.chromium.launch(headless=True)
    page = _browser.new_page(viewport={'width': 1280, 'height': 2400},
                             user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36')
    try:
        page.goto(URL, wait_until='networkidle', timeout=45000)
        for _ in range(8):                      # baja para que cargue toda la lista
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(700)
        return page.inner_text('body'), page
    except Exception:
        page.close()
        raise


def refresh():
    """Carga TNNS una vez (al empezar cada scan). Devuelve True si se pudo leer."""
    global _lines, _when
    try:
        text, page = _page_text()
        page.close()
        _lines = [l.strip() for l in text.splitlines() if l.strip()]
        _when = time.time()
        return True
    except Exception as ex:
        print('  TNNS no carga:', str(ex)[:120])
        _lines = []
        return False


def prob(home, away):
    """(p_home, p_away) entre 0 y 1, o None si TNNS no tiene el partido."""
    if not _lines or time.time() - _when > 600:
        refresh()
    th, ta = tokens(home), tokens(away)
    if not th or not ta:
        return None
    low = [set(norm(l).split()) for l in _lines]
    for i, w in enumerate(low):
        if not (w & th):
            continue
        for j in range(max(0, i - 8), min(len(low), i + 12)):
            if j == i or not (low[j] & ta):
                continue
            lo, hi = min(i, j), max(i, j)
            for window in (_lines[lo: hi + 8], _lines[max(0, lo - 3): lo]):   # primero lo que va tras los nombres
                vals = [float(x.replace(',', '.')) for l in window for x in PCT.findall(l)]
                for k in range(len(vals) - 1):
                    a, b = vals[k], vals[k + 1]
                    if 95 <= a + b <= 105:
                        a, b = a / (a + b), b / (a + b)
                        return (a, b) if i < j else (b, a)    # el primer % es del primer nombre que aparece
    return None


def diagnostico():
    out = os.path.join(HERE, 'tnns_debug')
    os.makedirs(out, exist_ok=True)
    text, page = _page_text()
    page.screenshot(path=os.path.join(out, 'tnns.png'), full_page=True)
    open(os.path.join(out, 'tnns_texto.txt'), 'w', encoding='utf-8').write(text)
    page.close()
    n = len(PCT.findall(text))
    print(f'Guardado en {out}: tnns.png y tnns_texto.txt · {len(text)} caracteres · {n} porcentajes encontrados')


if __name__ == '__main__':
    if len(sys.argv) >= 3:
        print(prob(sys.argv[1], sys.argv[2]))
    else:
        diagnostico()
