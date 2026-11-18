"""CCMA (autónomos y monotributo), réplica de las pantallas relevadas con Gaby el 17/11/2026 (datos de fantasía):
  - propio contribuyente: P02 (recálculo de deuda) -> P04 (última deuda calculada, tabla con filas "Saldo");
  - apoderado: Monotributo -> SelecRepresentado (tarjetas) -> Inicio -> VER SALDO / PAGAR -> CCMA;
  - criterio de 4 días corridos para marcar impago; importes 159,563.00 y (159,563.00).
Uso: PYTHONPATH=. python3 robots/pruebas/test_ccma.py
"""
import json
import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ["ROBOTS_DATOS"] = tempfile.mkdtemp()
from playwright.sync_api import sync_playwright  # noqa: E402
from robots import arca, robot_ccma as rc  # noqa: E402

arca.pausa = lambda *a, **k: None
arca.verificar_sesion = lambda *a, **k: None
HOY = date(2026, 11, 17)
CUIT, NOMBRE = "20111111112", "PRUEBA, JUAN"
CCAM = "https://servicios2.afip.gob.ar/tramites_con_clave_fiscal/ccam/"
MONO = "https://monotributo.afip.gob.ar/app/"


def cab(cuit=CUIT):
    return (f"<table><tr><td>CUIT: <b>{arca.cuit_fmt(cuit)}</b></td><td>Tipo de Contribuyente: <b>MONOTRIBUTISTA | AUTONOMO</b>"
            f"</td><td>17/11/2026 - 21:18</td></tr></table><p>Apellido y Nombre: {NOMBRE}</p>")


def fila(per, imp, desc, fecha, debe="", haber="", cp="019", sub="019"):
    return (f"<tr><td>+</td><td><img src='doc.gif'></td><td>{per}</td><td>{imp}</td><td>{cp}</td><td>{sub}</td>"
            f"<td>{desc}</td><td>{fecha}</td><td>{debe}</td><td>{haber}</td><td></td></tr>")


def saldo(per, s):
    return f"<tr><td></td><td></td><td>{per}</td><td></td><td></td><td></td><td>Saldo</td><td>17/11/2026</td><td></td><td></td><td>{s}</td></tr>"


P04 = f"""<html><body>{cab()}
<table><tr><td>ÚLTIMA DEUDA CALCULADA</td><td>FECHA DE CÁLCULO: 17/11/2026</td></tr>
<tr><td>Total Saldo Deudor:</td><td>120,036.74</td><td>Total Saldo Acreedor:</td><td>1,000.00</td></tr>
<tr><td>Obligación Mensual:</td><td>120,000.00</td><td>Obligación Mensual:</td><td>1,000.00</td></tr>
<tr><td>Accesorios:</td><td>36.74</td><td>Accesorios:</td><td>0.00</td></tr></table>
<p>Mostrar <select name="cant"><option>12</option><option>24</option></select> períodos</p>
<input type="button" value="Consultar">
<table>
<tr><th>Detalle</th><th>Período</th><th>Impuesto</th><th>Concepto</th><th>Subcpto</th><th>Descripción</th><th>Fecha Movimiento</th><th>Debe</th><th>Haber</th><th>Saldo</th></tr>
{fila('11/2026', 'AUT', 'Obligacion Mensual Autonomo.', '07/12/2026', '159,563.00')}
{saldo('11/2026', '(159,563.00)')}
{fila('10/2026', 'AUT', 'Obligacion Mensual Autonomo.', '05/11/2026', '156,541.75')}
{fila('10/2026', 'AUT', 'Pago Obligacion Mensual Autonomo.', '01/11/2026', '', '156,541.75')}
{saldo('10/2026', '0.00')}
{fila('09/2026', 'MON', 'Obligacion Mensual Monotributo', '20/10/2026', '120,000.00')}
{saldo('09/2026', '(120,000.00)')}
{fila('08/2026', 'MON', 'Obligacion Mensual Monotributo', '14/11/2026', '50,000.00')}
{saldo('08/2026', '(50,000.00)')}
{fila('12/2025', 'AUT', 'Obligacion Mensual Autonomo.', '05/01/2026', '122,460.30')}
{fila('12/2025', 'AUT', 'Pago Obligacion Mensual Autonomo.', '09/01/2026', '', '122,460.30')}
{fila('12/2025', 'AUT', 'Intereses Resarcitorios Autonomo', '09/01/2026', '135.53', '', '019', '051')}
{fila('12/2025', 'AUT', 'Pago Intereses Resarcitorios Autonomo', '13/01/2026', '', '135.53', '019', '051')}
{saldo('12/2025', '0.00')}
</table></body></html>"""

P02 = f"""<html><body>{cab()}<form action="P04_ctacte.asp" method="get"><p>RECÁLCULO DE DEUDA A FECHA</p>
PERÍODO DESDE (MM/AAAA) <input type="text" name="desde" value="01/2023">
PERÍODO HASTA (MM/AAAA) <input type="text" name="hasta" value="11/2026">
FECHA DE CÁLCULO <input type="text" name="fecha" value="17/11/2026">
<input type="submit" value="CALCULO DE DEUDA"><input type="button" value="PÁGINA PRINCIPAL"></form></body></html>"""

REPRES = f"""<html><body><div class="card"><span>OTRA PERSONA</span><span>20-99999999-7</span></div>
<div class="card" onclick="location.href='{MONO}Inicio.aspx'"><span>{NOMBRE}</span><span>{arca.cuit_fmt(CUIT)}</span></div></body></html>"""
INICIO = f"""<html><body><h3>Estado de Cuenta</h3><a href="{CCAM}P02_ctacte.asp" target="_blank">VER SALDO / PAGAR</a>
<a>PLAN DE PAGOS</a></body></html>"""
PEDIDOS = {"desde": None}


def ruteo(route):
    u = route.request.url
    if "P04_ctacte" in u:
        if "desde=" in u:
            PEDIDOS["desde"] = u.split("desde=")[1].split("&")[0]
        return route.fulfill(content_type="text/html; charset=utf-8", body=P04)
    if "P02_ctacte" in u:
        return route.fulfill(content_type="text/html; charset=utf-8", body=P02)
    if "SelecRepresentado" in u:
        return route.fulfill(content_type="text/html; charset=utf-8", body=REPRES)
    if "Inicio.aspx" in u:
        return route.fulfill(content_type="text/html; charset=utf-8", body=INICIO)
    return route.fulfill(content_type="text/html; charset=utf-8", body="<html><body>portal</body></html>")


ok = True


def chk(c, m):
    global ok
    print(("✔ " if c else "✘ ") + m)
    ok &= bool(c)


# 1) análisis puro
filas = [["", "", "09/2026", "MON", "019", "019", "Obligacion Mensual Monotributo", "20/10/2026", "120,000.00", "", ""],
         ["", "", "09/2026", "", "", "", "Saldo", "17/11/2026", "", "", "(120,000.00)"]]
a = rc.analizar(filas, HOY)
chk(a["impagos"] and a["impagos"][0]["dias_vencido"] == 28 and a["deuda_impaga"] == 120000.0, "período vencido hace 28 días: IMPAGO")
chk(rc.analizar(filas, date(2026, 10, 23))["periodos"][0]["estado"].startswith("vencido (esperando"),
    "a 3 días del vencimiento todavía no es impago (criterio de 4 días)")
chk(rc._num("(159,563.00)") == -159563.0 and rc._num("1,225.30") == 1225.3, "importes con coma de miles y paréntesis")

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context()
    ctx.route("https://servicios2.afip.gob.ar/**", ruteo)
    ctx.route("https://monotributo.afip.gob.ar/**", ruteo)
    # 2) propio contribuyente: P02 -> P04
    pg = ctx.new_page()
    pg.goto(CCAM + "P02_ctacte.asp")
    r = rc.leer(pg, CUIT, HOY)
    est = {x["periodo"]: x["estado"] for x in r["periodos"]}
    chk(PEDIDOS["desde"] is not None, f"recalcula la deuda desde {PEDIDOS['desde']}")
    chk(est == {"11/2026": "a vencer", "10/2026": "pagado", "09/2026": "IMPAGO", "08/2026": "vencido (esperando que se acredite el pago)",
                "12/2025": "pagado"}, f"estado de cada período ({est})")
    chk(r["deuda_impaga"] == 120000.0 and len(r["impagos"]) == 1, "deuda impaga solo lo vencido hace más de 4 días")
    t = r["totales"]
    chk(t["deudor"] == 120036.74 and t["deudor_accesorios"] == 36.74 and t["acreedor"] == 1000.0
        and "MONOTRIBUTISTA" in t["tipo"], f"totales de la cabecera ({t})")
    al = rc.alertas(r)
    chk(al and al[0]["prioridad"] == "ALTA" and "09/2026" in al[0]["texto"] and "120.000,00" in al[0]["texto"], "alerta ALTA con período e importe")
    # 3) otro CUIT en pantalla -> no se lee
    try:
        rc.leer(pg, "20222222223", HOY)
        chk(False, "con otro CUIT en pantalla debe frenar")
    except arca.CuitEquivocado:
        chk(True, "con otro CUIT en pantalla frena (CuitEquivocado)")
    pg.close()

    # 4) apoderado: Monotributo -> representado -> VER SALDO / PAGAR -> CCMA (pestaña nueva)
    def abrir(ctx_, portal, servicio):
        assert servicio == "monotributo", servicio
        nueva = ctx_.new_page()
        nueva.goto(MONO + "SelecRepresentado.aspx")
        return nueva
    arca.abrir_servicio = abrir
    portal = ctx.new_page()
    estado = {}
    res = rc.paso(CUIT, "20333333334", estado)(ctx, portal)
    guardado = json.load(open(os.path.join(os.environ["ROBOTS_DATOS"], CUIT, "ccma", f"{date.today().isoformat()}.json")))
    chk(res.startswith("OK") and guardado["periodos"] and estado["alertas"], f"apoderado: entra por Monotributo y lee la CCMA ({res})")
    chk(rc.paso("30711111119", "20333333334", {})(ctx, portal) == "no corresponde", "persona jurídica: no se consulta")
    b.close()

print("OK" if ok else "FALLÓ")
sys.exit(0 if ok else 1)
