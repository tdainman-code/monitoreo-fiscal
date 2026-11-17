# Robots – Estudio Mancovsky (versión 1.4.0)

Corre **solo** en la máquina virtual `robots` (Ubuntu Server, disco cifrado).

## Contenido
| Archivo | Qué hace |
|---|---|
| `robots/almacen_claves.py` | Almacén cifrado de claves por cliente y organismo + importador de la planilla |
| `robots/arca.py` | Ingreso a ARCA y apertura de servicios. Se detiene ante captcha, token, cambio de clave o términos. Nunca reintenta una clave rechazada |
| `robots/robot_mis_comprobantes.py` | Descarga CSV de emitidos y recibidos por período y los procesa |
| `robots/robot_situacion_fiscal.py` | Cuentas Tributarias (deudas, vencimientos, DDJJ pendientes) + Mis Facilidades (planes vigentes, valor de cuota, cuotas pendientes, vencidas impagas, a vencer en 15 días). Genera `situacion_fiscal.xlsx` |
| `robots/lector_situacion.py` | Convierte las tablas de esos dos servicios en datos, controles y alertas |
| `robots/correr.py` | Lanzador: un cliente, varios o todos |
| `robots/lector_mis_comprobantes.py`, `lector_f931.py`, `recordatorios.py` | Lectores y reglas probados el 14/11/2026 |
| `pruebas/test_robot_simulado.py` | Prueba Mis Comprobantes contra una simulación de ARCA (sin internet) |
| `pruebas/test_situacion_simulado.py` | Prueba Situación Fiscal contra una simulación de ARCA (sin internet) |

## Instalación en la máquina `robots` (una sola vez)
```bash
sudo apt update && sudo apt install -y python3-venv unzip
python3 -m venv ~/venv
~/venv/bin/pip install playwright pandas openpyxl cryptography
~/venv/bin/playwright install --with-deps chromium
sudo mkdir -p /etc/robots /var/lib/robots
sudo chown $USER: /etc/robots /var/lib/robots && chmod 700 /etc/robots /var/lib/robots
unzip robots_v0.1.zip -d ~/robots && cd ~/robots
~/venv/bin/python -m robots.almacen_claves crear-llave
```
**Copiar `/etc/robots/llave_maestra.key` a un pendrive guardado bajo llave.** Sin esa llave las claves no se pueden leer.

## Scripts (se corren con `bash <nombre>` desde /home/robot)
| Script | Para qué |
|---|---|
| `actualizar.sh` | Instala o actualiza los robots desde `robots_v1.2.3.zip`. No toca la llave ni las claves |
| `situacion.sh` | Situación fiscal de un cliente: `bash situacion.sh CUIT` (o `... CUIT sct` / `... CUIT mf`) |
| `importar.sh` | Importa la planilla más reciente; si no hay errores la borra con `shred` |
| `revisar_planilla.sh` | Revisa la estructura de la planilla sin mostrar datos |

## La planilla
- Se leen las filas desde la **3 hasta la última con datos**: no hay límite de clientes.
- Las columnas se buscan por su **título de la fila 1** (no importa el orden).
- Las solapas deben llamarse **Clientes** y **Accesos** (mayúsculas/espacios no importan). *Relacionados* e *Instrucciones* son opcionales.
- Las filas de ejemplo (CUIT 20000000001 / 20000000002) se ignoran.
- Se puede re-importar la misma planilla con más clientes: lo existente se actualiza y lo nuevo se agrega, sin duplicar.

## Carga de claves del piloto
1. Completar `plantilla_carga_clientes.xlsx` (máx. 10 clientes).
2. Copiarla a la máquina `robots` e importar:
   ```bash
   ~/venv/bin/python -m robots.almacen_claves importar plantilla.xlsx
   ~/venv/bin/python -m robots.almacen_claves listar     # muestra todo menos las claves
   ```
3. **Borrar la planilla** (`shred -u plantilla.xlsx`) y sus copias.

## Primera prueba real (un cliente)
```bash
~/venv/bin/python -m robots.correr mis_comprobantes --periodo 2026-10 --cuit 20XXXXXXXXX
```
Si falla, quedan capturas `error_*.png` en `/var/lib/robots/datos/<cuit>/<período>/` para ver qué mostró ARCA (se bajan con WinSCP). Los selectores del login están marcados `# VERIFICAR` en `arca.py`.

## Corrida para todos
```bash
~/venv/bin/python -m robots.correr mis_comprobantes --periodo 2026-10 --todos
```
Deja 20 a 45 segundos entre clientes. Resultados en `/var/lib/robots/datos/<cuit>/<período>/` y registro en `/var/lib/robots/ejecuciones.jsonl`.

## Situación fiscal (Cuentas Tributarias + Mis Facilidades)
```bash
bash situacion.sh 20331162788
```
Un solo ingreso a ARCA. Resultados en `/var/lib/robots/datos/<cuit>/situacion/<fecha>/`:
`situacion_fiscal.xlsx` (Resumen, Alertas, Deudas, Vencimientos, DDJJ pendientes, Planes vigentes, Cuotas, Todos los planes),
`resultado.json` y los datos crudos `sct_crudo.json` / `mf_crudo.json`.

Controles: el CUIT de cada pantalla debe ser el del cliente; las filas leídas deben coincidir con el contador
de ARCA (Deudas N, DDJJ N) y la suma de capital e intereses con el resumen de ARCA; cada pantalla de plan debe
mostrar el número de plan pedido. Si algo no coincide, se detiene o lo marca como alerta "Control de lectura".

Sesión vencida: si ARCA pide volver a ingresar a mitad del trabajo (la sesión caduca rápido), el robot
vuelve a entrar con la misma clave (ya aceptada en esa corrida) y sigue desde donde quedó, hasta 3 veces
por corrida. Si ARCA rechaza la clave, no reintenta. Deja captura `error_sesion_*.png` de cada vencimiento.
No conviene tener abierta en otro navegador una sesión del mismo CUIT mientras corre el robot.

CUIT equivocado (falla conocida de ARCA: Cuentas Tributarias a veces muestra los datos de una sesión
anterior): el robot anota qué CUIT viaja en cada consulta interna de datos (getVencimientos, getDeudas,
getFaltasPresentacion) y solo acepta los datos si TODAS son del cliente; también controla el CUIT que muestran
el portal y cada pantalla de Mis Facilidades. Si aparece otro CUIT, descarta lo leído y vuelve a entrar
(cuenta como reingreso). El registro de esas consultas queda en `sct_crudo.json` (`consultas_cuit`).

Empresas que entran con la clave de otra persona (p. ej. el administrador; en Accesos: Usuario distinto del CUIT):
- Cuentas Tributarias: elige el CUIT en el desplegable del encabezado. ARCA recuerda la última elección, así que
  el robot lo controla SIEMPRE y lo cambia si quedó otro.
- Mis Facilidades: en "Seleccione una de las Cuits asociadas" elige la empresa y Aceptar (solo elige contribuyente).
Si la empresa no figura entre los CUIT asociados, se detiene sin reintentar: revisar la relación en ARCA.

Clasificación de cuotas: *Pagada* (ARCA: Cuota Cancelada), *Vencida impaga* (ARCA: Cuota Impaga),
*Vencida sin pago informado* (venció y ARCA todavía no informa estado: demora del banco), *A vencer*.
Planes con anticipo (p. ej. RG 5711): la lista de ARCA cuenta anticipo + cuotas (61) y el cronograma solo las
cuotas (60); no es un error de lectura. Se marca `con_anticipo` en la hoja Planes vigentes y no se alerta.
Alerta de plan caduco: solo planes presentados en los últimos 12 meses.

## Todo junto: un cliente, un ingreso, todas las fuentes + informes  (v1.0)
```bash
bash todo.sh CUIT            # o varios:  bash todo.sh CUIT1 CUIT2 ...
```
Fuentes: Cuentas Tributarias, Mis Facilidades, Domicilio Fiscal Electrónico (sin abrir nada), SIFERE (impuesto
determinado por jurisdicción), Declaración en línea (F931) y Mis Comprobantes de los últimos 12 meses.
Si un cliente no tiene alguna fuente (sin empleados, sin Convenio Multilateral), se anota y se sigue.
Lo ya bajado no se vuelve a bajar (`--forzar` para repetir). Si la sesión vence, vuelve a entrar y sigue.

Informes en `/var/lib/robots/informes/<fecha>/`:
- `relacion_dc_<CUIT>.xlsx`: relación débito/crédito de 12 meses (formato del ejemplo del 14/11, con fórmulas).
- `situacion_fiscal_<CUIT>.xlsx`: Resumen, Planes, Cronogramas, Deuda, Vencimientos 15 días, Notificaciones.
- `consolidado_<CUIT>_<nombre>.xlsx`: si el cliente tiene relacionados (hoja Relacionados de la planilla).
Para regenerar solo los informes (sin entrar a ARCA): `~/venv/bin/python -m robots.informe --cuit CUIT`.

DFE: abrir una comunicación no leída la da por notificada; el robot NUNCA abre comunicaciones: lista fecha,
organismo, asunto y si está sin abrir, y clasifica la importancia por el asunto.

## Corridas automáticas  (v1.2.2)
```bash
bash programar.sh            # activar (una vez)
bash programar.sh ver        # ver lo programado
bash programar.sh quitar     # desactivar
```
Lunes a viernes 02:00 todos los clientes; además días 20 y 30 (28 en febrero) para control de cuotas.
La máquina pasa a hora de Argentina. Si una corrida sigue trabajando, la siguiente no arranca.

## ARBA – Ingresos Brutos local
`bash arba.sh CUIT` corre solo ARBA (2-3 min) y regenera los informes.
  (v1.2)
Si el cliente tiene su CIT cargada (planilla, solapa Accesos: Organismo = ARBA, Usuario = CUIT, Clave = CIT),
el robot "todo" entra también a ARBA (Presentación de DJ web -> Consultas DJ cerradas Anticipo) y lee el
"Impuesto determinado de período" de cada mes. En la relación débito/crédito aparece la fila
"ARBA – Buenos Aires (contribuyente local)" y suma en el total de IIBB. Solo consulta: nunca presenta ni borra DJ.

## Cortes de ARCA / internet y corridas en segundo plano  (v1.1.1)
- Si se corta internet o ARCA (página que no carga, tiempo agotado) o vence la sesión, el robot espera
  30 s / 2 min / 5 min, vuelve a entrar y sigue desde donde quedó (hasta 3 veces por fuente).
- Corridas largas: lanzarlas EN SEGUNDO PLANO, así siguen aunque se corte el escritorio remoto o se cierre PuTTY:
```bash
bash todo_fondo.sh 27169781295 30519698338     # o:  bash todo_fondo.sh todos
bash ver_log.sh                                 # ver cómo va (Ctrl+C sale de la vista; el robot sigue)
```
  No arranca una segunda corrida si ya hay una en marcha (evita dos sesiones con el mismo CUIT).

## Aplicación web del estudio (tablero)  (v1.1)
Para todo el equipo, desde el navegador de cualquier PC del estudio o escritorio remoto (y el celular cuando
esté la VPN): **https://192.168.1.106:8443**
- Clientes con semáforo (rojo: cuotas impagas, DDJJ pendientes, notificaciones importantes sin abrir, plan caduco;
  amarillo: deuda vencida, cuotas que vencen en 15 días, errores de la última corrida).
- Ficha del cliente: alertas, planes, DDJJ, DFE, vencimientos, **descarga de informes** y **notas del equipo**.
- Agenda de todos los clientes, notas, **sugerencias** (ideas/problemas; el admin responde), estado de robots,
  registro de actividad (solo admin).
- Cada persona con su usuario. Bloqueo tras 5 intentos fallidos. La web NO puede leer las claves fiscales.

Instalar / actualizar (una vez, y después de cada versión nueva):
```bash
sudo bash instalar_web.sh
bash usuario_web.sh crear gabriel "Gabriel Mancovsky" --admin
bash usuario_web.sh crear ana "Ana Pérez"
```
La primera vez el navegador avisa "conexión no privada" (el certificado es propio del estudio): Avanzado → Continuar.

## Lo que el robot NO hace
No presenta, no paga (en Cuentas Tributarias no toca las casillas ni "Pagar seleccionado"), no confirma nada en Mis Facilidades, no genera VEP, no acepta términos, no resuelve captchas, no abre notificaciones: **solo consulta y descarga**.


## Novedades 1.4.0 / web 2.4 (17/11/2026): lo aprendido en Radar fiscal + versión para la nube
| Qué | Dónde |
|---|---|
| **AGIP** (Ciudad): ingreso con Clave Ciudad, DFE (solo el listado, nunca abre una comunicación), estado de cuenta y fiscalización electrónica. Si se entra con la clave de un representante, elige el CUIT del cliente y verifica que la pantalla lo muestre antes de leer | `robots/robot_agip.py` · `xvfb-run -a ~/venv/bin/python -m robots.correr agip --cuit 30XXXXXXXXX` |
| **Fiscalizaciones ARCA**: órdenes de intervención, fiscalización electrónica y SIACE (solo lectura; si el servicio no está, anota "sin servicio") | `robots/robot_fiscalizaciones.py` · `python -m robots.correr fiscalizaciones --cuit ...` |
| AGIP y fiscalizaciones entran en la corrida **semanal** y en la completa | `robot_todo.py` |
| **Pedir corridas desde la web** (botón "Actualizar ahora" en la ficha): la web deja el pedido en la bandeja y `robots.pedidos` lo corre (cada minuto, mismo candado que las nocturnas) | `robots/pedidos.py` |
| Web: **Cartera** (DFE de ARCA/ARBA/AGIP de todos con "marcar informada", deudas, planes, faltas de presentación, débito/crédito, proyección de IVA, resultado mensual, fiscalizaciones) | `robots_web/` |
| Web: en la ficha, **Débito/crédito y proyección** (gráfico), **Resultado mensual** (ventas − compras − sueldos − F.931, con conclusiones), **Fiscalizaciones**, **AGIP**, **Datos del cliente** | `robots_web/analisis.py` |
| Reglas de alerta (criterios TributIA): deuda mínima $15.000; D/C 12 meses < 0,8 Crítico, < 1,2 Advertencia (desde 6 meses); fiscalización abierta = Crítico | `robots_web/analisis.py` (REGLAS) |

AGIP no deja entrar navegadores ocultos: en el servidor se corre con pantalla virtual (`xvfb-run -a`). Los nombres de
servicios de AGIP y de fiscalizaciones de ARCA se confirman en la primera corrida real con las capturas de `capturas/`.

### Frecuencia (17/11/2026, cartera de +500 clientes)
`python -m robots.correr todo --todos --grupo-del-dia`: cada cliente tiene un día fijo (lunes a viernes, guardado en
`publico/grupos.json`). Responsables inscriptos todas las semanas; monotributistas / sin Portal IVA semana por medio.
`--solo-fallidos`: repechaje de los que terminaron en error en los últimos 7 días (sábados).

### Servidor en la nube
`nube/instalar_nube.sh` (servidor Ubuntu 24.04 nuevo), `nube/migrar_desde_oficina.sh` (en esta máquina: manda claves,
llaves, datos y usuarios cifrados al servidor nuevo) y `nube/restaurar_en_nube.sh` (en el servidor). Ver `nube/GUIA.md`.
En la nube el programa vive en `/home/robot/app/robots` y la web en `https://<dominio>` (Caddy, candado automático).

### Pruebas (sin internet)
`PYTHONPATH=. python3 robots/pruebas/test_agip_simulado.py` · `python3 pruebas/test_web_radar.py`
