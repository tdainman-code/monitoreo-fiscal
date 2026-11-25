"""Lanzador de robots.

Ejemplos (en la máquina 'robots'):
  python3 -m robots.correr mis_comprobantes --periodo 2026-10 --cuit 20331162788 --ver
  python3 -m robots.correr mis_comprobantes --periodo 2026-10 --todos
  python3 -m robots.correr situacion_fiscal --cuit 20331162788          (Cuentas Tributarias + Mis Facilidades)
  python3 -m robots.correr situacion_fiscal --cuit 20331162788 --solo mf
  python3 -m robots.correr todo --cuit 20331162788                     (todas las fuentes + informes, 12 meses)
  python3 -m robots.correr todo --todos --modo diaria                  (lun-vie: deuda/VEP + e-ventanilla ARCA)
  python3 -m robots.correr todo --todos --modo planes                  (días 20 y 30: Mis Facilidades)
  python3 -m robots.correr todo --todos --modo semanal                 (sábado: todo + ventanillas ARBA)
  python3 -m robots.correr mis_comprobantes --meses 12 --cuit 20331162788
  python3 -m robots.correr libro_iva --cuit 20331162788                (Portal IVA: Libro IVA de los meses presentados)
  python3 -m robots.correr observados --cuit 20331162788               (Nuestra Parte: comprobantes observados / APOC)
  python3 -m robots.correr arba_dfe --cuit 20331162788                 (ARBA: ventanilla DFE, lee y resume)
  xvfb-run -a python3 -m robots.correr agip --cuit 30717468631         (AGIP: DFE sin abrir, deuda, fiscalización)
  python3 -m robots.correr fiscalizaciones --cuit 20331162788          (ARCA: órdenes de intervención, verificaciones, SIACE)

--ver        navegador visible (solo si hay pantalla gráfica). En la máquina robots no:
             ante un error se guardan capturas en la carpeta del cliente (error_*.png).
--todos      recorre todos los clientes con clave ARCA en estado distinto de "Clave inválida".
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import sys
import time
import traceback
from contextlib import closing

from . import almacen_claves as alm
from . import arca, robot_agip, robot_arba, robot_arba_dfe, robot_arba_retenciones, robot_dfe, robot_f931, robot_libro_iva, robot_mis_comprobantes, robot_observados, robot_sifere, robot_situacion_fiscal, robot_todo
from . import robot_ccma, robot_fiscalizaciones, robot_sct_historico, robot_mis_retenciones

REGISTRO = os.environ.get("ROBOTS_REGISTRO", "/var/lib/robots/ejecuciones.jsonl")
ROBOTS = {"mis_comprobantes": robot_mis_comprobantes, "situacion_fiscal": robot_situacion_fiscal,
          "f931": robot_f931, "sifere": robot_sifere, "dfe": robot_dfe, "todo": robot_todo, "arba": robot_arba,
          "libro_iva": robot_libro_iva, "observados": robot_observados, "arba_dfe": robot_arba_dfe,
          "agip": robot_agip, "fiscalizaciones": robot_fiscalizaciones, "ccma": robot_ccma, "sct_historico": robot_sct_historico,
          "mis_retenciones": robot_mis_retenciones, "arba_retenciones": robot_arba_retenciones}


DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
GRUPOS = os.path.join(os.environ.get("ROBOTS_PUBLICO", "/var/lib/robots/publico"), "grupos.json")


def asignar_grupos(cuits: list[str], grupos: int = 5) -> dict[str, dict]:
    """Día fijo de la semana (0 = lunes) y semana par/impar de cada cliente (17/11/2026).
    Responsables inscriptos: corrida completa TODAS las semanas en su día.
    Monotributistas / sin Portal IVA: DOS VECES POR MES (su día, semana por medio, según 'semana' = 0 par / 1 impar).
    Queda guardado en publico/grupos.json (la web lo lee): un cliente nunca cambia de día; los nuevos van al día con
    menos clientes y a la semana con menos clientes de ese día. Para mover uno a mano, editar ese archivo."""
    try:
        with open(GRUPOS, encoding="utf-8") as f:
            crudo = json.load(f)
    except (OSError, ValueError):
        crudo = {}
    mapa: dict[str, dict] = {}
    for k, v in crudo.items():
        v = {"dia": int(v), "semana": int(k[-1]) % 2} if isinstance(v, (int, str)) else v
        if int(v.get("dia", 99)) < grupos:
            mapa[k] = {"dia": int(v["dia"]), "semana": int(v.get("semana", 0)) % 2}
    carga = [[0, 0] for _ in range(grupos)]
    for c in cuits:
        if c in mapa:
            carga[mapa[c]["dia"]][mapa[c]["semana"]] += 1
    nuevos = [c for c in cuits if c not in mapa]
    for c in nuevos:
        d = min(range(grupos), key=lambda i: sum(carga[i]))
        sem = 0 if carga[d][0] <= carga[d][1] else 1
        mapa[c] = {"dia": d, "semana": sem}
        carga[d][sem] += 1
    if nuevos or any(not isinstance(v, dict) for v in crudo.values()):
        os.makedirs(os.path.dirname(GRUPOS), exist_ok=True)
        tmp = GRUPOS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(mapa, f, indent=0)
        os.chmod(tmp, 0o640)
        os.replace(tmp, GRUPOS)
    return mapa


def asignar_finde(cuits: list[str]) -> dict[str, dict]:
    """Pedido del 20/11/2026: la corrida COMPLETA pasa al fin de semana. Cada cliente queda fijo en sábado (5) o domingo
    (6), repartidos parejo; los monotributistas siguen semana por medio. Se guarda en publico/grupos.json (la web lo lee)."""
    try:
        with open(GRUPOS, encoding="utf-8") as f:
            crudo = json.load(f)
    except (OSError, ValueError):
        crudo = {}
    mapa: dict[str, dict] = {}
    for k, v in crudo.items():
        v = {"dia": int(v), "semana": int(k[-1]) % 2} if isinstance(v, (int, str)) else dict(v)
        mapa[k] = {"dia": int(v.get("dia", 99)), "semana": int(v.get("semana", 0)) % 2}
    carga = {5: [0, 0], 6: [0, 0]}
    for c in cuits:
        if c in mapa and mapa[c]["dia"] in carga:
            carga[mapa[c]["dia"]][mapa[c]["semana"]] += 1
    cambio = False
    for c in cuits:                     # nuevos, y los que tenían un día de lunes a viernes (esquema anterior)
        if c in mapa and mapa[c]["dia"] in carga:
            continue
        d = min(carga, key=lambda i: sum(carga[i]))
        sem = mapa[c]["semana"] if c in mapa else (0 if carga[d][0] <= carga[d][1] else 1)
        mapa[c] = {"dia": d, "semana": sem}
        carga[d][sem] += 1
        cambio = True
    if cambio:
        os.makedirs(os.path.dirname(GRUPOS), exist_ok=True)
        tmp = GRUPOS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(mapa, f, indent=0)
        os.chmod(tmp, 0o640)
        os.replace(tmp, GRUPOS)
    return mapa


def urgentes_primero(cuits: list[str]) -> list[str]:
    """Corrida diaria (20/11/2026): primero los que tenían deuda vencida o DDJJ sin presentar en la última lectura, y
    dentro de cada grupo los de datos más viejos. Si una noche no alcanza, los que quedaron van primero la siguiente."""
    import glob

    def clave(c):
        ult = sorted(glob.glob(os.path.join(DATOS, c, "situacion", "*", "resultado.json")))
        if not ult:
            return (0, "")                                   # nunca leído: primero de todo
        try:
            with open(ult[-1], encoding="utf-8") as f:
                r = json.load(f)
        except (OSError, ValueError):
            return (0, "")
        urg = any(a.get("prioridad") == "ALTA" and a.get("tipo") in ("Deuda vencida", "Falta de presentación")
                  for a in r.get("alertas") or [])
        return (1 if urg else 2, os.path.basename(os.path.dirname(ult[-1])))
    return sorted(cuits, key=clave)


FRENO_ERRORES_SEGUIDOS = 4      # errores de portal seguidos (no claves inválidas): ARCA está rechazando, se frena la noche


def hora_limite(hhmm: str, ahora: dt.datetime | None = None) -> dt.datetime:
    """Próxima vez que el reloj marca HH:MM a partir de ahora (24/11/2026): una corrida de las 20 h con --hasta 06:00
    corta a las 6 del día siguiente, y una que arrancó a las 4 (porque esperó a otra) corta a las 6 de ese mismo día."""
    ahora = ahora or dt.datetime.now()
    h, m = (int(x) for x in hhmm.split(":"))
    lim = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
    if lim > ahora:
        return lim
    # si la hora límite pasó hace menos de 8 h (una corrida de la noche que esperó a otra y recién arranca a las 6:30),
    # ya está vencida: no se mete en el día. Si pasó hace más, es la de mañana.
    return lim if ahora - lim < dt.timedelta(hours=8) else lim + dt.timedelta(days=1)


def regimen_iibb(cuit: str) -> dict:
    """Régimen de Ingresos Brutos del cliente (25/11/2026): lo cargado en la web y, si está vacío, lo que se deduce de lo
    bajado (DDJJ de SIFERE = Convenio Multilateral con sus jurisdicciones; solo DJ de ARBA = local Buenos Aires)."""
    import glob
    try:
        from . import avisos
        c = avisos.contactos().get(cuit) or {}
    except Exception:
        c = {}
    reg, jur = (c.get("regimen_iibb") or "").strip(), (c.get("jurisdicciones_iibb") or "").strip()
    fuente = "cargado en la web"
    if not reg:
        sif = [os.path.basename(x)[:7] for x in glob.glob(os.path.join(DATOS, cuit, "sifere", "[0-9][0-9][0-9][0-9]-[0-9][0-9].json"))]
        arba = glob.glob(os.path.join(DATOS, cuit, "arba", "[0-9][0-9][0-9][0-9]-[0-9][0-9].json"))
        if sif:
            reg, fuente = "Convenio Multilateral", "deducido: tiene DDJJ en SIFERE"
        elif arba:
            reg, jur, fuente = "Local", jur or "Buenos Aires", "deducido: tiene DJ local en ARBA"
        else:
            fuente = ""
    return {"regimen": reg, "jurisdicciones": jur, "no_corresponde": (c.get("no_corresponde") or "").upper(), "fuente": fuente}


def organismos_que_no_van(cuit: str) -> set[str]:
    """ARBA / AGIP a los que el robot NO entra: marcados 'No corresponde', o el cliente es local de la otra jurisdicción."""
    r = regimen_iibb(cuit)
    fuera = {o for o in ("ARBA", "AGIP") if o in r["no_corresponde"]}
    if r["regimen"].lower().startswith("local"):
        j = r["jurisdicciones"].lower()
        caba = "caba" in j or "ciudad" in j or "capital" in j
        pba = "buenos aires" in j or "pba" in j or "provincia" in j
        if caba and not pba:
            fuera.add("ARBA")
        if pba and not caba:
            fuera.add("AGIP")
    return fuera


def le_toca_hoy(cuit: str, asig: dict, hoy: dt.date | None = None) -> bool:
    hoy = hoy or dt.date.today()
    if asig["dia"] != hoy.weekday():
        return False
    if robot_libro_iva.prioridad(cuit) == 3:                  # monotributo / sin Portal IVA: semana por medio
        return hoy.isocalendar()[1] % 2 == asig["semana"]
    return True                                              # inscripto o todavía sin clasificar: todas las semanas


def fallidos_recientes(dias: int = 7) -> set[str]:
    """CUITs cuya ÚLTIMA corrida de los últimos N días terminó en error (corte, portal caído). No incluye
    'Clave inválida' (eso necesita una clave nueva, no reintentar)."""
    desde = (dt.datetime.now() - dt.timedelta(days=dias)).isoformat()
    ultimo: dict[str, str] = {}
    try:
        with open(REGISTRO, encoding="utf-8") as f:
            for linea in f:
                try:
                    e = json.loads(linea)
                except ValueError:
                    continue
                if e.get("cuit") and e.get("fecha", "") >= desde and isinstance(e.get("cuit"), str):
                    ultimo[e["cuit"]] = e.get("estado", "")
    except OSError:
        return set()
    return {c for c, est in ultimo.items() if est in ("Error", "Requiere intervención")}


def registrar(evento: dict) -> None:
    os.makedirs(os.path.dirname(REGISTRO), exist_ok=True)
    evento = {"fecha": dt.datetime.now().isoformat(timespec="seconds"), **evento}
    with open(REGISTRO, "a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False, default=str) + "\n")


PAUSADOS = os.environ.get("ROBOTS_PAUSADOS", "/var/lib/robots/pausados.txt")


def pausados() -> set[str]:
    """Clientes EN PAUSA (24/11/2026, Tomás): siguen cargados (claves y datos) pero las corridas automáticas no los
    toman hasta que se decida si se dan de baja. Un CUIT por renglón en /var/lib/robots/pausados.txt."""
    try:
        with open(PAUSADOS, encoding="utf-8") as f:
            return {"".join(ch for ch in x if ch.isdigit()) for x in f if len("".join(ch for ch in x if ch.isdigit())) == 11}
    except OSError:
        return set()


def clientes_arca() -> list[str]:
    """Clientes con clave de ARCA utilizable, ORDENADOS POR IMPORTANCIA (pedido del 16/11/2026):
    responsables inscriptos -> sin clasificar todavía -> monotributistas / sin Portal IVA. Sin los clientes en pausa."""
    with closing(alm.conectar()) as con:
        cuits = [r[0] for r in con.execute(
            "SELECT cuit FROM accesos WHERE organismo='ARCA' AND estado NOT IN ('Clave inválida','Requiere intervención') "
            "ORDER BY cuit")]
    pausa = pausados()
    return sorted((c for c in cuits if c not in pausa), key=lambda c: (robot_libro_iva.prioridad(c), c))


def correr_arba(cuit: str, periodo: str, visible: bool, meses=None, forzar=False, robot: str = "arba") -> str:
    """Solo ARBA (IIBB local o ventanilla DFE: robot='arba_dfe') y regenera los informes. No entra a ARCA."""
    from . import informe
    try:
        usuario, clave, _ = alm.obtener_clave(cuit, "ARBA", motivo="arba (IIBB local)")
    except alm.ErrorAlmacen:
        return "SIN CIT DE ARBA cargada (cargarla en la planilla e importar)"
    periodos = arca.periodos_ultimos(meses or 12, periodo)
    try:
        estado: dict = {}
        if robot == "arba_retenciones":
            from . import robot_arba_retenciones
            robot_arba_retenciones.paso(usuario, clave, estado)()
            txt = estado.get("retenciones", "")
        elif robot == "arba_dfe":
            from . import robot_arba_dfe
            robot_arba_dfe.paso(usuario, clave, estado)()
            txt = (f"{estado.get('total', 0)} comunicaciones, {estado.get('nuevas_leidas', 0)} leídas hoy, "
                   f"{estado.get('alertas', 0)} alertas ALTA")
        else:
            robot_arba.paso(usuario, clave, periodos, estado, forzar)()
            txt = _resumir(estado)
        alm.marcar_estado(cuit, "ARBA", "OK")
        informes = informe.generar_cliente(cuit, periodos)
        registrar({"robot": robot, "cuit": cuit, "periodo": periodo, "estado": "OK", "periodos": estado})
        return f"OK\n     {robot}: " + txt + "".join(f"\n     informe: {v}" for v in informes)
    except arca.ClaveInvalida as e:
        alm.marcar_estado(cuit, "ARBA", "Clave inválida")
        registrar({"robot": "arba", "cuit": cuit, "estado": "Clave inválida", "detalle": str(e)})
        return "CIT DE ARBA RECHAZADA – pedir la CIT correcta (no se reintenta)"
    except Exception as e:
        registrar({"robot": "arba", "cuit": cuit, "estado": "Error", "detalle": f"{type(e).__name__}: {e}",
                   "traza": traceback.format_exc(limit=3)})
        return f"ERROR – {type(e).__name__}: {e}"
    finally:
        clave = None  # noqa: F841


def claves_agip(cuit: str, motivo: str):
    """(usuario, clave, miba) — Clave Ciudad vieja (detalle '') y/o cuenta miBA (detalle 'miba'). None si no hay ninguna."""
    try:
        u, c, _ = alm.obtener_clave(cuit, "AGIP", motivo=motivo)
    except alm.ErrorAlmacen:
        u = c = ""
    try:
        mu, mc, _ = alm.obtener_clave(cuit, "AGIP", motivo=motivo + " (miBA)", detalle="miba")
        miba = (mu, mc)
    except alm.ErrorAlmacen:
        miba = None
    return (u, c, miba) if (u or miba) else None


def correr_agip(cuit: str) -> str:
    """Solo AGIP (Ciudad), con la Clave Ciudad y/o la cuenta miBA del almacén. No entra a ARCA."""
    cred = claves_agip(cuit, "agip (DFE, deuda, fiscalización)")
    if not cred:
        return "SIN CLAVE CIUDAD de AGIP cargada (cargarla en la web: Claves)"
    usuario, clave, miba = cred
    try:
        estado: dict = {}
        robot_agip.paso(usuario, clave, cuit, estado, miba=miba)()
        alm.marcar_estado(cuit, "AGIP", "OK")
        registrar({"robot": "agip", "cuit": cuit, "estado": "OK", "servicios": estado.get("servicios")})
        return f"OK\n     agip: {estado.get('servicios')} · {estado.get('sin_abrir', 0)} comunicaciones sin abrir"
    except arca.ClaveInvalida as e:
        alm.marcar_estado(cuit, "AGIP", "Clave inválida")
        registrar({"robot": "agip", "cuit": cuit, "estado": "Clave inválida", "detalle": str(e)})
        return "CLAVE CIUDAD RECHAZADA – pedir la clave correcta (no se reintenta)"
    except arca.RequiereIntervencion as e:
        registrar({"robot": "agip", "cuit": cuit, "estado": "Requiere intervención", "detalle": str(e)})
        return f"REQUIERE INTERVENCIÓN – {e}"
    except Exception as e:
        registrar({"robot": "agip", "cuit": cuit, "estado": "Error", "detalle": f"{type(e).__name__}: {e}",
                   "traza": traceback.format_exc(limit=3)})
        return f"ERROR – {type(e).__name__}: {e}"
    finally:
        clave = None  # noqa: F841


def correr_uno(robot: str, cuit: str, periodo: str, visible: bool, partes=None, meses=None, forzar=False,
               modo: str = "completo") -> str:
    if robot in ("arba", "arba_dfe", "arba_retenciones"):
        return correr_arba(cuit, periodo, visible, meses, forzar, robot)
    if robot == "agip":
        return correr_agip(cuit)
    usuario, clave, metodo = alm.obtener_clave(cuit, "ARCA", motivo=f"{robot} {periodo or ''}".strip())
    try:
        extra = {"partes": partes} if partes else {}
        if robot == "mis_comprobantes" and meses:
            res = robot_mis_comprobantes.correr_periodos(cuit, arca.periodos_ultimos(meses, periodo), usuario,
                                                         clave, metodo, visible, forzar)
        elif robot == "observados":
            res = robot_observados.correr(cuit, periodo, usuario, clave, metodo, visible)
            from . import informe
            res["informes"] = informe.generar_cliente(cuit, arca.periodos_ultimos(meses or 12, periodo))
        elif robot == "libro_iva":
            pers = arca.periodos_ultimos(meses or 12, periodo)
            res = robot_libro_iva.correr(cuit, periodo, usuario, clave, metodo, visible, periodos=pers, forzar=forzar)
            from . import informe
            res["informes"] = informe.generar_cliente(cuit, pers)
        elif robot in ("f931", "sifere") and meses:
            res = ROBOTS[robot].correr(cuit, None, usuario, clave, metodo, visible,
                                       periodos=arca.periodos_ultimos(meses, periodo))
        elif robot == "todo":
            fuera = organismos_que_no_van(cuit)          # régimen local: no entra a la otra jurisdicción (25/11/2026)
            try:
                u_arba, c_arba, _ = alm.obtener_clave(cuit, "ARBA", motivo="todo (IIBB local)")
                arba = (u_arba, c_arba) if "ARBA" not in fuera else None
            except alm.ErrorAlmacen:
                arba = None
            agip = claves_agip(cuit, "todo (AGIP)") if "AGIP" not in fuera else None
            res = robot_todo.correr(cuit, periodo, usuario, clave, metodo, visible, meses=meses or 12,
                                    forzar=forzar, arba=arba, agip=agip, modo=modo)
            if "Clave Ciudad rechazada" in str((res.get("errores") or {}).get("agip", "")):
                alm.marcar_estado(cuit, "AGIP", "Clave inválida")
            if "CIT de ARBA rechazada" in str((res.get("errores") or {}).get("arba", "")):
                alm.marcar_estado(cuit, "ARBA", "Clave inválida")
        else:
            res = ROBOTS[robot].correr(cuit, periodo, usuario, clave, metodo, visible=visible, **extra)
        alm.marcar_estado(cuit, "ARCA", "OK")
        n_alertas = sum(len(a.get("alertas", [])) for a in res["archivos"].values())
        errores = res.get("errores") or {}
        registrar({"robot": robot, "cuit": cuit, "periodo": periodo, "estado": "OK" if not errores else "OK parcial",
                   "alertas": n_alertas, "errores": errores})
        extra_txt = ""
        if robot in ("libro_iva", "observados"):
            extra_txt = f"\n     {robot}: {_resumir(res['periodos'])}"
            extra_txt += "".join(f"\n     informe: {v}" for v in (res.get("informes") or []))
        if robot == "todo":
            extra_txt = "".join(f"\n     {k}: {_resumir(v)}" for k, v in res.items()
                                if k in ("mis_comprobantes", "f931", "sifere", "libro_iva", "arba", "arba_dfe", "dfe", "agip", "fiscalizaciones", "ccma", "sct_historico", "mis_retenciones") and v)
            extra_txt += "".join(f"\n     ERROR {k}: {v[:150]}" for k, v in errores.items())
            extra_txt += "".join(f"\n     informe: {v}" for v in (res.get("informes") or []))
        return f"OK ({n_alertas} alertas){extra_txt}"
    except arca.ClaveInvalida as e:
        alm.marcar_estado(cuit, "ARCA", "Clave inválida")
        registrar({"robot": robot, "cuit": cuit, "periodo": periodo, "estado": "Clave inválida", "detalle": str(e)})
        return "CLAVE INVÁLIDA – pedir clave nueva al cliente"
    except arca.RequiereIntervencion as e:
        alm.marcar_estado(cuit, "ARCA", "Requiere intervención")
        registrar({"robot": robot, "cuit": cuit, "periodo": periodo, "estado": "Requiere intervención", "detalle": str(e)})
        return f"REQUIERE INTERVENCIÓN – {e}"
    except Exception as e:  # error de portal / red: se reintenta en la próxima corrida
        registrar({"robot": robot, "cuit": cuit, "periodo": periodo, "estado": "Error",
                   "detalle": f"{type(e).__name__}: {e}", "traza": traceback.format_exc(limit=3)})
        return f"ERROR – {type(e).__name__}: {e}"
    finally:
        clave = None  # noqa: F841  (no dejar la clave en memoria más de lo necesario)


def _resumir(v) -> str:
    if isinstance(v, dict):
        if "total" in v:
            return f"{v.get('total')} comunicaciones, {v.get('sin_abrir')} sin abrir ({v.get('altas_sin_abrir')} importantes)"
        cuenta: dict = {}
        for k, x in v.items():
            cuenta[str(x)] = cuenta.get(str(x), 0) + 1
        return ", ".join(f"{n} {k}" for k, n in cuenta.items())
    return str(v)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("robot", choices=ROBOTS)
    ap.add_argument("--periodo", help="AAAA-MM (obligatorio para mis_comprobantes)")
    ap.add_argument("--solo", choices=["sct", "mf"], help="situacion_fiscal: solo Cuentas Tributarias o solo Mis Facilidades")
    ap.add_argument("--meses", type=int, help="últimos N meses completos (mis_comprobantes, f931, sifere, libro_iva, todo)")
    ap.add_argument("--forzar", action="store_true", help="volver a bajar meses ya bajados")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--cuit", nargs="+")
    g.add_argument("--todos", action="store_true")
    ap.add_argument("--ver", action="store_true")
    ap.add_argument("--horas", type=float, help="tanda: no arrancar clientes nuevos pasadas N horas (siguen los "
                    "más importantes primero; los que quedan se anotan como pendientes por tiempo)")
    ap.add_argument("--grupo-del-dia", action="store_true",
                    help="con --todos: solo los clientes a los que les toca HOY (cada cliente tiene un día fijo de lunes a viernes)")
    ap.add_argument("--solo-fallidos", action="store_true",
                    help="con --todos: solo los clientes cuya última corrida de los últimos 7 días terminó en error (repechaje)")
    ap.add_argument("--fin-de-semana", action="store_true",
                    help="corrida completa de fin de semana: los clientes que tienen fijo el sábado o el domingo (el de hoy)")
    ap.add_argument("--hasta", help="HH:MM: no arrancar clientes nuevos pasada esa hora (la próxima vez que llegue después "
                                    "de arrancar; p. ej. 06:00 para no meterse en el día aunque la corrida haya esperado)")
    ap.add_argument("--urgentes-primero", action="store_true",
                    help="primero los que tenían deuda vencida o DDJJ sin presentar, después los de datos más viejos")
    ap.add_argument("--grupos", type=int, default=5, help="en cuántos días se reparten los clientes (5 = lunes a viernes)")
    ap.add_argument("--trabajadores", type=int, default=1,
                    help="clientes en paralelo (navegadores a la vez); se limita solo según la memoria del servidor")
    ap.add_argument("--modo", choices=["diaria", "planes", "semanal", "completo"], default="completo",
                    help="todo: diaria (deuda + e-ventanilla), planes (Mis Facilidades), semanal/completo (todo)")
    a = ap.parse_args(argv)
    if a.robot == "mis_comprobantes" and not a.periodo and not a.meses:
        ap.error("mis_comprobantes necesita --periodo AAAA-MM o --meses N")
    partes = (a.solo,) if a.solo else None

    cuits = clientes_arca() if a.todos else []
    if a.todos and a.grupo_del_dia:
        hoy = dt.date.today().weekday()
        if hoy >= a.grupos:
            print(f"Hoy ({DIAS[hoy]}) no le toca a ningún grupo.")
            return 0
        mapa = asignar_grupos(cuits, a.grupos)
        cuits = [c for c in cuits if le_toca_hoy(c, mapa[c])]
        print(f"Grupo del {DIAS[hoy]} (semana {'par' if dt.date.today().isocalendar()[1] % 2 == 0 else 'impar'}): "
              f"{len(cuits)} cliente(s) — inscriptos todas las semanas, monotributistas semana por medio")
    if a.todos and a.fin_de_semana:
        hoy = dt.date.today()
        if hoy.weekday() not in (5, 6):
            print(f"Hoy ({DIAS[hoy.weekday()]}) no es fin de semana.")
            return 0
        mapa = asignar_finde(cuits)
        cuits = [c for c in cuits if le_toca_hoy(c, mapa[c])]
        print(f"Corrida completa del {DIAS[hoy.weekday()]}: {len(cuits)} cliente(s) — inscriptos todas las semanas, "
              "monotributistas semana por medio")
    if a.urgentes_primero:
        cuits = urgentes_primero(cuits)
    if a.todos and a.solo_fallidos:
        cuits = [c for c in cuits if c in fallidos_recientes()]
        print(f"Repechaje: {len(cuits)} cliente(s) con error en la última corrida")
    for c in ([] if a.todos else a.cuit):
        limpio = "".join(ch for ch in c if ch.isdigit())
        if len(limpio) != 11 or limpio != c.replace("-", ""):
            ap.error(f"CUIT mal escrito: '{c}' (tienen que ser 11 números; ¿se pegó texto de más?)")
        cuits.append(limpio)
    print(f"{a.robot} {a.periodo or ''}{' modo ' + a.modo if a.robot == 'todo' else ''}: {len(cuits)} cliente(s)")
    inicio = time.time()
    seguidos = 0
    if a.todos:
        _progreso({"robot": a.robot, "modo": a.modo, "fin_de_semana": bool(getattr(a, "fin_de_semana", False)),
                   "solo_fallidos": bool(getattr(a, "solo_fallidos", False)), "horas": a.horas, "total": len(cuits),
                   "inicio": dt.datetime.now().isoformat(timespec="seconds"), "i": 0, "cuit": "", "pid": os.getpid()})
    try:
        n_trab = trabajadores_posibles(a.trabajadores) if len(cuits) > 1 else 1
        if n_trab > 1:
            _en_paralelo(a, cuits, n_trab)
        else:
            _recorrer(a, cuits, partes, inicio, seguidos)
    finally:
        if a.todos:
            _progreso(None)


def _progreso(d: dict | None) -> None:
    """21/11/2026 (Gaby): la web muestra la corrida programada en curso (Más -> Robots); antes solo se veían los pedidos
    desde la web y no se entendía por qué una versión nueva esperaba para instalarse."""
    ruta = os.path.join(os.environ.get("ROBOTS_PUBLICO", "/var/lib/robots/publico"), "corrida_en_curso.json")
    try:
        if d is None:
            if os.path.exists(ruta):
                os.remove(ruta)
            return
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.chmod(ruta + ".tmp", 0o644)
        os.replace(ruta + ".tmp", ruta)
    except Exception as e:                      # la web es secundaria: nunca frena a los robots
        print(f"(aviso: no se pudo publicar el avance: {e})")



MEMORIA_POR_NAVEGADOR_MB = 1100       # navegador + Python del robot, con margen (servidor de 2 GB: ~1,4 GB usados con uno)


def trabajadores_posibles(pedidos: int, mem_mb: int | None = None) -> int:
    """Cuántos clientes a la vez (25/11/2026): los pedidos, pero no más de los que entran en la memoria del servidor
    (con 2 GB, uno solo; con 8 GB, hasta 3 dejando 1,5 GB para la web y el sistema)."""
    if pedidos <= 1:
        return 1
    if mem_mb is None:
        try:
            with open("/proc/meminfo") as f:
                mem_mb = int(next(x for x in f if x.startswith("MemTotal")).split()[1]) // 1024
        except (OSError, StopIteration, ValueError):
            return 1
    por_cpu = int((os.cpu_count() or 1) * 1.5)          # el navegador pasa casi todo el tiempo esperando a ARCA
    return max(1, min(pedidos, (mem_mb - 1500) // MEMORIA_POR_NAVEGADOR_MB, por_cpu))


def _en_paralelo(a, cuits: list[str], n: int) -> None:
    """Reparte los clientes (en el orden que traen: urgentes primero) entre N procesos, cada uno con su navegador y
    su log (~/logs/trabajador_<k>_<fecha>.log). El candado de la corrida lo sigue teniendo este proceso."""
    import subprocess
    partes_ = [cuits[k::n] for k in range(n)]
    extra = ["--modo", a.modo]
    for opt, val in (("--hasta", a.hasta), ("--horas", a.horas), ("--periodo", a.periodo), ("--meses", a.meses),
                     ("--solo", a.solo)):
        if val:
            extra += [opt, str(val)]
    if a.forzar:
        extra.append("--forzar")
    logs = os.path.join(os.path.expanduser("~"), "logs")
    os.makedirs(logs, exist_ok=True)
    procs = []
    for k, sub in enumerate(partes_, 1):
        ruta = os.path.join(logs, f"trabajador_{k}_{dt.date.today().isoformat()}.log")
        print(f"trabajador {k}: {len(sub)} cliente(s) -> {ruta}", flush=True)
        f = open(ruta, "a", encoding="utf-8")
        procs.append((subprocess.Popen([sys.executable, "-m", "robots.correr", a.robot, "--cuit", *sub, *extra],
                                       stdout=f, stderr=subprocess.STDOUT, env={**os.environ, "ROBOTS_TRABAJADOR": str(k)}), f))
        time.sleep(30)                                   # que no entren todos a ARCA en el mismo segundo
    for p_, f in procs:
        p_.wait()
        f.close()
    print(f"terminaron los {n} trabajadores", flush=True)


def _recorrer(a, cuits, partes, inicio, seguidos):
    limite = hora_limite(a.hasta) if getattr(a, "hasta", None) else None
    for i, cuit in enumerate(cuits, 1):
        if limite and dt.datetime.now() >= limite:
            pend = cuits[i - 1:]
            print(f"SON LAS {a.hasta}: quedan {len(pend)} clientes pendientes para la próxima corrida: {' '.join(pend)}")
            registrar({"robot": a.robot, "modo": a.modo, "estado": "Pendientes por horario", "cuits": pend})
            break
        if a.horas and time.time() - inicio > a.horas * 3600:
            pend = cuits[i - 1:]
            print(f"TIEMPO CUMPLIDO ({a.horas} h): quedan {len(pend)} clientes pendientes por tiempo: {' '.join(pend)}")
            registrar({"robot": a.robot, "modo": a.modo, "estado": "Pendientes por tiempo", "cuits": pend})
            break
        print(f"[{i}/{len(cuits)}] {cuit} ... ", end="", flush=True)
        if a.todos:
            try:
                with open(os.path.join(os.environ.get("ROBOTS_PUBLICO", "/var/lib/robots/publico"), "corrida_en_curso.json"),
                          encoding="utf-8") as f:
                    d = json.load(f)
                d.update(i=i, cuit=cuit, cliente_desde=dt.datetime.now().isoformat(timespec="seconds"))
                _progreso(d)
            except Exception:
                pass
        r = correr_uno(a.robot, cuit, a.periodo, a.ver, partes, a.meses, a.forzar, a.modo)
        print(r)
        # freno (20/11/2026): si ARCA empieza a pedir captcha o a rechazar seguido, no insistir esa noche
        seguidos = seguidos + 1 if r.startswith("ERROR") else 0
        if "captcha" in r.lower() or seguidos >= FRENO_ERRORES_SEGUIDOS:
            pend = cuits[i:]
            motivo = "ARCA pidió captcha" if "captcha" in r.lower() else f"{seguidos} errores seguidos de ARCA"
            print(f"FRENADA: {motivo}. Quedan {len(pend)} clientes para la próxima corrida.")
            registrar({"robot": a.robot, "modo": a.modo, "estado": "Frenada", "detalle": motivo, "cuits": pend})
            break
        if i < len(cuits):
            time.sleep(random.uniform(20, 45))   # espacio entre clientes para no saturar ARCA


def _publicar():
    try:
        from . import publicar
        publicar.publicar()
    except Exception as e:  # la web es secundaria: nunca frena a los robots
        print(f"(aviso: no se pudo publicar la lista de clientes para la web: {e})")


if __name__ == "__main__":
    if os.environ.get("ROBOTS_CORRER_FALSO") == "1":      # solo pruebas: no entra a ARCA
        correr_uno = lambda robot, cuit, *a, **k: "OK (prueba)"  # noqa: E731
        time.sleep = lambda s: None
    try:
        sys.exit(main())
    finally:
        _publicar()
