"""Robot ARCA: fiscalizaciones y verificaciones en curso (traído de Radar fiscal, 17/11/2026).

Servicios (por el título de la tarjeta en "Mis servicios"; los nombres se VERIFICAN en la primera corrida real con
las capturas que quedan en DATOS/<cuit>/capturas):
  Fiscalización Electrónica                 -> requerimientos / fiscalizaciones electrónicas
  Consulta de Órdenes de Intervención       -> OI en curso (número, estado, inspector, supervisor, impuestos)
  SIACE (controles electrónicos)            -> acciones de control electrónico
Solo se LEEN las tablas. No se abre ningún requerimiento ni se responde nada.
Si el contribuyente no tiene el servicio habilitado, se anota "sin servicio" (es lo normal: sin fiscalizaciones).

Resultado: DATOS/<cuit>/fiscalizaciones/<fecha>.json
  {"cuit","fecha","en_curso":[filas], "verificaciones":[filas], "siace":[filas], "tablas":{servicio:[...]},
   "servicios":{servicio: estado}, "alertas":[...]}
"""
from __future__ import annotations

import json
import os
import re
from datetime import date

from . import arca
from .robot_situacion_fiscal import JS_TABLA, _controlar_cuit

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
SERVICIOS = [("fiscalizacion_electronica", "Fiscalización Electrónica"),
             ("ordenes_intervencion", "Órdenes de Intervención"),
             ("siace", "SIACE")]
FINALIZADA = re.compile(r"finaliz|cerrad|conclu|archiv|cumplid|respondid|resuelt|anulad|sin efecto|baja", re.I)


def _tablas(page) -> list[dict]:
    out = []
    for fr in [page] + [f for f in page.frames if f != page.main_frame]:
        try:
            tablas = fr.locator("table").all()
        except Exception:
            continue
        for t in tablas:
            try:
                if not t.is_visible():
                    continue
                d = t.evaluate(JS_TABLA)
            except Exception:
                continue
            filas = [f["celdas"] for f in d["filas"] if any(c for c in f["celdas"])]
            if d["encabezados"] and filas and not re.search(r"no (hay|se encontraron|existen)", " ".join(filas[0]), re.I):
                out.append({"encabezados": d["encabezados"], "filas": filas})
    return out


def _como_dicts(tablas: list[dict]) -> list[dict]:
    return [dict(zip(t["encabezados"], f)) for t in tablas for f in t["filas"]]


def _estado(d: dict) -> str:
    return next((v for k, v in d.items() if re.search(r"estado|situaci", k, re.I)), "")


def abiertas(filas: list[dict]) -> list[dict]:
    """Solo cuenta como ABIERTA una fila que tiene columna de estado/situación con un valor que no esté
    finalizado. Filas sin estado (menús, historial, tablas de ayuda) NO se cuentan (17/11/2026: BH
    figuraba con 2 'controles' que eran filas sin estado de la pantalla de SIACE)."""
    return [f for f in filas if _estado(f).strip() and not FINALIZADA.search(_estado(f))]


def _abrir_si_existe(ctx, portal, clave):
    """Abre el servicio solo si su tarjeta está en "Mis servicios" (sin esperar: la mayoría de los clientes
    no tiene fiscalizaciones y el servicio directamente no aparece)."""
    import re as _re
    ident = arca.SERVICIOS[clave][6:]
    portal.goto(arca.URL_MIS_SERVICIOS, wait_until="domcontentloaded")
    arca.pausa(1.0, 2.0)
    arca.verificar_sesion(portal, "portal")
    try:
        portal.locator("a[role=button]").first.wait_for(state="attached", timeout=15_000)
    except Exception:
        return None
    titulos = portal.locator("a[role=button] h3").all_inner_texts()
    if not any(_re.search(ident, t, _re.I) for t in titulos):
        return None
    return arca.abrir_servicio(ctx, portal, clave)


def paso(cuit: str, estado: dict):
    def fn(ctx, portal):
        hoy = date.today().isoformat()
        r = {"cuit": cuit, "fecha": hoy, "en_curso": [], "verificaciones": [], "siace": [], "fiscalizacion_electronica": [],
             "tablas": {}, "servicios": {}, "alertas": []}
        for clave, nombre in SERVICIOS:
            try:
                page = _abrir_si_existe(ctx, portal, clave)
            except arca.SesionPerdida:
                raise
            except Exception as e:                       # servicio no habilitado / nombre a verificar: no frena la corrida
                r["servicios"][clave] = f"sin servicio ({type(e).__name__})"
                continue
            if page is None:
                r["servicios"][clave] = "sin servicio"
                continue
            try:
                arca.elegir_representado(page, cuit)
                page.wait_for_load_state("domcontentloaded")
                arca.pausa(1.5, 2.5)
                try:
                    _controlar_cuit(page.inner_text("body"), cuit, nombre)
                except arca.SinRepresentado:
                    raise
                except Exception:
                    pass                                  # algunas pantallas no muestran el CUIT: se lee igual
                tablas = _tablas(page)
                r["tablas"][clave] = tablas
                filas = _como_dicts(tablas)
                if clave == "ordenes_intervencion":
                    r["en_curso"] = abiertas(filas)
                    r["verificaciones"] = [f for f in filas if re.search(r"verific", " ".join(f.values()), re.I)]
                elif clave == "siace":
                    r["siace"] = abiertas(filas)
                else:
                    r["fiscalizacion_electronica"] = abiertas(filas)
                r["servicios"][clave] = f"OK ({len(filas)} filas leídas, {len(abiertas(filas))} abiertas)"
            finally:
                page.close()
            arca.pausa()
        if r["en_curso"]:
            r["alertas"].append({"prioridad": "ALTA", "tipo": "Fiscalización en curso",
                                 "texto": f"{len(r['en_curso'])} orden(es) de intervención abiertas en ARCA"})
        if r["fiscalizacion_electronica"]:
            r["alertas"].append({"prioridad": "ALTA", "tipo": "Fiscalización electrónica",
                                 "texto": f"{len(r['fiscalizacion_electronica'])} requerimiento(s) abiertos en ARCA"})
        if r["siace"]:
            r["alertas"].append({"prioridad": "ALTA", "tipo": "Control electrónico (SIACE)",
                                 "texto": f"{len(r['siace'])} acción(es) de control electrónico"})
        carpeta = os.path.join(DATOS, cuit, "fiscalizaciones")
        os.makedirs(carpeta, exist_ok=True)
        with open(os.path.join(carpeta, f"{hoy}.json"), "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        estado.update(servicios=r["servicios"], alertas=r["alertas"])
        return "OK"
    return fn


def correr(cuit, periodo, usuario, clave, metodo="Directo", visible=False, **_):
    estado: dict = {}
    r = arca.ejecutar(usuario, clave, [("fiscalizaciones", paso(cuit, estado))], os.path.join(DATOS, cuit, "capturas"),
                      visible)
    return {"cuit": cuit, "fiscalizaciones": estado.get("servicios", {}), "reingresos": r["_reingresos"],
            "archivos": {"fiscalizaciones": {"alertas": estado.get("alertas", [])}}}
