#!/bin/bash
# Corrida urgente de UN cliente (servidor de respaldo o la nube). Como root:
#     sudo bash /root/corrida_urgente.sh CUIT [robot]
# robot: todo (por defecto), situacion_fiscal, libro_iva, mis_comprobantes, sct_historico, mis_retenciones, agip, arba_dfe...
# Espera si hay otra corrida en curso (mismo candado que las automáticas).
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Correr como root:  sudo bash $0 CUIT [robot]"; exit 1; }
CUIT="$(echo "${1:?Uso: sudo bash corrida_urgente.sh CUIT [robot]}" | tr -cd '0-9')"
ROBOT="${2:-todo}"
[ ${#CUIT} -eq 11 ] || { echo "El CUIT tiene que tener 11 números"; exit 1; }
[[ "$ROBOT" =~ ^[a-z_]+$ ]] || { echo "Robot inválido"; exit 1; }
echo "== $ROBOT para $CUIT (si hay otra corrida en curso, espera)"
sudo -u robot bash -c "cd ~/app && flock -w 7200 /tmp/robots_todo.lock xvfb-run -a ~/venv/bin/python -m robots.correr $ROBOT --cuit $CUIT" \
  | tee "/root/corrida_urgente_${CUIT}_$(date +%Y%m%d_%H%M).log"
echo
echo "Datos:     /var/lib/robots/datos/$CUIT"
echo "Informes:  ls -t /var/lib/robots/informes/*/*$CUIT* | head"
