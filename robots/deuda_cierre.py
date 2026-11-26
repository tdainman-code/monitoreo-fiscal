"""Deuda fiscal al cierre de balance (Gaby, 26/11/2026). Primera parte: los PLANES DE PAGO en cualquier estado.

Para una fecha de cierre F, por cada plan de Mis Facilidades (robot_planes_todos):
  - Plan consolidado DESPUÉS de F: las obligaciones que incluye con vencimiento hasta F eran deuda a F
    (se toma el "Saldo a Cancelar" de cada obligación: lo que quedaba después de los pagos imputados).
  - Plan consolidado hasta F: la deuda a F es el capital de las cuotas no pagadas a F (sin pago registrado hasta F;
    si no hay fecha de pago, la cuota cancelada cuenta como pagada si venció hasta F). El interés financiero de esas
    cuotas va aparte (es interés futuro, no deuda a F).
Falta (cuando Gaby lo muestre): deuda de Cuentas Tributarias a F y los conceptos del F.931 de "estado de deuda".
Excel al repositorio permanente: DATOS/<cuit>/biblioteca/_conciliaciones/deuda_cierre/<AAAA-MM-DD>.xlsx
"""
from __future__ import annotations

import calendar
import glob
import json
import os
import re
from datetime import date

from . import lector_situacion as ls

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]


def _dicts(tabla: dict) -> list[dict]:
    cab = tabla.get("encabezados") or []
    return [dict(zip(cab, f.get("celdas") or [])) for f in tabla.get("filas") or []]


def _g(d: dict, *claves) -> str:
    for k in d:
        if any(re.sub(r"\W", "", k).lower().startswith(re.sub(r"\W", "", c).lower()) for c in claves):
            return d[k]
    return ""


def mes_cierre(cuit: str) -> int | None:
    try:
        from . import avisos
        v = (avisos.contactos().get(cuit) or {}).get("mes_cierre") or ""
    except Exception:
        v = ""
    v = str(v).strip().lower()
    if v in MESES:
        return MESES.index(v) + 1
    if v.isdigit() and 1 <= int(v) <= 12:
        return int(v)
    r = sorted(glob.glob(os.path.join(DATOS, cuit, "sistema_registral", "*.json")))
    if r:
        try:
            mc = json.load(open(r[-1], encoding="utf-8")).get("mes_cierre")
            if str(mc).isdigit() and 1 <= int(mc) <= 12:
                return int(mc)
        except (OSError, ValueError):
            pass
    return None


def cierres(cuit: str, hoy: date | None = None, n: int = 2) -> list[date]:
    """Las n últimas fechas de cierre de balance ya pasadas."""
    hoy = hoy or date.today()
    m = mes_cierre(cuit) or 12                       # sin mes de cierre en la ficha: 31/12 (el más común)
    out, a = [], hoy.year
    while len(out) < n:
        f = date(a, m, calendar.monthrange(a, m)[1])
        if f < hoy:
            out.append(f)
        a -= 1
    return out


def _norm(t) -> str:
    return re.sub(r"\s+", " ", str(t or "")).strip().lower()


def leer_cuotas(tabla: dict) -> dict[int, dict]:
    """Pantalla Ver Pagos (SeguimientoDetallePagos). Cada cuota puede ocupar 2 filas (1° y 2° vencimiento, con
    rowspan en Cuota N°, Capital y Estado). En la columna Pago dice "Pago" en la fila del vencimiento en que se pagó;
    si hay un botón (celda vacía) no se pagó en ese vencimiento. Caso Nabajuma T587743 (caduco): cuota 6 pagada al
    2° vencimiento, cuotas 1/5/7 impagas, cuotas posteriores a la caducidad sin estado."""
    out, actual = {}, None
    for f in tabla.get("filas") or []:
        c = [(x or "").strip() for x in f.get("celdas") or []]
        if not c or _norm(c[0]).startswith(("total", "cuota")):
            continue
        fechas = [ls.fecha(x) for x in c if ls.fecha(x)]
        pago = any(_norm(x) == "pago" for x in c)
        if re.fullmatch(r"\d+", c[0]) and len(c) >= 7:
            actual = int(c[0])
            est = c[-1] if not ls.fecha(c[-1]) and _norm(c[-1]) != "pago" and ls.importe(c[-1]) is None else ""
            out[actual] = {"cuota": actual, "capital": ls.importe(c[1]) or 0.0, "interes": ls.importe(c[2]) or 0.0,
                           "estado": est, "vencimientos": [], "pagada_el": None, "importe_pagado": None}
        elif actual is None:
            continue
        q = out[actual]
        if fechas:
            q["vencimientos"].append(fechas[0])
        if pago and fechas and not q["pagada_el"]:
            q["pagada_el"] = fechas[0]
            imps = [ls.importe(x) for x in c if ls.importe(x) is not None and not ls.fecha(x)]
            q["importe_pagado"] = imps[-1] if imps else None
    return out


def _pagada_al(q: dict, f: date) -> bool:
    if q["pagada_el"]:
        return q["pagada_el"] <= f
    # Cancelada sin la marca "Pago" (débito u otra forma): se toma pagada a su 1° vencimiento.
    return "cancelad" in _norm(q["estado"]) and bool(q["vencimientos"]) and min(q["vencimientos"]) <= f


def calcular(datos: dict, f: date) -> dict:
    """Deuda a la fecha f por los planes de pago.
    Las obligaciones originales del plan bajan por las cuotas pagadas; ARCA no siempre lo muestra en
    "Total Pagos Imputados" (en planes caducos suele quedar en 0 aunque se pagaron cuotas). Por eso:
      - plan consolidado hasta f: saldo a f = consolidado - capital de las cuotas pagadas hasta f
        (= capital de las cuotas no pagadas a f). Sirve igual para vigente, caduco o cancelado: una cuota pagada
        después de f no baja la deuda a f. El saldo se reparte entre las obligaciones del plan en proporción.
      - plan consolidado después de f: las obligaciones con vencimiento hasta f eran deuda a f, por su monto.
    """
    planes, oblig, cuotas = [], [], []
    for p in datos.get("planes") or []:
        d = (datos.get("detalle") or {}).get(p["numero"]) or {}
        cons = date.fromisoformat(p["presentacion"]) if p.get("presentacion") else None
        obs = _dicts(d.get("obligaciones") or {})
        fila = {"numero": p["numero"], "tipo": p.get("tipo"), "consolidacion": p.get("presentacion"),
                "situacion": p.get("situacion"), "cuotas": p.get("cuotas"), "consolidado": p.get("consolidado"),
                "capital_pagado_a_cierre": 0.0, "capital_a_cierre": 0.0, "interes_cuotas_pendientes": 0.0,
                "criterio": "", "nota": d.get("error", "")}
        if not cons:
            fila["criterio"] = "sin fecha de consolidación"
        elif cons > f:
            fila["criterio"] = "consolidado después del cierre: obligaciones vencidas hasta el cierre, por su monto"
            for o in obs:
                vto = ls.fecha(_g(o, "Fecha Vto"))
                monto = ls.importe(_g(o, "Monto Obligación")) or 0.0
                if vto and vto <= f:
                    oblig.append({"plan": p["numero"], "impuesto": _g(o, "Imp"), "concepto": _g(o, "Cpto"),
                                  "subconcepto": _g(o, "Subcpto"), "periodo": "/".join(x for x in (_g(o, "Mes"), _g(o, "Año")) if x),
                                  "vencimiento": vto.isoformat(), "monto": monto,
                                  "pagos_hoy": ls.importe(_g(o, "Total Pagos")) or 0.0, "saldo": monto})
                    fila["capital_a_cierre"] += monto
        else:
            qs = leer_cuotas(d.get("pagos") or {})
            if not qs and d.get("cronograma"):                   # sin pantalla de pagos: cronograma sin pagos
                qs = {c["cuota"]: {"cuota": c["cuota"], "capital": c["capital"] or 0.0, "interes": c["int_financiero"] or 0.0,
                                   "estado": "", "vencimientos": [x for x in (c["venc_1"], c["venc_2"]) if x],
                                   "pagada_el": None, "importe_pagado": None} for c in ls.leer_plan_de_pago(d["cronograma"])}
            base = p.get("consolidado") or sum(q["capital"] for q in qs.values())
            pagado = sum(q["capital"] for q in qs.values() if _pagada_al(q, f))
            for q in qs.values():
                if not _pagada_al(q, f):
                    cuotas.append({"plan": p["numero"], "cuota": q["cuota"],
                                   "vencimiento": min(q["vencimientos"]).isoformat() if q["vencimientos"] else "",
                                   "capital": q["capital"], "interes": q["interes"], "estado": q["estado"],
                                   "pagada_el": q["pagada_el"].isoformat() if q["pagada_el"] else ""})
                    fila["interes_cuotas_pendientes"] += q["interes"]
            fila["capital_pagado_a_cierre"] = pagado
            fila["capital_a_cierre"] = max(base - pagado, 0.0)
            fila["criterio"] = ("consolidado hasta el cierre: consolidado menos capital de cuotas pagadas hasta el cierre"
                                + (" (plan caduco: ARCA puede no mostrar los pagos imputados)" if "caduc" in _norm(p.get("situacion")) else ""))
            tot = sum(ls.importe(_g(o, "Monto Obligación")) or 0.0 for o in obs)
            for o in obs:
                monto = ls.importe(_g(o, "Monto Obligación")) or 0.0
                oblig.append({"plan": p["numero"], "impuesto": _g(o, "Imp"), "concepto": _g(o, "Cpto"),
                              "subconcepto": _g(o, "Subcpto"), "periodo": "/".join(x for x in (_g(o, "Mes"), _g(o, "Año")) if x),
                              "vencimiento": (ls.fecha(_g(o, "Fecha Vto")) or "") and ls.fecha(_g(o, "Fecha Vto")).isoformat(),
                              "monto": monto, "pagos_hoy": ls.importe(_g(o, "Total Pagos")) or 0.0,
                              "saldo": round(fila["capital_a_cierre"] * monto / tot, 2) if tot else 0.0})
        for k in ("capital_pagado_a_cierre", "capital_a_cierre", "interes_cuotas_pendientes"):
            fila[k] = round(fila[k], 2)
        planes.append(fila)
    return {"cierre": f.isoformat(), "planes": planes, "obligaciones": oblig, "cuotas": cuotas,
            "total_planes": round(sum(p["capital_a_cierre"] for p in planes), 2)}


def excel(cuit: str, r: dict, destino: str, leido: str = "") -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    neg, cab = Font(bold=True), PatternFill("solid", fgColor="1F4E78")

    def hoja(ws, cols, filas, anchos):
        ws.append(cols)
        for c in ws[ws.max_row]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = cab
        for f in filas:
            ws.append(f)
        for i, w in enumerate(anchos, 1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = w
        ws.freeze_panes = "A2"

    ws = wb.active
    ws.title = "Resumen"
    for k, v in (("CUIT", cuit), ("Deuda fiscal al", r["cierre"]), ("Planes leídos de Mis Facilidades el", leido),
                 ("Planes de pago: capital adeudado al cierre", r["total_planes"]),
                 ("Cuentas Tributarias y F.931 (estado de deuda)", "pendiente: falta relevar la pantalla con Gabriel")):
        ws.append([k, v])
    ws["B4"].number_format = "#,##0.00"
    ws["A4"].font = ws["B4"].font = neg
    ws.column_dimensions["A"].width = 48
    ws.column_dimensions["B"].width = 52
    hoja(wb.create_sheet("Planes"), ["Plan", "Tipo", "Consolidación", "Situación hoy", "Cuotas", "Consolidado",
                                     "Capital pagado hasta el cierre", "Capital adeudado al cierre", "Interés de cuotas pendientes", "Criterio", "Nota"],
         [[p["numero"], p["tipo"], p["consolidacion"], p["situacion"], p["cuotas"], p["consolidado"],
           p["capital_pagado_a_cierre"], p["capital_a_cierre"], p["interes_cuotas_pendientes"], p["criterio"], p["nota"]]
          for p in r["planes"]],
         (11, 30, 13, 16, 8, 15, 18, 18, 18, 70, 30))
    hoja(wb.create_sheet("Obligaciones al cierre"),
         ["Plan", "Impuesto", "Concepto", "Subconcepto", "Período", "Vencimiento", "Monto obligación",
          "Pagos imputados (ARCA hoy)", "Saldo al cierre"],
         [[o["plan"], o["impuesto"], o["concepto"], o["subconcepto"], o["periodo"], o["vencimiento"], o["monto"],
           o["pagos_hoy"], o["saldo"]] for o in r["obligaciones"]], (11, 32, 20, 20, 10, 12, 16, 18, 16))
    hoja(wb.create_sheet("Cuotas pendientes al cierre"),
         ["Plan", "Cuota", "Vencimiento", "Capital", "Interés financiero", "Estado hoy", "Pagada el"],
         [[c["plan"], c["cuota"], c["vencimiento"], c["capital"], c["interes"], c["estado"], c["pagada_el"]]
          for c in r["cuotas"]], (11, 7, 12, 15, 16, 18, 12))
    for w in wb.worksheets[1:]:
        for row in w.iter_rows(min_row=2):
            for c in row:
                if isinstance(c.value, float):
                    c.number_format = "#,##0.00"
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    wb.save(destino)
    return destino


def generar(cuit: str, hoy: date | None = None, fechas: list[date] | None = None) -> list[str]:
    """Excel de deuda al cierre para las últimas fechas de cierre (o las pedidas). Devuelve las fechas hechas."""
    r = sorted(glob.glob(os.path.join(DATOS, cuit, "planes_todos", "*.json")))
    if not r:
        return []
    with open(r[-1], encoding="utf-8") as fh:
        datos = json.load(fh)
    hechas = []
    for f in fechas or cierres(cuit, hoy):
        res = calcular(datos, f)
        excel(cuit, res, os.path.join(DATOS, cuit, "biblioteca", "_conciliaciones", "deuda_cierre", f"{f.isoformat()}.xlsx"),
              datos.get("fecha", ""))
        hechas.append(f.strftime("%d/%m/%Y"))
    return hechas
