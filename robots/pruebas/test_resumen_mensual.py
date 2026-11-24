"""Relación D/C con 'Estado de resultados', 'Resumen mensual', 'Notas' y 'Mail para el cliente' (Tomás, 24/11/2026):
ventas y compras del Libro IVA, sueldos del F.931, IIBB SOLO de DDJJ (sin DDJJ no se inventa). Datos de fantasía.
Uso: PYTHONPATH=. python3 robots/pruebas/test_resumen_mensual.py   (si hay LibreOffice, recalcula y controla los totales)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ["ROBOTS_DATOS"] = TMP
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from openpyxl import load_workbook  # noqa: E402
from robots import informe_cliente as ic  # noqa: E402

CUIT = "30711111119"
ok = True


def chk(m, c):
    global ok
    ok &= bool(c)
    print(("✔ " if c else "✘ ") + m)


def esc(sub, per, d):
    os.makedirs(os.path.join(TMP, CUIT, sub), exist_ok=True)
    json.dump(d, open(os.path.join(TMP, CUIT, sub, f"{per}.json"), "w"))


for per, vn, cn, cc in (("2026-08", 1000.0, 1500.0, 50.0), ("2026-09", 2000.0, 900.0, 0.0)):
    esc("libro_iva", per, {"ventas": {"Neto gravado total": vn, "No gravado": 10.0, "Exento": 0.0, "Total IVA": vn * .21,
                                      "Otros tributos / percepciones": 5.0},
                           "compras": {"Neto gravado total": cn, "No gravado": 0.0, "Exento": 20.0, "Total IVA": cn * .21,
                                       "Otros tributos / percepciones": 7.0, "Impuesto a los combustibles": 3.0,
                                       "Comprobantes B/C (sin IVA discriminado)": cc},
                           "comprobantes_compras": [{"b_c": True, "tipo": 11, "total": cc}] if cc else []})
    esc("f931", per, {"Empleados": 2, "Remuneración total (Rem. 1)": 300.0, "Remuneración total (con no remunerativos)": 320.0,
                      "Contribuciones S.S. (subtotal)": 60.0, "Contribuciones O.S. (subtotal)": 18.0, "ART (L.R.T. total)": 9.0,
                      "Seguro de vida obligatorio": 1.0, "RENATRE": 0.0, "Aportes S.S. (a1)": 33.0, "Aportes O.S. (a1)": 9.0})
esc("sifere", "2026-08", {"jurisdicciones": {"901": {"determinado": 30.0}, "902": {"determinado": 12.0}}})
# 2026-09 SIN DDJJ de IIBB: no se estima

ruta = os.path.join(TMP, "rel.xlsx")
ic.relacion_dc(CUIT, "Cliente de Prueba S.A.", ["2026-07", "2026-08", "2026-09"], ruta)
wb = load_workbook(ruta)
chk(f"hojas en orden ({wb.sheetnames})", wb.sheetnames == ["Estado de resultados", "Resumen mensual", "Notas", "Relación DC",
                                                           "Mail para el cliente"])
rm = wb["Resumen mensual"]
enc = [c.value for c in rm[1]]
chk("columnas de IIBB por jurisdicción (CM03)", enc[-2:] == ["IIBB – CABA", "IIBB – Buenos Aires"])
chk("solo meses con datos (jul sin Libro IVA ni F.931 no aparece)", [rm.cell(r, 1).value for r in (2, 3, 4)] == ["Ago-2026", "Sep-2026", "Total"])
chk("sin DDJJ de IIBB no se inventa: dice 'Sin DDJJ'", rm.cell(3, 18).value == "Sin DDJJ" and rm.cell(3, 19).value is None)
chk("compras sin crédito fiscal = Facturas C", rm.cell(2, 9).value == 50.0)
chk("sueldos con no remunerativos y cargas = contrib. + ART + SCVO", rm.cell(2, 14).value == 320.0 and rm.cell(2, 15).value == 88.0)
mail = "\n".join(str(c.value or "") for c in wb["Mail para el cliente"]["A"])
chk("mail modelo con el nombre y el pedido de justificar la pérdida (préstamos / proveedores / facturar)",
    "Cliente de Prueba S.A." in mail and "préstamos tomados en blanco" in mail and "tiene que ser facturada" in mail)
chk("mail guardado para la web", os.path.exists(os.path.join(TMP, CUIT, "mail_relacion_dc.txt")))
notas = " ".join(str(c.value or "") for c in wb["Notas"]["A"])
chk("notas: IIBB solo de DDJJ, facturas B nunca", "No se estima ni se presume" in notas and "Facturas B de compra NO se toman" in notas)

soffice = shutil.which("soffice") or shutil.which("libreoffice")
if soffice:
    out = os.path.join(TMP, "calc")
    subprocess.run([soffice, "--headless", "--convert-to", "xlsx", "--outdir", out, ruta], capture_output=True, timeout=180)
    w2 = load_workbook(os.path.join(out, "rel.xlsx"), data_only=True)
    er = w2["Estado de resultados"]
    fila = {er.cell(r, 1).value: [er.cell(r, j).value for j in range(2, 5)] for r in range(5, 14)}
    v = fila["Ventas netas (neto gravado + no gravado / exento)"]
    chk(f"estado: ventas netas ago/sep/total {v}", v == [1010, 2010, 3020])
    c_ = fila["Compras netas (neto + no gravado / exento + sin CF + combustibles)"]
    chk(f"estado: compras netas {c_}", c_ == [1573, 923, 2496])
    op = fila["RESULTADO OPERATIVO"]
    # ago: 1010-1573-320-88-42 = -1013 ; sep: 2010-923-320-88-0 = 679
    chk(f"estado: resultado operativo {op} (IIBB de sep sin DDJJ no resta)", [round(x, 2) for x in op] == [-1013, 679, -334])
    rs = w2["Resumen mensual"]
    chk("resumen: total de IIBB solo lo declarado (42)", rs.cell(4, 18).value == 42)
else:
    print("(sin LibreOffice: no se recalculan las fórmulas)")
print("OK" if ok else "FALLÓ")
sys.exit(0 if ok else 1)
