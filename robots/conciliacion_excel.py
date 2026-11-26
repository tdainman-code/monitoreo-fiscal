"""Excel del cruce de percepciones (ARCA, ARBA, AGIP) contra el Libro IVA (Portal IVA) y Mis Comprobantes.

Gaby, 26/11/2026: rango inicial de 5 años (una sola vez) y habitual de los 2 últimos meses; el reporte va a la
Biblioteca como repositorio PERMANENTE (sección Conciliaciones), uno por fecha, para rescatar el gasto deducible y el
crédito fiscal de las facturas que no se cargaron (la percepción en sí ya entró sola en la DDJJ).

DATOS/<cuit>/biblioteca/_conciliaciones/percepciones/<AAAA-MM-DD>.xlsx
"""
from __future__ import annotations

import os
from datetime import date

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
CARPETA = ("biblioteca", "_conciliaciones")


def ruta(cuit: str, tipo: str, hoy: date) -> str:
    return os.path.join(DATOS, cuit, *CARPETA, tipo, f"{hoy.isoformat()}.xlsx")


def percepciones(cuit: str, r: dict, nombre: str = "", hoy: date | None = None) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    hoy = hoy or date.today()
    wb = Workbook()
    neg = Font(bold=True)
    cab = PatternFill("solid", fgColor="1F4E78")

    def encabezado(ws, cols):
        ws.append(cols)
        for c in ws[ws.max_row]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = cab

    ws = wb.active
    ws.title = "Resumen"
    ini = r.get("rango_inicial") or {}
    filas = [
        ("Cliente", f"{nombre} — CUIT {cuit}"),
        ("Fecha del cruce", r.get("fecha")),
        ("Períodos cruzados", f"{r.get('desde') or '?'} a {r.get('hasta') or '?'} ({len(r.get('meses_cruzados') or [])} meses)"),
        ("Rango inicial (5 años)", f"hecho el {ini.get('fecha')} ({ini.get('desde')} a {ini.get('hasta')})" if ini else
         "todavía no: pedir «Cruce histórico de percepciones» (o va solo en la primera corrida de un cliente nuevo)"),
        ("Percepciones con la factura en el Libro IVA", r.get("en_libro")),
        ("Percepciones SIN la factura en el Libro IVA", len(r.get("sin_comprobante") or [])),
        ("Importe de esas percepciones (ya tomado en la DDJJ)", r.get("total_sin_comprobante")),
        ("GASTO DEDUCIBLE a rescatar", r.get("gasto_recuperable")),
        ("CRÉDITO FISCAL a rescatar (IVA de las facturas, no de la percepción)", r.get("credito_fiscal_recuperable")),
        ("Notas de crédito con percepción sin registrar", len(r.get("nc_sin_comprobante") or [])),
        ("Meses sin Libro IVA bajado (no comparables)", ", ".join(r.get("meses_sin_libro") or []) or "ninguno"),
    ]
    for k, v in filas:
        ws.append([k, v])
    for row in ws.iter_rows(min_row=8, max_row=9):
        for c in row:
            c.font = neg
    ws.column_dimensions["A"].width = 62
    ws.column_dimensions["B"].width = 60
    for c in ("B7", "B8", "B9"):
        ws[c].number_format = "#,##0.00"

    cols = ["Mes", "Fecha comprobante", "CUIT agente", "Proveedor (Mis Comprobantes)", "Comprobante", "Impuesto",
            "Fuente", "Percepción", "¿En Mis Comprobantes?", "Neto gravado", "No gravado + exento", "IVA de la factura",
            "Total factura", "Gasto deducible a rescatar", "Crédito fiscal a rescatar", "Según", "Nota"]
    for titulo, lista in (("Facturas a rescatar", r.get("sin_comprobante") or []),
                          ("Notas de crédito", r.get("nc_sin_comprobante") or [])):
        ws = wb.create_sheet(titulo)
        encabezado(ws, cols)
        for x in lista:
            mc = x.get("mc") or {}
            en_mc = x.get("en_mis_comprobantes")
            ws.append([x.get("mes"), x.get("fecha_comprobante"), x.get("agente"), mc.get("emisor", ""),
                       x.get("comprobante"), x.get("impuesto"), x.get("fuente"), x.get("importe"),
                       "Sí" if en_mc else ("No" if en_mc is False else "Sin bajar"),
                       mc.get("neto"), (mc.get("no_gravado") or 0) + (mc.get("exento") or 0) if mc else None,
                       mc.get("iva"), mc.get("total"), x.get("gasto_recuperable"), x.get("credito_fiscal_recuperable"),
                       x.get("recuperable_segun", "sin dato: buscar la factura"), x.get("nota")])
        if lista:
            n = ws.max_row
            ws.append(["Total"] + [None] * 6 + [f"=SUM(H2:H{n})"] + [None] * 5 + [f"=SUM(N2:N{n})", f"=SUM(O2:O{n})"])
            for c in ws[ws.max_row]:
                c.font = neg
        for i, w in enumerate((9, 12, 13, 30, 20, 16, 26, 13, 12, 13, 13, 13, 13, 15, 15, 40, 30), 1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = w
        for row in ws.iter_rows(min_row=2, min_col=8, max_col=15):
            for c in row:
                c.number_format = "#,##0.00"
        ws.freeze_panes = "A2"
    destino = ruta(cuit, "percepciones", hoy)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    wb.save(destino)
    return destino
