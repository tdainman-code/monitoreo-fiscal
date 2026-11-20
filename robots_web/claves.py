"""Carga de clientes y claves desde la pantalla.

La web NO guarda claves. Cada clave se cifra al instante con la llave PÚBLICA del robot (RSA-OAEP, vía openssl,
pasando la clave por entrada estándar: nunca por archivos ni por la línea de comandos) y queda un sobre en la
bandeja. Solo el robot, con su llave privada, puede abrirlo. Nada de acá puede leer una clave ya enviada.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import subprocess
import uuid

from . import datos

BANDEJA = os.environ.get("ROBOTS_BANDEJA", "/var/lib/robots-bandeja")
PUB = os.environ.get("ROBOTS_SOBRES_PUB", os.path.join(datos.PUBLICO, "sobres_publica.pem"))
ORGANISMOS = {"ARCA": "ARCA (clave fiscal)", "ARBA": "ARBA (CIT)", "AGIP": "AGIP"}
MAX_CLAVE = 100


class ErrorClaves(Exception):
    pass


def cuit_valido(c: str) -> bool:
    if len(c) != 11 or not c.isdigit():
        return False
    s = sum(int(d) * m for d, m in zip(c[:10], (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)))
    v = 11 - s % 11
    v = {11: 0, 10: 9}.get(v, v)
    return v == int(c[10])


def listo() -> bool:
    return os.path.exists(PUB) and os.path.isdir(BANDEJA)


def sellar(clave: str) -> str:
    if not clave or len(clave) > MAX_CLAVE or any(ord(ch) < 32 for ch in clave):
        raise ErrorClaves(f"La clave debe tener entre 1 y {MAX_CLAVE} caracteres, sin saltos de línea")
    try:
        r = subprocess.run(["openssl", "pkeyutl", "-encrypt", "-pubin", "-inkey", PUB,
                            "-pkeyopt", "rsa_padding_mode:oaep", "-pkeyopt", "rsa_oaep_md:sha256",
                            "-pkeyopt", "rsa_mgf1_md:sha256"],
                           input=clave.encode(), capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ErrorClaves("No se pudo cifrar la clave en este servidor") from e
    if r.returncode != 0 or not r.stdout:
        raise ErrorClaves("No se pudo cifrar la clave (¿falta la llave pública del robot?)")
    return base64.b64encode(r.stdout).decode()


def encolar(cuit: str, razon_social: str, organismo: str, usuario: str, clave: str, por: str, detalle: str = "") -> str:
    if organismo not in ORGANISMOS:
        raise ErrorClaves("Organismo desconocido")
    if not cuit_valido(cuit):
        raise ErrorClaves("El CUIT no es válido (revisá los números)")
    if not listo():
        raise ErrorClaves("La carga de claves todavía no está habilitada en el servidor")
    sobre = {"v": 1, "id": uuid.uuid4().hex, "fecha": dt.datetime.now().isoformat(timespec="seconds"), "por": por,
             "cuit": cuit, "razon_social": razon_social.strip()[:120], "organismo": organismo,
             "detalle": detalle, "usuario": usuario.strip()[:60], "clave_sellada": sellar(clave)}
    ruta = os.path.join(BANDEJA, f"{sobre['fecha'].replace(':', '')}_{sobre['id'][:8]}.json")
    tmp = ruta + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o660)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(sobre, f)
    os.chmod(tmp, 0o660)
    os.replace(tmp, ruta)
    return sobre["id"]


def encolar_razon_social(cuit: str, razon_social: str, por: str) -> None:
    """Corrige la razón social en el almacén del robot (sin clave). Lo aplica la bandeja en pocos minutos."""
    if not cuit_valido(cuit):
        raise ErrorClaves("El CUIT no es válido")
    os.makedirs(BANDEJA, exist_ok=True)
    sobre = {"v": 1, "tipo": "razon_social", "id": uuid.uuid4().hex,
             "fecha": dt.datetime.now().isoformat(timespec="seconds"), "por": por, "cuit": cuit,
             "razon_social": razon_social.strip()[:120]}
    ruta = os.path.join(BANDEJA, f"{sobre['fecha'].replace(':', '')}_{sobre['id'][:8]}.json")
    with open(ruta + ".tmp", "w", encoding="utf-8") as f:
        json.dump(sobre, f)
    os.replace(ruta + ".tmp", ruta)


def pendientes() -> list[dict]:
    out = []
    try:
        for n in sorted(os.listdir(BANDEJA)):
            if n.endswith(".json"):
                try:
                    with open(os.path.join(BANDEJA, n), encoding="utf-8") as f:
                        s = json.load(f)
                    if s.get("tipo"):                    # correcciones de datos: no son claves pendientes
                        continue
                    out.append({k: s.get(k, "") for k in ("cuit", "razon_social", "organismo", "por", "fecha")})
                except (OSError, ValueError):
                    pass
    except OSError:
        pass
    return out


def resultados() -> list[dict]:
    """Últimos sobres procesados por el robot (sin valores): aplicado / rechazado."""
    try:
        with open(os.path.join(datos.PUBLICO, "bandeja_estado.json"), encoding="utf-8") as f:
            return json.load(f)[:30]
    except (OSError, ValueError):
        return []
