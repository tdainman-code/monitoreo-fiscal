#!/bin/bash
# =====================================================================================================
#  RESPALDO COMPLETO del Monitoreo fiscal, CON DATOS, para tener una copia que funcione en otro servidor
#  (pedido de Gaby, 24/11/2026: poder hacer una corrida urgente desde su servidor si la nube no está).
#
#  Se corre en el servidor de la NUBE, como root:
#      sudo bash /opt/monitoreo/repo/nube/respaldo_completo.sh
#
#  Arma /root/respaldo_monitoreo_AAAA-MM-DD/ con:
#      respaldo.enc          TODO cifrado con una contraseña que elegís en el momento (AES-256):
#                            código, llave maestra + almacén de claves, datos e informes de los clientes,
#                            usuarios de la web y la programación de las corridas
#      respaldo.sha256       para controlar que el archivo llegó entero
#      restaurar_respaldo.sh el instalador para el otro servidor (este archivo no tiene datos)
#      LEEME.txt             los pasos
#  Sin la contraseña el respaldo no sirve: guardala aparte (NO en el mismo lugar que el archivo).
#  No se sube a GitHub ni a ninguna nube: lo bajás vos directo del servidor (WinSCP / scp).
# =====================================================================================================
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Correr como root:  sudo bash $0"; exit 1; }
FECHA=$(date +%F)
DEST="/root/respaldo_monitoreo_$FECHA"
REPO=/opt/monitoreo/repo
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
mkdir -p "$DEST" "$TMP/m/codigo" "$TMP/m/etc_robots" "$TMP/m/var_lib_robots" "$TMP/m/web"

echo "== Esperando que no haya una corrida en curso (máximo 1 hora)..."
if [ -e /tmp/robots_todo.lock ]; then exec 9</tmp/robots_todo.lock; else exec 9>/tmp/robots_todo.lock; fi
flock -w 3600 9 || { echo "Hay una corrida muy larga: probá más tarde"; exit 1; }

echo "== Código (versión instalada)"
if [ -d "$REPO/.git" ]; then
  git -C "$REPO" archive --format=tar HEAD | tar -C "$TMP/m/codigo" -xf -
  git -C "$REPO" rev-parse --short HEAD > "$TMP/m/codigo/VERSION"
else
  cp -a /home/robot/app/robots "$TMP/m/codigo/"; cp -a /opt/robots-web/robots_web "$TMP/m/codigo/"
  cp -a "$(cd "$(dirname "$0")" && pwd)" "$TMP/m/codigo/nube"
fi
find "$TMP/m/codigo" -name '__pycache__' -prune -exec rm -rf {} +

echo "== Claves: llave maestra, llaves de los sobres y almacén (copia consistente)"
cp -a /etc/robots/. "$TMP/m/etc_robots/"
python3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close()" \
  /var/lib/robots/almacen.db "$TMP/m/var_lib_robots/almacen.db"

echo "== Datos, informes y registro de corridas"
tar -C /var/lib/robots -cf "$TMP/m/var_lib_robots/datos.tar" --exclude='./almacen.db' --exclude='./almacen.db-*' .

echo "== Usuarios de la web"
python3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close()" \
  /var/lib/robots-web/web.db "$TMP/m/web/web.db"
cp /var/lib/robots-web/secreto.key "$TMP/m/web/" 2>/dev/null || true
crontab -u robot -l > "$TMP/m/crontab_robot.txt" 2>/dev/null || true
flock -u 9

echo "== Empaquetando"
tar -C "$TMP/m" -czf "$TMP/respaldo.tgz" .
du -h "$TMP/respaldo.tgz" | awk '{print "   tamaño sin cifrar: "$1}'
echo
echo "== Elegí una contraseña para el respaldo (te la pide dos veces; se usa para restaurar)."
echo "   Guardala aparte: sin ella el archivo no se puede abrir."
openssl enc -aes-256-cbc -pbkdf2 -iter 300000 -salt -in "$TMP/respaldo.tgz" -out "$DEST/respaldo.enc"
(cd "$DEST" && sha256sum respaldo.enc > respaldo.sha256)
SRC="$TMP/m/codigo/nube/restaurar_respaldo.sh"
[ -f "$SRC" ] || SRC="$(cd "$(dirname "$0")" && pwd)/restaurar_respaldo.sh"
install -m 755 "$SRC" "$DEST/restaurar_respaldo.sh"
cat > "$DEST/LEEME.txt" <<LEEME
RESPALDO COMPLETO DEL MONITOREO FISCAL — $FECHA (versión $(cat "$TMP/m/codigo/VERSION" 2>/dev/null || echo '?'))

Contiene, CIFRADO con tu contraseña: código, claves (llave maestra + almacén), datos e informes de los clientes,
usuarios de la web. Sin la contraseña no sirve. No lo subas a ningún lado ni lo mandes por mail.

INSTALARLO EN TU SERVIDOR (Ubuntu 24.04, recién instalado o dedicado a esto, 2 GB de RAM o más):
  1. Copiá esta carpeta entera al servidor, por ejemplo a /root/respaldo_monitoreo_$FECHA
  2. sudo bash /root/respaldo_monitoreo_$FECHA/restaurar_respaldo.sh
     (te pide la contraseña del respaldo; tarda unos 15 minutos la primera vez)
  3. Queda instalado SIN corridas automáticas, para no pisarse con la nube.

CORRIDA URGENTE DE UN CLIENTE:
  sudo bash /root/corrida_urgente.sh 30XXXXXXXXX           (todo: ARCA + ARBA + AGIP + informes)
  sudo bash /root/corrida_urgente.sh 30XXXXXXXXX situacion_fiscal

SI LA NUBE NO VA A VOLVER y este servidor pasa a ser el principal:
  sudo -u robot bash /home/robot/programar_nube.sh          (activa las corridas automáticas)
  Nunca las dos a la vez: ARCA corta la sesión si el mismo usuario entra desde dos lugares, y los avisos
  por mail saldrían dos veces.
LEEME
chmod 700 "$DEST"; chmod 600 "$DEST/respaldo.enc" "$DEST/respaldo.sha256" "$DEST/LEEME.txt"
echo
echo "LISTO:  $DEST"
ls -la "$DEST"
echo
echo "Bajalo a tu compu con WinSCP (o: scp -r root@$(hostname -I | awk '{print $1}'):$DEST .)"
echo "Cuando lo tengas guardado en tu servidor, borralo de acá:  rm -rf $DEST"
