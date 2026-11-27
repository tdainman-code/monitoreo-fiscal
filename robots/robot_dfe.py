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

IMPORTANTE: abrir una comunicación no leída la da por NOTIFICADA (corren plazos). Este robot solo lee la lista y
clasifica la importancia por asunto y clasificación. ÚNICA excepción (Gaby 27/11/2026): abre las de los sistemas sin
importancia (Libro de sueldos, SIM servicios extraordinarios, SICNEA, Malvina, SECOEXPO, Mi PyME) para que queden
leídas, salvo que hablen de intimación, pago, fiscalización o falta de presentación. Ver abrir_rutinarias.
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


def _cerrar_cartel(page, espera_ms: int = 4000):
    """Cierra los carteles que tapan la bandeja SIN aceptar ni abrir nada:
      - viejo (e-ventanilla): "Recordar más tarde"
      - nuevo (DFE 4.8, nov/2026): modal "Notificaciones de oficio" -> botón CERRAR.
    NUNCA se toca "Visualizar": abriría comunicaciones."""
    for nombre in (r"^\s*Recordar m[aá]s tarde\s*$", r"^\s*Cerrar\s*$"):
        try:
            b = page.get_by_role("button", name=re.compile(nombre, re.I))
            b.first.wait_for(state="visible", timeout=espera_ms)
            texto = (b.first.inner_text() or "").strip().lower()
            if "visualizar" in texto:            # por las dudas: jamás
                continue
            b.first.click()
            arca.pausa(0.5, 1.0)
        except Exception:
            pass


def _vigilar_cartel_oficio(page) -> None:
    """Gaby 26/11/2026 (Nabajuma): el modal "Notificaciones de oficio — tenés N comunicaciones notificadas de oficio sin
    leer" puede aparecer en cualquier momento (al elegir el representado o al aplicar fechas) y tapa los clics: el robot
    esperaba 45 s y fallaba. Playwright lo cierra solo antes de cada acción, siempre con CERRAR (nunca VISUALIZAR)."""
    if not hasattr(page, "add_locator_handler"):
        return
    # 27/11/2026: solo el modal (no un texto suelto de la página) y sin esperar a que desaparezca: si el texto
    # quedaba visible, Playwright frenaba cada clic hasta los 45 s (Nabajuma: "Locator.click: Timeout 45000ms")
    cartel = page.locator(".modal.show, .modal.in, .modal[style*='block'], [role=dialog], [role=alertdialog]").filter(
        has_text=re.compile(r"notificadas de oficio sin leer", re.I))

    def cerrar(*_):
        for loc in (page.get_by_role("button", name=re.compile(r"^\s*Cerrar\s*$", re.I)),
                    page.locator(".modal button, .modal a, [role=dialog] button").filter(has_text=re.compile(r"^\s*Cerrar\s*$", re.I))):
            try:
                if loc.count():
                    loc.first.click(timeout=5000)
                    return
            except Exception:
                continue
        page.keyboard.press("Escape")

    try:
        page.add_locator_handler(cartel, cerrar, no_wait_after=True)
    except TypeError:                                  # Playwright viejo, sin no_wait_after
        page.add_locator_handler(cartel, cerrar)
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


# ---------------------------------------------------------------- pantalla nueva (DFE 4.8, nov/2026)
# Encabezado "DOMICILIO FISCAL ELECTRONICO"; a la izquierda "Bandeja de entrada (N)";
# solapas "Mis Comunicaciones (N)" | "Comunicaciones de [CHIP: RAZÓN SOCIAL (N) x]".
# Las filas NO LEÍDAS van en negrita; la columna "Notificado" trae fecha aunque no se haya leído
# (notificación de oficio: los plazos ya corren).

def es_pantalla_nueva(page) -> bool:
    try:
        return page.get_by_text(re.compile(r"Bandeja de entrada", re.I)).count() > 0 \
            and page.locator("#select-representados").count() == 0
    except Exception:
        return False


_SUFIJOS = r"\b(s\.?\s?a\.?\s?s?|s\.?\s?r\.?\s?l|s\.?\s?a\.?\s?u|s\.?\s?c|s\.?\s?h|sociedad an[oó]nima|sociedad de responsabilidad limitada)\b\.?"


def _norm(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(_SUFIJOS, " ", t)
    t = re.sub(r"\(\d+\)", " ", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def coincide_representado(texto_chip: str, cuit: str, razon_social: str) -> bool:
    """El chip muestra "RAZÓN SOCIAL (N)". Coincide si trae el CUIT o la razón social (sin S.A./S.R.L.)."""
    if cuit in re.sub(r"\D", "", texto_chip) or arca.cuit_fmt(cuit) in texto_chip:
        return True
    a, b = _norm(texto_chip).replace(" x", " ").replace(" ", ""), _norm(razon_social).replace(" ", "")
    return len(b) >= 4 and (b in a or (len(a) >= 6 and a in b))


def _solapa_representados(page):
    return page.locator("[role=tab], .nav-link, .nav-item, li, a, button").filter(
        has_text=re.compile(r"Comunicaciones de", re.I)).last


def _texto_solapa(page) -> str:
    try:
        return _solapa_representados(page).inner_text(timeout=5000)
    except Exception:
        return ""


def _elegir_representado_nuevo(page, cuit: str, razon_social: str):
    sol = _solapa_representados(page)
    try:
        sol.wait_for(state="visible", timeout=30_000)
    except Exception:
        raise arca.SinRepresentado(f"DFE: no aparece la solapa 'Comunicaciones de' (¿{arca.cuit_fmt(cuit)} "
                                   "no es representado del usuario?)")
    # clic en el texto de la solapa (NO en la x del chip, que quita el representado)
    page.get_by_text(re.compile(r"^\s*Comunicaciones de\s*$", re.I)).first.click()
    arca.pausa(1.5, 2.5)
    _cerrar_cartel(page)
    if coincide_representado(_texto_solapa(page), cuit, razon_social):
        return
    # No es el que está elegido: buscarlo en el selector que abra la solapa (lista, select o buscador)
    candidatos = [cuit, arca.cuit_fmt(cuit)] + ([razon_social] if razon_social else [])
    elegido = False
    for sel in page.locator("select:visible").all():
        try:
            ops = sel.evaluate("s => [...s.options].map(o => [o.value, o.textContent])")
            for v, t in ops:
                if any(c and (c in (v or "") or c.lower() in (t or "").lower()) for c in candidatos) \
                        or coincide_representado(t or "", cuit, razon_social):
                    sel.select_option(value=v)
                    elegido = True
                    break
        except Exception:
            pass
        if elegido:
            break
    if not elegido:
        for c in candidatos:
            item = page.locator("[role=option]:visible, .dropdown-item:visible, li:visible, button:visible").filter(
                has_text=re.compile(re.escape(c), re.I))
            if item.count():
                item.first.click()
                elegido = True
                break
    arca.pausa(2.0, 3.5)
    _cerrar_cartel(page)
    chip = _texto_solapa(page)
    if not coincide_representado(chip, cuit, razon_social):
        raise arca.CuitEquivocado(
            f"DFE (pantalla nueva): la solapa muestra '{chip.strip()[:80]}' y no a {arca.cuit_fmt(cuit)}"
            + ("" if razon_social else " (falta la razón social del cliente para comparar)"))


JS_TABLA_DFE = """(t) => {
  const limpiar = s => (s || '').replace(/\\(Click to [^)]*\\)/ig, '').replace(/\\s+/g, ' ').trim();
  const hr = t.tHead ? t.tHead.rows[t.tHead.rows.length - 1] : t.rows[0];
  const cuerpo = [...t.rows].filter(r => r !== hr && !['THEAD', 'TFOOT'].includes(r.parentElement.tagName));
  const noLeida = r => !!r.querySelector('.no-leido') || [...r.cells].some(c => [c, ...c.querySelectorAll('*')]
        .some(e => (parseInt(getComputedStyle(e).fontWeight) || 400) >= 600 && e.textContent.trim()));
  const deOficio = r => [...r.querySelectorAll('[title],[aria-label]')].some(e =>
        /de oficio/i.test(e.getAttribute('title') || e.getAttribute('aria-label') || ''));
  return {encabezados: [...hr.cells].map(c => limpiar(c.textContent)),
          filas: cuerpo.map(r => ({negrita: noLeida(r), oficio: deOficio(r),
                                   celdas: [...r.cells].map(c => limpiar(c.innerText || c.textContent))}))};
}"""


def _tabla_activa(page):
    t = page.locator(".tab-pane.active table, [role=tabpanel].active table")
    return t if t.count() else page.locator("table:visible")


def _leer_tabla_nueva(page) -> tuple[list[dict], str]:
    """Devuelve (filas, aviso). Nunca hace clic en una fila."""
    try:
        _tabla_activa(page).first.wait_for(state="visible", timeout=30_000)
    except Exception:
        texto = page.inner_text("body")
        if re.search(r"no (hay|ten[eé]s|se encontraron)|sin (comunicaciones|resultados)", texto, re.I):
            return [], ""
        raise arca.ErrorRobot("DFE (pantalla nueva): no apareció la tabla de comunicaciones")
    for sel in page.locator("select:visible").all():          # "Mostrar [10] registros" -> 100
        try:
            ops = sel.evaluate("s => [...s.options].map(o => o.value)")
            if "100" in ops:
                sel.select_option("100")
                arca.pausa(1.5, 2.5)
                break
        except Exception:
            pass
    _cerrar_cartel(page, 1500)
    t = _tabla_activa(page).first.evaluate(JS_TABLA_DFE)
    enc = [e.lower() for e in t["encabezados"]]
    idx = {k: next((i for i, e in enumerate(enc) if e.startswith(k)), None)
           for k in ("notific", "asunto", "organismo", "representado", "clasificaci", "recibido")}
    filas = []
    for f in t["filas"]:
        c = f["celdas"]
        if len(c) != len(enc) or not any(c):
            continue
        g = lambda k: c[idx[k]] if idx[k] is not None else ""
        noti = g("notific")
        mf = re.search(r"\d{2}/\d{2}/\d{4}", noti or "")
        filas.append({"notificado": mf[0] if mf else None, "leida_pantalla": not f["negrita"],
                      "de_oficio": bool(f.get("oficio")),
                      "asunto": g("asunto"), "organismo": g("organismo"), "representado": g("representado"),
                      "clasificacion": g("clasificaci"), "recibido": g("recibido")})
    aviso = ""
    m = re.search(r"\bde\s+(\d+)\b", page.locator(".tab-pane.active").first.inner_text()
                  if page.locator(".tab-pane.active").count() else "")
    if m and int(m[1]) > 1:
        aviso = f"La bandeja tiene {m[1]} páginas y se leyó la primera (100 comunicaciones)."
    return filas, aviso


MAX_ABRIR = 25

JS_MARCAR_FILA = """([asunto, recibido, representado]) => {
  document.querySelectorAll('[data-robot-abrir]').forEach(e => e.removeAttribute('data-robot-abrir'));
  const limpiar = s => (s || '').replace(/\\s+/g, ' ').trim();
  const t = [...document.querySelectorAll('.tab-pane.active table, [role=tabpanel].active table, table')]
            .find(x => x.offsetParent !== null);
  if (!t) return 'sin tabla';
  const filas = [...t.querySelectorAll('tbody tr')].filter(r => {
    const c = [...r.cells].map(x => limpiar(x.innerText));
    return c.includes(asunto) && c.includes(recibido) && (!representado || c.includes(representado));
  });
  if (filas.length !== 1) return 'filas: ' + filas.length;
  const celda = [...filas[0].cells].find(x => limpiar(x.innerText) === asunto);
  const el = celda.querySelector('a, button, [role=link], span, div') || celda;
  el.setAttribute('data-robot-abrir', '1');
  return 'ok';
}"""


def abrir_rutinarias(page, filas: list[dict], cuit: str, razon_social: str) -> int:
    """Gaby 27/11/2026: abre (para que queden leídas en ARCA) las comunicaciones NO LEÍDAS de los sistemas sin
    importancia (Libro de sueldos, SIM servicios extraordinarios, SICNEA, Malvina, SECOEXPO, Mi PyME). Solo esas:
    clic en el asunto -> detalle ("N° de comunicación", adjuntos) -> VOLVER. Nunca toca otra comunicación. Si algo no
    coincide (fila repetida, otro representado, otra pantalla), no abre y sigue."""
    from .notificaciones import rutinaria
    n = 0
    for f in filas:
        if n >= MAX_ABRIR:
            break
        if f.get("leida_pantalla") or not rutinaria(f["asunto"], f["clasificacion"], f.get("organismo") or ""):
            continue
        if f.get("representado") and razon_social and not coincide_representado(f["representado"], cuit, razon_social):
            continue
        try:
            if razon_social and not coincide_representado(_texto_solapa(page), cuit, razon_social):
                break                                # volvió a "Todos tus representados" u otro: no se abre nada más
            if page.evaluate(JS_MARCAR_FILA, [f["asunto"], f["recibido"], f.get("representado") or ""]) != "ok":
                continue
            page.locator("[data-robot-abrir='1']").first.click()
            page.get_by_text(re.compile(r"N[°º]\s*de\s*comunicaci[oó]n\s*:", re.I)).first.wait_for(timeout=30_000)
            arca.pausa(1.0, 2.0)
            detalle = page.inner_text("body")
            ok = f["asunto"][:40].lower() in detalle.lower()
            page.get_by_role("button", name=re.compile(r"^\s*VOLVER\s*$", re.I)).first.click()
            _tabla_activa(page).first.wait_for(state="visible", timeout=30_000)
            arca.pausa(1.0, 2.0)
            _cerrar_cartel(page, 1500)
            if ok:
                f["leida_pantalla"] = True
                f["abierta_por_robot"] = True
                n += 1
        except Exception:
            break                                   # pantalla inesperada: no se sigue abriendo nada
    return n


def _guardar_html(page, cuit: str) -> None:
    """Copia de la página (sin claves) para relevar cambios de pantalla de ARCA."""
    try:
        d = os.path.join(DATOS, cuit, "capturas")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"dfe_pagina_{date.today().isoformat()}.html"), "w", encoding="utf-8") as fh:
            fh.write(page.content())
    except Exception:
        pass


def paso(cuit: str, usuario: str, estado: dict):
    def fn(ctx, portal):
        page = arca.abrir_servicio(ctx, portal, "domicilio_fiscal")
        _vigilar_cartel_oficio(page)
        page.wait_for_load_state("domcontentloaded")
        arca.pausa(2.0, 3.5)
        _cerrar_cartel(page, 8000)
        aviso = ""
        abiertas = 0
        if es_pantalla_nueva(page):
            from .almacen_claves import razon_social as _rs
            try:
                rs = _rs(cuit)
            except Exception:
                rs = ""
            if cuit == usuario:
                pest = page.locator("[role=tab], .nav-link, li, a, button").filter(
                    has_text=re.compile(r"Mis Comunicaciones", re.I))
                if pest.count():
                    pest.first.click()
                    arca.pausa(1.0, 2.0)
                    _cerrar_cartel(page)
            else:
                _elegir_representado_nuevo(page, cuit, rs)
            _guardar_html(page, cuit)
            filas, aviso = _leer_tabla_nueva(page)
            abiertas = abrir_rutinarias(page, filas, cuit, rs if cuit != usuario else "")
        else:
            if cuit == usuario:
                try:
                    page.get_by_text(arca.cuit_fmt(cuit)).first.wait_for(state="visible", timeout=30_000)
                except Exception:
                    raise arca.CuitEquivocado(f"DFE: el encabezado no muestra {arca.cuit_fmt(cuit)}")
                solapa = page.locator("[role=tab]:visible").filter(has_text=re.compile(r"Mis Comunicaciones", re.I))
                try:
                    solapa.first.wait_for(state="visible", timeout=8_000)
                    solapa.first.click()
                    arca.pausa(1.0, 2.0)
                except Exception:
                    pass
            else:
                _elegir_representado(page, cuit)
            _guardar_html(page, cuit)
            filas = _leer_tabla(page)
        hoy = date.today()
        com, alertas = [], []
        from .notificaciones import clasificar, responsable
        resp = responsable(cuit)
        for f in filas:
            cl = clasificar(f["asunto"], f["clasificacion"], sistema=f.get("organismo") or "")
            leida = f.get("leida_pantalla", f["notificado"] is not None)
            com.append({"fecha": f["recibido"], "notificado": f["notificado"], "leida": leida,
                        "notificada_sin_leer": bool(f["notificado"]) and not leida,
                        "de_oficio": f.get("de_oficio", False),
                        "organismo": f["organismo"], "asunto": f["asunto"], "clasificacion": f["clasificacion"],
                        "importancia": cl["importancia"], "para": cl["para"], "motivo": cl["motivo"],
                        "abierta_por_robot": bool(f.get("abierta_por_robot")),
                        "responsable": resp if cl["motivo"] == "falta de presentación" else ""})
        no_leidas_altas = [c for c in com if not c["leida"] and c["importancia"] == "ALTA"]
        for c in com:
            if c["notificada_sin_leer"]:
                alertas.append({"prioridad": "ALTA", "tipo": "DFE",
                                "texto": f"{c['fecha']} {c['organismo']}: {c['asunto'] or c['clasificacion']} — "
                                         f"NOTIFICADA{' DE OFICIO' if c['de_oficio'] else ''} el {c['notificado']} SIN LEER (los plazos ya corren)"})
            elif c["importancia"] == "ALTA":
                alertas.append({"prioridad": "ALTA" if not c["leida"] else "Media", "tipo": "DFE",
                                "texto": f"{c['fecha']} {c['organismo']}: {c['asunto']} [{c['motivo']} -> {c['para']}]"
                                         + (f" RESPONSABLE: {c['responsable']}" if c["responsable"] else "")
                                         + (" (SIN ABRIR)" if not c["leida"] else f" (notificada {c['notificado']})")})
        res = {"cuit": cuit, "fecha": hoy.isoformat(), "rango": "últimos 60 días (por defecto de ARCA)",
               "comunicaciones": com, "total": len(com), "sin_abrir": sum(1 for c in com if not c["leida"]),
               "abiertas_por_robot": abiertas,
               "altas_sin_abrir": len(no_leidas_altas),
               "notificadas_sin_leer": sum(1 for c in com if c["notificada_sin_leer"]),
               "aviso": aviso, "alertas": alertas}
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
