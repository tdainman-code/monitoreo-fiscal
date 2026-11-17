"""Reglas de las notificaciones (ventanillas de ARCA, ARBA y las que se agreguen): importancia y a quién va.

Pedido del estudio (16/11/2026):
  - NO importantes (se abren igual para que queden leídas): SICNEA, emisión de Libro de Sueldos Digital,
    MALVINA (informaciones genéricas de Aduana).
  - Intimación de PAGO / deuda: al ESTUDIO y al CLIENTE.
  - Falta de PRESENTACIÓN: SOLO al estudio, indicando el RESPONSABLE del cliente según la planilla
    ("ver quién se lo comió").
  - Fiscalizaciones / requerimientos: solo al estudio (tentativo).
  - Deuda de Convenio (SIFERE): solo al estudio (capital sin actualizar).
  - Lo demás: al estudio, "a revisar" (las reglas se van ajustando con el uso).
"""
from __future__ import annotations

import ast
import re
from contextlib import closing

NO_IMPORTANTE = re.compile(r"sicnea|libro de sueldos|\blsd\b|malvina", re.I)
FALTA_PRESENTACION = re.compile(r"falta de presentaci|omisi[oó]n de presentaci|no present|ddjj (omitida|pendiente)|"
                                r"intimaci[oó]n.{0,40}presentaci|incumplimiento.{0,30}(presentaci|declaraci)", re.I)
PAGO = re.compile(r"intimaci[oó]n.{0,40}pago|falta de pago|deuda|mora|vep|saldo impago|ejecuci[oó]n fiscal|"
                  r"embargo|apremio|boleta de deuda|art\.?\s*104", re.I)
FISCALIZACION = re.compile(r"fiscaliz|inspecci|requerimiento|fire\b|inconsistencia|verificaci", re.I)
SECLO = re.compile(r"seclo", re.I)


def clasificar(asunto: str, clasificacion: str = "", texto: str = "", tipo: str = "") -> dict:
    """Devuelve {'importancia', 'para', 'motivo'}.  para: 'nadie (no importante)' | 'estudio' | 'estudio y cliente'."""
    t = " ".join(x for x in (asunto, clasificacion, tipo, (texto or "")[:3000]) if x)
    if NO_IMPORTANTE.search(f"{asunto} {clasificacion}"):
        return {"importancia": "Baja", "para": "nadie (no importante)", "motivo": "aviso genérico"}
    if FALTA_PRESENTACION.search(t):
        return {"importancia": "ALTA", "para": "estudio", "motivo": "falta de presentación"}
    if PAGO.search(t):
        return {"importancia": "ALTA", "para": "estudio y cliente", "motivo": "intimación de pago / deuda"}
    if FISCALIZACION.search(t):
        return {"importancia": "ALTA", "para": "estudio", "motivo": "fiscalización / requerimiento"}
    if re.search(r"intimaci|\bintima", t, re.I):
        return {"importancia": "ALTA", "para": "estudio", "motivo": "intimación (revisar tipo)"}
    if SECLO.search(t):
        return {"importancia": "ALTA", "para": "estudio", "motivo": "SECLO (recordar al llegar y 2 días hábiles antes)"}
    return {"importancia": "Media", "para": "estudio", "motivo": "a revisar"}


_CACHE: dict[str, str] = {}


def responsable(cuit: str) -> str:
    """Responsable del cliente según la planilla (hoja Clientes, columna 'Responsable', 'Encargado' o
    'Asignado'). Vacío si la planilla no lo tiene."""
    if cuit in _CACHE:
        return _CACHE[cuit]
    valor = ""
    try:
        from . import almacen_claves as alm
        with closing(alm.conectar()) as con:
            fila = con.execute("SELECT * FROM clientes WHERE cuit=?", (cuit,)).fetchone()
        if fila and len(fila) >= 3 and fila[2]:
            otros = ast.literal_eval(fila[2]) if isinstance(fila[2], str) else {}
            for k, v in otros.items():
                if re.search(r"responsable|encargad|asignad|empleado a cargo", str(k), re.I) and v:
                    valor = str(v).strip()
                    break
    except Exception:
        valor = ""
    _CACHE[cuit] = valor
    return valor
