"""Mis Retenciones (versión anterior, seti .../misret) y cruce de percepciones con el Libro IVA. Réplica de las pantallas
que mostró Gaby el 21/11/2026, con datos de fantasía.
Uso: PYTHONPATH=. python3 robots/pruebas/test_mis_retenciones.py
"""
import json
import os
import sys
import tempfile
from datetime import date
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ["ROBOTS_DATOS"] = D = tempfile.mkdtemp()
from playwright.sync_api import sync_playwright  # noqa: E402
from robots import arca, percepciones, robot_mis_retenciones as rm  # noqa: E402

arca.pausa = lambda *a, **k: None
ok = True


def chk(c, m):
    global ok
    ok = ok and bool(c)
    print(("✔ " if c else "✘ ") + m)


CUIT, OTRO = "33710732979", "20400734306"
NUEVA = "https://mirequa-web.arca.gob.ar/"
VIEJA = "https://seti.afip.gob.ar/misret/consultaMisRetenciones.do"
# 7 percepciones de IVA (767) y 1 retención; una página de 5 y otra de 3
FILAS = [("30500036911", "767", "493", "29/10/2026", "172050", "PERCEPCION", "6,980.30", "0000005107046553", "29/10/2026", "FACTURA"),
         ("30516186670", "767", "493", "27/10/2026", "25298", "PERCEPCION", "449.88", "0201500000225945", "27/10/2026", "FACTURA"),
         ("30560950108", "767", "214", "26/10/2026", "2026001376", "RETENCION", "142,188.36", "0000000000085460", "26/10/2026", "ORDEN DE PAGO"),
         ("30500001735", "767", "493", "26/10/2026", "7716856", "PERCEPCION", "600.00", "0000000070256604", "26/10/2026", "OTRO COMPROBANTE"),
         ("30655116512", "767", "493", "15/10/2026", "55728", "PERCEPCION", "8,251.38", "0000050104520954", "06/10/2026", "LIQ SERV PUBLICOS - CLASE A"),
         ("30516186670", "767", "493", "21/10/2026", "62751", "PERCEPCION", "291.83", "0203100000281993", "21/10/2026", "FACTURA"),
         ("30711111119", "767", "493", "02/09/2026", "11", "PERCEPCION", "1,000.00", "0000300000001234", "28/09/2026", "FACTURA"),
         ("30722222227", "767", "493", "10/03/2026", "12", "PERCEPCION", "500.00", "0000100000000077", "10/03/2026", "FACTURA")]
CONSULTAS = []

MENU = f"""<table><tr><td><a href="{VIEJA}?method=getForm">- Impositivas</a></td></tr>
<tr><td><a href="{VIEJA.replace('Retenciones.do', 'RetencionesAduana.do')}?method=getForm">- Aduaneras</a></td></tr></table>"""
ADUANA = [("33693450239", "767", "700", "19/10/2026", "0", "PERCEPCION", "500,000.00", "26001IC04212899D", "19/10/2026", "OTRO COMPROBANTE"),
          ("33693450239", "217", "83", "19/10/2026", "0", "PERCEPCION", "2,798,190.12", "26001IC04212899D", "19/10/2026", "OTRO COMPROBANTE"),
          ("33693450239", "217", "83", "09/10/2026", "0", "PERCEPCION", "1,559,161.56", "26001IC04206722Y", "09/10/2026", "OTRO COMPROBANTE")]
FORM_ADUANA = f"""<html><body>{MENU}<h3>Consulta de Retenciones de Aduana</h3>
<table><tr><td>CUIT del retenido :</td><td><select name="cuitRetenido"><option value="{OTRO}">{OTRO}</option><option value="{CUIT}">{CUIT}</option></select></td></tr>
<tr><td>CUIT del agente :</td><td><input type="text" value="33693450239" disabled></td></tr>
<tr><td>Impuesto retenido :</td><td><input type="text" size="4"><select name="impSel"><option></option>
<option value="217">217 - SICORE-IMPTO.A LAS GANANCIAS</option><option value="767">767 - SICORE - RETENCIONES Y PERCEPC</option></select></td></tr>
<tr><td>Fecha desde de la ret./perc. :</td><td><input type="text" name="fd" value="01012026"></td></tr>
<tr><td>Fecha hasta de la ret./perc. :</td><td><input type="text" name="fh" value="21112026"></td></tr></table>
<input type="button" value="CONSULTAR" onclick="var q=new URLSearchParams();q.set('cuit',document.querySelector('[name=cuitRetenido]').value);
q.set('imp',document.querySelector('[name=impSel]').value);q.set('fd',document.querySelector('[name=fd]').value);
q.set('fh',document.querySelector('[name=fh]').value);q.set('adu','1');location.href='{VIEJA}?method=consultar&pag=1&'+q.toString()">
</body></html>"""

FORM = f"""<html><body>{MENU}
<h3>Consulta de Retenciones Impositivas</h3>
<table><tr><td>CUIT del retenido :</td><td><select name="cuitRetenido"><option>Seleccione una CUIT...</option>
<option value="{OTRO}">{OTRO}</option><option value="{CUIT}">{CUIT}</option></select></td></tr>
<tr><td>CUIT del agente :</td><td><input type="text" name="cuitAgente"></td></tr>
<tr><td>Impuesto retenido :</td><td><input type="text" name="imp" size="4"><select name="impSel"><option></option>
<option value="216">216 - SIRE - IVA</option><option value="217">217 - SICORE-IMPTO.A LAS GANANCIAS</option>
<option value="767">767 - SICORE - RETENCIONES Y PERCEPC</option></select></td></tr>
<tr><td>Retención : <input type="radio" name="op" value="R"> Percepción : <input type="radio" name="op" value="P">
 Retención y/o Percepción : <input type="radio" name="op" value="A" checked></td></tr>
<tr><td>Fecha Ret./Perc.</td><td>Desde : <input type="text" name="fd" value="01012026"> Hasta : <input type="text" name="fh" value="21112026"></td></tr>
<tr><td>Fecha Comprobante</td><td>Desde : <input type="text" name="cd"> Hasta : <input type="text" name="ch"></td></tr></table>
<input type="button" value="CONSULTAR" onclick="var q=new URLSearchParams();q.set('cuit',document.querySelector('[name=cuitRetenido]').value);
q.set('imp',document.querySelector('[name=impSel]').value);q.set('fd',document.querySelector('[name=fd]').value);
q.set('fh',document.querySelector('[name=fh]').value);location.href='{VIEJA}?method=consultar&pag=1&'+q.toString()">
</body></html>"""


def resultados(q):
    cuit, imp, pag = q["cuit"][0], q["imp"][0], int(q.get("pag", ["1"])[0])
    CONSULTAS.append((("A" if q.get("adu") else "") + imp, q["fd"][0], q["fh"][0]))
    if q.get("adu"):
        filas = [f for f in ADUANA if f[1] == imp and q["fd"][0] == "01052026"]
    elif imp != "767" or q["fd"][0] != "01052026":       # todo cae en el tramo may-oct 2026 del 767 (salvo marzo)
        filas = [f for f in FILAS if imp == "767" and q["fd"][0] == "01112025" and f[3].endswith("/03/2026")]
    else:
        filas = [f for f in FILAS if not f[3].endswith("/03/2026")]
    if not filas:
        return f"<html><body>{MENU}<p>CUIT del Retenido : {cuit}</p><p>No se encontraron retenciones para la consulta.</p></body></html>"
    trozo = filas[(pag - 1) * 5: pag * 5]
    cab = ("<tr><th>CUIT Agente Ret./Perc.</th><th>Impuesto</th><th>Régimen</th><th>Fecha Ret./Perc.</th><th>Número Certificado</th>"
           "<th>Descripción Operación</th><th>Importe Ret./Perc.</th><th>Número Comprobante</th><th>Fecha Comprobante</th>"
           "<th>Descripción Comprobante</th><th>Fecha Registración DJ Ag.Ret.</th><th>Código de Seguridad</th></tr>")
    cuerpo = "".join("<tr>" + "".join(f"<td>{x}</td>" for x in f) + "<td>12/11/2026</td><td>0000</td></tr>" for f in trozo)
    sig = (f"<a href='{VIEJA}?method=consultar&pag={pag + 1}&cuit={cuit}&imp={imp}&fd={q['fd'][0]}&fh={q['fh'][0]}'>[&gt;]</a>"
           if pag * 5 < len(filas) else "")
    return (f"<html><body>{MENU}<p>CUIT del Retenido : {cuit}</p><p>Impuesto retenido : {imp}</p>"
            f"<p>1-50 {sig} | mostrar <select><option>50</option></select></p><table>{cab}{cuerpo}</table></body></html>")


def ruteo(route):
    u = route.request.url
    h = "text/html; charset=utf-8"
    if u.startswith(NUEVA):
        return route.fulfill(content_type=h, body=f"<html><body><p>Podés acceder a la versión anterior del servicio haciendo "
                                                  f"<a href='{VIEJA}?method=getForm'>click aquí</a></p><h1>Mis retenciones</h1></body></html>")
    q = parse_qs(urlparse(u).query)
    if q.get("method", [""])[0] == "consultar":
        return route.fulfill(content_type=h, body=resultados(q))
    return route.fulfill(content_type=h, body=FORM_ADUANA if "Aduana" in u else FORM)


# ---------------------------------------------------------------- tramos y lectura
t = rm.tramos(date(2026, 11, 21))
chk(t[0][0] == date(2025, 11, 1) and t[-1][1] == date(2026, 11, 21) and all((b - a).days < 186 for a, b in t),
    f"últimos 12 meses en tramos de hasta 6 meses ({[(a.isoformat(), b.isoformat()) for a, b in t]})")
chk(rm._num("6,980.30") == 6980.30 and rm._num("142,188.36") == 142188.36 and rm._num("1.234,56") == 1234.56, "importes 6,980.30")

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context()
    ctx.route("https://mirequa-web.arca.gob.ar/**", ruteo)
    ctx.route("https://seti.afip.gob.ar/**", ruteo)
    pg = ctx.new_page()
    pg.goto(NUEVA)
    r = rm.leer(ctx, pg, CUIT, date(2026, 11, 21))
    chk(len(r["filas"]) == 11 and sum(f["operacion"] == "RETENCION" for f in r["filas"]) == 1,
        f"lee todas las páginas de la versión anterior ({len(r['filas'])} renglones)")
    chk(sum(1 for f in r["filas"] if f["aduana"]) == 3 and {c[0] for c in CONSULTAS} >= {"A767", "A217"}
        and any(f["comprobante"] == "26001IC04212899D" for f in r["filas"]), "lee también las Aduaneras (IVA y Ganancias) con el n° de despacho")
    chk({c[0] for c in CONSULTAS} - {"A767", "A217"} == {"767", "216"} and ("767", "01052026", "31102026") in CONSULTAS
        and any(c[1] == "01112025" for c in CONSULTAS), f"consulta 767 y 216 por tramos con fechas ddmmaaaa ({CONSULTAS[:3]}…)")
    f0 = next(f for f in r["filas"] if f["certificado"] == "172050")
    chk(f0["agente"] == "30500036911" and f0["importe"] == 6980.30 and f0["comprobante"] == "0000005107046553", "campos del renglón")
    # CUIT que no está en el selector
    pg.goto(VIEJA + "?method=getForm")
    try:
        rm._formulario(pg, "20999999995", "767", date(2026, 1, 1), date(2026, 6, 30))
        chk(False, "un CUIT que no está en 'CUIT del retenido' debe frenar")
    except arca.SinRepresentado:
        chk(True, "si el cliente no figura en 'CUIT del retenido', avisa")
    # 22/11/2026: mensaje real de ARCA cuando no hay movimientos (captura de Gaby)
    pg.set_content("<table><tr><td>- Impositivas</td></tr></table><p>No se han encontrado datos para esta consulta o los "
                   "parámetros ingresados corresponden a retenciones /percepciones con importe en cero</p><button>VOLVER</button>")
    chk(rm._resultados(pg, CUIT, "impositivas_216") == [], "sin movimientos ('No se han encontrado datos…') no es falla")
    # 22/11/2026: si ARCA no muestra resultados, el error dice qué cartel o mensaje mostró la página
    pg.set_content("<p>Consulta de Retenciones Impositivas</p><button onclick=\"alert('Debe ingresar el Impuesto retenido')\">CONSULTAR</button>")
    rm._escuchar_avisos(pg)
    rm.AVISOS.clear()
    pg.locator("button").click()
    try:
        rm._resultados(pg, CUIT, "impositivas_767")
        chk(False, "sin resultados debe dar error")
    except arca.ErrorRobot as e:
        chk("Debe ingresar el Impuesto retenido" in str(e), f"sin resultados: el error trae el cartel de ARCA ({e})")
    b.close()

# ---------------------------------------------------------------- cruce con el Libro IVA
os.makedirs(f"{D}/{CUIT}/mis_retenciones")
r.update(cuit=CUIT, fecha="2026-11-21")
json.dump(r, open(f"{D}/{CUIT}/mis_retenciones/2026-11-21.json", "w"))
open(f"{D}/{CUIT}/mis_retenciones/_basura.json", "w").write("{}")


def libro(mes, comps):
    os.makedirs(f"{D}/{CUIT}/libro_iva", exist_ok=True)
    json.dump({"periodo": mes, "comprobantes_compras": [dict(c, b_c=False, neto=1, iva=1, total=1) for c in comps]},
              open(f"{D}/{CUIT}/libro_iva/{mes}.json", "w"))


libro("2026-10", [{"fecha": "2026-10-29", "tipo": 1, "punto_venta": 51, "numero": 7046553, "cuit": "30500036911", "nombre": "A"},
                  {"fecha": "27/10/2026", "tipo": 1, "punto_venta": 2015, "numero": 225945, "cuit": "30516186670", "nombre": "B"},
                  {"fecha": "2026-10-06", "tipo": 1, "punto_venta": 501, "numero": 99999999, "cuit": "30655116512", "nombre": "Luz"}])
libro("2026-11", [{"fecha": "2026-10-09", "tipo": 66, "punto_venta": 0, "numero": 4206722, "numero_txt": "26001IC04206722Y",
                   "cuit": "33693450239", "nombre": "Aduana"},
                  {"fecha": "2026-09-28", "tipo": 1, "punto_venta": 3, "numero": 1234, "cuit": "30711111119", "nombre": "C"}])
libro("2026-09", [])
# AGIP Gestión-AR: CSV de "Descargar Excel" (solapa Percepciones), como el que mandó Gaby (datos de fantasía)
from robots import robot_agip  # noqa: E402
CSV = ('sep=,\r\n\r\nCUIT,N\xb0 Ader,Razon Social,N\xb0 Certificado,Norma,Fecha Percepcion,Tipo Comprobante,N\xb0 Comprobante,'
       'Fecha Comprobante,Monto Percibido,Base Calculo\r\n'
       '"30500036911","6923","PROVEEDOR A","0000000000000000","29","29/10/2026","F","A0   0510007046553","29/10/2026","725.50","24183.33",\r\n'
       '"30733333331","6924","PROVEEDOR Z","0000000000000000","29","05/10/2026","F","A0   0004000000088","05/10/2026","1500.00","50000.00",\r\n')
pa = robot_agip.leer_csv_percepciones(CSV)
chk(len(pa) == 2 and pa[0]["agente"] == "30500036911" and pa[0]["importe"] == 725.5 and pa[0]["comprobante"] == "A00510007046553",
    "AGIP: lee el CSV de percepciones de Gestión-AR")
os.makedirs(f"{D}/{CUIT}/agip/2026-11-21")
json.dump({"fecha": "2026-11-21", "percepciones": pa}, open(f"{D}/{CUIT}/agip/2026-11-21/resultado.json", "w"))
cr = percepciones.cruzar(CUIT, date(2026, 11, 21))
_z = [x for x in cr["sin_comprobante"] if x["agente"] == "30733333331"]
chk(len(_z) == 1 and _z[0]["impuesto"] == "IIBB CABA" and _z[0]["fuente"].startswith("AGIP")
    and not any(x["agente"] == "30500036911" and x["impuesto"] == "IIBB CABA" for x in cr["sin_comprobante"]),
    "AGIP: la percepción de IIBB sin factura en el Libro IVA se señala; la que tiene factura no")
# ARBA: zip de "Descarga para Importar" (Deducciones), archivo CP de ancho fijo
import io, zipfile  # noqa: E401,E402
from robots import robot_arba_dfe  # noqa: E402
_b = io.BytesIO()
with zipfile.ZipFile(_b, "w") as z:
    z.writestr(f"{CUIT}CP10202620261121.txt", "0290230-50003691-129/10/20260010600000000000007046553FA000000000333,15\r\n"
                                               "0290230-74444444-405/10/20260010600000000000011084586FA000000000367,56\r\n")
    z.writestr(f"{CUIT}CB10202620261121.txt", "0490230-50001008-42026/102850513830094194057581CCP000000042890,17\r\n")
pb = robot_arba_dfe.leer_zip_deducciones(_b.getvalue())
chk(len(pb) == 2 and pb[0]["agente"] == "30500036911" and pb[0]["comprobante"] == "07046553" and pb[1]["importe"] == 367.56,
    "ARBA: lee las percepciones (CP) del zip de Deducciones y no las bancarias (CB)")
os.makedirs(f"{D}/{CUIT}/arba_dfe/2026-11-21")
json.dump({"fecha": "2026-11-21", "percepciones": pb}, open(f"{D}/{CUIT}/arba_dfe/2026-11-21/resultado.json", "w"))
cr = percepciones.cruzar(CUIT, date(2026, 11, 21))
_y = [x for x in cr["sin_comprobante"] if x["impuesto"] == "IIBB Buenos Aires"]
chk(len(_y) == 1 and _y[0]["agente"] == "30744444444", f"ARBA: la percepción sin factura se señala, la otra no ({_y})")
os.remove(f"{D}/{CUIT}/arba_dfe/2026-11-21/resultado.json")
os.remove(f"{D}/{CUIT}/agip/2026-11-21/resultado.json")
cr = percepciones.cruzar(CUIT, date(2026, 11, 21))
faltan = {(x["agente"], x["comprobante"]) for x in cr["sin_comprobante"]}
chk(faltan == {("30500001735", "0000000070256604"), ("30516186670", "0203100000281993"), ("33693450239", "26001IC04212899D")},
    f"sin comprobante en el Libro IVA: las 2 facturas y el despacho que no están ({sorted(faltan)})")
_d = next(x for x in cr["sin_comprobante"] if x["comprobante"] == "26001IC04212899D")
chk(_d["impuesto"] == "Ganancias + IVA" and _d["importe_iva"] == 500000.0 and _d["desc_comprobante"] == "Despacho",
    f"un despacho con percepción de IVA y de Ganancias se cuenta una sola vez ({_d})")
chk(cr["en_libro"] == 5, f"encontradas por número, por fecha y registradas meses después ({cr['en_libro']})")
chk(cr["no_comparables"] == 1 and cr["meses_sin_libro"] == ["2026-03"], "mes sin Libro IVA: no comparable, no se acusa")
chk(round(cr["total_sin_comprobante"], 2) == round(891.83 + 500000 + 2798190.12, 2) and cr["alertas"] and "ni el gasto ni el crédito fiscal" in cr["alertas"][0]["texto"],
    "total y alerta para el encargado")
chk(os.path.exists(f"{D}/{CUIT}/conciliacion/percepciones.json"), "queda en conciliacion/percepciones.json")
chk(not any(x["comprobante"] == "0000000000085460" for x in cr["sin_comprobante"]), "las retenciones no se cruzan con compras")

print("OK" if ok else "FALLÓ")
sys.exit(0 if ok else 1)
