"""Reportes en Excel desde la web (20/11/2026): falta de presentación de DDJJ de todos los clientes."""
from __future__ import annotations

import io
from datetime import date


def _fecha(v):
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def faltas_excel(filas: list[dict], titulo_filtro: str, hoy: date | None = None) -> bytes:
    """filas: [{cuit, nombre, encargado, d: {impuesto, concepto, periodo_txt, vencimiento, establecimiento}, fecha}]."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    hoy = hoy or date.today()
    azul, rojo = PatternFill("solid", fgColor="1F4E78"), PatternFill("solid", fgColor="FFC7CE")
    wb = Workbook()

    def hoja(ws, titulo, columnas, datos, anchos, marcar=None):
        ws["A1"] = titulo
        ws["A1"].font = Font(bold=True, size=13)
        ws["A2"] = f"Generado el {hoy.strftime('%d/%m/%Y')} · {titulo_filtro}"
        ws["A2"].font = Font(italic=True, color="595959")
        for j, c in enumerate(columnas, 1):
            cel = ws.cell(4, j, c)
            cel.font, cel.fill = Font(bold=True, color="FFFFFF"), azul
            cel.alignment = Alignment(horizontal="center", wrap_text=True)
            ws.column_dimensions[get_column_letter(j)].width = anchos[j - 1]
        for i, fila in enumerate(datos, 5):
            for j, v in enumerate(fila, 1):
                cel = ws.cell(i, j, v)
                if isinstance(v, date):
                    cel.number_format = "DD/MM/YYYY"
                if marcar and marcar(fila):
                    cel.fill = rojo
        if not datos:
            ws.cell(5, 1, "Sin faltas de presentación").font = Font(italic=True, color="595959")
        ws.freeze_panes = "A5"
        if datos:
            ws.auto_filter.ref = f"A4:{get_column_letter(len(columnas))}{4 + len(datos)}"

    det = []
    for f in sorted(filas, key=lambda x: (x["nombre"].upper(), str(x["d"].get("vencimiento") or ""))):
        d = f["d"]
        v = _fecha(d.get("vencimiento"))
        det.append([f["nombre"], f"{f['cuit'][:2]}-{f['cuit'][2:10]}-{f['cuit'][10]}", f.get("encargado") or "",
                    d.get("impuesto") or "", d.get("concepto") or "", d.get("periodo_txt") or d.get("periodo") or "", v,
                    (hoy - v).days if v and v < hoy else 0, _fecha(f.get("fecha"))])
    ws = wb.active
    ws.title = "Faltas de presentación"
    hoja(ws, "Falta de presentación de declaraciones juradas", ["Cliente", "CUIT", "Encargado", "Impuesto", "Concepto",
         "Período", "Vencimiento", "Días de atraso", "Datos de ARCA al"], det, [40, 15, 16, 34, 26, 12, 13, 10, 13],
         marcar=lambda r: r[7] > 30)
    por_cli = {}
    for r in det:
        x = por_cli.setdefault(r[1], [r[0], r[1], r[2], 0, None, set()])
        x[3] += 1
        x[4] = min(filter(None, [x[4], r[6]]), default=None)
        x[5].add(r[3])
    hoja(wb.create_sheet("Por cliente"), "Faltas de presentación por cliente",
         ["Cliente", "CUIT", "Encargado", "DDJJ sin presentar", "Vencimiento más antiguo", "Impuestos"],
         sorted(([*x[:5], ", ".join(sorted(x[5]))] for x in por_cli.values()), key=lambda r: -r[3]), [40, 15, 16, 12, 14, 60])
    por_imp = {}
    for r in det:
        x = por_imp.setdefault(r[3], [r[3], 0, set()])
        x[1] += 1
        x[2].add(r[1])
    hoja(wb.create_sheet("Por impuesto"), "Faltas de presentación por impuesto", ["Impuesto", "DDJJ sin presentar", "Clientes"],
         sorted(([x[0], x[1], len(x[2])] for x in por_imp.values()), key=lambda r: -r[1]), [40, 14, 10])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ ventas para bancos (20/11/2026)
def _n(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def periodos_entre(desde: str, hasta: str) -> list[str]:
    y, m = map(int, desde.split("-"))
    yh, mh = map(int, hasta.split("-"))
    out = []
    while (y, m) <= (yh, mh) and len(out) < 60:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


MESES_TXT = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
             "noviembre", "diciembre"]


def ventas_bancos(libro: dict, desde: str, hasta: str) -> dict:
    """Ventas mes por mes desde el Libro IVA (Portal IVA, DDJJ F.2002 presentadas). libro = {periodo: json del lector}."""
    filas = []
    for p in periodos_entre(desde, hasta):
        d = libro.get(p)
        mes = f"{MESES_TXT[int(p[5:]) - 1].capitalize()} {p[:4]}"
        if not d:
            filas.append({"periodo": p, "mes": mes, "sin_dj": True})
            continue
        v = d.get("ventas") or {}
        neto = _n(v.get("Neto gravado total"))
        exento = _n(v.get("No gravado")) + _n(v.get("Exento"))
        iva = _n(v.get("Total IVA"))
        otros = _n(v.get("Otros tributos / percepciones"))
        total = _n(v.get("TOTAL COMPROBANTES")) or round(neto + exento + iva + otros, 2)
        filas.append({"periodo": p, "mes": mes, "sin_dj": False, "neto": round(neto, 2), "exento": round(exento, 2),
                      "ventas_netas": round(neto + exento, 2), "iva": round(iva, 2), "otros": round(otros, 2),
                      "total": round(total, 2), "cantidad": int(_n(v.get("Cantidad de comprobantes"))),
                      "secuencia": d.get("secuencia_portal", d.get("secuencia")) or 0})
    con = [f for f in filas if not f["sin_dj"]]
    tot = {k: round(sum(f[k] for f in con), 2) for k in ("neto", "exento", "ventas_netas", "iva", "otros", "total")}
    tot["meses"] = len(con)
    tot["promedio_netas"] = round(tot["ventas_netas"] / len(con), 2) if con else 0.0
    tot["promedio_total"] = round(tot["total"] / len(con), 2) if con else 0.0
    return {"filas": filas, "total": tot, "desde": desde, "hasta": hasta, "faltan": [f["mes"] for f in filas if f["sin_dj"]]}


def ventas_bancos_excel(r: dict, nombre: str, cuit: str, condicion: str = "", hoy: date | None = None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    hoy = hoy or date.today()
    NUM = '#,##0.00;[Red]\\-#,##0.00;"-"'
    wb = Workbook()
    ws = wb.active
    ws.title = "Ventas"
    cuit_f = f"{cuit[:2]}-{cuit[2:10]}-{cuit[10]}"
    d0, d1 = r["filas"][0]["mes"], r["filas"][-1]["mes"]
    for fila in (["DETALLE DE VENTAS MENSUALES"], [f"Contribuyente: {nombre}"], [f"CUIT: {cuit_f}" + (f"   ·   Condición frente al IVA: {condicion}" if condicion else "")],
                 [f"Período: {d0} a {d1}"], []):
        ws.append(fila)
    ws["A1"].font = Font(bold=True, size=14)
    for c in ("A2", "A3", "A4"):
        ws[c].font = Font(bold=True)
    cab = ["Mes", "Neto gravado", "Exento / no gravado", "Ventas netas (sin IVA)", "IVA débito fiscal", "Otros tributos",
           "Total facturado", "Comprobantes"]
    ws.append(cab)
    fino = Side(style="thin", color="BFBFBF")
    for j in range(1, len(cab) + 1):
        c = ws.cell(6, j)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F4E78")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for f in r["filas"]:
        if f["sin_dj"]:
            ws.append([f["mes"], "Sin DDJJ de IVA presentada"])
            ws.cell(ws.max_row, 2).font = Font(italic=True, color="9C5700")
            continue
        ws.append([f["mes"], f["neto"], f["exento"], f["ventas_netas"], f["iva"], f["otros"], f["total"], f["cantidad"]])
    ult = ws.max_row
    ws.append(["TOTAL"] + [f"=SUM({col}7:{col}{ult})" for col in "BCDEFG"] + [f"=SUM(H7:H{ult})"])
    ws.append([f"PROMEDIO MENSUAL ({r['total']['meses']} meses)"] + [f"=IFERROR(AVERAGE({col}7:{col}{ult}),0)" for col in "BCDEFG"])
    for i in range(7, ws.max_row + 1):
        for j in range(1, len(cab) + 1):
            c = ws.cell(i, j)
            c.border = Border(top=fino, bottom=fino, left=fino, right=fino)
            if 2 <= j <= 7:
                c.number_format = NUM
            if i > ult:
                c.font = Font(bold=True)
                c.fill = PatternFill("solid", fgColor="F2F2F2")
    for col, w in zip("ABCDEFGH", (30, 17, 17, 19, 17, 15, 18, 13)):
        ws.column_dimensions[col].width = w
    ws.row_dimensions[6].height = 32
    notas = ["Fuente: Libro IVA Digital — declaraciones juradas de IVA (F.2002) presentadas ante ARCA (Portal IVA).",
             "Ventas netas = neto gravado + exento y no gravado (sin IVA). Total facturado = incluye IVA y otros tributos.",
             "Importes en pesos; notas de crédito restadas."]
    if r["faltan"]:
        notas.append("Meses sin declaración jurada de IVA presentada a la fecha: " + ", ".join(r["faltan"]) + ".")
    ws.append([])
    for t in notas:
        ws.append([t])
        ws.cell(ws.max_row, 1).font = Font(italic=True, color="595959", size=9)
    ws.append([])
    ws.append([f"Lugar y fecha: ____________________, {hoy.day} de {MESES_TXT[hoy.month - 1]} de {hoy.year}"])
    ws.append([])
    ws.append(["", "", "", "", "", "_______________________________"])
    ws.append(["", "", "", "", "", "Firma y sello del Contador Público"])
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToHeight = 0
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- percepciones sin factura (22/11/2026, Gaby)
def nombres_proveedores(cuit: str) -> dict:
    """CUIT -> razón social, de los Libros IVA de compras del cliente (Mis Retenciones no trae el nombre del agente)."""
    import glob
    import json
    import os
    from . import datos
    out = {}
    for ruta in glob.glob(os.path.join(datos.DATOS, cuit, "libro_iva", "[0-9][0-9][0-9][0-9]-[0-9][0-9].json")):
        try:
            with open(ruta, encoding="utf-8") as f:
                for c in json.load(f).get("comprobantes_compras") or []:
                    if c.get("cuit") and c.get("nombre"):
                        out[str(c["cuit"])] = c["nombre"]
        except (OSError, ValueError):
            continue
    return out


def percepciones_filas(pc: dict, nombres: dict) -> tuple[list[dict], list[dict]]:
    orden = lambda x: (x.get("agente") or "", x.get("mes") or "", x.get("fecha_comprobante") or "")
    arma = lambda x: {**x, "proveedor": x.get("nombre") or nombres.get(str(x.get("agente")), "")}
    return ([arma(x) for x in sorted(pc.get("sin_comprobante") or [], key=orden)],
            [arma(x) for x in sorted(pc.get("nc_sin_comprobante") or [], key=orden)])


def percepciones_excel(pc: dict, nombre: str, cuit: str, nombres: dict, hoy: date | None = None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    hoy = hoy or date.today()
    NUM = '#,##0.00;[Red]\\-#,##0.00;"-"'
    fac, ncs = percepciones_filas(pc, nombres)
    wb = Workbook()
    fino = Side(style="thin", color="BFBFBF")

    def hoja(ws, titulo, filas, nota):
        cuit_f = f"{cuit[:2]}-{cuit[2:10]}-{cuit[10]}"
        for f in ([titulo], [f"Contribuyente: {nombre}   ·   CUIT: {cuit_f}"],
                  [f"Percepciones informadas por los agentes del {pc.get('desde') or '—'} al {pc.get('hasta') or '—'} · "
                   f"preparado el {hoy.strftime('%d/%m/%Y')}"], [nota], []):
            ws.append(f)
        ws["A1"].font = Font(bold=True, size=14)
        ws["A2"].font = Font(bold=True)
        ws["A4"].font = Font(italic=True, color="595959", size=9)
        cab = ["Impuesto", "Origen", "CUIT del agente", "Proveedor", "Régimen", "Comprobante", "Número", "Fecha",
               "Mes del Libro IVA", "Percepción", "¿Encontrado? / observaciones"]
        ws.append(cab)
        for j in range(1, len(cab) + 1):
            c = ws.cell(6, j)
            c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F4E78")
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for x in filas:
            ag = str(x.get("agente") or "")
            ws.append([x.get("impuesto"), x.get("fuente"), f"{ag[:2]}-{ag[2:10]}-{ag[10:]}" if len(ag) == 11 else ag,
                       x.get("proveedor"), x.get("regimen") or "", x.get("desc_comprobante") or "", x.get("comprobante") or "",
                       x.get("fecha_comprobante") or "", f"{(x.get('mes') or '')[5:]}/{(x.get('mes') or '')[:4]}", x.get("importe") or 0.0, ""])
        ult = ws.max_row
        if filas:
            ws.append(["TOTAL", "", "", f"{len(filas)} comprobante(s)", "", "", "", "", "", f"=SUM(J7:J{ult})", ""])
        for i in range(7, ws.max_row + 1):
            for j in range(1, len(cab) + 1):
                c = ws.cell(i, j)
                c.border = Border(top=fino, bottom=fino, left=fino, right=fino)
                if j == 10:
                    c.number_format = NUM
                if i > ult:
                    c.font = Font(bold=True)
                    c.fill = PatternFill("solid", fgColor="F2F2F2")
        for col, w in zip("ABCDEFGHIJK", (14, 22, 15, 32, 9, 24, 20, 12, 12, 15, 30)):
            ws.column_dimensions[col].width = w
        ws.row_dimensions[6].height = 32
        ws.freeze_panes = "A7"
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToHeight = 0

    ws = wb.active
    ws.title = "Facturas a buscar"
    hoja(ws, "PERCEPCIONES SIN FACTURA EN EL LIBRO IVA", fac,
         "Entraron en la DDJJ de IVA (importación automática) pero la factura no está en el Libro IVA Digital: ni el gasto ni "
         "el crédito fiscal se computaron. Buscar el comprobante.")
    if ncs:
        hoja(wb.create_sheet("Notas de crédito"), "NOTAS DE CRÉDITO CON PERCEPCIÓN SIN REGISTRAR", ncs,
             "Al revés que las facturas: si la nota de crédito no se registró, el crédito fiscal y el gasto pueden estar de más.")
    from io import BytesIO
    b = BytesIO()
    wb.save(b)
    return b.getvalue()
