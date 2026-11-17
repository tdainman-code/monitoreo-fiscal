"""Publica para la aplicación web la lista de clientes SIN claves:
  /var/lib/robots/publico/clientes.json  -> [{cuit, razon_social, estado_arca, usuario_es_otro, relacionados}]
La aplicación web no tiene acceso al almacén de claves: solo lee este archivo, los datos y los informes.
Se ejecuta solo al terminar cada corrida y cada importación (y a mano: python3 -m robots.publicar).
"""
from __future__ import annotations

import json
import os
from contextlib import closing

PUBLICO = os.environ.get("ROBOTS_PUBLICO", "/var/lib/robots/publico")


def publicar() -> str:
    from . import almacen_claves as alm
    with closing(alm.conectar()) as con:
        clientes = {c: {"cuit": c, "razon_social": r or ""} for c, r in con.execute("SELECT cuit, razon_social FROM clientes")}
        for cuit, usuario, estado, act in con.execute(
                "SELECT cuit, usuario, estado, actualizado FROM accesos WHERE organismo='ARCA'"):
            d = clientes.setdefault(cuit, {"cuit": cuit, "razon_social": ""})
            d.update({"estado_arca": estado, "ingresa_con_otro_cuit": usuario != cuit, "actualizado": act})
        for cuit, org, det, usuario, estado, act in con.execute(
                "SELECT cuit, organismo, detalle, usuario, estado, actualizado FROM accesos ORDER BY cuit, organismo"):
            clientes.setdefault(cuit, {"cuit": cuit, "razon_social": ""}).setdefault("accesos", []).append(
                {"organismo": org, "detalle": det, "usuario": usuario, "estado": estado, "actualizado": act})
        for a, b, nom, vin, cons in con.execute(
                "SELECT cuit, cuit_relacionado, nombre, vinculo, consolidar FROM relacionados"):
            clientes.setdefault(a, {"cuit": a, "razon_social": ""}).setdefault("relacionados", []).append(
                {"cuit": b, "nombre": nom, "vinculo": vin, "consolidar": cons})
    os.makedirs(PUBLICO, exist_ok=True)
    ruta = os.path.join(PUBLICO, "clientes.json")
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(clientes.values(), key=lambda x: (x.get("razon_social") or x["cuit"]).upper()),
                  f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o640)
    os.replace(tmp, ruta)
    return ruta


if __name__ == "__main__":
    print(publicar())
