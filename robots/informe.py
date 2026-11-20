"""Informe de situación fiscal CONSOLIDADO por contribuyente y sus relacionados.

Toma lo último que bajaron los robots de cada CUIT del grupo (no entra a ARCA):
  situacion/<fecha>/resultado.json   Cuentas Tributarias + Mis Facilidades
  <AAAA-MM>/resultado.json           Mis Comprobantes (último período bajado)
  dfe/<fecha>/resultado.json         Domicilio Fiscal Electrónico (cuando exista)

Grupos: un cliente + sus relacionados con "Consolidar en informes" = S (hoja Relacionados de la
planilla). Si A se relaciona con B y B con C, los tres forman un solo grupo.

Uso (en la máquina robots):
  python3 -m robots.informe --cuit 20331162788      el grupo de ese CUIT
  python3 -m robots.informe --todos                 un informe por grupo
Salida: /var/lib/robots/informes/<fecha>/
  relacion_dc_<CUIT>.xlsx, situacion_fiscal_<CUIT>.xlsx   (cada CUIT, formato de los ejemplos)
  conciliacion_compras_<CUIT>.xlsx                         (responsables inscriptos con Libro IVA bajado)
  consolidado_<CUIT>_<nombre>.xlsx                         (solo si el grupo tiene más de un CUIT)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from contextlib import closing
from datetime import date

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
INFORMES = os.environ.get("ROBOTS_INFORMES", "/var/lib/robots/informes")
PRIORIDAD = {"ALTA": 0, "Media": 1, "Baja": 2}


# ---------------------------------------------------------------- datos
def _ultimo(patron: str) -> str | None:
    rutas = sorted(glob.glob(patron))
    return rutas[-1] if rutas else None


def _leer(ruta: str | None) -> dict | None:
    if not ruta:
        return None
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def datos_cuit(cuit: str) -> dict:
    base = os.path.join(DATOS, cuit)
    sit = _leer(_ultimo(os.path.join(base, "situacion", "*", "resultado.json")))
    mc_ruta = _ultimo(os.path.join(base, "[0-9][0-9][0-9][0-9]-[0-9][0-9]", "resultado.json"))
    dfe = _leer(_ultimo(os.path.join(base, "dfe", "*", "resultado.json")))
    dfe_arba = _leer(_ultimo(os.path.join(base, "arba_dfe", "[0-9]*", "resultado.json")))
    cm = _leer(_ultimo(os.path.join(base, "sifere_deuda", "*.json")))
    return {"cuit": cuit, "situacion": sit, "mc": _leer(mc_ruta), "dfe": dfe, "dfe_arba": dfe_arba, "cm_deuda": cm}


def grupos(cuits_clientes: list[str], relaciones: list[tuple[str, str]]) -> list[list[str]]:
    """Componentes conexas: cada grupo ordenado, primero el CUIT con más vínculos (el 'titular')."""
    vecinos: dict[str, set[str]] = {c: set() for c in cuits_clientes}
    for a, b in relaciones:
        vecinos.setdefault(a, set()).add(b)
        vecinos.setdefault(b, set()).add(a)
    vistos, out = set(), []
    for c in sorted(vecinos):
        if c in vistos:
            continue
        pila, comp = [c], []
        while pila:
            x = pila.pop()
            if x in vistos:
                continue
            vistos.add(x)
            comp.append(x)
            pila.extend(vecinos[x] - vistos)
        comp.sort(key=lambda x: (-len(vecinos[x]), x[:2] not in ("20", "23", "24", "27"), x))
        out.append(comp)
    return out


def grupos_desde_almacen() -> list[list[str]]:
    from . import almacen_claves as alm
    with closing(alm.conectar()) as con:
        clientes = [r[0] for r in con.execute("SELECT cuit FROM clientes")]
        rel = [(a, b) for a, b in con.execute("SELECT cuit, cuit_relacionado FROM relacionados WHERE consolidar='S'")]
    return grupos(clientes, rel)


def nombre(cuit: str, d: dict) -> str:
    try:
        from . import almacen_claves as alm
        n = alm.razon_social(cuit)
        if n:
            return n
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------- armado de filas
def _f(v):
    """Fecha ISO -> date (para que Excel la muestre como fecha)."""
    if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return date.fromisoformat(v)
    return v


def filas_resumen(cuit: str, nom: str, d: dict) -> dict:
    s = (d.get("situacion") or {})
    sct, mf = s.get("sct"), s.get("mis_facilidades")
    fila = {"CUIT": cuit, "Contribuyente": nom, "Datos al": _f(s.get("fecha")) if s else "SIN DATOS"}
    if sct:
        t = sct["totales_leidos"]
        fila.update({"Deuda vencida": t["vencido"], "Deuda total": t["total"],
                     "DDJJ pendientes": len(sct["ddjj_pendientes"])})
    if mf:
        v = mf["vigentes"]
        fila.update({
            "Planes vigentes": len(v),
            "Cuotas vencidas impagas": sum(p["vencidas_impagas"] for p in v),
            "Importe vencido impago": sum(p["importe_vencido_impago"] for p in v),
            "Cuotas a vencer 15 días": sum(p["a_vencer_15_dias"] for p in v),
            "Importe a vencer 15 días": sum(p["importe_a_vencer_15_dias"] for p in v),
            "Saldo capital en planes": sum(p["saldo_capital_pendiente"] for p in v),
        })
    dfe = d.get("dfe")
    if dfe:
        fila["Comunicaciones DFE sin leer"] = sum(1 for c in dfe.get("comunicaciones", []) if not c.get("leida"))
    cm = d.get("cm_deuda")
    if cm:
        fila["Deuda IIBB Convenio (SIFERE)"] = cm.get("deuda_total", 0.0)
    arba = d.get("dfe_arba")
    if arba:
        fila["ARBA DFE: ALTA leídas hoy / sin notificar"] = len(arba.get("alertas") or [])
    fila["Alertas ALTA"] = sum(1 for a in (s.get("alertas") or []) + ((dfe or {}).get("alertas") or [])
                              + ((arba or {}).get("alertas") or []) + ((cm or {}).get("alertas") or [])
                              if a.get("prioridad") == "ALTA")
    return fila


COLUMNAS_RESUMEN = ["CUIT", "Contribuyente", "Datos al", "Deuda vencida", "Deuda total", "DDJJ pendientes",
                    "Planes vigentes", "Cuotas vencidas impagas", "Importe vencido impago",
                    "Cuotas a vencer 15 días", "Importe a vencer 15 días", "Saldo capital en planes",
                    "Deuda IIBB Convenio (SIFERE)", "Comunicaciones DFE sin leer",
                    "ARBA DFE: ALTA leídas hoy / sin notificar", "Alertas ALTA"]
SUMAR = {"Deuda vencida", "Deuda total", "DDJJ pendientes", "Planes vigentes", "Cuotas vencidas impagas",
         "Importe vencido impago", "Cuotas a vencer 15 días", "Importe a vencer 15 días",
         "Saldo capital en planes", "Comunicaciones DFE sin leer", "Alertas ALTA", "Deuda IIBB Convenio (SIFERE)",
         "ARBA DFE: ALTA leídas hoy / sin notificar"}


def armar(grupo: list[str]) -> dict:
    hojas = {k: [] for k in ("resumen", "alertas", "deudas", "ddjj", "vencimientos", "planes", "cuotas",
                             "comprobantes", "dfe")}
    hoy = date.today()
    for cuit in grupo:
        d = datos_cuit(cuit)
        nom = nombre(cuit, d)
        hojas["resumen"].append(filas_resumen(cuit, nom, d))
        s = d.get("situacion") or {}
        for a in (s.get("alertas") or []) + ((d.get("dfe") or {}).get("alertas") or []) + ((d.get("dfe_arba") or {}).get("alertas") or []) + ((d.get("cm_deuda") or {}).get("alertas") or []):
            hojas["alertas"].append({"Prioridad": a.get("prioridad"), "CUIT": cuit, "Contribuyente": nom,
                                     "Tipo": a.get("tipo"), "Detalle": a.get("texto")})
        sct = s.get("sct")
        if sct:
            for x in sct["deudas"]:
                hojas["deudas"].append({"CUIT": cuit, "Contribuyente": nom, "Impuesto": x["impuesto"],
                                        "Concepto": x["concepto"], "Período": x["periodo_txt"],
                                        "Cuota": x["cuota"], "Vencimiento": _f(x["vencimiento"]),
                                        "Capital": x["capital"], "Int. resarcitorio": x["int_resarcitorio"],
                                        "Int. punitorio": x["int_punitorio"], "Total": x["total"],
                                        "Vencida": "Sí" if x["vencida"] else "No"})
            for x in sct["ddjj_pendientes"]:
                hojas["ddjj"].append({"CUIT": cuit, "Contribuyente": nom, "Impuesto": x["impuesto"],
                                      "Período": x["periodo_txt"], "Vencimiento": _f(x["vencimiento"])})
            for x in sct["vencimientos"]:
                hojas["vencimientos"].append({"CUIT": cuit, "Contribuyente": nom, "Impuesto": x["impuesto"],
                                              "Concepto": x["concepto"], "Período": x["periodo_txt"],
                                              "Vencimiento": _f(x["vencimiento"]), "Detalle": x["detalle"]})
        mf = s.get("mis_facilidades")
        if mf:
            for p in mf["vigentes"]:
                hojas["planes"].append({
                    "CUIT": cuit, "Contribuyente": nom, "Plan": p["numero"], "Tipo": p["tipo"],
                    "Presentación": _f(p["presentacion"]), "Cuotas": p["cuotas_total"],
                    "Con anticipo": "Sí" if p.get("con_anticipo") else "",
                    "Valor de cuota": p["valor_cuota"], "Pagadas": p["cuotas_pagadas"],
                    "Pendientes": p["cuotas_pendientes"], "Vencidas impagas": p["vencidas_impagas"],
                    "Importe vencido impago": p["importe_vencido_impago"],
                    "Próximo vencimiento": _f(p["proximo_vencimiento"]),
                    "Saldo capital": p["saldo_capital_pendiente"]})
                for c in p["detalle_cuotas"]:
                    if c["situacion"] == "Vencida impaga" or (
                            c["situacion"] == "A vencer" and c["venc_1"]
                            and (date.fromisoformat(str(c["venc_1"])) - hoy).days <= 15):
                        hojas["cuotas"].append({
                            "CUIT": cuit, "Contribuyente": nom, "Plan": p["numero"], "Cuota": c["cuota"],
                            "Situación": c["situacion"], "1° venc.": _f(c["venc_1"]), "Importe 1° venc.": c["total_1"],
                            "2° venc.": _f(c["venc_2"]), "Importe 2° venc.": c["total_2"]})
        mc = d.get("mc")
        if mc:
            for tipo, info in (mc.get("archivos") or {}).items():
                for concepto, valor in (info.get("resumen") or {}).items():
                    hojas["comprobantes"].append({"CUIT": cuit, "Contribuyente": nom, "Período": mc.get("periodo"),
                                                  "Tipo": "Ventas (emitidos)" if tipo == "emitidos" else "Compras (recibidos)",
                                                  "Concepto": concepto.strip(), "Importe": valor})
        for clave in ("dfe", "dfe_arba"):
            dfe = d.get(clave)
            if not dfe:
                continue
            for c in dfe.get("comunicaciones", []):
                hojas["dfe"].append({"CUIT": cuit, "Contribuyente": nom, "Fecha": _f(c.get("fecha")),
                                     "Organismo": c.get("organismo"), "Asunto": c.get("asunto"),
                                     "Importancia": c.get("importancia"), "Leída": "Sí" if c.get("leida") else "NO",
                                     "Motivo": c.get("motivo") or "", "Para": c.get("para") or "",
                                     "Responsable": c.get("responsable") or "",
                                     "Plazo": c.get("plazo") or "", "Resumen": c.get("resumen") or "",
                                     "Observación": c.get("estado_robot") or ""})
    hojas["alertas"].sort(key=lambda a: (PRIORIDAD.get(a["Prioridad"], 9), a["CUIT"]))
    hojas["cuotas"].sort(key=lambda c: (c["Situación"] == "A vencer", str(c["1° venc."])))
    return hojas


# ---------------------------------------------------------------- Excel con formato
def escribir_excel(hojas: dict, grupo: list[str], ruta: str) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    AZUL, GRIS = "1F3864", "F2F2F2"
    ROJO, AMARILLO = "F8CBAD", "FFF2CC"
    fino = Side(style="thin", color="BFBFBF")
    wb = Workbook()
    wb.remove(wb.active)
    titulo_grupo = " / ".join(f"{(r['Contribuyente'] or r['CUIT'])}" for r in hojas["resumen"])

    def hoja(nombre_hoja, filas, columnas=None, titulo=None, totales=None, colorear=None):
        ws = wb.create_sheet(nombre_hoja)
        columnas = columnas or (list(filas[0].keys()) if filas else ["Sin datos"])
        ws["A1"] = titulo or nombre_hoja
        ws["A1"].font = Font(bold=True, size=13, color=AZUL)
        ws["A2"] = f"{titulo_grupo} — generado {date.today():%d/%m/%Y}"
        ws["A2"].font = Font(italic=True, size=9, color="595959")
        fila0 = 4
        for j, c in enumerate(columnas, 1):
            cel = ws.cell(fila0, j, c)
            cel.font = Font(bold=True, color="FFFFFF")
            cel.fill = PatternFill("solid", fgColor=AZUL)
            cel.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        for i, f in enumerate(filas, fila0 + 1):
            color = colorear(f) if colorear else None
            for j, c in enumerate(columnas, 1):
                v = f.get(c, "")
                cel = ws.cell(i, j, v)
                cel.border = Border(bottom=fino)
                if isinstance(v, float):
                    cel.number_format = "#,##0.00"
                elif isinstance(v, date):
                    cel.number_format = "DD/MM/YYYY"
                if color:
                    cel.fill = PatternFill("solid", fgColor=color)
        if totales and filas:
            i = fila0 + len(filas) + 1
            ws.cell(i, 1, "TOTAL GRUPO").font = Font(bold=True)
            for j, c in enumerate(columnas, 1):
                if c in totales:
                    v = sum((f.get(c) or 0) for f in filas if isinstance(f.get(c), (int, float)))
                    cel = ws.cell(i, j, v)
                    cel.font = Font(bold=True)
                    cel.fill = PatternFill("solid", fgColor=GRIS)
                    if isinstance(v, float):
                        cel.number_format = "#,##0.00"
        for j, c in enumerate(columnas, 1):
            largo = max([len(str(c))] + [len(f"{f.get(c, ''):,.2f}" if isinstance(f.get(c), float) else str(f.get(c, "")))
                                          for f in filas[:300]])
            ws.column_dimensions[get_column_letter(j)].width = min(55, max(10, largo + 2))
        ws.row_dimensions[fila0].height = 32
        ws.freeze_panes = ws.cell(fila0 + 1, 3 if "Contribuyente" in columnas else 1)
        if filas:
            ws.auto_filter.ref = f"A{fila0}:{get_column_letter(len(columnas))}{fila0 + len(filas)}"
        ws.sheet_view.showGridLines = False
        return ws

    cols = [c for c in COLUMNAS_RESUMEN if any(c in r for r in hojas["resumen"])]
    hoja("Resumen", hojas["resumen"], cols, "Situación fiscal consolidada", SUMAR,
         lambda f: ROJO if (f.get("Cuotas vencidas impagas") or f.get("DDJJ pendientes")) else None)
    hoja("Alertas", hojas["alertas"], ["Prioridad", "CUIT", "Contribuyente", "Tipo", "Detalle"], "Alertas",
         colorear=lambda f: ROJO if f["Prioridad"] == "ALTA" else AMARILLO if f["Prioridad"] == "Media" else None)
    hoja("Planes de pago", hojas["planes"], titulo="Planes de facilidades vigentes",
         totales={"Valor de cuota", "Pendientes", "Vencidas impagas", "Importe vencido impago", "Saldo capital"},
         colorear=lambda f: ROJO if f.get("Vencidas impagas") else None)
    hoja("Cuotas a controlar", hojas["cuotas"], titulo="Cuotas vencidas impagas y a vencer en 15 días",
         colorear=lambda f: ROJO if f["Situación"] != "A vencer" else AMARILLO)
    hoja("Deudas", hojas["deudas"], titulo="Deudas (Sistema de Cuentas Tributarias)",
         totales={"Capital", "Int. resarcitorio", "Int. punitorio", "Total"})
    hoja("DDJJ pendientes", hojas["ddjj"], titulo="Declaraciones juradas pendientes de presentación")
    hoja("Vencimientos", hojas["vencimientos"], titulo="Próximos vencimientos")
    if hojas["comprobantes"]:
        hoja("Compras y ventas", hojas["comprobantes"], titulo="Mis Comprobantes – último período bajado")
    if hojas["dfe"]:
        hoja("Domicilio Fiscal Electr.", hojas["dfe"], titulo="Comunicaciones del Domicilio Fiscal Electrónico",
             colorear=lambda f: ROJO if f["Leída"] == "NO" and f.get("Importancia") == "ALTA" else None)
    for ws in wb.worksheets:
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToHeight = 0
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    wb.save(ruta)


def dejar_solo_el_ultimo(raiz: str | None = None) -> int:
    """Pedido del 20/11/2026: de cada informe Excel se guarda solo el último. Borra las copias de fechas anteriores
    (informes/<AAAA-MM-DD>/<mismo nombre>.xlsx) y las carpetas de fecha que quedan vacías. Devuelve cuántos borró."""
    import glob
    raiz = raiz or INFORMES
    ultimo: dict[str, str] = {}
    borrados = 0
    for r in sorted(glob.glob(os.path.join(raiz, "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]", "*.xlsx")), reverse=True):
        n = os.path.basename(r)
        if n in ultimo:
            try:
                os.remove(r)
                borrados += 1
            except OSError:
                pass
        else:
            ultimo[n] = r
    for d in glob.glob(os.path.join(raiz, "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]")):
        try:
            os.rmdir(d)                                        # solo si quedó vacía
        except OSError:
            pass
    return borrados


def generar(grupo: list[str], carpeta: str | None = None) -> str:
    hojas = armar(grupo)
    principal = hojas["resumen"][0]
    nom = re.sub(r"[^\w]+", "_", principal["Contribuyente"] or "")[:40].strip("_")
    carpeta = carpeta or os.path.join(INFORMES, date.today().isoformat())
    ruta = os.path.join(carpeta, f"consolidado_{principal['CUIT']}{'_' + nom if nom else ''}.xlsx")
    escribir_excel(hojas, grupo, ruta)
    if carpeta.startswith(INFORMES):
        dejar_solo_el_ultimo()
    return ruta


def generar_cliente(cuit: str, periodos: list[str] | None = None, carpeta: str | None = None) -> list[str]:
    """Relación débito/crédito (12 meses) + situación fiscal de UN cliente, con el formato de los ejemplos."""
    from . import arca, informe_cliente as ic
    periodos = periodos or arca.periodos_ultimos(12)
    nom = nombre(cuit, {}) or cuit
    carpeta = carpeta or os.path.join(INFORMES, date.today().isoformat())
    r1 = os.path.join(carpeta, f"relacion_dc_{cuit}.xlsx")
    r2 = os.path.join(carpeta, f"situacion_fiscal_{cuit}.xlsx")
    # Primero la conciliación: deja las facturas B/C fuera del Libro IVA que suma la relación débito/crédito
    from . import conciliacion
    r3 = os.path.join(carpeta, f"conciliacion_compras_{cuit}.xlsx")
    hay_conc = conciliacion.generar(cuit, nom, r3) is not None
    ic.relacion_dc(cuit, nom, periodos, r1)
    ic.situacion_fiscal(cuit, nom, r2)
    salida = [r1, r2] + ([r3] if hay_conc else [])
    if carpeta.startswith(INFORMES):
        dejar_solo_el_ultimo()
    return salida


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--cuit", help="informes de este CUIT y de su grupo de relacionados")
    g.add_argument("--todos", action="store_true")
    ap.add_argument("--hasta", help="último mes de la relación débito/crédito (AAAA-MM); por defecto el mes anterior")
    ap.add_argument("--meses", type=int, default=12)
    a = ap.parse_args(argv)
    from . import arca
    periodos = arca.periodos_ultimos(a.meses, a.hasta)
    todos = grupos_desde_almacen()
    elegidos = todos if a.todos else [next((gr for gr in todos if a.cuit in gr), [a.cuit])]
    for gr in elegidos:
        for cuit in gr:
            for ruta in generar_cliente(cuit, periodos):
                print(f"{cuit} -> {ruta}")
        if len(gr) > 1:
            print(f"GRUPO {' + '.join(gr)} -> {generar(gr)}")


if __name__ == "__main__":
    sys.exit(main())
