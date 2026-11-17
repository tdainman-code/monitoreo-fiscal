"""Robot F931 (Declaración en Línea): sueldos y cargas sociales de los últimos meses.

Recorrido (relevado el 15/11/2026 con la empresa 30-51969833-8):
  Mis servicios -> sudeclaracion -> avisoInicial.aspx (el encabezado muestra "CUIT: 30-51969833-8")
  consultar/dj_generadas.aspx : lista "Secuencia | Periodo | Cant. de empleados | Fecha de generación ..."
                                Secuencia = "Original (0)", "Rectificativa (1)", ...
  consultar/ver_formulario.aspx?Periodo=AAAAMM&SecDJVig=00N : texto del F931 -> lector_f931
Por cada período se toma la ÚLTIMA secuencia (la vigente). Solo consulta: no genera ni presenta nada.
Si el contribuyente no tiene el servicio (sin empleados), queda anotado "sin servicio".
"""
from __future__ import annotations

import json
import os
import re

from . import arca
from .lector_f931 import leer_f931

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
BASE = "https://serviciossegsoc.afip.gob.ar/djproforma/app/"


def _ir(page, url):
    page.goto(url, wait_until="domcontentloaded")
    arca.pausa(1.0, 2.5)
    arca.verificar_sesion(page, "declaracion_en_linea")


def _controlar_cuit(page, cuit):
    texto = page.inner_text("body")[:1500]
    m = re.search(r"CUIT:?\s*(\d{2}-?\d{8}-?\d)", texto)
    if not m:
        raise arca.ErrorRobot("Declaración en línea: no se ve el CUIT en el encabezado")
    if re.sub(r"\D", "", m[1]) != cuit:
        raise arca.SinRepresentado(f"Declaración en línea trabaja con {m[1]} y no con {arca.cuit_fmt(cuit)} "
                                   "(hay que cambiar el CUIT de sesión; pantalla a relevar)")


def lista_dj(page) -> dict[str, int]:
    """{'2026-10': secuencia vigente, ...}"""
    filas = page.evaluate("""() => [...document.querySelectorAll('table tr')].map(r =>
        [...r.cells].map(c => c.textContent.replace(/\\s+/g, ' ').trim()))""")
    out: dict[str, int] = {}
    for c in filas:
        if len(c) < 3:
            continue
        ms = re.match(r"(Original|Rectificativa)\s*\((\d+)\)", c[0])
        mp = re.fullmatch(r"(\d{2})/(\d{4})", c[1])
        if ms and mp:
            per = f"{mp[2]}-{mp[1]}"
            out[per] = max(out.get(per, -1), int(ms[2]))
    return out


def paso(cuit: str, periodos: list[str], estado: dict, forzar: bool = False):
    carpeta = os.path.join(DATOS, cuit, "f931")

    def fn(ctx, portal):
        try:
            page = arca.abrir_servicio(ctx, portal, "declaracion_en_linea")
        except arca.RequiereIntervencion:
            estado["_servicio"] = "sin servicio (no habilitado)"
            return dict(estado)
        _ir(page, BASE + "consultar/dj_generadas.aspx")
        _controlar_cuit(page, cuit)
        vigentes = lista_dj(page)
        os.makedirs(carpeta, exist_ok=True)
        for per in periodos:
            if per in estado:
                continue
            ruta = os.path.join(carpeta, f"{per}.json")
            if per not in vigentes:
                estado[per] = "sin DJ"
                continue
            if os.path.exists(ruta) and not forzar:
                with open(ruta, encoding="utf-8") as f:
                    if json.load(f).get("Secuencia") == vigentes[per]:
                        estado[per] = "ya bajado"
                        continue
            _ir(page, BASE + f"consultar/ver_formulario.aspx?Periodo={per.replace('-', '')}&SecDJVig={vigentes[per]:03d}")
            texto = page.inner_text("body")
            try:
                d = leer_f931(texto)
            except Exception as e:
                with open(os.path.join(carpeta, f"{per}_no_leido.txt"), "w", encoding="utf-8") as f:
                    f.write(texto)
                estado[per] = f"no se pudo leer ({e})"
                continue
            if re.sub(r"\D", "", d["CUIT"]) != cuit:
                raise arca.CuitEquivocado(f"F931 {per}: el formulario es del CUIT {d['CUIT']}")
            if d.get("Periodo") and d["Periodo"] != per:
                raise arca.ErrorRobot(f"F931: se pidió {per} y el formulario es de {d['Periodo']}")
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            estado[per] = "OK"
            arca.pausa(1.5, 3.0)
        page.close()
        return dict(estado)
    return fn


def correr(cuit, periodo, usuario, clave, metodo="Directo", visible=False, periodos=None, **_):
    periodos = periodos or ([periodo] if periodo else arca.periodos_ultimos(12))
    estado: dict = {}
    r = arca.ejecutar(usuario, clave, [("f931", paso(cuit, periodos, estado))],
                      os.path.join(DATOS, cuit, "capturas"), visible)
    return {"cuit": cuit, "periodos": estado, "reingresos": r["_reingresos"], "archivos": {"f931": {"alertas": []}}}
