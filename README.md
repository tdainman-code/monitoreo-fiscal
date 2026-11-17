# Monitoreo fiscal (robots + web)
- `robots/` robots de ARCA, ARBA y AGIP (Python + Playwright). Ver `robots/LEEME.md`.
- `robots_web/` aplicación web (Flask).
- `nube/` instalación y actualización en el servidor (`nube/GUIA.md`).
- `pruebas/` y `robots/pruebas/` pruebas sin internet: el servidor las corre antes de instalar cada cambio.
Cada cambio en la rama `main` se instala solo en el servidor (cada 5 minutos) si pasan las pruebas.
NUNCA subir claves, llaves ni datos de clientes a este repositorio.
