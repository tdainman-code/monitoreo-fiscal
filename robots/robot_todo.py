"""Robot TODO: un cliente, un solo ingreso a ARCA, todas las fuentes de los informes.

Orden: Cuentas Tributarias -> Mis Facilidades -> Domicilio Fiscal Electrónico -> SIFERE ->
       Declaración en línea (F931) -> Portal IVA (Libro IVA de los meses presentados) -> Mis Comprobantes.
- Si la sesión vence, vuelve a entrar y sigue donde quedó (hasta 3 reingresos).
- Si una fuente falla (o el cliente no tiene ese servicio), se anota y se sigue con la siguiente.
- Lo ya bajado de meses anteriores no se vuelve a bajar (salvo --forzar).
Después genera los informes (relación débito/crédito y situación fiscal).

Modos (pedido del 16/11/2026):
  diaria    lunes a viernes: Cuentas Tributarias (deuda / VEP impagos) + e-ventanilla de ARCA
  planes    días 20 y 30:    Mis Facilidades (cuotas vencidas y a vencer)
  semanal   sábado:          todo lo demás + fiscalizaciones + ventanillas de ARBA y AGIP -> relación D/C
  completo  todo junto (a pedido o primera corrida)
Lo que un modo no lee se toma de la última corrida que sí lo leyó (queda anotado de qué fecha es).
"""
from __future__ import annotations

import json
import os
import glob
from datetime import date

from . import arca, robot_agip, robot_arba, robot_ddjj_presentadas, robot_fiscalizaciones, robot_dfe, robot_f931, robot_libro_iva, robot_mis_comprobantes, robot_observados, robot_sifere
from . import robot_situacion_fiscal as rsf

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")


def correr(cuit, periodo, usuario, clave, metodo="Directo", visible=False, meses: int = 12,
           forzar: bool = False, informes: bool = True, arba: tuple | None = None, agip: tuple | None = None,
           modo: str = "completo", **_):
    """arba = (usuario, CIT) y agip = (usuario, Clave Ciudad) si el cliente tiene esas claves en el almacén."""
    hoy = date.today()
    periodos = arca.periodos_ultimos(meses, periodo)
    destino = os.path.join(DATOS, cuit, "situacion", hoy.isoformat())
    os.makedirs(destino, exist_ok=True)
    delegacion = metodo == "Delegación" or usuario != cuit
    rsf.USUARIO_ACTUAL["cuit"], rsf.USUARIO_ACTUAL["cliente"] = usuario, cuit
    sit = {"cuit": cuit, "fecha": hoy.isoformat(), "alertas": [], "archivos": {}, "reingresos": 0}
    avance_mf: dict = {}
    est = {"mc": {}, "f931": {}, "sifere": {}, "dfe": {}, "arba": {}, "presentadas": {}, "liva": {}, "obs": {}, "arba_dfe": {}, "agip": {}, "fisc": {}}

    def p_sct(ctx, portal):
        sit["sct"] = rsf.leer_cuentas_tributarias(ctx, portal, cuit, destino, hoy, delegacion)
        return "OK"

    def p_mf(ctx, portal):
        sit["mis_facilidades"] = rsf.leer_mis_facilidades(ctx, portal, cuit, destino, hoy, delegacion, avance_mf)
        return "OK"

    pasos = [("cuentas_tributarias", p_sct), ("mis_facilidades", p_mf),
             ("ddjj_presentadas", robot_ddjj_presentadas.paso(cuit, est["presentadas"])),
             ("dfe", robot_dfe.paso(cuit, usuario, est["dfe"])),
             ("sifere", robot_sifere.paso(cuit, periodos, est["sifere"], forzar)),
             ("f931", robot_f931.paso(cuit, periodos, est["f931"], forzar)),
             ("libro_iva", robot_libro_iva.paso(cuit, periodos, est["liva"], forzar)),
             ("observados", robot_observados.paso(cuit, est["obs"])),
             ("fiscalizaciones", robot_fiscalizaciones.paso(cuit, est["fisc"])),
             ("mis_comprobantes", robot_mis_comprobantes.paso_periodos(cuit, periodos, est["mc"], forzar))]
    elegir = {"diaria": {"cuentas_tributarias", "dfe"}, "planes": {"mis_facilidades"}}.get(modo)
    if elegir:
        pasos = [p for p in pasos if p[0] in elegir]
        if modo in ("diaria", "planes"):
            arba = None                              # ventanillas y DJ de ARBA: solo en la semanal
            agip = None                              # AGIP: solo en la semanal
    r = arca.ejecutar(usuario, clave, pasos, os.path.join(DATOS, cuit, "capturas"), visible,
                      seguir_si_falla=True)

    # ARBA (IIBB local): ingreso propio, después de ARCA. Reintenta una vez ante un corte.
    if arba:
        for intento in range(2):
            try:
                robot_arba.paso(arba[0], arba[1], periodos, est["arba"], forzar)()
                r["_errores"].pop("arba", None)
                break
            except arca.ClaveInvalida as e:
                r["_errores"]["arba"] = f"CIT de ARBA rechazada: {e}"
                break
            except Exception as e:
                r["_errores"]["arba"] = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
                if not arca.es_corte(e):
                    break
                arca.pausa(30, 60)

    # ARBA: ventanilla del Domicilio Fiscal Electrónico (lee y resume; no abre las SIN NOTIFICAR)
    if arba and "CIT de ARBA rechazada" not in str(r["_errores"].get("arba", "")):
        from . import robot_arba_dfe
        try:
            robot_arba_dfe.paso(arba[0], arba[1], est["arba_dfe"])()
        except Exception as e:
            r["_errores"]["arba_dfe"] = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"

    # AGIP (Ciudad): ingreso propio con Clave Ciudad, ventana visible (en el servidor: xvfb-run)
    if agip:
        try:
            robot_agip.paso(agip[0], agip[1], cuit, est["agip"])()
        except arca.ClaveInvalida as e:
            r["_errores"]["agip"] = f"Clave Ciudad rechazada: {e}"
        except Exception as e:
            r["_errores"]["agip"] = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"

    # situación fiscal (mismo formato que el robot situacion_fiscal)
    sit["reingresos"] = r["_reingresos"]
    sit["modo"] = modo
    # lo que este modo no leyó: se toma de la última situación que sí lo tenga (con su fecha)
    previas = sorted(glob.glob(os.path.join(DATOS, cuit, "situacion", "*", "resultado.json")), reverse=True)
    for parte in ("sct", "mis_facilidades"):
        if parte in sit:
            continue
        for ruta in previas:
            try:
                with open(ruta, encoding="utf-8") as f:
                    prev = json.load(f)
            except Exception:
                continue
            if parte in prev:
                sit[parte] = prev[parte]
                sit.setdefault("tomado_de", {})[parte] = prev.get("fecha") if prev.get("fecha") != hoy.isoformat() \
                    else prev.get("tomado_de", {}).get(parte, prev.get("fecha"))
                break
    for parte in ("sct", "mis_facilidades"):
        if parte in sit:
            sit["alertas"] += sit[parte]["alertas"]
    if est["presentadas"].get("presentadas"):
        robot_ddjj_presentadas.depurar_alertas(sit, est["presentadas"]["presentadas"])
    if "sct" in sit or "mis_facilidades" in sit:
        with open(os.path.join(destino, "resultado.json"), "w", encoding="utf-8") as f:
            json.dump(sit, f, ensure_ascii=False, indent=1, default=str)
        rsf.guardar_excel(sit, os.path.join(destino, "situacion_fiscal.xlsx"))

    resumen = {"cuit": cuit, "fecha": hoy.isoformat(), "modo": modo, "periodos": periodos, "reingresos": r["_reingresos"],
               "errores": r["_errores"], "mis_comprobantes": est["mc"], "f931": est["f931"],
               "sifere": est["sifere"], "libro_iva": est["liva"], "observados": est["obs"].get("resultado", ""), "arba": est["arba"] if arba else "sin CIT cargada",
               "arba_dfe": est["arba_dfe"] if arba else "sin CIT cargada",
               "agip": est["agip"].get("servicios", est["agip"]) if agip else "sin Clave Ciudad cargada",
               "fiscalizaciones": est["fisc"].get("servicios", {}), "dfe": {k: est["dfe"].get(k) for k in ("total", "sin_abrir", "altas_sin_abrir")}}
    with open(os.path.join(DATOS, cuit, f"corrida_todo_{hoy.isoformat()}_{modo}.json"), "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=1, default=str)

    if informes:
        from . import informe
        try:
            resumen["informes"] = informe.generar_cliente(cuit, periodos)
        except Exception as e:
            resumen["errores"]["informes"] = f"{type(e).__name__}: {e}"
    if r["_errores"] and not ("sct" in sit or "mis_facilidades" in sit or est["mc"] or est["liva"]):
        raise arca.ErrorRobot(f"Ninguna fuente se pudo leer: {r['_errores']}")
    resumen["archivos"] = {"todo": {"alertas": sit["alertas"] + est["dfe"].get("alertas", []) + est["agip"].get("alertas", [])
                                    + est["fisc"].get("alertas", [])}}
    return resumen
