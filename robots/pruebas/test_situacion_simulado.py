"""Prueba del robot Situación Fiscal (Cuentas Tributarias + Mis Facilidades) contra una
simulación local de ARCA armada con la estructura real relevada el 15/11/2026 (sin internet).
Los importes son de ejemplo.
"""
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from robots import arca, lector_situacion as ls, robot_situacion_fiscal as rsf  # noqa: E402

CUIT = "20331162788"
MODO = {"cuit_pantalla": "20-33116278-8", "contador_deudas": 3, "plan_ver_pagos": None}

LOGIN = """<html><body><form><input id="F1:username" name="F1:username">
<input type=button id="F1:btnSiguiente" name="F1:btnSiguiente" value="Siguiente">
<input type=password id="F1:password"><input type=button id="F1:btnIngresar" name="F1:btnIngresar" value="Ingresar"
 onclick="location.href='https://portalcf.cloud.afip.gob.ar/portal/app/'"></form></body></html>"""
PORTAL = "<html><body><h1>Portal</h1> JUAN JOSE [20-33116278-8]</body></html>"
SERVICIOS = """<html><body>
<a class="panel" title="cuenta_corriente_contrib" role="button" onclick="window.open('https://ctacte.cloud.afip.gob.ar/contribuyente/externo')"><h3>SISTEMA DE CUENTAS TRIBUTARIAS</h3></a>
<a class="panel" title="misfacilidades" role="button" onclick="window.open('https://serviciossegsoc.afip.gob.ar/tramites_con_clave_fiscal/MisFacilidadesNet/app/contribuyente/seguimiento_presentacion.aspx')"><h3>MIS FACILIDADES</h3></a>
</body></html>"""

SCT_EXTERNO = """<html><body><div>GONCALVES VICENTE JUAN JOSE %s</div>%s
<iframe src="https://ctacte.cloud.afip.gob.ar/contribuyente/scripts/vue/homeContribuyente/index.html" width=1300 height=800></iframe></body></html>"""

FILAS_DEUDA = [("0", "30 - IVA", "201912", "24/01/2020", "$ 0,00", "$ 1.000,00"),
               ("0", "30 - IVA", "202410", "25/11/2024", "$ 3.000,00", "$ 500,50"),
               ("0", "351 - CONTRIBUCIONES SEG. SOCIAL", "202610", "13/11/2026", "$ 2.000,00", "$ 10,00")]


def _tabla(heads, filas, clase_fila=""):
    th = "".join(f"<th>{h}<span class=sr-only> (Click to sort ascending)</span></th>" for h in heads)
    if not filas:
        tb = f"<tr class='b-table-empty-row'><td colspan={len(heads)}>No se encontraron resultados</td></tr>"
    else:
        tb = "".join(f"<tr class='{clase_fila}'>" + "".join(f"<td>{c}</td>" for c in f) + "</tr>" for f in filas)
    return f"<table class='table b-table'><thead><tr>{th}</tr></thead><tbody>{tb}</tbody>" \
           f"<tfoot><tr><td colspan={len(heads)}>Total a pagar $ 0,00</td></tr></tfoot></table>"


def sct_home():
    if MODO["usuario"] != CUIT:
        pass                                  # cuit_datos lo fija el desplegable
    elif MODO["cuit_datos_veces"] > 0:      # falla de ARCA: trae datos de otro CUIT las primeras N veces
        MODO["cuit_datos_veces"] -= 1
        MODO["cuit_datos"] = "20084821196"
    else:
        MODO["cuit_datos"] = CUIT
    venc = _tabla(["Impuesto", "Concepto", "Subconcepto", "Período", "Ant/Cuota", "Fecha Vencimiento", "Detalle"],
                  [("30 - IVA", "19 - DECLARACIÓN JURADA", "19 - DECLARACIÓN JURADA", "20261000", "0", "25/11/2026",
                    "Presentacion y Pago"),
                   ("301 - SUSS", "19 - DECLARACIÓN JURADA", "19 - DECLARACIÓN JURADA", "20261100", "0", "11/12/2026",
                    "Presentacion y Pago")])
    deu = _tabla(["", "Establecimiento", "", "Impuesto", "Concepto", "Subconcepto", "Período", "Ant/Cuota",
                  "Vencimiento", "Saldo", "Int. Resarcitorio", "Int. Punitorio"],
                 [("<input type=checkbox checked>", e, "", i, "19 - DECLARACIÓN JURADA", "19 - DECLARACIÓN JURADA",
                   p, "0", v, s, r, "$ 0,00") for e, i, p, v, s, r in FILAS_DEUDA], " vencida")
    dj = _tabla(["Establecimiento", "Impuesto", "Concepto", "Subconcepto", "Período", "Ant/Cuota", "Vencimiento"],
                [] if MODO.get("ddjj_vacia") else
                [("0", "30 - IVA", "19 - DECLARACIÓN JURADA", "19 - DECLARACIÓN JURADA", "202609", "0", "23/10/2026")])
    sel = "<select><option value=10>10</option><option value=-1>Todos</option></select>"
    sel_off = "<select disabled class='mx-2 form-control'><option value=10>10</option><option value=-1>Todos</option></select>"
    return f"""<html><body>
<style>.fa-cal::before{{content:"\\f073"}} .fa-usd::before{{content:"\\f155"}}</style>
<div style="display:none"><ul role=tablist><li><a role=tab>Vencimientos oculto</a></li><li><a role=tab>Deudas 0</a></li></ul></div>
<ul role=tablist>
 <li><a role=tab href=# onclick="ver(0)"><i class=fa-cal></i> Vencimientos</a></li>
 <li><a role=tab href=# onclick="ver(1)"><i class=fa-usd></i> Deudas <span>{MODO['contador_deudas']}</span></a></li>
 <li><a role=tab href=# onclick="ver(2)">DDJJ pendientes de presentación <span>{0 if MODO.get('ddjj_vacia') else 1}</span></a></li></ul>
<div class="tab-pane active">Fecha de consulta: 15/11/2026 {sel}{venc}</div>
<div class="tab-pane" style="display:none">Saldo total a pagar: $ 6.510,50 Capital vencido $ 5.000,00
 Capital no vencido $ 0,00 Int. Resarcitorios $ 1.510,50 Int. Punitorios $ 0,00
 <button onclick="window.PAGO=1">Pagar seleccionado</button> Fecha de consulta: 15/11/2026 {sel}{deu}</div>
<div class="tab-pane" style="display:none">Fecha de consulta: 15/11/2026 {sel_off if MODO.get('ddjj_vacia') else sel}{dj} de {0 if MODO.get('ddjj_vacia') else 1} registros</div>
<script>
for (const m of ["getContribuyenteLogueado", "getVencimientos", "getDeudas", "getFaltasPresentacion"]) {{
  const pedido = m === "getContribuyenteLogueado" ? {{serviceName: "x", methodName: m}}
               : {{serviceName: "x", methodName: m, arguments: [{MODO['cuit_datos']}, null]}};
  fetch("/contribuyente/rest-access/service?request=" + encodeURIComponent(JSON.stringify(pedido)));
}}
function ver(i){{document.querySelectorAll('.tab-pane').forEach((p,j)=>{{p.classList.toggle('active',i===j);
 p.style.display=i===j?'':'none'}});return false}}</script></body></html>"""


PLANES = [("01/10/2026", "W742451", "8", "RG 5321 - Plan Deuda General", "7.937.049,59", "Aceptada", "Vigente", 101),
          ("05/05/2026", "W026105", "8", "RG 5321 - Plan Deuda General", "7.814.795,87", "Aceptada", "Plan Caduco", 102),
          ("18/02/2026", "V710205", "4", "RG 5321 - Plan Deuda General", "6.000,00", "Aceptada", "Vigente", 103),
          ("10/05/2023", "R516729", "12", "RG 4268", "1.000,00", "Aceptada", "Plan Caduco", 104),
          ("01/01/2022", "P000001", "6", "RG 4268", "1.000,00", "Aceptada", "Plan Cancelado", 105)]


def mf_lista():
    filas = "".join(
        f"<tr{' style=display:none' if i > 3 else ''}>" + "".join(f"<td>{c}</td>" for c in p[:7]) +
        f"<td><input type=submit value=Detalle id='ContentPlaceHolder1_rpt_detallePlan_{i}' "
        f"onclick=\"location.href='/tramites_con_clave_fiscal/MisFacilidadesNet/SeguimientoPlanEnviado/{p[7]}';return false\"></td></tr>"
        for i, p in enumerate(PLANES))
    return f"""<html><body>Contribuyente: {MODO['cuit_pantalla']} - GONCALVES
<input type=submit id=ContentPlaceHolder1_confirmarLiqManual value=Confirmar onclick="window.CONFIRMO=1">
<table class="table paginar searchTable"><thead><tr><th>Presentación</th><th>Número</th><th>Cuotas</th><th>Tipo</th>
<th>Consolidado($)</th><th>Estado</th><th>Situación</th><th></th></tr></thead><tbody>{filas}</tbody></table></body></html>"""


CRONO = {"W742451": [("1", "900521,36", "1.118.790,22", "16/11/2026", "1.129.045,80", "26/11/2026"),
                     ("2", "925285,69", "1.118.790,22", "16/12/2026", "1.129.000,00", "28/12/2026")]
         + [(str(n), "900000,00", "1.118.790,22", f"16/{n+10-12:02d}/2027", "1.129.000,00", f"26/{n+10-12:02d}/2027")
            for n in range(3, 9)],
         "V710205": [("1", "1739544,42", "2.161.176,15", "16/03/2026", "2.180.986,93", "26/03/2026"),
                     ("2", "1787381,88", "2.161.176,15", "16/10/2026", "2.180.986,93", "26/10/2026"),
                     ("3", "2103334,43", "2.161.176,15", "16/11/2026", "2.180.986,93", "26/11/2026")]}
ESTADOS = {"W742451": {1: ""}, "V710205": {1: "Cuota Cancelada", 2: "Cuota Impaga", 3: ""}}


def mf_plan(numero, id_, pagina):
    mostrado = MODO["plan_ver_pagos"] if MODO["plan_ver_pagos"] and pagina == "pagos" else numero
    cab = f"""<html><body>Contribuyente: {MODO['cuit_pantalla']}<div>Nro de plan: {mostrado}</div>
<input type=submit id=ContentPlaceHolder1_confirmarLiqManual value=Confirmar onclick="window.CONFIRMO=1">"""
    if pagina == "detalle":
        return cab + "<input type=submit id=ContentPlaceHolder1_btnPlanPago value='Plan de Pago'></body></html>"
    filas = ""
    for c in CRONO[numero]:
        if pagina == "cronograma":
            filas += f"<tr><td>{c[0]}</td><td>{c[1]}</td><td>1,00</td><td>-</td><td>{c[2]}</td><td>{c[3]}</td></tr>"
            filas += f"<tr><td></td><td></td><td>1,00</td><td>10,00</td><td>{c[4]}</td><td>{c[5]}</td></tr>"
        elif int(c[0]) in ESTADOS[numero]:
            est = ESTADOS[numero][int(c[0])]
            filas += f"<tr><td>{c[0]}</td><td>{c[1]}</td><td>1,00</td><td>0,00</td><td>{c[2]}</td><td>{c[3]}</td><td></td><td>{est}</td></tr>"
            filas += f"<tr><td></td><td></td><td>1,00</td><td>10,00</td><td>{c[4]}</td><td>{c[5]}</td><td></td><td></td></tr>"
            if "Cancelada" in est:
                filas += f"<tr><td></td><td></td><td>1,00</td><td>20,00</td><td>2.200.000,00</td><td>19/05/2026</td><td>Pago</td><td></td></tr>"
    if pagina == "cronograma":
        return cab + f"""<h4>Detalle del Plan de Pago</h4><table id=tableDetallePlanPago class=paginar><thead><tr><th>Cuota N°</th>
<th>Capital($)</th><th>Interés Financiero($)</th><th>Interés Resarcitorio($)</th><th>Total($)</th><th>Fecha Vencimiento</th>
</tr></thead><tbody>{filas}<tr><td>Totales</td><td>1</td><td>1</td><td>0,00</td><td>1</td><td>1° Vencimiento</td></tr>
<tr><td>1</td><td>1</td><td>1</td><td>2° Vencimiento</td></tr></tbody></table></body></html>"""
    return cab + f"""<h4>Pago Realizado</h4><table id=tableDetallePagos><thead><tr><th>Cuota N°</th><th>Capital($)</th>
<th>Interés Financiero($)</th><th>Interés Resarcitorio($)</th><th>Total($)</th><th>Fecha Venc.</th><th>Pago</th>
<th>Estado de Cuota</th></tr></thead><tbody>{filas}<tr><td>Total Pagado:</td><td>$ 1</td><td>$ 1</td><td>$ 1</td><td>$ 1</td><td></td></tr>
</tbody></table></body></html>"""


def servir(route):
    url = route.request.url
    html = lambda b: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=b)
    if "auth.afip.gob.ar" in url:
        return html(LOGIN)
    if url.endswith("/mis-servicios"):
        return html(SERVICIOS)
    if "portalcf" in url:
        u = MODO.get("usuario", CUIT)
        return html(PORTAL.replace("20-33116278-8", f"{u[:2]}-{u[2:10]}-{u[10]}"))
    if "rest-access/service" in url:
        return route.fulfill(status=200, content_type="application/json", body="{}")
    if "homeContribuyente" in url:
        return html(sct_home())
    if "ctacte.cloud" in url:
        if MODO.get("sct_al_login", 0) > 0:          # la sesión "vence" las primeras N veces
            MODO["sct_al_login"] -= 1
            return html("<script>location.href='https://auth.afip.gob.ar/contribuyente_/login.xhtml'</script>")
        if MODO["usuario"] != CUIT:            # usuario con representados: desplegable en el encabezado
            m_sel = re.search(r"PropertySelection=(\d+)", url.replace("%24", "$"))
            if m_sel:
                MODO["sct_elegido"] = m_sel[1]
            el = MODO.get("sct_elegido") or MODO["usuario"]
            opciones = [MODO["usuario"]] + ([CUIT] if MODO.get("representa", True) else [])
            sel = ("<form action='/contribuyente/externo' method=get><select name='$PropertySelection' "
                   "onchange='this.form.submit()'>" + "".join(
                       f"<option value='{o}'{' selected' if o == el else ''}>{o}</option>" for o in opciones)
                   + "</select></form>")
            MODO["cuit_datos"] = el
            return html(SCT_EXTERNO % (f"{el[:2]}-{el[2:10]}-{el[10]}", sel))
        return html(SCT_EXTERNO % (MODO["cuit_pantalla"], ""))
    if "IndexContribuyente.aspx" in url:
        u = MODO["usuario"]
        ops = [u] + ([CUIT] if MODO.get("representa", True) else [])
        return html("<html><body>CUIT " + u + "<select id=ContentPlaceHolder1_ddlCUIT>" + "".join(
            f"<option value=x{o}>{o[:2]}-{o[2:10]}-{o[10]}</option>" for o in ops) +
            "</select><input type=submit id=ContentPlaceHolder1_btnAceptar value=Aceptar onclick=\"MF_ELEGIDO="
            "document.getElementById('ContentPlaceHolder1_ddlCUIT').value;location.href="
            "'/tramites_con_clave_fiscal/MisFacilidadesNet/app/contribuyente/seguimiento_presentacion.aspx?e='+MF_ELEGIDO.slice(1);"
            "return false\"></body></html>")
    if "seguimiento_presentacion.aspx" in url:
        if MODO["usuario"] != CUIT and "?e=" not in url and not MODO.get("mf_elegido"):
            return route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                 body="<script>location.href='/tramites_con_clave_fiscal/MisFacilidadesNet/app/login/IndexContribuyente.aspx'</script>")
        m_e = re.search(r"\?e=(\d+)", url)
        if m_e:
            MODO["mf_elegido"] = m_e[1]
        return html(mf_lista())
    m = re.search(r"/(SeguimientoPlanEnviado|SeguimientoDetallePlanPago|SeguimientoDetallePagos)/(\d+)", url)
    if m:
        numero = next(p[1] for p in PLANES if p[7] == int(m[2]))
        if MODO.get("mf_vence_en") == (numero, m[1]):   # vence una vez a mitad de Mis Facilidades
            MODO["mf_vence_en"] = None
            return html("<script>location.href='https://portalcf.cloud.afip.gob.ar/portal/app/expiredSession'</script>")
        pagina = {"SeguimientoPlanEnviado": "detalle", "SeguimientoDetallePlanPago": "cronograma",
                  "SeguimientoDetallePagos": "pagos"}[m[1]]
        return html(mf_plan(numero, m[2], pagina))
    return route.abort()


_original = arca.navegador


@contextmanager
def navegador_simulado(visible=False, carpeta_descargas=None):
    with _original(visible=False) as ctx:
        ctx.route("**/*", servir)
        yield ctx


arca.ESPERAS_CORTE = [0, 0, 0]
arca.navegador = navegador_simulado
arca.pausa = lambda *a, **k: None


class _Hoy(date):
    @classmethod
    def today(cls):
        return date(2026, 11, 15)


rsf.date = _Hoy


def caso(nombre, esperado, chequeo=None, **modo):
    base = {"cuit_pantalla": "20-33116278-8", "contador_deudas": 3, "plan_ver_pagos": None, "sct_al_login": 0, "cuit_datos": CUIT, "cuit_datos_veces": 0, "usuario": CUIT,
            "sct_elegido": None, "mf_elegido": None, "representa": True, "ddjj_vacia": False,
            "mf_vence_en": None}
    MODO.update(base)
    MODO.update(modo)
    try:
        r = rsf.correr(CUIT, None, MODO["usuario"], "x")
        obtenido, det = "OK", ""
        if chequeo:
            fallas = chequeo(r)
            if fallas:
                obtenido, det = "OK con diferencias", fallas
    except arca.SesionPerdida as e:
        obtenido, det = "SesionPerdida", str(e)[:100]
    except arca.ErrorRobot as e:
        obtenido, det = "ErrorRobot", str(e)[:100]
    print(f"{'✔' if obtenido == esperado else '✘'} {nombre}: {obtenido} {det}")
    return obtenido == esperado


def chequeo_completo(r):
    f = []
    s, m = r["sct"], r["mis_facilidades"]
    if len(s["deudas"]) != 3 or s["totales_leidos"]["capital"] != 5000 or s["controles"]:
        f.append(f"deudas {len(s['deudas'])} {s['totales_leidos']} {s['controles']}")
    if len(s["ddjj_pendientes"]) != 1 or len(s["vencimientos"]) != 2:
        f.append("ddjj/vencimientos")
    if [p["numero"] for p in m["vigentes"]] != ["W742451", "V710205"]:
        f.append(f"vigentes {[p['numero'] for p in m['vigentes']]}")
    v = {p["numero"]: p for p in m["vigentes"]}
    w, x = v["W742451"], v["V710205"]
    if (w["cuotas_pendientes"], w["vencidas_impagas"], w["a_vencer_15_dias"], w["valor_cuota"]) != (8, 0, 1, 1118790.22):
        f.append(f"W742451 {w['cuotas_pendientes'], w['vencidas_impagas'], w['a_vencer_15_dias'], w['valor_cuota']}")
    if (x["cuotas_pagadas"], x["vencidas_impagas"], x["a_vencer_15_dias"], x["importe_vencido_impago"]) != (1, 1, 1, 2180986.93):
        f.append(f"V710205 {x['cuotas_pagadas'], x['vencidas_impagas'], x['a_vencer_15_dias'], x['importe_vencido_impago']}")
    tipos = sorted(a["tipo"] for a in r["alertas"])
    caducos = [a for a in r["alertas"] if a["tipo"] == "Plan caduco"]
    if len(caducos) != 1 or "W026105" not in caducos[0]["texto"]:
        f.append(f"caducos {caducos}")
    if "Cuota impaga" not in tipos or "Falta de presentación" not in tipos or "Deuda vencida" not in tipos:
        f.append(f"alertas {tipos}")
    if not os.path.exists(os.path.join(rsf.DATOS, CUIT, "situacion", "2026-11-15", "situacion_fiscal.xlsx")):
        f.append("sin Excel")
    return "; ".join(f)


if __name__ == "__main__":
    rsf.DATOS = tempfile.mkdtemp()
    ok = all([
        caso("Situación fiscal completa", "OK", chequeo_completo),
        caso("DDJJ pendientes vacía con 'Mostrar' deshabilitado (como en ARCA real)", "OK",
             lambda r: "" if r["sct"]["ddjj_pendientes"] == [] and not r["sct"]["controles"] else "ddjj",
             ddjj_vacia=True),
        caso("Contador de deudas distinto de lo leído -> alerta de control", "OK con diferencias",
             lambda r: "control" if r["sct"]["controles"] else "", contador_deudas=5),
        caso("Pantalla siempre con OTRO CUIT -> reintenta 3 veces y no guarda nada", "SesionPerdida",
             cuit_pantalla="20-99999999-9"),
        caso("SCT trae datos de otro CUIT 1 vez -> vuelve a entrar y lee los correctos", "OK",
             lambda r: "" if r["reingresos"] == 1 and all(a == CUIT for _, a in
                       json.load(open(os.path.join(rsf.DATOS, CUIT, "situacion", "2026-11-15", "sct_crudo.json")))
                       ["consultas_cuit"]) else f"reingresos {r['reingresos']}", cuit_datos_veces=1),
        caso("SCT trae datos de otro CUIT siempre -> se corta, no guarda datos ajenos", "SesionPerdida",
             cuit_datos_veces=9),
        caso("'Ver Pagos' muestra otro plan -> no guarda los planes, deja alerta y SCT queda", "OK",
             lambda r: "" if "mis_facilidades" not in r and "sct" in r
             and "otro plan" not in str(r.get("errores", {}).get("mf", "x")) and "muestra el plan" in
             str(r.get("errores", {}).get("mf", "")) else f"errores {r.get('errores')}",
             plan_ver_pagos="W026105"),
        caso("Empresa con clave del administrador: elige la empresa en SCT y en Mis Facilidades", "OK",
             chequeo_completo, usuario="20142836751"),
        caso("Empresa que no figura entre los representados -> se detiene sin reingresar", "ErrorRobot",
             usuario="20142836751", representa=False),
        caso("Sesión vence al abrir Cuentas Tributarias -> vuelve a entrar y completa", "OK",
             lambda r: "" if r["reingresos"] == 1 and len(r["sct"]["deudas"]) == 3 else f"reingresos {r['reingresos']}",
             sct_al_login=1),
        caso("Sesión vence a mitad de Mis Facilidades -> sigue desde ese plan", "OK",
             lambda r: "" if r["reingresos"] == 1 and len(r["mis_facilidades"]["vigentes"]) == 2 else
             f"reingresos {r['reingresos']} vigentes {[p['numero'] for p in r['mis_facilidades']['vigentes']]}",
             mf_vence_en=("V710205", "SeguimientoDetallePagos")),
        caso("Sesión vence una y otra vez -> se corta tras 3 reingresos", "SesionPerdida", sct_al_login=9),
    ])
    for root, _, files in os.walk(rsf.DATOS):
        for f in files:
            print("  archivo:", os.path.relpath(os.path.join(root, f), rsf.DATOS))
    sys.exit(0 if ok else 1)
