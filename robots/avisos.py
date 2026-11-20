"""Avisos de cuotas de planes de facilidades impagas (pedido de Gaby, 17/11/2026).

Reglas (días CORRIDOS desde el 1° vencimiento de la cuota; el pago tarda en verse en ARCA, por eso se espera):
  - Día 4 sin cancelar  -> aviso al ENCARGADO del cliente (contador a cargo del estudio), por mail y en la web
                           (pantalla "Avisos"). El encargado decide con un botón: "Enviar aviso al cliente" o
                           "Enviar aviso + VEP".
  - Día 15 sin cancelar -> RECORDATORIO al encargado (mail y web). Desde el 19/11/2026 (acordado entre Gaby y Tomás)
                           NADA va al cliente sin la aprobación del encargado: ni el aviso ni el VEP. Antes, el día 15
                           se mandaba solo.
  - Si la cuota aparece cancelada en una corrida posterior, el aviso queda "resuelto" y no se manda nada más.

Datos:
  - Planes: la última situación fiscal bajada (DATOS/<cuit>/situacion/<fecha>/resultado.json, Mis Facilidades).
  - Contactos: los publica la web en la bandeja (_contactos.txt): encargado (nombre y mail) y mails del cliente.
  - Estado de los avisos para la web: PUBLICO/avisos.json.
  - Mails: cola en DATOS/../correo/salida. Se mandan solo si existe la casilla configurada en
    /etc/robots/correo.json ({"host","puerto","usuario","clave","remitente","tls":true}); mientras tanto quedan en
    la cola con estado "esperando casilla" (la configura Tomás; ver nube/GUIA.md).
  - VEP: lo genera robot_vep_facilidades (cuando esté programado con las pantallas de Gaby); hasta entonces el
    aviso sale sin VEP y lo dice.

Uso:  python3 -m robots.avisos evaluar        (cada 30 minutos por cron; también manda la cola)
      python3 -m robots.avisos enviar          (solo manda la cola)
      python3 -m robots.avisos probar-correo tu@mail.com
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import smtplib
import ssl
import sys
import uuid
from email.message import EmailMessage

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
PUBLICO = os.environ.get("ROBOTS_PUBLICO", "/var/lib/robots/publico")
BANDEJA = os.environ.get("ROBOTS_BANDEJA", "/var/lib/robots-bandeja")
CORREO_CFG = os.environ.get("ROBOTS_CORREO", "/etc/robots/correo.json")
SALIDA = os.environ.get("ROBOTS_CORREO_SALIDA", os.path.join(os.path.dirname(DATOS.rstrip("/")), "correo", "salida"))
DIAS_ENCARGADO = 4
DIAS_CLIENTE = 15
ANTIGUEDAD_MAX = 120          # no se avisan cuotas vencidas hace más de 120 días (ya deberían estar gestionadas)


# ---------------------------------------------------------------- utilidades
def _leer(ruta, defecto=None):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defecto


def _guardar(ruta, d):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1, default=str)
    os.chmod(tmp, 0o640)
    os.replace(tmp, ruta)


def _fecha(v) -> dt.date | None:
    if isinstance(v, dt.date):
        return v
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(v or ""))
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3]))
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", str(v or ""))
    return dt.date(int(m[3]), int(m[2]), int(m[1])) if m else None


def _pesos(x) -> str:
    try:
        return "$ " + f"{float(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "—"


def _cuit_fmt(c: str) -> str:
    return f"{c[:2]}-{c[2:10]}-{c[10:]}" if len(c) == 11 else c


def contactos() -> dict:
    """{cuit: {"razon_social","encargado","encargado_nombre","encargado_email","emails_cliente":[...]}}"""
    return _leer(os.path.join(BANDEJA, "pedidos", "_contactos.txt"), {}) or {}


def _situacion(cuit: str) -> dict | None:
    rutas = sorted(glob.glob(os.path.join(DATOS, cuit, "situacion", "*", "resultado.json")))
    return _leer(rutas[-1]) if rutas else None


# ---------------------------------------------------------------- mails
def casilla() -> dict | None:
    c = _leer(CORREO_CFG)
    return c if isinstance(c, dict) and c.get("host") and c.get("remitente") else None


def encolar_mail(para: list[str], asunto: str, cuerpo: str, cc: list[str] | None = None, motivo: str = "",
                 adjuntos: list[str] | None = None) -> str:
    para = [p for p in (para or []) if re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+", p or "")]
    m = {"id": uuid.uuid4().hex, "fecha": dt.datetime.now().isoformat(timespec="seconds"), "para": para,
         "cc": [c for c in (cc or []) if c and c not in para], "asunto": asunto, "cuerpo": cuerpo, "motivo": motivo,
         "adjuntos": adjuntos or [], "estado": "en cola" if para else "sin destinatario"}
    _guardar(os.path.join(SALIDA, f"{m['fecha'].replace(':', '')}_{m['id'][:8]}.json"), m)
    return m["id"]


def enviar_cola() -> dict:
    """Manda los mails en cola. Sin casilla configurada, quedan 'esperando casilla'."""
    cfg = casilla()
    res = {"enviados": 0, "esperando": 0, "errores": 0}
    for ruta in sorted(glob.glob(os.path.join(SALIDA, "*.json"))):
        m = _leer(ruta)
        if not m or m.get("estado") not in ("en cola", "esperando casilla", "error"):
            continue
        if not cfg:
            if m["estado"] != "esperando casilla":
                m["estado"] = "esperando casilla"
                _guardar(ruta, m)
            res["esperando"] += 1
            continue
        try:
            msg = EmailMessage()
            msg["From"] = cfg["remitente"]
            msg["To"] = ", ".join(m["para"])
            if m.get("cc"):
                msg["Cc"] = ", ".join(m["cc"])
            msg["Subject"] = m["asunto"]
            msg.set_content(m["cuerpo"])
            for a in m.get("adjuntos") or []:
                if os.path.exists(a):
                    with open(a, "rb") as f:
                        msg.add_attachment(f.read(), maintype="application", subtype="pdf", filename=os.path.basename(a))
            puerto = int(cfg.get("puerto") or 587)
            if puerto == 465:
                s = smtplib.SMTP_SSL(cfg["host"], puerto, context=ssl.create_default_context(), timeout=60)
            else:
                s = smtplib.SMTP(cfg["host"], puerto, timeout=60)
                if cfg.get("tls", True):
                    s.starttls(context=ssl.create_default_context())
            with s:
                if cfg.get("usuario"):
                    s.login(cfg["usuario"], cfg.get("clave", ""))
                s.send_message(msg)
            m["estado"], m["enviado"] = "enviado", dt.datetime.now().isoformat(timespec="seconds")
            res["enviados"] += 1
        except Exception as e:                          # se reintenta en la próxima pasada
            m["estado"], m["error"] = "error", f"{type(e).__name__}: {e}"[:300]
            res["errores"] += 1
        _guardar(ruta, m)
    return res


def estado_mail(mid: str) -> str:
    for ruta in glob.glob(os.path.join(SALIDA, f"*_{mid[:8]}.json")):
        return (_leer(ruta) or {}).get("estado", "?")
    return "?"


# ---------------------------------------------------------------- textos
def _texto_cliente(a: dict, veps: list[dict], nota_vep: str) -> str:
    if veps:
        lineas = "\n".join(f"  - {v['medio']}: VEP N° {v['vep']} por $ {v.get('importe')}" for v in veps)
        linea_vep = (f"\nPara pagarla generamos el VEP (búsquenlo por su número en el home banking):\n{lineas}\n"
                     f"IMPORTANTE: el VEP vence HOY ({dt.date.today():%d/%m/%Y}) a las 24 h; después hay que generar otro.\n")
    else:
        linea_vep = f"\n{nota_vep}\n" if nota_vep else ""
    return (f"Estimados de {a['razon_social'] or _cuit_fmt(a['cuit'])}:\n\n"
            f"Les informamos que en ARCA figura IMPAGA la cuota {a['cuota']} del plan de facilidades de pago "
            f"N° {a['plan']}, con vencimiento el {_fecha(a['venc_1']):%d/%m/%Y}, por {_pesos(a['importe'])}"
            + (f" (con el 2° vencimiento: {_pesos(a['importe_2'])})" if a.get("importe_2") else "") + ".\n"
            "Si el plan acumula cuotas impagas, ARCA puede declarar su caducidad.\n"
            f"{linea_vep}\nSi ya la pagaron, desestimen este aviso (el pago puede demorar unos días en verse en ARCA).\n\n"
            "Saludos cordiales.\nEstudio")


def _texto_encargado(a: dict, etapa: str) -> str:
    base = (f"Cliente: {a['razon_social']} ({_cuit_fmt(a['cuit'])})\nPlan {a['plan']} — cuota {a['cuota']}, "
            f"vencida el {_fecha(a['venc_1']):%d/%m/%Y} ({a['dias']} días), {_pesos(a['importe'])}.\n"
            f"Estado en ARCA: {a['situacion']}.\n\n")
    if etapa == "encargado":
        return base + ("Pasaron 4 días del vencimiento y la cuota sigue sin cancelar.\n"
                       "Entrá a la web (Avisos) para enviarle el aviso al cliente, con o sin VEP.\n"
                       "Al cliente no le llega nada si no lo aprobás vos.")
    return base + ("Pasaron 15 días y sigue impaga. Al cliente no se le mandó nada: entrá a la web (Avisos) y aprobá "
                   "el envío del aviso, con o sin VEP.")


# ---------------------------------------------------------------- evaluación
def _cuotas_abiertas(cuit: str, hoy: dt.date):
    sit = _situacion(cuit) or {}
    mf = sit.get("mis_facilidades") or {}
    for p in mf.get("vigentes") or []:
        for c in p.get("detalle_cuotas") or []:
            v1 = _fecha(c.get("venc_1"))
            if not v1:
                continue
            yield p, c, v1


def evaluar(hoy: dt.date | None = None) -> dict:
    hoy = hoy or dt.date.today()
    ruta = os.path.join(PUBLICO, "avisos.json")
    avisos = {a["id"]: a for a in (_leer(ruta, []) or [])}
    cont = contactos()
    nuevos = auto = resueltos = 0
    cuits = sorted(n for n in os.listdir(DATOS) if re.fullmatch(r"\d{11}", n)) if os.path.isdir(DATOS) else []
    vistos = set()
    for cuit in cuits:
        info = cont.get(cuit) or {}
        if not info.get("razon_social"):
            try:
                from .almacen_claves import razon_social
                info = {**info, "razon_social": razon_social(cuit)}
            except Exception:
                pass
        for p, c, v1 in _cuotas_abiertas(cuit, hoy):
            aid = f"{cuit}:{p.get('numero')}:{c.get('cuota')}"
            vistos.add(aid)
            dias = (hoy - v1).days
            pagada = c.get("situacion") == "Pagada"
            a = avisos.get(aid)
            if a and pagada and a["estado"] != "resuelto":
                a.update(estado="resuelto", resuelto=hoy.isoformat(), detalle="la cuota figura cancelada en ARCA")
                resueltos += 1
                continue
            if pagada or dias < DIAS_ENCARGADO or dias > ANTIGUEDAD_MAX:
                continue
            if not a:
                a = avisos[aid] = {
                    "id": aid, "cuit": cuit, "razon_social": info.get("razon_social", ""), "plan": p.get("numero"),
                    "cuota": c.get("cuota"), "venc_1": v1.isoformat(), "venc_2": str(c.get("venc_2") or ""),
                    "importe": c.get("total_1"), "importe_2": c.get("total_2"), "creado": hoy.isoformat(),
                    "estado": "para el encargado", "historial": []}
                nuevos += 1
            a.update(dias=dias, situacion=c.get("situacion", ""), encargado=info.get("encargado", ""),
                     encargado_nombre=info.get("encargado_nombre", ""), razon_social=a.get("razon_social") or info.get("razon_social", ""))
            if a["estado"] == "para el encargado" and not a.get("mail_encargado"):
                a["mail_encargado"] = encolar_mail(
                    [info.get("encargado_email", "")], f"Cuota impaga: {a['razon_social'] or _cuit_fmt(cuit)} — plan {a['plan']}",
                    _texto_encargado(a, "encargado"), motivo=f"aviso {aid} (día {DIAS_ENCARGADO})")
                a["historial"].append({"fecha": hoy.isoformat(), "que": "aviso al encargado",
                                       "a": info.get("encargado_email") or "(el encargado no tiene mail cargado)"})
            if dias >= DIAS_CLIENTE and a["estado"] == "para el encargado" and not a.get("recordatorio_encargado"):
                # sin envío automático al cliente: el encargado aprueba con el botón (19/11/2026)
                a["recordatorio_encargado"] = encolar_mail(
                    [info.get("encargado_email", "")], f"SIGUE IMPAGA ({dias} días): {a['razon_social'] or _cuit_fmt(cuit)} — plan {a['plan']}",
                    _texto_encargado(a, "recordatorio"), motivo=f"aviso {aid} (día {DIAS_CLIENTE}, recordatorio)")
                a["historial"].append({"fecha": hoy.isoformat(), "que": f"recordatorio al encargado ({DIAS_CLIENTE} días)",
                                       "a": info.get("encargado_email") or "(el encargado no tiene mail cargado)"})
                auto += 1
    lista = sorted(avisos.values(), key=lambda a: (a["estado"] == "resuelto", -int(a.get("dias") or 0)))
    _guardar(ruta, lista[:2000])
    rev = avisar_revisiones(cont, cuits, hoy)
    try:
        avisar_iva_diferido(cont, cuits, hoy)
    except Exception:
        pass
    env = enviar_cola()
    return {"nuevos": nuevos, "automaticos": auto, "resueltos": resueltos, "revisiones": rev, "mails": env}


def _ultimo_json(cuit: str, carpeta: str) -> dict | None:
    import glob
    rutas = sorted(glob.glob(os.path.join(DATOS, cuit, carpeta, "*.json")))
    return _leer(rutas[-1]) if rutas else None


def revisiones(cuit: str) -> list[dict]:
    """Deuda histórica que el encargado tiene que revisar (mismas claves que la web: robots_web/datos.revisiones)."""
    out = []
    cm = _ultimo_json(cuit, "sifere_deuda") or {}
    for j, v in (cm.get("jurisdicciones") or {}).items():
        imp = [a for a in v.get("anticipos") or [] if a.get("impago") and "reciente" not in a.get("estado", "")]
        if imp:
            out.append({"clave": f"cm:{cuit}:{j}:{imp[-1]['anticipo']}:{len(imp)}", "tema": "Convenio Multilateral",
                        "texto": f"{j} {v.get('nombre', '')}: {len(imp)} anticipo(s) con saldo a favor del fisco y sin el pago "
                                 f"({imp[0]['anticipo']} a {imp[-1]['anticipo']}), {_pesos(v.get('deuda'))} sin actualizar"
                                 + (f"; saldos a favor del contribuyente: {_pesos(v.get('saldo_contribuyente'))}"
                                    if v.get("saldo_contribuyente") else "")})
    for org, carpeta in (("agip", "agip"), ("arba", "arba_dfe")):   # deuda y saldo a favor AGIP / ARBA (20/11/2026)
        rutas = sorted(__import__("glob").glob(os.path.join(DATOS, cuit, carpeta, "[0-9]*", "resultado.json")))
        res = _leer(rutas[-1]) if rutas else None
        for a in (res or {}).get("alertas") or []:
            if re.match(r"(AGIP|ARBA): (compensar|saldo a favor para recuperar|deuda en juicio)", a.get("tipo", "")):
                clave = f"{org}:{cuit}:" + re.sub(r"[^\w.:-]", "", (a["tipo"].split(":")[1] + ":" + "".join(re.findall(r"\d", a["texto"]))[:24]))[:58]
                out.append({"clave": clave, "tema": a["tipo"], "texto": a["texto"]})
    h = _ultimo_json(cuit, "sct_historico") or {}
    if h.get("saldos_recuperar"):                       # pagos mal hechos -> F.399 (19/11/2026)
        sr = h["saldos_recuperar"]
        out.append({"clave": f"sld:{cuit}:{round(h.get('saldos_recuperar_total') or 0)}:{len(sr)}",
                    "tema": "Saldos a recuperar (F.399)",
                    "texto": f"Pago en demasía, reimputable por F.399, por {_pesos(h.get('saldos_recuperar_total'))}: "
                             + "; ".join(f"{x['impuesto']} {x['periodo'][4:6]}/{x['periodo'][:4]} {_pesos(x['sld'])}" for x in sr[:8])
                             + ". Reimputarlos con el F.399 a los períodos que se deben"
                             + ("; deuda en otros impuestos: " + "; ".join(f"{k} {_pesos(v)}" for k, v in
                                sorted((h.get("por_impuesto") or {}).items(), key=lambda x: -x[1])[:4] if v)
                                if any((h.get("por_impuesto") or {}).values()) else "") + "."})
    if h.get("deudas"):
        out.append({"clave": f"sct:{cuit}:{round(h.get('deuda_total') or 0)}:{len(h['deudas'])}", "tema": "Cuentas Tributarias",
                    "texto": f"Estado de cumplimiento: {len(h['deudas'])} período(s)/concepto(s) con deuda por "
                             f"{_pesos(h.get('deuda_total'))} en " + ", ".join(list(h.get("por_impuesto") or {})[:6])})
    return out


def avisar_revisiones(cont: dict, cuits: list[str], hoy: dt.date) -> int:
    """Un mail al encargado por cada deuda histórica NUEVA (una sola vez por clave). La marca de "visto, me ocupo"
    la pone el encargado en la web."""
    ruta = os.path.join(PUBLICO, "revisiones.json")
    hechas = _leer(ruta, {}) or {}
    n = 0
    for cuit in cuits:
        info = cont.get(cuit) or {}
        for x in revisiones(cuit):
            if x["clave"] in hechas:
                continue
            nombre = info.get("razon_social") or _cuit_fmt(cuit)
            historica = x["clave"].split(":")[0] in ("cm", "sct")
            cuerpo = (f"Hola {info.get('encargado_nombre') or ''}:\n\nEl robot encontró en {nombre} "
                      f"({_cuit_fmt(cuit)}) algo que hay que revisar:\n\n{x['tema']}: {x['texto']}\n\n"
                      + ("Es capital sin actualizar (no es la deuda de hoy). Fijate si está compensada, en un plan o si hay que "
                         "pagarla, y marcala \"Visto, me ocupo\" en la ficha del cliente.\n" if historica else
                         "Ocupate y marcalo \"Visto, me ocupo\" en la ficha del cliente (Deuda histórica).\n"))
            hechas[x["clave"]] = {"fecha": hoy.isoformat(), "cuit": cuit,
                                  "mail": encolar_mail([info.get("encargado_email", "")], f"Para revisar: {nombre} — {x['tema']}",
                                                       cuerpo, motivo=f"revisión {x['clave']}")}
            n += 1
    _guardar(ruta, hechas)
    return n


def mail_vep_deuda(cuit: str, v: dict, por: str) -> str:
    """Mail al cliente con el VEP de deuda generado desde la web (copia al encargado)."""
    info = contactos().get(cuit) or {}
    para = info.get("emails_cliente") or []
    if not para:
        return "el cliente no tiene mails cargados (no se envió)"
    nombre = info.get("razon_social") or _cuit_fmt(cuit)
    renglones = "\n".join(f"  · {c.get('impuesto')} — {c.get('concepto')} — período {c.get('periodo')}"
                          for c in v.get("conceptos") or [])
    cuerpo = (f"Estimados {nombre}:\n\nLes enviamos el VEP para pagar la siguiente deuda con ARCA:\n\n{renglones}\n\n"
              f"Número de VEP: {v['vep']}\nImporte: {_pesos(v.get('importe'))}\nMedio de pago: {v.get('medio')}\n\n"
              "IMPORTANTE: el VEP vence HOY a las 24 h. Para pagarlo, ingresen a su home banking, sección pagos AFIP/ARCA "
              "(VEP), y búsquenlo por el número.\n\nSaludos,\nEl estudio")
    mid = encolar_mail(para, f"VEP ARCA {v['vep']} — {nombre} (vence hoy)", cuerpo,
                       cc=[info.get("encargado_email", "")], motivo=f"VEP deuda {cuit} por {por}")
    return f"mail al cliente ({', '.join(para)}): {estado_mail(mid)}"


DIAS_IVA_DIFERIDO = 10


def iva_por_vencer(cuit: str, hoy: dt.date) -> list[dict]:
    """IVA diferido (pago a 90 días): obligaciones de IVA de la solapa Deudas de Cuentas Tributarias que todavía no
    vencieron (pedido de Gaby 20/11/2026)."""
    sit = _situacion(cuit) or {}
    out = []
    for d in (sit.get("sct") or {}).get("deudas") or []:
        if not re.match(r"\s*0*30\b|.*\bIVA\b", str(d.get("impuesto") or ""), re.I):
            continue
        v = _fecha(d.get("vencimiento"))
        if not v or v < hoy or not (d.get("total") or d.get("capital")):
            continue
        out.append({**d, "venc": v})
    return out


def avisar_iva_diferido(cont: dict, cuits: list[str], hoy: dt.date) -> int:
    """Mail al ENCARGADO del cliente 10 días corridos antes del vencimiento de cada IVA diferido, una sola vez, para
    que él le avise al cliente (no se le manda nada al cliente)."""
    ruta = os.path.join(PUBLICO, "iva_diferido.json")
    hechos = _leer(ruta, {}) or {}
    n = 0
    for cuit in cuits:
        info = cont.get(cuit) or {}
        for d in iva_por_vencer(cuit, hoy):
            faltan = (d["venc"] - hoy).days
            clave = f"{cuit}:{d.get('periodo')}:{d.get('cuota')}:{d['venc'].isoformat()}"
            if faltan > DIAS_IVA_DIFERIDO or clave in hechos:
                continue
            nombre = info.get("razon_social") or _cuit_fmt(cuit)
            importe = d.get("total") or d.get("capital")
            cuerpo = (f"Hola {info.get('encargado_nombre') or ''}:\n\n{nombre} ({_cuit_fmt(cuit)}) tiene IVA diferido que vence "
                      f"el {d['venc']:%d/%m/%Y} (en {faltan} días): período {d.get('periodo_txt') or d.get('periodo')}, "
                      f"{_pesos(importe)}.\n\nAvisale al cliente para que lo pague a término. Al cliente el sistema no le "
                      "manda nada.\n")
            hechos[clave] = {"fecha": hoy.isoformat(), "cuit": cuit, "importe": importe,
                             "mail": encolar_mail([info.get("encargado_email", "")],
                                                  f"IVA diferido vence el {d['venc']:%d/%m}: {nombre}", cuerpo,
                                                  motivo=f"iva diferido {clave}")}
            n += 1
    _guardar(ruta, hechos)
    return n


def vep_programado() -> bool:
    try:
        from . import robot_vep_facilidades  # noqa: F401
        return True
    except ImportError:
        return False


def enviar_al_cliente(a: dict, info: dict, con_vep: bool, por: str) -> None:
    """Encola el aviso al cliente (copia al encargado). Con VEP: lo genera en ARCA en este momento (vence hoy a las 24 h)
    por cada medio de pago del cliente. Se llama con el candado de las corridas tomado (pedidos.py)."""
    veps, nota = [], ""
    if con_vep:
        medios = info.get("medios_vep") or []
        if not medios:
            nota = ""
            a["vep"] = "sin VEP: falta cargar el medio de pago del VEP en 'Datos del cliente'"
        elif not vep_programado():
            a["vep"] = "pendiente: falta programar la generación del VEP"
        else:
            from . import robot_vep_facilidades
            try:
                veps = robot_vep_facilidades.correr(a["cuit"], str(a["plan"]), int(a["cuota"]), medios)
                a["vep"] = ", ".join(f"{v['medio']} N° {v['vep']}" for v in veps) or "ARCA no generó el VEP"
            except Exception as e:
                a["vep"] = f"no se pudo generar ({type(e).__name__}: {str(e)[:150]})"
    else:
        a["vep"] = "sin VEP"
    mid = encolar_mail(info.get("emails_cliente") or [],
                       f"Aviso: cuota impaga del plan de facilidades {a['plan']}" + (" — VEP para pagar HOY" if veps else ""),
                       _texto_cliente(a, veps, nota), cc=[info.get("encargado_email", "")],
                       motivo=f"aviso {a['id']} al cliente ({por})")
    a["estado"] = "enviado al cliente"
    a["mail_cliente"] = mid
    a["veps"] = veps
    a.setdefault("historial", []).append({
        "fecha": dt.date.today().isoformat(), "que": f"aviso al cliente{' + VEP' if con_vep else ''} — {por}",
        "a": ", ".join(info.get("emails_cliente") or []) or "(el cliente no tiene mails cargados)"})


def _pedir_vep_automatico(a: dict) -> None:
    """Día 15: el VEP necesita entrar a ARCA (candado de corridas + pantalla virtual): se deja un pedido para
    robots.pedidos, que genera el VEP y manda el aviso al cliente."""
    carpeta = os.path.join(BANDEJA, "pedidos")
    p = {"id": uuid.uuid4().hex, "fecha": dt.datetime.now().isoformat(timespec="seconds"), "por": "automático (15 días)",
         "cuit": a["cuit"], "robot": "aviso_vep", "aviso": a["id"]}
    ruta = os.path.join(carpeta, f"{p['fecha'].replace(':', '')}_{p['id'][:8]}.json")
    with open(ruta + ".tmp", "w", encoding="utf-8") as f:
        json.dump(p, f)
    os.replace(ruta + ".tmp", ruta)
    a["estado"] = "VEP en preparación (15 días)"


def accion_web(aviso_id: str, con_vep: bool, por: str) -> str:
    """Botón del encargado en la web: 'Enviar aviso al cliente' / 'Enviar aviso + VEP'."""
    ruta = os.path.join(PUBLICO, "avisos.json")
    lista = _leer(ruta, []) or []
    a = next((x for x in lista if x["id"] == aviso_id), None)
    if not a:
        return "aviso inexistente"
    if a["estado"] not in ("para el encargado", "VEP en preparación (15 días)"):
        return f"el aviso ya está '{a['estado']}'"
    info = contactos().get(a["cuit"]) or {}
    enviar_al_cliente(a, info, con_vep, por=f"pedido por {por}")
    _guardar(ruta, lista)
    enviar_cola()
    return "OK " + a["vep"]


def mail_dfe(p: dict) -> str:
    """Tablero DFE: reenvío de una comunicación al cliente (copia al encargado) o alerta a los administradores."""
    cont = contactos()
    info = cont.get(p["cuit"]) or {}
    n = {k: str(v)[:300] for k, v in (p.get("notif") or {}).items()}
    try:
        from .almacen_claves import razon_social
        rs = razon_social(p["cuit"]) or _cuit_fmt(p["cuit"])
    except Exception:
        rs = _cuit_fmt(p["cuit"])
    detalle = (f"Organismo: {n.get('origen')} {('— ' + n['organismo']) if n.get('organismo') and n.get('organismo') != n.get('origen') else ''}\n"
               f"Fecha: {n.get('fecha')}\nAsunto: {n.get('asunto')}\nEstado: {n.get('estado')}\n")
    if p["a"] == "cliente":
        para, cc = info.get("emails_cliente") or [], [info.get("encargado_email", "")]
        asunto = f"Comunicación de {n.get('origen')} en su domicilio fiscal electrónico"
        cuerpo = (f"Estimados de {rs}:\n\nLes informamos que recibieron una comunicación en su domicilio fiscal "
                  f"electrónico:\n\n{detalle}\nNos ponemos en contacto para ver los pasos a seguir.\n\nSaludos cordiales.\nEstudio")
    else:
        para, cc = cont.get("_admins") or [], []
        asunto = f"Alerta DFE: {rs} — {n.get('asunto', '')[:80]}"
        cuerpo = (f"{p.get('por_nombre') or p.get('por')} marcó esta comunicación para revisar:\n\nCliente: {rs} "
                  f"({_cuit_fmt(p['cuit'])})\n{detalle}{('Motivo: ' + n['motivo']) if n.get('motivo') else ''}\n")
    mid = encolar_mail(para, asunto, cuerpo, cc=cc, motivo=f"DFE {p['a']} {p['cuit']} (pedido por {p.get('por')})")
    enviar_cola()
    est = estado_mail(mid)
    if not para:
        return "sin destinatario: " + ("el cliente no tiene mails cargados" if p["a"] == "cliente" else "ningún admin tiene mail")
    return f"OK mail {est}"


def main(argv=None):
    a = (argv if argv is not None else sys.argv[1:]) or ["evaluar"]
    if a[0] == "evaluar":
        print(evaluar())
    elif a[0] == "enviar":
        print(enviar_cola())
    elif a[0] == "probar-correo" and len(a) > 1:
        encolar_mail([a[1]], "Prueba del monitoreo fiscal", "Si llegó este mail, la casilla está bien configurada.",
                     motivo="prueba")
        print(enviar_cola())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
