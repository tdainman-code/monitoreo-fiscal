#!/bin/bash
# =====================================================================================================
#  Actualización automática desde GitHub (la corre root cada 5 minutos con un temporizador de systemd).
#
#  Flujo para cambiar el robot:  pedirle el cambio a Claude Code sobre el repositorio de GitHub -> queda en la rama
#  "main" -> este script lo detecta, CORRE LAS PRUEBAS sobre el código nuevo y:
#     - si pasan: lo instala (robots + web), reinicia la web y anota la versión;
#     - si fallan: NO lo instala, sigue la versión anterior y deja el motivo en la pantalla Sistema de la web.
#  Nunca se corta una corrida de robots a la mitad: espera el candado de las corridas.
#
#  A mano:  sudo bash /opt/monitoreo/repo/nube/actualizar_desde_github.sh --ya       (sin esperar los 5 minutos)
#           sudo bash /opt/monitoreo/repo/nube/actualizar_desde_github.sh --volver   (vuelve a la versión anterior)
# =====================================================================================================
set -uo pipefail
REPO=/opt/monitoreo/repo
RAMA=main
PUB=/var/lib/robots/publico
LOG=/var/log/monitoreo-actualizacion.log
ANT=/opt/monitoreo/anterior
exec 8>/tmp/monitoreo_actualizacion.lock; flock -n 8 || exit 0
[ -d "$REPO/.git" ] || exit 0
cd "$REPO" || exit 1

# Dirección alternativa (19/11/2026): algunas redes de celular no resuelven *.sslip.io (ERR_NAME_NOT_RESOLVED).
# Se suma <ip>.nip.io, que apunta al mismo servidor; Caddy saca su candado solo. Idempotente: se hace una vez.
CF=/etc/caddy/Caddyfile
if [ -f "$CF" ] && ! grep -q 'nip\.io' "$CF"; then
  SS=$(grep -oE '^[0-9-]+\.sslip\.io' "$CF" | head -1)
  if [ -n "$SS" ]; then
    cp -a "$CF" "$CF.antes_nipio"
    sed -i "s/^$SS {/$SS, ${SS%.sslip.io}.nip.io {/" "$CF"
    if caddy validate --config "$CF" --adapter caddyfile >/dev/null 2>&1; then
      systemctl reload caddy && echo "$(date) agregada la dirección ${SS%.sslip.io}.nip.io" >> "$LOG"
    else
      cp -a "$CF.antes_nipio" "$CF"; echo "$(date) no se pudo agregar nip.io (Caddyfile restaurado)" >> "$LOG"
    fi
  fi
fi

anotar() {   # estado legible para la web (pantalla Sistema, solo administradores)
  python3 - "$@" <<'PY'
import json, sys, os, datetime as dt
pub = "/var/lib/robots/publico"; ruta = os.path.join(pub, "actualizaciones.json")
try: lista = json.load(open(ruta))
except Exception: lista = []
nuevo = {"fecha": dt.datetime.now().isoformat(timespec="seconds"), "estado": sys.argv[1],
         "commit": sys.argv[2], "mensaje": sys.argv[3], "detalle": sys.argv[4][-3000:]}
if lista and lista[0].get("estado", "").startswith("esperando") and lista[0].get("commit") == sys.argv[2]:
    lista[0] = nuevo          # la espera de esta misma versión se reemplaza (no se repite cada 5 minutos)
else:
    lista.insert(0, nuevo)
json.dump(lista[:40], open(ruta + ".tmp", "w"), ensure_ascii=False, indent=1); os.replace(ruta + ".tmp", ruta)
if sys.argv[1] == "instalada":
    json.dump({"commit": sys.argv[2], "mensaje": sys.argv[3], "fecha": lista[0]["fecha"]},
              open(os.path.join(pub, "version.json"), "w"), ensure_ascii=False)
PY
  chown robot:robotsweb "$PUB"/actualizaciones.json "$PUB"/version.json 2>/dev/null; chmod 640 "$PUB"/actualizaciones.json "$PUB"/version.json 2>/dev/null
}

instalar_desde() {   # $1 = carpeta con robots/ y robots_web/
  # /tmp tiene protected_regular: root no puede ABRIR PARA ESCRIBIR un archivo de otro usuario en /tmp.
  # El candado lo crea el usuario robot; se abre solo para lectura (flock funciona igual).
  if [ -e /tmp/robots_todo.lock ]; then exec 9</tmp/robots_todo.lock; else exec 9>/tmp/robots_todo.lock; fi
  if [ "${SOLO_WEB:-no}" = "si" ] && ! flock -n 9; then
    # 21/11/2026: el cambio no toca los robots (solo la web, pruebas o textos): la web se instala sin esperar la corrida
    rm -rf "$ANT"; mkdir -p "$ANT"
    cp -a /home/robot/app/robots "$ANT/robots"; cp -a /opt/robots-web/robots_web "$ANT/robots_web"
    rsync -a --delete --exclude '__pycache__' "$1/robots_web/" /opt/robots-web/robots_web/
    chown -R root:root /opt/robots-web; chmod -R go-w /opt/robots-web
    systemctl restart robots-web
    return 0
  fi
  if ! flock -n 9; then       # 21/11/2026: que la pantalla Sistema muestre que la versión espera a la corrida en curso
    anotar "esperando: hay una corrida de robots en curso; se instala apenas termine" "${CORTO:-}" "${MSJ:-}" ""
    flock -w 7200 9 || { echo "corrida muy larga, se reintenta"; return 1; }
  fi
  rm -rf "$ANT"; mkdir -p "$ANT"
  cp -a /home/robot/app/robots "$ANT/robots"; cp -a /opt/robots-web/robots_web "$ANT/robots_web"
  rsync -a --delete --exclude '__pycache__' "$1/robots/" /home/robot/app/robots/
  rsync -a --delete --exclude '__pycache__' "$1/robots_web/" /opt/robots-web/robots_web/
  chown -R robot:robot /home/robot/app; chown -R root:root /opt/robots-web; chmod -R go-w /opt/robots-web
  [ -f "$1/nube/programar_nube.sh" ] && install -o robot -g robot -m 755 "$1/nube/programar_nube.sh" /home/robot/programar_nube.sh \
      && sudo -u robot bash /home/robot/programar_nube.sh >/dev/null
  # 24/11/2026: si openpyxl no se pudo instalar, que quede anotado (antes fallaba en silencio y la planilla no subía)
  /opt/robots-web/venv/bin/python -c "import openpyxl" 2>/dev/null || /opt/robots-web/venv/bin/pip install -q openpyxl \
      || /opt/robots-web/venv/bin/pip install -q --no-cache-dir openpyxl \
      || echo "$(date) ERROR: no se pudo instalar openpyxl en la web" >> "$LOG"
  rm -f /etc/cron.d/monitoreo-revisiones      # 25/11/2026: el reporte por mail de revisiones no va (Tomás)
  systemctl restart robots-web
  flock -u 9
}

if [ "${1:-}" = "--volver" ]; then
  [ -d "$ANT/robots" ] || { echo "No hay versión anterior guardada"; exit 1; }
  instalar_desde "$ANT" && anotar "vuelta atrás" "$(git rev-parse --short HEAD)" "se volvió a la versión anterior" ""
  echo "Listo: versión anterior instalada"; exit 0
fi

git fetch -q origin "$RAMA" 2>>"$LOG" || { echo "$(date) no se pudo leer GitHub" >> "$LOG"; exit 0; }
NUEVO=$(git rev-parse "origin/$RAMA"); ACTUAL=$(cat /opt/monitoreo/instalado 2>/dev/null || echo ninguno)
[ "$NUEVO" = "$ACTUAL" ] && [ "${1:-}" != "--ya" ] && exit 0
[ "$NUEVO" = "$(cat /opt/monitoreo/rechazado 2>/dev/null)" ] && [ "${1:-}" != "--ya" ] && exit 0
MSJ=$(git log -1 --format=%s "$NUEVO"); CORTO=$(git rev-parse --short "$NUEVO")
echo "$(date) nueva versión $CORTO: $MSJ" >> "$LOG"

PRUEBA=$(mktemp -d /tmp/monitoreo_prueba.XXXX); chmod 755 "$PRUEBA"
git --work-tree="$PRUEBA" checkout -q "$NUEVO" -- . && chown -R robot:robot "$PRUEBA"
SALIDA=$(cd "$PRUEBA" && timeout 1200 sudo -u robot env PYTHONPATH="$PRUEBA" HOME=/home/robot \
         /home/robot/venv/bin/python pruebas/test_web_radar.py 2>&1; echo "CODIGO=$?")
SALIDA2=$(cd "$PRUEBA" && timeout 900 sudo -u robot env PYTHONPATH="$PRUEBA" HOME=/home/robot \
         /home/robot/venv/bin/python robots/pruebas/test_agip_simulado.py 2>&1 && \
         /home/robot/venv/bin/python robots/pruebas/test_conciliacion_compras.py 2>&1 && \
         /home/robot/venv/bin/python robots/pruebas/test_ccma.py 2>&1 && \
         /home/robot/venv/bin/python robots/pruebas/test_sct_historico.py 2>&1 && \
         /home/robot/venv/bin/python robots/pruebas/test_mis_retenciones.py 2>&1 && \
         /home/robot/venv/bin/python robots/pruebas/test_vep_deuda.py 2>&1 && \
         /home/robot/venv/bin/python robots/pruebas/test_arba_retenciones.py 2>&1 && \
         /home/robot/venv/bin/python robots/pruebas/test_sistema_registral.py 2>&1 && \
         /home/robot/venv/bin/python robots/pruebas/test_corridas.py 2>&1 && \
         /home/robot/venv/bin/python robots/pruebas/test_resumen_mensual.py 2>&1 && \
         /home/robot/venv/bin/python robots/pruebas/test_bajas.py 2>&1 && \
         /home/robot/venv/bin/python pruebas/test_asientos.py 2>&1; echo "CODIGO=$?")
# solo cambia la web (no robots/ ni nube/): se puede instalar aunque haya una corrida de robots en curso
SOLO_WEB=no
if [ "$ACTUAL" != "ninguno" ] && git cat-file -e "$ACTUAL^{commit}" 2>/dev/null; then
  OTROS=$(git diff --name-only "$ACTUAL" "$NUEVO" | grep -vE '^(robots_web/|pruebas/|docs/)|\.md$' || true)
  [ -z "$OTROS" ] && SOLO_WEB=si
fi
if echo "$SALIDA" | grep -q "CODIGO=0" && echo "$SALIDA2" | grep -q "CODIGO=0"; then
  if instalar_desde "$PRUEBA"; then
    echo "$NUEVO" > /opt/monitoreo/instalado; git checkout -q --detach "$NUEVO"
    anotar "instalada" "$CORTO" "$MSJ" "$(echo "$SALIDA" | tail -3)"
    echo "$(date) instalada $CORTO" >> "$LOG"
  fi
else
  echo "$NUEVO" > /opt/monitoreo/rechazado
  anotar "rechazada: fallaron las pruebas" "$CORTO" "$MSJ" "$(echo "$SALIDA" | grep -E '✘|Error|Traceback' | head -20; echo "$SALIDA2" | grep -E '✘|Error' | head -10)"
  echo "$(date) RECHAZADA $CORTO (pruebas)" >> "$LOG"
fi
rm -rf "$PRUEBA"
