#!/bin/bash
# Tareas automáticas del usuario robot en el servidor en la nube (las instala instalar_nube.sh; se puede volver a correr).
#   lunes a viernes 20:00 corrida COMPLETA del grupo del día (cada cliente tiene un día fijo: ~1/5 de la cartera
#                         por día; deuda, planes, DFE, Libro IVA, F.931, SIFERE, fiscalizaciones, ARBA y AGIP) hasta las 7:00
#   sábados 9:00          repechaje: los que dieron error en la semana (cortes, portal caído)
#   cada 3 minutos        claves cargadas desde la web (bandeja de sobres)
#   cada minuto           corridas pedidas desde la web
# Todas usan el mismo candado (/tmp/robots_todo.lock): nunca corren dos robots a la vez.
# La zona horaria del servidor es la de Argentina (la pone el instalador).
# xvfb-run: pantalla virtual (AGIP no deja entrar a navegadores ocultos).
set -u
PY="$HOME/venv/bin/python"
[ -x "$PY" ] || { echo "No encuentro $PY"; exit 1; }
mkdir -p "$HOME/logs"
[ "$(date +%Z)" = "-03" ] || echo "AVISO: la zona horaria no es la de Argentina ($(date +%Z)); revisar con: timedatectl"
TAG="# robots-nube"
CMD="cd \$HOME/app && flock -w 172800 /tmp/robots_todo.lock xvfb-run -a $PY -m robots.correr todo --todos"
NUEVAS=$(cat <<EOT
$TAG corrida completa del grupo del dia (lun-vie 20:00, no arranca clientes nuevos despues de 11 h)
0 20 * * 1-5 $CMD --modo completo --grupo-del-dia --horas 11 >> \$HOME/logs/grupo_\$(date +\%F).log 2>&1 $TAG
$TAG repechaje de la semana (sabado 9:00)
0 9 * * 6 $CMD --modo completo --solo-fallidos --horas 10 >> \$HOME/logs/repechaje_\$(date +\%F).log 2>&1 $TAG
$TAG claves cargadas desde la web
*/3 * * * * cd \$HOME/app && $PY -m robots.almacen_claves procesar-bandeja >> \$HOME/logs/bandeja.log 2>&1 $TAG
$TAG corridas pedidas desde la web
* * * * * cd \$HOME/app && flock -n /tmp/robots_pedidos.lock xvfb-run -a $PY -m robots.pedidos >> \$HOME/logs/pedidos.log 2>&1 $TAG
$TAG limpieza de logs de mas de 60 dias
30 5 * * 0 find \$HOME/logs -name '*.log' -mtime +60 -delete $TAG
EOT
)
ACTUAL=$(crontab -l 2>/dev/null || true)
[ -n "$ACTUAL" ] && echo "$ACTUAL" > "$HOME/crontab_antes_$(date +%Y%m%d_%H%M%S).txt"
{ echo "$ACTUAL" | grep -v "$TAG"; echo "$NUEVAS"; } | sed '/^$/d' | crontab - || { echo "ERROR al instalar el crontab"; exit 1; }
echo "Tareas instaladas:"; crontab -l | grep -v '^#'
