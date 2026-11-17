#!/bin/bash
# =====================================================================================================
#  Conecta el servidor con el repositorio privado de GitHub para poder cambiar el robot cuando quieras.
#  Uso (root):   bash nube/conectar_github.sh  tdainman-code/monitoreo-fiscal
#
#  1. Crea una "llave de despliegue" SOLO para este servidor y te la muestra.
#  2. Vos la pegás en GitHub: repositorio -> Settings -> Deploy keys -> Add deploy key
#     (título "servidor robots"; tildá "Allow write access" SOLO si el repositorio está vacío, para la primera subida).
#  3. Si el repositorio está vacío, sube este paquete como primera versión.
#  4. Activa la actualización automática cada 5 minutos (con pruebas y vuelta atrás si fallan).
# =====================================================================================================
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Correr como root"; exit 1; }
REPO_GH="${1:?Uso: bash conectar_github.sh usuario/repositorio}"
AQUI="$(cd "$(dirname "$0")" && pwd)"; PAQ="$(cd "$AQUI/.." && pwd)"
mkdir -p /opt/monitoreo /root/.ssh; chmod 700 /root/.ssh
LLAVE=/root/.ssh/monitoreo_github
[ -f "$LLAVE" ] || ssh-keygen -q -t ed25519 -N "" -C "servidor-robots-$(hostname)" -f "$LLAVE"
grep -q "Host github-monitoreo" /root/.ssh/config 2>/dev/null || cat >> /root/.ssh/config <<CFG
Host github-monitoreo
    HostName github.com
    User git
    IdentityFile $LLAVE
    IdentitiesOnly yes
CFG
ssh-keyscan -t ed25519 github.com 2>/dev/null >> /root/.ssh/known_hosts
echo
echo "=========================================================================================="
echo " Pegá esta llave en GitHub -> $REPO_GH -> Settings -> Deploy keys -> Add deploy key"
echo "=========================================================================================="
cat "$LLAVE.pub"
echo "=========================================================================================="
read -r -p "Cuando la hayas agregado, apretá Enter... " _
URL="git@github-monitoreo:$REPO_GH.git"
until git ls-remote "$URL" >/dev/null 2>&1; do
  read -r -p "GitHub todavía no acepta la llave (¿se guardó? ¿el nombre del repositorio es $REPO_GH?). Enter para reintentar... " _
done
if [ -z "$(git ls-remote "$URL" 2>/dev/null)" ]; then
  echo "== El repositorio está vacío: subo este paquete como primera versión"
  T=$(mktemp -d); cp -r "$PAQ/robots" "$PAQ/robots_web" "$PAQ/nube" "$PAQ/pruebas" "$T/"
  find "$T" -name '__pycache__' -prune -exec rm -rf {} +
  cat > "$T/.gitignore" <<'GI'
__pycache__/
*.pyc
*.db
*.key
*.pem
*.enc
datos/
capturas/
.env*
GI
  cat > "$T/README.md" <<'RM'
# Monitoreo fiscal (robots + web)
- `robots/` robots de ARCA, ARBA y AGIP (Python + Playwright). Ver `robots/LEEME.md`.
- `robots_web/` aplicación web (Flask).
- `nube/` instalación y actualización en el servidor (`nube/GUIA.md`).
- `pruebas/` y `robots/pruebas/` pruebas sin internet: el servidor las corre antes de instalar cada cambio.
Cada cambio en la rama `main` se instala solo en el servidor (cada 5 minutos) si pasan las pruebas.
NUNCA subir claves, llaves ni datos de clientes a este repositorio.
RM
  (cd "$T" && git init -q -b main && git add -A && git -c user.name="Servidor robots" -c user.email="robots@localhost" \
     commit -q -m "Versión 1.4.0 / web 2.4: robots + web + Radar fiscal + nube" && git push -q "$URL" main) \
     || { echo "No se pudo subir (¿la llave tiene 'Allow write access'?)"; exit 1; }
  rm -rf "$T"
  echo "   Subido. Si querés, ahora podés sacarle el permiso de escritura a la llave (el servidor solo necesita leer)."
fi
rm -rf /opt/monitoreo/repo
git clone -q "$URL" /opt/monitoreo/repo
git -C /opt/monitoreo/repo rev-parse HEAD > /opt/monitoreo/instalado      # lo instalado hoy = lo que está en GitHub
install -m 755 /opt/monitoreo/repo/nube/actualizar_desde_github.sh /opt/monitoreo/actualizar.sh
cat > /etc/systemd/system/monitoreo-actualizar.service <<U
[Unit]
Description=Monitoreo fiscal: instalar cambios de GitHub (con pruebas)
[Service]
Type=oneshot
ExecStart=/bin/bash /opt/monitoreo/repo/nube/actualizar_desde_github.sh
U
cat > /etc/systemd/system/monitoreo-actualizar.timer <<U
[Unit]
Description=Monitoreo fiscal: buscar cambios en GitHub cada 5 minutos
[Timer]
OnBootSec=3min
OnUnitActiveSec=5min
[Install]
WantedBy=timers.target
U
systemctl daemon-reload; systemctl enable --now monitoreo-actualizar.timer >/dev/null
echo "LISTO: cada cambio en $REPO_GH (rama main) se prueba y se instala solo en 5 minutos."
echo "Estado: web -> ⚙ Más -> Sistema (solo administradores).  Vuelta atrás: sudo bash /opt/monitoreo/repo/nube/actualizar_desde_github.sh --volver"
