"""Robot Nuestra Parte: comprobantes electrónicos observados (facturas de proveedores sin capacidad = APOC).

Recorrido (relevado el 16/11/2026):
  Mis servicios -> NUESTRA PARTE (cgpf-webv2-fe.arca.gob.ar/#/)  encabezado "NOMBRE [20-27311121-3]"
  "Tenés N mensajes importantes" -> Ver Detalle               (#/mensajes-cumplimiento)
  "Comprobantes electrónicos observados" -> Ver Detalle       (#/comprobantes_observados)
     "Comprobantes observados: tenés 9 al 11/11/2026."   tabla + EXPORTAR ▾ (Solo columnas visualizadas /
     FORMATO XLSX / GENERAR XLSX) -> exportacion_<fecha>.xlsx  (lector_observados)
Si la exportación no baja, lee la tabla de la pantalla página por página (mismo resultado).
Guarda DATOS/<cuit>/observados/observados.json (+ el xlsx). Solo consulta.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date

from . import arca
from .lector_observados import leer
from .robot_libro_iva import PROHIBIDO, _controlar_cuit, _xp_texto

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
TITULO = re.compile(r"Comprobantes electr[oó]nicos observados", re.I)
SIN_DATOS = re.compile(r"no (ten[eé]s|registr|hay|se encontraron|existen) .{0,40}comprobantes|ten[eé]s 0 ", re.I)

JS_TABLA = r"""() => {
  const t = [...document.querySelectorAll('table')].find(x => /cuit del emisor/i.test(x.innerText)) ;
  if (!t) return null;
  const cab = [...t.querySelectorAll('thead th, thead td')].map(c => c.innerText.trim());
  const filas = [...t.querySelectorAll('tbody tr')].map(tr => [...tr.querySelectorAll('td')].map(c => c.innerText.trim()))
                 .filter(f => f.length >= 4);
  return {cab, filas};
}"""


def _pantalla(page, base: str) -> str:
    """Abre la pantalla de observados. Devuelve 'ok' o 'sin observados'."""
    page.goto(base + "#/comprobantes_observados", wait_until="domcontentloaded")
    limite = time.time() + 45
    while time.time() < limite:
        t = page.inner_text("body") if page.locator("body").count() else ""
        if TITULO.search(t) and (page.locator("table").count() or SIN_DATOS.search(t)):
            return "sin observados" if SIN_DATOS.search(t) and not page.locator("table tbody tr").count() else "ok"
        page.wait_for_timeout(1500)
    # Camino por menús: Mensajes importantes -> Comprobantes electrónicos observados
    page.goto(base + "#/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    t = page.inner_text("body")
    if not re.search(r"mensajes importantes", t, re.I):
        return "sin observados"                      # sin mensajes importantes: no hay observados
    page.locator(f"xpath=//{_xp_texto('ver detalle')}").first.click()
    arca.pausa(1.0, 2.0)
    tit = page.get_by_text(TITULO).first
    try:
        tit.wait_for(state="visible", timeout=30_000)
    except Exception:
        return "sin observados"
    tit.locator(f"xpath=ancestor::*[.//{_xp_texto('ver detalle')}][1]").locator(f"xpath=.//{_xp_texto('ver detalle')}").first.click()
    page.get_by_text(re.compile(r"cuit del emisor", re.I)).first.wait_for(timeout=45_000)
    return "ok"


def _exportar(page, ruta: str) -> bool:
    """EXPORTAR ▾ -> todas las columnas, formato XLSX -> descarga. Devuelve False si no bajó."""
    try:
        page.locator(f"xpath=//{_xp_texto('exportar')}").first.click()
        arca.pausa(0.8, 1.5)
        solo = page.get_by_label(re.compile(r"solo columnas visualizadas", re.I))
        if solo.count() and solo.first.is_checked():
            solo.first.uncheck()
        fmt = page.get_by_text(re.compile(r"FORMATO\s+XLSX", re.I))
        if not (fmt.count() and fmt.first.is_visible()):
            page.get_by_text(re.compile(r"^\s*FORMATO", re.I)).first.click()
            page.get_by_text(re.compile(r"XLSX", re.I)).last.click()
        # Botón del panel relevado el 16/11/2026: "GENERAR XLSX" (exactamente ese texto; nada más se toca)
        gen = page.locator(f"xpath=//{_xp_texto('generar xlsx')}")
        gen.first.wait_for(state="visible", timeout=15_000)
        with page.expect_download(timeout=90_000) as dl:
            gen.first.click()
        dl.value.save_as(ruta)
        return True
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False


def _leer_pantalla(page) -> list[dict]:
    """Plan B: lee la tabla de la pantalla, todas las páginas."""
    try:                                              # mostrar el máximo de filas por página
        sel = page.locator("select").filter(has=page.locator("option"))
        if sel.count():
            opciones = sel.first.locator("option").all_inner_texts()
            nums = [o for o in opciones if o.strip().isdigit()]
            if nums:
                sel.first.select_option(label=max(nums, key=int))
                page.wait_for_timeout(1500)
    except Exception:
        pass
    filas, cab, vistas = [], None, set()
    for _ in range(100):
        d = page.evaluate(JS_TABLA)
        if not d:
            break
        cab = d["cab"]
        nuevas = [f for f in d["filas"] if tuple(f) not in vistas]
        if not nuevas:
            break
        for f in nuevas:
            vistas.add(tuple(f))
            filas.append(f)
        sig = page.locator("button[aria-label*='iguiente'], button[aria-label*='ext'], li.next a, .pagination-next")
        if not sig.count() or not sig.first.is_enabled():
            break
        sig.first.click()
        page.wait_for_timeout(1500)
    if not cab:
        return []
    from openpyxl import Workbook
    import tempfile
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(cab)
    for f in filas:
        ws.append(f)
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False).name
    wb.save(tmp)
    try:
        return leer(tmp)
    finally:
        os.remove(tmp)


def guardar(cuit: str, comps: list[dict], origen: str, aviso: str = "") -> str:
    carpeta = os.path.join(DATOS, cuit, "observados")
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, "observados.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"cuit": cuit, "fecha": date.today().isoformat(), "origen": origen, "aviso": aviso,
                   "comprobantes": comps}, f, ensure_ascii=False, indent=1, default=str)
    return ruta


def paso(cuit: str, estado: dict):
    def fn(ctx, portal):
        try:
            page = arca.abrir_servicio(ctx, portal, "nuestra_parte")
        except arca.RequiereIntervencion:
            estado["resultado"] = "sin servicio Nuestra Parte"
            return dict(estado)
        page.wait_for_load_state("domcontentloaded")
        _controlar_cuit(page, cuit, "Nuestra Parte")
        base = page.url.split("#")[0]
        if _pantalla(page, base) == "sin observados":
            guardar(cuit, [], "pantalla")
            estado["resultado"] = "sin observados"
            page.close()
            return dict(estado)
        aviso = ""
        m = re.search(r"ten[eé]s\s+(\d+)\s+al\s+(\d{2}/\d{2}/\d{4})", page.inner_text("body"), re.I)
        if m:
            aviso = f"{m.group(1)} al {m.group(2)}"
        carpeta = os.path.join(DATOS, cuit, "observados")
        os.makedirs(carpeta, exist_ok=True)
        ruta = os.path.join(carpeta, f"observados_{date.today().isoformat()}.xlsx")
        if _exportar(page, ruta):
            comps, origen = leer(ruta), "exportación XLSX"
        else:
            comps, origen = _leer_pantalla(page), "lectura de pantalla"
        if m and int(m.group(1)) != len(comps):
            raise arca.ErrorRobot(f"Observados: ARCA dice {m.group(1)} y se leyeron {len(comps)}")
        guardar(cuit, comps, origen, aviso)
        estado["resultado"] = f"{len(comps)} observados ({origen})"
        page.close()
        return dict(estado)
    return fn


def correr(cuit, periodo, usuario, clave, metodo="Directo", visible=False, **_):
    estado: dict = {}
    r = arca.ejecutar(usuario, clave, [("observados", paso(cuit, estado))], os.path.join(DATOS, cuit, "capturas"), visible)
    return {"cuit": cuit, "periodos": {"observados": estado.get("resultado", "")}, "reingresos": r["_reingresos"],
            "archivos": {"observados": {"alertas": []}}}
