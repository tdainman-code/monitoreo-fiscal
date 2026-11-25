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
# trabajadores en paralelo: los limita la memoria
correr.os.cpu_count = lambda: 4
chk(correr.trabajadores_posibles(3, 1961) == 1, "con 2 GB corre de a uno aunque se pidan 3")
chk(correr.trabajadores_posibles(3, 7940) == 3, "con 8 GB corre 3 a la vez")
chk(correr.trabajadores_posibles(3, 3900) == 2, "con 4 GB dos a la vez")
correr.os.cpu_count = lambda: 1
chk(correr.trabajadores_posibles(6, 15900) == 1, "con 1 procesador, de a uno aunque sobre memoria")
correr.os.cpu_count = lambda: 4
chk(correr.trabajadores_posibles(6, 7940) == 5 and correr.trabajadores_posibles(6, 15900) == 6, "4 procesadores: 8 GB -> 5, 16 GB -> 6")
# reparto real en 3 procesos (sin entrar a ARCA)
import subprocess  # noqa: E402
os.environ.update(ROBOTS_CORRER_FALSO="1", HOME=T)
correr.trabajadores_posibles = lambda p: p
_t0 = correr.time.time
correr.time.sleep = lambda s: None
correr.main(["todo", "--cuit"] + cuits[:7] + ["--trabajadores", "3", "--hasta", "23:59"])
_logs = sorted(os.listdir(os.path.join(T, "logs")))
_txt = "".join(open(os.path.join(T, "logs", x)).read() for x in _logs)
chk(len(_logs) == 3 and all(c in _txt for c in cuits[:7]) and _txt.count("OK (prueba)") == 7,
    f"3 trabajadores en paralelo se reparten los 7 clientes ({len(_logs)} logs)")
# Mis Comprobantes: un mes bajado mientras estaba en curso se vuelve a bajar (25/11/2026)
from robots import robot_mis_comprobantes as rmc  # noqa: E402
_pv = os.path.join(T, "mc.json")
def _mc(fecha):
    json.dump({"fecha": fecha}, open(_pv, "w"))
    return _pv
chk(rmc._incompleto(_mc("2026-10-20"), "2026-10"), "octubre bajado el 20/10 (en curso): se vuelve a bajar")
chk(rmc._incompleto(_mc("2026-11-05"), "2026-10"), "octubre bajado el 5/11: se vuelve a bajar (pueden faltar comprobantes)")
chk(not rmc._incompleto(_mc("2026-11-20"), "2026-10"), "octubre bajado el 20/11: queda")
# régimen de IIBB: local de una jurisdicción -> no entra a la otra (25/11/2026)
from robots import avisos as _av  # noqa: E402
_cont = {}
_av.contactos = lambda: _cont
_cont.update({cuits[10]: {"regimen_iibb": "Local", "jurisdicciones_iibb": "CABA"},
              cuits[11]: {"regimen_iibb": "Local", "jurisdicciones_iibb": "Buenos Aires"},
              cuits[12]: {"regimen_iibb": "Convenio Multilateral", "jurisdicciones_iibb": "CABA, Buenos Aires"},
              cuits[13]: {"no_corresponde": "AGIP"}})
chk(correr.organismos_que_no_van(cuits[10]) == {"ARBA"} and correr.organismos_que_no_van(cuits[11]) == {"AGIP"},
    "local CABA no entra a ARBA; local Buenos Aires no entra a AGIP")
chk(correr.organismos_que_no_van(cuits[12]) == set() and correr.organismos_que_no_van(cuits[13]) == {"AGIP"},
    "Convenio entra a las dos; 'No corresponde' se respeta")
os.makedirs(os.path.join(correr.DATOS, cuits[14], "arba"), exist_ok=True)
open(os.path.join(correr.DATOS, cuits[14], "arba", "2026-10.json"), "w").write("{}")
chk(correr.regimen_iibb(cuits[14])["regimen"] == "Local" and correr.organismos_que_no_van(cuits[14]) == {"AGIP"},
    "sin datos cargados: solo DJ de ARBA = local Buenos Aires (deducido)")
print("OK" if all(res) else "FALLÓ")
sys.exit(0 if all(res) else 1)
