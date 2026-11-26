"""AGIP (CABA): Constancia de Inscripción de Ingresos Brutos (PDF) y régimen para la ficha.

Recorrido mostrado por Gabriel el 25/11/2026 (GARBUGLIA ALEJANDRA CARLA, 27-27137058-5):
  Clave Ciudad -> menú principal (claveciudad.agip.gob.ar/menu_principal.php) -> tarjeta "Ingresos Brutos"
  ("Portal de consultas y trámites de IIBB") -> ventana nueva gitweb.agip.gob.ar/GITP/home.jsf
  "Sistema de Gestión Integral Tributaria" -> menú izquierdo "Ingresos Brutos" ->
  "Impresión y Re-Impresión de Constancia de Inscripción ISIB" -> "Selección de Persona":
     CUIT / CUIL representante [27]-[27137058]-[5]   CUIT / CUIL personal [..]-[........]-[.]  -> lupa
  -> PDF gitweb.agip.gob.ar/GITP/download/<id>.pdf  "Impuesto sobre los Ingresos Brutos - Constancia de Inscripción":
     Titular, Datos básicos (Tipo, Categoría), Domicilios, "Vigente / Ultima Categoría Registrada: ISIB-RG  Estado: ACTIVO",
     actividades e "Historial de Tramos Registrados" (ISIB-RG régimen general, ISIB-RS régimen simplificado).
Solo consulta. PDF a la Biblioteca del mes (fuente "constancia_agip"); datos en DATOS/<cuit>/agip_constancia/.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import date

from . import arca, biblioteca_archivos as bib

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")


def texto_pdf(crudo: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(crudo)
        f.flush()
        return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, timeout=60).stdout.decode("utf-8", "replace")


def leer_constancia(texto: str) -> dict:
    t = texto.replace("\xa0", " ")
    r = {}
    m = re.search(r"Nro\. de CUIT\s+(\d{2}-\d{8}-\d)", t)
    r["cuit"] = re.sub(r"\D", "", m[1]) if m else ""
    m = re.search(r"Vigente\s*/\s*Ultima Categor[ií]a Registrada:\s*(\S+)\s+Estado:\s*(\w+)", t, re.I)
    r["categoria"], r["estado"] = (m[1], m[2]) if m else ("", "")
    m = re.search(r"Categor[ií]a:\s+(\w+)", t)
    r["segmento"] = m[1] if m else ""
    r["actividades"] = [{"tipo": a, "codigo": c, "descripcion": d.strip()}
                        for a, c, d in re.findall(r"Actividad (Principal|Secundaria)\s+(\d{6})\s+(.+)", t)]
    r["tramos"] = [{"regimen": g, "desde": d, "hasta": h, "inscripcion": (i or "").strip()}
                   for g, d, h, i in re.findall(r"^\s*(ISIB-\w+|CM\w*)\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s*(\d[\d -]*)?\s*$", t, re.M)]
    return r


def resumen_ficha(r: dict) -> dict:
    cat, est = (r.get("categoria") or "").upper(), (r.get("estado") or "").upper()
    if est and est != "ACTIVO":
        return {}
    if cat.startswith("ISIB-RS"):
        return {"regimen_iibb": "Régimen simplificado", "jurisdicciones_iibb": "CABA"}
    if cat.startswith("ISIB"):
        return {"regimen_iibb": "Local", "jurisdicciones_iibb": "CABA"}
    if "CM" in cat or "CONVENIO" in cat:
        return {"regimen_iibb": "Convenio Multilateral"}
    return {}


def _cuit_en_campos(pag, campos, cuit: str) -> None:
    for c, v in zip(campos, (cuit[:2], cuit[2:10], cuit[10])):
        if c.is_editable():
            c.fill(v)


def bajar(ctx, page, cuit: str, hoy: date | None = None) -> dict:
    """page = menú principal de Clave Ciudad (con el representado ya elegido)."""
    hoy = hoy or date.today()
    tarjeta = page.get_by_text(re.compile(r"^\s*Ingresos Brutos\s*$", re.I)).locator("visible=true")
    if not tarjeta.count():
        from .robot_agip import _cambiar_representado   # las tarjetas dependen del representado elegido arriba
        if _cambiar_representado(page, None):
            tarjeta = page.get_by_text(re.compile(r"^\s*Ingresos Brutos\s*$", re.I)).locator("visible=true")
    if not tarjeta.count():
        tarjeta = page.locator("a, div, h3, h4, span").filter(has_text=re.compile(r"Portal de consultas y tr[aá]mites de IIBB", re.I))
    if not tarjeta.count():
        raise arca.ErrorRobot(f"AGIP: no aparece la tarjeta 'Ingresos Brutos' en el menú de Clave Ciudad (página: {page.url[:80]})")
    antes = set(ctx.pages)
    tarjeta.first.click()
    page.wait_for_timeout(4000)
    nuevas = [p for p in ctx.pages if p not in antes]
    git = nuevas[-1] if nuevas else page
    try:
        git.wait_for_load_state("load", timeout=60_000)
    except Exception:
        pass
    git.wait_for_timeout(2000)
    try:
        t0 = git.inner_text("body", timeout=20_000)[:2000]
    except Exception:
        t0 = ""
    if re.search(r"Seleccione\s+Representado", t0, re.I):
        from .robot_agip import _elegir_cuit          # NOMBRE [cuit] -> Ingresar (igual que Gestión-AR)
        _elegir_cuit(git, cuit)
        nuevas = [p for p in ctx.pages if p not in antes and p is not git]
        if nuevas:
            git = nuevas[-1]
            git.wait_for_load_state("domcontentloaded")
    git.get_by_text(re.compile(r"Gesti[oó]n Integral Tributaria", re.I)).first.wait_for(timeout=45_000)
    item = git.get_by_text(re.compile(r"Impresi[oó]n y Re-Impresi[oó]n de Constancia", re.I)).locator("visible=true")
    if not item.count():
        m = git.get_by_text(re.compile(r"^\s*Ingresos Brutos\s*$", re.I)).locator("visible=true")
        if m.count():
            m.first.click()
            git.wait_for_timeout(1000)
        item = git.get_by_text(re.compile(r"Impresi[oó]n y Re-Impresi[oó]n de Constancia", re.I)).locator("visible=true")
    item.first.click()
    git.get_by_text(re.compile(r"Selecci[oó]n de Persona", re.I)).first.wait_for(timeout=45_000)
    git.wait_for_timeout(1500)
    # los tres cuadritos de "CUIT / CUIL personal" (los segundos tres): si se pueden escribir, va el CUIT del cliente
    cajas = git.locator("input[type=text], input:not([type])").filter(visible=True)
    if cajas.count() >= 6:
        _cuit_en_campos(git, [cajas.nth(i) for i in (3, 4, 5)], cuit)
    pdf: dict = {}

    def al_responder(resp):
        if "/GITP/download/" in resp.url and "b" not in pdf:
            try:
                b = resp.body()
                if b[:4] == b"%PDF":
                    pdf["b"] = b
            except Exception:
                pass
    ctx.on("response", al_responder)
    try:
        antes = set(ctx.pages)
        lupa = git.locator("img[src*='lupa' i], img[src*='search' i], img[title*='uscar' i], a[title*='uscar' i], "
                           "input[type=image], button[title*='uscar' i]").filter(visible=True)
        if not lupa.count():
            raise arca.ErrorRobot("AGIP constancia: no aparece la lupa de 'Selección de Persona'")
        lupa.first.click()
        for _ in range(60):
            if "b" in pdf:
                break
            git.wait_for_timeout(500)
        if "b" not in pdf:                                  # el PDF quedó en una pestaña: se pide de nuevo por su URL
            for p in ctx.pages:
                if p not in antes and "/GITP/download/" in p.url:
                    try:
                        b = p.request.get(p.url).body()
                        if b[:4] == b"%PDF":
                            pdf["b"] = b
                    except Exception:
                        pass
        for p in ctx.pages:
            if p not in antes:
                try:
                    p.close()
                except Exception:
                    pass
    finally:
        ctx.remove_listener("response", al_responder)
    if not pdf.get("b"):
        raise arca.ErrorRobot("AGIP constancia: no bajó el PDF")
    r = leer_constancia(texto_pdf(pdf["b"]))
    if r.get("cuit") and r["cuit"] != cuit:
        raise arca.CuitEquivocado(f"AGIP constancia: el PDF es de {r['cuit']}, no de {cuit}")
    bib.guardar_archivo(cuit, hoy.strftime("%Y-%m"), "constancia_agip",
                        f"constancia_inscripcion_IIBB_AGIP_{cuit}_{hoy.isoformat()}.pdf", pdf["b"])
    r.update(cuit=cuit, fecha=hoy.isoformat())
    r["ficha"] = resumen_ficha(r)
    d = os.path.join(DATOS, cuit, "agip_constancia")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{hoy.isoformat()}.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    if git is not page:
        git.close()
    return r
