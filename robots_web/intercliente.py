"""Facturación entre clientes del estudio (solo administradores). Gaby, 26/11/2026.

De Mis Comprobantes EMITIDOS de cada cliente se toman las facturas a otros clientes nuestros. Hay una comisión por
gestión de negocios que paga EL QUE COMPRA, sobre el TOTAL FACTURADO FINAL (con IVA). Los pares que ya se conocían de
antes se marcan y quedan afuera. Excel con una solapa por cliente comprador. Más adelante, el resultado va a la app de
cuentas corrientes como débito interno (no se factura: es reposición de gastos de infraestructura y relaciones públicas).

Marcas y porcentaje: ROBOTS_WEB_DATOS/intercliente.json
  {"porcentaje": 0.0, "conocidos": ["vendedor>comprador", ...], "propios": [cuit, ...], "grupos": [[cuit, cuit], ...]}
Exclusiones (Gaby 26/11/2026):
  - "propios": somos nosotros (BH, Tallpir, Arturo, Mancovsky, Dainman) que le facturamos al cliente -> nunca van.
  - "grupos": clientes del mismo dueño (Nabajuma y Dinafer) -> lo que se facturan entre ellos nunca va.
  Si el archivo todavía no tiene esas claves, se arrancan por nombre (PROPIOS_NOMBRES / GRUPOS_NOMBRES) y se corrigen en pantalla.
"""
from __future__ import annotations

import glob
import io
import json
import os
import re

from . import datos

# Arturo va por CUIT (Gaby 26/11/2026: "busca por cuit, no existen 2 personas con el mismo cuit"): se carga en pantalla.
PROPIOS_NOMBRES = r"\bBH SOLUCIONES|\bTALLPIR|\bMANCOVSKY|\bDAINMAN"
GRUPOS_NOMBRES = [r"\bNABAJUMA", r"\bDINAFER"]
NOTAS_CREDITO = {3, 8, 13, 53, 110, 112, 113, 114, 203, 208, 213}
# Columnas como el Libro IVA (Gaby 26/11/2026): (clave, título, columnas posibles del CSV de Mis Comprobantes)
IMPORTES = [("neto_gravado", "Neto gravado", ("Imp. Neto Gravado Total", "Imp. Neto Gravado")),
            ("no_gravado", "No gravado", ("Imp. Neto No Gravado",)),
            ("exento", "Exento", ("Imp. Op. Exentas",)),
            ("iva_21", "IVA 21%", ("IVA 21%",)),
            ("iva_105", "IVA 10,5%", ("IVA 10,5%",)),
            ("iva_27", "IVA 27%", ("IVA 27%",)),
            ("iva_otros", "IVA otras alícuotas", ("IVA 2,5%", "IVA 5%")),
            ("iva", "Total IVA", ("Total IVA", "IVA")),
            ("otros_tributos", "Otros tributos", ("Otros Tributos",)),
            ("total", "Total", ("Imp. Total",))]


def _ruta_conf() -> str:
    return os.path.join(os.environ.get("ROBOTS_WEB_DATOS", "/var/lib/robots-web"), "intercliente.json")


def conf() -> dict:
    try:
        with open(_ruta_conf(), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    out = {"porcentaje": float(d.get("porcentaje") or 0), "conocidos": list(d.get("conocidos") or []),
           "propios": d.get("propios"), "grupos": d.get("grupos")}
    if out["propios"] is None or out["grupos"] is None:
        cl = [(c["cuit"], (c.get("razon_social") or "").upper()) for c in datos.lista_clientes()]
        if out["propios"] is None:
            out["propios"] = sorted(x for x, n in cl if re.search(PROPIOS_NOMBRES, n))
        if out["grupos"] is None:
            g = sorted({x for x, n in cl for rx in GRUPOS_NOMBRES if re.search(rx, n)})
            out["grupos"] = [g] if len(g) > 1 else []
    return out


def excluido(c: dict, vend: str, comp: str) -> str:
    """Motivo por el que una venta entre clientes nunca va al listado ('' = va)."""
    if vend in c["propios"] or comp in c["propios"]:
        return "del estudio"
    if any(vend in g and comp in g for g in c["grupos"]):
        return "mismo dueño"
    return ""


def unir_grupo(grupos: list, a: str, b: str) -> list:
    juntos = {a, b}
    resto = []
    for g in grupos:
        if juntos & set(g):
            juntos |= set(g)
        else:
            resto.append(g)
    return resto + [sorted(juntos)]


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


def _importes(r: dict, factor: float) -> dict:
    out = {}
    for clave, _, cols in IMPORTES:
        if clave == "iva_otros":
            v = sum(_num(r.get(c)) for c in cols)
        else:
            v = next((_num(r.get(c)) for c in cols if c in r), 0.0)
        out[clave] = round(v * factor, 2)
    return out


def operaciones(desde: str = "", hasta: str = "", cliente: str = "") -> list[dict]:
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
                                    "tipo_txt": r.get("Tipo") or r.get("Tipo de Comprobante") or "",
                                    **_importes(r, signo * tc)})
            except OSError:
                continue
    if cliente:
        out = [o for o in out if cliente in (o["vendedor"], o["comprador"])]
    return out


def resumen(desde: str = "", hasta: str = "", cliente: str = "") -> dict:
    c = conf()
    conocidos = set(c["conocidos"])
    todas = operaciones(desde, hasta, cliente)
    ops = [o for o in todas if not excluido(c, o["vendedor"], o["comprador"])]
    pares: dict[str, dict] = {}
    for o in ops:
        k = f"{o['vendedor']}>{o['comprador']}"
        p = pares.setdefault(k, {"clave": k, "vendedor": o["vendedor"], "nombre_vendedor": o["nombre_vendedor"],
                                 "comprador": o["comprador"], "nombre_comprador": o["nombre_comprador"],
                                 "comprobantes": 0, "conocidos": k in conocidos, **{x[0]: 0.0 for x in IMPORTES}})
        p["comprobantes"] += 1
        for x in IMPORTES:
            p[x[0]] = round(p[x[0]] + o[x[0]], 2)
    for p in pares.values():
        p["comision"] = 0.0 if p["conocidos"] else round(p["total"] * c["porcentaje"] / 100, 2)
    nombres = {x["cuit"]: x.get("razon_social") or x["cuit"] for x in datos.lista_clientes()}
    excl: dict[str, dict] = {}
    for o in todas:
        m = excluido(c, o["vendedor"], o["comprador"])
        if m:
            e = excl.setdefault(f"{o['vendedor']}>{o['comprador']}", {"nombre_vendedor": o["nombre_vendedor"],
                                "nombre_comprador": o["nombre_comprador"], "motivo": m, "comprobantes": 0, "total": 0.0})
            e["comprobantes"] += 1
            e["total"] = round(e["total"] + o["total"], 2)
    return {"porcentaje": c["porcentaje"], "excluidos": sorted(excl.values(), key=lambda e: (e["motivo"], -e["total"])),
            "propios": [{"cuit": x, "nombre": nombres.get(x, x)} for x in c["propios"]],
            "grupos": [[{"cuit": x, "nombre": nombres.get(x, x)} for x in g] for g in c["grupos"]],
            "pares": sorted(pares.values(), key=lambda p: (p["nombre_comprador"], -p["total"])),
            "operaciones": ops}


def excel(desde: str = "", hasta: str = "", cliente: str = "") -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    r = resumen(desde, hasta, cliente)
    tits = [x[1] for x in IMPORTES]
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    ws.append([f"Facturación entre clientes — comisión {r['porcentaje']} % sobre el total facturado, la paga el comprador"
               + (f" — períodos {desde or 'inicio'} a {hasta or 'hoy'}" if desde or hasta else "")])
    ws["A1"].font = Font(bold=True)
    ws.append([])
    cab = ["Comprador (paga)", "CUIT comprador", "Vendedor", "CUIT vendedor", "Comprobantes", *tits,
           "¿Ya se conocían?", "Comisión"]
    ws.append(cab)
    for c in ws[3]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E78")
    for p in r["pares"]:
        ws.append([p["nombre_comprador"], p["comprador"], p["nombre_vendedor"], p["vendedor"], p["comprobantes"],
                   *[p[x[0]] for x in IMPORTES], "Sí (sin comisión)" if p["conocidos"] else "No", p["comision"]])
    for i, w in enumerate((34, 14, 34, 14, 13, *[15] * len(IMPORTES), 18, 14), 1):
        ws.column_dimensions[ws.cell(3, i).column_letter].width = w
    wc = wb.create_sheet("Comprobantes")
    wc.append(["Todos los comprobantes entre clientes, uno por uno (como el Libro IVA)"])
    wc["A1"].font = Font(bold=True)
    wc.append([])
    wc.append(["Período", "Fecha", "Tipo", "Comprobante", "Vendedor", "CUIT vendedor", "Comprador (paga)", "CUIT comprador",
               *tits, "¿Ya se conocían?", "Comisión"])
    for c in wc[3]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E78")
    conoc_all = {p["clave"] for p in r["pares"] if p["conocidos"]}
    for o in sorted(r["operaciones"], key=lambda o: (o["periodo"], o["fecha"], o["nombre_vendedor"])):
        ex = f"{o['vendedor']}>{o['comprador']}" in conoc_all
        wc.append([o["periodo"], o["fecha"], o["tipo_txt"], o["comprobante"], o["nombre_vendedor"], o["vendedor"],
                   o["nombre_comprador"], o["comprador"], *[o[x[0]] for x in IMPORTES], "Sí" if ex else "No",
                   0.0 if ex else round(o["total"] * r["porcentaje"] / 100, 2)])
    for i, w in enumerate((10, 12, 22, 18, 30, 14, 30, 14, *[15] * len(IMPORTES), 16, 14), 1):
        wc.column_dimensions[get_column_letter(i)].width = w
    wc.freeze_panes = "A4"
    compradores = sorted({p["comprador"] for p in r["pares"]}, key=lambda x: next(p["nombre_comprador"] for p in r["pares"] if p["comprador"] == x))
    for comp in compradores:
        nom = next(p["nombre_comprador"] for p in r["pares"] if p["comprador"] == comp)
        w2 = wb.create_sheet(re.sub(r"[\[\]:*?/\\]", "", nom)[:28] or comp)
        w2.append([f"{nom} — CUIT {comp} — compras a otros clientes del estudio"])
        w2["A1"].font = Font(bold=True)
        w2.append([])
        w2.append(["Período", "Fecha", "Tipo", "Comprobante", "Vendedor", "CUIT vendedor", *tits, "¿Ya se conocían?", "Comisión"])
        for c in w2[3]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F4E78")
        conoc = {p["vendedor"] for p in r["pares"] if p["comprador"] == comp and p["conocidos"]}
        for o in [o for o in r["operaciones"] if o["comprador"] == comp]:
            ex = o["vendedor"] in conoc
            w2.append([o["periodo"], o["fecha"], o["tipo_txt"], o["comprobante"], o["nombre_vendedor"], o["vendedor"],
                       *[o[x[0]] for x in IMPORTES], "Sí" if ex else "No", 0.0 if ex else round(o["total"] * r["porcentaje"] / 100, 2)])
        n = w2.max_row
        sumas = [f"=SUM({get_column_letter(i)}4:{get_column_letter(i)}{n})" for i in range(7, 7 + len(IMPORTES))]
        com = get_column_letter(8 + len(IMPORTES))
        w2.append(["Total", None, None, None, None, None, *sumas, None, f"=SUM({com}4:{com}{n})"])
        for c in w2[w2.max_row]:
            c.font = Font(bold=True)
        for i, w in enumerate((10, 12, 22, 18, 34, 14, *[15] * len(IMPORTES), 16, 14), 1):
            w2.column_dimensions[w2.cell(3, i).column_letter].width = w
    for w in wb.worksheets:
        for row in w.iter_rows(min_row=4):
            for c in row:
                if isinstance(c.value, float) or (isinstance(c.value, str) and c.value.startswith("=SUM")):
                    c.number_format = "#,##0.00"
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()
