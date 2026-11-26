"""Mis Retenciones (ARCA): percepciones y retenciones de IVA que los agentes le informaron al cliente.
Relevado con Gaby el 21/11/2026.

Para qué (Gaby): las percepciones entran SOLAS en la DDJJ de IVA (importación automática), pero si la factura de esa
compra no está en el Libro IVA Digital (Portal IVA) ni el gasto ni el crédito fiscal se computaron: hay que buscarla.
El cruce lo hace robots/percepciones.py y se muestra en la Relación débito crédito.

Recorrido:
  Mis servicios -> "Mis Retenciones" -> mirequa-web.arca.gob.ar (versión NUEVA, en implementación: máximo 8 meses por
  consulta y la exportación tarda hasta 2 horas) -> cartel "Podés acceder a la versión anterior del servicio haciendo
  click aquí" -> seti.afip.gob.ar/misret (versión ANTERIOR, la que funciona; es la que usa el robot):
    "Consulta de Retenciones Impositivas":
      CUIT del retenido  <select> con los CUIT que puede ver el usuario (el propio y sus representados)
      Impuesto retenido  código + <select> ("767 - SICORE - RETENCIONES Y PERCEPC", "216 - SIRE - IVA", ...)
      Retención / Percepción / Retención y/o Percepción (radio)
      Fecha Ret./Perc. Desde / Hasta (ddMMaaaa)
      CONSULTAR -> tabla paginada de 50 (CUIT Agente Ret./Perc. | Impuesto | Régimen | Fecha Ret./Perc. |
        Número Certificado | Descripción Operación | Importe Ret./Perc. | Número Comprobante | Fecha Comprobante |
        Descripción Comprobante | Fecha Registración DJ Ag.Ret. | Código de Seguridad); importes 6,980.30
Solo consulta: no exporta para aplicativos ni toca reclamos.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta

from . import arca

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
MESES = 2              # habitual: los 2 últimos meses (Gaby 26/11/2026); el inicial (5 años) pasa meses=60
IMPUESTOS = ("767", "216")                     # SICORE IVA y SIRE IVA (los que filtra la versión nueva para IVA)
# Aduaneras (menú "Aduaneras", agente 33-69345023-9 ARCA-Aduana): percepciones de IVA (767) y Ganancias (217) de los
# despachos de importación; las dos sirven para ver que el despacho exista en el Libro IVA (Gaby, 21/11/2026).
IMPUESTOS_ADUANA = ("767", "217")

_COLUMNAS = {
    "agente": r"CUIT\s*Agente", "impuesto": r"^Impuesto$", "regimen": r"R[eé]gimen", "fecha": r"Fecha\s*Ret",
    "certificado": r"Certificado", "operacion": r"Desc(ripci[oó]n|\.)?\s*Operaci", "importe": r"Importe",
    "comprobante": r"N[uú]mero\s*Comprobante", "fecha_comprobante": r"Fecha\s*Comprobante",
    "desc_comprobante": r"Descripci[oó]n\s*Comprobante", "fecha_dj": r"Registraci",
}

JS_TABLA = r"""() => {
  // 25/11/2026: la consulta de Aduana NO tiene columna "CUIT Agente" (el agente va arriba): se busca por los encabezados
  const t = [...document.querySelectorAll('table')].filter(x => /Importe/i.test(x.innerText)
      && (/CUIT\s*Agente/i.test(x.innerText) || /Fecha\s*Ret/i.test(x.innerText)) && /\bImpuesto\b/i.test(x.innerText));
  const tabla = t.length ? t[t.length - 1] : null;
  if (!tabla) return null;
  return [...tabla.querySelectorAll('tr')].map(r => [...r.cells].map(c => c.innerText.replace(/\s+/g, ' ').trim()));
}"""


def _num(t) -> float:
    t = str(t or "").strip()
    if not re.search(r"\d", t):
        return 0.0
    if "," in t and "." in t and t.rfind(",") > t.rfind("."):      # 1.234,56
        t = t.replace(".", "").replace(",", ".")
    else:                                                           # 6,980.30 (formato de la página)
        t = t.replace(",", "")
    neg = t.startswith("-") or t.startswith("(")
    v = float(re.sub(r"[^\d.]", "", t) or 0)
    return -v if neg else v


def filas_tabla(crudas: list[list[str]] | None, agente: str = "") -> list[dict]:
    """Filas crudas de la tabla de resultados -> renglones con nombre (se ubican las columnas por el encabezado).
    agente: el de la consulta, para la tabla de Aduana que no trae la columna "CUIT Agente" (25/11/2026)."""
    if not crudas:
        return []
    i_cab = next((i for i, f in enumerate(crudas) if any(re.search(_COLUMNAS["agente"], c, re.I) for c in f)), None)
    if i_cab is None and agente:
        i_cab = next((i for i, f in enumerate(crudas) if any(re.fullmatch(r"\s*Impuesto\s*", c, re.I) for c in f)
                      and any(re.search(r"Importe", c, re.I) for c in f) and len(f) >= 5), None)
    if i_cab is None:
        return []
    cab = crudas[i_cab]
    pos = {}
    for k, pat in _COLUMNAS.items():
        j = next((j for j, c in enumerate(cab) if re.search(pat, c, re.I)), None)
        if j is not None:
            pos[k] = j
    out = []
    for f in crudas[i_cab + 1:]:
        if len(f) < len(cab) - 1:
            continue
        if "agente" in pos:
            if not re.fullmatch(r"\d{11}", (f[pos["agente"]] or "").replace("-", "")):
                continue
        elif not re.fullmatch(r"\d{3}", (f[pos.get("impuesto", 0)] or "").strip()):
            continue
        g = lambda k: f[pos[k]] if k in pos and pos[k] < len(f) else ""
        out.append({"agente": g("agente").replace("-", "") or agente, "impuesto": g("impuesto"), "regimen": g("regimen"),
                    "fecha": g("fecha"), "certificado": g("certificado"), "operacion": g("operacion").upper(),
                    "importe": _num(g("importe")), "comprobante": re.sub(r"[^\w]", "", g("comprobante")).upper(),
                    "fecha_comprobante": g("fecha_comprobante"), "desc_comprobante": g("desc_comprobante"),
                    "fecha_dj": g("fecha_dj")})
    return out


def tramos(hoy: date, meses: int = MESES) -> list[tuple[date, date]]:
    """Desde el 1° del mes de hace 'meses' meses hasta hoy, en tramos de 6 meses (la versión nueva acepta hasta 8)."""
    ini = hoy.replace(day=1)
    for _ in range(meses):
        ini = (ini - timedelta(days=1)).replace(day=1)
    out, d = [], ini
    while d <= hoy:
        a, m = d.year + (d.month + 5) // 12, (d.month + 5) % 12 + 1
        fin = min(date(a, m, 1) - timedelta(days=1), hoy)
        out.append((d, fin))
        d = fin + timedelta(days=1)
    return out


def _version_anterior(ctx, page):
    """Desde la versión nueva (mirequa) pasa a la anterior (seti .../misret) con el 'click aquí' del cartel."""
    if re.search(r"misret", page.url, re.I):
        return page
    enlace = page.get_by_text(re.compile(r"^\s*click aqu[ií]\s*$", re.I))
    try:
        enlace.first.wait_for(state="visible", timeout=30_000)
    except Exception:
        raise arca.ErrorRobot("Mis Retenciones: no aparece el enlace a la versión anterior ('click aquí')")
    antes = set(ctx.pages)
    enlace.first.click()
    page.wait_for_timeout(3000)
    nuevas = [p for p in ctx.pages if p not in antes]
    destino = nuevas[-1] if nuevas else page
    destino.wait_for_load_state("domcontentloaded")
    if not re.search(r"misret", destino.url, re.I):
        destino.wait_for_url(re.compile(r"misret", re.I), timeout=30_000)
    return destino


FORM: dict = {}                                 # lo que quedó cargado en el formulario (para el mensaje de error)


def _navegando(page, accion, espera_ms: int = 8000) -> None:
    """Hace la acción y, si la página se recarga (el selector de CUIT y CONSULTAR recargan la página), espera."""
    try:
        with page.expect_navigation(timeout=espera_ms, wait_until="domcontentloaded"):
            accion()
    except Exception:
        pass
    page.wait_for_timeout(800)


def _formulario(page, cuit: str, impuesto: str, desde: date, hasta: date) -> None:
    """22/11/2026: en ARCA real el formulario quedaba sin consultar. Al elegir el CUIT del retenido la página se
    RECARGA (busca el nombre); lo cargado antes de que termine se pierde. Ahora se espera la recarga, los campos se
    escriben como un usuario (tecla por tecla) y se controla lo cargado antes de CONSULTAR."""
    sel_cuit = page.locator("select").filter(has=page.locator(f"option[value='{cuit}']"))
    if not sel_cuit.count():
        sel_cuit = page.locator("select").filter(has=page.locator("option", has_text=cuit))
    if not sel_cuit.count():
        raise arca.SinRepresentado(f"Mis Retenciones: {arca.cuit_fmt(cuit)} no figura en 'CUIT del retenido'")
    s = sel_cuit.first
    actual = s.evaluate("x => (x.options[x.selectedIndex] || {}).text || ''")
    if cuit not in actual.replace("-", ""):
        op = next((o for o in s.locator("option").all_inner_texts() if cuit in o.replace("-", "")), cuit)
        _navegando(page, lambda: s.select_option(label=op))
    # impuesto: código en la caja chica (como un usuario: escribir y salir del campo) y el selector
    sel_imp = page.locator("select").filter(has=page.locator("option", has_text=re.compile(rf"^\s*{impuesto}\s*-")))
    if not sel_imp.count():
        raise arca.ErrorRobot(f"Mis Retenciones: no está el impuesto {impuesto} en el selector")
    n_cod = page.evaluate("""(imp) => { const s = [...document.querySelectorAll('select')].find(x =>
        [...x.options].some(o => o.text.trim().startsWith(imp + ' -'))); if (!s) return -1;
        const ins = [...document.querySelectorAll('input[type=text], input:not([type])')];
        const prev = ins.filter(i => i.offsetParent !== null && !i.disabled && !i.readOnly
                                && (i.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_FOLLOWING)).pop();
        if (!prev) return -1; ins.forEach((i, n) => i.setAttribute('data-robot-mr', String(n)));
        return Number(prev.getAttribute('data-robot-mr')); }""", impuesto)
    if n_cod >= 0:
        cod = page.locator(f"[data-robot-mr='{n_cod}']")
        cod.fill("")
        cod.press_sequentially(impuesto, delay=60)
        cod.press("Tab")
        page.wait_for_timeout(600)
    op = next(o for o in sel_imp.first.locator("option").all_inner_texts() if re.match(rf"\s*{impuesto}\s*-", o))
    if not re.match(rf"\s*{impuesto}\s*-", sel_imp.first.evaluate("x => (x.options[x.selectedIndex] || {}).text || ''")):
        sel_imp.first.select_option(label=op)
    radio = page.locator("input[type=radio]").locator("visible=true")
    if radio.count():
        radio.last.check()                              # "Retención y/o Percepción"
    # Fecha Ret./Perc. Desde / Hasta: los dos primeros campos de texto después de ese rótulo
    idx = page.evaluate("""() => {
      const vis = e => e.offsetParent !== null;
      const rot = [...document.querySelectorAll('td, span, label, div, b')].find(e => vis(e) && e.children.length === 0
                   && /Fecha.{0,20}ret/i.test(e.textContent));
      if (!rot) return [];
      const ins = [...document.querySelectorAll('input[type=text], input:not([type])')];
      ins.forEach((i, n) => i.setAttribute('data-robot-mrf', String(n)));
      return ins.filter(i => vis(i) && (rot.compareDocumentPosition(i) & Node.DOCUMENT_POSITION_FOLLOWING))
                .slice(0, 2).map(i => Number(i.getAttribute('data-robot-mrf'))); }""")
    if len(idx) != 2:
        raise arca.ErrorRobot("Mis Retenciones: no se encontraron los campos de Fecha Ret./Perc.")
    for n, v in zip(idx, (desde.strftime("%d%m%Y"), hasta.strftime("%d%m%Y"))):
        c = page.locator(f"[data-robot-mrf='{n}']")
        c.click()
        c.fill("")
        c.press_sequentially(v, delay=40)
        c.press("Tab")
        if re.sub(r"\D", "", c.input_value()) != v:      # con máscara: si no quedó, se fuerza el valor
            c.evaluate("(i, v) => { i.value = v; ['input','change','blur'].forEach(t => i.dispatchEvent(new Event(t, {bubbles: true}))); }", v)
    FORM.clear()
    FORM.update(page.evaluate("""() => { const sel = [...document.querySelectorAll('select')].map(x =>
        (x.options[x.selectedIndex] || {}).text || '').filter(t => t.trim());
        const ins = [...document.querySelectorAll('input[type=text], input:not([type])')].filter(i => i.offsetParent !== null)
        .map(i => i.value).filter(v => v); return {selectores: sel.join(' | '), campos: ins.join(' | ')}; }"""))
    boton = page.locator("input[value='CONSULTAR' i], button:has-text('CONSULTAR'), a:has-text('CONSULTAR')").locator("visible=true")
    if not boton.count():
        raise arca.ErrorRobot("Mis Retenciones: no aparece el botón CONSULTAR")
    _navegando(page, lambda: boton.first.click(), espera_ms=60_000)


AVISOS: list[str] = []                         # carteles (alert) de la página: errores de validación del formulario


def _escuchar_avisos(page) -> None:
    if getattr(page, "_robot_avisos", False):
        return

    def _d(d):
        AVISOS.append(d.message)
        try:
            d.accept()
        except Exception:
            pass
    page.on("dialog", _d)
    page._robot_avisos = True


def _resultados(page, cuit: str, que: str = "") -> list[dict]:
    """Lee todas las páginas de resultados. [] si ARCA no encontró movimientos.
    22/11/2026: si no aparecen, el error dice lo que mostró la página (cartel o mensaje) y se guarda la pantalla."""
    for _ in range(45):
        crudas = page.evaluate(JS_TABLA)
        if crudas:
            break
        texto = page.inner_text("body")
        # 22/11/2026: ARCA dice "No se han encontrado datos para esta consulta o los parámetros ingresados
        # corresponden a retenciones/percepciones con importe en cero" (la consulta anduvo, no hay movimientos)
        if re.search(r"no se han encontrado|no (se encontraron|existen|hay|posee|registra)|sin (resultados|datos|movimientos)|"
                     r"no hay (datos|registros)|0 registros", texto, re.I):
            return []
        if AVISOS:
            break
        page.wait_for_timeout(1000)
    if not crudas:
        msg = AVISOS[-1] if AVISOS else ""
        if not msg:
            t = re.sub(r"\s+", " ", page.inner_text("body"))
            m = re.search(r"[^.]{0,80}(error|inv[aá]lid|debe|obligatori|incorrect|no se pudo|intente)[^.]{0,100}", t, re.I)
            i = t.find("Consulta de Retenciones")
            msg = m[0].strip() if m else (f"quedó en el formulario sin consultar; cargado: {FORM.get('selectores', '')} / "
                                          f"{FORM.get('campos', '')}" if i >= 0 else f"la página quedó en: {t[:160]}")
        try:
            d = os.path.join(DATOS, cuit, "capturas")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, f"mis_retenciones_{que or 'consulta'}.html"), "w", encoding="utf-8") as fh:
                fh.write(page.content())
            page.screenshot(path=os.path.join(d, f"mis_retenciones_{que or 'consulta'}.png"), full_page=True)
        except Exception:
            pass
        AVISOS.clear()
        raise arca.ErrorRobot(f"Mis Retenciones {que}: no aparecieron los resultados ({msg[:200]})")
    texto = page.inner_text("body")
    if not re.search(rf"{cuit}|{re.escape(arca.cuit_fmt(cuit))}", texto):
        otros = sorted(set(re.findall(r"\b(?:20|23|24|27|30|33|34)\d{9}\b", texto[:600])) - {cuit})
        raise arca.CuitEquivocado(f"Mis Retenciones muestra {', '.join(otros) or 'otro CUIT'} en lugar de {cuit}")
    try:                                                 # "mostrar": la mayor cantidad por página
        sel = page.locator("select").filter(has=page.locator("option", has_text=re.compile(r"^\s*50\s*$")))
        if sel.count():
            ops = [o.strip() for o in sel.last.locator("option").all_inner_texts() if o.strip().isdigit()]
            mayor = max(ops, key=int)
            if mayor != "50":
                sel.last.select_option(label=mayor)
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(1500)
    except Exception:
        pass
    filas, vistos = [], set()
    for _ in range(100):
        nuevas = [f for f in filas_tabla(page.evaluate(JS_TABLA), ADUANA if que.startswith("aduaneras") else "")
                  if (k := tuple(sorted(f.items()))) not in vistos and not vistos.add(k)]
        if not nuevas:
            break
        filas += nuevas
        sig = page.locator("a").filter(has_text=re.compile(r"^\s*\[?\s*>\s*\]?\s*$"))
        if not sig.count():
            break
        sig.first.click()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(1200)
    return filas


def _menu(page, nombre: str) -> None:
    """Menú de la izquierda (Impositivas / Aduaneras); también está en la pantalla de resultados."""
    for _ in range(2):
        m = page.get_by_text(re.compile(rf"^\s*-?\s*{nombre}\s*$", re.I))
        if m.count():
            m.first.click()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(1200)
            return
        page.go_back()
        page.wait_for_load_state("domcontentloaded")
    raise arca.ErrorRobot(f"Mis Retenciones: no aparece el menú '{nombre}'")


def leer(ctx, page, cuit: str, hoy: date, meses: int = MESES) -> dict:
    page = _version_anterior(ctx, page)
    filas, consultas = [], []
    for menu, impuestos in (("Impositivas", IMPUESTOS), ("Aduaneras", IMPUESTOS_ADUANA)):
        for imp in impuestos:
            for d, h in tramos(hoy, meses):
                _menu(page, menu)
                _escuchar_avisos(page)
                AVISOS.clear()
                _formulario(page, cuit, imp, d, h)
                r = _resultados(page, cuit, f"{menu.lower()}_{imp}")
                for x in r:
                    x["aduana"] = menu == "Aduaneras"
                consultas.append({"menu": menu, "impuesto": imp, "desde": d.isoformat(), "hasta": h.isoformat(),
                                  "renglones": len(r)})
                filas += r
                arca.pausa(0.8, 1.6)
    t = tramos(hoy, meses)
    return {"desde": t[0][0].isoformat(), "hasta": t[-1][1].isoformat(), "consultas": consultas, "filas": filas,
            "meses": meses}


ADUANA = "33693450239"


def guardar_versiones(cuit: str, filas: list[dict], hoy: date) -> list[str]:
    """Biblioteca de archivos (pedido de Gabriel, 25/11/2026): de los DOS últimos meses cerrados guarda una versión por
    fuente cada vez que cambia lo informado (presentaciones tardías o rectificativas de los agentes). La web compara la
    última con la anterior y marca lo que apareció, desapareció o cambió. DATOS/<cuit>/biblioteca/<AAAA-MM>/<fuente>/<fecha>.json"""
    guardadas = []
    p1 = hoy.replace(day=1) - timedelta(days=1)
    p2 = p1.replace(day=1) - timedelta(days=1)
    for per in (p2.strftime("%Y-%m"), p1.strftime("%Y-%m")):
        for fuente, es_aduana in (("arca_mr", False), ("arca_aduana", True)):
            del_mes = sorted((f for f in filas if (f.get("agente") == ADUANA) == es_aduana
                              and re.match(r"\d{2}/(\d{2})/(\d{4})", f.get("fecha") or "")
                              and f"{f['fecha'][6:10]}-{f['fecha'][3:5]}" == per),
                             key=lambda f: (f.get("fecha"), f.get("agente"), f.get("comprobante"), f.get("importe")))
            d = os.path.join(DATOS, cuit, "biblioteca", per, fuente)
            previas = sorted(x for x in (os.listdir(d) if os.path.isdir(d) else []) if x.endswith(".json"))
            if previas:
                with open(os.path.join(d, previas[-1]), encoding="utf-8") as f:
                    if json.load(f).get("filas") == del_mes:
                        continue                        # igual a la última versión: no se guarda otra
            os.makedirs(d, exist_ok=True)
            ruta = os.path.join(d, f"{hoy.isoformat()}.json")
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump({"cuit": cuit, "periodo": per, "fuente": fuente, "fecha": hoy.isoformat(), "filas": del_mes},
                          f, ensure_ascii=False, indent=1)
            guardadas.append(ruta)
    return guardadas


def paso(cuit: str, estado: dict, meses: int | None = None):
    def fn(ctx, portal):
        hoy = date.today()
        from . import percepciones_hist as hist
        n = meses or (hist.HISTORICO_MESES if hist.es_cliente_nuevo(cuit) else MESES)
        antes = set(ctx.pages)
        page = arca.abrir_servicio(ctx, portal, "mis_retenciones")
        try:
            r = leer(ctx, page, cuit, hoy, n)
        finally:
            for p in list(ctx.pages):
                if p not in antes:
                    try:
                        p.close()
                    except Exception:
                        pass
        r.update(cuit=cuit, fecha=hoy.isoformat())
        d = os.path.join(DATOS, cuit, "mis_retenciones")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{hoy.isoformat()}.json"), "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        guardar_versiones(cuit, r["filas"], hoy)
        t = tramos(hoy, n)                               # histórico acumulado por mes (pisa los meses consultados)
        cons_meses, d0 = [], t[0][0]
        while d0 <= hoy:
            cons_meses.append(d0.strftime("%Y-%m"))
            d0 = (d0.replace(day=28) + timedelta(days=4)).replace(day=1)
        hist.guardar(cuit, "arca", r["filas"], cons_meses, hoy)
        from . import percepciones
        cr = percepciones.cruzar(cuit)
        n_p = sum(1 for x in r["filas"] if x["operacion"].startswith("PERCEP"))
        res = f"OK ({n_p} percepciones, {len(r['filas']) - n_p} retenciones)"
        if cr and cr.get("sin_comprobante"):
            res += f"; {len(cr['sin_comprobante'])} sin factura en el Libro IVA"
        estado.update(resultado=res, alertas=(cr or {}).get("alertas", []))
        return res
    return fn


def correr(cuit, periodo, usuario, clave, metodo="Directo", visible=False, **_):
    estado: dict = {}
    arca.ejecutar(usuario, clave, [("mis_retenciones", paso(cuit, estado))], os.path.join(DATOS, cuit, "capturas"), visible)
    return {"cuit": cuit, "mis_retenciones": estado.get("resultado"),
            "archivos": {"mis_retenciones": {"alertas": estado.get("alertas", [])}}}
