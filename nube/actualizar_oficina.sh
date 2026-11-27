#!/bin/bash
# =====================================================================================================
#  Actualiza el robot de la OFICINA (máquina "robots", banco de pruebas de Gaby) con la misma versión que corre
#  en la nube. No toca la llave maestra, las claves, los datos ni los usuarios de la web.
#
#  1) Subir a /home/robot con WinSCP:  monitoreo_oficina_<versión>.tgz  y  actualizar_oficina.sh
#  2) En la consola de la máquina robots:   sudo bash actualizar_oficina.sh
#  Para volver atrás: el script imprime el comando al final (deja copia de lo anterior).
#
#  Qué hace: espera a que no haya una corrida en curso, guarda copia de lo instalado, prueba el código nuevo
#  (sintaxis + pruebas rápidas sin internet) y recién ahí reemplaza robots (~/robots/robots) y web
#  (/opt/robots-web/robots_web), y reinicia la web.
# =====================================================================================================
set -u
[ "$(id -u)" = "0" ] || { echo "Correlo con sudo:  sudo bash actualizar_oficina.sh"; exit 1; }
AQUI="$(cd "$(dirname "$0")" && pwd)"
U=robot; H=/home/$U
P=$(ls -t "$AQUI"/monitoreo_oficina_*.tgz 2>/dev/null | head -1)
[ -n "$P" ] || { echo "Falta monitoreo_oficina_<versión>.tgz en $AQUI (subilo con WinSCP)"; exit 1; }
[ -d "$H/robots/robots" ] || { echo "No existe $H/robots/robots"; exit 1; }
echo "== Paquete: $(basename "$P")"

TMP=$(mktemp -d); chmod 755 "$TMP"; trap 'rm -rf "$TMP"' EXIT
tar xzf "$P" -C "$TMP" || { echo "ERROR al descomprimir: no se cambió nada"; exit 1; }
chown -R $U:$U "$TMP"
cat "$TMP/VERSION.txt" 2>/dev/null

echo "== Dependencias del robot (pypdf y flask para las pruebas; si ya están, no hace nada)"
sudo -u $U "$H/venv/bin/pip" install -q pypdf flask >/dev/null 2>&1 || echo "   (no se pudieron instalar: sigo igual)"

echo "== Probando el código nuevo (no toca nada todavía)"
sudo -u $U "$H/venv/bin/python" -m py_compile "$TMP"/robots/*.py || { echo "ERROR de sintaxis en robots: no se cambió nada"; exit 1; }
WEBPY=/opt/robots-web/venv/bin/python; [ -x "$WEBPY" ] || WEBPY="$H/venv/bin/python"
"$WEBPY" -m py_compile "$TMP"/robots_web/*.py || { echo "ERROR de sintaxis en la web: no se cambió nada"; exit 1; }
for t in robots/pruebas/test_conciliacion_compras.py robots/pruebas/test_ccma.py robots/pruebas/test_sct_historico.py robots/pruebas/test_mis_retenciones.py robots/pruebas/test_vep_deuda.py robots/pruebas/test_vep_iva90.py \
         pruebas/test_web_radar.py pruebas/test_asientos.py; do
  [ -f "$TMP/$t" ] || continue
  if (cd "$TMP" && sudo -u $U env PYTHONPATH="$TMP" HOME=$H timeout 900 "$H/venv/bin/python" "$t" > "$TMP/prueba.log" 2>&1); then
    echo "   OK  $t"
  else
    echo "   FALLÓ $t  (no se cambió nada). Últimas líneas:"; tail -15 "$TMP/prueba.log"; exit 1
  fi
done

echo "== Esperando que termine la corrida en curso (si hay)..."
if [ -e /tmp/robots_todo.lock ]; then exec 9</tmp/robots_todo.lock; else exec 9>/tmp/robots_todo.lock; fi
flock -w 7200 9 || { echo "Hay una corrida muy larga: probá más tarde"; exit 1; }

F=$(date +%Y%m%d_%H%M%S)
tar czf "$H/robots_antes_$F.tgz" -C "$H/robots" robots || { echo "No se pudo copiar lo anterior: no se cambió nada"; exit 1; }
[ -d /opt/robots-web/robots_web ] && tar czf "$H/robots_web_antes_$F.tgz" -C /opt/robots-web robots_web
chown $U:$U "$H"/robots_*antes_$F.tgz
echo "== Copia de lo anterior: $H/robots_antes_$F.tgz y $H/robots_web_antes_$F.tgz"

rm -rf "$H/robots/robots" && cp -r "$TMP/robots" "$H/robots/" && chown -R $U:$U "$H/robots/robots"
find "$H/robots/robots" -name __pycache__ -prune -exec rm -rf {} +
if [ -d /opt/robots-web ]; then
  [ -x /opt/robots-web/venv/bin/pip ] && { /opt/robots-web/venv/bin/python -c "import openpyxl" 2>/dev/null || /opt/robots-web/venv/bin/pip install -q openpyxl; }
  rm -rf /opt/robots-web/robots_web && cp -r "$TMP/robots_web" /opt/robots-web/
  find /opt/robots-web/robots_web -name __pycache__ -prune -exec rm -rf {} +
  chown -R root:root /opt/robots-web/robots_web; chmod -R go-w,a+rX /opt/robots-web/robots_web
  SERV=$(systemctl list-units --type=service --all --no-legend 2>/dev/null | awk '{print $1}' | grep -i -E 'robots.?web|monitoreo' | head -1)
  [ -n "$SERV" ] && systemctl restart "$SERV" && sleep 2 && echo "== Web reiniciada ($SERV: $(systemctl is-active "$SERV"))"
fi
flock -u 9
echo
echo "LISTO: robot de la oficina actualizado."
echo "Para volver atrás:"
echo "  sudo tar xzf $H/robots_antes_$F.tgz -C $H/robots && sudo tar xzf $H/robots_web_antes_$F.tgz -C /opt/robots-web && sudo systemctl restart ${SERV:-robots-web}"
