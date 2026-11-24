"""Esquema de corridas del 20/11/2026: diaria liviana (lun-vie) con los urgentes primero, completa repartida entre
sábado y domingo, y freno si ARCA pide captcha o rechaza seguido. Sin entrar a ARCA."""
import datetime as dt
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
T = tempfile.mkdtemp()
os.environ.update(ROBOTS_DATOS=os.path.join(T, "datos"), ROBOTS_PUBLICO=os.path.join(T, "publico"),
                  ROBOTS_REGISTRO=os.path.join(T, "ejecuciones.jsonl"), ROBOTS_PAUSADOS=os.path.join(T, "pausados.txt"))
from robots import correr  # noqa: E402

res = []


def chk(c, m):
    res.append(bool(c))
    print(("✔ " if c else "✘ ") + m)


# fin de semana: los que tenían día de lunes a viernes pasan a sábado o domingo, parejo, y no cambian después
cuits = [f"2033116{i:04d}" for i in range(40)]
os.makedirs(os.path.dirname(correr.GRUPOS), exist_ok=True)
json.dump({c: {"dia": i % 5, "semana": i % 2} for i, c in enumerate(cuits[:30])}, open(correr.GRUPOS, "w"))
m = correr.asignar_finde(cuits)
dias = [m[c]["dia"] for c in cuits]
chk(set(dias) == {5, 6} and abs(dias.count(5) - dias.count(6)) <= 1, f"repartidos sábado/domingo ({dias.count(5)}/{dias.count(6)})")
chk(all(m[c]["semana"] == i % 2 for i, c in enumerate(cuits[:30])), "conservan la semana par/impar (monotributo)")
chk(correr.asignar_finde(cuits) == m, "un cliente no cambia de día entre corridas")
sab = dt.date(2026, 11, 21)
chk(all((m[c]["dia"] == 5) == correr.le_toca_hoy(c, m[c], sab) for c in cuits[:5] if correr.robot_libro_iva.prioridad(c) != 3),
    "el sábado corren los del sábado")

# diaria: primero los urgentes, después los de datos más viejos (los que no se alcanzaron la noche anterior)
def sit(c, fecha, alertas):
    d = os.path.join(correr.DATOS, c, "situacion", fecha)
    os.makedirs(d, exist_ok=True)
    json.dump({"alertas": alertas}, open(os.path.join(d, "resultado.json"), "w"))
A, B, C, D = cuits[:4]
sit(A, "2026-11-19", [])
sit(B, "2026-11-18", [])
sit(C, "2026-11-19", [{"prioridad": "ALTA", "tipo": "Falta de presentación", "texto": "1 DDJJ"}])
chk(correr.urgentes_primero([A, B, C, D]) == [D, C, B, A], "orden: sin leer nunca, urgentes, y después los más viejos")

# freno: 4 errores de portal seguidos o un captcha -> corta la noche y deja anotados los pendientes
llamadas = []


def falso(r):
    def f(robot, cuit, *a, **k):
        llamadas.append(cuit)
        return r(cuit)
    return f


correr.time.sleep = lambda s: None
correr.correr_uno = falso(lambda c: "ERROR – TimeoutError: portal caído")
correr.main(["todo", "--cuit"] + cuits[:8])
chk(len(llamadas) == correr.FRENO_ERRORES_SEGUIDOS, f"frena después de {correr.FRENO_ERRORES_SEGUIDOS} errores seguidos")
reg = [json.loads(x) for x in open(correr.REGISTRO)]
chk(reg[-1]["estado"] == "Frenada" and len(reg[-1]["cuits"]) == 8 - correr.FRENO_ERRORES_SEGUIDOS, "anota la corrida frenada y los pendientes")
llamadas.clear()
correr.correr_uno = falso(lambda c: "REQUIERE INTERVENCIÓN – El login pide captcha" if c == cuits[1] else "OK (0 alertas)")
correr.main(["todo", "--cuit"] + cuits[:8])
chk(llamadas == cuits[:2], "captcha: frena enseguida")
llamadas.clear()
correr.correr_uno = falso(lambda c: "CLAVE INVÁLIDA – pedir clave nueva al cliente")
correr.main(["todo", "--cuit"] + cuits[:8])
chk(len(llamadas) == 8, "claves inválidas no frenan la corrida (son de cada cliente)")
# --hasta: corta a la próxima vez que llega esa hora
d0 = dt.datetime(2026, 11, 24, 19, 30)
chk(correr.hora_limite("06:00", d0) == dt.datetime(2026, 11, 25, 6, 0), "--hasta 06:00 arrancando 19:30 corta a las 6 del día siguiente")
chk(correr.hora_limite("06:00", dt.datetime(2026, 11, 25, 4, 0)) == dt.datetime(2026, 11, 25, 6, 0),
    "--hasta 06:00 arrancando 4:00 (esperó a otra) corta a las 6 de ese día")
chk(correr.hora_limite("06:00", dt.datetime(2026, 11, 25, 6, 30)) <= dt.datetime(2026, 11, 25, 6, 30),
    "--hasta 06:00 si recién arranca a las 6:30 (esperó toda la noche) no corre de día")
llamadas.clear()
correr.correr_uno = falso(lambda c: "OK (0 alertas)")
correr.hora_limite = lambda h: dt.datetime.now() - dt.timedelta(seconds=1)       # ya pasó la hora límite
correr.main(["todo", "--cuit"] + cuits[:3] + ["--hasta", "06:00"])
chk(llamadas == [], "--hasta: pasada la hora no arranca clientes nuevos y los deja pendientes")
# clientes en pausa: las corridas automáticas no los toman
open(correr.PAUSADOS, "w").write("20-33116000-0\n2033116000\n")   # el segundo está mal escrito: se ignora
chk(correr.pausados() == {cuits[0]}, "lista de clientes en pausa")
print("OK" if all(res) else "FALLÓ")
sys.exit(0 if all(res) else 1)
