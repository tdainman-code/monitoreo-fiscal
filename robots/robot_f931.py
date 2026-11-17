"""Robot F931 (Declaración en Línea): sueldos y cargas sociales de los últimos meses.

Recorrido (relevado el 15/11/2026 con la empresa 30-51969833-8):
  Mis servicios -> sudeclaracion -> avisoInicial.aspx (el encabezado muestra "CUIT: 30-51969833-8")
  consultar/dj_generadas.aspx : lista "Secuencia | Periodo | Cant. de empleados | Fecha de generación ..."
                                Secuencia = "Original (0)", "Rectificativa (1)", ...
  consultar/ver_formulario.aspx?Periodo=AAAAMM&SecDJVig=00N : texto del F931 -> lector_f931
Por cada período se toma la ÚLTIMA secuencia (la vigente). Solo consulta: no genera ni presenta nada.
Si el contribuyente no tiene el servicio (sin empleados), queda anotado "sin servicio".

APODERADOS (relevado con Gaby el 17/11/2026, usuario 20-38893131-1 con varias empresas):
  al entrar abre login/checkIngreso.aspx: "Ud. es apoderado de los siguientes CUITs, por favor seleccione uno
  para comenzar a operar" + desplegable "30-71746863-1 - BH SOLUCIONES EMPRESARIALES". Al elegir pasa a
  avisoInicial.aspx (botón ACEPTAR) / index.aspx y el encabezado muestra "CUIT: 30-71746863-1".
  Si la sesión ya está en otra empresa, el menú INGRESE... tiene "para cambiar el CUIT de sesión", que vuelve
  a la misma lista.
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


def _cuit_encabezado(page) -> str:
    m = re.search(r"CUIT:?\s*(\d{2}-?\d{8}-?\d)", page.inner_text("body")[:1500])
    return re.sub(r"\D", "", m[1]) if m else ""


def _elegir_en_lista(page, cuit: str) -> bool:
    """Pantalla 'Ud. es apoderado de los siguientes CUITs': elige la empresa. Devuelve False si no está la lista."""
    sel = page.locator("select").filter(has=page.locator("option", has_text=arca.cuit_fmt(cuit)))
    if not sel.count():
        if page.locator("select").count() and re.search(r"apoderado", page.inner_text("body"), re.I):
            opciones = page.locator("select").first.locator("option").all_inner_texts()
            raise arca.SinRepresentado(f"Declaración en línea: {arca.cuit_fmt(cuit)} no está entre los CUIT del "
                                       f"apoderado ({'; '.join(o.strip() for o in opciones)})")
        return False
    valor = sel.first.evaluate("(s, c) => [...s.options].find(o => o.text.includes(c)).value", arca.cuit_fmt(cuit))
    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=30_000):
            sel.first.select_option(value=valor)           # el desplegable hace postback al elegir
    except Exception:
        boton = page.locator("input[type=submit], input[type=image], button").filter(
            has_not_text=re.compile(r"cerrar", re.I))
        if boton.count():
            with page.expect_navigation(wait_until="domcontentloaded", timeout=30_000):
                boton.first.click()
    arca.pausa(1.0, 2.0)
    arca.verificar_sesion(page, "declaracion_en_linea")
    return True


def elegir_empresa(page, cuit: str) -> None:
    """Deja la sesión de Declaración en línea en el CUIT del cliente (apoderados con varias empresas)."""
    if _elegir_en_lista(page, cuit):
        return
    _ir(page, BASE + "consultar/dj_generadas.aspx")
    actual = _cuit_encabezado(page)
    if actual == cuit or not actual:
        return
    # sesión en otra empresa: "para cambiar el CUIT de sesión" -> vuelve a la lista de apoderado
    link = page.locator("a").filter(has_text=re.compile(r"cambiar el CUIT", re.I))
    if link.count():
        href = link.first.get_attribute("href") or ""
        if href and not href.startswith("javascript"):
            _ir(page, href if href.startswith("http") else BASE + href.lstrip("./").replace("app/", "", 1))
        else:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=30_000):
                link.first.evaluate("a => a.click()")
    else:
        _ir(page, BASE + "login/checkIngreso.aspx")
    if not _elegir_en_lista(page, cuit):
        raise arca.SinRepresentado(f"Declaración en línea trabaja con {arca.cuit_fmt(actual)} y no se pudo cambiar "
                                   f"a {arca.cuit_fmt(cuit)}")


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
        page.wait_for_load_state("domcontentloaded")
        elegir_empresa(page, cuit)
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
