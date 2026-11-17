"""Conciliación de compras: Mis Comprobantes (recibidos) contra Libro IVA (Portal IVA). Responsables inscriptos.

Pedido del 16/11/2026:
  - Facturas de compra (NO B) que están en Mis Comprobantes y NO figuran en el Libro IVA de ese mes ni de los
    siguientes -> para ver si fue una omisión o si no correspondía tomarlas.
  - Control APOC: si el emisor está en la base de facturas apócrifas, la fila va en rojo con alerta.
  - Al revés, informativo: comprobantes del Libro IVA que no están en Mis Comprobantes (despachos de
    importación, servicios públicos, etc.).
Solo se comparan meses con Libro IVA bajado (DJ presentada). No entra a ARCA: usa lo que bajaron los robots.

APOC: los "Comprobantes electrónicos observados" que ARCA le informa a cada cliente en Nuestra Parte
(robot_observados -> DATOS/<cuit>/observados/observados.json). Cada observado se cruza con el Libro IVA:
si quedó COMPUTADO como crédito, riesgo ALTO (habría que rectificar). Opcional: DATOS/apoc/apoc.csv con
CUIT de emisores apócrifos de otras fuentes.

Uso:  python3 -m robots.conciliacion --cuit 20331162788
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
from datetime import date

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
INFORMES = os.environ.get("ROBOTS_INFORMES", "/var/lib/robots/informes")
TIPOS_B = {6, 7, 8, 9, 10, 82}            # B: no se concilian (no dan crédito)
NOTAS_CREDITO = {3, 8, 13, 53, 110, 112, 113, 114, 203, 208, 213}
NOMBRES = {1: "Factura A", 2: "Nota de Débito A", 3: "Nota de Crédito A", 11: "Factura C", 12: "Nota de Débito C",
           13: "Nota de Crédito C", 17: "Liq. Servicios Públicos A", 51: "Factura M", 63: "Liquidación A",
           66: "Despacho de importación", 81: "Tique Factura A", 83: "Tique"}


def _leer_json(r):
    with open(r, encoding="utf-8") as f:
        return json.load(f)


def base_apoc() -> set[str] | None:
    ruta = os.path.join(DATOS, "apoc", "apoc.csv")
    if not os.path.exists(ruta):
        return None
    with open(ruta, encoding="utf-8", errors="replace") as f:
        return {m for linea in f for m in re.findall(r"(?<!\d)(\d{11})(?!\d)", linea.replace("-", ""))}


def _clave(cuit, tipo, pv, num):
    return (str(cuit).strip().lstrip("0"), int(tipo), int(pv), int(num))


def _mc_recibidos(cuit: str, periodo: str) -> list[dict]:
    ruta = os.path.join(DATOS, cuit, periodo, "recibidos.csv")
    if not os.path.exists(ruta):
        return []
    from .lector_mis_comprobantes import leer
    df = leer(ruta)
    out = []
    for _, x in df.iterrows():
        try:
            num = int(str(x.get("Número Desde", "0")).split(".")[0] or 0)
            pv = int(str(x.get("Punto de Venta", "0")).split(".")[0] or 0)
        except ValueError:
            continue
        out.append({"periodo": periodo, "fecha": x["Fecha"].date(), "tipo": int(x["Tipo"]), "punto_venta": pv,
                    "numero": num, "cuit": str(x["CUIT contraparte"]).strip(), "nombre": x["Contraparte"],
                    "neto": float(x["Imp. Neto Gravado Total"]), "iva": float(x["Total IVA"]),
                    "total": float(x["Imp. Total"])})
    return out


def conciliar(cuit: str) -> dict:
    liva = {}
    for r in sorted(glob.glob(os.path.join(DATOS, cuit, "libro_iva", "[0-9][0-9][0-9][0-9]-[0-9][0-9].json"))):
        d = _leer_json(r)
        liva[os.path.basename(r)[:7]] = d.get("comprobantes_compras") or []
    if not liva:
        return {"sin_libro_iva": True}
    hasta = max(liva)
    apoc = base_apoc()
    ruta_obs = os.path.join(DATOS, cuit, "observados", "observados.json")
    obs_d = _leer_json(ruta_obs) if os.path.exists(ruta_obs) else None
    observados = (obs_d or {}).get("comprobantes") or []
    obs_claves = {_clave(o["cuit"], o["tipo"], o["punto_venta"], o["numero"]) for o in observados}
    obs_cuits = {o["cuit"].lstrip("0") for o in observados}
    if obs_d is not None:
        apoc = (apoc or set()) | obs_cuits

    def marca_apoc(c, k):
        if k in obs_claves:
            return "SÍ - OBSERVADO POR ARCA"
        if apoc is not None and c["cuit"].lstrip("0") in apoc:
            return "SÍ - EMISOR OBSERVADO/APÓCRIFO"
        return "no" if apoc is not None else "sin verificar"
    # índice del Libro IVA: clave completa y clave sin tipo (por si el tipo se cargó distinto)
    tomado, tomado_sin_tipo = {}, {}
    for per, comps in liva.items():
        for c in comps:
            k = _clave(c["cuit"], c["tipo"], c["punto_venta"], c["numero"])
            tomado.setdefault(k, per)
            tomado_sin_tipo.setdefault(k[:1] + k[2:], per)
    no_tomadas, otro_mes, vistos_mc = [], [], set()
    resumen = []
    for per in sorted(liva):
        mc = _mc_recibidos(cuit, per)
        if not mc:
            resumen.append({"Período": per, "Mis Comprobantes": "sin bajar", "Comprobantes MC (no B)": None,
                            "No tomados": None, "Importe no tomado": None, "En otro mes": None})
            continue
        n_nt = imp_nt = n_om = n = 0
        for c in mc:
            k = _clave(c["cuit"], c["tipo"], c["punto_venta"], c["numero"])
            vistos_mc.add(k)
            vistos_mc.add(k[:1] + k[2:])
            if c["tipo"] in TIPOS_B:
                continue
            n += 1
            donde = tomado.get(k) or tomado_sin_tipo.get(k[:1] + k[2:])
            fila = {"Período MC": per, "Fecha": c["fecha"], "Comprobante": NOMBRES.get(c["tipo"], f"Tipo {c['tipo']}"),
                    "Pto. venta": c["punto_venta"], "Número": c["numero"], "CUIT emisor": c["cuit"],
                    "Emisor": c["nombre"], "Neto gravado": c["neto"], "IVA": c["iva"], "Total": c["total"],
                    "APOC": marca_apoc(c, k),
                    "Nota de crédito": "Sí" if c["tipo"] in NOTAS_CREDITO else ""}
            if not donde:
                fila["Libro IVA revisado hasta"] = hasta
                fila["Observación"] = ("Nota de crédito NO computada (debería restar crédito)" if c["tipo"] in NOTAS_CREDITO
                                       else "No tomada: ¿omisión o no correspondía?")
                if per == hasta:
                    fila["Observación"] += " — puede tomarse en la DJ del mes siguiente"
                no_tomadas.append(fila)
                n_nt += 1
                imp_nt += c["total"]
            elif donde != per:
                fila["Tomada en"] = donde
                otro_mes.append(fila)
                n_om += 1
        resumen.append({"Período": per, "Mis Comprobantes": "OK", "Comprobantes MC (no B)": n,
                        "No tomados": n_nt, "Importe no tomado": round(imp_nt, 2), "En otro mes": n_om})
    solo_liva = []
    for per, comps in liva.items():
        if not _mc_recibidos(cuit, per):
            continue
        for c in comps:
            k = _clave(c["cuit"], c["tipo"], c["punto_venta"], c["numero"])
            if k in vistos_mc or (k[:1] + k[2:]) in vistos_mc:
                continue
            solo_liva.append({"Período": per, "Fecha": c["fecha"], "Comprobante": NOMBRES.get(c["tipo"], f"Tipo {c['tipo']}"),
                              "Pto. venta": c["punto_venta"], "Número": c["numero"], "CUIT emisor": c["cuit"],
                              "Emisor": c["nombre"], "Neto gravado": c["neto"], "IVA": c["iva"], "Total": c["total"]})
    # Observados por ARCA cruzados con el Libro IVA
    desde = min(liva)
    obs_filas = []
    for o in observados:
        k = _clave(o["cuit"], o["tipo"], o["punto_venta"], o["numero"])
        donde = tomado.get(k) or tomado_sin_tipo.get(k[:1] + k[2:])
        f_txt = str(o.get("fecha") or "")
        per_cbte = f_txt[:7] if re.match(r"\d{4}-\d{2}", f_txt) else ""
        if donde:
            comp = f"COMPUTADO en Libro IVA {donde}"
        elif per_cbte and per_cbte < desde:
            comp = f"anterior a {desde}: no revisado"
        else:
            comp = "no computado"
        anul = o.get("anulada_con") or ""
        if not donde:
            riesgo = "Bajo (no computado)" if not comp.startswith("anterior") else "Revisar a mano"
        elif anul:
            par = next((x for x in observados if x is not o and x.get("anulada_con") and x["cuit"] == o["cuit"]
                        and abs(x["total"] - o["total"]) < 0.01 and x["nc"] != o["nc"]), None)
            k2 = _clave(par["cuit"], par["tipo"], par["punto_venta"], par["numero"]) if par else None
            par_comp = bool(par and (tomado.get(k2) or tomado_sin_tipo.get(k2[:1] + k2[2:])))
            riesgo = ("Neutro (factura y NC computadas)" if par_comp
                      else "ALTO: computado sin su anulación" if not o["nc"] else "Revisar: NC computada sin la factura")
        else:
            riesgo = "ALTO: crédito fiscal observado — evaluar rectificar"
        obs_filas.append({"Fecha": o.get("fecha"), "Comprobante": o.get("tipo_txt"), "Pto. venta": o["punto_venta"],
                          "Número": o["numero"], "CUIT emisor": o["cuit"], "Emisor": o["nombre"],
                          "IVA": o["iva"] * (-1 if o["nc"] else 1), "Total": o["total"] * (-1 if o["nc"] else 1),
                          "Anulación": anul, "En Libro IVA": comp, "Riesgo": riesgo})
    apoc_alertas = [f for f in no_tomadas + otro_mes if f["APOC"].startswith("SÍ")] + \
                   [f for f in obs_filas if f["Riesgo"].startswith("ALTO")]
    return {"no_tomadas": no_tomadas, "otro_mes": otro_mes, "solo_libro_iva": solo_liva, "resumen": resumen,
            "apoc": ("sin verificar (falta correr el robot de observados)" if obs_d is None
                     else f"{len(observados)} comprobantes observados por ARCA (consulta del {obs_d.get('fecha')})"),
            "alertas_apoc": apoc_alertas, "observados": obs_filas,
            "hasta": hasta}


def generar(cuit: str, nombre: str, ruta: str) -> dict | None:
    r = conciliar(cuit)
    if r.get("sin_libro_iva"):
        return None
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    AZUL, ROJO, ROJO_FUERTE, AMARILLO = "1F4E78", "FFC7CE", "FF7C80", "FFEB9C"
    NUM = '#,##0.00;[Red]\\-#,##0.00;"-"'
    wb = Workbook()
    wb.remove(wb.active)

    def hoja(titulo, sub, filas, columnas, color=None):
        ws = wb.create_sheet(titulo[:31])
        ws["A1"] = f"{titulo} — {nombre} — CUIT {cuit[:2]}-{cuit[2:10]}-{cuit[10]}"
        ws["A1"].font = Font(bold=True, size=13)
        ws["A2"] = sub
        ws["A2"].font = Font(italic=True, color="595959")
        for j, c in enumerate(columnas, 1):
            cel = ws.cell(4, j, c)
            cel.font = Font(bold=True, color="FFFFFF")
            cel.fill = PatternFill("solid", fgColor=AZUL)
            cel.alignment = Alignment(wrap_text=True, horizontal="center")
        for i, f in enumerate(filas, 5):
            col = color(f) if color else None
            for j, c in enumerate(columnas, 1):
                v = f.get(c)
                cel = ws.cell(i, j, v)
                if isinstance(v, float):
                    cel.number_format = NUM
                elif isinstance(v, date):
                    cel.number_format = "DD/MM/YYYY"
                if col:
                    cel.fill = PatternFill("solid", fgColor=col)
        if not filas:
            ws.cell(5, 1, "Sin casos").font = Font(italic=True, color="595959")
        for j, c in enumerate(columnas, 1):
            largo = max([len(str(c))] + [len(str(f.get(c, ""))) for f in filas[:300]])
            ws.column_dimensions[get_column_letter(j)].width = min(48, max(10, largo + 2))
        ws.freeze_panes = "A5"
        if filas:
            ws.auto_filter.ref = f"A4:{get_column_letter(len(columnas))}{4 + len(filas)}"
        return ws

    cols = ["Período MC", "Fecha", "Comprobante", "Pto. venta", "Número", "CUIT emisor", "Emisor", "Neto gravado",
            "IVA", "Total", "APOC", "Observación", "Libro IVA revisado hasta"]
    rojo = lambda f: ROJO_FUERTE if f["APOC"].startswith("SÍ") else ROJO
    hoja("No tomadas en Libro IVA",
         f"Compras de Mis Comprobantes (sin facturas B) que no figuran en el Libro IVA de ese mes ni de los siguientes "
         f"(revisado hasta {r['hasta']}). Base APOC: {r['apoc']}.", r["no_tomadas"], cols, rojo)
    hoja("Tomadas en otro mes", "Comprobantes de Mis Comprobantes computados en un Libro IVA de un mes distinto.",
         r["otro_mes"], cols[:11] + ["Tomada en"], lambda f: ROJO_FUERTE if f["APOC"].startswith("SÍ") else AMARILLO)
    hoja("Solo en Libro IVA", "Informativo: comprobantes del Libro IVA que no están en Mis Comprobantes "
         "(despachos de importación, servicios públicos, etc.).", r["solo_libro_iva"],
         ["Período", "Fecha", "Comprobante", "Pto. venta", "Número", "CUIT emisor", "Emisor", "Neto gravado", "IVA", "Total"])
    hoja("Observados por ARCA (APOC)",
         "Comprobantes electrónicos observados (Nuestra Parte): proveedores sin capacidad técnico-económica según ARCA. "
         f"No deben computarse como crédito ni deducción. {r['apoc']}.", r["observados"],
         ["Fecha", "Comprobante", "Pto. venta", "Número", "CUIT emisor", "Emisor", "IVA", "Total", "Anulación",
          "En Libro IVA", "Riesgo"],
         lambda f: ROJO_FUERTE if f["Riesgo"].startswith("ALTO") else AMARILLO if f["Riesgo"].startswith(("Revisar", "Neutro")) else None)
    ws = hoja("Resumen", "Por período con Libro IVA bajado.", r["resumen"],
              ["Período", "Mis Comprobantes", "Comprobantes MC (no B)", "No tomados", "Importe no tomado", "En otro mes"],
              lambda f: ROJO if f.get("No tomados") else None)
    wb.move_sheet(ws, offset=-4)
    wb.active = 0
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    wb.save(ruta)
    return r


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cuit", required=True)
    a = ap.parse_args(argv)
    from .informe import nombre
    ruta = os.path.join(INFORMES, date.today().isoformat(), f"conciliacion_compras_{a.cuit}.xlsx")
    r = generar(a.cuit, nombre(a.cuit, {}) or a.cuit, ruta)
    if r is None:
        print("Sin Libro IVA bajado para este CUIT (monotributista o falta correr el robot libro_iva)")
        return
    print(f"No tomadas: {len(r['no_tomadas'])}   en otro mes: {len(r['otro_mes'])}   "
          f"solo en Libro IVA: {len(r['solo_libro_iva'])}   APOC: {len(r['alertas_apoc'])}\n{ruta}")


if __name__ == "__main__":
    main()
