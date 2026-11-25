#!/bin/bash
# Tareas automáticas del usuario robot en el servidor en la nube (las instala instalar_nube.sh; se puede volver a correr).
#   (esquema del 20/11/2026)
#   lunes a viernes 20:00 corrida DIARIA liviana de TODOS: Cuentas Tributarias (deuda vencida, DDJJ sin presentar,
#                         vencimientos) + e-ventanilla de ARCA. Primero los urgentes; no arranca clientes nuevos
#                         después de las 6:00. Si ARCA pide captcha o rechaza seguido, frena esa noche.
#   sábado y domingo 6:00 corrida COMPLETA: cada cliente tiene fijo el sábado o el domingo (mitad y mitad;
#                         monotributistas semana por medio): deuda, planes, DFE, Libro IVA, F.931, SIFERE,
#                         fiscalizaciones, ARBA, AGIP e informes
#   domingo 20:00         repechaje: los que dieron error en la semana (cortes, portal caído), hasta las 5:00
#   cada 3 minutos        claves cargadas desde la web (bandeja de sobres); si hay una corrida en curso se guardan sin
#                         verificar (las prueba la corrida misma) para no tener dos navegadores compitiendo (25/11/2026)
#   corridas automáticas: hasta 6 clientes a la vez, según memoria y procesadores (2 GB: de a uno; 8 GB: 5; 16 GB: 6)
#   cada minuto           corridas pedidas desde la web
#   cada 30 minutos       avisos de cuotas impagas (4 días: al encargado; 15 días: al cliente) y envío de mails
# Todas usan el mismo candado (/tmp/robots_todo.lock): nunca corren dos robots a la vez.
# La zona horaria del servidor es la de Argentina (la pone el instalador).
# xvfb-run: pantalla virtual (AGIP no deja entrar a navegadores ocultos).
set -u
PY="$HOME/venv/bin/python"
[ -x "$PY" ] || { echo "No encuentro $PY"; exit 1; }
mkdir -p "$HOME/logs"
[ "$(date +%Z)" = "-03" ] || echo "AVISO: la zona horaria no es la de Argentina ($(date +%Z)); revisar con: timedatectl"
TAG="# robots-nube"
CMD="cd \$HOME/app && flock -w 172800 /tmp/robots_todo.lock xvfb-run -a $PY -m robots.correr todo --todos --trabajadores 6"
NUEVAS=$(cat <<EOT
$TAG corrida diaria liviana de todos los clientes (lun-vie 20:00, no arranca clientes nuevos despues de las 6:00)
0 20 * * 1-5 $CMD --modo diaria --urgentes-primero --horas 10 --hasta 06:00 >> \$HOME/logs/diaria_\$(date +\%F).log 2>&1 $TAG
$TAG corrida completa de fin de semana (sabado y domingo 6:00; cada cliente tiene su dia)
0 6 * * 6 $CMD --modo completo --fin-de-semana --horas 14 >> \$HOME/logs/finde_\$(date +\%F).log 2>&1 $TAG
0 6 * * 0 $CMD --modo completo --fin-de-semana --horas 13 >> \$HOME/logs/finde_\$(date +\%F).log 2>&1 $TAG
$TAG repechaje de la semana (domingo 20:00)
0 20 * * 0 $CMD --modo completo --solo-fallidos --horas 9 --hasta 05:00 >> \$HOME/logs/repechaje_\$(date +\%F).log 2>&1 $TAG
$TAG claves cargadas desde la web
*/3 * * * * cd \$HOME/app && if flock -n /tmp/robots_todo.lock true; then $PY -m robots.almacen_claves procesar-bandeja; else $PY -m robots.almacen_claves procesar-bandeja --sin-verificar; fi >> \$HOME/logs/bandeja.log 2>&1 $TAG
$TAG corridas pedidas desde la web
* * * * * cd \$HOME/app && flock -n /tmp/robots_pedidos.lock xvfb-run -a $PY -m robots.pedidos >> \$HOME/logs/pedidos.log 2>&1 $TAG
$TAG avisos de cuotas impagas (4 y 15 dias) y cola de mails
*/30 * * * * cd \$HOME/app && $PY -m robots.avisos evaluar >> \$HOME/logs/avisos.log 2>&1 $TAG
$TAG limpieza de logs de mas de 60 dias
30 5 * * 0 find \$HOME/logs -name '*.log' -mtime +60 -delete $TAG
EOT
)
ACTUAL=$(crontab -l 2>/dev/null || true)
[ -n "$ACTUAL" ] && echo "$ACTUAL" > "$HOME/crontab_antes_$(date +%Y%m%d_%H%M%S).txt"
{ echo "$ACTUAL" | grep -v "$TAG"; echo "$NUEVAS"; } | sed '/^$/d' | crontab - || { echo "ERROR al instalar el crontab"; exit 1; }
echo "Tareas instaladas:"; crontab -l | grep -v '^#'
