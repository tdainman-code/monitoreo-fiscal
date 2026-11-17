"""Prueba de los robots F931, SIFERE, DFE, Mis Comprobantes (varios meses, con representado) y TODO
contra una simulación local armada con la estructura relevada en ARCA el 15/11/2026 (sin internet)."""
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import test_situacion_simulado as base  # noqa: E402  (login, portal, SCT, Mis Facilidades simulados)
from robots import (arca, robot_arba, robot_dfe, robot_f931, robot_mis_comprobantes as rmc, robot_sifere,  # noqa: E402
                    robot_situacion_fiscal as rsf, robot_todo, informe_cliente)

EMPRESA, ADMIN = "30519698338", "20142836751"
M = {"usuario": ADMIN, "cliente": EMPRESA, "sifere_otro": False}
F931_TXT = open(os.path.join(os.path.dirname(__file__), "f931_ejemplo.txt"), encoding="utf-8").read() \
    if os.path.exists(os.path.join(os.path.dirname(__file__), "f931_ejemplo.txt")) else None
CSV = ("Fecha,Tipo,Punto de Venta,Número Desde,Número Hasta,Cód. Autorización,Tipo Doc. Receptor,"
       "Nro. Doc. Receptor,Denominación Receptor,Tipo Cambio,Moneda,Imp. Neto Gravado,Imp. Neto No Gravado,"
       "Imp. Op. Exentas,Otros Tributos,IVA,Imp. Total\n")

SERVICIOS = """<html><body>
<a title="mcmp" role="button" onclick="window.open('https://fes.afip.gob.ar/mcmp/jsp/index.do')">MC</a>
<a title="sudeclaracion" role="button" onclick="window.open('https://serviciossegsoc.afip.gob.ar/djproforma/app/avisoInicial.aspx')">DJ</a>
<a title="comarb_sifereweb_consultas" role="button" onclick="window.open('http://app1.comarb.gob.ar/siferewebconsultas/mainMenu.do;jsessionid=abc')">SIF</a>
<a title="e-ventanilla" role="button" onclick="window.open('https://ve.cloud.afip.gob.ar/index.html')">DFE</a>
<a title="cuenta_corriente_contrib" role="button" onclick="window.open('https://ctacte.cloud.afip.gob.ar/contribuyente/externo')">SCT</a>
<a title="misfacilidades" role="button" onclick="window.open('https://serviciossegsoc.afip.gob.ar/tramites_con_clave_fiscal/MisFacilidadesNet/app/contribuyente/seguimiento_presentacion.aspx')">MF</a>
</body></html>"""

ENC_DJ = "<div>Usuario: MARIO EDUARDO TRAICOFF</div><div>CUIT: 30-51969833-8</div><div>Contribuyente: OFFSET TRAMAR</div>"
F931 = """<html><body>{enc}<pre>
C.U.I.T. 30-51969833-8  Rect. (1/9): {sec}  {mm}/{aaaa} Servicios Eventuales
Empleados en nómina: 2
Suma de Rem. 1: 1.000.000,00
a1 - Total de aportes S.S. 110.000,00
a1 - Total de aportes O.S. 30.000,00
b1 - Total de contribuciones 180.000,00
b3 - Detracción art. 23 Ley 27.541 0,00
Subtotal contribuciones S.S. 180.000,00
Contribuciones S.S. SIPA 160.000,00
Contribuciones S.S. No SIPA 20.000,00
Subtotal contribuciones O.S. 60.000,00
L.R.T. total a pagar 40.000,00
S.C.V.O. a Pagar: 500,00
Total Contribuciones RENATRE 0,00
Pago a Cuenta Dec. 394: 0,00
Total retenciones 0,00
</pre></body></html>"""

SIF_ENC = "<div>CONTRIBUYENTE (20-14283675-1) representando a OFFSET TRAMAR S. R. L. (%s)</div>"
SIF_MENU = "<a href='sfrDdjj.do?method=consultar' style='display:none'>Mensuales</a>"
SIF_FORM = """<form action='/siferewebconsultas/sfrDdjj.do' method=get><select id=mesDesdeStr name=md>%s</select>
<select id=anioDesdeStr name=ad>%s</select><select id=mesHastaStr name=mh>%s</select><select id=anioHastaStr name=ah>%s</select>
<input type=hidden name=buscar value=1><input type=submit value=Buscar></form>"""


def sifere_lista():
    filas = "".join(
        f"<tr><td><a href='/siferewebconsultas/sfrDdjj.do?det={a}{m}-{r}'><img alt='Valores por Jurisdicción'></a></td>"
        f"<td>{m}/{a} - {r}</td><td>5866 - Presentacion</td><td></td><td></td><td>993 - Afip</td><td>19/10/2026</td></tr>"
        for a, m, r in [("2026", "09", 0), ("2026", "08", 0), ("2026", "08", 1), ("2026", "07", 0)])
    return f"<table><tr><th></th><th>Anticipo</th><th>Formulario</th><th>Monto Total</th><th>Forma Pago</th><th>Banco / Sucursal</th><th>Fecha</th></tr>{filas}</table>"


def sifere_detalle(per_rect):
    det = "14.583,00" if per_rect.endswith("-1") else "10.000,00"
    return ("<table><tr><th></th><th>Jurisdicción</th><th>Imp determinado</th><th>Valores que Restan</th>"
            "<th>Valores que Suman</th><th>Int / Recargos</th><th>A favor Contrib</th><th>A favor Fisco</th><th>A Pagar</th></tr>"
            f"<tr><td></td><td>901</td><td>$0,00</td><td>$1,00</td><td>$0,00</td><td>$0,00</td><td>$1,00</td><td>$0,00</td><td>$0,00</td></tr>"
            f"<tr><td></td><td>902</td><td>${det}</td><td>$1,00</td><td>$0,00</td><td>$0,00</td><td>$1,00</td><td>$0,00</td><td>$0,00</td></tr>"
            f"<tr><td>Total</td><td>${det}</td><td>$2,00</td><td>$0,00</td><td>$0,00</td><td>$2,00</td><td>$0,00</td><td>$0,00</td></tr></table>")


DFE = """<html><body><div>TRAICOFF MARIO EDUARDO [20-14283675-1]</div>
<div class=modal style='display:block'><button onclick="this.parentNode.style.display='none'">Recordar más tarde</button><button>Entendido</button></div>
<ul><li><a role=tab href=# onclick="ver(0)">Mis Comunicaciones (2)</a></li><li><a role=tab href=# onclick="ver(1)">Comunicaciones de mis representados ()</a></li></ul>
<div class='tab-pane active' id=p0>%s</div>
<div class='tab-pane' id=p1 style='display:none'><select id=select-representados style='display:none'><option value=''>Seleccionar</option>
<option value='todos'>Todos</option><option value='30519698338'>OFFSET</option></select>
<div class='form-control dropdown-toggle' onclick="document.getElementById('dd').style.display='block'">Seleccionar</div>
<div id=dd style='display:none'><button class=dropdown-item>Todos tus representados</button>
<button class=dropdown-item onclick="document.getElementById('select-representados').value='30519698338';document.getElementById('tabla1').innerHTML=window.T1">OFFSET TRAMAR S.R.L. - 30519698338</button></div>
<div id=tabla1></div></div>
<select id=per-page-select><option>10</option><option>50</option><option>100</option></select>
<script>function ver(i){document.querySelectorAll('.tab-pane').forEach((p,j)=>{p.classList.toggle('active',i===j);p.style.display=i===j?'':'none'});return false}
window.T1=%s;</script></body></html>"""


def tabla_dfe(filas):
    th = "".join(f"<th>{h}<span> (Click to sort ascending)</span></th>" for h in
                 ["Notificado", "Asunto", "", "Organismo", "Representado", "Clasificación", "Recibido"])
    tb = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in f) + "</tr>" for f in filas)
    return f"<table class='table b-table'><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table>"


MC_ELEGIR = """<html><body><div>TRAICOFF MARIO EDUARDO [20-14283675-1]</div><h2>Elegí una persona para ingresar</h2>
<div>REPRESENTAR A:</div>
<a class='panel panel-default' href='#' onclick="location.href='/mcmp/jsp/setearContribuyente.do?c=30519698338';return false">OFFSET TRAMAR S.R.L. 30-51969833-8</a>
<a class='panel panel-default' href='#' onclick="location.href='/mcmp/jsp/setearContribuyente.do?c=20142836751';return false">TRAICOFF MARIO EDUARDO 20-14283675-1</a></body></html>"""


ARBA_DJ = [("188923545", "2025", "11", "1.254.988,30"), ("189255546", "2025", "12", "1.294.963,80"),
           ("189767035", "2026", "1", "1.100.000,00"), ("190183765", "2026", "2", "1.200.000,00")]


def arba(route, url):
    html = lambda b: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=b)
    enc = "<div>Usuario: 20-33116278-8 20331162788</div>"
    if "sso.arba" in url:
        if route.request.method == "POST":
            ok = "clave=bien" in (route.request.post_data or "")
            destino = "https://app.arba.gov.ar/Gestionar/dist/gestionar" if ok else "https://sso.arba.gov.ar/Login/login?err=1"
            return html(f"<script>location.href='{destino}'</script>")
        err = "<div>Usuario o clave incorrecta</div>" if "err=1" in url else ""
        return html(f"<html><body>{err}<form method=post action='/Login/login'>"
                    "<select id=selectLoguin><option value=op_Cuit>C.U.I.T.</option><option value=op_Host>Host</option></select>"
                    "<input type=text id=CUIT name=CUIT><input type=password id=clave_Cuit name=clave>"
                    "<input type=text id=USER name=USER style='display:none'>"
                    "<button type=button>Olvidé mi clave</button><button type=submit>Ingresar</button></form></body></html>")
    if "Gestionar" in url:
        return html(f"<html><body><div>20331162788</div><a>Otros trámites</a></body></html>")
    if "preBuscarDDJJCerradas" in url:
        ops = lambda r: "".join(f"<option value='{x}'>{x}</option>" for x in r)
        return html(f"""<html><body>{enc}<form action='/IBPresentaciones/performBuscarDDJJ.do' method=get>
<select name=estado><option value=C>Cerrada</option></select><select name=anioMensualDesde>{ops(range(2027,2019,-1))}</select>
<select name=mesDesde>{ops(range(1,13))}</select><select name=anioMensualHasta>{ops(range(2027,2019,-1))}</select>
<select name=mesHasta>{ops(range(1,13))}</select><input type=submit name=buscar value='Buscar DDJJ'></form>
<form action='/IBPresentaciones/deleteDJPendiente.do'><input type=submit value=Eliminar onclick="window.BORRO=1"></form></body></html>""")
    if "performBuscarDDJJ" in url:
        q = dict(x.split("=") for x in url.split("?")[1].split("&"))
        d = int(q["anioMensualDesde"]) * 100 + int(q["mesDesde"]); h = int(q["anioMensualHasta"]) * 100 + int(q["mesHasta"])
        filas = "".join(f"<tr><td>{c}</td><td>Cerrada</td><td>Mensual</td><td>{a}</td><td>{m}</td><td>Original</td><td>01/01/2026</td>"
                        f"<td>01/01/2026</td><td><span class=iconoEditar title='Ver detalle de la DJ {c}' "
                        f"onclick=\"location.href='/IBPresentaciones/detalleDJView.do?c={c}'\"></span></td></tr>"
                        for c, a, m, _ in ARBA_DJ if d <= int(a) * 100 + int(m) <= h)
        return html(f"<html><body>{enc}<table id=resultados class=dataTable><thead><tr><th>Nro. comprobante</th><th>Estado</th>"
                    f"<th>Régimen</th><th>Año</th><th>Periodo</th><th>Tipo</th><th>Fecha inicio</th><th>Fecha cierre</th><th></th>"
                    f"</tr></thead><tbody>{filas}</tbody></table></body></html>")
    if "detalleDJView" in url:
        c = url.split("c=")[1]
        _, a, m, imp = next(x for x in ARBA_DJ if x[0] == c)
        return html(f"<html><body>{enc}<table><tr><td>CUIT:</td><td>20-33116278-8</td><td>Año - Período:</td><td>{a} - {m}</td></tr>"
                    f"<tr><td>Nro comprobante:</td><td>{c} (Cerrada)</td><td>Tipo de DJ:</td><td>Original</td></tr></table>"
                    f"<table><tr><td>Impuesto determinado de período</td><td>$ {imp}</td></tr>"
                    f"<tr><td>Monto imponible declarado total</td><td>$ 77.912.177,87</td></tr></table></body></html>")
    return route.abort()


def servir(route):
    url = route.request.url
    if "arba.gov.ar" in url:
        return arba(route, url)
    html = lambda b: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=b)
    if url.endswith("/mis-servicios"):
        return html(SERVICIOS)
    if "djproforma" in url:
        if "dj_generadas" in url:
            filas = "".join(f"<tr><td>{s}</td><td>{p}</td><td>2</td><td>03/11/2026</td><td></td></tr>"
                            for s, p in [("Original (0)", "10/2026"), ("Original (0)", "09/2026"),
                                         ("Rectificativa (1)", "09/2026"), ("Original (0)", "08/2026")])
            return html(f"<html><body>{ENC_DJ}<table><tr><td>Consulta de declaraciones</td></tr><tr><th>Secuencia</th>"
                        f"<th>Periodo</th><th>Cant</th><th>Fecha</th><th>Ver</th></tr>{filas}</table></body></html>")
        m = re.search(r"Periodo=(\d{4})(\d{2})&SecDJVig=(\d+)", url)
        if m:
            return html(F931.format(enc=ENC_DJ, sec=int(m[3]), mm=m[2], aaaa=m[1]))
        return html(f"<html><body>{ENC_DJ}aviso</body></html>")
    if url.startswith("http://") and "comarb" in url:
        return route.abort("timedout")          # como en el estudio: http de COMARB no responde
    if "siferewebconsultas" in url:
        cuit = "30-99999999-9" if M["sifere_otro"] else "30-51969833-8"
        enc = SIF_ENC % cuit + SIF_MENU
        m = re.search(r"det=(\d{6}-\d)", url)
        if m:
            return html(f"<html><body>{enc}{sifere_detalle(m[1])}</body></html>")
        if "buscar=1" in url and "redir" not in url:
            return route.fulfill(status=302, headers={"Location": url.replace("https://", "http://") + "&redir=1"})
        if "buscar=1" in url:
            return html(f"<html><body>{enc}{sifere_lista()}</body></html>")
        if "method=consultar" in url:
            ops = lambda r: "".join(f"<option value='{x}'>{x}</option>" for x in r)
            meses, anios = [f"{i:02d}" for i in range(1, 13)], [str(a) for a in range(2027, 2019, -1)]
            return html(f"<html><body>{enc}" + SIF_FORM % (ops(meses), ops(anios), ops(meses), ops(anios)) + "</body></html>")
        return html(f"<html><body>{enc}Sistema SifereWeb</body></html>")
    if "ve.cloud" in url and M.get("cortes_dfe", 0) > 0:
        M["cortes_dfe"] -= 1
        return route.abort("internetdisconnected")     # corte de internet
    if "ve.cloud" in url:
        propias = tabla_dfe([("-", "Comunicación sobre tu presentación digital", "", "ARCA", "", "Notificaciones", "13/11/2026"),
                             ("11/11/2026", "Monotributistas y autónomos - Intimación por falta de pago", "", "ARCA", "",
                              "Intimaciones", "02/11/2026")])
        rep = tabla_dfe([("-", "Libro de sueldos digital - Aviso de emisión", "", "ARCA", "OFFSET", "Libro de sueldos", "03/11/2026"),
                         ("-", "Notificaciones Seclo", "", "Secretaría de Trabajo", "OFFSET", "Seclo", "04/11/2026")])
        return html(DFE % (propias, json.dumps(rep)))
    if "mcmp" in url:
        if "setearContribuyente" in url or "comprobantes" in url.lower():
            c = re.search(r"c=(\d+)", url)
            if c:
                M["mc_elegido"] = c[1]
            el = M.get("mc_elegido", ADMIN)
            enc = (f"<div>MIS COMPROBANTES TRAICOFF MARIO EDUARDO [20-14283675-1] REPRESENTANDO A: OFFSET [{arca.cuit_fmt(el)}]</div>"
                   if el != ADMIN else "<div>TRAICOFF [20-14283675-1]</div>")
            if "/mcmp/export/" in url:
                return route.fulfill(status=200, headers={"Content-Disposition": 'attachment; filename="x.csv"'},
                                     content_type="text/csv", body=CSV.encode())
            if "comprobantes" in url.lower():
                per = M.get("per", "01/10/2026")
                return html(f"""<html><body>{enc}<label for=fecha>Fecha del Comprobante</label><input id=fecha>
<script>var dp={{setStartDate:function(d){{this.s=d}},setEndDate:function(d){{this.e=d}}}};
window.jQuery=function(el){{return {{data:function(){{return dp}},val:function(v){{el.value=v}},trigger:function(){{}}}}}};
function buscar(){{document.getElementById('r').style.display='block';document.getElementById('f').textContent='Fecha del Comprobante: '+dp.s+' a '+dp.e}}</script>
<button onclick=buscar()>Buscar</button><div id=r style=display:none><div id=f></div>No se encontraron registros</div></body></html>""")
            return html(f"<html><body>{enc}Menú principal</body></html>")
        return html(MC_ELEGIR)
    return base.servir(route)


_orig = base._original


from contextlib import contextmanager  # noqa: E402


@contextmanager
def nav(visible=False, carpeta_descargas=None):
    with _orig(visible=False) as ctx:
        ctx.route("**/*", servir)
        yield ctx


arca.ESPERAS_CORTE = [0, 0, 0]
arca.navegador = nav


def caso(nombre, fn, esperado):
    try:
        r = fn()
        ok = esperado(r)
        print(f"{'✔' if ok else '✘'} {nombre}: {r if not ok else 'OK'}"[:400])
        return ok
    except Exception as e:
        print(f"✘ {nombre}: {type(e).__name__}: {e}"[:400])
        return False


if __name__ == "__main__":
    D = tempfile.mkdtemp()
    import robots.informe as _inf
    _inf.INFORMES = os.path.join(D, "informes")
    for mod in (robot_f931, robot_sifere, robot_dfe, rmc, rsf, robot_todo, informe_cliente, robot_arba):
        mod.DATOS = D
    base.MODO.update({"usuario": ADMIN, "cuit_pantalla": "20-33116278-8", "contador_deudas": 3, "plan_ver_pagos": None,
                      "sct_al_login": 0, "cuit_datos": base.CUIT, "cuit_datos_veces": 0, "sct_elegido": None,
                      "mf_elegido": None, "representa": True, "ddjj_vacia": False, "mf_vence_en": None})
    pers = ["2026-07", "2026-08", "2026-09", "2026-10"]
    oks = [
        caso("F931: toma la última secuencia de cada mes y lee el formulario",
             lambda: robot_f931.correr(EMPRESA, None, ADMIN, "x", periodos=pers),
             lambda r: r["periodos"] == {"2026-07": "sin DJ", "2026-08": "OK", "2026-09": "OK", "2026-10": "OK"}
             and json.load(open(f"{D}/{EMPRESA}/f931/2026-09.json"))["Secuencia"] == 1),
        caso("SIFERE: última rectificativa por anticipo e impuesto determinado por jurisdicción",
             lambda: robot_sifere.correr(EMPRESA, None, ADMIN, "x", periodos=pers),
             lambda r: r["periodos"] == {"2026-07": "OK", "2026-08": "OK", "2026-09": "OK", "2026-10": "no presentada"}
             and json.load(open(f"{D}/{EMPRESA}/sifere/2026-08.json"))["jurisdicciones"]["902"]["determinado"] == 14583.0),
        caso("DFE: elige la empresa en 'mis representados' y lista SIN abrir",
             lambda: (robot_dfe.correr(EMPRESA, None, ADMIN, "x"),
                      json.load(open(sorted(__import__('glob').glob(f"{D}/{EMPRESA}/dfe/*/resultado.json"))[-1])))[1],
             lambda r: r["total"] == 2 and r["sin_abrir"] == 2 and r["altas_sin_abrir"] == 1),
        caso("Corte de internet al abrir el DFE (2 veces) -> espera, vuelve a entrar y completa",
             lambda: (M.update(cortes_dfe=2), robot_dfe.correr(EMPRESA, None, ADMIN, "x"),
                      json.load(open(sorted(__import__('glob').glob(f"{D}/{EMPRESA}/dfe/*/resultado.json"))[-1])))[2],
             lambda r: r["total"] == 2 and M["cortes_dfe"] == 0),
        caso("DFE: comunicaciones propias del usuario",
             lambda: (robot_dfe.correr(ADMIN, None, ADMIN, "x"),
                      json.load(open(sorted(__import__('glob').glob(f"{D}/{ADMIN}/dfe/*/resultado.json"))[-1])))[1],
             lambda r: r["total"] == 2 and r["sin_abrir"] == 1),
        caso("Mis Comprobantes: elige la empresa y baja 2 meses en una sesión",
             lambda: rmc.correr_periodos(EMPRESA, ["2026-09", "2026-10"], ADMIN, "x"),
             lambda r: r["periodos"] == {"2026-09": "OK", "2026-10": "OK"}),
    ]
    oks.append(caso("ARBA: ingresa, busca DJ cerradas y lee el impuesto determinado de cada mes local",
                    lambda: robot_arba.correr(base.CUIT, None, base.CUIT, "bien",
                                              periodos=["2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03"]),
                    lambda r: r["periodos"] == {"2025-10": "sin DJ local", "2025-11": "OK", "2025-12": "OK", "2026-01": "OK",
                                                "2026-02": "OK", "2026-03": "sin DJ local"}
                    and json.load(open(f"{D}/{base.CUIT}/arba/2025-12.json"))["impuesto_determinado"] == 1294963.8))
    oks.append(not caso("ARBA con CIT incorrecta -> ClaveInvalida (no reintenta)",
                        lambda: robot_arba.correr(base.CUIT, None, base.CUIT, "mal", periodos=["2025-11"]), lambda r: False))
    print("   (el caso anterior DEBE fallar con ClaveInvalida)")

    def _todo():
        base.MODO.update({"usuario": base.CUIT})
        r = robot_todo.correr(base.CUIT, "2026-10", base.CUIT, "x", meses=2)
        base.MODO.update({"usuario": ADMIN})
        print("   ", {k: r[k] for k in ("errores", "mis_comprobantes", "reingresos")}, r.get("informes"))
        return r
    oks.append(caso("TODO: si una fuente muestra otro CUIT queda como error y sigue con las demás; genera los informes",
                    _todo, lambda r: {"dfe", "f931", "sifere"} <= set(r["errores"]) and len(r.get("informes", [])) == 2))
    M["sifere_otro"] = True
    oks.append(caso("SIFERE con OTRO contribuyente en el encabezado -> se detiene",
                    lambda: robot_sifere.correr(EMPRESA, None, ADMIN, "x", periodos=["2026-06"]),
                    lambda r: False))
    oks[-1] = not oks[-1]
    print(("✔" if oks[-1] else "✘") + "   (el caso anterior DEBE fallar)")
    sys.exit(0 if all(oks) else 1)
