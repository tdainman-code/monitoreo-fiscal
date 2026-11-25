"""Baja de clientes (25/11/2026): se borran claves, ficha y sobres pendientes; los datos se guardan aparte; sale de los
grupos y de los pausados; el resto de los clientes queda igual. Datos de fantasía.
Uso: PYTHONPATH=. python3 robots/pruebas/test_bajas.py
"""
import json
import os
import sys
import tempfile

T = tempfile.mkdtemp()
os.environ.update(ROBOTS_DB=os.path.join(T, "almacen.db"), ROBOTS_LLAVE=os.path.join(T, "llave.key"),
                  ROBOTS_DATOS=os.path.join(T, "datos"), ROBOTS_INFORMES=os.path.join(T, "informes"),
                  ROBOTS_PUBLICO=os.path.join(T, "publico"), ROBOTS_BANDEJA=os.path.join(T, "bandeja"),
                  ROBOTS_PAUSADOS=os.path.join(T, "pausados.txt"), ROBOTS_REGISTRO=os.path.join(T, "reg.jsonl"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from robots import almacen_claves as alm  # noqa: E402

alm.crear_llave(alm.RUTA_LLAVE)
from robots import bajas, correr  # noqa: E402

ok = True


def chk(m, c):
    global ok
    ok &= bool(c)
    print(("✔ " if c else "✘ ") + m)


VA, QUEDA = "20111111112", "30222222223"
for c in (VA, QUEDA):
    alm.guardar_acceso(c, "ARCA", c, "clave-de-prueba-1")
    alm.guardar_acceso(c, "AGIP", c, "clave-de-prueba-2")
    os.makedirs(os.path.join(alm.DATOS if hasattr(alm, "DATOS") else os.environ["ROBOTS_DATOS"], c, "situacion"), exist_ok=True)
os.makedirs(os.path.join(os.environ["ROBOTS_INFORMES"], "2026-11-24"), exist_ok=True)
open(os.path.join(os.environ["ROBOTS_INFORMES"], "2026-11-24", f"relacion_dc_{VA}.xlsx"), "wb").write(b"x")
os.makedirs(os.environ["ROBOTS_BANDEJA"], exist_ok=True)
for c in (VA, QUEDA):
    json.dump({"cuit": c, "organismo": "ARCA", "sobre": "cifrado"}, open(os.path.join(os.environ["ROBOTS_BANDEJA"], f"s_{c}.json"), "w"))
os.makedirs(os.path.dirname(correr.GRUPOS), exist_ok=True)
json.dump({VA: {"dia": 5, "semana": 0}, QUEDA: {"dia": 6, "semana": 1}}, open(correr.GRUPOS, "w"))
open(correr.PAUSADOS, "w").write(f"{VA}\n{QUEDA}\n")

r = bajas.dar_de_baja([f"{VA[:2]}-{VA[2:10]}-{VA[10]}", "basura"])
chk(f"resultado {r}", r["clientes"] == 1 and r["claves"] == 2 and r["sobres"] == 1 and r["carpetas"] == 1 and r["informes"] == 1)
with alm.conectar() as con:
    quedan = {x[0] for x in con.execute("SELECT DISTINCT cuit FROM accesos")}
    audit = con.execute("SELECT COUNT(*) FROM auditoria WHERE cuit=? AND accion='baja'", (VA,)).fetchone()[0]
chk("claves: se borran solo las del dado de baja", quedan == {QUEDA} and audit == 1)
chk("bandeja: se descarta su sobre pendiente", sorted(os.listdir(os.environ["ROBOTS_BANDEJA"])) == [f"s_{QUEDA}.json"])
bj = os.path.join(os.environ["ROBOTS_DATOS"], "_bajas")
chk("datos e informes guardados aparte", not os.path.exists(os.path.join(os.environ["ROBOTS_DATOS"], VA))
    and os.path.isdir(os.path.join(os.environ["ROBOTS_DATOS"], QUEDA)) and len(os.listdir(bj)) == 1
    and os.listdir(os.path.join(bj, os.listdir(bj)[0], "informes")) == [f"relacion_dc_{VA}.xlsx"])
chk("sale de los grupos y de los pausados", list(json.load(open(correr.GRUPOS))) == [QUEDA] and correr.pausados() == {QUEDA})
pub = json.load(open(os.path.join(os.environ["ROBOTS_PUBLICO"], "clientes.json")))
chk("la lista publicada para la web ya no lo tiene", [c["cuit"] for c in pub] == [QUEDA])
print("OK" if ok else "FALLÓ")
sys.exit(0 if ok else 1)
