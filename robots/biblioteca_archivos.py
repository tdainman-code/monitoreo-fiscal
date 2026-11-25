"""Biblioteca de archivos (pedido de Gabriel, 25/11/2026): lo que dejan los robots de retenciones y percepciones.

DATOS/<cuit>/biblioteca/<AAAA-MM>/<fuente>/<fecha>.json      una versión cada vez que cambia lo informado
DATOS/<cuit>/biblioteca/<AAAA-MM>/<fuente>/archivos/         los archivos tal como los baja el organismo (TXT para importar)
DATOS/<cuit>/biblioteca/_diagnostico/<fuente>.json           último intento: si bajó, en qué paso falló, error y captura
Siempre los DOS últimos meses cerrados, nunca más.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from datetime import date, timedelta

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")


def periodos(hoy: date) -> list[tuple[int, int]]:
    """Los 2 últimos meses cerrados, del más viejo al más nuevo: [(2026, 9), (2026, 10)] el 25/11/2026."""
    p1 = hoy.replace(day=1) - timedelta(days=1)
    p2 = p1.replace(day=1) - timedelta(days=1)
    return [(p2.year, p2.month), (p1.year, p1.month)]


def carpeta(cuit: str, periodo: str, fuente: str) -> str:
    return os.path.join(DATOS, cuit, "biblioteca", periodo, fuente)


def guardar_version(cuit: str, periodo: str, fuente: str, filas: list[dict], hoy: date, extra: dict | None = None) -> str | None:
    """Guarda las filas del mes si cambiaron respecto de la última versión. Devuelve la ruta nueva o None."""
    filas = sorted(filas, key=lambda f: json.dumps(f, sort_keys=True, ensure_ascii=False))
    d = carpeta(cuit, periodo, fuente)
    previas = sorted(x for x in (os.listdir(d) if os.path.isdir(d) else []) if x[:1].isdigit() and x.endswith(".json"))
    if previas:
        try:
            with open(os.path.join(d, previas[-1]), encoding="utf-8") as f:
                if json.load(f).get("filas") == filas:
                    return None
        except (OSError, ValueError):
            pass
    os.makedirs(d, exist_ok=True)
    ruta = os.path.join(d, f"{hoy.isoformat()}.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"cuit": cuit, "periodo": periodo, "fuente": fuente, "fecha": hoy.isoformat(), "filas": filas,
                   **(extra or {})}, f, ensure_ascii=False, indent=1)
    return ruta


def guardar_archivo(cuit: str, periodo: str, fuente: str, nombre: str, crudo: bytes) -> str:
    d = os.path.join(carpeta(cuit, periodo, fuente), "archivos")
    os.makedirs(d, exist_ok=True)
    ruta = os.path.join(d, os.path.basename(nombre))
    with open(ruta, "wb") as f:
        f.write(crudo)
    return ruta


def guardar_diagnostico(cuit: str, fuente: str, diag: dict) -> None:
    """diag: {"estado": "ok"|"error"|"sin_movimientos", "pasos": [{"paso", "ok", "detalle"}], "error", "captura", "meses"}"""
    d = os.path.join(DATOS, cuit, "biblioteca", "_diagnostico")
    os.makedirs(d, exist_ok=True)
    diag = {"fecha": dt.datetime.now().isoformat(timespec="seconds"), **diag}
    with open(os.path.join(d, f"{fuente}.json"), "w", encoding="utf-8") as f:
        json.dump(diag, f, ensure_ascii=False, indent=1)
