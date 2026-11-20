# Pasar el Monitoreo fiscal a un servidor en la nube

Paquete `robots_v1.4.0_web_v2.4.tgz`: robots + web + lo traído de Radar fiscal + estos scripts.

## 0. Repositorio de GitHub (para poder cambiar el robot cuando quieras)
En GitHub (cuenta tdainman-code): **New repository** → nombre `monitoreo-fiscal` → **Private** → sin README → Create.
Queda vacío: el servidor sube la primera versión solo.

## 1. Crear el servidor (lo hacés vos: cuenta y tarjeta a tu nombre)
- Proveedor con datos en **São Paulo** (más cerca y con IP de la región, menos riesgo de que ARCA/AGIP/ARBA
  bloqueen o pidan captcha): por ejemplo **Vultr** → *Cloud Compute*.
  Si te piden otra región, Miami o Nueva York también sirven.
- Sistema: **Ubuntu 24.04 LTS**. Tamaño: **2 GB de RAM** como mínimo (el navegador del robot usa memoria).
- Acceso: dejá que te genere la **contraseña de root** (o cargá tu llave SSH). Anotá la **IP**.

## 2. Subir el paquete e instalar (unos 10 minutos)
En tu compu, abrí **PowerShell** y escribí (cambiando la IP):
```
scp "$HOME\Documents\robot-nube\robots_v1.4.0_web_v2.4.tgz" root@IP:/root/
ssh root@IP
```
Ya adentro del servidor:
```
tar xzf robots_v1.4.0_web_v2.4.tgz && bash nube/instalar_nube.sh --github tdainman-code/monitoreo-fiscal
```
Durante la instalación pregunta:
- tu **usuario administrador de la web** (y su contraseña): ves usuarios, actividad y la pantalla **Sistema**;
- un **usuario administrador del servidor** (opcional, con sudo, para no entrar como root);
- y muestra una **llave** para pegar en GitHub → `monitoreo-fiscal` → Settings → Deploy keys → Add deploy key
  (tildá *Allow write access* solo esta primera vez, para que suba el código).
Al terminar muestra la dirección, por ejemplo `https://203-0-113-5.sslip.io`. Si después querés una propia
(`robots.tuestudio.com.ar`), se apunta el dominio a la IP y se vuelve a correr `bash nube/instalar_nube.sh robots.tuestudio.com.ar`.

## 3. Mudar claves, datos y usuarios desde la oficina
1. Copiá `nube/migrar_desde_oficina.sh` y `nube/restaurar_en_nube.sh` a la máquina **robots** de la oficina (WinSCP),
   y `restaurar_en_nube.sh` también al servidor nuevo (`scp ... root@IP:/root/`).
2. En la máquina robots (PuTTY, usuario robot): `bash migrar_desde_oficina.sh IP` → pedís una contraseña nueva para
   cifrar el paquete y lo manda directo al servidor.
3. En el servidor: `bash /root/restaurar_en_nube.sh /root/mudanza_robots.enc` → pide esa contraseña, restaura y borra el paquete.

La llave maestra y la base de claves viajan juntas **pero cifradas**: sin la contraseña el archivo no sirve.
Guardá la copia de la llave maestra en el pendrive como siempre.

## 4. Probar
```
sudo -u robot bash -c 'cd ~/app && ~/venv/bin/python -m robots.correr situacion_fiscal --cuit 20XXXXXXXXX'
sudo -u robot bash -c 'cd ~/app && xvfb-run -a ~/venv/bin/python -m robots.correr agip --cuit 30XXXXXXXXX'
sudo -u robot bash -c 'cd ~/app && ~/venv/bin/python -m robots.correr fiscalizaciones --cuit 20XXXXXXXXX'
```
Si algo falla, las capturas quedan en `/var/lib/robots/datos/<cuit>/capturas/`.
AGIP y fiscalizaciones se programaron con lo relevado en Radar fiscal: la **primera corrida real** confirma los
nombres de los servicios (si cambian, se ajustan en `robot_agip.py` / `arca.py`).

## 5. Apagar la oficina (recién cuando la nube corrió bien una noche)
En la máquina robots: `crontab -e` y comentar las líneas `# robots-auto`. No borres nada de la oficina por un tiempo.

## Cambiar el robot o la web cuando quieras
Le pedís el cambio a **Claude Code** sobre el repositorio `monitoreo-fiscal`. Cuando queda en la rama `main`, el servidor
(cada 5 minutos) corre las pruebas y, si pasan, lo instala sin cortar una corrida en curso. Si fallan, no lo instala y
queda anotado en la web: ⚙ Más → **Sistema**. Volver atrás: `sudo bash /opt/monitoreo/repo/nube/actualizar_desde_github.sh --volver`.

## Qué queda andando en la nube
- **Lunes a viernes, 20 a 6 h — corrida diaria liviana de todos los clientes:** Cuentas Tributarias (deuda vencida,
  DDJJ sin presentar, vencimientos) y e-ventanilla de ARCA. Primero los urgentes y los de datos más viejos (si una noche
  no alcanza, los que quedaron van primero la siguiente). Si ARCA pide captcha o rechaza 4 veces seguidas, frena esa noche.
- **Sábado y domingo desde las 6 h — corrida completa:** cada cliente tiene fijo el sábado o el domingo (mitad y mitad;
  monotributistas semana por medio): deuda, planes, DFE, Libro IVA, F.931, SIFERE, fiscalizaciones, ARBA, AGIP e informes.
- Domingo 20 h: repechaje de los que dieron error en la semana (cortes de ARCA, portal caído).
- Un pedido de "Actualizar ahora" hecho durante la corrida nocturna espera a que termine.
- Cada minuto: corridas pedidas desde la web (botón **Actualizar ahora** en la ficha del cliente).
- Cada 3 minutos: claves cargadas desde la web.
- Firewall (solo SSH y https), actualizaciones de seguridad automáticas, bloqueo de intentos de ingreso (fail2ban).
