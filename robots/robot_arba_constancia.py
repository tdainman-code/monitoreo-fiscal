"""ARBA: Constancia de Inscripción de Ingresos Brutos (PDF) y datos para la ficha.

Recorrido mostrado por Gabriel el 25/11/2026 (GONCALVES VICENTE JUAN JOSE, 20-33116278-8):
  Autogestión -> Mis accesos frecuentes -> Ingresos Brutos -> "Constancia de inscripción"
  -> app.arba.gov.ar/WebConstancias/seguridad/Constancia.do  (menú: Solicitar Constancia de IB | Contactenos | Salir)
  -> "Solicitar Constancia de IB" -> presentarConstancia.do  "INGRESOS BRUTOS - Constancia de Inscripción":
     CUIT/CUIL/CDI, N° Transacción, Denominación, Distrito, Régimen de Pago (MENSUAL), Tipo de contribuyente
     (CENTRALIZADO), Inicio de Actividades, Convenio, leyenda "Contribuyente directo de la Provincia de Buenos Aires",
     actividades, domicilios -> botones Volver | Imprimir
  -> Imprimir abre generarConstanciaPDF.do en el visor de PDF del navegador: el robot toma el PDF de esa respuesta.
Solo consulta. El PDF va a la Biblioteca del mes (fuente "constancia_arba"); los datos a DATOS/<cuit>/arba_constancia/.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date

from . import arca, biblioteca_archivos as bib

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")

JS_CAMPOS = r"""() => {
  const out = {};
  document.querySelectorAll('input, textarea').forEach(i => {
    const td = i.closest('td'); let et = '';
    if (td && td.previousElementSibling) et = td.previousElementSibling.innerText;
    if (!et) { const l = i.closest('tr, div'); et = l ? (l.innerText || '').split('\n')[0] : ''; }
    et = (et || '').replace(/\s+/g, ' ').trim();
    if (et && i.value && !(et in out)) out[et] = i.value.trim();
  });
  return out;
}"""


def leer_campos(campos: dict, texto: str) -> dict:
    g = lambda pat: next((v for k, v in campos.items() if re.search(pat, k, re.I)), "")
    r = {"regimen_pago": g(r"R[eé]gimen de Pago"), "tipo": g(r"Tipo de contribuyente"), "convenio": g(r"^Convenio"),
         "inicio": g(r"Inicio de Actividades"), "distrito": g(r"Distrito"), "transaccion": g(r"Transacci")}
    r["directo"] = bool(re.search(r"Contribuyente directo de la Provincia", texto, re.I))
    r["convenio_multilateral"] = bool(r["convenio"].strip()) or bool(re.search(r"Convenio Multilateral", texto, re.I))
    return r


def resumen_ficha(r: dict) -> dict:
    if r.get("convenio_multilateral"):
        return {"regimen_iibb": "Convenio Multilateral"}
    if r.get("directo"):
        return {"regimen_iibb": "Local", "jurisdicciones_iibb": "Buenos Aires"}
    return {}


def bajar(ctx, page, cuit: str, hoy: date | None = None) -> dict:
    """page = Autogestión de ARBA. Devuelve los datos leídos (y guarda el PDF si lo pudo tomar)."""
    hoy = hoy or date.today()
    link = page.get_by_text(re.compile(r"^\s*Constancia de inscripci[oó]n\s*$", re.I)).locator("visible=true")
    if not link.count():
        for t in (r"^\s*Mis accesos frecuentes\s*$", r"^\s*Ingresos Brutos\s*$"):
            x = page.get_by_text(re.compile(t, re.I)).locator("visible=true")
            if x.count():
                x.last.click()
                page.wait_for_timeout(1000)
        link = page.get_by_text(re.compile(r"^\s*Constancia de inscripci[oó]n\s*$", re.I)).locator("visible=true")
    if not link.count():
        raise arca.ErrorRobot("ARBA: no aparece 'Constancia de inscripción' (Mis accesos frecuentes -> Ingresos Brutos)")
    antes = set(ctx.pages)
    link.first.click()
    page.wait_for_timeout(3000)
    nuevas = [p for p in ctx.pages if p not in antes]
    c = nuevas[-1] if nuevas else page
    c.wait_for_load_state("domcontentloaded")
    c.get_by_text(re.compile(r"Solicitar Constancia de IB", re.I)).first.click()
    c.wait_for_load_state("domcontentloaded")
    c.get_by_text(re.compile(r"Constancia de Inscripci[oó]n", re.I)).first.wait_for(timeout=45_000)
    texto = c.inner_text("body")
    if arca.cuit_fmt(cuit) not in texto and cuit not in texto:
        raise arca.CuitEquivocado(f"ARBA Constancia: no muestra el CUIT {arca.cuit_fmt(cuit)}")
    r = leer_campos(c.evaluate(JS_CAMPOS), texto)
    pdf: dict = {}

    def al_responder(resp):
        if "generarConstanciaPDF" in resp.url and "b" not in pdf:
            try:
                b = resp.body()
                if b[:4] == b"%PDF":
                    pdf["b"] = b
            except Exception:
                pass

    def al_descargar(dl):
        try:
            pdf.setdefault("b", open(dl.path(), "rb").read())
        except Exception:
            pass
    ctx.on("response", al_responder)
    c.on("download", al_descargar)
    try:
        antes = set(ctx.pages)
        c.locator("input[value='Imprimir' i], button:has-text('Imprimir'), a:has-text('Imprimir')").first.click()
        for _ in range(40):
            if "b" in pdf:
                break
            c.wait_for_timeout(500)
        for p in ctx.pages:
            if p not in antes:
                try:
                    p.close()
                except Exception:
                    pass
    finally:
        ctx.remove_listener("response", al_responder)
    if pdf.get("b"):
        bib.guardar_archivo(cuit, hoy.strftime("%Y-%m"), "constancia_arba",
                            f"constancia_inscripcion_IIBB_ARBA_{cuit}_{hoy.isoformat()}.pdf", pdf["b"])
    r.update(cuit=cuit, fecha=hoy.isoformat(), pdf=bool(pdf.get("b")))
    r["ficha"] = resumen_ficha(r)
    d = os.path.join(DATOS, cuit, "arba_constancia")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{hoy.isoformat()}.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    if c is not page:
        c.close()
    return r
