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
MESES = 12
IMPUESTOS = ("767", "216")                     # SICORE IVA y SIRE IVA (los que filtra la versión nueva para IVA)
# Aduaneras (menú "Aduaneras", agente 33-69345023-9 ARCA-Aduana): percepciones de IVA (767) y Ganancias (217) de los
# despachos de importación; las dos sirven para ver que el despacho exista en el Libro IVA (Gaby, 21/11/2026).
IMPUESTOS_ADUANA = ("767", "217")

_COLUMNAS = {
    "agente": r"CUIT\s*Agente", "impuesto": r"^Impuesto$", "regimen": r"R[eé]gimen", "fecha": r"Fecha\s*Ret",
    "certificado": r"Certificado", "operacion": r"Descripci[oó]n\s*Operaci", "importe": r"Importe",
    "comprobante": r"N[uú]mero\s*Comprobante", "fecha_comprobante": r"Fecha\s*Comprobante",
    "desc_comprobante": r"Descripci[oó]n\s*Comprobante", "fecha_dj": r"Registraci",
}

JS_TABLA = r"""() => {
  const t = [...document.querySelectorAll('table')].filter(x => /CUIT\s*Agente/i.test(x.innerText) && /Importe/i.test(x.innerText));
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


def filas_tabla(crudas: list[list[str]] | None) -> list[dict]:
    """Filas crudas de la tabla de resultados -> renglones con nombre (se ubican las columnas por el encabezado)."""
    if not crudas:
        return []
    i_cab = next((i for i, f in enumerate(crudas) if any(re.search(_COLUMNAS["agente"], c, re.I) for c in f)), None)
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
        if len(f) < len(cab) - 1 or not re.fullmatch(r"\d{11}", (f[pos.get("agente", 0)] or "").replace("-", "")):
            continue
        g = lambda k: f[pos[k]] if k in pos and pos[k] < len(f) else ""
        out.append({"agente": g("agente").replace("-", ""), "impuesto": g("impuesto"), "regimen": g("regimen"),
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


def _formulario(page, cuit: str, impuesto: str, desde: date, hasta: date) -> None:
    sel_cuit = page.locator("select").filter(has=page.locator(f"option[value='{cuit}']"))
    if not sel_cuit.count():
        sel_cuit = page.locator("select").filter(has=page.locator("option", has_text=cuit))
    if not sel_cuit.count():
        raise arca.SinRepresentado(f"Mis Retenciones: {arca.cuit_fmt(cuit)} no figura en 'CUIT del retenido'")
    s = sel_cuit.first
    op = next((o for o in s.locator("option").all_inner_texts() if cuit in o.replace("-", "")), cuit)
    s.select_option(label=op)
    s.dispatch_event("change")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(1200)
    sel_imp = page.locator("select").filter(has=page.locator("option", has_text=re.compile(rf"^\s*{impuesto}\s*-")))
    if not sel_imp.count():
        raise arca.ErrorRobot(f"Mis Retenciones: no está el impuesto {impuesto} en el selector")
    op = next(o for o in sel_imp.first.locator("option").all_inner_texts() if re.match(rf"\s*{impuesto}\s*-", o))
    sel_imp.first.select_option(label=op)
    sel_imp.first.dispatch_event("change")
    # código del impuesto (la caja chica al lado del selector), si está vacía
    page.evaluate("""(imp) => { const s = [...document.querySelectorAll('select')].find(x =>
        [...x.options].some(o => o.text.trim().startsWith(imp + ' -'))); if (!s) return;
        const prev = [...document.querySelectorAll('input[type=text]')].filter(i =>
        i.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_FOLLOWING).pop();
        if (prev && !prev.value) { prev.value = imp; prev.dispatchEvent(new Event('change', {bubbles: true})); } }""", impuesto)
    radio = page.locator("input[type=radio]")
    if radio.count():
        radio.last.check()                              # "Retención y/o Percepción"
    # Fecha Ret./Perc. Desde / Hasta: los dos primeros campos de texto después de ese rótulo
    n = page.evaluate("""(v) => {
      const vis = e => e.offsetParent !== null;
      const rot = [...document.querySelectorAll('td, span, label, div')].find(e => vis(e) && e.children.length === 0
                   && /Fecha.{0,20}ret/i.test(e.textContent));
      if (!rot) return 0;
      const ins = [...document.querySelectorAll('input[type=text], input:not([type])')].filter(i => vis(i)
                   && (rot.compareDocumentPosition(i) & Node.DOCUMENT_POSITION_FOLLOWING)).slice(0, 2);
      ins.forEach((i, k) => { i.value = v[k]; i.dispatchEvent(new Event('change', {bubbles: true})); });
      return ins.length; }""", [desde.strftime("%d%m%Y"), hasta.strftime("%d%m%Y")])
    if n != 2:
        raise arca.ErrorRobot("Mis Retenciones: no se encontraron los campos de Fecha Ret./Perc.")
    page.locator("input[value='CONSULTAR' i], button:has-text('CONSULTAR'), a:has-text('CONSULTAR')").first.click()
    page.wait_for_load_state("domcontentloaded")


def _resultados(page, cuit: str) -> list[dict]:
    """Lee todas las páginas de resultados. [] si ARCA no encontró movimientos."""
    for _ in range(60):
        crudas = page.evaluate(JS_TABLA)
        if crudas:
            break
        texto = page.inner_text("body")
        if re.search(r"no (se encontraron|existen|hay)|sin resultados|no posee", texto, re.I):
            return []
        page.wait_for_timeout(1000)
    else:
        raise arca.ErrorRobot("Mis Retenciones: no aparecieron los resultados de la consulta")
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
        nuevas = [f for f in filas_tabla(page.evaluate(JS_TABLA))
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


def leer(ctx, page, cuit: str, hoy: date) -> dict:
    page = _version_anterior(ctx, page)
    filas, consultas = [], []
    for menu, impuestos in (("Impositivas", IMPUESTOS), ("Aduaneras", IMPUESTOS_ADUANA)):
        for imp in impuestos:
            for d, h in tramos(hoy):
                _menu(page, menu)
                _formulario(page, cuit, imp, d, h)
                r = _resultados(page, cuit)
                for x in r:
                    x["aduana"] = menu == "Aduaneras"
                consultas.append({"menu": menu, "impuesto": imp, "desde": d.isoformat(), "hasta": h.isoformat(),
                                  "renglones": len(r)})
                filas += r
                arca.pausa(0.8, 1.6)
    t = tramos(hoy)
    return {"desde": t[0][0].isoformat(), "hasta": t[-1][1].isoformat(), "consultas": consultas, "filas": filas}


def paso(cuit: str, estado: dict):
    def fn(ctx, portal):
        hoy = date.today()
        antes = set(ctx.pages)
        page = arca.abrir_servicio(ctx, portal, "mis_retenciones")
        try:
            r = leer(ctx, page, cuit, hoy)
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
