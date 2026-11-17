"""DDJJ anuales de Ganancias ya PRESENTADAS (para no alertar vencimientos de presentación cumplidos).

Cuentas Tributarias muestra el vencimiento de "PRESENTACION" de Ganancias aunque la DDJJ ya esté presentada
(caso ACUÑA 15/11/2026: DDJJ 2025 presentada el 16/06/2026 por el régimen simplificado y SCT igual mostraba
"vence 16/11/2026"). Este paso lee la lista de presentadas y el robot "todo" saca esas alertas.

Servicio "DECLARACIÓN JURADA SIMPLIFICADA" (F2711): siapweb-f2711-...arca.gob.ar/f2711/index.html#/declaracion.presentadas
   tabla: Período | Establecimiento | Secuencia | Fecha de presentación | Acciones
Si el contribuyente no tiene el servicio, se anota "sin servicio" y no se hace nada.
"""
from __future__ import annotations

import json
import os
import re

from . import arca

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")

JS_FILAS = """() => [...document.querySelectorAll('table')].filter(t => /Fecha de presentaci/i.test(t.textContent))
    .flatMap(t => [...t.querySelectorAll('tbody tr')].map(r => [...r.cells].map(c => c.textContent.replace(/\\s+/g,' ').trim())))"""


def paso(cuit: str, estado: dict):
    def fn(ctx, portal):
        try:
            page = arca.abrir_servicio(ctx, portal, "ddjj_simplificada")
        except arca.RequiereIntervencion:
            estado["_servicio"] = "sin servicio"
            return dict(estado)
        page.wait_for_load_state("domcontentloaded")
        base = page.url.split("#")[0]
        page.goto(base + "#/declaracion.presentadas", wait_until="domcontentloaded")
        filas = []
        for _ in range(30):                        # aplicación Angular: espera a que cargue la tabla
            filas = page.evaluate(JS_FILAS)
            if filas or arca._hay_texto(page, r"no (hay|se encontraron|existen)"):
                break
            page.wait_for_timeout(1000)
        txt = page.inner_text("body")[:1500]
        if arca.cuit_fmt(cuit) not in txt and cuit not in re.sub(r"\D", "", txt):
            raise arca.CuitEquivocado("DDJJ simplificada: la pantalla no muestra el CUIT del cliente")
        pres = []
        for c in filas:
            if len(c) >= 4 and re.fullmatch(r"\d{4}", c[0]):
                pres.append({"periodo": c[0], "secuencia": c[2], "fecha": c[3], "regimen": "Simplificada (F2711)"})
        destino = os.path.join(DATOS, cuit, "ddjj_presentadas.json")
        with open(destino, "w", encoding="utf-8") as f:
            json.dump(pres, f, ensure_ascii=False, indent=1)
        estado.update({"presentadas": pres})
        page.close()
        return dict(estado)
    return fn


def depurar_alertas(sit: dict, presentadas: list[dict]) -> int:
    """Saca de la situación las alertas/vencimientos de PRESENTACIÓN de Ganancias anual ya presentada.
    Devuelve cuántas alertas sacó. Marca el vencimiento como 'presentada el …' en vez de borrarlo."""
    anios = {p["periodo"]: p["fecha"] for p in presentadas}
    sacadas = 0
    sct = sit.get("sct") or {}
    for v in sct.get("vencimientos", []):
        m = re.match(r"(\d{4})0000$", str(v.get("periodo", "")))
        if m and v.get("impuesto", "").startswith("11 ") and m[1] in anios and "PRESENTA" in v.get("detalle", "").upper():
            v["detalle"] = f"Presentada el {anios[m[1]]} (ARCA igual muestra el vencimiento)"
    nuevas = []
    for a in sit.get("alertas", []):
        m = re.search(r"GANANCIAS.*Anual (\d{4}).*PRESENTACI", a.get("texto", ""), re.I)
        if a.get("tipo") == "Vencimiento próximo" and m and m[1] in anios:
            sacadas += 1
            continue
        nuevas.append(a)
    sit["alertas"] = nuevas
    if sct:
        sct["alertas"] = [a for a in sct.get("alertas", []) if a in nuevas]
    return sacadas
