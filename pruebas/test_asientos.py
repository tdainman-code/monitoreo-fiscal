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

print(f"\n{sum(res)}/{len(res)} OK")
sys.exit(0 if all(res) else 1)
