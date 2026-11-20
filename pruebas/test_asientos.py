"""Prueba de Asientos contables (pedido de Gaby 18-19/11/2026): sin ARCA, sin claves, sin internet.

Usa los números reales que mostró Gaby (RAPTOR.MAX SRL 10/2026, pagos de SIFERE) con datos simulados.
Uso:  python3 pruebas/test_asientos.py      (desde la carpeta que tiene robots/ y robots_web/)
"""
import io
import json
import os
import re
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, RAIZ)
R = tempfile.mkdtemp()
D = os.path.join(R, "datos")
os.makedirs(os.path.join(R, "publico"))
os.environ.update(ROBOTS_RAIZ=R, ROBOTS_WEB_DATOS=os.path.join(R, "web"), ROBOTS_WEB_HTTP="1", ROBOTS_DATOS=D,
                  ROBOTS_PUBLICO=os.path.join(R, "publico"), ROBOTS_BANDEJA=os.path.join(R, "bandeja"))
res = []


def ok(c, m):
    res.append(bool(c))
    print(("✔" if c else "✘"), m)


def escribir(ruta, d):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)


# ------------------------------------------------ lectores del robot SIFERE
from robots import robot_sifere as rs  # noqa: E402

TEXTO_DETALLE = """PEDRAZA GABRIELA ALEJANDRA (27-31445619-5) representando a RAPTOR.MAX SRL (30-71654889-5)
Información presentación CM03 (Jurisdicción 901 - Ciudad Autónoma de Buenos Aires)
Anticipo\t10/2026 - 0\tDatos Presentación (16/11/2026)\tCoef. Juris\t0,8452
Base Imponible e Impuesto a Liquidar
Art\tCod Act\tTF\tPpal\tDescripción de la Actividad\tBase Imponible\tAjte a la Base\tBase Imp Neta\tAlícuota\tImpuesto
2\t476320\t\t\tVenta al por menor de armas\t$28.749.303,20\t0,00\t$28.749.303,20\t3,00%\t$862.479,10
Liquidación Mensual
Impuesto determinado\t862.479,10
Saldo a Favor DDJJ anteriores (Ant 20260900 - Sec )\t3.080.479,93
Total Retenciones soportadas\t390.195,00
Total de Recaudaciones Bancarias soportadas\t0,00
Total Percepciones a deducir\t699.039,22
Total Percepciones Aduaneras a deducir\t0,00
Total de deducciones\t4.169.714,15
Subtotal a favor del contribuyente\t3.307.235,05
Subtotal a favor de la D.G.R.\t0,00
Total Otros Debitos\t0,00
Intereses\t0,00
Monto a Ingresar\t0,00
Subtotal 2 a favor del contribuyente\t3.307.235,05
Totales Generales
Total de Ingresos en el País\t34.014.793,18"""
liq = rs.leer_liquidacion(TEXTO_DETALLE)
ok(liq["determinado"] == 862479.10 and liq["saldo_favor_anterior"] == 3080479.93 and liq["retenciones"] == 390195.0
   and liq["recaudaciones_bancarias"] == 0.0 and liq["percepciones"] == 699039.22 and liq["monto_a_ingresar"] == 0.0
   and liq["coeficiente"] == 0.8452, "liquidación mensual de SIFERE (RAPTOR.MAX 10/2026, CABA)")
try:
    rs.leer_liquidacion("otra pantalla")
    ok(False, "pantalla equivocada frena")
except Exception:
    ok(True, "pantalla equivocada frena")

TABLA_PAGOS = [["Anticipo", "Formulario", "Forma Pago", "Banco / Sucursal", "Fecha Pago", "Impuesto", "Int/Recargo/Multa", "Total"],
               ["06/2024 - 0", "5869 - Vep Solo Pago - Sifere Web", "Efectivo", "7 - Banco de Galicia Y Buenos Aires S.a. / 1003",
                "17/07/2024", "$82.680,61", "$0,00", "$82.680,61"],
               ["08/2020 - 0", "5869 - Vep Solo Pago - Sifere Web", "Efectivo", "285 - Banco Macro S.a. / 1002", "20/10/2020",
                "$18.313,37", "$120,00", "$18.433,37"],
               ["Total", "", "", "", "", "$1.195.314,02", "$0,00", "$1.195.314,02"]]
pg = rs.leer_tabla_pagos(TABLA_PAGOS)
ok(len(pg) == 2 and pg[0]["banco"] == "Banco de Galicia Y Buenos Aires S.a." and pg[0]["fecha"] == "2024-07-17"
   and pg[0]["anticipo"] == "2024-06" and pg[1]["intereses"] == 120.0 and pg[1]["total"] == 18433.37,
   "tabla de pagos de SIFERE (banco, fecha, intereses; sin la fila de total)")

# ------------------------------------------------ F931 sin ART/SCVO y con sueldo no remunerativo (TALLPIR, 19/11/2026)
from robots.lector_f931 import leer_f931  # noqa: E402
_t = """C.U.I.T. 30-69962585-6  Rect. (1/9): 0  10/2026 Servicios Eventuales
Empleados en nómina: 2
Suma de Rem. 1: 0,00
a1 - Total de aportes S.S. 0,00
a1 - Total de aportes O.S. 0,00
Conceptos no remunerativos: 800.000,00
"""
_f = leer_f931(_t)
ok(_f["Periodo"] == "2026-10" and _f["Remuneración total (con no remunerativos)"] == 800_000.0 and _f["TOTAL CARGAS SOCIALES"] == 0.0
   and "ART (L.R.T. total)" in _f["Campos sin dato"], "F931 sin contrato LRT/SCVO y sueldo no remunerativo: se lee igual")
_viejo = """C.U.I.T. 30-51969833-8  Rect. (1/9): 1  09/2026 Servicios Eventuales
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
Total retenciones 0,00"""
_f = leer_f931(_viejo)
ok(_f["Remuneración total (Rem. 1)"] == 1_000_000.0 and _f["TOTAL CARGAS SOCIALES"] == 280_500.0 and "Campos sin dato" not in _f
   and _f["Control SIPA+NoSIPA"] == "OK", "F931 completo: mismos importes que antes")

# ------------------------------------------------ armado de asientos
C, C2 = "30716548895", "20208313771"
escribir(f"{R}/publico/clientes.json", [{"cuit": C, "razon_social": "RAPTOR.MAX SRL"}, {"cuit": C2, "razon_social": "VALGUARNERA HECTOR"}])
escribir(f"{D}/{C}/f931/2026-10.json", {"Periodo": "2026-10", "Remuneración total (Rem. 1)": 1_000_000.0,
                                        "Aportes S.S. (a1)": 110_000.0, "Aportes O.S. (a1)": 30_000.0,
                                        "TOTAL CARGAS SOCIALES": 265_000.0})
escribir(f"{D}/{C}/sifere/2026-10.json", {"periodo": "2026-10", "rectificativa": 0, "jurisdicciones": {
    "901": {"determinado": 862479.10, "a_pagar": 0.0, "liquidacion": liq},
    "902": {"determinado": 263274.50, "a_pagar": 0.0, "liquidacion_error": "ErrorRobot: no está el enlace"}}})
escribir(f"{D}/{C}/sifere/2026-09.json", {"periodo": "2026-09", "rectificativa": 1, "jurisdicciones": {
    "901": {"determinado": 100_000.0, "liquidacion": {"determinado": 100_000.0, "recaudaciones_bancarias": 10_000.0,
            "percepciones": 20_000.0, "percepciones_aduaneras": 5_000.0, "retenciones": 15_000.0,
            "saldo_favor_anterior": 0.0, "intereses": 0.0, "otros_debitos": 0.0, "monto_a_ingresar": 50_000.0}}}})
escribir(f"{D}/{C}/sifere/2026-08.json", {"periodo": "2026-08", "rectificativa": 0, "jurisdicciones": {
    "901": {"determinado": 100_000.0, "liquidacion": {"determinado": 100_000.0, "recaudaciones_bancarias": 10_000.0,
            "percepciones": 20_000.0, "retenciones": 15_000.0, "saldo_favor_anterior": 80_000.0,
            "intereses": 0.0, "otros_debitos": 0.0, "monto_a_ingresar": 0.0}}}})
escribir(f"{D}/{C}/arba/2026-10.json", {"periodo": "2026-10", "impuesto_determinado": 50_000.0})
escribir(f"{D}/{C}/sifere_pagos/2026-11-19.json", {"jurisdicciones": {
    "901": {"pagos": [{"anticipo": "2026-09", "fecha": "2026-10-16", "banco": "Banco de Galicia", "forma_pago": "Efectivo",
                       "impuesto": 50_000.0, "intereses": 0.0, "total": 50_000.0}]},
    "902": {"pagos": [{"anticipo": "2026-09", "fecha": "2026-10-16", "banco": "Banco de Galicia", "forma_pago": "Efectivo",
                       "impuesto": 7_000.0, "intereses": 300.0, "total": 7_300.0}]}}})

from robots_web import asientos, usuarios  # noqa: E402

su = asientos.armar(C, "sueldos")
s0 = su[0]
dl = {l["concepto"]: (l["debe"], l["haber"]) for l in s0["lineas"]}
ok(s0["balanceado"] and dl["sueldos"] == (1_000_000.0, 0) and dl["cargas_perdida"] == (265_000.0, 0)
   and dl["sueldos_a_pagar"] == (0, 860_000.0) and dl["cargas_a_pagar"] == (0, 405_000.0),
   "sueldos: remuneración y contribuciones al Debe; sueldos a pagar y total F.931 al Haber")

ib = {a["clave"]: a for a in asientos.armar(C, "iibb")}
a = ib["iibb:2026-10:901"]
dl = {l["concepto"]: (l["debe"], l["haber"]) for l in a["lineas"]}
ok(a["balanceado"] and dl["iibb_perdida:901"] == (862479.10, 0) and dl["percepciones:901"] == (0, 699039.22)
   and dl["retenciones:901"] == (0, 163439.88) and "sircreb:901" not in dl and "iibb_a_pagar:901" not in dl,
   "IIBB CABA 10/2026 como el ejemplo: percepciones 699.039,22 y retenciones 163.439,88")
a = ib["iibb:2026-09:901"]
dl = {l["concepto"]: (l["debe"], l["haber"]) for l in a["lineas"]}
ok(a["balanceado"] and dl["iibb_a_pagar:901"] == (0, 50_000.0) and dl["sircreb:901"] == (0, 10_000.0)
   and dl["percepciones:901"] == (0, 25_000.0) and dl["retenciones:901"] == (0, 15_000.0),
   "orden SIRCREB → percepciones (con aduaneras) → retenciones y saldo a pagar")
a = ib["iibb:2026-08:901"]
dl = {l["concepto"]: (l["debe"], l["haber"]) for l in a["lineas"]}
ok(a["balanceado"] and dl["retenciones:901"] == (0, 70_000.0) and any("saldo a favor" in n for n in a["notas"]),
   "faltante cubierto con saldo a favor anterior va a Retenciones")
ok(not ib["iibb:2026-10:902"]["balanceado"] and ib["iibb:2026-10:902"]["estado"] == "desbalanceado"
   and any("no está el enlace" in n for n in ib["iibb:2026-10:902"]["notas"]), "sin liquidación: queda desbalanceado con el motivo")
ok(not ib["iibb:2026-10:arba"]["balanceado"] and ib["iibb:2026-10:arba"]["diferencia"] == 50_000.0,
   "ARBA (solo determinado): desbalanceado a la espera de revisión")

pa = asientos.armar(C, "pagos")
ok(len(pa) == 1 and pa[0]["balanceado"] and pa[0]["haber"] == 57_300.0
   and {l["concepto"] for l in pa[0]["lineas"]} == {"iibb_a_pagar:901", "iibb_a_pagar:902", "intereses_iibb", "banco:Banco de Galicia"},
   "pago de SIFERE: un asiento por fecha y banco, una línea por jurisdicción e intereses aparte")
ok(su[0]["estado"] == "sin cuenta asignada", "sin equivalencias: 'sin cuenta asignada'")

# ------------------------------------------------ pantallas
from werkzeug.security import generate_password_hash  # noqa: E402

con = usuarios.conectar()
with con:
    for u, n, p, rol in (("gabriel", "Gabriel", "claveadmin123", "admin"), ("ana", "Ana", "claveana12345", "colaborador"),
                         ("beto", "Beto", "clavebeto12345", "colaborador")):
        con.execute("INSERT INTO usuarios (usuario,nombre,hash,rol,activo,creado) VALUES (?,?,?,?,1,'x')",
                    (u, n, generate_password_hash(p), rol))
usuarios.guardar_datos_cliente(C, {"encargado": "ana", "equipo": "beto"}, "gabriel")
from robots_web.app import app  # noqa: E402

app.config["TESTING"] = True


def login(cl, u, p):
    r = cl.get("/ingresar")
    tok = re.search(r'name="csrf" value="(\w+)"', r.text)[1]
    cl.post("/ingresar", data={"usuario": u, "clave": p, "csrf": tok})
    m = re.search(r'name="csrf" value="(\w+)"', cl.get("/mi-clave").text)
    return m[1] if m else tok


def token(html):
    return re.search(r'name="csrf" value="(\w+)"', html)[1]


ca = app.test_client()
ok(ca.get("/asientos").status_code == 302, "asientos pide ingresar")
login(ca, "ana", "claveana12345")
r = ca.get("/", follow_redirects=True)
ok("Asientos contables" in r.text, "botón 'Asientos contables' en el menú")
r = ca.get("/asientos", follow_redirects=True)
ok(r.status_code == 200 and all(t in r.text for t in ("Sueldos (F.931)", "Devengamiento IIBB", "Pagos de impuestos",
                                                       "Equivalencias de cuentas")), "submenú por tipo de asiento")
r = ca.get(f"/asientos/iibb?cuit={C}")
ok("DESBALANCEADO" in r.text and "163.439,88" in r.text, "pantalla IIBB con desbalanceados")
r = ca.get(f"/asientos/iibb?cuit={C}&ver=pendientes")
ok("RAPTOR" in r.text and "699.039,22" not in r.text, "filtro 'para revisar' deja solo los que hay que mirar")
r = ca.get(f"/asientos/cuentas?cuit={C}")
ok("iibb_perdida:901" in r.text and "banco:Banco de Galicia" in r.text, "equivalencias muestran los conceptos usados")
ca.post(f"/asientos/cuentas?cuit={C}", data={"csrf": token(r.text), "cuit": C, "cuenta_sueldos": "5.1.01 Sueldos",
                                             "cuenta_iibb_perdida:901": "5.2.01 IIBB CABA", "cuenta_<script>": "x"})
eq = asientos.cuentas(C)
ok(eq == {"sueldos": "5.1.01 Sueldos", "iibb_perdida:901": "5.2.01 IIBB CABA"}, "guarda equivalencias (ignora conceptos raros)")
r = ca.get(f"/asientos/sueldos?cuit={C}")
ok("5.1.01 Sueldos" in r.text, "el asiento usa la cuenta del cliente")
r = ca.get(f"/asientos/iibb?cuit={C}")
ca.post(f"/asientos/iibb?cuit={C}", data={"csrf": token(r.text), "cuit": C, "clave": "iibb:2026-10:arba", "marcar": "1",
                                          "nota": "completo a mano en SOS"})
ok(asientos.revisiones(C).get("iibb:2026-10:arba", {}).get("estado") == "revisado", "el encargado marca revisado con nota")
ok(ca.post(f"/asientos/iibb?cuit={C}", data={"csrf": "malo", "cuit": C, "clave": "iibb:2026-10:arba", "marcar": "0"}).status_code == 400,
   "revisión con CSRF")
x = ca.get(f"/asientos/iibb/excel?cuit={C}")
from openpyxl import load_workbook  # noqa: E402
wb = load_workbook(io.BytesIO(x.data))
txt = " ".join(str(c.value) for fila in wb.active.iter_rows() for c in fila if c.value is not None)
ok(x.status_code == 200 and "DESBALANCEADO" in txt and "5.2.01 IIBB CABA" in txt, "Excel con los asientos y los desbalanceados")

cb = app.test_client()
tok_b = login(cb, "beto", "clavebeto12345")
r = cb.get(f"/asientos/iibb?cuit={C}")
ok(r.status_code == 200 and "Marcar revisado" not in r.text, "el equipo ve pero no revisa (solo encargado o admin)")
ok(cb.post(f"/asientos/iibb?cuit={C}", data={"csrf": tok_b, "cuit": C, "clave": "iibb:2026-10:arba", "marcar": "0"}).status_code == 403,
   "el equipo no puede quitar la revisión")
ok(cb.get(f"/asientos/sueldos?cuit={C2}").status_code == 403, "no ve asientos de clientes que no lleva")
cg = app.test_client()
login(cg, "gabriel", "claveadmin123")
ok("Marcar revisado" in cg.get(f"/asientos/sueldos?cuit={C}").text, "el admin revisa cualquier cliente")
ok(cg.get(f"/asientos/sueldos?cuit={C2}").status_code == 200, "cliente sin datos no rompe")
ok(cg.get("/asientos/otro").status_code == 404, "tipo desconocido = 404")

# ------------------------------------------------ saldos a recuperar (S.L.D. -> F.399), 19/11/2026
escribir(f"{D}/{C}/sct_historico/2026-11-19.json", {"fecha": "2026-11-19", "anios": [], "deudas": [], "deuda_total": 0.0, "deuda_arca": 0.0, "deuda_terceros": 0.0,
         "deuda_f931_otros": 0.0, "por_impuesto": {},
         "saldos_recuperar": [{"impuesto": "302", "nombre": "APORTES OBRAS SOCIALES", "periodo": "20260500", "concepto": "DDJJ",
                               "sld": 45210.5, "anio": "2026"}], "saldos_recuperar_total": 45210.5})
r = cg.get(f"/cliente/{C}/historica")
ok(r.status_code == 200 and "F.399" in r.text and "45.210,50" in r.text and "05/2026" in r.text,
   "deuda histórica muestra los saldos a recuperar con el F.399")
ok("Saldos a recuperar (F.399)" in cg.get("/alertas").text, "alerta del día para el encargado")
ok("crédito a recuperar (F.399): $ 45.210,50" in cg.get(f"/cliente/{C}").text, "tablero: renglón 'crédito a recuperar' en Deuda ARCA")

# ------------------------------------------------ F.931 con personal y sin remuneración: lo completa el encargado
escribir(f"{D}/{C}/f931/_lista.json", {"2026-10": {"empleados": 2, "estado": "OK"},
                                       "2026-09": {"empleados": 2, "estado": "no se pudo leer (No se encontró: ...)"}})
pend = asientos.f931_pendientes(C)
ok([x["periodo"] for x in pend] == ["2026-09"], "F.931: detecta el mes con personal y sin remuneración leída")
ok("F.931 para completar" in cg.get("/alertas").text, "alerta del día 'F.931 para completar'")
r = ca.get(f"/asientos/sueldos?cuit={C}")
ok("F.931 para completar" in r.text and "09/2026" in r.text, "pantalla Sueldos muestra el mes para completar")
ca.post(f"/asientos/sueldos?cuit={C}", data={"csrf": token(r.text), "cuit": C, "accion": "f931_manual", "periodo": "2026-09",
                                            "remuneracion": "800.000,00", "cargas": "", "aportes": "", "nota": "directores"})
su = {a["periodo"]: a for a in asientos.armar(C, "sueldos")}
ok(not asientos.f931_pendientes(C) and su["2026-09"]["debe"] == 800_000.0 and su["2026-09"]["balanceado"]
   and any("a mano" in n for n in su["2026-09"]["notas"]), "el encargado lo completa y sale el asiento de sueldos")
from robots_web import analisis  # noqa: E402
_rm = {m["periodo"]: m for m in analisis.resultado_mensual(C)}
ok(_rm.get("2026-09", {}).get("sueldos") == 800_000.0, "la relación débito/crédito toma la carga manual")
ok(cb.post(f"/asientos/sueldos?cuit={C}", data={"csrf": tok_b, "cuit": C, "accion": "f931_manual", "periodo": "2026-08",
                                               "remuneracion": "1"}).status_code == 403, "el equipo no carga F.931 a mano")

# ------------------------------------------------ AGIP / ARBA: deuda y saldo a favor -> encargado (20/11/2026)
from robots import robot_agip as _ra, robot_arba_dfe as _rad  # noqa: E402
_cct = {"saldo_deudor": 2133601.0, "nominal": 2133601.0, "intereses": 885569.26, "saldo_favor": 26303826.11,
        "faltas_presentacion": 71, "notificaciones_no_leidas": 8,
        "impuestos": [{"impuesto": "IIBB - Convenio Multilateral", "adeudado": 0.0, "a_favor": 26303826.11},
                      {"impuesto": "Automotor", "adeudado": 3019167.35, "a_favor": 0.0}]}
escribir(f"{D}/{C}/agip/2026-11-20/resultado.json", {"fecha": "2026-11-20", "cct": _cct, "servicios": {"cct": "OK"},
                                                     "comunicaciones": [], "deuda": {"total": None, "tablas": []},
                                                     "alertas": _ra.alertas_cct(_cct)})
_cta = _rad.leer_cuenta("Mi cuenta corriente\nDeuda\nSaldo a favor\n1\nIngresos Brutos\n$ 10.613.047,90\nJuicios\n$ 0,00\n"
                        "4\nSellos\n$ 0,00\n$ 0,00\nTOTALES\n$ 10.613.047,90\n$ 0,00")
escribir(f"{D}/{C}/arba_dfe/2026-11-20/resultado.json", {"fecha": "2026-11-20", "organismo": "ARBA", "comunicaciones": [],
                                                         "cuenta": _cta, "alertas": _rad.alertas_cuenta(_cta)})
r = cg.get("/alertas").text
ok("AGIP: compensar deuda con saldo a favor" in r and "ARBA: deuda en juicio" in r, "alertas del día: compensar en AGIP y juicio en ARBA")
r = cg.get(f"/cliente/{C}/historica").text
ok("AGIP: saldo a favor para recuperar" in r and "Visto, me ocupo" in r, "el encargado lo ve en la ficha y lo marca visto")
r = cg.get(f"/cliente/{C}/agip").text
ok("26.303.826,11" in r and "Automotor" in r, "ficha AGIP muestra la Cuenta Corriente Tributaria")
from robots import avisos as _av  # noqa: E402
_av.DATOS = D
ok({x["tema"] for x in _av.revisiones(C)} >= {"AGIP: compensar deuda con saldo a favor", "ARBA: deuda en juicio", "Saldos a recuperar (F.399)"},
   "mail al encargado: AGIP, ARBA y F.399")

# ------------------------------------------------ ventas sin IVA (alquileres de vivienda, Humaitá 20/11/2026)
from robots import lector_libro_iva as _li  # noqa: E402
_c = _li._comprobante({"Tipo de Comprobante": "6", "Importe Total": "500000,00", "Importe de Operaciones Exentas": "500000,00",
                       "Nro. Doc. Comprador": "20111111112"}, "Comprador")
ok(_c["exento"] == 500000.0, "Libro IVA: toma el exento aunque la columna tenga otro título")
_r = _li._resumir([_li._comprobante({"Tipo de Comprobante": "11", "Importe Total": "300000,00"}, "Comprador")], "2026-10", compras=False)
ok(_r["Otras ventas sin IVA (sin desglose)"] == 300000.0, "Libro IVA: factura sin desglose cuenta como venta sin IVA")
escribir(f"{D}/{C2}/libro_iva/2026-10.json", {"periodo": "2026-10", "ventas": {"Neto gravado total": 0.0, "Exento": 0.0, "No gravado": 0.0},
         "compras": {"Neto gravado total": 100_000.0, "Exento": 0.0, "No gravado": 0.0},
         "comprobantes_ventas": [{"tipo": 11, "neto": 0.0, "iva": 0.0, "total": 400_000.0}]})
_rm = {m["periodo"]: m for m in analisis.resultado_mensual(C2)}
ok(_rm["2026-10"]["ventas"] == 400_000.0 and _rm["2026-10"]["resultado"] > 0,
   "relación D/C: alquileres sin IVA entran en ventas (Libro IVA bajado antes del arreglo)")

# ------------------------------------------------ dos fuentes de la relación D/C (Benavidez, 20/11/2026)
from robots import conciliacion as _co  # noqa: E402
_co.DATOS = D
escribir(f"{D}/{C2}/libro_iva/2026-09.json", {"periodo": "2026-09", "ventas": {"Neto gravado total": 1_000_000.0},
         "compras": {"Neto gravado total": 500_000.0}, "comprobantes_ventas": []})
os.makedirs(f"{D}/{C2}/2026-08", exist_ok=True)                         # mes con Mis Comprobantes y sin Libro IVA
_mc = {"2026-09": {"ventas": 1_300_000.0, "compras": 500_000.0}, "2026-10": {"ventas": 400_000.0, "compras": 100_000.0},
       "2026-08": {"ventas": 1.0, "compras": 1.0}}
_co._mc_totales = lambda cuit, per: _mc.get(per)
escribir(f"{D}/{C2}/libro_iva/2026-10.json", {"periodo": "2026-10", "ventas": {"Neto gravado total": 876_446.28, "Exento": 0.0, "No gravado": 0.0},
         "compras": {"Neto gravado total": 100_000.0, "Exento": 0.0, "No gravado": 0.0},
         "comprobantes_ventas": [{"tipo": 11, "punto_venta": 2, "neto": 0.0, "iva": 0.0, "total": 400_000.0},
                                 {"tipo": 83, "punto_venta": 7, "neto": 826_446.28, "iva": 173_553.72, "total": 1_000_000.0},
                                 {"tipo": 60, "punto_venta": 9, "neto": 50_000.0, "iva": 10_500.0, "total": 60_500.0}]})
_co._pv_mc = lambda cuit: {2}
_fu = _co.comparar_fuentes(C2, {"no_declaradas": [{"Período MC": "2026-09", "Comprobante": "Factura A", "Pto. venta": 3,
                                                   "Número": 99, "Receptor": "X", "Total MC": 363000.0}]}, {})
_e = {f["periodo"]: f for f in _fu["meses"]}
ok(_e["2026-09"]["estado"] == "DIFERENCIA" and _e["2026-10"]["estado"] == "OK" and _e["2026-08"]["estado"].startswith("no comparable")
   and _e["2026-09"]["solo_en_una"], "Libro IVA vs Mis Comprobantes: diferencia > 2 % / $25.000, 'no comparable' si falta una fuente")
ok(_e["2026-10"]["tiques"] == 876_446.28 and _e["2026-10"]["tiques_pv"] == [7, 9] and _e["2026-10"]["estado"] == "OK",
   "tiques (ticketeadora) y líquido producto se descuentan: no suben a Mis Comprobantes (Goncalves)")
r = cg.get(f"/cliente/{C2}/relacion").text
ok("Revisión cruzada" in r and "DIFERENCIA" in r and "no comparable" in r and "Saldo con Mis Comprobantes" in r,
   "relación D/C: tabla de revisión cruzada y saldo con la segunda fuente")
ok("Relación D/C: las dos fuentes no coinciden" in cg.get("/alertas").text, "alerta si las fuentes no coinciden")
r = cg.get(f"/cliente/{C2}").text
ok("IVA: débito / crédito fiscal" in r and ("datos incompletos" in r or "índice erogaciones/ventas" in r),
   "tarjetas sin la 'utilidad' contradictoria; datos incompletos a la vista")

# ------------------------------------------------ Deuda ARCA cuando Cuentas Tributarias falló (Benavidez)
import glob as _g  # noqa: E402
escribir(f"{D}/{C2}/ccma/2026-11-20.json", {"fecha": "2026-11-20", "deuda_impaga": 248283.0, "impagos": [{"periodo": "2026-08"}],
                                                      "periodos": [], "totales": {}, "alertas": []})
r = cg.get(f"/cliente/{C2}").text
ok("Cuentas Tributarias sin leer" in r and "248.283,00" in r, "Deuda ARCA: muestra autónomos impagos aunque falle Cuentas Tributarias")

# ------------------------------------------------ corregir razón social: solo admin (20/11/2026)
r = cg.get(f"/cliente/{C2}/datos")
cg.post(f"/cliente/{C2}/datos", data={"csrf": token(r.text), "razon_social": "VALGUARNERA HECTOR OSCAR"})
ok(any(c["razon_social"] == "VALGUARNERA HECTOR OSCAR" for c in __import__("robots_web.datos", fromlist=["x"]).lista_clientes()),
   "el admin corrige la razón social y se ve enseguida")
_rb = cb.get(f"/cliente/{C}/datos")
cb.post(f"/cliente/{C}/datos", data={"csrf": tok_b, "razon_social": "OTRO NOMBRE"})
ok(not any(c["razon_social"] == "OTRO NOMBRE" for c in __import__("robots_web.datos", fromlist=["x"]).lista_clientes()),
   "un colaborador no puede cambiar la razón social")

# ------------------------------------------------ asignar clientes uno mismo (19/11/2026)
C3 = "27169781295"
escribir(f"{R}/publico/clientes.json", [{"cuit": C, "razon_social": "RAPTOR.MAX SRL"}, {"cuit": C2, "razon_social": "VALGUARNERA HECTOR"},
                                        {"cuit": C3, "razon_social": "ACUÑA ANA MARIA"}])
with usuarios.conectar() as con:
    con.execute("INSERT INTO usuarios (usuario,nombre,hash,rol,activo,creado) VALUES ('mariela','Mariela',?,'colaborador',1,'x')",
                (generate_password_hash("clavemariela123"),))
cd = app.test_client()
tok_d = login(cd, "beto", "clavebeto12345")
r = cd.get("/asignar")
ok(r.status_code == 200 and "VALGUARNERA" in r.text and "ACUÑA" in r.text and "RAPTOR" not in r.text,
   "asignar: un colaborador ve los clientes SIN encargado (aunque no los lleve)")
ok("Asignar clientes" in cd.get("/mas").text, "botón en Más")
cd.post("/asignar", data={"csrf": tok_d, "cuit": [C2, C3], "encargado": "mariela", "modo": "encargado"})
ok(usuarios.datos_cliente(C2).get("encargado") == "mariela" and usuarios.datos_cliente(C3).get("encargado") == "mariela",
   "Beto deja a Mariela como encargada de dos clientes")
cd.post("/asignar", data={"csrf": tok_d, "cuit": [C2], "encargado": "beto", "modo": "encargado"})
ok(usuarios.datos_cliente(C2).get("encargado") == "mariela", "no puede pisar un encargado ya puesto (eso es del admin)")
cd.post("/asignar", data={"csrf": tok_d, "cuit": [C2], "encargado": "beto", "modo": "equipo"})
ok("beto" in usuarios.datos_cliente(C2).get("equipo", "") and cd.get(f"/cliente/{C2}").status_code == 200,
   "se suma al equipo y desde ahí ve el cliente")
ok(cd.post("/asignar", data={"csrf": "malo", "cuit": [C3], "encargado": "beto", "modo": "encargado"}).status_code == 400,
   "asignar con CSRF")
cd.post("/asignar", data={"csrf": tok_d, "cuit": [C3], "encargado": "fantasma", "modo": "encargado"})
ok(usuarios.datos_cliente(C3).get("encargado") == "mariela", "no acepta usuarios inexistentes")
cg2 = app.test_client()
tok_g = login(cg2, "gabriel", "claveadmin123")
cg2.post("/asignar", data={"csrf": tok_g, "cuit": [C3], "encargado": "ana", "modo": "encargado"})
ok(usuarios.datos_cliente(C3).get("encargado") == "ana", "el admin sí cambia un encargado")

print(f"\n{sum(res)}/{len(res)} OK")
sys.exit(0 if all(res) else 1)
