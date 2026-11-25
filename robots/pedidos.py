"""Corridas pedidas desde la web (17/11/2026).

La web NO corre robots ni ve claves: deja un pedido (JSON) en la bandeja  /var/lib/robots-bandeja/pedidos/.
Esta tarea (cada minuto, usuario robot) toma los pedidos de a uno, del más viejo al más nuevo, y los corre con el
mismo lanzador de siempre (robots.correr). Usa el MISMO candado que las corridas automáticas: si hay una corrida
nocturna en curso, el pedido queda "en espera" y se toma apenas termine.

Pedido: {"id", "fecha", "por", "cuit", "robot"}   robot ∈ ROBOTS_PERMITIDOS
Estado para la web: /var/lib/robots/publico/pedidos_estado.json  (últimos 50: en espera / corriendo / resultado)

Cron (lo instala el instalador):
  * * * * * cd /home/robot/app && xvfb-run -a flock -n /tmp/robots_pedidos.lock ~/venv/bin/python -m robots.pedidos
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import re

BANDEJA = os.environ.get("ROBOTS_BANDEJA", "/var/lib/robots-bandeja")
PEDIDOS = os.path.join(BANDEJA, "pedidos")
PUBLICO = os.environ.get("ROBOTS_PUBLICO", "/var/lib/robots/publico")
CANDADO = os.environ.get("ROBOTS_CANDADO", "/tmp/robots_todo.lock")
ROBOTS_PERMITIDOS = {
    "todo": "Todo (ARCA + ARBA + AGIP + informes)",
    "situacion_fiscal": "Deuda y planes (Cuentas Tributarias + Mis Facilidades)",
    "dfe": "Domicilio fiscal electrónico ARCA",
    "libro_iva": "Libro IVA (débito / crédito)",
    "fiscalizaciones": "Fiscalizaciones ARCA",
    "ccma": "Autónomos y Monotributo (pagos, CCMA)",
    "mis_retenciones": "Percepciones y retenciones de IVA (Mis Retenciones) vs Libro IVA",
    "sct_historico": "Deuda histórica (Cuentas Tributarias, estado de cumplimiento)",
    "agip": "AGIP (DFE, deuda, fiscalización)",
    "arba_dfe": "ARBA (domicilio fiscal electrónico)",
    "arba_retenciones": "ARBA: retenciones y percepciones (2 últimos meses)",
    "sistema_registral": "Datos registrales ARCA (impuestos inscriptos, importador) → completa la ficha",
    "padron_cm": "Constancia de Convenio Multilateral (Padrón Web COMARB) → régimen y jurisdicciones",
    "pyme_iva": "IVA a 90 días (F.1272 PyME: pago diferido del IVA)",
    # botones de la pantalla Avisos (cuotas impagas): no entran a ARCA salvo para el VEP
    "aviso_enviar": "Aviso de cuota impaga al cliente",
    "aviso_vep": "Aviso de cuota impaga al cliente + VEP",
}
AVISOS = {"aviso_enviar", "aviso_vep"}
ROBOTS_PERMITIDOS["mail_dfe"] = "Mail de una comunicación del domicilio fiscal electrónico"
ROBOTS_PERMITIDOS["reporte_revisiones"] = "Reporte de revisiones diarias sin hacer"
# 25/11/2026 (Tomás): el reporte de revisiones va SIEMPRE a esta casilla (la web solo manda asunto y texto)
REPORTE_REVISIONES_PARA = ["tdainman@gmail.com"]
ROBOTS_PERMITIDOS["vep_deuda"] = "VEP de deuda (conceptos tildados en la web)"
MAX_ESTADO = 50


def _estado_leer() -> list[dict]:
    try:
        with open(os.path.join(PUBLICO, "pedidos_estado.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _estado_guardar(lista: list[dict]) -> None:
    os.makedirs(PUBLICO, exist_ok=True)
    ruta = os.path.join(PUBLICO, "pedidos_estado.json")
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lista[:MAX_ESTADO], f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o640)
    os.replace(tmp, ruta)


def _anotar(p: dict, estado: str, detalle: str = "") -> None:
    lista = [x for x in _estado_leer() if x.get("id") != p["id"]]
    lista.insert(0, {"id": p["id"], "fecha": p.get("fecha"), "por": p.get("por"), "cuit": p["cuit"],
                     "robot": p["robot"], "estado": estado, "detalle": detalle[:400],
                     "medio": p.get("medio"), "n_conceptos": len(p.get("conceptos") or []) or None,
                     "actualizado": dt.datetime.now().isoformat(timespec="seconds")})
    _estado_guardar(lista)


def _valido(p: dict) -> bool:
    ok = (isinstance(p, dict) and re.fullmatch(r"\d{11}", str(p.get("cuit", ""))) is not None
          and p.get("robot") in ROBOTS_PERMITIDOS and re.fullmatch(r"[0-9a-f]{8,32}", str(p.get("id", ""))) is not None)
    if ok and p["robot"] == "reporte_revisiones":
        ok = isinstance(p.get("asunto"), str) and isinstance(p.get("cuerpo"), str) and len(p["asunto"]) <= 200 \
            and len(p["cuerpo"]) <= 100_000
    if ok and p["robot"] == "mail_dfe":
        ok = p.get("a") in ("cliente", "admin") and isinstance(p.get("notif"), dict)
    if ok and p["robot"] == "vep_deuda":
        from .robot_vep_deuda import MEDIOS
        c = p.get("conceptos")
        ok = (isinstance(c, list) and 0 < len(c) <= 60 and all(isinstance(x, dict) and x.get("impuesto") for x in c)
              and p.get("medio") in MEDIOS)
    if ok and p["robot"] in AVISOS:
        ok = re.fullmatch(rf"{p['cuit']}:[A-Za-z0-9-]{{1,20}}:\d{{1,3}}", str(p.get("aviso", ""))) is not None
    return ok


def pendientes() -> list[tuple[str, dict]]:
    out = []
    try:
        nombres = sorted(n for n in os.listdir(PEDIDOS) if n.endswith(".json"))
    except OSError:
        return []
    for n in nombres:
        ruta = os.path.join(PEDIDOS, n)
        try:
            with open(ruta, encoding="utf-8") as f:
                p = json.load(f)
        except (OSError, ValueError):
            os.replace(ruta, ruta + ".mal")
            continue
        if not _valido(p):
            os.replace(ruta, ruta + ".mal")
            continue
        out.append((ruta, p))
    return out


def _procesar_avisos(lista) -> list:
    """Los avisos SIN VEP se mandan al instante (no entran a ARCA, no esperan el candado de las corridas)."""
    from . import avisos
    resto = []
    for ruta, p in lista:
        if p["robot"] == "reporte_revisiones":
            os.remove(ruta)
            try:
                avisos.encolar_mail(REPORTE_REVISIONES_PARA, p["asunto"], p["cuerpo"], motivo="reporte de revisiones")
                avisos.enviar_cola()
                _anotar(p, "terminado", "OK reporte encolado")
            except Exception as e:
                _anotar(p, "error", f"{type(e).__name__}: {e}")
            continue
        if p["robot"] == "mail_dfe":
            os.remove(ruta)
            try:
                r = avisos.mail_dfe(p)
                _anotar(p, "terminado" if r.startswith("OK") else "con problemas", r)
            except Exception as e:
                _anotar(p, "error", f"{type(e).__name__}: {e}")
            continue
        if p["robot"] == "aviso_enviar" or (p["robot"] == "aviso_vep" and not avisos.vep_programado()):
            os.remove(ruta)
            try:
                r = avisos.accion_web(p["aviso"], con_vep=p["robot"] == "aviso_vep", por=p.get("por") or "?")
                _anotar(p, "terminado" if r.startswith("OK") else "con problemas", r)
            except Exception as e:
                _anotar(p, "error", f"{type(e).__name__}: {e}")
        else:
            resto.append((ruta, p))
    return resto


def _limpiar_cortados() -> None:
    """Un pedido quedó 'corriendo' pero ningún proceso lo está corriendo (se cortó: actualización, reinicio, falta de
    memoria). Solo se llama con el candado tomado, o sea, cuando seguro no hay otro pedido en curso (25/11/2026)."""
    lista = _estado_leer()
    cambio = False
    for x in lista:
        if x.get("estado") == "corriendo":
            x.update(estado="se cortó", detalle="la corrida se interrumpió sin terminar (reinicio o actualización del "
                     "servidor): volver a pedirla", actualizado=dt.datetime.now().isoformat(timespec="seconds"))
            cambio = True
    if cambio:
        _estado_guardar(lista)


def procesar() -> int:
    lista = _procesar_avisos(pendientes())
    if not lista:
        try:                                                 # sin pedidos: igual se limpian los que quedaron colgados
            with open(CANDADO, "a") as candado:
                fcntl.flock(candado, fcntl.LOCK_EX | fcntl.LOCK_NB)
                _limpiar_cortados()
        except (BlockingIOError, OSError):
            pass
        return 0
    with open(CANDADO, "a") as candado:
        try:
            fcntl.flock(candado, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            for _, p in lista:
                if not any(x.get("id") == p["id"] and x.get("estado") == "en espera" for x in _estado_leer()):
                    _anotar(p, "en espera", "hay otra corrida en curso; se toma apenas termine")
            return 0
        _limpiar_cortados()
        from .correr import _publicar, correr_uno
        hechos = 0
        for ruta, p in lista:
            os.remove(ruta)                                  # se saca de la bandeja ANTES de correr (no repetir)
            _anotar(p, "corriendo")
            try:
                if p["robot"] in AVISOS:                     # aviso + VEP: entra a ARCA a generar el VEP
                    from . import avisos
                    res = avisos.accion_web(p["aviso"], con_vep=True, por=p.get("por") or "?")
                elif p["robot"] == "vep_deuda":              # VEP de deuda pedido desde la web (20/11/2026)
                    from . import avisos, robot_vep_deuda
                    v = robot_vep_deuda.correr(p["cuit"], p["conceptos"], p["medio"], por=p.get("por") or "")
                    res = (f"OK VEP {v['vep']} por $ {v.get('importe') or 0:,.2f} ({p['medio']}), vence hoy a la medianoche"
                           .replace(",", "X").replace(".", ",").replace("X", "."))
                    if p.get("enviar"):
                        res += " · " + avisos.mail_vep_deuda(p["cuit"], v, p.get("por") or "?")
                else:
                    res = correr_uno(p["robot"], p["cuit"], None, visible=False, modo="completo")
                _anotar(p, "terminado" if res.startswith("OK") else "con problemas", res)
            except Exception as e:                           # nunca dejar la tarea trabada
                _anotar(p, "error", f"{type(e).__name__}: {e}")
            hechos += 1
        _publicar()
        return hechos


if __name__ == "__main__":
    print(f"{procesar()} pedido(s) procesado(s)")
