#!/bin/bash
# =====================================================================================================
#  Instala el RESPALDO COMPLETO (respaldo_completo.sh) en otro servidor, para poder correr los robots desde ahí.
#  Servidor: Ubuntu 24.04, 2 GB de RAM o más. Correr como root, en la carpeta del respaldo:
#      sudo bash restaurar_respaldo.sh              (busca respaldo.enc al lado de este archivo)
#      sudo bash restaurar_respaldo.sh /ruta/respaldo.enc
#  Queda instalado SIN corridas automáticas (para no pisarse con la nube). Corrida urgente:
#      sudo bash /root/corrida_urgente.sh CUIT [robot]
#  Se puede volver a correr con un respaldo más nuevo: reemplaza código, claves y datos por los del respaldo.
# =====================================================================================================
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Correr como root:  sudo bash $0"; exit 1; }
AQUI="$(cd "$(dirname "$0")" && pwd)"
ENC="${1:-$AQUI/respaldo.enc}"
[ -f "$ENC" ] || { echo "No encuentro $ENC"; exit 1; }
if [ -f "$(dirname "$ENC")/respaldo.sha256" ]; then
  (cd "$(dirname "$ENC")" && sha256sum -c respaldo.sha256) || { echo "El archivo no llegó entero: copialo de nuevo"; exit 1; }
fi
command -v openssl >/dev/null || { apt-get update -q && apt-get -y -q install openssl; }
TMP=$(mktemp -d /root/.restaurar.XXXXXX); trap 'rm -rf "$TMP"' EXIT
echo "== Contraseña del respaldo:"
openssl enc -d -aes-256-cbc -pbkdf2 -iter 300000 -in "$ENC" -out "$TMP/r.tgz" || { echo "Contraseña incorrecta"; exit 1; }
mkdir "$TMP/r"; tar -C "$TMP/r" -xzf "$TMP/r.tgz"; rm -f "$TMP/r.tgz"
echo "   versión del código: $(cat "$TMP/r/codigo/VERSION" 2>/dev/null || echo '?')"

# ---------------------------------------------------------------------------------------------------
# MÁQUINA DE LA OFICINA (24/11/2026): la "robots" de Gaby (192.168.1.106) ya tiene el sistema instalado en
# /home/robot/robots (no en /home/robot/app como la nube). Ahí NO se reinstala nada del sistema operativo
# (ni firewall, ni Caddy, ni swap): se reemplazan código, claves, datos y usuarios de la web, guardando
# copia de lo anterior, y se apagan las corridas automáticas.
# ---------------------------------------------------------------------------------------------------
if [ -d /home/robot/robots/robots ] && [ ! -d /home/robot/app ]; then
  H=/home/robot; F=$(date +%Y%m%d_%H%M%S)
  echo "== Máquina de la oficina: se reemplazan código, claves, datos y usuarios (con copia de lo anterior)"
  if [ -e /tmp/robots_todo.lock ]; then exec 9</tmp/robots_todo.lock; else exec 9>/tmp/robots_todo.lock; fi
  flock -w 7200 9 || { echo "Hay una corrida muy larga: probá más tarde"; exit 1; }
  ANT="$H/antes_del_respaldo_$F"; mkdir -p "$ANT"
  crontab -u robot -l > "$ANT/crontab_robot.txt" 2>/dev/null || true
  crontab -u robot -r 2>/dev/null || true
  tar czf "$ANT/robots.tgz" -C "$H/robots" robots 2>/dev/null || true
  [ -d /opt/robots-web/robots_web ] && tar czf "$ANT/robots_web.tgz" -C /opt/robots-web robots_web
  [ -d /etc/robots ] && tar czf "$ANT/etc_robots.tgz" -C /etc robots
  [ -f /var/lib/robots-web/web.db ] && cp -a /var/lib/robots-web/web.db "$ANT/"
  [ -d /var/lib/robots ] && mv /var/lib/robots "/var/lib/robots.antes_$F"
  chown -R robot:robot "$ANT"; chmod 700 "$ANT"
  # código
  rm -rf "$H/robots/robots" && cp -r "$TMP/r/codigo/robots" "$H/robots/" && chown -R robot:robot "$H/robots/robots"
  sudo -u robot "$H/venv/bin/pip" install -q playwright pandas openpyxl cryptography pypdf >/dev/null 2>&1 || true
  if [ -d /opt/robots-web ]; then
    rm -rf /opt/robots-web/robots_web && cp -r "$TMP/r/codigo/robots_web" /opt/robots-web/
    chown -R root:root /opt/robots-web/robots_web; chmod -R go-w,a+rX /opt/robots-web/robots_web
    [ -x /opt/robots-web/venv/bin/pip ] && /opt/robots-web/venv/bin/pip install -q flask gunicorn openpyxl >/dev/null 2>&1 || true
  fi
  # claves y datos
  mkdir -p /etc/robots /var/lib/robots
  cp -a "$TMP/r/etc_robots/." /etc/robots/; chown -R robot:robot /etc/robots; chmod 700 /etc/robots; chmod 600 /etc/robots/*
  tar -C /var/lib/robots -xf "$TMP/r/var_lib_robots/datos.tar"
  install -o robot -g robot -m 600 "$TMP/r/var_lib_robots/almacen.db" /var/lib/robots/almacen.db
  G=robot; getent group robotsweb >/dev/null && G=robotsweb
  chown -R robot:$G /var/lib/robots; chmod 750 /var/lib/robots
  rm -f /var/lib/robots/publico/corrida_en_curso.json
  if id web >/dev/null 2>&1 && [ -d /var/lib/robots-web ]; then
    install -o web -g web -m 600 "$TMP/r/web/web.db" /var/lib/robots-web/web.db
    [ -f "$TMP/r/web/secreto.key" ] && install -o web -g web -m 600 "$TMP/r/web/secreto.key" /var/lib/robots-web/secreto.key
    SERV=$(systemctl list-units --type=service --all --no-legend 2>/dev/null | awk '{print $1}' | grep -i -E 'robots.?web|monitoreo' | head -1)
    [ -n "$SERV" ] && systemctl restart "$SERV" || true
  fi
  flock -u 9
  install -m 755 "$TMP/r/codigo/nube/corrida_urgente.sh" /root/corrida_urgente.sh
  echo "== Comprobando las claves"
  sudo -u robot bash -c "cd $H/robots && $H/venv/bin/python -m robots.almacen_claves listar | tail -5" \
    && echo "   claves: se pueden leer" || echo "   ERROR: no se pueden leer las claves"
  cat <<FIN_OF

LISTO (máquina de la oficina). Quedó con el código, las claves, los datos y los usuarios del respaldo.
Las corridas automáticas de esta máquina quedaron APAGADAS (para no pisarse con la nube).
Lo que había antes está en $ANT y /var/lib/robots.antes_$F

Corrida urgente de un cliente:
   sudo bash /root/corrida_urgente.sh 30XXXXXXXXX                    (todo)
   sudo bash /root/corrida_urgente.sh 30XXXXXXXXX situacion_fiscal   (solo deuda y planes)
Volver a la programación que tenía esta máquina:  sudo crontab -u robot $ANT/crontab_robot.txt
FIN_OF
  exit 0
fi

echo "== Instalando el sistema (sin corridas automáticas y sin pedir usuarios: vienen en el respaldo)"
# los usuarios de la web se ponen ANTES para que el instalador no pida un administrador nuevo
id web >/dev/null 2>&1 || useradd --system --home-dir /var/lib/robots-web --shell /usr/sbin/nologin web
mkdir -p /var/lib/robots-web
install -o web -g web -m 600 "$TMP/r/web/web.db" /var/lib/robots-web/web.db
[ -f "$TMP/r/web/secreto.key" ] && install -o web -g web -m 600 "$TMP/r/web/secreto.key" /var/lib/robots-web/secreto.key
chown web:web /var/lib/robots-web; chmod 700 /var/lib/robots-web
(cd / && SIN_TAREAS=1 SIN_ADMIN_SERVIDOR=1 bash "$TMP/r/codigo/nube/instalar_nube.sh" </dev/null)

echo "== Claves, datos y usuarios del respaldo"
if [ -e /tmp/robots_todo.lock ]; then exec 9</tmp/robots_todo.lock; else exec 9>/tmp/robots_todo.lock; fi; flock -w 3600 9
cp -a "$TMP/r/etc_robots/." /etc/robots/; chown -R robot:robot /etc/robots; chmod 700 /etc/robots; chmod 600 /etc/robots/*
tar -C /var/lib/robots -xf "$TMP/r/var_lib_robots/datos.tar"
install -o robot -g robot -m 600 "$TMP/r/var_lib_robots/almacen.db" /var/lib/robots/almacen.db
chown -R robot:robotsweb /var/lib/robots/datos /var/lib/robots/informes /var/lib/robots/publico
[ -f /var/lib/robots/ejecuciones.jsonl ] && chown robot:robotsweb /var/lib/robots/ejecuciones.jsonl
chmod -R g+rX,g-w,o-rwx /var/lib/robots/datos /var/lib/robots/informes /var/lib/robots/publico
find /var/lib/robots/datos /var/lib/robots/informes /var/lib/robots/publico -type d -exec chmod g+s {} +
[ -f /etc/robots/sobres_publica.pem ] && install -o robot -g robotsweb -m 644 /etc/robots/sobres_publica.pem /var/lib/robots/publico/sobres_publica.pem
rm -f /var/lib/robots/publico/corrida_en_curso.json
flock -u 9
cp "$TMP/r/crontab_robot.txt" /root/crontab_robot_de_la_nube.txt 2>/dev/null || true
systemctl restart robots-web 2>/dev/null || true

install -m 755 "$TMP/r/codigo/nube/corrida_urgente.sh" /root/corrida_urgente.sh
echo "== Comprobando las claves"
sudo -u robot bash -c 'cd ~/app && ~/venv/bin/python -m robots.almacen_claves listar | tail -5' \
  && echo "   claves: se pueden leer" || echo "   ERROR: no se pueden leer las claves (¿llave maestra?)"
cat <<FIN

LISTO. El sistema está instalado con los datos y las claves del respaldo, SIN corridas automáticas.

Corrida urgente de un cliente:
   sudo bash /root/corrida_urgente.sh 30XXXXXXXXX                    (todo: ARCA + ARBA + AGIP + informes)
   sudo bash /root/corrida_urgente.sh 30XXXXXXXXX situacion_fiscal   (solo deuda y planes)
   Los informes quedan en /var/lib/robots/informes y los datos en /var/lib/robots/datos/CUIT

Si este servidor pasa a ser el principal (la nube no vuelve):
   sudo -u robot bash /home/robot/programar_nube.sh
   NUNCA con la nube andando también: ARCA corta la sesión si el mismo usuario entra desde dos lugares.

Podés borrar la carpeta del respaldo si ya lo guardaste en otro lado.
FIN
