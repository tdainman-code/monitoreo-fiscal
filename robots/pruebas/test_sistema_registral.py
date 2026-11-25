"""Sistema Registral de ARCA (pantallas de Nabajuma mostradas por Gabriel el 25/11/2026) -> datos para la ficha."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from robots import robot_sistema_registral as sr  # noqa: E402

res = []


def ok(c, t):
    res.append(bool(c))
    print(("✔ " if c else "✘ ") + t)


TXT = """Estado de la CUIT
Activa
Mi dependencia
AGENCIA NRO 54
CUIT:
30-71222757-1
DENOMINACIÓN
NABAJUMA S.A.
Datos fiscales
DEPENDENCIA:
54-AGENCIA NRO 54
TIPO DE INSCRIPCIÓN:
33-Alta por presentación
MES DE CIERRE:
12
REGISTRA IMPUESTOS ACTIVOS?
SI
FECHA DE INSCRIPCIÓN:
13/03/2012
Está adherido al domicilio fiscal Electrónico: Si
"""
d = sr.leer_datos(TXT)
ok(d.get("mes_cierre") == "12" and d.get("dependencia") == "54-AGENCIA NRO 54" and d.get("fecha_inscripcion") == "13/03/2012"
   and d.get("dfe_adherido") is True and d.get("estado_cuit") == "Activa", "datos fiscales: cierre, dependencia, inscripción, DFE")
SEC = [
    {"titulo": "Impuestos y/o Aportes", "filas": [["Código", "Descripción", "Estado", "Período"],
        ["10", "GANANCIAS SOCIEDADES", "ACTIVO", "04/2012"], ["30", "IVA", "ACTIVO", "04/2012"],
        ["211", "BP-ACCIONES O PARTICIPACIONES", "ACTIVO", "04/2012"], ["301", "EMPLEADOR-APORTES SEG. SOCIAL", "ACTIVO", "09/2013"],
        ["5900", "IIBB CONVENIO MULTILATERAL", "ACTIVO", "04/2012"], ["25", "GANANCIA MINIMA PRESUNTA", "BAJA DEFINITIVA", "12/2016"]]},
    {"titulo": "E-Mails", "filas": [["Mail", "Tipo"], ["estudio@ejemplo.com.ar", "TRIBUTARIO"]]},
    {"titulo": "Teléfonos", "filas": [["Número de teléfono", "Tipo"], ["11-40000000", "Fijo"]]},
    {"titulo": "Datos de actividad económica", "filas": [["Nomenclador", "Código", "Descripción", "Orden"],
        ["883", "152040", "FABRICACIÓN DE PARTES DE CALZADO", "1"]]},
]
r = {**d, **sr.leer_secciones(SEC)}
ok(len(r["impuestos"]) == 6 and r["actividades"][0]["codigo"] == "152040", "tablas de impuestos y actividades")
ADU = """Situación en el Sistema Registral - 30712227571
Tipo de Operador	Fecha Inicio	Fecha Alta	Fecha Baja	Motivo de baja	Fecha Actualización
IMPORTADOR/EXPORTADOR	18-05-2012	05-06-2012		11-11-2013 16:35:52
Estados del operador - 30712227571
Tipo de operador	Estado	Fecha vigencia desde
IMPORTADOR/EXPORTADOR	HABILITADO	14-12-2021
"""
r["aduana"] = sr.leer_aduana(ADU)
ok(r["aduana"]["operador"] == "IMPORTADOR/EXPORTADOR" and r["aduana"]["estado"] == "HABILITADO", "Registro Aduanero: importador habilitado")
f = sr.resumen_ficha(r)
ok(f.get("condicion_iva") == "Responsable inscripto" and f.get("condicion_ganancias") == "Inscripto"
   and f.get("regimen_iibb") == "Convenio Multilateral" and f.get("empleador") == "Sí" and f.get("mes_cierre") == "Diciembre"
   and f.get("bienes_personales") == "Responsable sustituto", "ficha: IVA, Ganancias, CM, empleador, cierre, BP acciones")
ok(f.get("emails") == "estudio@ejemplo.com.ar" and f.get("importador", "").startswith("IMPORTADOR/EXPORTADOR"), "ficha: mails e importador")
ok("25" not in {i["codigo"] for i in r["impuestos"] if i["estado"] == "ACTIVO"}, "los impuestos dados de baja no cuentan")
print(f"\n{sum(res)}/{len(res)} OK")
sys.exit(0 if all(res) else 1)
