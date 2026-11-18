#!/bin/bash
# =====================================================================================================
#  Instalador del Monitoreo fiscal (robots + web) en un servidor nuevo en la nube.  Versión 1.4.0 / web 2.4
#  Servidor: Ubuntu 24.04 LTS, 2 GB de RAM o más (el navegador del robot usa memoria), recién creado.
#
#  Uso (como root, en la carpeta donde se descomprimió el paquete):
#      bash instalar_nube.sh  [--dominio robots.tuestudio.com.ar]  [--github tdainman-code/monitoreo-fiscal]
#  Si no se indica dominio se usa  <ip-con-guiones>.sslip.io  (gratis, apunta solo a la IP del servidor) y el
#  candado (https) lo saca Caddy automáticamente con Let's Encrypt.
#
#  Qué hace:
#   1. Actualiza el sistema, zona horaria de Argentina, firewall (solo SSH, 80 y 443), fail2ban,
#      actualizaciones automáticas de seguridad.
#   2. Usuarios separados:  robot (corre los robots y es el ÚNICO que puede leer las claves)  y
#      web (la aplicación: NO puede leer la llave ni el almacén de claves).
#   3. Robots en /home/robot/app (Python + Chromium + pantalla virtual para AGIP).
#   4. Web en /opt/robots-web detrás de Caddy (https).
#   5. Tareas automáticas: corridas nocturnas (diaria / semanal / planes), claves cargadas desde la web
#      (cada 3 min) y corridas pedidas desde la web (cada 1 min).
#  NO crea la llave maestra si después se va a migrar desde la máquina de la oficina (ver migrar_desde_oficina.sh).
#  Se puede volver a correr: no borra datos, claves ni usuarios.
# =====================================================================================================
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Correr como root:  sudo bash instalar_nube.sh"; exit 1; }
AQUI="$(cd "$(dirname "$0")" && pwd)"
PAQ="$(cd "$AQUI/.." && pwd)"
[ -d "$PAQ/robots" ] && [ -d "$PAQ/robots_web" ] || { echo "No encuentro robots/ y robots_web/ en $PAQ"; exit 1; }

DOMINIO=""; GITHUB=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dominio) DOMINIO="$2"; shift 2;;
    --github) GITHUB="$2"; shift 2;;
    *) echo "Opción desconocida: $1"; exit 1;;
  esac
done
IP=$(curl -fsS4 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
DOMINIO="${DOMINIO:-$(echo "$IP" | tr . -).sslip.io}"
echo "== Servidor $IP  ->  https://$DOMINIO"

echo "== 1. Sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get -y -q upgrade
apt-get -y -q install python3-venv python3-pip unzip curl openssl git rsync xvfb xauth poppler-utils ufw fail2ban \
  unattended-upgrades debian-keyring debian-archive-keyring apt-transport-https sqlite3 cron
timedatectl set-timezone America/Argentina/Buenos_Aires
dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null 2>&1 || true
if ! command -v caddy >/dev/null; then
  apt-get -y -q install caddy 2>/dev/null || {
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -q && apt-get -y -q install caddy; }
fi
# memoria de intercambio: Chromium + la web entran justo en 2 GB
if ! swapon --show | grep -q swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
systemctl enable --now fail2ban >/dev/null 2>&1 || true

echo "== 2. Usuarios y carpetas"
getent group robotsweb >/dev/null || groupadd robotsweb
id robot >/dev/null 2>&1 || useradd --create-home --shell /bin/bash robot
id web >/dev/null 2>&1 || useradd --system --home-dir /var/lib/robots-web --shell /usr/sbin/nologin web
usermod -aG robotsweb robot; usermod -aG robotsweb web
mkdir -p /etc/robots /var/lib/robots /var/lib/robots-web /var/lib/robots-bandeja/pedidos /home/robot/logs
chown robot:robot /etc/robots; chmod 700 /etc/robots
chown robot:robotsweb /var/lib/robots; chmod 750 /var/lib/robots
for d in datos informes publico; do
  mkdir -p "/var/lib/robots/$d"; chown -R robot:robotsweb "/var/lib/robots/$d"
  chmod -R g+rX,g-w,o-rwx "/var/lib/robots/$d"; find "/var/lib/robots/$d" -type d -exec chmod g+s {} +
done
touch /var/lib/robots/ejecuciones.jsonl; chown robot:robotsweb /var/lib/robots/ejecuciones.jsonl; chmod 640 /var/lib/robots/ejecuciones.jsonl
chown web:web /var/lib/robots-web; chmod 700 /var/lib/robots-web
chown -R web:robot /var/lib/robots-bandeja; chmod 2770 /var/lib/robots-bandeja /var/lib/robots-bandeja/pedidos
chown robot:robot /home/robot/logs

echo "== 3. Robots"
rm -rf /home/robot/app.nuevo; mkdir -p /home/robot/app.nuevo
cp -r "$PAQ/robots" /home/robot/app.nuevo/
find /home/robot/app.nuevo -name '__pycache__' -prune -exec rm -rf {} +
[ -d /home/robot/app ] && mv /home/robot/app "/home/robot/app.anterior.$(date +%Y%m%d%H%M%S)"
mv /home/robot/app.nuevo /home/robot/app
chown -R robot:robot /home/robot/app
sudo -u robot bash -c '
  set -e
  [ -x ~/venv/bin/python ] || python3 -m venv ~/venv
  ~/venv/bin/pip install -q --upgrade pip
  ~/venv/bin/pip install -q playwright pandas openpyxl cryptography pypdf flask   # flask: para las pruebas
'
/home/robot/venv/bin/playwright install-deps chromium >/dev/null
sudo -u robot /home/robot/venv/bin/playwright install chromium >/dev/null
# llaves de los sobres (para cargar claves desde la web) — solo si no existen (la migración las trae)
if [ ! -f /etc/robots/sobres_privada.pem ] && [ -f /etc/robots/llave_maestra.key ]; then
  sudo -u robot bash -c 'cd ~/app && ~/venv/bin/python -m robots.almacen_claves crear-llaves-sobres'
fi
[ -f /etc/robots/sobres_publica.pem ] && install -o robot -g robotsweb -m 644 /etc/robots/sobres_publica.pem /var/lib/robots/publico/sobres_publica.pem

echo "== 4. Web"
mkdir -p /opt/robots-web
rm -rf /opt/robots-web/robots_web; cp -r "$PAQ/robots_web" /opt/robots-web/
find /opt/robots-web -name '__pycache__' -prune -exec rm -rf {} +
[ -x /opt/robots-web/venv/bin/python ] || python3 -m venv /opt/robots-web/venv
/opt/robots-web/venv/bin/pip install -q --upgrade flask gunicorn openpyxl
chown -R root:root /opt/robots-web; chmod -R go-w /opt/robots-web
cat > /etc/systemd/system/robots-web.service <<UNIT
[Unit]
Description=Monitoreo fiscal - aplicacion web
After=network-online.target

[Service]
User=web
Group=web
SupplementaryGroups=robotsweb
Environment=ROBOTS_RAIZ=/var/lib/robots
Environment=ROBOTS_WEB_DATOS=/var/lib/robots-web
Environment=ROBOTS_BANDEJA=/var/lib/robots-bandeja
WorkingDirectory=/opt/robots-web
ExecStart=/opt/robots-web/venv/bin/gunicorn -w 3 -b 127.0.0.1:8000 --forwarded-allow-ips=127.0.0.1 --access-logfile - robots_web.app:app
Restart=on-failure
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=/var/lib/robots-web /var/lib/robots-bandeja
InaccessiblePaths=/etc/robots

[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/caddy/Caddyfile <<CADDY
$DOMINIO {
    encode gzip
    reverse_proxy 127.0.0.1:8000 {
        header_up X-Forwarded-For {remote_host}
    }
    header {
        Strict-Transport-Security "max-age=31536000"
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        Referrer-Policy same-origin
        -Server
    }
}
CADDY
systemctl daemon-reload
systemctl enable --now robots-web >/dev/null 2>&1; systemctl restart robots-web
systemctl enable --now caddy >/dev/null 2>&1; systemctl reload caddy || systemctl restart caddy

echo "== 5. Tareas automáticas (usuario robot)"
install -o robot -g robot -m 755 "$AQUI/programar_nube.sh" /home/robot/programar_nube.sh
sudo -u robot bash /home/robot/programar_nube.sh

echo "== 6. Administrador de la web"
if ! sudo -u web env ROBOTS_WEB_DATOS=/var/lib/robots-web /opt/robots-web/venv/bin/python -m robots_web.usuarios listar 2>/dev/null | grep -qi admin; then
  read -r -p "   Usuario administrador para la web (ej. tomas): " ADMIN
  read -r -p "   Nombre a mostrar (ej. Tomás Dainman): " NOMBRE
  (cd /opt/robots-web && sudo -u web env ROBOTS_WEB_DATOS=/var/lib/robots-web /opt/robots-web/venv/bin/python -m robots_web.usuarios crear "$ADMIN" "$NOMBRE" --admin)
fi
# administrador del SERVIDOR (además de root): usuario con sudo, para entrar por SSH sin usar root
if [ -z "$(getent group sudo | cut -d: -f4)" ]; then
  read -r -p "   Usuario administrador del servidor (Enter para seguir usando solo root): " ADM_SRV
  if [ -n "$ADM_SRV" ]; then
    id "$ADM_SRV" >/dev/null 2>&1 || adduser --gecos "" "$ADM_SRV"
    usermod -aG sudo "$ADM_SRV"
    [ -f /root/.ssh/authorized_keys ] && install -d -o "$ADM_SRV" -m 700 "/home/$ADM_SRV/.ssh" \
      && install -o "$ADM_SRV" -m 600 /root/.ssh/authorized_keys "/home/$ADM_SRV/.ssh/authorized_keys"
  fi
fi

echo "== 7. Comprobando"
sleep 3
systemctl is-active --quiet robots-web && echo "   web: funcionando" || echo "   ERROR web: sudo journalctl -u robots-web -n 40"
systemctl is-active --quiet caddy && echo "   https: funcionando" || echo "   ERROR caddy: sudo journalctl -u caddy -n 40"
sudo -u robot bash -c 'cd ~/app && ~/venv/bin/python -c "import robots.correr, robots.pedidos, robots.robot_agip; print(\"   robots: OK\")"'
[ -f /etc/robots/llave_maestra.key ] && echo "   llave maestra: presente" || echo "   llave maestra: TODAVÍA NO (se trae con la migración, o: sudo -u robot bash -c 'cd ~/app && ~/venv/bin/python -m robots.almacen_claves crear-llave')"
if [ -n "$GITHUB" ]; then
  echo "== 8. GitHub ($GITHUB): cambios del código que se instalan solos"
  bash "$AQUI/conectar_github.sh" "$GITHUB"
fi
cat <<FIN

LISTO.  Abrir:  https://$DOMINIO     (el candado puede tardar 1 o 2 minutos la primera vez)
Más usuarios de la web (o desde la web: ⚙ Más -> Usuarios):
   sudo -u web env ROBOTS_WEB_DATOS=/var/lib/robots-web /opt/robots-web/venv/bin/python -m robots_web.usuarios crear tomas "Tomás" --admin
Prueba de un cliente (ARCA):   sudo -u robot bash -c 'cd ~/app && ~/venv/bin/python -m robots.correr situacion_fiscal --cuit 20XXXXXXXXX'
Prueba de AGIP:                sudo -u robot bash -c 'cd ~/app && xvfb-run -a ~/venv/bin/python -m robots.correr agip --cuit 30XXXXXXXXX'
Cambiar el robot: pedile el cambio a Claude Code sobre el repositorio de GitHub; el servidor lo prueba e instala solo.
   (sin GitHub todavía:  bash nube/conectar_github.sh tdainman-code/monitoreo-fiscal)
FIN-INSTALAR-NUBE
FIN
