"""Histórico acumulado de percepciones y retenciones sufridas, mes por mes (Gaby, 26/11/2026).

Dos rangos para el cruce contra el Libro IVA (Portal IVA) y Mis Comprobantes:
  - INICIAL (una sola vez, clientes nuevos o que entran al sistema): HISTORICO_MESES hacia atrás (5 años).
  - HABITUAL: los 2 últimos meses (lo que bajan las corridas de siempre).
Cada corrida guarda los meses que bajó (pisa esos meses con lo más nuevo); el cruce lee TODO lo acumulado, así lo
del histórico no se pierde cuando las corridas habituales bajan solo 2 meses.

DATOS/<cuit>/percepciones_hist/<fuente>/<AAAA-MM>.json   fuente: arca (Mis Retenciones + Aduana), arba, agip
DATOS/<cuit>/percepciones_hist/historico.json            marca del histórico inicial ya hecho (desde, hasta, fecha)
"""
from __future__ import annotations

import glob
import json
import os
import re
from datetime import date

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
HISTORICO_MESES = 60          # 5 años (Gaby: entre 3 y 5)
FUENTES = ("arca", "arba", "agip")


def mes_de(fecha: str) -> str:
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", fecha or "")
    if m:
        return f"{m[3]}-{m[2]}"
    m = re.match(r"(\d{4})-(\d{2})", fecha or "")
    return f"{m[1]}-{m[2]}" if m else ""


def carpeta(cuit: str, fuente: str = "") -> str:
    return os.path.join(DATOS, cuit, "percepciones_hist", fuente) if fuente else os.path.join(DATOS, cuit, "percepciones_hist")


def guardar(cuit: str, fuente: str, filas: list[dict], meses: list[str] | None = None, hoy: date | None = None) -> int:
    """Guarda por mes. `meses`: los meses consultados (también los que vinieron vacíos, para que quede 'sin movimientos')."""
    hoy = hoy or date.today()
    por_mes: dict[str, list] = {m: [] for m in (meses or [])}
    for f in filas:
        m = mes_de(f.get("fecha") or "")
        if m:
            por_mes.setdefault(m, []).append(f)
    d = carpeta(cuit, fuente)
    os.makedirs(d, exist_ok=True)
    for m, fs in por_mes.items():
        with open(os.path.join(d, f"{m}.json"), "w", encoding="utf-8") as fh:
            json.dump({"cuit": cuit, "fuente": fuente, "mes": m, "fecha": hoy.isoformat(), "filas": fs}, fh, ensure_ascii=False)
    return len(por_mes)


def leer(cuit: str, fuente: str) -> tuple[list[dict], list[str]]:
    """(filas de todos los meses guardados, meses guardados ordenados)."""
    filas, meses = [], []
    for r in sorted(glob.glob(os.path.join(carpeta(cuit, fuente), "[0-9][0-9][0-9][0-9]-[0-9][0-9].json"))):
        try:
            with open(r, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        meses.append(d.get("mes") or os.path.basename(r)[:7])
        filas += d.get("filas") or []
    return filas, meses


def historico_hecho(cuit: str) -> dict | None:
    try:
        with open(os.path.join(carpeta(cuit), "historico.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def marcar_historico(cuit: str, meses: int, hoy: date | None = None, detalle: dict | None = None) -> None:
    hoy = hoy or date.today()
    os.makedirs(carpeta(cuit), exist_ok=True)
    a, m = hoy.year, hoy.month - meses
    while m <= 0:
        a, m = a - 1, m + 12
    with open(os.path.join(carpeta(cuit), "historico.json"), "w", encoding="utf-8") as fh:
        json.dump({"fecha": hoy.isoformat(), "meses": meses, "desde": f"{a}-{m:02d}", "hasta": hoy.strftime("%Y-%m"),
                   **(detalle or {})}, fh, ensure_ascii=False, indent=1)


def es_cliente_nuevo(cuit: str) -> bool:
    """Sin histórico hecho y sin nada bajado del Libro IVA: es su primera corrida -> va el rango inicial."""
    if historico_hecho(cuit):
        return False
    return not glob.glob(os.path.join(DATOS, cuit, "libro_iva", "[0-9][0-9][0-9][0-9]-[0-9][0-9].json"))


def meses_atras(hoy: date, n: int) -> list[tuple[int, int]]:
    """Los n meses cerrados anteriores a hoy, del más viejo al más nuevo."""
    out, a, m = [], hoy.year, hoy.month
    for _ in range(n):
        a, m = (a, m - 1) if m > 1 else (a - 1, 12)
        out.append((a, m))
    return out[::-1]
