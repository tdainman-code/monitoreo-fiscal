"""Deuda al cierre por planes de pago. Caso real Nabajuma T587743 (plan caduco, 26/11/2026)."""
import os, sys, tempfile, unittest
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from robots import deuda_cierre as dc

def fila(*c): return {"celdas": list(c)}
# como la pantalla: cuotas en 2 filas (rowspan) ; la 2° fila trae menos celdas
PAGOS = {"encabezados": ["Cuota N°", "Capital($)", "Interés Financiero($)", "Interés Resarcitorio($)", "Total($)", "Fecha Venc.", "Pago", "Estado de Cuota"],
 "filas": [
  fila("1", "201.176,66", "92.408,40", "0,00", "293.585,06", "16/10/2024", "", "Cuota Impaga"),
  fila("92.408,40", "6.272,93", "299.857,99", "26/10/2024", ""),
  fila("2", "207.614,31", "85.970,75", "0,00", "293.585,06", "16/11/2024", "Pago", "Cuota Cancelada"),
  fila("3", "214.257,97", "79.327,09", "0,00", "293.585,06", "16/12/2024", "Pago", "Cuota Cancelada"),
  fila("4", "221.114,22", "72.470,84", "0,00", "293.585,06", "16/01/2025", "Pago", "Cuota Cancelada"),
  fila("5", "228.189,88", "65.395,18", "0,00", "293.585,06", "16/02/2025", "", "Cuota Impaga"),
  fila("65.395,18", "7.104,76", "300.689,82", "26/02/2025", ""),
  fila("6", "235.491,95", "58.093,11", "0,00", "293.585,06", "16/03/2025", "", "Cuota Cancelada"),
  fila("58.093,11", "3.914,47", "297.499,53", "26/03/2025", "Pago"),
  fila("7", "243.027,70", "50.557,36", "0,00", "293.585,06", "16/04/2025", "", "Cuota Impaga"),
  fila("50.557,36", "3.914,47", "297.499,53", "26/04/2025", ""),
  fila("8", "250.804,58", "42.780,48", "0,00", "293.585,06", "16/05/2025", "", ""),
  fila("42.780,48", "3.914,47", "297.499,53", "26/05/2025", ""),
 ]}
OBL = {"encabezados": ["Detalle", "Año", "Mes", "Ant/Cta", "Establ.", "Imp.", "Cpto.", "Subcpto.", "Fecha Vto.", "Deuda Complementaria",
                       "Monto Obligación($)", "Total Pagos Imputados($)", "Saldo a Cancelar($)"],
 "filas": [fila("", "2023", "", "", "0", "Bp-Acciones O Participaciones", "Declaración Jurada", "Declaración Jurada", "26/08/2024", "No", "2.758.112,92", "0,00", "2.758.112,92"),
           fila("", "2023", "", "", "0", "Bp-Acciones O Participaciones", "Declaración Jurada", "Intereses Resarcitorios", "17/09/2024", "No", "129.649,69", "0,00", "129.649,69")]}
DATOS = {"fecha": "2026-11-26", "planes": [{"numero": "T587743", "presentacion": "2024-09-17", "cuotas": 12, "tipo": "RG 5321 - Plan Deuda General",
          "consolidado": 2887762.61, "situacion": "Plan Caduco"}], "detalle": {"T587743": {"obligaciones": OBL, "pagos": PAGOS}}}
CONS = 2887762.61


class T(unittest.TestCase):
    def test_lee_cuotas_en_dos_filas(self):
        q = dc.leer_cuotas(PAGOS)
        self.assertEqual(sorted(q), list(range(1, 9)))
        self.assertEqual(q[6]["pagada_el"], date(2025, 3, 26))          # pagada al 2° vencimiento
        self.assertEqual(q[6]["importe_pagado"], 297499.53)
        self.assertIsNone(q[1]["pagada_el"]); self.assertEqual(q[1]["estado"], "Cuota Impaga")
        self.assertEqual(q[8]["estado"], "")
        self.assertEqual(q[2]["pagada_el"], date(2024, 11, 16))

    def test_antes_de_la_consolidacion_obligaciones_por_monto(self):
        r = dc.calcular(DATOS, date(2024, 8, 31))
        self.assertAlmostEqual(r["total_planes"], 2758112.92, 2)         # la de interés venció 17/09 (después)

    def test_cierre_31_12_2024_bajan_cuotas_2_y_3(self):
        r = dc.calcular(DATOS, date(2024, 12, 31))
        self.assertAlmostEqual(r["total_planes"], round(CONS - 207614.31 - 214257.97, 2), 2)
        o = r["obligaciones"]
        self.assertAlmostEqual(sum(x["saldo"] for x in o), r["total_planes"], 0)   # reparto proporcional

    def test_caduco_pagos_no_imputados_igual_bajan(self):
        r = dc.calcular(DATOS, date(2025, 12, 31))
        pag = 207614.31 + 214257.97 + 221114.22 + 235491.95
        self.assertAlmostEqual(r["planes"][0]["capital_pagado_a_cierre"], round(pag, 2), 2)
        self.assertAlmostEqual(r["total_planes"], round(CONS - pag, 2), 2)
        self.assertIn("caduco", r["planes"][0]["criterio"])

    def test_cuota_pagada_despues_del_cierre_no_baja(self):
        r = dc.calcular(DATOS, date(2025, 3, 20))                         # cuota 6 se pagó el 26/03
        self.assertAlmostEqual(r["total_planes"], round(CONS - 207614.31 - 214257.97 - 221114.22, 2), 2)

    def test_sin_mes_de_cierre_usa_31_12(self):
        dc.mes_cierre = lambda cuit: None
        self.assertEqual(dc.cierres("x", date(2026, 11, 26)), [date(2025, 12, 31), date(2024, 12, 31)])

    def test_cuentas_tributarias_solo_ddjj_hasta_el_cierre(self):
        scth = {"fecha": "2026-11-20", "deudas": [
            {"impuesto": "302", "nombre": "APORTES OBRAS SOCIALES", "periodo": "20241100", "concepto": "DDJJ", "deuda": 1000.0, "f931": True},
            {"impuesto": "302", "nombre": "APORTES OBRAS SOCIALES", "periodo": "20241100", "concepto": "Intereses resarcitorios", "deuda": 50.0, "f931": True},
            {"impuesto": "30", "nombre": "IVA", "periodo": "20241200", "concepto": "DDJJ", "deuda": 700.0, "f931": False},
            {"impuesto": "30", "nombre": "IVA", "periodo": "20250100", "concepto": "DDJJ", "deuda": 999.0, "f931": False}]}
        ct = dc.cuentas_tributarias(scth, date(2024, 12, 31))
        self.assertEqual(ct["total"], 1700.0)
        self.assertEqual(ct["total_f931"], 1000.0)
        self.assertTrue(next(x for x in ct["filas"] if x["periodo"] == "20241200")["vence_despues"])

    def test_pagos_posteriores(self):
        pp = dc.pagos_posteriores({"desde": "2025-01-01", "pagos": [
            {"fecha": "2025-01-09", "formulario": "1931", "impuesto": "312 - ART", "periodo": "20241200", "importe": 991245.98, "observaciones": ""},
            {"fecha": "2026-04-16", "formulario": "800", "impuesto": "352 - OS", "periodo": "20241100", "importe": 3330.31, "observaciones": ""},
            {"fecha": "2026-11-17", "formulario": "1931", "impuesto": "352 - OS", "periodo": "20261000", "importe": 1866268.45, "observaciones": ""}]},
            date(2024, 12, 31))
        self.assertEqual(pp["total"], 991245.98)
        self.assertEqual(pp["total_f800"], 3330.31)
        self.assertEqual(len(pp["filas"]), 2)

    def test_csv_pagos(self):
        from robots import robot_pagos_sct as rp
        t = ("CUIT: 30-71222757-1 - Fecha de emisión: 26/11/2026\nFecha Operación;Formulario;Version;Impuesto;Periodo;Importe;Observaciones\n"
             "09/01/2025;1931;0;312 - ASEG.RIESGO DE TRABAJO L 24557;20241200;$ 991.245,98;02 - Comprobante general\n")
        x = rp.leer_csv(t)
        self.assertEqual(x[0]["importe"], 991245.98)
        self.assertEqual(x[0]["periodo"], "20241200")

    def test_excel(self):
        with tempfile.TemporaryDirectory() as t:
            x = dc.excel("30712227571", dc.calcular(DATOS, date(2024, 12, 31)), os.path.join(t, "a.xlsx"), "2026-11-26")
            from openpyxl import load_workbook
            self.assertEqual(load_workbook(x).sheetnames, ["Resumen", "Planes", "Obligaciones al cierre", "Cuotas pendientes al cierre",
                                                          "Cuentas Tributarias", "Pagos posteriores al cierre"])

if __name__ == "__main__":
    unittest.main()
