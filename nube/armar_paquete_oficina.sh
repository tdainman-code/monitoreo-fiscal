#!/bin/bash
# Arma el paquete para actualizar el robot de la oficina con la versión de "main" (sin claves ni datos).
# Uso (en el repositorio):  bash nube/armar_paquete_oficina.sh  [carpeta_destino]
set -euo pipefail
cd "$(dirname "$0")/.."
DEST="${1:-.}"
V=$(git rev-parse --short HEAD); FECHA=$(date +%Y%m%d)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
git archive HEAD robots robots_web pruebas | tar x -C "$TMP"
git log -1 --format="Versión %h del %cd: %s" --date=format:%d/%m/%Y > "$TMP/VERSION.txt"
tar czf "$DEST/monitoreo_oficina_${FECHA}_$V.tgz" -C "$TMP" .
cp nube/actualizar_oficina.sh "$DEST/"
echo "$DEST/monitoreo_oficina_${FECHA}_$V.tgz"
