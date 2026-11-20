"""Aplicación web del estudio: panel de clientes, alertas, agenda y descarga de informes.
Solo LEE lo que dejan los robots. No tiene acceso a las claves fiscales.
"""
from __future__ import annotations

import re
import json
import os
import secrets
from datetime import date, timedelta
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request, send_file, session, url_for)

from . import analisis, asientos, claves, datos, pedidos, usuarios

app = Flask(__name__)


def _clave_secreta():
    ruta = os.path.join(usuarios.BASE, "secreto.key")
    os.makedirs(usuarios.BASE, exist_ok=True)
    if not os.path.exists(ruta):
        with open(ruta, "w") as f:
            f.write(secrets.token_hex(32))
        os.chmod(ruta, 0o600)
    return open(ruta).read().strip()


app.config.update(SECRET_KEY=_clave_secreta(), SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("ROBOTS_WEB_HTTP") != "1",
                  PERMANENT_SESSION_LIFETIME=timedelta(hours=10))


# ---------------------------------------------------------------- utilidades
@app.template_filter("pesos")
def pesos(v):
    if v is None or v == "":
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return v
    t = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if v < 0 else ''}$ {t}"


@app.template_filter("fecha")
def fecha(v):
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    d = datos._fecha(v)
    return d.strftime("%d/%m/%Y") if d else (v or "—")


app.jinja_env.globals["cuit_fmt"] = datos.cuit_fmt


@app.template_filter("utilidad")
def utilidad(ratio):
    """Relación D/C como utilidad: 1,50 -> "50,00%"; 0,87 -> "−13,00%" (2 decimales, pedido de Gaby 17/11/2026)."""
    try:
        u = (float(ratio) - 1) * 100
    except (TypeError, ValueError):
        return "—"
    return ("−" if u < 0 else "") + f"{abs(u):,.2f}%".replace(",", "X").replace(".", ",").replace("X", ".")


@app.template_filter("dec")
def dec(v, n=2):
    try:
        return f"{float(v):.{n}f}".replace(".", ",")
    except (TypeError, ValueError):
        return "—"


def _ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "")


def _csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


app.jinja_env.globals["csrf"] = _csrf


def _controlar_csrf():
    if request.form.get("csrf") != session.get("csrf"):
        abort(400)


def requiere_login(f):
    @wraps(f)
    def env(*a, **k):
        if "usuario" not in session:
            return redirect(url_for("ingresar", siguiente=request.path))
        return f(*a, **k)
    return env


def requiere_admin(f):
    @wraps(f)
    def env(*a, **k):
        if session.get("rol") != "admin":
            abort(403)
        return f(*a, **k)
    return requiere_login(env)


@app.after_request
def cabeceras(r):
    r.headers["X-Frame-Options"] = "DENY"
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Referrer-Policy"] = "same-origin"
    r.headers["Cache-Control"] = "no-store"
    return r


# ---------------------------------------------------------------- ingreso
@app.route("/ingresar", methods=["GET", "POST"])
def ingresar():
    if request.method == "POST":
        _controlar_csrf()
        u, msg = usuarios.verificar(request.form.get("usuario", ""), request.form.get("clave", ""))
        if u:
            session.clear()
            session.permanent = True
            session.update(usuario=u["usuario"], nombre=u["nombre"], rol=u["rol"])
            usuarios.registrar(u["usuario"], "ingreso", "", _ip())
            sig = request.args.get("siguiente", "")
            return redirect(sig if sig.startswith("/") and not sig.startswith("//") else url_for("inicio"))
        usuarios.registrar(request.form.get("usuario", "")[:30], "ingreso fallido", "", _ip())
        flash(msg, "error")
    return render_template("ingresar.html")


@app.route("/salir")
def salir():
    if "usuario" in session:
        usuarios.registrar(session["usuario"], "salida", "", _ip())
    session.clear()
    return redirect(url_for("ingresar"))


@app.route("/mi-clave", methods=["GET", "POST"])
@requiere_login
def mi_clave():
    if request.method == "POST":
        _controlar_csrf()
        u, _ = usuarios.verificar(session["usuario"], request.form.get("actual", ""))
        if not u:
            flash("La contraseña actual no es correcta", "error")
        elif request.form.get("nueva") != request.form.get("repetir"):
            flash("Las contraseñas nuevas no coinciden", "error")
        else:
            err = usuarios.cambiar_clave(session["usuario"], request.form.get("nueva", ""))
            if err:
                flash(err, "error")
            else:
                usuarios.registrar(session["usuario"], "cambio de contraseña", "", _ip())
                flash("Contraseña cambiada", "ok")
                return redirect(url_for("inicio"))
    return render_template("mi_clave.html")


# ---------------------------------------------------------------- pantallas
ORDEN = {"rojo": 0, "amarillo": 1, "verde": 2, "gris": 3}


@app.route("/")
@requiere_login
def inicio():
    q = request.args.get("q", "").strip().lower()
    filtro = request.args.get("f", "")
    todos = []
    for c in datos.lista_clientes(_solo()):
        if q and q not in c["cuit"] and q not in (c.get("razon_social") or "").lower():
            continue
        todos.append({**c, **datos.situacion(c["cuit"])})
    filas = [x for x in todos if not filtro or x["semaforo"] == filtro]
    filas.sort(key=lambda x: (ORDEN[x["semaforo"]], (x.get("razon_social") or x["cuit"]).upper()))
    cuenta = {k: sum(1 for f in todos if f["semaforo"] == k) for k in ORDEN}
    suma = lambda k: sum(x.get(k) or 0 for x in todos)
    kpi = {"clientes": len(todos), "deuda": suma("deuda_vencida"), "cuotas": suma("cuotas_impagas"),
           "dfe": suma("dfe_sin_abrir"), "ddjj": suma("ddjj")}
    return render_template("inicio.html", filas=filas, q=q, f=filtro, cuenta=cuenta, kpi=kpi, solo_mios=_solo() is not None)


SECCIONES = {"deuda": "Deuda ARCA (vencida)", "por_vencer": "Por vencer", "planes": "Planes de pago", "vencimientos": "Vencimientos",
             "ddjj": "DDJJ / faltas de presentación", "notificaciones": "Notificaciones", "iibb": "Ingresos Brutos",
             "relacion": "Relación débito crédito", "compras": "Compras y APOC", "informes": "Informes Excel",
             "notas": "Notas del equipo", "iva": "Débito / crédito y proyección de IVA",
             "resultado": "Resultado mensual", "fiscalizaciones": "Fiscalizaciones y verificaciones", "agip": "AGIP (Ciudad)",
             "ccma": "Autónomos y Monotributo (CCMA)", "historica": "Deuda histórica (Cuentas Tributarias)"}


def _solo():
    """None = ve todos (administrador). Si no, el conjunto de CUITs que lleva (encargado o equipo). 18/11/2026."""
    if session.get("rol") == "admin":
        return None
    if "_asignados" not in g:
        g._asignados = usuarios.asignados(session.get("usuario", ""))
    return g._asignados


def _puede(cuit) -> bool:
    s = _solo()
    return s is None or cuit in s


def _cliente_info(cuit):
    if not datos.CUIT_RE.match(cuit):
        abort(404)
    if not _puede(cuit):
        abort(403)
    return next((c for c in datos.lista_clientes() if c["cuit"] == cuit), {"cuit": cuit, "razon_social": ""})


@app.route("/cliente/<cuit>")
@requiere_login
def cliente(cuit):
    info = _cliente_info(cuit)
    s = datos.ficha(cuit)
    usuarios.registrar(session["usuario"], "consulta cliente", cuit, _ip())
    mal = any(x.get("estado") == "Clave inválida" for x in info.get("accesos", []))
    pend = [p for p in pedidos.pendientes() if p.get("cuit") == cuit]
    ult = [p for p in pedidos.estado() if p.get("cuit") == cuit][:3]
    return render_template("cliente.html", c=info, s=s, n_notas=len(usuarios.notas(cuit)), claves_mal=mal,
                           robots_pedir=pedidos.ROBOTS, pedidos_pend=pend, pedidos_ult=ult, pedir_listo=pedidos.listo(),
                           dc=usuarios.datos_cliente(cuit), dia_corrida=analisis.dia_de_corrida(
                               cuit, monotributo=bool(s.get("categoria")) and not str(s.get("categoria")).startswith("Responsable")))


@app.route("/cliente/<cuit>/<seccion>")
@requiere_login
def cliente_seccion(cuit, seccion):
    if seccion not in SECCIONES:
        abort(404)
    info = _cliente_info(cuit)
    s = datos.ficha(cuit)
    usuarios.registrar(session["usuario"], f"consulta {seccion}", cuit, _ip())
    org = request.args.get("org", "")
    graf = analisis.grafico_iva(s.get("iva") or [], s.get("proyeccion")) if seccion == "iva" else ""
    return render_template("seccion.html", c=info, s=s, sec=seccion, titulo=SECCIONES[seccion], org=org,
                           notas=usuarios.notas(cuit) if seccion == "notas" else [], grafico=graf,
                           informadas=usuarios.informadas() if seccion == "notificaciones" else {}, pct=analisis.pct,
                           periodo_txt=analisis.periodo_txt)


# ---------------------------------------------------------------- traído de Radar fiscal (17/11/2026)
VISTAS = {"dfe": "Domicilio fiscal electrónico", "deudas": "Deudas vencidas", "por_vencer": "Por vencer", "planes": "Planes de pago",
          "faltas": "Falta de presentación", "iva": "Débito / crédito", "proyeccion": "Proyección de IVA",
          "resultado": "Relación débito crédito", "fiscalizaciones": "Fiscalizaciones y verificaciones"}


@app.route("/cartera/<vista>")
@requiere_login
def cartera(vista):
    if vista not in VISTAS:
        abort(404)
    todos = datos.cartera(_solo())
    usuarios.registrar(session["usuario"], f"cartera {vista}", "", _ip())
    filas, extra = [], {}
    minima = analisis.REGLAS["deuda_minima"]
    if vista == "dfe":
        inf = usuarios.informadas()
        ver = request.args.get("ver", "pendientes")
        org = request.args.get("org", "")
        mios = request.args.get("mios") == "1"
        enc = {cu: (usuarios.datos_cliente(cu) or {}).get("encargado", "") for cu in {c["cuit"] for c in todos}} if mios else {}
        todas = []
        for c in todos:
            for n in c["f"]["notificaciones"]:
                todas.append({**n, "cuit": c["cuit"], "nombre": c["nombre"], "informada": inf.get(n["id"])})
        extra["kpi"] = {"oficio": sum(1 for n in todas if n.get("notificada_sin_leer") and not n["informada"]),
                        "altas": sum(1 for n in todas if n["prioridad"] == 2 and not n["informada"]),
                        "pend": sum(1 for n in todas if not n["informada"] and n["importancia"] != "Baja"),
                        "total": len(todas)}
        for n in todas:
            if ver == "pendientes" and (n["informada"] or n["importancia"] == "Baja"):
                continue
            if org and n["origen"] != org:
                continue
            if mios and enc.get(n["cuit"]) not in (session["usuario"], ""):
                continue
            filas.append(n)
        filas.sort(key=lambda n: (n["prioridad"], bool(n["informada"]), n["nombre"]))
        extra.update(ver=ver, org=org, mios=mios)
    elif vista == "deudas":
        for c in todos:
            f = c["f"]
            arca_ = f["deuda_vencida"] or 0.0
            total = arca_ + (f["deuda_cm"] or 0.0) + (f["agip_deuda"] or 0.0)
            if total >= minima:
                filas.append({**c, "arca": arca_, "cm": f["deuda_cm"] or 0.0, "agip": f["agip_deuda"] or 0.0, "total": total})
        filas.sort(key=lambda x: -x["total"])
        extra["total"] = sum(x["total"] for x in filas)
    elif vista == "por_vencer":
        for c in todos:
            for d in c["f"].get("deudas_por_vencer") or []:
                filas.append({**c, "d": d})
        filas.sort(key=lambda x: (str(x["d"].get("vencimiento") or "9999"), x["nombre"]))
        extra["total"] = sum(x["d"].get("total") or 0 for x in filas)
    elif vista == "planes":
        for c in todos:
            for p in ((c["f"]["mf"] or {}).get("vigentes") or []):
                filas.append({**c, "p": p})
            for a in ((c["f"]["mf"] or {}).get("alertas") or []):
                if a.get("tipo") == "Plan caduco":
                    filas.append({**c, "caduco": a.get("texto", "")})
        filas.sort(key=lambda x: (not x.get("caduco"), -((x.get("p") or {}).get("vencidas_impagas") or 0), x["nombre"]))
    elif vista == "faltas":
        for c in todos:
            for d in ((c["f"]["sct"] or {}).get("ddjj_pendientes") or []):
                filas.append({**c, "d": d})
        filas.sort(key=lambda x: x["nombre"])
    elif vista in ("iva", "proyeccion"):
        for c in todos:
            iva = c["f"].get("iva") or []
            if not iva:
                continue
            filas.append({**c, "ratio": c["f"].get("ratio"), "proy": c["f"].get("proyeccion"), "ultimo": iva[-1]})
        if vista == "iva":
            o = {"Crítico": 0, "Advertencia": 1, "Adecuado": 2}
            filas.sort(key=lambda x: (o.get((x["ratio"] or {}).get("nivel"), 3), (x["ratio"] or {}).get("ratio", 9)))
        else:
            filas = [x for x in filas if x["proy"]]
            filas.sort(key=lambda x: -x["proy"]["saldo"])
            elegido = next((x for x in filas if x["cuit"] == request.args.get("c")), filas[0] if filas else None)
            extra["elegido"] = elegido
            extra["grafico"] = analisis.grafico_iva(elegido["f"]["iva"], elegido["proy"]) if elegido else ""
    elif vista == "resultado":
        for c in todos:
            r = c["f"].get("resultado")
            if r:
                filas.append({**c, "r": r})
        filas.sort(key=lambda x: x["r"]["total"]["resultado"])
    elif vista == "fiscalizaciones":
        for c in todos:
            f = c["f"]
            fi, ag = f.get("fisc") or {}, f.get("agip") or {}
            for k, titulo in (("en_curso", "ARCA · Orden de intervención"), ("fiscalizacion_electronica", "ARCA · Fiscalización electrónica"),
                              ("siace", "ARCA · Control electrónico (SIACE)")):
                for d in fi.get(k) or []:
                    filas.append({**c, "tipo": titulo, "d": d, "fecha": fi.get("fecha")})
            for d in ag.get("fiscalizacion") or []:
                filas.append({**c, "tipo": "AGIP · Fiscalización electrónica", "d": {"Detalle": " · ".join(d)}, "fecha": ag.get("fecha")})
        extra["sin_datos"] = sum(1 for c in todos if not c["f"].get("fisc") and not c["f"].get("agip"))
    return render_template("cartera.html", vista=vista, titulo=VISTAS[vista], filas=filas, x=extra, n=len(todos),
                           pct=analisis.pct, periodo_txt=analisis.periodo_txt, reglas=analisis.REGLAS)


@app.route("/sistema")
@requiere_admin
def sistema():
    def leer(n, defecto):
        try:
            with open(os.path.join(datos.PUBLICO, n), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return defecto
    return render_template("sistema.html", version=leer("version.json", {}), cambios=leer("actualizaciones.json", []),
                           pedidos_listo=pedidos.listo(), claves_listo=claves.listo())


@app.route("/dfe/informada", methods=["POST"])
@requiere_login
def dfe_informada():
    _controlar_csrf()
    id_, cuit = request.form.get("id", ""), request.form.get("cuit", "")
    if not id_.isalnum() or not datos.CUIT_RE.match(cuit):
        abort(400)
    _cliente_info(cuit)
    marcar = request.form.get("marcar") == "1"
    usuarios.marcar_informada(id_, cuit, session["usuario"], session.get("nombre", ""), marcar)
    usuarios.registrar(session["usuario"], "DFE informada" if marcar else "DFE desmarcada", cuit, _ip())
    destino = request.form.get("volver", "")
    return redirect(destino if destino.startswith("/") and not destino.startswith("//") else url_for("cartera", vista="dfe"))


@app.route("/revision/visto", methods=["POST"])
@requiere_login
def revision_visto():
    """Deuda histórica (Convenio / Cuentas Tributarias): el encargado la marca "visto, me ocupo"."""
    _controlar_csrf()
    clave, cuit = request.form.get("clave", ""), request.form.get("cuit", "")
    if not datos.CUIT_RE.match(cuit) or not re.fullmatch(r"(cm|sct|sld|agip|arba):\d{11}:[\w.:-]{1,60}", clave) or f":{cuit}:" not in clave:
        abort(400)
    _cliente_info(cuit)
    enc = (usuarios.datos_cliente(cuit) or {}).get("encargado")
    if session.get("rol") != "admin" and enc and enc != session["usuario"]:
        flash("Ese cliente tiene otro encargado", "error")
    else:
        marcar = request.form.get("marcar") == "1"
        usuarios.marcar_visto(clave, cuit, session["usuario"], session.get("nombre", ""), request.form.get("nota", ""), marcar)
        usuarios.registrar(session["usuario"], "Deuda histórica vista" if marcar else "Deuda histórica desmarcada", clave, _ip())
        flash("Marcada como vista" if marcar else "Vuelve a quedar para revisar", "ok")
    destino = request.form.get("volver", "")
    return redirect(destino if destino.startswith("/") and not destino.startswith("//") else url_for("cliente", cuit=cuit))


@app.route("/dfe/mail", methods=["POST"])
@requiere_login
def dfe_mail():
    """Tablero DFE: 'Reenviar al cliente' / 'Alertar al admin' (el mail lo manda el robot desde la casilla del estudio)."""
    _controlar_csrf()
    id_, cuit, a = request.form.get("id", ""), request.form.get("cuit", ""), request.form.get("a", "")
    if not id_.isalnum() or not datos.CUIT_RE.match(cuit) or a not in ("cliente", "admin"):
        abort(400)
    _cliente_info(cuit)
    n = next((x for x in datos.ficha(cuit)["notificaciones"] if x["id"] == id_), None)
    enc = (usuarios.datos_cliente(cuit) or {}).get("encargado")
    if a == "cliente" and session.get("rol") != "admin" and enc and enc != session["usuario"]:
        flash("Solo el encargado del cliente aprueba el envío al cliente", "error")   # acuerdo Gaby/Tomás 19/11/2026
    elif not n:
        flash("La comunicación ya no figura", "error")
    else:
        try:
            pedidos.encolar_mail_dfe(cuit, a, {k: str(n.get(k) or "")[:300] for k in
                                               ("origen", "organismo", "fecha", "asunto", "estado", "motivo")},
                                     session["usuario"], session.get("nombre", ""))
            usuarios.registrar(session["usuario"], f"DFE: {'reenvío al cliente' if a == 'cliente' else 'alerta al admin'}", cuit, _ip())
            flash("Mail pedido: sale en un minuto (o queda en cola hasta que se configure la casilla del estudio)", "ok")
        except pedidos.ErrorPedido as e:
            flash(str(e), "error")
    destino = request.form.get("volver", "")
    return redirect(destino if destino.startswith("/") and not destino.startswith("//") else url_for("cartera", vista="dfe"))


@app.route("/cliente/<cuit>/pedir", methods=["POST"])
@requiere_login
def pedir_corrida(cuit):
    _controlar_csrf()
    _cliente_info(cuit)
    robot = request.form.get("robot", "")
    try:
        pedidos.encolar(cuit, robot, session["usuario"])
        usuarios.registrar(session["usuario"], f"pidió corrida {robot}", cuit, _ip())
        flash(f"Pedido enviado: {pedidos.ROBOTS[robot]}. Arranca en un minuto (o cuando termine la corrida en curso).", "ok")
    except pedidos.ErrorPedido as e:
        flash(str(e), "error")
    return redirect(url_for("cliente", cuit=cuit))


MEDIOS_VEP = ["Pago Mis Cuentas (Banelco)", "Pagar (Red Link)", "Interbanking", "XN Group"]
CAMPOS_CLIENTE = {
    "condicion_iva": "Condición frente al IVA", "condicion_ganancias": "Ganancias", "bienes_personales": "Bienes Personales",
    "regimen_iibb": "Régimen de Ingresos Brutos", "jurisdicciones_iibb": "Jurisdicciones de IIBB",
    "agente": "Agente de retención / percepción", "mes_cierre": "Mes de cierre", "empleador": "Empleador",
    "convenios": "Convenios colectivos", "encargado": "Encargado del estudio (recibe los avisos)",
    "equipo": "También lo llevan (ven este cliente)",
    "contadores": "Contador/es a cargo", "emails": "Mails del cliente",
    "medios_vep": "Medios de pago del VEP (según sus bancos)",
    "telefonos": "Teléfonos", "whatsapp": "WhatsApp", "observaciones": "Observaciones",
}
OPCIONES_CLIENTE = {
    "condicion_iva": ["", "Responsable inscripto", "Monotributo", "Exento", "No alcanzado"],
    "condicion_ganancias": ["", "Inscripto", "No inscripto", "Exento", "Monotributo"],
    "bienes_personales": ["", "Inscripto", "No inscripto", "Responsable sustituto"],
    "regimen_iibb": ["", "Local", "Convenio Multilateral", "Régimen simplificado", "Exento"],
    "mes_cierre": [""] + ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre",
                          "Octubre", "Noviembre", "Diciembre"],
    "empleador": ["", "Sí", "No", "Casas particulares"],
}


@app.route("/cliente/<cuit>/datos", methods=["GET", "POST"])
@requiere_login
def datos_del_cliente(cuit):
    info = _cliente_info(cuit)
    if request.method == "POST":
        _controlar_csrf()
        nuevos = {k: request.form.get(k, "").strip()[:500] for k in CAMPOS_CLIENTE}
        for k, ops in OPCIONES_CLIENTE.items():
            if nuevos[k] not in ops:
                nuevos[k] = ""
        activos = {u[0] for u in usuarios.listar() if u[3]}
        if nuevos["encargado"] not in activos:
            nuevos["encargado"] = ""
        nuevos["equipo"] = ", ".join(u for u in sorted(activos) if u in request.form.getlist("equipo") and u != nuevos["encargado"])
        if session.get("rol") != "admin":                 # quién lleva el cliente lo decide un administrador
            antes = usuarios.datos_cliente(cuit) or {}
            nuevos["encargado"], nuevos["equipo"] = antes.get("encargado", ""), antes.get("equipo", "")
        nuevos["medios_vep"] = ", ".join(m for m in MEDIOS_VEP if m in request.form.getlist("medios_vep"))
        usuarios.guardar_datos_cliente(cuit, nuevos, session["usuario"])
        usuarios.registrar(session["usuario"], "datos del cliente", cuit, _ip())
        flash("Datos del cliente guardados", "ok")
        return redirect(url_for("cliente", cuit=cuit))
    return render_template("datos_cliente.html", c=info, d=usuarios.datos_cliente(cuit), campos=CAMPOS_CLIENTE,
                           opciones=OPCIONES_CLIENTE, medios_vep=MEDIOS_VEP, encargados=[(u[0], u[1]) for u in usuarios.listar() if u[3]],
                           es_admin=session.get("rol") == "admin")


@app.route("/asignar", methods=["GET", "POST"])
@requiere_login
def asignar_clientes():
    """Pedido de Gaby (19/11/2026): que cada uno marque sus clientes (y los de un compañero, p. ej. Daniela carga los
    de Mariela) sin depender del admin. Un colaborador solo puede poner encargado a un cliente que NO lo tiene,
    o sumar gente al equipo; cambiar un encargado ya puesto sigue siendo del admin."""
    activos = [(u[0], u[1] or u[0]) for u in usuarios.listar() if u[3]]
    ids = {u for u, _ in activos}
    es_admin = session.get("rol") == "admin"
    if request.method == "POST":
        _controlar_csrf()
        cuits = [c for c in request.form.getlist("cuit") if datos.CUIT_RE.match(c)]
        quien = request.form.get("encargado", "")
        modo = request.form.get("modo", "encargado")
        if quien not in ids or modo not in ("encargado", "equipo") or not cuits:
            flash("Elegí al menos un cliente y una persona", "error")
            return redirect(url_for("asignar_clientes", q=request.args.get("q", ""), ver=request.args.get("ver", "")))
        validos = {c["cuit"] for c in datos.lista_clientes()}
        hechos = saltados = 0
        for cuit in cuits:
            if cuit not in validos:
                continue
            d = dict(usuarios.datos_cliente(cuit) or {})
            if modo == "encargado":
                if d.get("encargado") and d["encargado"] != quien and not es_admin:
                    saltados += 1                       # ya tiene encargado: lo cambia el admin
                    continue
                d["encargado"] = quien
                eq = [x.strip() for x in str(d.get("equipo") or "").split(",") if x.strip() and x.strip() != quien]
                d["equipo"] = ", ".join(eq)
            else:
                eq = [x.strip() for x in str(d.get("equipo") or "").split(",") if x.strip()]
                if quien != d.get("encargado") and quien not in eq:
                    eq.append(quien)
                d["equipo"] = ", ".join(sorted(eq))
            usuarios.guardar_datos_cliente(cuit, d, session["usuario"])
            usuarios.registrar(session["usuario"], f"asignar {modo}: {quien}", cuit, _ip())
            hechos += 1
        nombre = dict(activos).get(quien, quien)
        flash(f"{hechos} cliente(s): {nombre} quedó como {'encargado/a' if modo == 'encargado' else 'parte del equipo'}"
              + (f". {saltados} ya tenían otro encargado (eso lo cambia un administrador)." if saltados else "."), "ok")
        return redirect(url_for("asignar_clientes", q=request.args.get("q", ""), ver=request.args.get("ver", "")))
    ver = request.args.get("ver", "sin")
    q = request.args.get("q", "").strip().lower()
    filas = []
    for c in datos.lista_clientes():
        d = usuarios.datos_cliente(c["cuit"]) or {}
        enc = d.get("encargado") or ""
        if ver == "sin" and enc:
            continue
        if ver == "mios" and enc != session["usuario"] and session["usuario"] not in str(d.get("equipo") or ""):
            continue
        if q and q not in (c.get("razon_social") or "").lower() and q.replace("-", "") not in c["cuit"]:
            continue
        filas.append({"cuit": c["cuit"], "nombre": c.get("razon_social") or "", "encargado": dict(activos).get(enc, enc),
                      "equipo": ", ".join(dict(activos).get(x.strip(), x.strip())
                                          for x in str(d.get("equipo") or "").split(",") if x.strip())})
    filas.sort(key=lambda f: f["nombre"] or f["cuit"])
    sin = sum(1 for c in datos.lista_clientes() if not (usuarios.datos_cliente(c["cuit"]) or {}).get("encargado"))
    return render_template("asignar.html", filas=filas[:500], total=len(filas), ver=ver, q=request.args.get("q", ""),
                           activos=activos, es_admin=es_admin, sin=sin)


@app.route("/alertas", methods=["GET", "POST"])
@requiere_login
def alertas():
    """Alertas del día. Cada alerta se puede descartar por un motivo; si a los 30 días sigue igual, vuelve (18/11/2026)."""
    if request.method == "POST":
        _controlar_csrf()
        cuit = request.form.get("cuit", "")
        _cliente_info(cuit)
        accion = request.form.get("accion", "")
        if accion in ("descartar_cliente", "restaurar_cliente"):
            # todas las alertas del cliente de una vez (pedido del 20/11/2026)
            if accion == "restaurar_cliente":
                n = 0
                for clave, d in usuarios.descartes_vigentes().items():
                    if d["cuit"] == cuit:
                        usuarios.restaurar_descarte(clave)
                        n += 1
                usuarios.registrar(session["usuario"], "alertas del cliente restauradas", cuit, _ip())
                flash(f"{n} alerta(s) del cliente volvieron a la lista", "ok")
            else:
                motivo, nota = request.form.get("motivo", ""), request.form.get("nota", "").strip()
                actuales = next((g["alertas"] for g in datos.alertas_del_dia({cuit}) if g["cuit"] == cuit), [])
                if motivo not in usuarios.MOTIVOS_DESCARTE:
                    flash("Elegí el motivo para descartar las alertas del cliente", "error")
                elif motivo == "Otro" and not nota:
                    flash("Con el motivo 'Otro' escribí una nota", "error")
                else:
                    for a in actuales:
                        usuarios.descartar(cuit, a["tipo"], a["texto"], motivo, nota, session["usuario"], session.get("nombre", ""))
                    usuarios.registrar(session["usuario"], f"cliente descartado en alertas ({motivo})", cuit, _ip())
                    flash(f"{len(actuales)} alerta(s) del cliente descartadas: {motivo}. Las que sigan igual vuelven en "
                          f"{usuarios.DIAS_DESCARTE} días; si aparece una nueva, se muestra enseguida.", "ok")
            return redirect(url_for("alertas", ver=request.args.get("ver", "")))
        if accion == "restaurar":
            clave = request.form.get("clave", "")
            d = usuarios.descartes_vigentes().get(clave)
            if d and d["cuit"] == cuit:
                usuarios.restaurar_descarte(clave)
                usuarios.registrar(session["usuario"], "alerta restaurada", cuit, _ip())
                flash("La alerta volvió a la lista", "ok")
        else:
            motivo = request.form.get("motivo", "")
            tipo, texto = request.form.get("tipo", ""), request.form.get("texto", "")
            actuales = next((g["alertas"] for g in datos.alertas_del_dia({cuit}) if g["cuit"] == cuit), [])
            if motivo not in usuarios.MOTIVOS_DESCARTE:
                flash("Elegí el motivo para descartar la alerta", "error")
            elif not any(a["tipo"] == tipo and a["texto"] == texto for a in actuales):
                flash("Esa alerta ya cambió o no está más", "error")
            elif motivo == "Otro" and not request.form.get("nota", "").strip():
                flash("Con el motivo 'Otro' escribí una nota", "error")
            else:
                usuarios.descartar(cuit, tipo, texto, motivo, request.form.get("nota", "").strip(), session["usuario"],
                                   session.get("nombre", ""))
                usuarios.registrar(session["usuario"], f"alerta descartada ({motivo})", f"{cuit} {tipo}"[:120], _ip())
                flash(f"Alerta descartada: {motivo}. Si en {usuarios.DIAS_DESCARTE} días sigue igual, vuelve a aparecer.", "ok")
        return redirect(url_for("alertas", ver=request.args.get("ver", "")))
    desc = usuarios.descartes_vigentes()
    grupos, descartadas = [], []
    for g in datos.alertas_del_dia(_solo()):
        quedan = []
        for a in g["alertas"]:
            d = desc.get(usuarios.clave_alerta(g["cuit"], a["tipo"], a["texto"]))
            if d:
                descartadas.append({**a, **d, "cuit": g["cuit"], "nombre_cliente": g["nombre"],
                                    "vuelve": date.fromisoformat(d["fecha"][:10]) + timedelta(days=usuarios.DIAS_DESCARTE),
                                    "clave": usuarios.clave_alerta(g["cuit"], a["tipo"], a["texto"])})
            else:
                quedan.append(a)
        if quedan:
            grupos.append({**g, "alertas": quedan})
    por_cliente = {}
    for d in descartadas:
        por_cliente.setdefault(d["cuit"], {"cuit": d["cuit"], "nombre": d["nombre_cliente"], "alertas": []})["alertas"].append(d)
    return render_template("alertas.html", grupos=grupos, descartadas=descartadas, desc_grupos=list(por_cliente.values()),
                           motivos=usuarios.MOTIVOS_DESCARTE,
                           dias=usuarios.DIAS_DESCARTE, ver=request.args.get("ver", ""))


@app.route("/mas")
@requiere_login
def mas():
    return render_template("mas.html")


# ---------------------------------------------------------------- asientos contables (pedido de Gaby 18-19/11/2026)
@app.route("/asientos")
@requiere_login
def asientos_inicio():
    return redirect(url_for("pantalla_asientos", tipo="sueldos", **({"cuit": request.args["cuit"]} if request.args.get("cuit") else {})))


def _cliente_asientos():
    clientes = datos.lista_clientes(_solo())
    cuit = request.values.get("cuit", "")
    if cuit and (not datos.CUIT_RE.match(cuit) or not _puede(cuit)):
        abort(403)
    return clientes, cuit, next((c for c in clientes if c["cuit"] == cuit), {"cuit": cuit, "razon_social": ""})


@app.route("/asientos/<tipo>", methods=["GET", "POST"])
@requiere_login
def pantalla_asientos(tipo):
    if tipo not in asientos.TIPOS:
        abort(404)
    clientes, cuit, info = _cliente_asientos()
    puede = bool(cuit) and asientos.puede_revisar(cuit, session["usuario"], session.get("rol", ""))
    if request.method == "POST":
        _controlar_csrf()
        if not cuit:
            abort(400)
        if not puede:
            abort(403)
        if tipo == "sueldos" and request.form.get("accion") == "f931_manual":
            per = request.form.get("periodo", "")
            if not re.fullmatch(r"\d{4}-\d{2}", per):
                abort(400)
            def _imp(k):
                v = (request.form.get(k) or "").strip().replace("$", "").replace(" ", "")
                if not v:
                    return None
                v = v.replace(".", "").replace(",", ".") if "," in v else v
                try:
                    return round(max(0.0, float(v)), 2)
                except ValueError:
                    return None
            rem = _imp("remuneracion")
            if request.form.get("borrar") == "1":
                rem = None
            elif rem is None:
                flash("Cargá la remuneración (número, ej. 800.000,00)", "error")
                return redirect(url_for("pantalla_asientos", tipo=tipo, cuit=cuit))
            asientos.guardar_f931_manual(cuit, per, rem, _imp("cargas"), _imp("aportes"), request.form.get("nota", ""),
                                         session["usuario"])
            usuarios.registrar(session["usuario"], "F.931 completado a mano" if rem is not None else "F.931 manual borrado",
                               f"{cuit} {per}", _ip())
            flash(f"F.931 {per[5:]}/{per[:4]}: " + ("guardado" if rem is not None else "carga manual borrada"), "ok")
        elif tipo == "cuentas":
            vals = {k[7:]: v for k, v in request.form.items() if k.startswith("cuenta_")}
            n = asientos.guardar_cuentas(cuit, vals, session["usuario"])
            usuarios.registrar(session["usuario"], "asientos: cuentas", cuit, _ip())
            flash(f"Equivalencias guardadas ({n} cuentas asignadas).", "ok")
        else:
            clave = request.form.get("clave", "")
            if not re.fullmatch(r"(sueldos|iibb|pagos):[\w\-: .,/()áéíóúñÁÉÍÓÚÑ]{1,120}", clave):
                abort(400)
            asientos.marcar_revisado(clave, cuit, request.form.get("marcar") == "1", request.form.get("nota", ""),
                                     session["usuario"], session.get("nombre", ""))
            usuarios.registrar(session["usuario"], "asientos: revisión", f"{cuit} {clave}", _ip())
        return redirect(url_for("pantalla_asientos", tipo=tipo, cuit=cuit, ver=request.args.get("ver", "")))
    lista, conceptos, ver = [], [], request.args.get("ver", "")
    if cuit:
        usuarios.registrar(session["usuario"], f"asientos {tipo}", cuit, _ip())
        if tipo == "cuentas":
            conceptos = asientos.conceptos_usados(cuit)
        else:
            lista = asientos.armar(cuit, tipo)
            if ver == "pendientes":
                lista = [a for a in lista if a["estado"] == "desbalanceado"]
            lista = list(reversed(lista))[:60]
    pend = asientos.f931_pendientes(cuit) if cuit and tipo == "sueldos" else []
    manual = asientos.f931_manual(cuit) if cuit and tipo == "sueldos" else {}
    return render_template("asientos.html", tipo=tipo, tipos=asientos.TIPOS, clientes=clientes, cuit=cuit, c=info,
                           lista=lista, conceptos=conceptos, puede=puede, ver=ver, pend=pend, manual=manual)


@app.route("/asientos/<tipo>/excel")
@requiere_login
def asientos_excel(tipo):
    if tipo not in asientos.ARMADORES:
        abort(404)
    _, cuit, info = _cliente_asientos()
    if not cuit:
        abort(400)
    lista = asientos.armar(cuit, tipo)
    usuarios.registrar(session["usuario"], f"asientos {tipo} excel", cuit, _ip())
    return send_file(asientos.excel(cuit, info.get("razon_social", ""), tipo, lista), as_attachment=True,
                     download_name=f"asientos_{tipo}_{cuit}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/cliente/<cuit>/nota", methods=["POST"])
@requiere_login
def nueva_nota(cuit):
    _controlar_csrf()
    _cliente_info(cuit)
    texto = request.form.get("texto", "").strip()
    if texto:
        usuarios.agregar_nota(cuit, session["usuario"], session["nombre"], texto)
        usuarios.registrar(session["usuario"], "nota", cuit, _ip())
    return redirect(url_for("cliente_seccion", cuit=cuit, seccion="notas"))


@app.route("/nota/<int:id_>/borrar", methods=["POST"])
@requiere_login
def borrar_nota(id_):
    _controlar_csrf()
    usuarios.borrar_nota(id_, session["usuario"], session.get("rol") == "admin")
    return redirect(request.form.get("volver") or url_for("inicio"))


@app.route("/notas")
@requiere_login
def todas_las_notas():
    nombres = {c["cuit"]: c.get("razon_social") or "" for c in datos.lista_clientes()}
    return render_template("notas.html", notas=[n for n in usuarios.notas(n=300) if _puede(n.get("cuit") if isinstance(n, dict) else n[1])],
                           nombres=nombres)


@app.route("/sugerencias", methods=["GET", "POST"])
@requiere_login
def sugerencias():
    if request.method == "POST":
        _controlar_csrf()
        if request.form.get("accion") == "responder" and session.get("rol") == "admin":
            usuarios.responder_sugerencia(int(request.form["id"]), request.form.get("estado", "Nueva"),
                                          request.form.get("respuesta", ""))
        else:
            texto = request.form.get("texto", "").strip()
            if texto:
                usuarios.agregar_sugerencia(session["usuario"], session["nombre"], request.form.get("tipo", "Idea"), texto)
                usuarios.registrar(session["usuario"], "sugerencia", texto[:60], _ip())
                flash("¡Gracias! Quedó registrada.", "ok")
        return redirect(url_for("sugerencias"))
    return render_template("sugerencias.html", filas=usuarios.sugerencias())


@app.route("/informe/<path:ruta>")
@requiere_login
def bajar_informe(ruta):
    archivo = datos.ruta_informe_segura(ruta)
    if not archivo:
        abort(404)
    m = re.search(r"(?<!\d)(\d{11})(?!\d)", os.path.basename(archivo))
    if _solo() is not None and not (m and _puede(m[1])):
        abort(403)
    usuarios.registrar(session["usuario"], "descarga informe", ruta, _ip())
    return send_file(archivo, as_attachment=True, download_name=os.path.basename(archivo))


@app.route("/agenda")
@requiere_login
def agenda():
    dias = min(max(int(request.args.get("dias", 15) or 15), 1), 60)
    return render_template("agenda.html", filas=datos.agenda(dias, _solo()), dias=dias)


@app.route("/robots")
@requiere_login
def robots():
    ok_ = lambda x: _puede(str(x.get("cuit") or ""))
    return render_template("robots.html", filas=[x for x in datos.ultimas_corridas() if ok_(x)],
                           pend=[x for x in pedidos.pendientes() if ok_(x)],
                           estado=[x for x in pedidos.estado() if ok_(x)], nombres=pedidos.ROBOTS)


# ---------------------------------------------------------------- avisos de cuotas impagas (17/11/2026)
@app.route("/avisos", methods=["GET", "POST"])
@requiere_login
def pantalla_avisos():
    lista = [a for a in pedidos.avisos() if _puede(str(a.get("cuit") or ""))]
    if request.method == "POST":
        _controlar_csrf()
        a = next((x for x in lista if x.get("id") == request.form.get("aviso", "")), None)
        accion = request.form.get("accion", "")
        if not a:
            flash("Ese aviso ya no existe", "error")
        elif a.get("estado") != "para el encargado":
            flash(f"Ese aviso ya está '{a.get('estado')}'", "error")
        elif session.get("rol") != "admin" and a.get("encargado") and a["encargado"] != session["usuario"]:
            flash("Ese cliente tiene otro encargado", "error")
        else:
            try:
                pedidos.encolar_aviso(a, accion, session["usuario"])
                usuarios.registrar(session["usuario"], f"{pedidos.AVISOS.get(accion, accion)}", a["cuit"], _ip())
                flash("Pedido: el aviso sale en un minuto" + (" (el VEP lo genera el robot)" if accion == "aviso_vep" else ""), "ok")
            except pedidos.ErrorPedido as e:
                flash(str(e), "error")
        return redirect(url_for("pantalla_avisos", ver=request.args.get("ver", "")))
    ver = request.args.get("ver", "mios")
    if ver == "mios":
        lista = [a for a in lista if a.get("encargado") in (session["usuario"], "", None)]
    abiertos = [a for a in lista if a.get("estado") != "resuelto"]
    resueltos = [a for a in lista if a.get("estado") == "resuelto"][:50]
    pend = {p.get("aviso") for p in pedidos.pendientes() if p.get("aviso")}
    revisar = []                                  # deuda histórica (Convenio / Cuentas Tributarias) sin revisar
    for c in datos.lista_clientes(_solo()):
        enc = (usuarios.datos_cliente(c["cuit"]) or {}).get("encargado") or ""
        if ver == "mios" and enc not in (session["usuario"], ""):
            continue
        for x in datos.situacion(c["cuit"])["revisar"]:
            revisar.append({**x, "cuit": c["cuit"], "nombre": c.get("razon_social") or "", "encargado": enc})
    return render_template("avisos.html", abiertos=abiertos, resueltos=resueltos, ver=ver, pend=pend, revisar=revisar)


@app.route("/actividad")
@requiere_admin
def actividad():
    return render_template("actividad.html", filas=usuarios.actividad(), usuarios=usuarios.listar())


@app.route("/asignaciones", methods=["GET", "POST"])
@requiere_admin
def asignaciones():
    """Planilla de clientes (18/11/2026): quién lleva cada cliente, sus datos, claves y altas nuevas."""
    from . import asignaciones as asg
    activos = [u for u in usuarios.listar() if u[3]]
    clientes = datos.lista_clientes()
    if request.method == "POST":
        _controlar_csrf()
        f = request.files.get("planilla")
        if not f or not f.filename.lower().endswith(".xlsx"):
            flash("Subí la planilla en formato Excel (.xlsx)", "error")
            return redirect(url_for("asignaciones"))
        contenido = f.read(10_000_001)
        if len(contenido) > 10_000_000:
            flash("La planilla es demasiado grande", "error")
            return redirect(url_for("asignaciones"))
        try:
            filas, errores = asg.leer(contenido, {u[0] for u in activos}, CAMPOS_CLIENTE, OPCIONES_CLIENTE, MEDIOS_VEP)
        except ImportError:
            flash("Falta instalar openpyxl en la web (se instala sola con la próxima actualización)", "error")
            return redirect(url_for("asignaciones"))
        finally:
            contenido = None                                   # el archivo no se guarda en ningún lado
        conocidos = {c["cuit"]: c.get("razon_social") or "" for c in clientes}
        cambiados = altas = n_claves = 0
        for cuit, x in filas.items():
            nuevo_cli = cuit not in conocidos
            if nuevo_cli:
                if not claves.cuit_valido(cuit):
                    errores.append(f"Fila {x['fila']}: el CUIT {cuit} no es válido")
                    continue
                if "ARCA" not in x["claves"] or not x["razon_social"]:
                    errores.append(f"Fila {x['fila']} ({cuit}): cliente nuevo sin Razón social o sin Clave fiscal ARCA (no se dio de alta)")
                    continue
            # claves: un sobre cifrado por clave (la de ARCA primero: da de alta al cliente nuevo)
            enviados = []
            for org in sorted(x["claves"], key=lambda o: o != "ARCA"):
                u, k = x["claves"][org]
                try:
                    claves.encolar(cuit, x["razon_social"] or conocidos.get(cuit, ""), org, u or cuit, k, session["usuario"])
                    enviados.append(org)
                except claves.ErrorClaves as e:
                    errores.append(f"Fila {x['fila']} ({cuit}) {org}: {e}")
            x["claves"] = None
            if enviados:
                n_claves += len(enviados)
                usuarios.registrar(session["usuario"], "clave enviada por planilla", f"{cuit} {', '.join(enviados)}", _ip())
            if nuevo_cli and "ARCA" not in enviados:
                continue
            altas += nuevo_cli
            d = usuarios.datos_cliente(cuit) or {}
            nuevos = {**d, **x["datos"]}
            if nuevos != d:
                usuarios.guardar_datos_cliente(cuit, nuevos, session["usuario"])
                cambiados += 1
        filas = None
        usuarios.registrar(session["usuario"], "planilla de clientes",
                           f"{cambiados} con datos cambiados, {altas} altas, {n_claves} claves", _ip())
        flash(f"Planilla importada: {cambiados} cliente(s) con datos cambiados, {altas} alta(s) nueva(s), "
              f"{n_claves} clave(s) enviada(s) al robot (las comprueba en unos minutos). "
              "Si la planilla tenía claves, borrá el archivo de tu computadora.", "ok")
        for e in errores[:40]:
            flash(e, "error")
        if len(errores) > 40:
            flash(f"… y {len(errores) - 40} observaciones más", "error")
        return redirect(url_for("asignaciones"))
    if request.args.get("bajar"):
        try:
            cont = asg.generar(clientes, {c["cuit"]: usuarios.datos_cliente(c["cuit"]) or {} for c in clientes},
                               [(u[0], u[1], u[2]) for u in activos], CAMPOS_CLIENTE, OPCIONES_CLIENTE, MEDIOS_VEP)
        except ImportError:
            flash("Falta instalar openpyxl en la web (se instala sola con la próxima actualización)", "error")
            return redirect(url_for("asignaciones"))
        usuarios.registrar(session["usuario"], "bajó la planilla de clientes", "", _ip())
        from io import BytesIO
        return send_file(BytesIO(cont), as_attachment=True, download_name="planilla_clientes.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resumen = {}
    sin = 0
    for c in clientes:
        d = usuarios.datos_cliente(c["cuit"]) or {}
        sin += not d.get("encargado")
        for u in {d.get("encargado")} | {x.strip() for x in str(d.get("equipo") or "").split(",")}:
            if u:
                resumen[u] = resumen.get(u, 0) + 1
    return render_template("asignaciones.html", activos=activos, resumen=resumen, sin=sin, total=len(clientes),
                           claves_listo=claves.listo())


@app.route("/usuarios", methods=["GET", "POST"])
@requiere_admin
def pantalla_usuarios():
    if request.method == "POST":
        _controlar_csrf()
        accion = request.form.get("accion", "")
        u = request.form.get("usuario", "").strip().lower()
        err = ""
        if accion == "crear":
            err = usuarios.crear(u, request.form.get("nombre", ""), request.form.get("clave", ""),
                                 "admin" if request.form.get("rol") == "admin" else "colaborador")
            if not err:
                usuarios.registrar(session["usuario"], "alta de usuario", u, _ip())
                flash(f"Usuario '{u}' creado. Pasale la contraseña en persona.", "ok")
        elif not usuarios.existe(u):
            err = "No existe ese usuario"
        elif accion == "clave":
            err = usuarios.cambiar_clave(u, request.form.get("clave", ""))
            if not err:
                usuarios.registrar(session["usuario"], "cambio de contraseña de usuario", u, _ip())
                flash(f"Contraseña de '{u}' cambiada.", "ok")
        elif accion == "email":
            err = usuarios.poner_email(u, request.form.get("email", ""))
            if not err:
                usuarios.registrar(session["usuario"], "mail de usuario", u, _ip())
                flash(f"Mail de '{u}' guardado.", "ok")
        elif accion in ("baja", "alta"):
            if accion == "baja" and u == session["usuario"]:
                err = "No podés darte de baja a vos mismo"
            else:
                err = usuarios.poner_activo(u, accion == "alta")
                if not err:
                    usuarios.registrar(session["usuario"], f"{accion} de usuario", u, _ip())
                    flash(f"Usuario '{u}': {accion}.", "ok")
        else:
            err = "Acción desconocida"
        if err:
            flash(err, "error")
        return redirect(url_for("pantalla_usuarios"))
    return render_template("usuarios.html", lista=usuarios.listar())


def _sin_cache(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _procesar_claves(cuit, razon, hay_razon):
    """Lee los campos del formulario y encola un sobre por cada clave escrita. No devuelve ni guarda claves."""
    enviados, err = [], ""
    for org in claves.ORGANISMOS:
        k = request.form.get("k_" + org, "")
        if not k:
            continue
        u = request.form.get("u_" + org, "") if org == "ARCA" else ""
        if u and not claves.cuit_valido("".join(ch for ch in u if ch.isdigit())):
            err = "El usuario de ARCA, si lo completás, tiene que ser un CUIT válido"
            break
        u = "".join(ch for ch in u if ch.isdigit())
        try:
            claves.encolar(cuit, razon, org, u or cuit, k, session["usuario"])
        except claves.ErrorClaves as e:
            err = str(e)
            break
        usuarios.registrar(session["usuario"], "clave enviada" if not hay_razon else "alta de cliente / clave enviada",
                           f"{cuit} {org}", _ip())
        enviados.append(org)
    return enviados, err


@app.route("/clientes/nuevo", methods=["GET", "POST"])
@requiere_login
def cliente_nuevo():
    if request.method == "POST":
        _controlar_csrf()
        cuit = "".join(ch for ch in request.form.get("cuit", "") if ch.isdigit())
        razon = request.form.get("razon", "").strip()
        if not claves.cuit_valido(cuit):
            flash("El CUIT no es válido: revisá los números", "error")
        elif not razon:
            flash("Falta el nombre o razón social", "error")
        elif not request.form.get("k_ARCA"):
            flash("Para dar de alta un cliente hace falta al menos la clave fiscal de ARCA", "error")
        else:
            env, err = _procesar_claves(cuit, razon, True)
            if env and session.get("rol") != "admin" and not (usuarios.datos_cliente(cuit) or {}).get("encargado"):
                usuarios.guardar_datos_cliente(cuit, {**(usuarios.datos_cliente(cuit) or {}), "encargado": session["usuario"]},
                                               session["usuario"])
            if env:
                flash(f"Cliente enviado al robot ({', '.join(env)}). Lo da de alta y comprueba que la clave funcione "
                      "en unos minutos. La clave ya no se muestra.", "ok")
            if err:
                flash(err, "error")
            if env:
                return redirect(url_for("cliente_nuevo"))
        return _sin_cache(app.make_response(render_template(
            "claves.html", nuevo=True, c={"cuit": cuit, "razon_social": razon}, orgs=claves.ORGANISMOS,
            pend=claves.pendientes(), res=claves.resultados(), listo=claves.listo())))
    return _sin_cache(app.make_response(render_template(
        "claves.html", nuevo=True, c={"cuit": "", "razon_social": ""}, orgs=claves.ORGANISMOS,
        pend=claves.pendientes(), res=claves.resultados(), listo=claves.listo())))


@app.route("/cliente/<cuit>/claves", methods=["GET", "POST"])
@requiere_login
def cliente_claves(cuit):
    info = _cliente_info(cuit)
    if request.method == "POST":
        _controlar_csrf()
        env, err = _procesar_claves(cuit, "", False)
        if env:
            flash(f"Clave nueva enviada al robot ({', '.join(env)}). La comprueba en unos minutos. "
                  "La clave ya no se muestra.", "ok")
        elif not err:
            flash("No escribiste ninguna clave nueva", "error")
        if err:
            flash(err, "error")
        return redirect(url_for("cliente_claves", cuit=cuit))
    return _sin_cache(app.make_response(render_template(
        "claves.html", nuevo=False, c=info, orgs=claves.ORGANISMOS,
        pend=[p for p in claves.pendientes() if p["cuit"] == cuit], res=[r for r in claves.resultados() if r.get("cuit") == cuit],
        listo=claves.listo())))


@app.route("/manifest.webmanifest")
def manifest():
    r = app.send_static_file("manifest.webmanifest")
    r.mimetype = "application/manifest+json"
    return r


@app.errorhandler(403)
def _403(e):
    return render_template("error.html", msg="No tenés permiso para ver esta página."), 403


@app.errorhandler(404)
def _404(e):
    return render_template("error.html", msg="No se encontró lo pedido."), 404
