"""Prueba de la web v2.4 (lo traído de Radar fiscal) con datos de ejemplo: sin ARCA, sin claves, sin internet.

Arma datos simulados de 3 clientes (situación fiscal simulada, Libro IVA y F.931 de 12 meses, DFE de ARCA y AGIP,
fiscalizaciones) y recorre todas las pantallas nuevas y las de antes.
Uso:  python3 pruebas/test_web_radar.py      (desde la carpeta que tiene robots/ y robots_web/)
"""
import json
import os
import re
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
R = tempfile.mkdtemp()
D = os.path.join(R, "datos")
os.makedirs(D)
BANDEJA = os.path.join(R, "bandeja")
os.makedirs(os.path.join(BANDEJA, "pedidos"))
sys.path.insert(0, os.path.join(RAIZ, "robots", "pruebas"))
sys.path.insert(0, RAIZ)
import test_situacion_simulado as t  # noqa: E402

t.rsf.DATOS = D
t.caso("datos de ejemplo", "OK", t.chequeo_completo)
C = t.CUIT                              # cliente 1: situación simulada + IVA sano
C2, C3 = "30717468631", "27169781295"   # cliente 2: D/C crítica + AGIP + fiscalización; cliente 3: sin datos


def escribir(ruta, d):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)


def meses(n=12, hasta=(2026, 10)):
    a, m = hasta
    out = []
    for _ in range(n):
        out.append(f"{a}-{m:02d}")
        a, m = (a - 1, 12) if m == 1 else (a, m - 1)
    return sorted(out)


for i, per in enumerate(meses()):
    # cliente 1: ventas que crecen, D/C ~ 1,6
    escribir(f"{D}/{C}/libro_iva/{per}.json", {
        "periodo": per, "ventas": {"Total IVA": 210_000 + i * 5_000, "Neto gravado total": 1_000_000 + i * 25_000, "Exento": 0, "No gravado": 0},
        "compras": {"Crédito fiscal computable": 130_000, "Neto gravado total": 620_000, "Exento": 10_000, "No gravado": 0,
                    "Comprobantes B/C (sin IVA discriminado)": 20_000}})
    escribir(f"{D}/{C}/f931/{per}.json", {"Remuneración total (Rem. 1)": 300_000, "Total aportes (retenidos al empleado)": 51_000,
                                           "TOTAL CARGAS SOCIALES": 80_000})
    # cliente 2: crédito mayor que débito (D/C ~ 0,5) y resultado negativo; falta el F.931 de 2 meses
    escribir(f"{D}/{C2}/libro_iva/{per}.json", {
        "periodo": per, "ventas": {"Total IVA": 100_000, "Neto gravado total": 476_190, "Exento": 0, "No gravado": 0},
        "compras": {"Crédito fiscal computable": 200_000, "Neto gravado total": 952_380, "Exento": 0, "No gravado": 0}})
    if i < 10:
        escribir(f"{D}/{C2}/f931/{per}.json", {"Remuneración total (Rem. 1)": 100_000, "Total aportes (retenidos al empleado)": 17_000,
                                                "TOTAL CARGAS SOCIALES": 27_000})

escribir(f"{D}/{C}/dfe/2026-11-15/resultado.json", {
    "total": 2, "sin_abrir": 1, "altas_sin_abrir": 1, "alertas": [{"prioridad": "ALTA", "tipo": "DFE", "texto": "Seclo SIN ABRIR"}],
    "comunicaciones": [{"fecha": "13/11/2026", "notificado": None, "leida": False, "organismo": "Trabajo",
                        "asunto": "Notificaciones Seclo", "clasificacion": "x", "importancia": "ALTA"},
                       {"fecha": "10/11/2026", "notificado": "11/11/2026", "leida": True, "organismo": "ARCA",
                        "asunto": "Aviso de vencimiento", "clasificacion": "y", "importancia": "Media"}]})
escribir(f"{D}/{C2}/agip/2026-11-15/resultado.json", {
    "cuit": C2, "fecha": "2026-11-15", "servicios": {"dfe": "OK (1 filas)", "deuda": "OK (2 filas)", "fiscalizacion": "OK (1 filas)"},
    "comunicaciones": [{"fecha": "12/11/2026", "organismo": "AGIP", "asunto": "Intimación de pago ISIB", "estado": "Sin notificar",
                        "importancia": "ALTA", "leida": False, "clasificacion": "Intimación", "impuesto": "ISIB"}],
    "sin_abrir": 1, "altas_sin_abrir": 1,
    "deuda": {"total": 250_000.0, "tablas": [{"encabezados": ["Impuesto", "Período", "Total"],
                                              "filas": [["ISIB", "2026-08", "150.000,00"], ["ISIB", "2026-09", "100.000,00"]]}]},
    "fiscalizacion": [["FE-2026-123", "En curso", "ISIB"]],
    "fiscalizacion_tablas": [{"encabezados": ["Número", "Estado", "Impuesto"], "filas": [["FE-2026-123", "En curso", "ISIB"]]}],
    "alertas": [{"prioridad": "ALTA", "tipo": "AGIP: fiscalización electrónica", "texto": "1 registro(s)"}]})
escribir(f"{D}/{C2}/fiscalizaciones/2026-11-15.json", {
    "cuit": C2, "fecha": "2026-11-15", "servicios": {"ordenes_intervencion": "OK (1 filas)", "siace": "sin servicio",
                                                    "fiscalizacion_electronica": "sin servicio"},
    "en_curso": [{"Número": "OI 1.234.567", "Estado": "En curso", "Inspector": "PÉREZ"}], "verificaciones": [], "siace": [],
    "fiscalizacion_electronica": [], "alertas": [{"prioridad": "ALTA", "tipo": "Fiscalización en curso", "texto": "1 OI"}]})

os.makedirs(f"{R}/informes/2026-11-15")
open(f"{R}/informes/2026-11-15/situacion_fiscal_{C}.xlsx", "wb").write(b"PK\x03\x04prueba")
os.makedirs(f"{R}/publico")
escribir(f"{R}/publico/clientes.json", [{"cuit": C, "razon_social": "GONCALVES VICENTE JUAN JOSE", "estado_arca": "OK"},
                                        {"cuit": C2, "razon_social": "BH SOLUCIONES EMPRESARIALES"},
                                        {"cuit": C3, "razon_social": "ACUÑA ANA MARIA"}])
open(f"{R}/ejecuciones.jsonl", "w").write(json.dumps({"fecha": "2026-11-15T21:31:00", "robot": "todo", "cuit": C,
                                                      "estado": "OK", "alertas": 29}) + "\n")
os.environ.update(ROBOTS_RAIZ=R, ROBOTS_WEB_DATOS=os.path.join(R, "web"), ROBOTS_WEB_HTTP="1", ROBOTS_BANDEJA=BANDEJA,
                  ROBOTS_DATOS=D, ROBOTS_PUBLICO=os.path.join(R, "publico"))

from werkzeug.security import generate_password_hash  # noqa: E402

from robots_web import analisis, datos, usuarios  # noqa: E402

con = usuarios.conectar()
with con:
    for u, n, p, rol in (("gabriel", "Gabriel", "claveadmin123", "admin"), ("ana", "Ana", "claveana12345", "colaborador"),
                         ("beto", "Beto", "clavebeto12345", "empleado")):
        con.execute("INSERT INTO usuarios (usuario,nombre,hash,rol,activo,creado) VALUES (?,?,?,?,1,'x')",
                    (u, n, generate_password_hash(p), rol))
for _c in (C, C2, C3):                       # Ana lleva los tres clientes de ejemplo (en el equipo, sin ser encargada)
    usuarios.guardar_datos_cliente(_c, {"equipo": "ana"}, "gabriel")
from robots_web.app import app  # noqa: E402

app.config["TESTING"] = True
res = []


def ok(c, m):
    res.append(bool(c))
    print(("✔" if c else "✘"), m)


def login(cl, u, p):
    r = cl.get("/ingresar")
    tok = re.search(r'name="csrf" value="(\w+)"', r.text)[1]
    return cl.post("/ingresar", data={"usuario": u, "clave": p, "csrf": tok}), tok


def token(html):
    return re.search(r'name="csrf" value="(\w+)"', html)[1]


# ------------------------------------------------ cálculos
iva = analisis.iva_mensual(C)
rt = analisis.ratio_dc(iva)
ok(len(iva) == 12 and rt["nivel"] == "Adecuado" and 1.5 < rt["ratio"] < 2.2, f"relación D/C cliente sano ({rt['ratio']:.2f})")
rt2 = analisis.ratio_dc(analisis.iva_mensual(C2))
ok(rt2["nivel"] == "Crítico" and abs(rt2["ratio"] - 0.5) < 0.01, f"relación D/C crítica ({rt2['ratio']:.2f})")
pr = analisis.proyectar_iva(iva)
ok(pr["periodo"] == "2026-11" and abs(pr["debito"] - 270_000) < 2 and pr["credito"] == 130_000, f"proyección {pr['periodo']} débito {pr['debito']}")
ok(analisis.proyectar_iva(iva[:2]) is None, "sin proyección con menos de 3 meses")
r1 = analisis.analizar_resultado(analisis.resultado_mensual(C))
m0 = r1["meses"][0]
ib0 = m0["iibb"] or 0
ok(abs(m0["ventas"] - 1_000_000) < 1 and abs(m0["compras"] - 650_000) < 1 and abs(m0["sueldos"] - 300_000) < 1
   and abs(m0["cargas"] - 80_000) < 1 and abs(m0["erogaciones"] - (1_030_000 + ib0)) < 1
   and abs(m0["resultado"] + 30_000 + ib0) < 1 and abs(m0["indice"] - m0["erogaciones"] / 1_000_000) < 1e-9
   and abs(m0["margen"] - (1 - m0["indice"])) < 1e-9, f"relación D/C de un mes como la planilla ({m0['resultado']:,.0f}, índice {m0['indice']:.3f})")
ok(abs(r1["meses"][1]["indice_acumulado"] - (r1["meses"][0]["erogaciones"] + r1["meses"][1]["erogaciones"])
       / (r1["meses"][0]["ventas"] + r1["meses"][1]["ventas"])) < 1e-9
   and abs(r1["meses"][1]["saldo_acumulado"] - (r1["meses"][0]["resultado"] + r1["meses"][1]["resultado"])) < 1e-6,
   "saldo acumulado e índice acumulado")
ok(r1["total"]["resultado"] > 0 and any("sube" in c for c in r1["conclusiones"]), "resultado 12 meses y tendencia en palabras")
r2 = analisis.analizar_resultado(analisis.resultado_mensual(C2))
ok(r2["total"]["resultado"] < 0 and len(r2["incompletos"]) == 2 and any("NEGATIVO" in c for c in r2["conclusiones"]),
   "resultado negativo y meses incompletos (falta F.931)")
import shutil  # noqa: E402
r3 = analisis.resultado_mensual(C3)
os.makedirs(f"{D}/{C3}/libro_iva", exist_ok=True)
shutil.copy(f"{D}/{C2}/libro_iva/2026-10.json", f"{D}/{C3}/libro_iva/2026-10.json")
r3 = analisis.analizar_resultado(analisis.resultado_mensual(C3))
ok(r3["meses"][0]["completo"] and any("sin empleados" in c for c in r3["conclusiones"]), "sin F.931 = sin empleados (no incompleto)")
shutil.rmtree(f"{D}/{C3}/libro_iva")
ok(r2["mejor"]["completo"] and r2["peor"]["completo"], "mejor y peor mes se eligen entre los completos")
svg = analisis.grafico_iva(iva, pr)
ok(svg.startswith("<svg") and svg.count("<rect") == 26 and "nov-26*" in svg, "gráfico SVG con el mes proyectado")
ok(analisis.tendencia([1, 2, 3])[1] == 4, "tendencia lineal")

# ------------------------------------------------ pantallas
cl = app.test_client()
ok(cl.get("/cartera/dfe").status_code == 302, "cartera pide ingresar")
r, _ = login(cl, "ana", "claveana12345")
r = cl.get("/")
ok("BH SOLUCIONES" in r.text and r.text.count("punto rojo") >= 2, "panel con semáforo (incluye D/C crítica / AGIP)")
ok("relación D/C crítica" in r.text or "aviso(s) de AGIP" in r.text, "motivo del rojo nuevo en el panel")
r = cl.get(f"/cliente/{C2}")
r2 = cl.get(f"/cliente/{C2}/relacion")
ok(r2.status_code == 200 and all(t in r2.text for t in ("Cargas sociales (F.931)", "Total erogaciones", "SALDO MENSUAL",
   "Índice erogaciones / ventas", "Índice acumulado", "Margen de utilidad bruto", "IIBB determinado")),
   "relación débito crédito: cuadro como la planilla (erogaciones, saldo, índices y margen)")
escribir(f"{D}/{C}/ccma/2026-11-17.json", {"cuit": C, "fecha": "2026-11-17", "totales": {"deudor": 120036.74, "deudor_obligacion": 120000.0,
         "deudor_accesorios": 36.74, "acreedor": 0.0, "tipo": "MONOTRIBUTISTA"},
         "periodos": [{"periodo": "09/2026", "impuestos": "MON", "vencimiento": "2026-10-20", "obligacion": 120000.0, "pagado": 0.0,
                       "saldo": -120000.0, "estado": "IMPAGO", "dias_vencido": 28}],
         "impagos": [{"periodo": "09/2026", "saldo": -120000.0}], "deuda_impaga": 120000.0,
         "alertas": [{"prioridad": "ALTA", "tipo": "Autónomos / Monotributo impago", "texto": "Monotributista: 1 período(s) impago(s) (09/2026)"}]})
_rc = cl.get(f"/cliente/{C}/ccma").text
ok("09/2026" in _rc and "IMPAGO" in _rc and "120.000,00" in _rc and "28 días" in _rc, "autónomos / monotributo: períodos impagos")
_f = cl.get(f"/cliente/{C}").text
ok("Autónomos / Monotributo" in _f and "1 período(s) impago(s)" in _f, "ficha: tarjeta de autónomos / monotributo")
ok("Autónomos / Monotributo impago" in cl.get("/alertas").text, "alertas del día: monotributo impago")
os.remove(f"{D}/{C}/ccma/2026-11-17.json")
# deuda histórica: Convenio + Cuentas Tributarias, con "visto, me ocupo" del encargado
escribir(f"{D}/{C}/sifere_deuda/2026-11-17.json", {"fecha": "2026-11-17", "desde": "2014-01", "hasta": "2026-10", "deuda_total": 9000.0,
         "jurisdicciones": {"901": {"nombre": "Ciudad Autónoma de Buenos Aires", "deuda": 9000.0, "impagos": 2, "saldo_contribuyente": 74849.8,
             "anticipos": [{"anticipo": "2019-03", "saldo_fisco": 5000.0, "saldo_contribuyente": 0, "pagado_ddjj": 0, "pagado_otro": 0, "impago": 5000.0, "estado": "IMPAGO"},
                           {"anticipo": "2019-04", "saldo_fisco": 4000.0, "saldo_contribuyente": 0, "pagado_ddjj": 0, "pagado_otro": 0, "impago": 4000.0, "estado": "IMPAGO"}]}}})
escribir(f"{D}/{C}/sct_historico/2026-11-17.json", {"fecha": "2026-11-17", "deuda_total": 6362.93, "deuda_f931_otros": 6362.93,
         "por_impuesto": {"302 - APORTES OBRAS SOCIALES": 6362.93},
         "anios": [{"anio": "2026", "totales": {"deuda": 22105640.35, "sld": 0.0, "saldo_tecnico": 2918725.52, "otros_creditos": 597411.24, "multas_no_firmes": 0.0}}],
         "deudas": [{"impuesto": "302", "nombre": "APORTES OBRAS SOCIALES", "periodo": "20260100", "concepto": "Intereses resarcitorios",
                     "deuda": 6362.93, "color": "verde", "estado_pago": "", "f931": True, "anio": "2026"}]})
_s = datos.situacion(C)
ok(len(_s["revisar"]) == 2 and _s["semaforo"] == "rojo", "deuda histórica (Convenio y SCT) queda para revisar por el encargado")
_r = cl.get(f"/cliente/{C}/iibb").text
ok("Visto, me ocupo" in _r and "74.849,80" in _r, "Convenio: botón 'Visto, me ocupo' y saldo a favor que puede compensar")
_h = cl.get(f"/cliente/{C}/historica").text
ok("302 APORTES OBRAS SOCIALES" in _h and "F.931" in _h and "22.105.640,35" in _h, "deuda histórica de Cuentas Tributarias por año e impuesto")
ok("Deuda histórica para revisar (2)" in cl.get("/avisos?ver=todos").text, "avisos: lista de deudas históricas para revisar")
_cl = [x["clave"] for x in _s["revisar"]]
cl.post("/revision/visto", data={"clave": _cl[0], "cuit": C, "marcar": "1", "nota": "compensada con saldo a favor", "csrf": token(_r)})
_s = datos.situacion(C)
ok(len(_s["revisar"]) == 1 and any(x["visto"] and x["visto"]["nota"].startswith("compensada") for x in _s["revisiones"]),
   "marcada vista con nota: sale de pendientes")
ok("compensada con saldo a favor" in cl.get(f"/cliente/{C}/iibb").text, "la ficha muestra quién la vio y la nota")
ok(cl.post("/revision/visto", data={"clave": "cm:99999999999:x", "cuit": C, "marcar": "1", "csrf": token(_r)}).status_code == 400,
   "visto: clave de otro cliente rechazada")
for _x in ("sifere_deuda", "sct_historico"):
    os.remove(f"{D}/{C}/{_x}/2026-11-17.json")
# cada colaborador ve solo sus clientes; los administradores ven todo (18/11/2026)
cb = app.test_client()
login(cb, "beto", "clavebeto12345")
ok({u[0]: u[2] for u in usuarios.listar()}["beto"] == "colaborador", "el rol viejo 'empleado' pasa a 'colaborador'")
_i = cb.get("/").text
ok("0 cliente(s) que llevás vos" in _i and "no tenés clientes asignados" in _i, "colaborador sin clientes asignados no ve ninguno")
ca = app.test_client()
login(ca, "gabriel", "claveadmin123")
_r = ca.get(f"/cliente/{C2}/datos")
ok('name="encargado"' in _r.text and 'name="equipo"' in _r.text, "administrador: asigna encargado y equipo")
ca.post(f"/cliente/{C2}/datos", data={"csrf": token(_r.text), "encargado": "beto", "equipo": ["ana", "fantasma"]})
_d = usuarios.datos_cliente(C2)
ok(_d["encargado"] == "beto" and _d["equipo"] == "ana", "encargado Beto, equipo Ana (usuarios inexistentes descartados)")
_i = cb.get("/").text
ok("BH SOLUCIONES" in _i and "1 cliente(s) que llevás vos" in _i, "Beto ve solo el cliente que lleva")
ok(cb.get(f"/cliente/{C}").status_code == 403 and cb.get(f"/cliente/{C}/deuda").status_code == 403,
   "Beto no puede abrir un cliente que no lleva (ni por la dirección)")
_tk = token(cb.get(f"/cliente/{C2}").text)
ok(cb.post(f"/cliente/{C}/pedir", data={"csrf": _tk, "robot": "todo"}).status_code == 403, "ni pedir corridas de otro cliente")
ok(cb.post(f"/cliente/{C}/nota", data={"csrf": _tk, "texto": "x"}).status_code == 403, "ni dejar notas en otro cliente")
_otro = f"{C[:2]}-{C[2:10]}-{C[10]}"
ok(f"/cliente/{C}" not in cb.get("/alertas").text and f"/cliente/{C}" in ca.get("/alertas").text, "alertas del día: solo de sus clientes")
ok(all(f"/cliente/{C}" not in cb.get(f"/cartera/{v}").text for v in ("deudas", "dfe", "iva", "planes")), "cartera: solo sus clientes")
_r = cb.get(f"/cliente/{C2}/datos")
cb.post(f"/cliente/{C2}/datos", data={"csrf": token(_r.text), "encargado": "", "equipo": ["beto"], "emails": "z@z.com"})
ok(usuarios.datos_cliente(C2)["encargado"] == "beto" and usuarios.datos_cliente(C2)["equipo"] == "ana",
   "un colaborador no puede cambiar quién lleva el cliente")
_ia = ca.get("/").text
ok("3 cliente(s)" in _ia and "que llevás vos" not in _ia, "el administrador ve todos los clientes")
usuarios.guardar_datos_cliente(C2, {**usuarios.datos_cliente(C2), "encargado": "", "equipo": "ana"}, "gabriel")
# planilla de asignación: bajar, completar y subir (solo administradores)
import io as _io  # noqa: E402
from openpyxl import load_workbook as _lw  # noqa: E402
ok(cb.get("/asignaciones").status_code == 403, "asignar clientes: solo administradores")
usuarios.guardar_datos_cliente(C, {**usuarios.datos_cliente(C), "emails": "x@y.com"}, "gabriel")
_x = ca.get("/asignaciones?bajar=1")
_wb = _lw(_io.BytesIO(_x.data))
_ws = _wb["Clientes"]
_cuits = {str(r[0].value).replace("-", ""): r for r in _ws.iter_rows(min_row=2)}
ok(_x.status_code == 200 and {C, C2, C3} <= set(_cuits) and "Usuarios" in _wb.sheetnames
   and _ws.data_validations.dataValidation, "planilla con todos los clientes, usuarios y desplegable")
_cuits[C][2].value, _cuits[C][3].value = "beto", "ana, fantasma"
_cuits[C3][2].value = "nadie"
_buf = _io.BytesIO(); _wb.save(_buf); _buf.seek(0)
_r = ca.get("/asignaciones")
_r = ca.post("/asignaciones", data={"csrf": token(_r.text), "planilla": (_buf, "asignacion.xlsx")},
             content_type="multipart/form-data", follow_redirects=True)
ok(usuarios.datos_cliente(C)["encargado"] == "beto" and usuarios.datos_cliente(C)["equipo"] == "ana"
   and usuarios.datos_cliente(C3).get("encargado", "") == "" and "nadie" in _r.text and "fantasma" in _r.text,
   "importa encargado y equipo; avisa usuarios inexistentes y no los asigna")
ok(usuarios.datos_cliente(C).get("emails") == "x@y.com", "el resto de los datos del cliente queda igual")
ok(f"/cliente/{C}" in cb.get("/").text, "Beto ahora ve el cliente asignado por planilla")
ok(ca.post("/asignaciones", data={"csrf": token(_r.text), "planilla": (_io.BytesIO(b"no"), "x.txt")},
           content_type="multipart/form-data", follow_redirects=True).status_code == 200, "archivo que no es Excel: rechazado")
# planilla completa: datos del cliente, claves (cifradas al instante) y alta de un cliente nuevo
import subprocess as _sp  # noqa: E402
from robots_web import claves as _claves  # noqa: E402
_priv, _pub = os.path.join(R, "priv.pem"), os.path.join(R, "pub.pem")
_sp.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", _priv], check=True, capture_output=True)
_sp.run(["openssl", "pkey", "-in", _priv, "-pubout", "-out", _pub], check=True, capture_output=True)
_claves.PUB = _pub
def _cuit_ok(base10):
    s_ = sum(int(d) * m for d, m in zip(base10, (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)))
    v_ = {11: 0, 10: 9}.get(11 - s_ % 11, 11 - s_ % 11)
    return base10 + str(v_)
NUEVO = _cuit_ok("2730123456")
_x = ca.get("/asignaciones?bajar=1")
_wb = _lw(_io.BytesIO(_x.data)); _ws = _wb["Clientes"]
_tit = [c.value for c in _ws[1]]
_col = {t: i for i, t in enumerate(_tit)}
ok(all(t in _tit for t in ("Condición frente al IVA", "Mails del cliente", "Teléfonos", "Clave fiscal ARCA", "CIT ARBA", "Clave Ciudad AGIP")),
   "planilla con todos los datos del cliente y columnas de claves")
ok(all(r[_col["Clave fiscal ARCA"]].value in (None, "") for r in _ws.iter_rows(min_row=2)), "las claves nunca se bajan")
_fila_c = next(r for r in _ws.iter_rows(min_row=2) if str(r[0].value).replace("-", "") == C)
_fila_c[_col["Condición frente al IVA"]].value = "Monotributo"
_fila_c[_col["Teléfonos"]].value = "11 4444-5555"
_fila_c[_col["Mails del cliente"]].value = "-"
_fila_c[_col["Medios de pago del VEP (según sus bancos)"]].value = "banelco, interbanking"
_fila_c[_col["CIT ARBA"]].value = "CitSecreta#1"
_fila_c[_col["Mes de cierre"]].value = "Trece"
_n = [None] * len(_tit)
_n[_col["CUIT"]], _n[_col["Razón social"]], _n[_col["Clave fiscal ARCA"]] = NUEVO, "CLIENTE NUEVO SRL", "ArcaSecreta#2"
_n[_col["Encargado (usuario)"]] = "beto"
_ws.append(_n)
_ws.append([_cuit_ok("2033333333")] + [None] * (len(_tit) - 1))          # nuevo sin clave: no se da de alta
_buf = _io.BytesIO(); _wb.save(_buf); _buf.seek(0)
_antes = set(os.listdir(BANDEJA))
_r = ca.post("/asignaciones", data={"csrf": token(ca.get("/asignaciones").text), "planilla": (_buf, "clientes.xlsx")},
             content_type="multipart/form-data", follow_redirects=True)
_d = usuarios.datos_cliente(C)
ok(_d["condicion_iva"] == "Monotributo" and _d["telefonos"] == "11 4444-5555" and _d["emails"] == ""
   and _d["medios_vep"] == "Pago Mis Cuentas (Banelco), Interbanking" and _d.get("equipo") == "ana",
   "datos del cliente cargados por planilla (vacío no cambia, guion borra)")
ok("Trece" in _r.text and "no es una opción válida" in _r.text, "valor fuera de lista: avisa y no lo cambia")
_sobres = [json.load(open(os.path.join(BANDEJA, n))) for n in set(os.listdir(BANDEJA)) - _antes if n.endswith(".json")]
ok(sorted((x["cuit"], x["organismo"]) for x in _sobres) == sorted([(C, "ARBA"), (NUEVO, "ARCA")]), "claves enviadas al robot (un sobre por clave)")
_txt = json.dumps(_sobres) + _r.text
ok("CitSecreta" not in _txt and "ArcaSecreta" not in _txt, "las claves no quedan a la vista (ni en sobres ni en mensajes)")
_sello = next(x for x in _sobres if x["organismo"] == "ARBA")["clave_sellada"]
_dec = _sp.run(["openssl", "pkeyutl", "-decrypt", "-inkey", _priv, "-pkeyopt", "rsa_padding_mode:oaep", "-pkeyopt", "rsa_oaep_md:sha256",
                "-pkeyopt", "rsa_mgf1_md:sha256"], input=__import__("base64").b64decode(_sello), capture_output=True).stdout.decode()
ok(_dec == "CitSecreta#1", "solo el robot (llave privada) puede abrir la clave")
ok(usuarios.datos_cliente(NUEVO).get("encargado") == "beto" and "1 alta(s) nueva(s)" in _r.text
   and "sin Clave fiscal ARCA" in _r.text, "alta de cliente nuevo con clave de ARCA; sin clave no se da de alta")
for n in set(os.listdir(BANDEJA)) - _antes:
    if n.endswith(".json"):
        os.remove(os.path.join(BANDEJA, n))
usuarios.guardar_datos_cliente(C, {**usuarios.datos_cliente(C), "encargado": "", "equipo": "ana"}, "gabriel")
_mf = app.test_client().get("/manifest.webmanifest")
ok(_mf.status_code == 200 and "icono-512.png" in _mf.text and _mf.mimetype == "application/manifest+json"
   and app.test_client().get("/static/icono-192.png").status_code == 200, "celular: se instala como app (manifest con íconos)")
from robots_web.app import utilidad  # noqa: E402
ok(utilidad(1.5) == "50,00%" and utilidad(0.87) == "−13,00%" and utilidad(1.23456) == "23,46%", "utilidad = D/C − 1 con 2 decimales")
_ri = cl.get(f"/cliente/{C2}/iva").text
ok("(D/C − 1)" in _ri and "no es la utilidad" in _ri and "−50,00%" in _ri and "txt-rojo" in _ri, "D/C − 1 con signo menos, en rojo y aclarando que no es la utilidad")
ok("IVA: débito / crédito fiscal" in r.text and "· utilidad" not in r.text and "índice erogaciones/ventas" in r.text or "datos incompletos" in r.text,
   "ficha del cliente: la tarjeta de IVA ya no dice 'utilidad'; la utilidad está en la relación D/C (20/11/2026)")
ok("con ajustes" not in r2.text, "sin conciliación: no muestra el bloque de ajustes")
_per = analisis.resultado_mensual(C2)[0]["periodo"]
escribir(f"{D}/{C2}/conciliacion/ajustes_conciliacion.json",
         {"por_mes": {_per: {"duplicados_neto": -10_000.0, "duplicados_iva": -2_100.0, "nc_neto": -50_000.0, "nc_iva": -10_500.0}}})
_m = analisis.resultado_mensual(C2)[0]
ok(abs(_m["erogaciones_ajustadas"] - (_m["erogaciones"] - 60_000)) < 1 and abs(_m["aj_iva_credito"] + 12_600) < 1
   and abs(_m["saldo_tecnico_ajustado"] - (_m["saldo_tecnico"] + 12_600)) < 1, "ajustes de conciliación en los saldos")
r2 = cl.get(f"/cliente/{C2}/relacion")
ok("con ajustes" not in r2.text, "relación D/C sin la conciliación (va en la planilla de conciliación aparte)")
os.remove(f"{D}/{C2}/conciliacion/ajustes_conciliacion.json")
ok("IVA: débito / crédito fiscal" in r.text and "Relación débito crédito" in r.text and "Fiscalizaciones" in r.text
   and "AGIP (Ciudad)" in r.text and "Pedir corrida" in r.text, "ficha con botones nuevos y pedir corrida")
escribir(f"{R}/publico/grupos.json", {C2: {"dia": 2, "semana": 1}, C3: {"dia": 4, "semana": 0}})
ok("<b>todos los miércoles</b>" in cl.get(f"/cliente/{C2}").text, "inscripto (o sin clasificar): todas las semanas")
escribir(f"{D}/{C3}/categoria.json", {"categoria": "sin Portal IVA (monotributo/exento)"})
ok("viernes por medio (dos veces por mes" in cl.get(f"/cliente/{C3}").text, "monotributista: semana por medio")
r = cl.get(f"/cliente/{C2}/iva")
ok("<svg" in r.text and "Crítico" in r.text and "0,50" in r.text, "sección débito/crédito con gráfico")
r = cl.get(f"/cliente/{C2}/resultado")
ok("Conclusiones" in r.text and "NEGATIVO" in r.text and "falta F.931" in r.text, "sección resultado mensual")
r = cl.get(f"/cliente/{C2}/fiscalizaciones")
ok("OI 1.234.567" in r.text and "FE-2026-123" in r.text, "sección fiscalizaciones ARCA + AGIP")
r = cl.get(f"/cliente/{C2}/agip")
ok("250.000" in r.text and "ISIB" in r.text, "sección AGIP con deuda")
r = cl.get(f"/cliente/{C2}/notificaciones?org=AGIP")
ok("Intimación de pago ISIB" in r.text and "marcar informada" in r.text, "notificaciones de AGIP en la ficha")
for v in ("dfe", "deudas", "planes", "faltas", "iva", "proyeccion", "resultado", "fiscalizaciones"):
    r = cl.get(f"/cartera/{v}")
    ok(r.status_code == 200 and "menu-cartera" in r.text, f"cartera/{v}")
r = cl.get("/cartera/dfe")
ok("Notificaciones Seclo" in r.text and "Intimación de pago ISIB" in r.text and "Aviso de vencimiento" in r.text,
   "DFE de toda la cartera (ARCA + AGIP)")
ident = re.search(r'name="id" value="(\w+)"><input type="hidden" name="cuit" value="' + C2, r.text)[1]
cl.post("/dfe/informada", data={"id": ident, "cuit": C2, "marcar": "1", "csrf": token(r.text), "volver": "/cartera/dfe"})
r = cl.get("/cartera/dfe")
ok("Intimación de pago ISIB" not in r.text and "Notificaciones Seclo" in r.text, "marcar informada la saca de pendientes")
ok("informada por Ana" in cl.get("/cartera/dfe?ver=todas").text, "en 'todas' se ve quién la informó")
ok("250.000" in cl.get("/cartera/deudas").text, "deudas incluye AGIP")
ok("BH SOLUCIONES" in cl.get("/cartera/proyeccion").text and "<svg" in cl.get("/cartera/proyeccion").text, "proyección de la cartera")
ok("OI 1.234.567" in cl.get("/cartera/fiscalizaciones").text, "fiscalizaciones de la cartera")
r = cl.get(f"/cliente/{C2}/datos")
cl.post(f"/cliente/{C2}/datos", data={"csrf": token(r.text), "condicion_iva": "Responsable inscripto", "contadores": "Tomás",
                                      "regimen_iibb": "Convenio Multilateral", "mes_cierre": "Diciembre", "emails": "a@b.com"})
r = cl.get(f"/cliente/{C2}")
ok("Responsable inscripto" in r.text and "Tomás" in r.text, "datos del cliente guardados")
cl.post(f"/cliente/{C2}/datos", data={"csrf": token(r.text), "condicion_iva": "<script>"})
ok("<script>" not in cl.get(f"/cliente/{C2}").text, "datos del cliente: opción inválida descartada")
r = cl.get(f"/cliente/{C2}")
r = cl.post(f"/cliente/{C2}/pedir", data={"csrf": token(r.text), "robot": "agip"}, follow_redirects=True)
ok("Pedido enviado" in r.text and len([n for n in os.listdir(os.path.join(BANDEJA, "pedidos")) if n.endswith(".json")]) == 1, "pedido de corrida en la bandeja")
r = cl.post(f"/cliente/{C2}/pedir", data={"csrf": token(r.text), "robot": "agip"}, follow_redirects=True)
ok("Ya hay un pedido igual" in r.text, "no duplica pedidos")
r = cl.post(f"/cliente/{C2}/pedir", data={"csrf": token(r.text), "robot": "rm -rf"}, follow_redirects=True)
ok("Robot desconocido" in r.text, "robot inválido rechazado")
ok(cl.post(f"/cliente/{C2}/pedir", data={"csrf": "malo", "robot": "agip"}).status_code == 400, "pedir corrida con CSRF")
ok(cl.post("/dfe/informada", data={"csrf": "malo", "id": "abc", "cuit": C2, "marcar": "1"}).status_code == 400, "informada con CSRF")
ok(cl.post(f"/cliente/{C2}/datos", data={"csrf": "malo", "condicion_iva": "Exento"}).status_code == 400, "datos del cliente con CSRF")
ok("en la bandeja" in cl.get("/robots").text, "pedido visible en Robots")

# ------------------------------------------------ robot: toma el pedido (sin correr nada real)
from robots import pedidos as rp  # noqa: E402

rp.PEDIDOS, rp.PUBLICO, rp.CANDADO = os.path.join(BANDEJA, "pedidos"), os.path.join(R, "publico"), os.path.join(R, "candado.lock")
import robots.correr as rc  # noqa: E402

llamados = []
rc.correr_uno = lambda robot, cuit, *a, **k: llamados.append((robot, cuit)) or "OK\n     agip: simulado"
rc._publicar = lambda: None
ok(rp.procesar() == 1 and llamados == [("agip", C2)] and not [n for n in os.listdir(rp.PEDIDOS) if n.endswith(".json")], "el robot toma el pedido y lo corre")
ok("terminado" in cl.get("/robots").text, "la web muestra el pedido terminado")
import fcntl  # noqa: E402

open(os.path.join(BANDEJA, "pedidos", "x_12345678.json"), "w").write(json.dumps(
    {"id": "1234567890ab", "cuit": C, "robot": "todo", "fecha": "2026-11-17T10:00:00", "por": "ana"}))
with open(rp.CANDADO, "a") as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    ok(rp.procesar() == 0 and len([n for n in os.listdir(rp.PEDIDOS) if n.endswith(".json")]) == 1, "con una corrida en curso el pedido espera")
ok("en espera" in cl.get("/robots").text, "estado 'en espera' visible")
open(os.path.join(BANDEJA, "pedidos", "y_mal.json"), "w").write(json.dumps({"cuit": "1; rm", "robot": "todo", "id": "zz"}))
rp.procesar()
ok(os.path.exists(os.path.join(BANDEJA, "pedidos", "y_mal.json.mal")), "pedido mal formado se descarta")

# ------------------------------------------------ avisos de cuotas impagas (17/11/2026)
json.dump([{"id": f"{C2}:W631300:2", "cuit": C2, "razon_social": "BH SOLUCIONES", "plan": "W631300", "cuota": 2,
            "venc_1": "2026-11-16", "dias": 5, "importe": 342337.29, "estado": "para el encargado", "encargado": "",
            "historial": []}], open(os.path.join(R, "publico", "avisos.json"), "w"))
r = cl.get("/avisos?ver=todos")
ok(r.status_code == 200 and "W631300" in r.text and "Enviar aviso + VEP" in r.text, "pantalla Avisos con botones")
r = cl.post("/avisos?ver=todos", data={"csrf": token(r.text), "aviso": f"{C2}:W631300:2", "accion": "aviso_vep"},
            follow_redirects=True)
pa = [json.load(open(os.path.join(BANDEJA, "pedidos", n))) for n in os.listdir(os.path.join(BANDEJA, "pedidos"))
      if n.endswith(".json")]
ok(any(p.get("robot") == "aviso_vep" and p.get("aviso") == f"{C2}:W631300:2" for p in pa), "botón 'Enviar aviso + VEP' deja el pedido")
ok(cl.post("/avisos", data={"csrf": "malo", "aviso": "x", "accion": "aviso_enviar"}).status_code == 400, "avisos con CSRF")
r = cl.get(f"/cliente/{C2}/datos")
ok('name="encargado"' not in r.text and "Lo asigna un administrador" in r.text and 'name="medios_vep"' in r.text,
   "datos del cliente (colaborador): ve el encargado pero no lo cambia; medios de pago del VEP")
cl.post(f"/cliente/{C2}/datos", data={"csrf": token(r.text), "medios_vep": ["Interbanking", "Pagar (Red Link)", "trucho"],
                                      "emails": "a@b.com"})
ct = json.load(open(os.path.join(BANDEJA, "pedidos", "_contactos.txt")))
ok(ct[C2]["medios_vep"] == ["Pagar (Red Link)", "Interbanking"] and ct[C2]["emails_cliente"] == ["a@b.com"],
   "medios de pago del VEP (varios) publicados para el robot")
r = cl.get("/cartera/dfe?ver=todas")
ok(r.status_code == 200 and "Notificadas sin leer" in r.text and "Reenviar al cliente" in r.text, "tablero DFE con prioridades y botones")
from robots_web import datos as _dw  # noqa: E402
nid = _dw.ficha(C2)["notificaciones"][0]["id"]
cl.post("/dfe/mail", data={"csrf": token(r.text), "id": nid, "cuit": C2, "a": "cliente", "volver": "/cartera/dfe"})
pa = [json.load(open(os.path.join(BANDEJA, "pedidos", n))) for n in os.listdir(os.path.join(BANDEJA, "pedidos"))
      if n.endswith(".json")]
ok(any(p.get("robot") == "mail_dfe" and p.get("a") == "cliente" and p["notif"].get("asunto") for p in pa),
   "DFE: 'Reenviar al cliente' deja el pedido de mail")
ok(cl.post("/dfe/mail", data={"csrf": "malo", "id": nid, "cuit": C2, "a": "admin"}).status_code == 400, "mail DFE con CSRF")
for n in os.listdir(os.path.join(BANDEJA, "pedidos")):
    if n.endswith(".json"):
        os.remove(os.path.join(BANDEJA, "pedidos", n))

# ------------------------------------------------ reparto por día y repechaje
import datetime as _dt  # noqa: E402

import robots.correr as rc2  # noqa: E402

rc2.GRUPOS = os.path.join(R, "publico", "grupos_prueba.json")
cs = [f"30{n:09d}" for n in range(523)]
m = rc2.asignar_grupos(cs)
cuenta = [sum(1 for v in m.values() if v["dia"] == d) for d in range(5)]
ok(max(cuenta) - min(cuenta) <= 1, f"523 clientes repartidos parejo de lunes a viernes {cuenta}")
pares = [sum(1 for v in m.values() if v["dia"] == 0 and v["semana"] == w) for w in (0, 1)]
ok(abs(pares[0] - pares[1]) <= 1, f"y parejo entre semanas pares e impares {pares}")
rc2.robot_libro_iva.DATOS = D
lunes_par, lunes_impar = _dt.date(2026, 11, 16), _dt.date(2026, 11, 23)      # semanas ISO 47 (impar) y 48 (par)
ok(rc2.le_toca_hoy(C2, {"dia": 0, "semana": 0}, lunes_par) and rc2.le_toca_hoy(C2, {"dia": 0, "semana": 0}, lunes_impar),
   "inscripto: corre todos los lunes")
ok([rc2.le_toca_hoy(C3, {"dia": 0, "semana": 0}, f) for f in (lunes_par, lunes_impar)] == [False, True],
   "monotributista: un lunes sí y otro no")
ok(rc2.asignar_grupos(cs + ["30999999999"])[cs[7]] == m[cs[7]], "un cliente no cambia de día al sumar otros")
escribir(rc2.GRUPOS, {"30000000005": 3})
ok(rc2.asignar_grupos(["30000000005"])["30000000005"]["dia"] == 3, "lee el formato anterior de grupos.json")
rc2.REGISTRO = os.path.join(R, "reg_prueba.jsonl")
import datetime as _dt  # noqa: E402

ahora = _dt.datetime.now().isoformat(timespec="seconds")
with open(rc2.REGISTRO, "w") as f:
    for c, e in (("30000000001", "Error"), ("30000000001", "OK"), ("30000000002", "Error"), ("30000000003", "Clave inválida")):
        f.write(json.dumps({"fecha": ahora, "cuit": c, "estado": e}) + "\n")
ok(rc2.fallidos_recientes() == {"30000000002"}, "repechaje: solo los que siguen con error (no clave inválida)")

# ------------------------------------------------ lo de antes sigue andando
r = cl.get(f"/cliente/{C}")
ok("Seclo" in r.text and "Situación fiscal" not in r.text or "Informes" in r.text, "ficha del cliente 1")
ok(cl.get(f"/informe/2026-11-15/situacion_fiscal_{C}.xlsx").status_code == 200, "descarga de informe")
ok(cl.get("/informe/../../etc/passwd").status_code == 404, "no se sale de la carpeta de informes")
ok("Plan" in cl.get("/agenda").text, "agenda")
ok(cl.get("/alertas").status_code == 200 and "Relación débito/crédito crítica" in cl.get("/alertas").text, "alertas del día con D/C")
# descartar alertas por motivo; a los 30 días, si sigue igual, vuelve (18/11/2026)
_al = cl.get("/alertas").text
_m = re.search(r'name="cuit" value="(\d{11})">\s*<input type="hidden" name="tipo" value="([^"]*)"><input type="hidden" name="texto" value="([^"]*)">', _al)
import html as _html  # noqa: E402
_ccu, _tipo, _texto = _m[1], _html.unescape(_m[2]), _html.unescape(_m[3])
_n_antes = _al.count('class="alta"')
_r = cl.post("/alertas", data={"csrf": token(_al), "cuit": _ccu, "tipo": _tipo, "texto": _texto, "motivo": "Otro", "nota": ""},
             follow_redirects=True)
ok("escribí una nota" in _r.text, "descartar con 'Otro' pide nota")
_r = cl.post("/alertas", data={"csrf": token(_al), "cuit": _ccu, "tipo": _tipo, "texto": _texto, "motivo": "Avisado al cliente",
                               "nota": "le escribí por WhatsApp"}, follow_redirects=True)
ok("Alerta descartada: Avisado al cliente" in _r.text and _r.text.count('class="alta"') == _n_antes - 1, "alerta descartada sale de pendientes")
_d = cl.get("/alertas?ver=descartadas").text
ok("le escribí por WhatsApp" in _d and "Avisado al cliente" in _d and "Volver a mostrar" in _d, "lista de descartadas con motivo, nota y quién")
ok(cl.post("/alertas", data={"csrf": token(_al), "cuit": _ccu, "tipo": "x", "texto": "y", "motivo": "Alerta sin relevancia"},
           follow_redirects=True).text.count("ya cambió") == 1, "no se puede descartar una alerta que no existe")
_con = usuarios.conectar()
with _con:
    _con.execute("UPDATE descartes SET fecha='2026-01-01T00:00:00'")
_con.close()
ok(cl.get("/alertas").text.count('class="alta"') == _n_antes, "a los 30 días, si sigue igual, la alerta vuelve")
# descartar el cliente completo (20/11/2026)
_al = cl.get("/alertas").text
ok(_al.count('class="grupo-alertas"') >= 2 and "Descartar <b>todas</b> las alertas de este cliente" in _al, "alertas agrupadas por cliente")
_n_cli = len([g for g in datos.alertas_del_dia({_ccu}) if g["cuit"] == _ccu][0]["alertas"])
_r = cl.post("/alertas", data={"csrf": token(_al), "accion": "descartar_cliente", "cuit": _ccu, "motivo": "Alerta sin relevancia"},
             follow_redirects=True)
ok(f"{_n_cli} alerta(s) del cliente descartadas" in _r.text and f'value="{_ccu}"><input type="hidden" name="tipo"' not in _r.text.replace("\n", "").replace("  ", ""),
   "descartar el cliente completo saca todas sus alertas")
_d = cl.get("/alertas?ver=descartadas").text
ok("Volver a mostrar todas las del cliente" in _d, "descartadas agrupadas por cliente")
_r = cl.post("/alertas", data={"csrf": token(_d), "accion": "restaurar_cliente", "cuit": _ccu}, follow_redirects=True)
ok(f"{_n_cli} alerta(s) del cliente volvieron" in _r.text, "volver a mostrar todas las del cliente")
ok(cb.post("/alertas", data={"csrf": token(cb.get("/sugerencias").text), "accion": "descartar_cliente", "cuit": C,
                             "motivo": "Alerta sin relevancia"}).status_code == 403, "no se descarta un cliente ajeno")
ok(cb.post("/alertas", data={"csrf": token(cb.get("/sugerencias").text), "cuit": C, "tipo": _tipo, "texto": _texto,
                             "motivo": "Alerta sin relevancia"}).status_code == 403, "no se descartan alertas de clientes ajenos")
ok(cl.get("/actividad").status_code == 403, "colaborador no ve actividad")
cl2 = app.test_client()
login(cl2, "gabriel", "claveadmin123")
ok("pidió corrida agip" in cl2.get("/actividad").text, "el admin ve quién pidió corridas")
escribir(f"{R}/publico/actualizaciones.json", [{"fecha": "2026-11-17T13:00:00", "estado": "rechazada: fallaron las pruebas",
                                               "commit": "abc1234", "mensaje": "cambio de prueba", "detalle": "✘ algo"}])
ok("cambio de prueba" in cl2.get("/sistema").text and "Sistema" in cl2.get("/mas").text, "el admin ve la pantalla Sistema")
ok(cl.get("/sistema").status_code == 403, "un colaborador no ve Sistema")
ok(cl.get(f"/cliente/{C3}").status_code == 200 and cl.get(f"/cliente/{C3}/iva").status_code == 200, "cliente sin datos no rompe")
if os.environ.get("VOLCAR_HTML"):                      # para ver la estética: guarda las pantallas en HTML
    os.makedirs(os.environ["VOLCAR_HTML"], exist_ok=True)
    css = open(os.path.join(RAIZ, "robots_web", "static", "estilo.css"), encoding="utf-8").read()
    for nom, url in (("inicio", "/"), ("ficha", f"/cliente/{C2}"), ("relacion", f"/cliente/{C2}/relacion"),
                     ("iva", f"/cliente/{C2}/iva"), ("deuda", f"/cliente/{C}/deuda"), ("planes", f"/cliente/{C}/planes"),
                     ("notificaciones", f"/cliente/{C2}/notificaciones"), ("cartera_dfe", "/cartera/dfe"),
                     ("cartera_iva", "/cartera/iva"), ("alertas", "/alertas"), ("avisos", "/avisos"),
                     ("datos", f"/cliente/{C2}/datos")):
        html = re.sub(r'<link[^>]+estilo\.css[^>]*>', "<style>" + css + "</style>", cl.get(url).text)
        open(os.path.join(os.environ["VOLCAR_HTML"], nom + ".html"), "w", encoding="utf-8").write(html)
print(f"\n{sum(res)}/{len(res)} OK")
sys.exit(0 if all(res) else 1)
