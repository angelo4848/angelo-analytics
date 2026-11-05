"""Genera la imagen "Pick en vivo" de A. Analytics (1080x1350) con Pillow.

make_live_image(liga, minuto, marcador, local, visitante, mercado, cuota=None) -> bytes PNG
"""
import io, os, re, datetime as dt
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
BG, GRID, GREEN, WHITE, MUTED, CARD, RED = (11, 26, 51), (26, 40, 64), (34, 197, 94), (255, 255, 255), (159, 179, 209), (27, 42, 66), (239, 68, 68)
DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

_CANDIDATES = {
    True: ['C:/Windows/Fonts/segoeuib.ttf', 'C:/Windows/Fonts/arialbd.ttf',
           '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/Library/Fonts/Arial Bold.ttf'],
    False: ['C:/Windows/Fonts/segoeui.ttf', 'C:/Windows/Fonts/arial.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/Library/Fonts/Arial.ttf'],
}


def font(size, bold=False):
    for p in _CANDIDATES[bold]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def clean(s):
    """Quita emojis/banderas que las fuentes no pintan."""
    return re.sub(r'[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F]', '', s or '').strip()


def fit(d, text, size, maxw, bold=True):
    while size > 20:
        f = font(size, bold)
        if d.textlength(text, font=f) <= maxw:
            return f
        size -= 2
    return font(size, bold)


def logo(d, x, y, s):
    d.rounded_rectangle([x, y, x + s, y + s], radius=int(s * .23), fill=WHITE)
    inner = s * 0.73
    k, o = inner / 70, (s - inner) / 2
    pt = lambda a, b: (x + o + a * k, y + o + b * k)
    d.line([pt(8, 62), pt(35, 8), pt(62, 62)], fill=BG, width=round(9 * k), joint='curve')
    d.line([pt(14, 48), pt(28, 38), pt(38, 44), pt(58, 22)], fill=GREEN, width=round(6 * k), joint='curve')


def make_live_image(liga, minuto, marcador, local, visitante, mercado, cuota=None, titulo='Pick en vivo'):
    im = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(im)
    for i in range(0, W, 60):
        d.line([(i, 0), (i, H)], fill=GRID, width=1)
    for j in range(0, H, 60):
        d.line([(0, j), (W, j)], fill=GRID, width=1)
    trend = [(0, 1130), (160, 1070), (300, 1090), (460, 990), (620, 1020), (780, 910), (920, 930), (1080, 810)]
    d.line(trend, fill=(20, 72, 68), width=8, joint='curve')

    logo(d, 70, 60, 96)
    fb = font(46, True)
    d.text((188, 82), 'A.', font=fb, fill=WHITE)
    d.text((188 + d.textlength('A. ', font=fb), 82), 'ANALYTICS', font=fb, fill=GREEN)

    d.text((70, 205), titulo, font=font(74, True), fill=WHITE)
    hoy = dt.datetime.now()
    d.text((70, 300), f"{DIAS[hoy.weekday()]} {hoy:%d/%m/%Y} · {clean(liga)}", font=fit(d, f"x {clean(liga)}", 30, 900, False), fill=MUTED)

    # tarjeta
    y0, y1 = 380, 640
    d.rounded_rectangle([70, y0, 1010, y1], radius=28, fill=CARD, outline=(52, 68, 94), width=2)
    d.ellipse([112, y0 + 42, 134, y0 + 64], fill=RED)
    mtxt = f"{minuto}' · " if str(minuto).isdigit() else (f"{minuto} · " if minuto else '')
    d.text((146, y0 + 36), f"EN VIVO · {mtxt}{marcador}", font=font(30, True), fill=MUTED)
    match = f"{clean(local)} vs {clean(visitante)}"
    oddw = 230 if cuota else 0
    d.text((112, y0 + 88), match, font=fit(d, match, 46, 860 - oddw), fill=WHITE)
    d.text((112, y0 + 160), clean(mercado), font=fit(d, clean(mercado), 34, 860 - oddw, False), fill=(219, 230, 245))
    if cuota:
        txt = f"{cuota:.2f}".replace('.', ',')
        fo = font(72, True)
        d.text((975 - d.textlength(txt, font=fo), y0 + 85), txt, font=fo, fill=GREEN)

    # bloque inferior
    ft = font(34)
    if cuota:
        big, sub = f"{cuota:.2f}".replace('.', ','), 'CUOTA · STAKE 10 €'
    else:
        big, sub = '≥ 1,45', 'CUOTA MÍNIMA · STAKE 10 €'
    d.text(((W - d.textlength(sub, font=ft)) / 2, 700), sub, font=ft, fill=MUTED)
    fbig = font(150, True)
    d.text(((W - d.textlength(big, font=fbig)) / 2, 750), big, font=fbig, fill=GREEN)

    foot = '+18. Apuesta con responsabilidad.'
    ff = font(28)
    d.text(((W - d.textlength(foot, font=ff)) / 2, 1268), foot, font=ff, fill=MUTED)

    buf = io.BytesIO()
    im.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


if __name__ == '__main__':
    open('prueba_live.png', 'wb').write(make_live_image('Primera Nacional 🇦🇷', 27, '0-0', 'Colón', 'Defensores de Belgrano', 'Menos de 0,5 goles 1.ª parte'))
    open('prueba_live2.png', 'wb').write(make_live_image('J1 League (Japan)', 40, '0-0', 'Machida Zelvia', 'Gamba Osaka', 'Victoria Machida Zelvia', 2.2))


def send_photo(token, chat_id, png, caption='', markup=None):
    """Envía una imagen PNG por Telegram (multipart, sin dependencias extra)."""
    import json, urllib.request, uuid
    b = uuid.uuid4().hex
    parts = []
    fields = [('chat_id', str(chat_id)), ('caption', caption), ('parse_mode', 'HTML')]
    if markup:
        fields.append(('reply_markup', markup))
    for k, v in fields:
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="photo"; filename="live.png"\r\n'
                 f'Content-Type: image/png\r\n\r\n'.encode() + png + b'\r\n')
    parts.append(f'--{b}--\r\n'.encode())
    req = urllib.request.Request(f'https://api.telegram.org/bot{token}/sendPhoto', data=b''.join(parts),
                                 headers={'Content-Type': f'multipart/form-data; boundary={b}'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def parse_alert(text):
    """Saca los datos de un mensaje de alerta del bot (para regenerar la imagen con la cuota)."""
    text = re.sub(r"<[^>]+>", "", text or "")
    m = re.search(r'⚽\s*(.+?)\s+–\s+(.+)', text)
    if not m:
        return None
    liga = re.search(r'🏆\s*(.+)', text)
    mn = re.search(r'Minuto\s+(\d+)\s*·\s*(\d+-\d+)', text)
    mk = re.search(r'✅\s*(.+?)(?:\s*·\s*cuota.*)?$', text, re.M)
    return {'local': m.group(1).strip(), 'visitante': m.group(2).strip(),
            'liga': liga.group(1).strip() if liga else '', 'minuto': mn.group(1) if mn else '',
            'marcador': mn.group(2) if mn else '0-0',
            'mercado': mk.group(1).strip() if mk else 'Menos de 0,5 goles 1.ª parte'}
