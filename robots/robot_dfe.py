"""Robot Domicilio Fiscal Electrónico (DFE): lista las comunicaciones SIN ABRIRLAS.

Recorrido (relevado el 15/11/2026, usuario 20-14283675-1):
  Mis servicios -> e-ventanilla -> ve.cloud.afip.gob.ar/index.html
  Cartel informativo al entrar: se cierra con "Recordar más tarde" (no acepta nada).
  Solapas: "Mis Comunicaciones (N)" | "Comunicaciones de mis representados"
     En la segunda: selector "Selecciona tu representado" (select#select-representados, valor = CUIT;
     se elige con la lista desplegable button.dropdown-item que muestra "RAZÓN SOCIAL - CUIT").
  Tabla: Notificado | Asunto | (adjunto) | Organismo | Representado | Clasificación | Recibido
     Notificado = fecha, o "-" si todavía NO se abrió (no notificada).
  Rango por defecto: últimos 60 días. Filas por página: select#per-page-select (10/50/100).

IMPORTANTE: abrir una comunicación no leída la da por NOTIFICADA (corren plazos). Este robot NUNCA hace
clic en una comunicación: solo lee la lista y clasifica la importancia por asunto y clasificación.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date

from . import arca
from .robot_situacion_fiscal import JS_TABLA

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")

# Importancia por palabras del asunto/clasificación (se ajusta con el uso)
REGLAS = [
    ("ALTA", r"intimaci|seclo|regularizaci[oó]n del trabajo|fiscaliz|inspecci|requerimiento|embargo|ejecuci[oó]n|"
             r"juicio|caduc|mis facilidades|determinaci[oó]n|sumario|cargo|falta de (pago|presentaci)|"
             r"exclusi[oó]n|baja de oficio|recategoriz|suspensi|clausura|multa|infracci"),
    ("Media", r"cuentas tributarias|presentaci[oó]n digital|vencimiento|deuda|plan|percepci|retenci|"
              r"comunicaci[oó]n"),
    ("Baja", r"libro de sueldos|aviso de emisi[oó]n|factura de cr[eé]dito|informativ|novedad"),
]


def importancia(asunto: str, clasificacion: str) -> str:
    t = f"{asunto} {clasificacion}".lower()
    for nivel, patron in REGLAS:
        if re.search(patron, t):
            return nivel
    return "Media"


def _cerrar_cartel(page):
    try:
        b = page.get_by_role("button", name=re.compile(r"Recordar m[aá]s tarde", re.I))
        if b.first.is_visible(timeout=4000):
            b.first.click()
            arca.pausa(0.5, 1.0)
    except Exception:
        pass


def _valor_selector(page) -> list[str] | None:
    """Valores del selector de representados (o None si todavía no está). Se consulta cada vez desde
    cero porque la página lo vuelve a dibujar al cambiar de solapa."""
    return page.evaluate("""() => { const s = document.querySelector('#select-representados');
        return s ? [s.value || '', ...[...s.options].map(o => o.value)] : null; }""")


def _elegir_representado(page, cuit: str):
    page.get_by_role("tab", name=re.compile(r"representados", re.I)).first.click()
    arca.pausa(1.5, 2.5)
    vals = None
    for _ in range(40):                                   # hasta ~40 s a que aparezca el selector
        vals = _valor_selector(page)
        if vals:
            break
        page.wait_for_timeout(1000)
    if not vals:
        raise arca.ErrorRobot("DFE: no apareció el selector de representados")
    if cuit not in [re.sub(r"\D", "", v) for v in vals[1:]]:
        raise arca.SinRepresentado(f"DFE: {arca.cuit_fmt(cuit)} no está entre los representados del usuario")
    for intento in range(3):
        if re.sub(r"\D", "", (_valor_selector(page) or [""])[0]) == cuit:
            break
        panel = page.locator(".tab-pane.active")
        panel.locator(".dropdown-toggle, .form-control").first.click()
        arca.pausa(0.8, 1.5)
        item = page.locator("button.dropdown-item:visible", has_text=cuit)
        item.first.wait_for(state="visible", timeout=15_000)
        item.first.click()
        arca.pausa(2.0, 3.5)
    elegido = re.sub(r"\D", "", (_valor_selector(page) or [""])[0])
    if elegido != cuit:
        raise arca.CuitEquivocado(f"DFE: se eligió {cuit} y quedó {elegido or 'nada'}")


def _leer_tabla(page) -> list[dict]:
    panel = page.locator(".tab-pane.active")
    if not panel.count():
        panel = page.locator("body")
    try:
        panel.locator("table").first.wait_for(state="visible", timeout=30_000)
    except Exception:
        return []
    pp = page.locator("#per-page-select")
    if pp.count():
        try:
            pp.first.select_option(label="100")
            arca.pausa(1.0, 2.0)
        except Exception:
            pass
    filas, vistos = [], 0
    for _ in range(20):                                   # páginas (100 por página)
        t = panel.locator("table").first.evaluate(JS_TABLA)
        enc = [e.lower() for e in t["encabezados"]]
        idx = {k: next((i for i, e in enumerate(enc) if e.startswith(k)), None)
               for k in ("notificado", "asunto", "organismo", "representado", "clasificaci", "recibido")}
        for f in t["filas"]:
            c = f["celdas"]
            if len(c) != len(enc):
                continue
            g = lambda k: c[idx[k]] if idx[k] is not None else ""
            filas.append({"notificado": None if g("notificado") in ("-", "") else g("notificado"),
                          "asunto": g("asunto"), "organismo": g("organismo"), "representado": g("representado"),
                          "clasificacion": g("clasificaci"), "recibido": g("recibido")})
        siguiente = page.locator("ul.pagination li:not(.disabled) [aria-label*='next' i], "
                                 "ul.pagination li:not(.disabled) [aria-label*='siguiente' i]")
        if len(filas) == vistos or not siguiente.count():
            break
        vistos = len(filas)
        siguiente.first.click()
        arca.pausa(1.0, 2.0)
    return filas


def paso(cuit: str, usuario: str, estado: dict):
    def fn(ctx, portal):
        page = arca.abrir_servicio(ctx, portal, "domicilio_fiscal")
        page.wait_for_load_state("domcontentloaded")
        _cerrar_cartel(page)
        if cuit == usuario:
            try:
                page.get_by_text(arca.cuit_fmt(cuit)).first.wait_for(state="visible", timeout=30_000)
            except Exception:
                raise arca.CuitEquivocado(f"DFE: el encabezado no muestra {arca.cuit_fmt(cuit)}")
            # Con representados hay solapas; sin representados, la bandeja se muestra directo (sin solapas)
            solapa = page.locator("[role=tab]:visible").filter(has_text=re.compile(r"Mis Comunicaciones", re.I))
            try:
                solapa.first.wait_for(state="visible", timeout=8_000)
                solapa.first.click()
                arca.pausa(1.0, 2.0)
            except Exception:
                pass
        else:
            _elegir_representado(page, cuit)
        filas = _leer_tabla(page)
        hoy = date.today()
        com, alertas = [], []
        from .notificaciones import clasificar, responsable
        resp = responsable(cuit)
        for f in filas:
            cl = clasificar(f["asunto"], f["clasificacion"])
            com.append({"fecha": f["recibido"], "notificado": f["notificado"], "leida": f["notificado"] is not None,
                        "organismo": f["organismo"], "asunto": f["asunto"], "clasificacion": f["clasificacion"],
                        "importancia": cl["importancia"], "para": cl["para"], "motivo": cl["motivo"],
                        "responsable": resp if cl["motivo"] == "falta de presentación" else ""})
        no_leidas_altas = [c for c in com if not c["leida"] and c["importancia"] == "ALTA"]
        for c in com:
            if c["importancia"] == "ALTA":
                alertas.append({"prioridad": "ALTA" if not c["leida"] else "Media", "tipo": "DFE",
                                "texto": f"{c['fecha']} {c['organismo']}: {c['asunto']} [{c['motivo']} -> {c['para']}]"
                                         + (f" RESPONSABLE: {c['responsable']}" if c["responsable"] else "")
                                         + (" (SIN ABRIR)" if not c["leida"] else f" (notificada {c['notificado']})")})
        res = {"cuit": cuit, "fecha": hoy.isoformat(), "rango": "últimos 60 días (por defecto de ARCA)",
               "comunicaciones": com, "total": len(com), "sin_abrir": sum(1 for c in com if not c["leida"]),
               "altas_sin_abrir": len(no_leidas_altas), "alertas": alertas}
        destino = os.path.join(DATOS, cuit, "dfe", hoy.isoformat())
        os.makedirs(destino, exist_ok=True)
        with open(os.path.join(destino, "resultado.json"), "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)
        estado.update(res)
        page.close()
        return res
    return fn


def correr(cuit, periodo, usuario, clave, metodo="Directo", visible=False, **_):
    estado: dict = {}
    arca.ejecutar(usuario, clave, [("dfe", paso(cuit, usuario, estado))],
                  os.path.join(DATOS, cuit, "capturas"), visible)
    return {"cuit": cuit, "archivos": {"dfe": {"alertas": estado.get("alertas", [])}}}
