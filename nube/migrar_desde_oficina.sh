#!/bin/bash
# =====================================================================================================
#  Paso final de la mudanza: se corre en la máquina "robots" de la OFICINA (usuario robot).
#  Empaqueta claves cifradas + llaves + datos + usuarios de la web, lo CIFRA con una contraseña que elegís en
#  el momento y lo manda directo al servidor nuevo (no pasa por ninguna otra compu ni por la nube de nadie).
#
#  Uso:   bash migrar_desde_oficina.sh  IP_DEL_SERVIDOR_NUEVO
#  Después, en el servidor nuevo:   sudo bash /root/restaurar_en_nube.sh /root/mudanza_robots.enc
#
#  Antes de correrlo: que no haya una corrida en curso (el script espera el candado igual).
#  La llave maestra y el almacén viajan JUNTOS pero cifrados con tu contraseña: sin ella el archivo no sirve.
# =====================================================================================================
set -euo pipefail
DEST="${1:?Uso: bash migrar_desde_oficina.sh IP_DEL_SERVIDOR_NUEVO}"
[ "$(id -un)" = "robot" ] || { echo "Correr como el usuario robot"; exit 1; }
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
echo "== Esperando que no haya robots corriendo..."
exec 9>/tmp/robots_todo.lock; flock -w 3600 9
echo "== Copiando base de claves (copia consistente)"
mkdir -p "$TMP/m/etc_robots" "$TMP/m/var_lib_robots" "$TMP/m/web"
python3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close()" \
  /var/lib/robots/almacen.db "$TMP/m/var_lib_robots/almacen.db"
cp -a /etc/robots/. "$TMP/m/etc_robots/"
tar -C /var/lib/robots -cf "$TMP/m/var_lib_robots/datos.tar" --exclude='./almacen.db' --exclude='./almacen.db-*' .
echo "== Usuarios de la web (pide la clave de sudo)"
sudo python3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close()" \
  /var/lib/robots-web/web.db "$TMP/m/web/web.db"
sudo cp /var/lib/robots-web/secreto.key "$TMP/m/web/" 2>/dev/null || true
sudo chown -R robot:robot "$TMP/m/web"
flock -u 9
tar -C "$TMP/m" -czf "$TMP/mudanza.tgz" .
echo "== Elegí una contraseña para cifrar el paquete (se te pide de nuevo al restaurar):"
openssl enc -aes-256-cbc -pbkdf2 -iter 300000 -salt -in "$TMP/mudanza.tgz" -out "$TMP/mudanza_robots.enc"
sha256sum "$TMP/mudanza_robots.enc" | tee "$TMP/mudanza_robots.sha256"
echo "== Enviando a root@$DEST (pide la contraseña o usa la llave SSH del servidor nuevo)"
scp "$TMP/mudanza_robots.enc" "$TMP/mudanza_robots.sha256" "root@$DEST:/root/"
echo "LISTO. En el servidor nuevo:  sudo bash /root/restaurar_en_nube.sh /root/mudanza_robots.enc"
echo "No apagues todavía las corridas de la oficina: hacelo cuando la nube haya corrido bien una noche."
