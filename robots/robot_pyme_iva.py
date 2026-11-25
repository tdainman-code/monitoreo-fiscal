"""ARCA · F.1272 PYMES (categorización y beneficios): ¿tiene el IVA a 90 días (pago diferido)?

Recorrido mostrado por Gabriel el 25/11/2026 con NABAJUMA S.A. (30-71222757-1):
  Portal ARCA -> "PYMES Solicitud de Categorización y/o Beneficios" (fenix.cloud.afip.gob.ar/fenix/fenix_f1272/app)
  -> Búsqueda: lista "CUIT/s" (TODOS / 20242125062 - … / 30712227571 - NABAJUMA S.A.) -> ACEPTAR
  -> tabla: ACCIONES | CUIT | EST. | FORMULARIO | PERÍODO FISCAL | ESTADO (Presentado) | FECHA ÚLTIMA MODIFICACIÓN | USUARIO
  -> en la fila del período más nuevo, "Acciones" -> ver el formulario
  -> solapa "Datos Informativos", bloque "Solicitud de Beneficios":
     "¿Solicita el beneficio del Pago del I.V.A. en forma diferida?"  Sí / No   <- IVA a 90 días
Solo consulta. Resultado: DATOS/<cuit>/pyme/<fecha>.json; la web lo pasa a la ficha ("IVA a 90 días").
"""
from __future__ import annotations

import json
import os
import re
from datetime import date

from . import arca

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
arca.SERVICIOS.setdefault("pymes_f1272", "texto:PYMES\\s+SOLICITUD\\s+DE\\s+CATEGORIZACI[OÓ]N")

JS_FILAS = r"""() => [...document.querySelectorAll('tr')].map(r => [...r.cells].map(c => c.innerText.replace(/\s+/g, ' ').trim()))
                    .filter(c => c.length >= 6)"""


def leer_beneficio(texto: str) -> bool | None:
    m = re.search(r"Pago del I\.?V\.?A\.? en forma diferida\??\s*[:\n\t ]*\s*(S[IÍ]|NO)\b", texto, re.I)
    return None if not m else m[1].upper().startswith("S")


def filas_presentadas(filas: list[list[str]], cuit: str) -> list[dict]:
    out = []
    for f in filas:
        anio = next((c for c in f if re.fullmatch(r"20\d{2}", c)), "")
        if cuit in f and anio:
            out.append({"periodo": anio, "estado": next((c for c in f if re.search(r"Presentad|Borrador|Anulad", c, re.I)), ""),
                        "fecha": next((c for c in f if re.fullmatch(r"\d{2}-\d{2}-\d{4}.*", c)), "")})
    return sorted(out, key=lambda x: x["periodo"], reverse=True)


def leer(ctx, portal, cuit: str) -> dict:
    pag = arca.abrir_servicio(ctx, portal, "pymes_f1272")
    try:
        lista = pag.locator("select").filter(has=pag.locator("option", has_text=cuit))
        if not lista.count():
            return {"tiene_f1272": False, "texto": "el CUIT no figura en el F.1272 (sin categorización PyME)"}
        op = next(o for o in lista.first.locator("option").all_inner_texts() if cuit in o)
        lista.first.select_option(label=op.strip())
        pag.locator("button, a, input, div").filter(has_text=re.compile(r"^\s*ACEPTAR\s*$", re.I)).locator("visible=true").first.click()
        pag.wait_for_timeout(4000)
        filas = filas_presentadas(pag.evaluate(JS_FILAS), cuit)
        if not filas:
            return {"tiene_f1272": False, "texto": "sin formularios F.1272 presentados"}
        ult = next((f for f in filas if re.search(r"Presentad", f["estado"], re.I)), filas[0])
        fila = pag.locator("tr").filter(has_text=cuit).filter(has_text=re.compile(rf"\b{ult['periodo']}\b"))
        acc = fila.first.locator("select, [class*=combo], input, a, button").filter(visible=True)
        if acc.count():
            el = acc.first
            if el.evaluate("e => e.tagName") == "SELECT":
                ops = el.locator("option").all_inner_texts()
                el.select_option(label=next((o for o in ops if re.search(r"ver|consult|visualiz", o, re.I)), ops[-1]).strip())
            else:
                el.click()
                pag.wait_for_timeout(800)
                pag.get_by_text(re.compile(r"^\s*(Ver|Consultar|Visualizar)\b", re.I)).locator("visible=true").first.click()
        else:
            fila.first.dblclick()
        pag.get_by_text(re.compile(r"forma diferida", re.I)).first.wait_for(timeout=45_000)
        texto = pag.inner_text("body")
        return {"tiene_f1272": True, "periodo": ult["periodo"], "estado": ult["estado"], "presentado": ult["fecha"],
                "iva_diferido": leer_beneficio(texto), "formularios": filas}
    finally:
        pag.close()


def paso(cuit: str, estado: dict):
    def fn(ctx, portal):
        hoy = date.today()
        r = leer(ctx, portal, cuit)
        r.update(cuit=cuit, fecha=hoy.isoformat())
        d = os.path.join(DATOS, cuit, "pyme")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{hoy.isoformat()}.json"), "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        iv = r.get("iva_diferido")
        estado.update(resultado=("IVA a 90 días: " + ("SÍ" if iv else "no" if iv is False else "no se pudo leer")
                                 + f" (F.1272 {r.get('periodo')})") if r.get("tiene_f1272") else r.get("texto", ""))
        return "OK"
    return fn


def correr(cuit, periodo, usuario, clave, metodo="Directo", visible=False, **_):
    estado: dict = {}
    arca.ejecutar(usuario, clave, [("pyme_iva", paso(cuit, estado))], os.path.join(DATOS, cuit, "capturas"), visible)
    return {"cuit": cuit, "pyme_iva": estado.get("resultado"), "archivos": {"pyme_iva": {"alertas": []}}}
