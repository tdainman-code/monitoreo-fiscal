"""Prueba del robot AGIP contra una simulación local del portal (sin internet), armada con lo confirmado en Radar
fiscal el 13/11/2026: claveciudad.agip.gob.ar abre con el botón de miBA y un enlace "Clave Ciudad" que muestra
#loginCC con #cuit, #clave y "Ingresar". Las pantallas internas (DFE, estado de cuenta, fiscalización) son de
ejemplo: los nombres reales se confirman en la primera corrida con las capturas.
"""
import json
import os
import sys
import tempfile
from contextlib import contextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from robots import arca, robot_agip  # noqa: E402

CUIT, REPRESENTANTE = "30717468631", "20142836751"
M = {"clave_ok": "bien", "entro": False, "con_selector": False}

INICIO = """<html><head><title>AGIP - Clave Ciudad</title></head><body>
<a class="btn-miba-login" href="https://login.buenosaires.gob.ar/auth/realms/mail">Ingresá con cuenta miBA</a>
<div class="clave-ciudad-info"><a href="#" onclick="document.getElementById('loginCC').style.display='block'">Clave Ciudad</a></div>
<form id="loginCC" style="display:none"><input id="cuit"><input id="clave" type="password">
<a class="btn btn-primary" href="#" onclick="location.href='https://claveciudad.agip.gob.ar/login?c='+document.getElementById('clave').value">Ingresar</a>
<span class="msgError"></span></form></body></html>"""
INICIO_ERROR = INICIO.replace('style="display:none"', "").replace('<span class="msgError"></span>',
                                                                 '<span class="msgError">CUIT o clave incorrecta</span>')
PORTAL = """<html><body><h1>Portal del contribuyente</h1>
<a href="https://lb.agip.gob.ar/dfe" target="_blank">Domicilio Fiscal Electrónico</a>
<a href="https://lb.agip.gob.ar/deuda">Estado de Cuenta</a>
<a href="https://lb.agip.gob.ar/fe" target="_blank">Fiscalización Electrónica</a>
<div class="tarjeta" onclick="window.open('https://portal-cct.agip.gob.ar/inicio')"><h3>Nueva Cuenta Corriente Tributaria</h3></div></body></html>"""
CCT = """<html><body><div>Dinafer S R L {cuit}</div><h1>Estado de Cuenta Corriente Tributaria</h1>
<div><h4>Saldo deudor</h4><p>$ 2.133.601,00</p><p>Importe Nominal: $ 2.133.601,00</p><p>Intereses: $ 885.569,26</p></div>
<div><h4>Saldo a favor</h4><p>$ 26.303.826,11</p></div>
<h2>Mis notificaciones</h2><div><h4>Presentación de DDJJ</h4><span>71</span><span>Faltas de presentación</span></div>
<div><h4>Bandeja de entrada</h4><span>8</span><span>Notificaciones no leídas</span></div>
<h2>Mis impuestos</h2><div><h4>IIBB - Convenio Multilateral</h4><p>Total adeudado</p><p>$ 0,00</p><p>Saldo a favor / Disponible</p><p>$ 26.303.826,11</p></div>
<div><h4>Automotor</h4><p>Total adeudado</p><p>$ 3.019.167,35</p><p>Saldo a favor / Disponible</p><p>$ 0,00</p></div></body></html>"""
SELECTOR = f"""<select id="contrib"><option value="1">{REPRESENTANTE} - EL CONTADOR</option>
<option value="2">{CUIT} - BH SOLUCIONES</option></select><button onclick="this.parentNode.dataset.ok=1">Consultar</button>"""
DFE = """<html><body><div>Contribuyente: BH SOLUCIONES {cuit}</div>{sel}
<table><thead><tr><th>Fecha</th><th>Asunto</th><th>Tipo de comunicación</th><th>Imp./Reg.</th><th>Estado</th></tr></thead><tbody>
<tr><td>12/11/2026</td><td>Intimación de pago - deuda ISIB</td><td>Intimación</td><td>ISIB</td><td>Sin notificar</td></tr>
<tr><td>01/11/2026</td><td>Comunicación informativa</td><td>Comunicación</td><td>ISIB</td><td>Notificado por plazo vencido</td></tr>
</tbody></table></body></html>"""
DEUDA = """<html><body><div>CUIT {cuit}</div><table><thead><tr><th>Impuesto</th><th>Período</th><th>Total</th></tr></thead>
<tbody><tr><td>ISIB</td><td>2026-08</td><td>$ 150.000,50</td></tr><tr><td>ISIB</td><td>2026-09</td><td>$ 100.000,00</td></tr></tbody></table>
<a href="#">volver</a></body></html>"""
FE = """<html><body><div>{cuit}</div><table><thead><tr><th>Número</th><th>Estado</th></tr></thead>
<tbody><tr><td>FE-2026-123</td><td>En curso</td></tr></tbody></table></body></html>"""


def html(s):
    return {"status": 200, "content_type": "text/html; charset=utf-8", "body": s}


def servir(route):
    url = route.request.url
    if url.rstrip("/") == "https://claveciudad.agip.gob.ar":
        return route.fulfill(**html(INICIO_ERROR if M.get("error_previo") else INICIO))
    if "login.buenosaires.gob.ar" in url:             # cuenta miBA (22/11/2026)
        if "p=" in url:
            if url.endswith("p=" + M.get("miba_ok", "-")):
                M["entro"] = True
                return route.fulfill(**html("<script>location.href='https://claveciudad.agip.gob.ar/menu_principal.php'</script>"))
            return route.fulfill(**html("<p class='alert-error'>Usuario o contraseña inválidos</p>"))
        return route.fulfill(**html("""<h1>Ingresá a tu cuenta de la Ciudad</h1><input id="username"><input id="password" type="password">
          <button id="kc-login" onclick="location.href='https://login.buenosaires.gob.ar/auth?p='+document.getElementById('password').value">Iniciar sesión</button>"""))
    if "/login?c=" in url:
        if url.endswith("c=" + M["clave_ok"]):
            M["entro"] = True
            return route.fulfill(**html(PORTAL))
        M["error_previo"] = True
        return route.fulfill(**html("<script>location.href='https://claveciudad.agip.gob.ar/'</script>"))
    sel = SELECTOR if M["con_selector"] else ""
    ver = "" if M["con_selector"] else CUIT
    if url.endswith("/dfe"):
        return route.fulfill(**html(DFE.format(cuit=ver, sel=sel)))
    if url.endswith("/deuda"):
        return route.fulfill(**html(DEUDA.format(cuit=CUIT)))
    if "portal-cct" in url:
        return route.fulfill(**html(CCT.format(cuit=arca.cuit_fmt(CUIT))))
    if url.endswith("/fe"):
        return route.fulfill(**html(FE.format(cuit=M.get("cuit_fe", CUIT))))
    return route.fulfill(**html(PORTAL)) if M["entro"] else route.abort()


_original = arca.navegador


@contextmanager
def navegador_simulado(visible=False, carpeta_descargas=None):
    with _original(visible=False) as ctx:
        ctx.route("**/*", servir)
        yield ctx


arca.navegador = navegador_simulado
arca.pausa = lambda *a, **k: None
D = tempfile.mkdtemp()
robot_agip.DATOS = D
res = []


def caso(nombre, fn, chequeo):
    try:
        r = fn()
        bien = chequeo(r)
    except Exception as e:
        r, bien = f"{type(e).__name__}: {e}", False
    res.append(bien)
    print(("✔" if bien else "✘"), nombre, "" if bien else str(r)[:300])


def leer():
    import glob
    return json.load(open(sorted(glob.glob(f"{D}/{CUIT}/agip/*/resultado.json"))[-1]))


caso("ingresa con Clave Ciudad y lee DFE (sin abrir), deuda y fiscalización",
     lambda: (robot_agip.correr(CUIT, None, CUIT, "bien"), leer())[1],
     lambda r: print("   servicios:", r["servicios"]) or len(r["comunicaciones"]) == 2 and r["sin_abrir"] == 1 and r["altas_sin_abrir"] == 1
     and r["comunicaciones"][0]["importancia"] == "ALTA" and abs(r["deuda"]["total"] - 250000.5) < 0.01
     and r["fiscalizacion"] == [["FE-2026-123", "En curso"]] and r["cct"]["saldo_favor"] == 26303826.11
     and r["cct"]["faltas_presentacion"] == 71 and {i["impuesto"] for i in r["cct"]["impuestos"]} == {"IIBB - Convenio Multilateral", "Automotor"}
     and any(a["tipo"] == "AGIP: compensar deuda con saldo a favor" and "Automotor" in a["texto"] for a in r["alertas"])
     and any(a["tipo"] == "AGIP: saldo a favor para recuperar" for a in r["alertas"]))
M.update(entro=False, error_previo=False)
caso("Clave Ciudad incorrecta -> ClaveInvalida (no reintenta)",
     lambda: robot_agip.correr(CUIT, None, CUIT, "mal"),
     lambda r: False)
res[-1] = not res[-1]
print("   (el caso anterior DEBE fallar con ClaveInvalida)")
M.update(entro=False, error_previo=False, miba_ok="miba123")
caso("Clave Ciudad rechazada pero la clave es de miBA -> entra por miBA (Gaby, 22/11/2026)",
     lambda: (robot_agip.correr(CUIT, None, CUIT, "miba123"), leer())[1],
     lambda r: M["entro"] and len(r["comunicaciones"]) == 2)
M.update(entro=False, error_previo=False, con_selector=True, cuit_fe=REPRESENTANTE)
caso("representante: elige el CUIT del cliente; si una pantalla muestra a otro, NO la lee",
     lambda: (robot_agip.correr(CUIT, None, REPRESENTANTE, "bien"), leer())[1],
     lambda r: len(r["comunicaciones"]) == 2 and r["servicios"]["fiscalizacion"] == "OK (sin fiscalización abierta)"
     and r["fiscalizacion"] == [])          # 25/11/2026 (Gaby): sin el CUIT en pantalla = sin fiscalización abierta
from robots.robot_agip import comunicaciones_de, deuda_de  # noqa: E402

caso("lector de tablas sin columnas reconocibles no inventa datos",
     lambda: (comunicaciones_de([{"encabezados": ["A", "B"], "filas": [["x", "y"]]}]), deuda_de([{"encabezados": ["A"], "filas": [["1"]]}])),
     lambda r: r == ([], None))
print(f"\n{sum(res)}/{len(res)} OK")
sys.exit(0 if all(res) else 1)
