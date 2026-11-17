#!/bin/bash
# Restaura en el servidor nuevo lo que mandó migrar_desde_oficina.sh (correr como root, DESPUÉS de instalar_nube.sh).
#   sudo bash restaurar_en_nube.sh /root/mudanza_robots.enc
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Correr como root"; exit 1; }
ENC="${1:?Uso: restaurar_en_nube.sh /root/mudanza_robots.enc}"
[ -f "${ENC%.enc}.sha256" ] && (cd "$(dirname "$ENC")" && sha256sum -c "$(basename "${ENC%.enc}.sha256")")
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
echo "== Contraseña del paquete:"
openssl enc -d -aes-256-cbc -pbkdf2 -iter 300000 -in "$ENC" -out "$TMP/m.tgz"
mkdir "$TMP/m"; tar -C "$TMP/m" -xzf "$TMP/m.tgz"
if [ -e /tmp/robots_todo.lock ]; then exec 9</tmp/robots_todo.lock; else exec 9>/tmp/robots_todo.lock; fi; flock -w 3600 9
if [ -f /etc/robots/llave_maestra.key ] && ! cmp -s /etc/robots/llave_maestra.key "$TMP/m/etc_robots/llave_maestra.key"; then
  mv /etc/robots "/etc/robots.antes.$(date +%Y%m%d%H%M%S)"; mkdir /etc/robots
fi
cp -a "$TMP/m/etc_robots/." /etc/robots/; chown -R robot:robot /etc/robots; chmod 700 /etc/robots; chmod 600 /etc/robots/*
tar -C /var/lib/robots -xf "$TMP/m/var_lib_robots/datos.tar"
install -o robot -g robot -m 600 "$TMP/m/var_lib_robots/almacen.db" /var/lib/robots/almacen.db
chown -R robot:robotsweb /var/lib/robots/datos /var/lib/robots/informes /var/lib/robots/publico /var/lib/robots/ejecuciones.jsonl
chmod -R g+rX,g-w,o-rwx /var/lib/robots/datos /var/lib/robots/informes /var/lib/robots/publico
find /var/lib/robots/datos /var/lib/robots/informes /var/lib/robots/publico -type d -exec chmod g+s {} +
[ -f /etc/robots/sobres_publica.pem ] && install -o robot -g robotsweb -m 644 /etc/robots/sobres_publica.pem /var/lib/robots/publico/sobres_publica.pem
install -o web -g web -m 600 "$TMP/m/web/web.db" /var/lib/robots-web/web.db
[ -f "$TMP/m/web/secreto.key" ] && install -o web -g web -m 600 "$TMP/m/web/secreto.key" /var/lib/robots-web/secreto.key
flock -u 9
sudo -u robot bash -c 'cd ~/app && ~/venv/bin/python -m robots.almacen_claves listar | tail -5 && ~/venv/bin/python -m robots.publicar'
systemctl restart robots-web
shred -u "$ENC" 2>/dev/null || rm -f "$ENC"
echo "LISTO: claves, datos y usuarios restaurados. El paquete cifrado se borró."
echo "Probá un cliente:  sudo -u robot bash -c 'cd ~/app && ~/venv/bin/python -m robots.correr situacion_fiscal --cuit 20XXXXXXXXX'"
