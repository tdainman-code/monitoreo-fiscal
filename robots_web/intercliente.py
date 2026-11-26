"""Facturación entre clientes del estudio (solo administradores). Gaby, 26/11/2026.

De Mis Comprobantes EMITIDOS de cada cliente se toman las facturas a otros clientes nuestros. Hay una comisión por
gestión de negocios que paga EL QUE COMPRA, sobre el TOTAL FACTURADO FINAL (con IVA). Los pares que ya se conocían de
antes se marcan y quedan afuera. Excel con una solapa por cliente comprador. Más adelante, el resultado va a la app de
cuentas corrientes como débito interno (no se factura: es reposición de gastos de infraestructura y relaciones públicas).

Marcas y porcentaje: ROBOTS_WEB_DATOS/intercliente.json  {"porcentaje": 0.0, "conocidos": ["vendedor>comprador", ...]}
"""
from __future__ import annotations

import glob
import io
import json
import os
import re

from . import datos

NOTAS_CREDITO = {3, 8, 13, 53, 110, 112, 113, 114, 203, 208, 213}


def _ruta_conf() -> str:
    return os.path.join(os.environ.get("ROBOTS_WEB_DATOS", "/var/lib/robots-web"), "intercliente.json")


def conf() -> dict:
    try:
        with open(_ruta_conf(), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    return {"porcentaje": float(d.get("porcentaje") or 0), "conocidos": list(d.get("conocidos") or [])}


def guardar_conf(c: dict) -> None:
    os.makedirs(os.path.dirname(_ruta_conf()), exist_ok=True)
    tmp = _ruta_conf() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _ruta_conf())


def _num(t) -> float:
    t = str(t or "").strip()
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t or 0)
    except ValueError:
        return 0.0


def operaciones(desde: str = "", hasta: str = "") -> list[dict]:
    """Una fila por comprobante emitido de un cliente a otro cliente nuestro."""
    clientes = {c["cuit"]: c.get("razon_social") or c["cuit"] for c in datos.lista_clientes()}
    out = []
    for vend, nom_v in clientes.items():
        for ruta in sorted(glob.glob(os.path.join(datos.DATOS, vend, "[0-9][0-9][0-9][0-9]-[0-9][0-9]", "emitidos.csv"))):
            per = os.path.basename(os.path.dirname(ruta))
            if (desde and per < desde) or (hasta and per > hasta):
                continue
            try:
                import csv
                with open(ruta, encoding="utf-8-sig", errors="replace") as f:
                    for r in csv.DictReader(f, delimiter=";"):
                        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
                        comp = re.sub(r"\D", "", r.get("Nro. Doc. Receptor") or r.get("CUIT contraparte") or "")
                        if comp == vend or comp not in clientes:
                            continue
                        m = re.match(r"\s*(\d+)", r.get("Tipo") or r.get("Tipo de Comprobante") or "")
                        tipo = int(m[1]) if m else 0
                        signo = -1 if tipo in NOTAS_CREDITO else 1
                        tc = _num(r.get("Tipo Cambio") or 1) or 1.0
                        out.append({"periodo": per, "fecha": r.get("Fecha") or r.get("Fecha de Emisión", ""), "vendedor": vend, "nombre_vendedor": nom_v,
                                    "comprador": comp, "nombre_comprador": clientes[comp], "tipo": tipo,
                                    "comprobante": f"{r.get('Punto de Venta', '')}-{r.get('Número Desde', '')}",
                                    "total": round(signo * _num(r.get("Imp. Total")) * tc, 2)})
            except OSError:
                continue
    return out


def resumen(desde: str = "", hasta: str = "") -> dict:
    c = conf()
    conocidos = set(c["conocidos"])
    ops = operaciones(desde, hasta)
    pares: dict[str, dict] = {}
    for o in ops:
        k = f"{o['vendedor']}>{o['comprador']}"
        p = pares.setdefault(k, {"clave": k, "vendedor": o["vendedor"], "nombre_vendedor": o["nombre_vendedor"],
                                 "comprador": o["comprador"], "nombre_comprador": o["nombre_comprador"],
                                 "comprobantes": 0, "total": 0.0, "conocidos": k in conocidos})
        p["comprobantes"] += 1
        p["total"] = round(p["total"] + o["total"], 2)
    for p in pares.values():
        p["comision"] = 0.0 if p["conocidos"] else round(p["total"] * c["porcentaje"] / 100, 2)
    return {"porcentaje": c["porcentaje"], "pares": sorted(pares.values(), key=lambda p: (p["nombre_comprador"], -p["total"])),
            "operaciones": ops}


def excel(desde: str = "", hasta: str = "") -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    r = resumen(desde, hasta)
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    ws.append([f"Facturación entre clientes — comisión {r['porcentaje']} % sobre el total facturado, la paga el comprador"
               + (f" — períodos {desde or 'inicio'} a {hasta or 'hoy'}" if desde or hasta else "")])
    ws["A1"].font = Font(bold=True)
    ws.append([])
    cab = ["Comprador (paga)", "CUIT comprador", "Vendedor", "CUIT vendedor", "Comprobantes", "Total facturado",
           "¿Ya se conocían?", "Comisión"]
    ws.append(cab)
    for c in ws[3]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E78")
    for p in r["pares"]:
        ws.append([p["nombre_comprador"], p["comprador"], p["nombre_vendedor"], p["vendedor"], p["comprobantes"],
                   p["total"], "Sí (sin comisión)" if p["conocidos"] else "No", p["comision"]])
    for i, w in enumerate((34, 14, 34, 14, 13, 16, 18, 14), 1):
        ws.column_dimensions[ws.cell(3, i).column_letter].width = w
    compradores = sorted({p["comprador"] for p in r["pares"]}, key=lambda x: next(p["nombre_comprador"] for p in r["pares"] if p["comprador"] == x))
    for comp in compradores:
        nom = next(p["nombre_comprador"] for p in r["pares"] if p["comprador"] == comp)
        w2 = wb.create_sheet(re.sub(r"[\[\]:*?/\\]", "", nom)[:28] or comp)
        w2.append([f"{nom} — CUIT {comp} — compras a otros clientes del estudio"])
        w2["A1"].font = Font(bold=True)
        w2.append([])
        w2.append(["Período", "Fecha", "Vendedor", "CUIT vendedor", "Comprobante", "Total", "¿Ya se conocían?", "Comisión"])
        for c in w2[3]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F4E78")
        conoc = {p["vendedor"] for p in r["pares"] if p["comprador"] == comp and p["conocidos"]}
        for o in [o for o in r["operaciones"] if o["comprador"] == comp]:
            ex = o["vendedor"] in conoc
            w2.append([o["periodo"], o["fecha"], o["nombre_vendedor"], o["vendedor"], o["comprobante"], o["total"],
                       "Sí" if ex else "No", 0.0 if ex else round(o["total"] * r["porcentaje"] / 100, 2)])
        n = w2.max_row
        w2.append(["Total", None, None, None, None, f"=SUM(F4:F{n})", None, f"=SUM(H4:H{n})"])
        for c in w2[w2.max_row]:
            c.font = Font(bold=True)
        for i, w in enumerate((10, 12, 34, 14, 18, 16, 16, 14), 1):
            w2.column_dimensions[w2.cell(3, i).column_letter].width = w
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()
