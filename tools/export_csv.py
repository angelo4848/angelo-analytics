#!/usr/bin/env python3
"""Mantiene app.csv: registro acumulado día a día de los partidos ★★★ y su pronóstico.

Uso:
  python3 tools/export_csv.py            -> añade/actualiza con lo que hay en data.json
  python3 tools/export_csv.py --backfill -> además recorre el historial de git (una vez)
El Google Sheet "APP" lo importa con IMPORTDATA desde GitHub Pages.
"""
import csv, json, os, re, subprocess, sys
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA, OUT = os.path.join(ROOT, 'data.json'), os.path.join(ROOT, 'app.csv')
TZ = ZoneInfo('Europe/Lisbon')
FIELDS = ['Fecha', 'Hora', 'Liga', 'Local', 'Visitante', 'Pronóstico', 'Cuota', 'Resultado', 'Acierto']


def row(m):
    t = datetime.fromisoformat(m['inicio']).astimezone(TZ)
    ten = m.get('tendencia', '').replace('★★★ ', '')
    ac = 'Acertado' if '✓' in ten else 'Fallado' if '✗' in ten else ''
    ten = re.sub(r' · [✓✗].*$', '', ten)
    cu = re.search(r'cuota ~?([\d,]+)', ten)
    pron = re.sub(r' · cuota.*$', '', ten).strip()
    return {'Fecha': t.strftime('%Y-%m-%d'), 'Hora': t.strftime('%H:%M'), 'Liga': m.get('liga', ''),
            'Local': m.get('local', ''), 'Visitante': m.get('visitante', ''), 'Pronóstico': pron,
            'Cuota': cu.group(1).replace(',', '.') if cu else '', 'Resultado': m.get('resultado', '') or '',
            'Acierto': ac}


def key(r):
    return (r['Fecha'], r['Local'].lower(), r['Visitante'].lower())


def merge(rows, partidos):
    for m in partidos:
        if not m.get('inicio') or '★★★' not in m.get('tendencia', ''):
            continue
        r = row(m)
        old = rows.get(key(r))
        if old:  # no perder un resultado ya conocido
            for f in ('Resultado', 'Acierto', 'Cuota'):
                r[f] = r[f] or old[f]
        rows[key(r)] = r


def main():
    rows = {}
    if os.path.exists(OUT):
        with open(OUT, encoding='utf-8') as f:
            rows = {key(r): r for r in csv.DictReader(f)}
    if '--backfill' in sys.argv:
        revs = subprocess.run(['git', 'log', '--reverse', '--format=%H', '--', 'data.json'], cwd=ROOT,
                              capture_output=True, text=True).stdout.split()
        for h in revs:
            try:
                d = json.loads(subprocess.run(['git', 'show', f'{h}:data.json'], cwd=ROOT,
                                              capture_output=True, text=True).stdout)
                merge(rows, d.get('partidos', []))
            except Exception:
                pass
    merge(rows, json.load(open(DATA, encoding='utf-8')).get('partidos', []))
    out = sorted(rows.values(), key=lambda r: (r['Fecha'], r['Hora'], r['Local']), reverse=True)
    with open(OUT, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    print(f'app.csv: {len(out)} partidos')


if __name__ == '__main__':
    main()
