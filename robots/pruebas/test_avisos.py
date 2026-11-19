"""Avisos de cuotas impagas: 4 días -> encargado; 15 días -> recordatorio al encargado (nada va al cliente sin su
aprobación, 19/11/2026); pagada -> resuelto."""
import datetime as dt, json, os, sys, tempfile
R = tempfile.mkdtemp()
for k, sub in (("ROBOTS_DATOS", "datos"), ("ROBOTS_PUBLICO", "publico"), ("ROBOTS_BANDEJA", "bandeja")):
    os.environ[k] = os.path.join(R, sub)
os.environ["ROBOTS_CORREO"] = os.path.join(R, "no_hay_casilla.json")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from robots import avisos as av  # noqa: E402

C = "30717468631"
HOY = dt.date(2026, 11, 30)


def plan(estado_c2):
    os.makedirs(f"{R}/datos/{C}/situacion/2026-11-30", exist_ok=True)
    cuotas = [{"cuota": 1, "venc_1": "2026-10-16", "situacion": "Pagada", "total_1": 100.0},
              {"cuota": 2, "venc_1": "2026-11-16", "venc_2": "2026-11-26", "situacion": estado_c2, "total_1": 342337.29,
               "total_2": 345475.38},
              {"cuota": 3, "venc_1": "2026-12-16", "situacion": "A vencer", "total_1": 1.0}]
    json.dump({"mis_facilidades": {"vigentes": [{"numero": "W631300", "detalle_cuotas": cuotas}]}},
              open(f"{R}/datos/{C}/situacion/2026-11-30/resultado.json", "w"))


os.makedirs(f"{R}/bandeja/pedidos", exist_ok=True)
json.dump({C: {"razon_social": "BH SOLUCIONES", "encargado": "tomas", "encargado_nombre": "Tomás",
               "encargado_email": "tomas@estudio.com", "emails_cliente": ["admin@bh.com"]}},
          open(f"{R}/bandeja/pedidos/_contactos.txt", "w"))
ok = True
def chk(c, m):
    global ok; print(("✔ " if c else "✘ ") + m); ok &= bool(c)

plan("Pendiente de pago")
r = av.evaluar(dt.date(2026, 11, 19))
chk(r["nuevos"] == 0, "día 3: todavía no avisa")
r = av.evaluar(dt.date(2026, 11, 20))
lista = json.load(open(f"{R}/publico/avisos.json"))
chk(r["nuevos"] == 1 and lista[0]["estado"] == "para el encargado" and lista[0]["cuota"] == 2, "día 4: aviso al encargado")
mails = [json.load(open(os.path.join(av.SALIDA, n))) for n in sorted(os.listdir(av.SALIDA))]
chk(len(mails) == 1 and mails[0]["para"] == ["tomas@estudio.com"] and mails[0]["estado"] == "esperando casilla",
    "mail al encargado en cola (sin casilla configurada queda esperando)")
av.evaluar(dt.date(2026, 11, 21))
chk(len(os.listdir(av.SALIDA)) == 1, "no repite el mail al encargado")
r2 = av.accion_web(lista[0]["id"], con_vep=False, por="tomas")
lista = json.load(open(f"{R}/publico/avisos.json"))
chk(r2.startswith("OK") and lista[0]["estado"] == "enviado al cliente", "botón 'Enviar aviso al cliente'")
mails = [json.load(open(os.path.join(av.SALIDA, n))) for n in sorted(os.listdir(av.SALIDA))]
mc = next(m for m in mails if "al cliente" in m["motivo"])
chk(mc["para"] == ["admin@bh.com"] and mc["cc"] == ["tomas@estudio.com"] and "W631300" in mc["cuerpo"],
    "mail al cliente con copia al encargado")
chk(av.accion_web(lista[0]["id"], con_vep=False, por="tomas").startswith("el aviso ya"), "no se manda dos veces")
# día 15: SOLO recordatorio al encargado, nada automático al cliente (acuerdo Gaby/Tomás 19/11/2026)
os.remove(f"{R}/publico/avisos.json")
previos = set(os.listdir(av.SALIDA))
antes = len(previos)
r = av.evaluar(dt.date(2026, 12, 1))
lista = json.load(open(f"{R}/publico/avisos.json"))
nuevos = [json.load(open(os.path.join(av.SALIDA, n))) for n in set(os.listdir(av.SALIDA)) - previos]
chk(lista[0]["estado"] == "para el encargado" and "recordatorio" in lista[0]["historial"][-1]["que"]
    and all(m["para"] == ["tomas@estudio.com"] for m in nuevos) and any("recordatorio" in m["motivo"] for m in nuevos)
    and not any("al cliente" in m["motivo"] for m in nuevos),
    "día 15: recordatorio al encargado, al cliente no le llega nada sin aprobación")
av.evaluar(dt.date(2026, 12, 2))
chk(len([n for n in os.listdir(av.SALIDA)]) == antes + len(nuevos), "el recordatorio no se repite")
c = json.load(open(f"{R}/bandeja/pedidos/_contactos.txt"))
c[C]["medios_vep"] = ["Pago Mis Cuentas (Banelco)", "Interbanking"]
json.dump(c, open(f"{R}/bandeja/pedidos/_contactos.txt", "w"))
peds = [json.load(open(f"{R}/bandeja/pedidos/{n}")) for n in os.listdir(f"{R}/bandeja/pedidos") if n.endswith(".json")]
chk(not any(p.get("por", "").startswith("automático") for p in peds), "no se piden VEP automáticos")
from robots import robot_vep_facilidades as rv  # noqa: E402
rv.correr = lambda cuit, plan, cuota, medios: [{"medio": m, "vep": str(1708960299 + i), "importe": "6854.63"}
                                                for i, m in enumerate(medios)]
r = av.accion_web(lista[0]["id"], con_vep=True, por="tomas")
lista = json.load(open(f"{R}/publico/avisos.json"))
mails = [json.load(open(os.path.join(av.SALIDA, n))) for n in sorted(os.listdir(av.SALIDA))]
m = [x for x in mails if "VEP para pagar HOY" in x["asunto"]]
chk(r.startswith("OK") and len(lista[0]["veps"]) == 2 and m and "1708960299" in m[0]["cuerpo"] and "1708960300" in m[0]["cuerpo"]
    and "vence HOY" in m[0]["cuerpo"], "VEP por cada medio de pago, en el mail al cliente con aviso de que vence hoy")
plan("Pagada")
r = av.evaluar(dt.date(2026, 12, 3))
lista = json.load(open(f"{R}/publico/avisos.json"))
chk(r["resueltos"] == 1 and lista[-1]["estado"] == "resuelto", "cuota pagada -> aviso resuelto")
r = av.mail_dfe({"cuit": C, "a": "cliente", "por": "gaby", "notif": {"origen": "ARCA", "fecha": "20/10/2026",
                 "asunto": "Sistema de Cuentas Tributarias", "estado": "NOTIFICADA DE OFICIO el 26/10/2026 — SIN LEER"}})
mails = [json.load(open(os.path.join(av.SALIDA, n))) for n in sorted(os.listdir(av.SALIDA))]
m = next(x for x in mails if x["motivo"].startswith("DFE cliente"))
chk(r.startswith("OK") and m["para"] == ["admin@bh.com"] and "Cuentas Tributarias" in m["cuerpo"], "DFE: reenvío al cliente")
r = av.mail_dfe({"cuit": C, "a": "admin", "por": "gaby", "notif": {"asunto": "x"}})
chk(r.startswith("sin destinatario"), "DFE: alerta al admin sin admins con mail -> lo avisa")
# deuda histórica: un mail al encargado por cada una nueva, una sola vez
os.makedirs(f"{R}/datos/{C}/sifere_deuda", exist_ok=True)
json.dump({"jurisdicciones": {"901": {"nombre": "CABA", "deuda": 9000.0, "saldo_contribuyente": 500.0, "anticipos": [
    {"anticipo": "2019-03", "impago": 9000.0, "estado": "IMPAGO"}]}}}, open(f"{R}/datos/{C}/sifere_deuda/2026-11-30.json", "w"))
n1 = av.avisar_revisiones(av.contactos(), [C], HOY)
n2 = av.avisar_revisiones(av.contactos(), [C], HOY)
mails = [json.load(open(os.path.join(av.SALIDA, f))) for f in os.listdir(av.SALIDA)]
mr = [x for x in mails if x["motivo"].startswith("revisión cm:")]
chk(n1 == 1 and n2 == 0 and len(mr) == 1 and mr[0]["para"] == ["tomas@estudio.com"] and "Visto, me ocupo" in mr[0]["cuerpo"]
    and "$ 500,00" in mr[0]["cuerpo"], "deuda histórica de Convenio: un mail al encargado, una sola vez")
print("TODO OK" if ok else "FALLAS"); sys.exit(0 if ok else 1)
