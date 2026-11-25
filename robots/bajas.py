"""Baja de clientes (Tomás, 25/11/2026): el cliente deja de existir para los robots.

  - almacén: se borran sus claves (también las anteriores), su ficha y sus relaciones; queda la auditoría "baja";
  - bandeja: se descartan los sobres con claves suyas que todavía no se aplicaron;
  - datos e informes: NO se borran, se mueven a DATOS/_bajas/<cuit>_<fecha> (por si hace falta algo de lo bajado);
  - grupos de corrida y lista de pausados: se lo saca.
La parte de la web (datos del cliente, encargado, descartes) la hace robots_web.usuarios.borrar_cliente.
Uso (usuario robot):  python -m robots.bajas /ruta/lista.txt      (un CUIT por renglón)
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import shutil
import sys
from contextlib import closing

from . import almacen_claves as alm

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
INFORMES = os.environ.get("ROBOTS_INFORMES", "/var/lib/robots/informes")


def _cuit(x) -> str | None:
    c = re.sub(r"\D", "", str(x or ""))
    return c if len(c) == 11 else None


def dar_de_baja(cuits: list[str]) -> dict:
    cuits = sorted({c for c in (_cuit(x) for x in cuits) if c})
    hoy = dt.date.today().isoformat()
    r = {"clientes": len(cuits), "claves": 0, "sobres": 0, "carpetas": 0, "informes": 0}
    if not cuits:
        return r
    marcas = ",".join("?" * len(cuits))
    with closing(alm.conectar()) as con:
        with con:
            r["claves"] = con.execute(f"SELECT COUNT(*) FROM accesos WHERE cuit IN ({marcas})", cuits).fetchone()[0]
            for t in ("accesos", "accesos_previos", "clientes"):
                con.execute(f"DELETE FROM {t} WHERE cuit IN ({marcas})", cuits)
            con.execute(f"DELETE FROM relacionados WHERE cuit IN ({marcas}) OR cuit_relacionado IN ({marcas})", cuits + cuits)
            for c in cuits:
                alm._auditar(con, c, "*", "baja", "cliente dado de baja (planilla de bajas)")
    # sobres de la bandeja con claves de estos clientes (que todavía no se aplicaron)
    if os.path.isdir(alm.BANDEJA):
        for n in os.listdir(alm.BANDEJA):
            ruta = os.path.join(alm.BANDEJA, n)
            if not n.endswith(".json") or not os.path.isfile(ruta):
                continue
            try:
                with open(ruta, encoding="utf-8") as f:
                    s = json.load(f)
            except (OSError, ValueError):
                continue
            if _cuit(s.get("cuit")) in cuits:
                os.remove(ruta)
                r["sobres"] += 1
    # datos e informes: se guardan aparte
    destino = os.path.join(DATOS, "_bajas")
    for c in cuits:
        d = os.path.join(DATOS, c)
        if os.path.isdir(d):
            os.makedirs(destino, exist_ok=True)
            shutil.move(d, os.path.join(destino, f"{c}_{hoy}"))
            r["carpetas"] += 1
        for inf in glob.glob(os.path.join(INFORMES, "*", f"*{c}*.xlsx")):
            dst = os.path.join(destino, f"{c}_{hoy}", "informes")
            os.makedirs(dst, exist_ok=True)
            shutil.move(inf, os.path.join(dst, os.path.basename(inf)))
            r["informes"] += 1
    # grupos de corrida y pausados
    from . import correr
    for ruta in (correr.GRUPOS,):
        try:
            with open(ruta, encoding="utf-8") as f:
                g = json.load(f)
            g = {k: v for k, v in g.items() if k not in cuits}
            with open(ruta + ".tmp", "w", encoding="utf-8") as f:
                json.dump(g, f, indent=0)
            os.replace(ruta + ".tmp", ruta)
        except (OSError, ValueError):
            pass
    if os.path.exists(correr.PAUSADOS):
        quedan = sorted(correr.pausados() - set(cuits))
        with open(correr.PAUSADOS, "w", encoding="utf-8") as f:
            f.write("".join(c + "\n" for c in quedan))
    try:
        from . import publicar
        publicar.publicar()
    except Exception as e:                       # la web es secundaria
        r["aviso"] = f"no se pudo publicar la lista de clientes: {e}"
    return r


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    with open(sys.argv[1], encoding="utf-8") as f:
        lista = [x.strip() for x in f if x.strip()]
    print(json.dumps(dar_de_baja(lista), ensure_ascii=False))
