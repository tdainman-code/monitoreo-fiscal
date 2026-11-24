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
