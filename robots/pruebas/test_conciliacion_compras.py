"""Conciliación de compras con los casos reales que marcó Gaby (17/11/2026), con CUIT y números de fantasía:
  - nota de crédito A en Mis Comprobantes NO computada en el Libro IVA -> va aparte en el resumen (IVA a restar);
  - tique cargado en el Libro con otro número (misma fecha, IVA y total) -> "Tomadas con otro número", no omisión;
  - el mismo tique cargado dos veces en el Libro (como Tique Factura A y como Factura A) -> "Duplicados";
  - tomada en otro mes;
  - factura C fuera del Libro -> gasto, no "no tomada"; factura B -> nada.
Uso: PYTHONPATH=. python3 robots/pruebas/test_conciliacion_compras.py
"""
import json
import os
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ["ROBOTS_DATOS"] = TMP
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from robots import conciliacion  # noqa: E402

CUIT = "20111111112"
EST, PROV, MONO, BEMI = "30700000001", "20700000002", "27700000003", "30700000004"
COLS = ["Fecha de Emisión", "Tipo de Comprobante", "Punto de Venta", "Número Desde", "Número Hasta", "Cód. Autorización",
        "Tipo Doc. Emisor", "Nro. Doc. Emisor", "Denominación Emisor", "Tipo Cambio", "Moneda"]
from robots.lector_mis_comprobantes import COLUMNAS_MONTO  # noqa: E402
COLS += COLUMNAS_MONTO


def mc(per, filas):
    os.makedirs(os.path.join(TMP, CUIT, per), exist_ok=True)
    with open(os.path.join(TMP, CUIT, per, "recibidos.csv"), "w", encoding="utf-8") as f:
        f.write(";".join(COLS) + "\n")
        for fecha, tipo, pv, num, cuit, nom, neto, iva in filas:
            d = {c: "0" for c in COLUMNAS_MONTO}
            d.update({"Imp. Neto Gravado Total": str(neto), "Imp. Neto Gravado IVA 21%": str(neto), "IVA 21%": str(iva),
                      "Total IVA": str(iva), "Imp. Total": str(round(neto + iva, 2))})
            base = {"Fecha de Emisión": fecha, "Tipo de Comprobante": str(tipo), "Punto de Venta": str(pv),
                    "Número Desde": str(num), "Número Hasta": str(num), "Cód. Autorización": "1", "Tipo Doc. Emisor": "80",
                    "Nro. Doc. Emisor": cuit, "Denominación Emisor": nom, "Tipo Cambio": "1", "Moneda": "$"}
            base.update(d)
            f.write(";".join(base[c].replace(".", ",") if c in COLUMNAS_MONTO else base[c] for c in COLS) + "\n")


def liva(per, comps):
    os.makedirs(os.path.join(TMP, CUIT, "libro_iva"), exist_ok=True)
    out = [{"fecha": f, "tipo": t, "punto_venta": pv, "numero": n, "cuit": c, "nombre": nom, "neto": neto, "iva": iva,
            "total": round(neto + iva, 2)} for f, t, pv, n, c, nom, neto, iva in comps]
    with open(os.path.join(TMP, CUIT, "libro_iva", f"{per}.json"), "w", encoding="utf-8") as fh:
        json.dump({"periodo": per, "comprobantes_compras": out}, fh)


mc("2025-11", [("2025-11-27", 3, 1, 345, PROV, "PROVEEDOR NC", 38362500.0, 8056125.0)])
liva("2025-11", [])
mc("2025-12", [])
liva("2025-12", [("2025-12-03", 81, 8, 26373, EST, "ESTACION", 17870.76, 3752.86),
                 ("2025-12-03", 1, 8, 26373, EST, "ESTACION", 17870.76, 3752.86)])
mc("2026-01", [("2026-01-08", 81, 8, 27327, EST, "ESTACION", 17789.52, 3735.80),
               ("2026-01-20", 81, 8, 27611, EST, "ESTACION", 17789.52, 3735.80),
               ("2026-01-30", 81, 8, 27895, EST, "ESTACION", 21347.38, 4482.95),
               ("2026-01-15", 11, 3, 1068, MONO, "MONOTRIBUTISTA C", 28990.0, 0.0),
               ("2026-01-16", 6, 2, 50, BEMI, "EMISOR B", 10000.0, 0.0)])
liva("2026-01", [("2026-01-08", 1, 8, 27227, EST, "ESTACION", 17789.52, 3735.80)])
mc("2026-02", [])
liva("2026-02", [("2026-01-30", 81, 8, 27895, EST, "ESTACION", 21347.38, 4482.95)])

r = conciliacion.conciliar(CUIT)
ok = True


def chk(desc, cond):
    global ok
    print(("✔ " if cond else "✘ ") + desc)
    ok &= bool(cond)


nt = {f["Número"] for f in r["no_tomadas"]}
chk("tique 27611 sin par queda como no tomado", 27611 in nt)
chk("tique 27327 NO es omisión: cargado como 27227", 27327 not in nt and
    any(f["Número"] == 27327 and f["Cargada como"].endswith("8-27227") for f in r["otro_numero"]))
chk("27227 ya no figura como 'solo en Libro IVA'", all(s["Número"] != 27227 for s in r["solo_libro_iva"]))
chk("27895 tomada en otro mes (2026-02)", any(f["Número"] == 27895 and f["Tomada en"] == "2026-02" for f in r["otro_mes"]))
chk("duplicado 8-26373 en el Libro (2 filas) con IVA de más 3.752,86",
    sum(1 for d in r["duplicados_libro"] if d["Número"] == 26373) == 2 and abs(r["iva_duplicado"] - 3752.86) < 0.01)
res = {x["Período"]: x for x in r["resumen"]}
chk("NC no computada va aparte en el resumen (no suma al importe no tomado)",
    res["2025-11"]["NC no computadas"] == 1 and res["2025-11"]["No tomados"] == 0
    and abs(res["2025-11"]["IVA de NC a restar"] + 8056125) < 1)
chk("enero: 1 no tomado (27611), 1 con otro número, 1 en otro mes",
    res["2026-01"]["No tomados"] == 1 and res["2026-01"]["Con otro número"] == 1 and res["2026-01"]["En otro mes"] == 1)
chk("factura C fuera del Libro -> gasto, no 'no tomada'; factura B -> nada",
    1068 not in nt and 50 not in nt and r["bc_fuera_libro"] == {"2026-01": 28990.0})
ruta = os.path.join(TMP, "conc.xlsx")
conciliacion.generar(CUIT, "Prueba", ruta)
from openpyxl import load_workbook  # noqa: E402
hojas = load_workbook(ruta).sheetnames
chk("Excel con hojas nuevas", "Tomadas con otro número" in hojas and "Duplicados en Libro IVA" in hojas)
aj = json.load(open(os.path.join(TMP, CUIT, "conciliacion", "ajustes_conciliacion.json")))["por_mes"]
chk("ajustes: duplicado resta en 2025-12 (IVA −3.752,86)", abs(aj["2025-12"]["duplicados_iva"] + 3752.86) < 0.01
    and abs(aj["2025-12"]["duplicados_neto"] + 17870.76) < 0.01)
chk("ajustes: NC no computada resta en 2025-11 (IVA −8.056.125)", abs(aj["2025-11"]["nc_iva"] + 8056125) < 1)
chk("ajustes: no tomada 27611 suma en 2026-01", abs(aj["2026-01"]["no_tomadas_iva"] - 3735.80) < 0.01)
from robots import informe_cliente  # noqa: E402
rel = os.path.join(TMP, "rel.xlsx")
informe_cliente.relacion_dc(CUIT, "Prueba", ["2025-11", "2025-12", "2026-01", "2026-02"], rel)
textos = [c.value for row in load_workbook(rel).active.iter_rows() for c in row if isinstance(c.value, str)]
chk("Relación D/C con bloque de ajustes", any("AJUSTES POR CONCILIACIÓN" in t for t in textos)
    and any("SALDO MENSUAL con ajustes" in t for t in textos))
print("OK" if ok else "FALLÓ")
sys.exit(0 if ok else 1)
