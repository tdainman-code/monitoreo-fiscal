"""Lector de la 'Descarga para Importar' de ARBA (formato mostrado por Gabriel el 25/11/2026) y biblioteca de versiones."""
import io
import os
import sys
import tempfile
import zipfile
from datetime import date

R = tempfile.mkdtemp()
os.environ["ROBOTS_DATOS"] = R
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from robots import biblioteca_archivos as bib, robot_arba_retenciones as r  # noqa: E402

bib.DATOS = r.DATOS = R
res = []


def ok(c, t):
    res.append(bool(c))
    print(("✔ " if c else "✘ ") + t)


CP = ("0290230-11111111-203/08/20260000300000000000000667069FA000000005600,28\r\n"
      "0290230-22222222-326/08/20260033100000000000000000658CA-00000000869,76\r\n"
      "0290230-22222222-327/08/20260033100000000000000000700O 000000000100,00\r\n")
CB = "0490230-33333333-42026/080150513902000105283610CCP000000028431,85\r\n"
CA = "0392433-69345023-903/08/2026000026042IC05019941C000000651677,57\r\n"
b = io.BytesIO()
with zipfile.ZipFile(b, "w") as z:
    z.writestr("30712227571CP8202620261125.txt", CP)
    z.writestr("30712227571CB8202620261125.txt", CB)
    z.writestr("30712227571CA8202620261125.txt", CA)
x = r.leer_zip(b.getvalue())
f = x["filas"]
ok(len(f) == 5 and len(x["archivos"]) == 3, "lee los 3 TXT (percepciones, bancarias, aduaneras)")
cp = [y for y in f if y["regimen"] == "PERCEPCION"]
ok(cp[0]["agente"] == "30111111112" and cp[0]["fecha"] == "03/08/2026" and cp[0]["punto_venta"] == "00003"
   and cp[0]["comprobante"] == "667069" and cp[0]["importe"] == 5600.28, "percepción: agente, fecha, PV, número, importe")
ok(cp[1]["importe"] == -869.76 and cp[1]["tipo"] == "C", "nota de crédito en negativo")
ok(cp[2]["desc_comprobante"] == "OTRO COMPROBANTE" and cp[2]["importe"] == 100.0, "tipo O sin letra")
cb = next(y for y in f if y["operacion"] == "RETENCION")
ok(cb["cbu"] == "0150513902000105283610" and cb["periodo"] == "2026-08" and cb["importe"] == 28431.85, "retención bancaria con CBU")
ca = next(y for y in f if y["regimen"] == "PERCEPCION ADUANERA")
ok(ca["agente"] == "33693450239" and ca["comprobante"] == "26042IC05019941C" and ca["importe"] == 651677.57, "aduanera con despacho")
ok(r.leer_totales("Total de Deducciones PERCEPCION $1,289,423.56 RETENCIONES BANCARIAS/PSP $1,638,897.48")
   == {"PERCEPCION": 1289423.56, "RETENCIONES BANCARIAS/PSP": 1638897.48}, "lee el Total de Deducciones de la pantalla")
ok(bib.periodos(date(2026, 11, 25)) == [(2026, 9), (2026, 10)] and bib.periodos(date(2027, 1, 3)) == [(2026, 11), (2026, 12)],
   "siempre los 2 últimos meses cerrados")
c = "30712227571"
ok(bib.guardar_version(c, "2026-08", "arba", f, date(2026, 11, 25)), "primera versión guardada")
ok(bib.guardar_version(c, "2026-08", "arba", list(reversed(f)), date(2026, 11, 26)) is None, "mismo contenido: no guarda otra")
ok(bib.guardar_version(c, "2026-08", "arba", f[:-1], date(2026, 12, 11)), "cambió: guarda versión nueva")
print(f"\n{sum(res)}/{len(res)} OK")
sys.exit(0 if all(res) else 1)
