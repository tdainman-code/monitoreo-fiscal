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
_no = sr.leer_aduana("""CUIT: 20205744283 - Apellido : MANCOVSKY Nombre : GABRIEL ERNESTO
Domicilio aduanero electrónico - 20205744283
Está adherido al SICNEA
NO
Solvencia económica - 20205744283
Determinación de solvencia
Acredita solvencia económica para actuar como importador/exportador
Datos Digitales Presentados y Confirmados - 20205744283""")
ok(_no["no_operador"] and not _no["operador"] and sr.resumen_ficha({"aduana": _no}).get("importador") == "No",
   "Registro Aduanero: sin 'Tipo de Operador' (Gaby) -> no es importador")
f = sr.resumen_ficha(r)
ok(f.get("condicion_iva") == "Responsable inscripto" and f.get("condicion_ganancias") == "Inscripto"
   and f.get("regimen_iibb") == "Convenio Multilateral" and f.get("empleador") == "Sí" and f.get("mes_cierre") == "Diciembre"
   and f.get("bienes_personales") == "Responsable sustituto", "ficha: IVA, Ganancias, CM, empleador, cierre, BP acciones")
ok(f.get("emails") == "estudio@ejemplo.com.ar" and f.get("importador", "").startswith("IMPORTADOR/EXPORTADOR"), "ficha: mails e importador")
ok("25" not in {i["codigo"] for i in r["impuestos"] if i["estado"] == "ACTIVO"}, "los impuestos dados de baja no cuentan")
# Padrón Web de COMARB: constancia de inscripción en Convenio Multilateral (texto del PDF de Nabajuma)
from robots import robot_padron_cm as pcm  # noqa: E402
CONST = """                                   CONSTANCIA DE INSCRIPCIÓN
       Fecha y Hora Emisión                                     Jurisdicción Sede
         25/11/2026 20:16                                   901 - CAPITAL FEDERAL
            Nº de CUIT                       Nº de Inscripción                              Tipo de Contribuyente
          30-71222757-1                                                                              Resto
230-Sociedad Anónima / Nro. I.G.J.: 1850715 / Fecha. I.G.J.: 2011-11-21 / Fecha Cierre Ejercicio: 2012-12-31 / Duración Años: 99
Actividades
Tipo     Art.    CUAC Descripción                                                                      Fecha Alta       Fecha Baja
  S      002     152040 Fabricación de partes de calzado                                               01/01/2018
  P      002     464130 Venta al por mayor de calzado excepto el ortopédico                            01/04/2012
  S      002     513130 Venta al por mayor de calzado excepto el ortopédico                            01/04/2012        31/12/2017
Jurisdicciones
Jurisdicción                             Fecha          Fecha      Jurisdicción                              Fecha          Fecha
901 - CAPITAL FEDERAL                  01/04/2012                  902 - BUENOS AIRES                     01/04/2012
Señor Contribuyente: Los datos aquí consignados son los declarados por Usted.
"""
c = pcm.leer_constancia(CONST)
ok(c["sede"] == "901" and [j["codigo"] for j in c["jurisdicciones"]] == ["901", "902"] and not c["jurisdicciones"][1]["baja"]
   and c["mes_cierre"] == 12, "constancia CM: sede, jurisdicciones y cierre")
ok(len(c["actividades"]) == 3 and c["actividades"][2]["baja"] == "31/12/2017" and c["actividades"][1]["tipo"] == "Principal",
   "constancia CM: actividades con alta y baja")
ok(pcm.resumen_ficha(c) == {"regimen_iibb": "Convenio Multilateral", "jurisdicciones_iibb": "CABA, Buenos Aires"},
   "ficha: Convenio Multilateral con CABA y Buenos Aires")
# ARBA: constancia de inscripción de IIBB (pantalla de Goncalves, 25/11/2026)
from robots import robot_arba_constancia as rac  # noqa: E402
_c = rac.leer_campos({"CUIT/CUIL/CDI": "20-33116278-8", "Régimen de Pago": "MENSUAL", "Tipo de contribuyente": "CENTRALIZADO",
                      "Inicio de Actividades": "1 feb. 2026", "Distrito": "117"}, "Convenio\nContribuyente directo de la Provincia de Buenos Aires")
ok(_c["directo"] and not _c["convenio_multilateral"] and rac.resumen_ficha(_c) == {"regimen_iibb": "Local", "jurisdicciones_iibb": "Buenos Aires"},
   "constancia ARBA: contribuyente directo -> régimen local Buenos Aires")
ok(rac.resumen_ficha(rac.leer_campos({"Convenio": "901-123456-7"}, "")) == {"regimen_iibb": "Convenio Multilateral"},
   "constancia ARBA con número de convenio -> Convenio Multilateral")
# F.1272 PyME: IVA a 90 días (pantalla de Nabajuma, 25/11/2026)
from robots import robot_pyme_iva as pi  # noqa: E402
ok(pi.leer_beneficio("¿Solicita el beneficio del Pago del I.V.A. en forma diferida?\tNo") is False
   and pi.leer_beneficio("¿Solicita el beneficio del Pago del I.V.A. en forma diferida?\n Si") is True
   and pi.leer_beneficio("nada") is None, "F.1272: lee Sí / No del pago diferido del IVA")
_fp = pi.filas_presentadas([["Acciones", "30712227571", "0", "F.1272 - PYMES", "2025", "Presentado", "21-04-2025 12:21", ""],
                            ["Acciones", "30712227571", "0", "F.1272 - PYMES", "2026", "Presentado", "21-04-2026 12:26", ""]], "30712227571")
ok(_fp[0]["periodo"] == "2026" and _fp[0]["estado"] == "Presentado", "F.1272: toma el período más nuevo")
# AGIP: constancia de inscripción de IIBB (texto del PDF de Garbuglia, 25/11/2026)
from robots import robot_agip_constancia as agc  # noqa: E402
_ag = agc.leer_constancia("""Nro. de CUIT 27-27137058-5                             Apellido y Nombre / Razón Social
Categoría:                      MASIVO                                             Sucesión Indivisa:
Vigente / Ultima Categoría Registrada:               ISIB-RG                            Estado:     ACTIVO
Actividad Principal                 960990 Servicios personales n.c.p.
Historial de Tramos Registrados en Ingresos Brutos
 ISIB-RG                       01/06/2022                   31/12/9999                  1623077 - 9
 ISIB-RS                       01/08/2019                   31/05/2022
""")
ok(_ag["cuit"] == "27271370585" and _ag["categoria"] == "ISIB-RG" and len(_ag["tramos"]) == 2
   and agc.resumen_ficha(_ag) == {"regimen_iibb": "Local", "jurisdicciones_iibb": "CABA"}, "constancia AGIP: ISIB-RG activo -> local CABA")
ok(agc.resumen_ficha({"categoria": "ISIB-RS", "estado": "ACTIVO"})["regimen_iibb"] == "Régimen simplificado"
   and agc.resumen_ficha({"categoria": "ISIB-RG", "estado": "BAJA"}) == {}, "constancia AGIP: simplificado y bajas")
print(f"\n{sum(res)}/{len(res)} OK")
sys.exit(0 if all(res) else 1)
