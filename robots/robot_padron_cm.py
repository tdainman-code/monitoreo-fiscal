"""COMARB · Padrón Web (Convenio Multilateral): constancia de inscripción y jurisdicciones.

Recorrido mostrado por Gabriel el 25/11/2026 con NABAJUMA S.A. (30-71222757-1):
  Portal ARCA -> "Convenio Multilateral - Padrón Web" (padronweb.comarb.gob.ar/padronweb/controller)
  -> SELECCIÓN DE CONTRIBUYENTE: select CUIT ("30712227571 - NABAJUMA S.A.") -> Seleccionar
     -> cartel del navegador "¿Está seguro que desea trabajar con este CUIT?" -> Aceptar
  -> encabezado "30-71222757-1 || Jur. Sede 901 - CAPITAL FEDERAL || NABAJUMA S.A." -> DATOS ACTUALES
  -> Consulta General del Contribuyente (action=ActionMostrarConsultaGral) -> "Constancia de Inscripción"
     (action=ActionImprimirConstanciaInscrip): PDF CInsc_0_-_<fecha>.pdf con Jurisdicción Sede, Tipo de Contribuyente,
     Naturaleza jurídica, Actividades (Tipo, Art., CUAC, Descripción, Alta, Baja) y Jurisdicciones (Alta, Baja).
Si el CUIT no está en la lista, el cliente no está en Convenio Multilateral (o el estudio no tiene la relación).
Solo consulta. Guarda el PDF en la Biblioteca del mes y DATOS/<cuit>/padron_cm/<fecha>.json.
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
arca.SERVICIOS.setdefault("padron_cm", "texto:CONVENIO\\s+MULTILATERAL\\s*-\\s*PADR[OÓ]N\\s+WEB")
NOMBRES = {"901": "CABA", "902": "Buenos Aires", "903": "Catamarca", "904": "Córdoba", "905": "Corrientes", "906": "Chaco",
           "907": "Chubut", "908": "Entre Ríos", "909": "Formosa", "910": "Jujuy", "911": "La Pampa", "912": "La Rioja",
           "913": "Mendoza", "914": "Misiones", "915": "Neuquén", "916": "Río Negro", "917": "Salta", "918": "San Juan",
           "919": "San Luis", "920": "Santa Cruz", "921": "Santa Fe", "922": "Santiago del Estero",
           "923": "Tierra del Fuego", "924": "Tucumán"}


def texto_pdf(crudo: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(crudo)
        f.flush()
        return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, timeout=60).stdout.decode("utf-8", "replace")


def leer_constancia(texto: str) -> dict:
    t = texto.replace("\xa0", " ")
    r = {}
    m = re.search(r"Jurisdicci[oó]n Sede\s*\n.*?(\d{3})\s*-\s*([A-ZÁÉÍÓÚÑ .]+)", t)
    if m:
        r["sede"] = m[1]
    m = re.search(r"Tipo de Contribuyente\s*\n\s*(\d{2}-\d{8}-\d).*?(\S[\w ]*)\s*$", t, re.M)
    if m:
        r["tipo"] = m[2].strip()
    m = re.search(r"Fecha Cierre Ejercicio:\s*\d{4}-(\d{2})-\d{2}", t)
    if m:
        r["mes_cierre"] = int(m[1])
    a = t.find("Jurisdicciones")
    b = t.find("Señor Contribuyente")
    bloque = t[a:b if b > a else None] if a >= 0 else ""
    jur = []
    tokens = re.findall(r"(\d{3})\s*-\s*[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ .]*?(?=\s{2,}|\s*\d{2}/)|(\d{2}/\d{2}/\d{4})", bloque)
    for cod, fecha in tokens:
        if cod:
            jur.append({"codigo": cod, "nombre": NOMBRES.get(cod, cod), "alta": "", "baja": ""})
        elif jur:
            k = "alta" if not jur[-1]["alta"] else "baja"
            if not jur[-1][k]:
                jur[-1][k] = fecha
    r["jurisdicciones"] = jur
    acts = []
    for m in re.finditer(r"^\s*([PS])\s+(\d{3})\s+(\d{6})\s+(.+?)\s{2,}(\d{2}/\d{2}/\d{4})(?:\s+(\d{2}/\d{2}/\d{4}))?\s*$", t, re.M):
        acts.append({"tipo": "Principal" if m[1] == "P" else "Secundaria", "articulo": m[2], "codigo": m[3],
                     "descripcion": m[4].strip(), "alta": m[5], "baja": m[6] or ""})
    r["actividades"] = acts
    return r


def resumen_ficha(r: dict) -> dict:
    activas = [j for j in r.get("jurisdicciones") or [] if not j.get("baja")]
    if not activas:
        return {}
    return {"regimen_iibb": "Convenio Multilateral", "jurisdicciones_iibb": ", ".join(j["nombre"] for j in activas)}


def leer(ctx, portal, cuit: str, hoy: date) -> dict:
    pag = arca.abrir_servicio(ctx, portal, "padron_cm")
    try:
        pag.on("dialog", lambda d: d.accept())          # "¿Está seguro que desea trabajar con este CUIT?"
        sel = pag.locator("select").filter(has=pag.locator("option", has_text=cuit))
        if not sel.count():
            if pag.locator("select").count():
                return {"en_padron": False, "texto": "el CUIT no figura en el Padrón Web de Convenio Multilateral"}
            raise arca.ErrorRobot("Padrón Web: no apareció la selección de contribuyente")
        op = next(o for o in sel.first.locator("option").all_inner_texts() if cuit in o)
        sel.first.select_option(label=op.strip())
        pag.locator("input, button, a").filter(has_text=re.compile(r"^\s*Seleccionar\s*$", re.I)).first.click()
        pag.wait_for_load_state("domcontentloaded")
        pag.wait_for_timeout(2500)
        enc = pag.inner_text("body")
        if arca.cuit_fmt(cuit) not in enc:
            raise arca.CuitEquivocado(f"Padrón Web: no muestra el CUIT {arca.cuit_fmt(cuit)}")
        # 25/11/2026: el texto "Datos Actuales" también está en el <title> invisible del ícono: se va por el enlace
        link_da = pag.locator("a[href*='ConsultaGral']").filter(visible=True)
        if link_da.count():
            link_da.first.click()
        else:
            pag.goto("https://padronweb.comarb.gob.ar/padronweb/controller?action=ActionMostrarConsultaGral",
                     wait_until="domcontentloaded")
        pag.wait_for_load_state("domcontentloaded")
        pag.wait_for_timeout(2000)
        link = pag.locator("a[href*='ConstanciaInscrip'], a:has-text('Constancia de Inscripción')").first
        crudo = None
        try:
            with pag.expect_download(timeout=45_000) as dl:
                link.click()
            with open(dl.value.path(), "rb") as fh:
                crudo = fh.read()
        except Exception:
            nuevas = [p for p in ctx.pages if p is not pag and p is not portal]
            for p in nuevas:                              # el PDF se abrió en otra pestaña
                try:
                    resp = p.request.get(p.url)
                    if resp.body()[:4] == b"%PDF":
                        crudo = resp.body()
                    p.close()
                except Exception:
                    pass
        if not crudo or crudo[:4] != b"%PDF":
            raise arca.ErrorRobot("Padrón Web: no bajó la Constancia de Inscripción en PDF")
        per = hoy.strftime("%Y-%m")
        bib.guardar_archivo(cuit, per, "constancia_cm", f"constancia_inscripcion_CM_{cuit}_{hoy.isoformat()}.pdf", crudo)
        m = re.search(r"Jur\.\s*Sede\s*(\d{3})", enc)
        r = {"en_padron": True, **leer_constancia(texto_pdf(crudo))}
        r.setdefault("sede", m[1] if m else "")
        return r
    finally:
        pag.close()


def paso(cuit: str, estado: dict):
    def fn(ctx, portal):
        hoy = date.today()
        r = leer(ctx, portal, cuit, hoy)
        r.update(cuit=cuit, fecha=hoy.isoformat())
        r["ficha"] = resumen_ficha(r)
        d = os.path.join(DATOS, cuit, "padron_cm")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{hoy.isoformat()}.json"), "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        estado.update(resultado=("OK: " + (r["ficha"].get("jurisdicciones_iibb") or "sin jurisdicciones activas"))
                      if r.get("en_padron") else "no está en Convenio Multilateral")
        return "OK"
    return fn


def correr(cuit, periodo, usuario, clave, metodo="Directo", visible=False, **_):
    estado: dict = {}
    arca.ejecutar(usuario, clave, [("padron_cm", paso(cuit, estado))], os.path.join(DATOS, cuit, "capturas"), visible)
    return {"cuit": cuit, "padron_cm": estado.get("resultado"), "archivos": {"padron_cm": {"alertas": []}}}
