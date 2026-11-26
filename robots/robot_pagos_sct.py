"""Pagos de Cuentas Tributarias (relevado con Gaby el 26/11/2026, Nabajuma).

Para qué: la deuda fiscal al cierre de balance no es solo lo que se debe HOY. Lo que estaba impago al cierre y se pagó
después también era deuda a esa fecha ("no tomaste en cuenta los pagos posteriores"). Se buscan los pagos con fecha de
operación posterior al cierre e imputados a períodos hasta el cierre.

Recorrido: Sistema de Cuentas Tributarias -> menú CONSULTAS -> PAGOS ("Consultar Pagos": Impuesto, Formulario, Período
Fiscal Desde/Hasta AAAAMMDD, Fecha Operación Desde/Hasta dd/mm/aaaa) -> CONSULTAR -> "Resultados" (Fecha Operación |
Formulario | Versión | Impuesto | Período Fiscal | Importe | Observaciones; 10 por página) -> EXPORTAR -> CSV / XLS / PDF.
Export XLS de ejemplo: fila 1 "CUIT: 30-71222757-1 - Fecha de emisión: 26/11/2026", fila 2 encabezados, importes
"$ 1.866.268,45", período 20261000.
Solo consulta. Resultado: DATOS/<cuit>/pagos_sct/<fecha>.json.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
from datetime import date, datetime

from . import arca

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")


def _importe(t) -> float:
    s = re.sub(r"[^\d,.\-]", "", str(t or ""))
    if not s:
        return 0.0
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)


def leer_csv(texto: str) -> list[dict]:
    """CSV (o texto de la tabla) exportado de Consultar Pagos."""
    lineas = [l for l in texto.replace("﻿", "").splitlines() if l.strip()]
    i = next((n for n, l in enumerate(lineas) if re.search(r"Fecha\s*Operaci", l, re.I)), None)
    if i is None:
        return []
    sep = ";" if lineas[i].count(";") >= lineas[i].count(",") else ","
    filas = list(csv.reader(lineas[i:], delimiter=sep))
    cab = [c.strip().lower() for c in filas[0]]

    def col(pref):
        return next((k for k, c in enumerate(cab) if c.startswith(pref)), None)
    i_f, i_form, i_imp, i_per, i_m, i_obs = (col("fecha"), col("formulario"), col("impuesto"), col("per"),
                                             col("importe"), col("observ"))
    out = []
    for f in filas[1:]:
        if i_f is None or len(f) <= max(x for x in (i_f, i_imp, i_per, i_m) if x is not None):
            continue
        try:
            fecha = datetime.strptime(f[i_f].strip(), "%d/%m/%Y").date()
        except ValueError:
            continue
        out.append({"fecha": fecha.isoformat(), "formulario": f[i_form].strip() if i_form is not None else "",
                    "impuesto": f[i_imp].strip(), "periodo": re.sub(r"\D", "", f[i_per]),
                    "importe": _importe(f[i_m]), "observaciones": f[i_obs].strip() if i_obs is not None else ""})
    return out


def leer(ctx, portal, cuit: str, desde: date, hasta: date) -> list[dict]:
    from . import robot_situacion_fiscal as rsf
    from .robot_sct_historico import _clic_texto, _marco_con
    page = arca.abrir_servicio(ctx, portal, "cuentas_tributarias")
    try:
        page.wait_for_load_state("domcontentloaded")
        rsf._elegir_cuit_sct(page, cuit, None)
        fr = rsf._frame_sct(page)
        rsf._controlar_cuit(page.inner_text("body") + fr.locator("body").inner_text(), cuit, "Cuentas Tributarias")
        try:
            _clic_texto(page, r"^\s*PAGOS\s*$", espera_s=10)
        except arca.ErrorRobot:
            _clic_texto(page, r"^\s*CONSULTAS\s*$")
            _clic_texto(page, r"^\s*PAGOS\s*$")
        fr = _marco_con(page, r"Fecha Operaci[oó]n Desde", espera_s=60)
        for etiqueta, valor in (("Desde", desde), ("Hasta", hasta)):
            campo = fr.locator(f"input[placeholder='{etiqueta}']")
            if not campo.count():
                raise arca.ErrorRobot(f"Consultar Pagos: no aparece el campo 'Fecha Operación {etiqueta}'")
            campo.first.fill(valor.strftime("%d/%m/%Y"))
            campo.first.press("Escape")
        fr.get_by_text(re.compile(r"^\s*CONSULTAR\s*$", re.I)).locator("visible=true").first.click()
        fr = _marco_con(page, r"Resultados|No se encontraron|no hay", espera_s=90)
        texto = fr.locator("body").inner_text()
        if arca.cuit_fmt(cuit) not in texto and cuit not in re.sub(r"\D", "", texto[:3000]):
            raise arca.CuitEquivocado(f"Consultar Pagos: no muestra el CUIT {arca.cuit_fmt(cuit)}")
        if not re.search(r"Resultados", texto, re.I):
            return []
        fr.get_by_text(re.compile(r"^\s*EXPORTAR", re.I)).locator("visible=true").first.click()
        page.wait_for_timeout(800)
        with page.expect_download(timeout=90_000) as dl:
            fr.get_by_text(re.compile(r"^\s*CSV\s*$", re.I)).locator("visible=true").first.click()
        ruta = dl.value.path()
        with open(ruta, "rb") as f:
            crudo = f.read()
        try:
            txt = crudo.decode("utf-8")
        except UnicodeDecodeError:
            txt = crudo.decode("latin-1")
        return leer_csv(txt)
    finally:
        page.close()


def paso(cuit: str, desde: date, estado: dict):
    def fn(ctx, portal):
        hoy = date.today()
        pagos = leer(ctx, portal, cuit, desde, hoy)
        d = os.path.join(DATOS, cuit, "pagos_sct")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{hoy.isoformat()}.json"), "w", encoding="utf-8") as f:
            json.dump({"cuit": cuit, "fecha": hoy.isoformat(), "desde": desde.isoformat(), "hasta": hoy.isoformat(),
                       "pagos": pagos}, f, ensure_ascii=False, indent=1)
        estado.update(resultado=f"OK ({len(pagos)} pagos desde {desde:%d/%m/%Y})")
        return "OK"
    return fn
