"""Pedidos de corrida desde la web (17/11/2026).

La web NO corre robots ni tiene acceso a las claves: deja un pedido en la bandeja (/var/lib/robots-bandeja/pedidos)
y la tarea robots.pedidos (usuario robot, cada minuto) lo toma y lo corre. El estado lo publica el robot en
/var/lib/robots/publico/pedidos_estado.json.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import uuid

from . import datos

BANDEJA = os.environ.get("ROBOTS_BANDEJA", "/var/lib/robots-bandeja")
PEDIDOS = os.path.join(BANDEJA, "pedidos")
ROBOTS = {
    "todo": "Todo (ARCA + ARBA + AGIP + informes)",
    "situacion_fiscal": "Deuda y planes",
    "dfe": "Domicilio fiscal electrónico ARCA",
    "libro_iva": "Libro IVA (débito / crédito)",
    "fiscalizaciones": "Fiscalizaciones ARCA",
    "agip": "AGIP (DFE, deuda, fiscalización)",
    "arba_dfe": "ARBA (domicilio fiscal electrónico)",
}
MAX_PENDIENTES = 30


class ErrorPedido(Exception):
    pass


def listo() -> bool:
    return os.path.isdir(PEDIDOS) and os.access(PEDIDOS, os.W_OK)


def pendientes() -> list[dict]:
    out = []
    try:
        for n in sorted(os.listdir(PEDIDOS)):
            if n.endswith(".json"):
                try:
                    with open(os.path.join(PEDIDOS, n), encoding="utf-8") as f:
                        out.append(json.load(f))
                except (OSError, ValueError):
                    pass
    except OSError:
        pass
    return out


def estado() -> list[dict]:
    try:
        with open(os.path.join(datos.PUBLICO, "pedidos_estado.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def encolar(cuit: str, robot: str, por: str) -> str:
    if robot not in ROBOTS:
        raise ErrorPedido("Robot desconocido")
    if not datos.CUIT_RE.match(cuit or ""):
        raise ErrorPedido("CUIT inválido")
    if not listo():
        raise ErrorPedido("Los pedidos de corrida todavía no están habilitados en el servidor")
    ya = pendientes()
    if any(p.get("cuit") == cuit and p.get("robot") == robot for p in ya):
        raise ErrorPedido("Ya hay un pedido igual esperando")
    if len(ya) >= MAX_PENDIENTES:
        raise ErrorPedido("Hay demasiados pedidos en espera; probá más tarde")
    p = {"id": uuid.uuid4().hex, "fecha": dt.datetime.now().isoformat(timespec="seconds"), "por": por,
         "cuit": cuit, "robot": robot}
    ruta = os.path.join(PEDIDOS, f"{p['fecha'].replace(':', '')}_{p['id'][:8]}.json")
    tmp = ruta + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o660)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(p, f)
    os.replace(tmp, ruta)
    return p["id"]
