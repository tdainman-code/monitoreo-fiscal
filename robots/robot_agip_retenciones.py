"""AGIP (CABA): retenciones, percepciones y retenciones bancarias sufridas — Gestión-AR.

Recorrido mostrado por Gabriel el 25/11/2026 con NABAJUMA SA (30-71222757-1), agosto 2026:
  Clave Ciudad (CUIT del administrador de relaciones) -> "Seleccione Representado" (NOMBRE [cuit]) -> Ingresar
  -> Gestión-AR / Agentes de Recaudación (lb.agip.gob.ar/gestionArciba/?url=cc)
     "Consulta de Retenciones / Percepciones": CUIT | Mes/Año desde | Mes/Año hasta | Régimen (Todas) | Buscar
     Los Mes/Año NO dejan escribir: calendario de meses (robot_agip.elegir_mes).
  -> resultado con solapas arriba: Retenciones | Percepciones | Retenciones Bancarias (y las que haya)
     botones: Buscar Registros | Descargar Excel | Descargar Txt | Descargar Txt SIFERE
  Archivos (los de Gabriel, guardados tal cual):
     "Excel" = CSV con 'sep=,'  (RentasCiudad_N.xls)
        Retenciones: CUIT,N° Ader,Razon Social,N° Certificado,Norma,Fecha Retencion,Tipo Comprobante,N° Comprobante,
                     Fecha Comprobante,Monto Retenido,Base Calculo
        Percepciones: ...,Fecha Percepcion,...,Monto Percibido,Base Calculo
        Bancarias: cuit,razonSocial,fechaPresentacion,importeCR,importeRecaudado,coeficienteJurisdiccion,
                   importeRecaudadoPorJuris,tipoCuenta,CBU
     Txt SIFERE (RentasCiudadEsicol<Regimen>-MM-AAAASifere.txt): 901 + CUIT agente con guiones + ... (para importar)
     Txt (…-Completo.txt): ancho fijo propio de AGIP
Solo consulta y descarga. Siempre los 2 últimos meses cerrados, mes por mes.
"""
from __future__ import annotations

import csv
import io
import os
import re
from datetime import date

from . import arca, biblioteca_archivos as bib

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
FUENTE = "agip"
SOLAPAS = ["Retenciones", "Percepciones", "Retenciones Bancarias", "Retenciones SIRTAC", "Percepciones Aduaneras"]
BOTONES = {"excel": r"Descargar\s+Excel", "txt_sifere": r"Descargar\s+Txt\s+SIFERE", "txt": r"Descargar\s+Txt\s*$"}


def _n(t: str) -> float:
    t = (t or "").strip()
    if "," in t and "." in t and t.rfind(",") > t.rfind("."):
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", "")
    try:
        return float(t or 0)
    except ValueError:
        return 0.0


def leer_csv(solapa: str, texto: str) -> list[dict]:
    """CSV de 'Descargar Excel' de cualquier solapa -> filas normalizadas."""
    lineas = [l for l in texto.splitlines() if l.strip() and not l.lower().startswith("sep=")]
    out = []
    for f in csv.DictReader(io.StringIO("\n".join(lineas))):
        f = {re.sub(r"[^a-z]", "", k.lower()): (v or "").strip() for k, v in f.items() if k and isinstance(v, str)}
        ag = re.sub(r"\D", "", f.get("cuit", ""))
        if len(ag) != 11:
            continue
        base = {"agente": ag, "nombre": f.get("razonsocial", ""), "regimen": solapa.upper(), "jurisdiccion": "901"}
        if "cbu" in f or "importerecaudadoporjuris" in f:                    # retenciones bancarias (SIRCREB CABA)
            out.append({**base, "fecha": f.get("fechapresentacion", ""), "cbu": f.get("cbu", ""),
                        "comprobante": f.get("cbu", ""), "desc_comprobante": "Retención bancaria",
                        "acreditado": _n(f.get("importecr")), "base": _n(f.get("importerecaudado")),
                        "coeficiente": f.get("coeficientejurisdiccion", ""),
                        "importe": _n(f.get("importerecaudadoporjuris") or f.get("importerecaudado")),
                        "operacion": "RETENCION"})
            continue
        es_perc = "montopercibido" in f or "fechapercepcion" in f
        out.append({**base, "fecha": f.get("fechapercepcion") or f.get("fecharetencion") or "",
                    "certificado": f.get("ncertificado", "").lstrip("0"), "norma": f.get("norma", ""),
                    "tipo": f.get("tipocomprobante", ""), "comprobante": re.sub(r"\s+", "", f.get("ncomprobante", "")),
                    "desc_comprobante": {"F": "FACTURA", "R": "RECIBO", "O": "OTRO", "X": "OTRO", "C": "NOTA DE CREDITO",
                                         "D": "NOTA DE DEBITO"}.get(f.get("tipocomprobante", ""), f.get("tipocomprobante", "")),
                    "fecha_comprobante": f.get("fechacomprobante", ""),
                    "base": _n(f.get("basecalculo")),
                    "importe": _n(f.get("montopercibido") or f.get("montoretenido") or f.get("importepercibido")),
                    "operacion": "PERCEPCION" if es_perc else "RETENCION"})
    return out


# ------------------------------------------------------------------ navegación
def _boton(pag, patron: str):
    return pag.locator("a, button, input[type=button], input[type=submit]").filter(
        has_text=re.compile(patron, re.I)).filter(visible=True)


def _descargar(pag, patron: str):
    """(nombre, bytes) o None si el botón no está o está deshabilitado."""
    b = _boton(pag, patron)
    if not b.count():
        return None
    el = b.first
    if el.get_attribute("disabled") is not None or "disabled" in (el.get_attribute("class") or ""):
        return None
    try:
        with pag.expect_download(timeout=45_000) as dl:
            el.click()
        with open(dl.value.path(), "rb") as fh:
            return dl.value.suggested_filename or "archivo", fh.read()
    except Exception:
        return None


def consultar_mes(pag, url_form: str, cuit: str, anio: int, mes: int) -> None:
    from .robot_agip import elegir_mes
    pag.goto(url_form, wait_until="domcontentloaded")
    pag.wait_for_timeout(2500)
    if arca.cuit_fmt(cuit) not in pag.inner_text("body") and cuit not in pag.inner_text("body"):
        raise arca.CuitEquivocado(f"AGIP Gestión-AR: no muestra el CUIT {arca.cuit_fmt(cuit)}")
    campos = pag.locator("input[type=text], input:not([type])").filter(visible=True)
    vals = {}
    for i in range(campos.count()):
        c = campos.nth(i)
        et = c.evaluate("e => { const l = e.closest('div, td'); return l ? l.innerText : ''; }") or ""
        if re.search(r"desde", et, re.I):
            vals["desde"] = c
        elif re.search(r"hasta", et, re.I):
            vals["hasta"] = c
    if "desde" not in vals or "hasta" not in vals:
        raise arca.ErrorRobot("AGIP Gestión-AR: no se encontraron los campos Mes/Año desde/hasta")
    elegir_mes(pag, vals["desde"], anio, mes)
    elegir_mes(pag, vals["hasta"], anio, mes)
    sel = pag.locator("select").filter(has=pag.locator("option", has_text=re.compile(r"^\s*Todas\s*$", re.I)))
    if sel.count():
        sel.first.select_option(label=next(o for o in sel.first.locator("option").all_inner_texts()
                                           if re.fullmatch(r"\s*Todas\s*", o, re.I)).strip())
    _boton(pag, r"^\s*Buscar\s*$").first.click()
    pag.wait_for_load_state("domcontentloaded")
    pag.wait_for_timeout(3500)


def bajar(ctx, pag, cuit: str, hoy: date | None = None, meses: int | None = None) -> dict:
    """pag = Gestión-AR abierto. Los 2 últimos meses, todas las solapas: archivos, versiones y diagnóstico.
    Devuelve {"meses", "filas", "percepciones"} (percepciones para el cruce con el Libro IVA)."""
    from . import percepciones_hist as hist
    hoy = hoy or date.today()
    url_form = pag.url
    ultimos = bib.periodos(hoy)
    pasos = [{"paso": "Clave Ciudad -> representado -> Gestión-AR", "ok": True}]
    res = {"meses": {}, "filas": 0, "percepciones": []}
    try:
        for anio, mes in (hist.meses_atras(hoy, meses) if meses and meses > 2 else ultimos):
            per = f"{anio}-{mes:02d}"
            if (anio, mes) not in ultimos:               # histórico inicial: solo el Excel de cada solapa, al histórico
                try:
                    consultar_mes(pag, url_form, cuit, anio, mes)
                    fs = []
                    for solapa in SOLAPAS:
                        tab = pag.locator("a, li, button").filter(has_text=re.compile(rf"^\s*{solapa}\s*$", re.I)).filter(visible=True)
                        if not tab.count():
                            continue
                        tab.first.click()
                        pag.wait_for_timeout(2000)
                        d = _descargar(pag, BOTONES["excel"])
                        if d:
                            fs += leer_csv(solapa, d[1].decode("latin-1"))
                    hist.guardar(cuit, "agip", fs, [per], hoy)
                except Exception as e:
                    pasos.append({"paso": f"Histórico {per}", "ok": False, "detalle": str(e).splitlines()[0][:120] if str(e) else ""})
                continue
            consultar_mes(pag, url_form, cuit, anio, mes)
            filas, detalle = [], []
            for solapa in SOLAPAS:
                tab = pag.locator("a, li, button").filter(has_text=re.compile(rf"^\s*{solapa}\s*$", re.I)).filter(visible=True)
                if not tab.count():
                    continue
                tab.first.click()
                pag.wait_for_timeout(2500)
                bajados = {}
                for k, patron in BOTONES.items():
                    d = _descargar(pag, patron)
                    if d:
                        nombre = re.sub(r"[^\w.-]", "_", f"{solapa}_{k}_{d[0]}")
                        bib.guardar_archivo(cuit, per, FUENTE, nombre, d[1])
                        bajados[k] = d[1]
                nuevas = leer_csv(solapa, bajados["excel"].decode("latin-1")) if "excel" in bajados else []
                filas += nuevas
                detalle.append(f"{solapa}: {len(nuevas)}" + ("" if "excel" in bajados else " (sin Excel)")
                               + (" + TXT SIFERE" if "txt_sifere" in bajados else ""))
            bib.guardar_version(cuit, per, FUENTE, filas, hoy)
            hist.guardar(cuit, "agip", filas, [per], hoy)
            pasos.append({"paso": f"Consulta {per}", "ok": True, "detalle": " · ".join(detalle) or "sin solapas"})
            res["meses"][per] = {"filas": len(filas), "importe": round(sum(f["importe"] for f in filas), 2)}
            res["filas"] += len(filas)
            res["percepciones"] += [f for f in filas if f["operacion"] == "PERCEPCION"]
            arca.pausa(0.8, 1.6)
        bib.guardar_diagnostico(cuit, FUENTE, {"estado": "ok" if res["filas"] else "sin_movimientos", "pasos": pasos,
                                               "meses": res["meses"]})
        return res
    except Exception as e:
        caps = arca.capturar(ctx, os.path.join(DATOS, cuit, "capturas"), "agip_retenciones")
        bib.guardar_diagnostico(cuit, FUENTE, {"estado": "error", "pasos": pasos + [{"paso": "siguiente paso", "ok": False}],
                                               "error": f"{type(e).__name__}: {str(e).splitlines()[0][:300] if str(e) else ''}",
                                               "captura": os.path.basename(caps[-1]) if caps else ""})
        raise
