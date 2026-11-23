#!/usr/bin/env bash
# A. Analytics – instala el bot de tenis en Linux (Ubuntu / Debian / Mint).
# Uso:  bash tools/instalar_linux.sh
set -e
cd "$(dirname "$0")"

echo "1/4 Paquetes del sistema…"
sudo apt-get update -qq
sudo apt-get install -y python3 python3-venv python3-pip

echo "2/4 Entorno de Python en ~/aa-venv…"
python3 -m venv ~/aa-venv
~/aa-venv/bin/pip install -q --upgrade pip
~/aa-venv/bin/pip install -q curl_cffi playwright pillow tzdata

echo "3/4 Navegador para TNNS (Chromium)…"
~/aa-venv/bin/playwright install --with-deps chromium

echo "4/4 Configuración…"
if [ ! -f bot_config.txt ]; then
  cat > bot_config.txt <<'EOF'
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=
SHEET_WEBHOOK=
SHEET_SECRET=
MIN_PROB=80
TNNS_OBLIGATORIO=1
VENTANA_MIN=20
EOF
  echo "   Creado tools/bot_config.txt -> pon tu TELEGRAM_TOKEN y la URL del Google Sheet."
fi

# Arranque automático al encender (servicio de usuario)
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/aa-tenis.service <<EOF
[Unit]
Description=A. Analytics bot de tenis
After=network-online.target

[Service]
WorkingDirectory=$(pwd)
ExecStart=$HOME/aa-venv/bin/python $(pwd)/tennis_bot.py
Restart=always
RestartSec=15

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
echo
echo "Listo ✅"
echo "  Probar a mano:      ~/aa-venv/bin/python $(pwd)/tennis_bot.py"
echo "  Probar TNNS:        ~/aa-venv/bin/python $(pwd)/tnns.py diagnostico"
echo "  Arranque automático: systemctl --user enable --now aa-tenis && sudo loginctl enable-linger $USER"
