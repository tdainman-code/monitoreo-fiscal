"""Mis Facilidades: TODOS los planes (vigentes, caducos, anulados, cancelados) con sus obligaciones y sus pagos.

Gaby, 26/11/2026 (Nabajuma): lista seguimiento_presentacion.aspx (Presentación | Número | Cuotas | Tipo | Consolidado |
Estado | Situación | Detalle; paginada abajo a la derecha: se lee con textContent, así entran todas las páginas) ->
Detalle -> SeguimientoPlanEnviado/<id>:
   - obligaciones incluidas: SeguimientoDetalleDeuda/<id>  (Año | Mes | Ant/Cta | Establ. | Imp. | Cpto. | Subcpto. |
     Fecha Vto. | Deuda Complementaria | Monto Obligación | Total Pagos Imputados | Saldo a Cancelar)
   - cronograma: SeguimientoDetallePlanPago/<id>
   - pagos: SeguimientoDetallePagos/<id>?estado=0  (Cuota N° | Capital | Interés Financiero | Interés Resarcitorio |
     Total | Fecha Venc. | Pago | Estado de Cuota)
Se va directo por las direcciones de cada plan (al volver a la lista, ARCA vuelve a la página 1).
Solo consulta. DATOS/<cuit>/planes_todos/<fecha>.json; de ahí sale la deuda al cierre del balance (deuda_cierre).
"""
from __future__ import annotations

import json
import os
from datetime import date

from . import arca
from . import lector_situacion as ls
from . import robot_situacion_fiscal as rsf

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")


def leer(ctx, portal, cuit: str, hoy: date) -> dict:
    page = arca.abrir_servicio(ctx, portal, "mis_facilidades")
    try:
        page.wait_for_load_state("domcontentloaded")
        rsf._elegir_cuit_mf(page, cuit)
        rsf._controlar_cuit(page.inner_text("body"), cuit, "Mis Facilidades")
        rsf.USUARIO_ACTUAL["cliente"] = cuit
        lista = rsf._tabla_por_texto(page, "Consolidado")
        planes = ls.leer_lista_planes(lista)
        detalle = {}
        vistas: dict = {}
        for p in planes:
            try:
                id_ = rsf._abrir_detalle(page, p["numero"])
                d = {"id": id_}
                for clave, url, marca, tid in (
                        ("obligaciones", f"SeguimientoDetalleDeuda/{id_}", "Saldo a Cancelar", None),
                        ("cronograma", f"SeguimientoDetallePlanPago/{id_}", "Fecha Vencimiento", "tableDetallePlanPago"),
                        ("pagos", f"SeguimientoDetallePagos/{id_}?estado=0", "Estado de Cuota", "tableDetallePagos")):
                    rsf._ir(page, rsf.BASE_MF + url)
                    rsf._controlar_cuit(page.inner_text("body"), cuit, "Mis Facilidades")
                    try:
                        d[clave] = rsf._tabla_por_texto(page, marca, tid)
                    except arca.ErrorRobot:
                        d[clave] = {"encabezados": [], "filas": []}      # plan anulado: puede no tener cronograma
                    if clave == "obligaciones" and not d[clave].get("filas") and not vistas.get("oblig"):
                        # 27/11/2026 (Nabajuma): la hoja "Obligaciones al cierre" sale vacía en todos los planes. Se guarda
                        # UNA captura de la pantalla para ver cómo la muestra ARCA (Biblioteca -> pantallas del robot)
                        vistas["oblig"] = True
                        try:
                            arca.capturar(ctx, os.path.join(DATOS, cuit, "capturas"), f"planes_obligaciones_{p['numero']}")
                        except Exception:
                            pass
                detalle[p["numero"]] = d
            except (arca.SesionPerdida, arca.CuitEquivocado):
                raise
            except Exception as e:
                detalle[p["numero"]] = {"error": f"{type(e).__name__}: {str(e).splitlines()[0][:160] if str(e) else ''}"}
            arca.pausa(1.0, 2.5)
        return {"planes": [{**p, "presentacion": p["presentacion"].isoformat() if p.get("presentacion") else None}
                           for p in planes], "detalle": detalle}
    finally:
        page.close()


def paso(cuit: str, estado: dict, fecha_cierre: str = ""):
    def fn(ctx, portal):
        hoy = date.today()
        r = leer(ctx, portal, cuit, hoy)
        r.update(cuit=cuit, fecha=hoy.isoformat())
        d = os.path.join(DATOS, cuit, "planes_todos")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{hoy.isoformat()}.json"), "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1, default=str)
        try:
            from . import deuda_cierre
            hechos = deuda_cierre.generar(cuit, fechas=[date.fromisoformat(fecha_cierre)] if fecha_cierre else None)
        except Exception as e:
            hechos = [f"error: {e}"]
        estado.update(resultado=f"OK ({len(r['planes'])} planes leídos; deuda al cierre: {', '.join(hechos) or 'sin fecha de cierre'})")
        return "OK"
    return fn


def correr(cuit, periodo, usuario, clave, metodo="Directo", visible=False, fecha_cierre="", **_):
    estado: dict = {}
    from datetime import timedelta
    from . import deuda_cierre, robot_pagos_sct
    fechas = [date.fromisoformat(fecha_cierre)] if fecha_cierre else deuda_cierre.cierres(cuit)
    desde = (min(fechas) + timedelta(days=1)) if fechas else date(date.today().year - 2, 1, 1)
    est_p: dict = {}
    # primero los pagos posteriores al cierre (Cuentas Tributarias), después los planes (que arman el Excel)
    pasos = [("pagos_sct", robot_pagos_sct.paso(cuit, desde, est_p)), ("planes_todos", paso(cuit, estado, fecha_cierre))]
    r = arca.ejecutar(usuario, clave, pasos, os.path.join(DATOS, cuit, "capturas"), visible, seguir_si_falla=True)
    if (r or {}).get("_errores", {}).get("planes_todos"):
        raise arca.ErrorRobot(str(r["_errores"]["planes_todos"]))
    e_p = (r or {}).get("_errores", {}).get("pagos_sct")
    if e_p:                                   # 27/11/2026: que se vea por qué faltan los pagos posteriores
        estado["resultado"] = f"{estado.get('resultado') or 'OK'} · PAGOS POSTERIORES NO LEÍDOS: {str(e_p)[:200]}"
    elif est_p.get("resultado"):
        estado["resultado"] = f"{estado.get('resultado') or 'OK'} · pagos: {est_p['resultado']}"
    return {"cuit": cuit, "planes_todos": estado.get("resultado"), "archivos": {"planes_todos": {"alertas": []}}}
