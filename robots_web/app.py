"""Aplicación web del estudio: panel de clientes, alertas, agenda y descarga de informes.
Solo LEE lo que dejan los robots. No tiene acceso a las claves fiscales.
"""
from __future__ import annotations

import re
from io import BytesIO
import json
import os
import glob
import secrets
from datetime import date, datetime, timedelta
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
    """Tablero de clientes (rediseñado el 20/11/2026: filtros por tema y por encargado, búsqueda al tipear, orden por
    columna y un resumen corto de 'qué pasa' por cliente). Los filtros corren en el navegador; ?q= y ?f= siguen andando."""
    try:                                                # fichas: completar lo vacío con lo que bajaron los robots
        import threading
        threading.Thread(target=datos.completar_todos, daemon=True).start()
    except Exception:
        pass
    q = request.args.get("q", "").strip()
    filtro = request.args.get("f", "")
    es_admin = _solo() is None
    enc = usuarios.encargados()
    nombres = {u[0]: (u[1] or u[0]) for u in usuarios.listar()}
    hoy = date.today()
    filas = []
    for c in datos.lista_clientes(_solo()):
        x = {**c, **datos.situacion(c["cuit"])}
        x["clave_mal"] = any(a.get("estado") == "Clave inválida" for a in (c.get("accesos") or []))
        try:
            x["dias"] = (hoy - date.fromisoformat(str(x.get("fecha") or "")[:10])).days
        except ValueError:
            x["dias"] = None
        x["encargado"] = enc.get(c["cuit"], "")
        x["encargado_nombre"] = nombres.get(x["encargado"], x["encargado"])
        x["tags"] = _que_pasa(x)
        filas.append(x)
    filas.sort(key=lambda x: (ORDEN[x["semaforo"]], (x.get("razon_social") or x["cuit"]).upper()))
    cuenta = {k: sum(1 for f in filas if f["semaforo"] == k) for k in ORDEN}
    temas = [  # (id, título, cuántos clientes, total en pesos o None)
        ("deuda", "Deuda vencida", sum(1 for x in filas if x.get("deuda_vencida")), sum(x.get("deuda_vencida") or 0 for x in filas)),
        ("ddjj", "DDJJ sin presentar", sum(1 for x in filas if x.get("ddjj")), None),
        ("cuotas", "Cuotas impagas", sum(1 for x in filas if x.get("cuotas_impagas")), None),
        ("dfe", "Notificaciones sin abrir", sum(1 for x in filas if x.get("dfe_sin_abrir")), None),
        ("clave", "Clave inválida", sum(1 for x in filas if x["clave_mal"]), None),
        ("viejos", "Sin actualizar (+10 días)", sum(1 for x in filas if x["dias"] is not None and x["dias"] > 10), None),
    ]
    encargados_lista = sorted({x["encargado"] for x in filas if x["encargado"]}, key=lambda u: nombres.get(u, u).upper())
    return render_template("inicio.html", filas=filas, q=q, f=filtro, cuenta=cuenta, temas=temas, total=len(filas),
                           solo_mios=not es_admin, es_admin=es_admin, nombres=nombres, encargados_lista=encargados_lista,
                           sin_encargado=sum(1 for x in filas if not x["encargado"]),
                           aviso_oficina=datos.aviso_oficina() if session.get("rol") == "admin" else None)


def _que_pasa(r: dict) -> list[tuple]:
    """Etiquetas cortas de lo que NO está en las columnas del tablero (deuda, DDJJ, cuotas y notificaciones ya tienen la suya)."""
    t = []
    if r.get("agente_impago"):
        t.append(("rojo", "🚨 retenciones/percepciones no depositadas"))
    if r.get("ddjj_determinativas"):
        t.append(("rojo", f"🚨 {len(r['ddjj_determinativas'])} DDJJ determinativa(s) sin presentar"))
    if r.get("caducos"):
        t.append(("rojo", f"{r['caducos']} plan caduco" if r["caducos"] == 1 else f"{r['caducos']} planes caducos"))
    if r.get("revisar"):
        t.append(("rojo", "deuda histórica a revisar"))
    if r.get("fiscalizaciones"):
        t.append(("rojo", "fiscalización abierta"))
    if r.get("ccma_impagos"):
        t.append(("rojo", "autónomos/monotributo impago"))
    if r.get("arba_altas"):
        t.append(("rojo", "aviso de ARBA"))
    if r.get("agip_altas"):
        t.append(("rojo", "aviso de AGIP"))
    rt = r.get("ratio") or {}
    if rt and (rt.get("meses") or 0) >= 6 and rt.get("nivel") in ("Crítico", "Advertencia"):
        t.append(("rojo" if rt["nivel"] == "Crítico" else "ambar", f"D/C {rt['ratio']:.2f}".replace(".", ",")))
    if (r.get("agip_deuda") or 0) > 0:
        t.append(("ambar", "deuda AGIP"))
    if r.get("deuda_cm"):
        t.append(("ambar", "deuda Convenio"))
    if r.get("cuotas_15"):
        t.append(("ambar", "cuota vence en 15 días"))
    if r.get("errores"):
        t.append(("gris", "corrida con errores"))
    return t


SECCIONES = {"deuda": "Deuda ARCA (vencida)", "por_vencer": "Por vencer", "planes": "Planes de pago", "vencimientos": "Vencimientos",
             "ddjj": "DDJJ / faltas de presentación", "notificaciones": "Notificaciones", "iibb": "Ingresos Brutos",
             "relacion": "Relación débito crédito", "compras": "Compras y APOC", "informes": "Informes Excel",
             "notas": "Notas del equipo", "iva": "Débito / crédito y proyección de IVA",
             "resultado": "Resultado mensual", "fiscalizaciones": "Fiscalizaciones y verificaciones", "agip": "AGIP (Ciudad)",
             "ccma": "Autónomos y Monotributo (CCMA)", "historica": "Deuda histórica (Cuentas Tributarias)",
             "ventas_bancos": "Reporte de ventas para bancos"}


def _ve_todos() -> bool:
    """Administrador o supervisor (27/11/2026): ve y atiende a todos los clientes."""
    return session.get("rol") in ("admin", "supervisor")


def _solo():
    """None = ve todos (administrador o supervisor). Si no, el conjunto de CUITs que lleva (encargado o equipo). 18/11/2026."""
    if _ve_todos():
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
    try:
        datos.completar_desde_registral(cuit)       # Sistema Registral de ARCA: completa lo vacío (25/11/2026, Gabriel)
    except Exception:
        pass
    try:
        datos.completar_regimen(cuit)               # régimen de IIBB deducido (SIFERE / ARBA) si estaba vacío (25/11/2026)
    except Exception:
        pass
    s = datos.ficha(cuit)
    usuarios.registrar(session["usuario"], "consulta cliente", cuit, _ip())
    al_dia = datos.claves_al_dia(cuit)
    mal = any(v["estado"] in ("invalida", "rechazada") for v in al_dia.values())
    pend = [p for p in pedidos.pendientes() if p.get("cuit") == cuit]
    ult = [p for p in pedidos.estado() if p.get("cuit") == cuit][:3]
    return render_template("cliente.html", c=info, s=s, n_notas=len(usuarios.notas(cuit)), claves_mal=mal, claves_al_dia=al_dia,
                           robots_pedir=pedidos.ROBOTS, pedidos_pend=pend, pedidos_ult=ult, pedir_listo=pedidos.listo(),
                           dc=usuarios.datos_cliente(cuit), dia_corrida=analisis.dia_de_corrida(
                               cuit, monotributo=bool(s.get("categoria")) and not str(s.get("categoria")).startswith("Responsable")))


def _ventas_bancos(cuit):
    """Reporte de ventas para bancos desde el Libro IVA (Portal IVA), 20/11/2026."""
    from . import reportes
    libro = analisis._meses(cuit, "libro_iva")
    pers = sorted(libro)
    if not pers:
        return None, libro
    y, m = map(int, pers[-1].split("-"))
    defecto_desde = f"{y - 1}-{m + 1:02d}" if m < 12 else f"{y}-01"
    desde = request.args.get("desde") or defecto_desde
    hasta = request.args.get("hasta") or pers[-1]
    if not (re.fullmatch(r"\d{4}-\d{2}", desde) and re.fullmatch(r"\d{4}-\d{2}", hasta)) or desde > hasta:
        desde, hasta = defecto_desde, pers[-1]
    return reportes.ventas_bancos(libro, desde, hasta), libro


@app.route("/cliente/<cuit>/percepciones/<formato>")
@requiere_login
def percepciones_bajar(cuit, formato):
    """Percepciones sin factura en el Libro IVA: Excel o versión para imprimir, para que el encargado busque los
    comprobantes (pedido de Gaby, 22/11/2026)."""
    info = _cliente_info(cuit)
    pc = datos._leer(os.path.join(datos.DATOS, cuit, "conciliacion", "percepciones.json"))
    if not pc or formato not in ("excel", "imprimir"):
        abort(404)
    from . import reportes
    nombre = info.get("razon_social") or datos.cuit_fmt(cuit)
    nombres = reportes.nombres_proveedores(cuit)
    usuarios.registrar(session["usuario"], f"percepciones sin factura ({formato})", cuit, _ip())
    if formato == "imprimir":
        fac, ncs = reportes.percepciones_filas(pc, nombres)
        return render_template("percepciones_imprimir.html", pc=pc, fac=fac, ncs=ncs, nombre=nombre, cuit=cuit, hoy=date.today())
    from io import BytesIO
    try:
        contenido = reportes.percepciones_excel(pc, nombre, cuit, nombres)
    except Exception as e:                            # 22/11/2026: que no quede un error 500 sin explicación
        app.logger.exception("Excel de percepciones %s", cuit)
        flash(f"No se pudo armar el Excel ({type(e).__name__}: {str(e)[:150]}). Avisar para revisarlo; "
              "mientras tanto se puede usar 'Imprimir / PDF'.", "error")
        return redirect(url_for("cliente_seccion", cuit=cuit, seccion="relacion"))
    return send_file(BytesIO(contenido), as_attachment=True,
                     download_name=f"percepciones_sin_factura_{cuit}_{date.today().isoformat()}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/cliente/<cuit>/ventas_bancos/<formato>")
@requiere_login
def ventas_bancos_bajar(cuit, formato):
    info = _cliente_info(cuit)
    r, _ = _ventas_bancos(cuit)
    if not r or formato not in ("excel", "imprimir"):
        abort(404)
    nombre = info.get("razon_social") or datos.cuit_fmt(cuit)
    cond = (usuarios.datos_cliente(cuit) or {}).get("condicion_iva", "")
    usuarios.registrar(session["usuario"], f"reporte de ventas para bancos ({formato})", f"{cuit} {r['desde']} a {r['hasta']}", _ip())
    if formato == "imprimir":
        from . import reportes
        return render_template("ventas_bancos_imprimir.html", r=r, nombre=nombre, cuit=cuit, condicion=cond, hoy=date.today(),
                               meses_txt=reportes.MESES_TXT)
    from io import BytesIO
    from . import reportes
    return send_file(BytesIO(reportes.ventas_bancos_excel(r, nombre, cuit, cond)), as_attachment=True,
                     download_name=f"ventas_{cuit}_{r['desde']}_a_{r['hasta']}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


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
    if seccion == "deuda":
        s = {**s, "dc": usuarios.datos_cliente(cuit)}
    if seccion == "ventas_bancos":
        s = {**s, "vb": _ventas_bancos(cuit)[0], "vb_periodos": sorted(analisis._meses(cuit, "libro_iva"))}
    return render_template("seccion.html", c=info, s=s, sec=seccion, hoy_iso=date.today().isoformat(), titulo=SECCIONES[seccion], org=org,
                           notas=usuarios.notas(cuit) if seccion == "notas" else [], grafico=graf,
                           informadas=usuarios.informadas() if seccion == "notificaciones" else {}, pct=analisis.pct,
                           medios_vep_todos=MEDIOS_VEP_DEUDA, vep_deuda_listo=VEP_DEUDA_LISTO,
                           periodo_txt=analisis.periodo_txt)


# ---------------------------------------------------------------- traído de Radar fiscal (17/11/2026)
VISTAS = {"dfe": "Domicilio fiscal electrónico", "deudas": "Deudas vencidas", "por_vencer": "Por vencer", "planes": "Planes de pago",
          "faltas": "Falta de presentación", "iva": "Débito / crédito", "iva_mes": "IVA del mes en curso",
          "proyeccion": "Proyección de IVA (tendencia)",
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
        # reporte de falta de presentación de todos los clientes (20/11/2026): filtros por impuesto y encargado + Excel
        imp_f, enc_f = request.args.get("impuesto", ""), request.args.get("encargado", "")
        encs = {c["cuit"]: (usuarios.datos_cliente(c["cuit"]) or {}).get("encargado") or "" for c in todos}
        impuestos = set()
        for c in todos:
            for d in ((c["f"]["sct"] or {}).get("ddjj_pendientes") or []):
                impuestos.add(d.get("impuesto") or "")
                if imp_f and d.get("impuesto") != imp_f:
                    continue
                if enc_f and encs.get(c["cuit"]) != (enc_f if enc_f != "-" else ""):
                    continue
                filas.append({**c, "d": d, "encargado": encs.get(c["cuit"]), "fecha": c["f"].get("fecha")})
        filas.sort(key=lambda x: (x["nombre"], str(x["d"].get("vencimiento") or "")))
        extra.update(impuestos=sorted(i for i in impuestos if i), imp_f=imp_f, enc_f=enc_f,
                     encargados=[(u[0], u[1]) for u in usuarios.listar() if u[3]], n_clientes=len({f["cuit"] for f in filas}))
        if request.args.get("excel"):
            from io import BytesIO
            from . import reportes
            filtro = " · ".join(x for x in [f"impuesto {imp_f}" if imp_f else "",
                                            f"encargado {enc_f if enc_f != '-' else '(sin encargado)'}" if enc_f else "",
                                            "solo mis clientes" if _solo() is not None else "todos los clientes"] if x)
            usuarios.registrar(session["usuario"], "reporte de faltas de presentación (Excel)", filtro, _ip())
            return send_file(BytesIO(reportes.faltas_excel(filas, filtro)), as_attachment=True,
                             download_name=f"faltas_de_presentacion_{date.today().isoformat()}.xlsx",
                             mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
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
    elif vista == "iva_mes":
        # 25/11/2026 (especificación de Gaby, parte 2): todos los clientes, ordenados por lo estimado a pagar del mes
        enc = request.args.get("enc", "")
        nombres = {u[0]: (u[1] or u[0]) for u in usuarios.listar()}
        quienes = set()
        for c in todos:
            ec = [m for m in c["f"].get("iva_en_curso") or [] if m.get("en_curso")]
            if not ec:
                continue
            d_ = usuarios.datos_cliente(c["cuit"]) or {}
            lleva = ({d_.get("encargado") or ""} | {x.strip() for x in str(d_.get("equipo") or "").split(",")}) - {""}
            quienes |= lleva
            if enc and (enc not in lleva if enc != "-" else lleva):
                continue
            filas.append({**c, "m": ec[0], "encargado": nombres.get(d_.get("encargado") or "", d_.get("encargado") or "")})
        filas.sort(key=lambda x: -x["m"]["estimado"])
        extra.update(enc=enc, quienes=sorted(quienes, key=lambda u: nombres.get(u, u).upper()), nombres=nombres,
                     total=round(sum(x["m"]["estimado"] for x in filas if x["m"]["estimado"] > 0), 2))
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
                           pedidos_listo=pedidos.listo(), claves_listo=claves.listo(),
                           paquete=datos.paquete_oficina(), oficina=datos.oficina_instalada())


@app.route("/sistema/oficina/<archivo>")
@requiere_admin
def paquete_oficina(archivo):
    """Paquete para la máquina "robots" de la oficina (Gaby 28/11/2026). Solo administradores."""
    p = datos.paquete_oficina()
    if not p or archivo not in (p["archivo"], "actualizar_oficina.sh"):
        abort(404)
    usuarios.registrar(session["usuario"], "bajó el paquete de la oficina", archivo, _ip())
    return send_file(os.path.join(datos.PUBLICO, "paquete_oficina", archivo), as_attachment=True, download_name=archivo)


@app.route("/sistema/oficina_instalada", methods=["POST"])
@requiere_admin
def oficina_instalada():
    _controlar_csrf()
    p = datos.paquete_oficina()
    if p:
        datos.marcar_oficina(p["version"], session["usuario"])
        usuarios.registrar(session["usuario"], "instaló el paquete en la oficina", p["version"], _ip())
        flash(f"Anotado: la oficina tiene la versión {p['version']}.", "ok")
    return redirect(request.form.get("volver") if (request.form.get("volver") or "").startswith("/") else url_for("sistema"))


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
    if not datos.CUIT_RE.match(cuit) or not re.fullmatch(r"(cm|sct|sld|agip|arba|perc|mono):\d{11}:[\w.:-]{1,60}", clave) or f":{cuit}:" not in clave:
        abort(400)
    _cliente_info(cuit)
    enc = (usuarios.datos_cliente(cuit) or {}).get("encargado")
    if not _ve_todos() and enc and enc != session["usuario"]:
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
    if a == "cliente" and not _ve_todos() and enc and enc != session["usuario"]:
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
    vuelta = request.form.get("volver", "")
    fc = ""
    if robot == "planes_todos" and request.form.get("fecha_cierre"):
        try:
            fc = date.fromisoformat(request.form["fecha_cierre"]).isoformat()
        except ValueError:
            flash("Fecha de cierre inválida", "error")
            return redirect(vuelta if vuelta.startswith(f"/cliente/{cuit}") else url_for("cliente", cuit=cuit))
    try:
        pedidos.encolar(cuit, robot, session["usuario"], fc)
        usuarios.registrar(session["usuario"], f"pidió corrida {robot}", cuit, _ip())
        flash(f"Pedido enviado: {pedidos.ROBOTS[robot]}" + (f" al {fc[8:]}/{fc[5:7]}/{fc[:4]}" if fc else "") + ". Arranca en un minuto (o cuando termine la corrida en curso).", "ok")
    except pedidos.ErrorPedido as e:
        flash(str(e), "error")
    return redirect(vuelta if vuelta.startswith(f"/cliente/{cuit}") else url_for("cliente", cuit=cuit))


MEDIOS_VEP = ["Pago Mis Cuentas (Banelco)", "Pagar (Red Link)", "Interbanking", "XN Group"]
# VEP de deuda (tildar conceptos + medio de pago, 20/11/2026): la web está lista; se habilita cuando el robot tenga
# relevada la pantalla de ARCA donde se genera (Cuentas Tributarias -> Deudas -> Generar VEP).
VEP_DEUDA_LISTO = True                       # relevado con Tomás el 20/11/2026 (robots/robot_vep_deuda.py)
MEDIOS_VEP_DEUDA = MEDIOS_VEP + ["Pago con QR"]


def _lineas(txt: str) -> list[dict]:
    """'Alquiler; 350000' o 'Comisiones; 0,5%' por renglón."""
    out = []
    for l in (txt or "").splitlines()[:60]:
        if ";" not in l:
            continue
        c, v = [x.strip() for x in l.split(";", 1)]
        num = re.sub(r"[^\d,.\-]", "", v)
        num = float(num.replace(".", "").replace(",", ".")) if re.search(r",\d{1,2}$", num) or num.count(".") > 1 else float(num or 0)
        out.append({"concepto": c[:80], **({"pct_ventas": num, "importe": 0.0} if "%" in v else {"importe": num, "pct_ventas": 0.0})})
    return out


@app.route("/cliente/<cuit>/cashflow", methods=["GET", "POST"])
@requiere_login
def cashflow(cuit):
    """Cash flow proyectado para bancos / aseguradoras (Gaby 26/11/2026)."""
    from . import cashflow as cf
    info = _cliente_info(cuit)
    nombre = info.get("razon_social") or datos.cuit_fmt(cuit)
    if request.method == "POST":
        _controlar_csrf()
        s = cf.supuestos(cuit)
        num = lambda k, d=0.0: float((request.form.get(k) or str(d)).replace(".", "").replace(",", ".")) if re.search(r",", request.form.get(k) or "") else float(request.form.get(k) or d)
        try:
            for k in ("saldo_inicial", "inflacion", "inflacion_costos", "aumento_nomina", "crecimiento", "impuesto_dc",
                      "gastos_bancarios"):
                s[k] = num(k, s.get(k) or 0)
            for k in ("meses", "dias_cobro", "dias_pago", "meses_base"):
                s[k] = int(num(k, s.get(k) or 0))
            s["prestamo"] = {"monto": num("p_monto"), "tasa_anual": num("p_tasa"), "cuotas": int(num("p_cuotas", 12)),
                             "mes": int(num("p_mes", 1)), "destino": (request.form.get("p_destino") or "")[:500],
                             "entidad": (request.form.get("p_entidad") or "")[:120]}
        except ValueError:
            flash("Algún número no se entendió: usá solo dígitos, coma decimal", "error")
            return redirect(url_for("cashflow", cuit=cuit))
        for k in ("motivos_crecimiento", "explicacion_inflacion", "notas"):
            s[k] = (request.form.get(k) or "")[:3000]
        try:
            s["fijos"], s["ingresos"] = _lineas(request.form.get("fijos")), _lineas(request.form.get("ingresos"))
        except ValueError:
            flash("Revisá los gastos u otros ingresos: un renglón por concepto, 'Alquiler; 350000' o 'Comisiones; 0,5%'", "error")
            return redirect(url_for("cashflow", cuit=cuit))
        cf.guardar(cuit, s)
        usuarios.registrar(session["usuario"], "cash flow: supuestos", cuit, _ip())
        flash("Supuestos guardados", "ok")
        return redirect(url_for("cashflow", cuit=cuit))
    r = cf.calcular(cuit)
    if request.args.get("excel"):
        usuarios.registrar(session["usuario"], "bajó el cash flow proyectado", cuit, _ip())
        return send_file(BytesIO(cf.excel(cuit, nombre, r)), as_attachment=True,
                         download_name=f"cashflow_{cuit}_{date.today().isoformat()}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return render_template("cashflow.html", c=info, nombre=nombre, r=r, renglones=cf.RENGLONES, egresos=cf.EGRESOS)


@app.route("/cliente/<cuit>/vep_ccma", methods=["POST"])
@requiere_login
def vep_ccma(cuit):
    """VEP de autónomos / monotributo (CCMA → Volante de pago), relevado con Gaby el 26/11/2026."""
    _controlar_csrf()
    _cliente_info(cuit)
    medio = request.form.get("medio", "")
    secciones = request.form.getlist("seccion")
    if medio not in MEDIOS_VEP_DEUDA:
        flash("Elegí el medio de pago", "error")
    else:
        try:
            pedidos.encolar_vep_ccma(cuit, medio, secciones, session["usuario"])
            usuarios.registrar(session["usuario"], f"pidió VEP de autónomos/monotributo ({medio})", cuit, _ip())
            flash(f"Pedido: el robot genera el VEP de autónomos / monotributo por {medio} en un minuto.", "ok")
        except pedidos.ErrorPedido as e:
            flash(str(e), "error")
    return redirect(url_for("cliente_seccion", cuit=cuit, seccion="ccma"))


@app.route("/cliente/<cuit>/vep_deuda", methods=["POST"])
@requiere_login
def vep_deuda(cuit):
    _controlar_csrf()
    _cliente_info(cuit)
    s = datos.ficha(cuit)
    vencidas = sorted(s.get("deudas_vencidas") or [], key=lambda d: -(d.get("total") or 0))
    elegidas = []
    for v in request.form.getlist("deuda"):
        partes = v.split("|")
        try:
            d = vencidas[int(partes[0])]
        except (ValueError, IndexError):
            continue
        if [str(d.get("impuesto")), str(d.get("concepto")), str(d.get("periodo"))] == partes[1:4]:
            elegidas.append({k: d.get(k) for k in ("impuesto", "concepto", "subconcepto", "periodo", "cuota",
                                                    "establecimiento", "total")})
    medio = request.form.get("medio", "")
    if not elegidas:
        flash("Tildá al menos un concepto (o la deuda cambió: recargá la página)", "error")
    elif medio not in MEDIOS_VEP_DEUDA:
        flash("Elegí el medio de pago", "error")
    elif not VEP_DEUDA_LISTO:
        flash("La generación del VEP de deuda todavía no está habilitada: falta relevar la pantalla de ARCA", "error")
    else:
        try:
            pedidos.encolar_vep_deuda(cuit, elegidas, medio, request.form.get("enviar") == "1", session["usuario"])
            usuarios.registrar(session["usuario"], f"pidió VEP de deuda ({len(elegidas)} conceptos, {medio})", cuit, _ip())
            flash(f"Pedido: el robot genera el VEP de {len(elegidas)} concepto(s) por {medio} en un minuto.", "ok")
        except pedidos.ErrorPedido as e:
            flash(str(e), "error")
    return redirect(url_for("cliente_seccion", cuit=cuit, seccion="deuda"))
@app.route("/cliente/<cuit>/vep_captura/<archivo>")
@requiere_login
def vep_captura(cuit, archivo):
    """Captura de la pantalla final de ARCA con el VEP generado (20/11/2026)."""
    _cliente_info(cuit)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}_deuda_\d{1,20}", archivo):
        abort(404)
    ruta = os.path.join(datos.DATOS, cuit, "vep", archivo + ".png")
    if not os.path.isfile(ruta):
        abort(404)
    return send_file(ruta, mimetype="image/png", download_name=f"VEP_{cuit}_{archivo}.png")


ORGANISMOS_OPCIONALES = ("ARBA", "AGIP")


@app.route("/cliente/<cuit>/no_corresponde", methods=["POST"])
@requiere_login
def marcar_no_corresponde(cuit):
    """22/11/2026 (Gaby, Acuña Ana María: local de ARBA, nunca va a tener AGIP): marcar que un organismo no le
    corresponde al cliente, desde 'Para corregir'. Se puede desmarcar en Datos del cliente."""
    _controlar_csrf()
    _cliente_info(cuit)
    org = request.form.get("organismo", "")
    if org not in ORGANISMOS_OPCIONALES:
        abort(400)
    d = {k: v for k, v in (usuarios.datos_cliente(cuit) or {}).items() if not k.startswith("_")}
    actual = [x for x in (d.get("no_corresponde") or "").split(", ") if x]
    if org not in actual:
        actual.append(org)
    d["no_corresponde"] = ", ".join(sorted(actual))
    usuarios.guardar_datos_cliente(cuit, d, session["usuario"])
    usuarios.registrar(session["usuario"], f"{org} no corresponde", cuit, _ip())
    flash(f"{org} marcado como 'no corresponde' para este cliente", "ok")
    return redirect(request.form.get("volver") if (request.form.get("volver") or "").startswith("/") else url_for("robots"))


@app.route("/cliente/<cuit>/captura/<archivo>")
@requiere_login
def captura_robot(cuit, archivo):
    """Pantalla que guardó el robot al fallar (22/11/2026: para ver qué mostró el organismo)."""
    _cliente_info(cuit)
    if not re.fullmatch(r"[\w.-]{1,120}\.png", archivo):
        abort(404)
    ruta = os.path.join(datos.DATOS, cuit, "capturas", archivo)
    if not os.path.isfile(ruta):
        abort(404)
    return send_file(ruta, mimetype="image/png")


CAMPOS_CLIENTE = {
    "condicion_iva": "Condición frente al IVA", "condicion_ganancias": "Ganancias", "bienes_personales": "Bienes Personales",
    "regimen_iibb": "Régimen de Ingresos Brutos", "jurisdicciones_iibb": "Jurisdicciones de IIBB",
    "agente": "Agente de retención / percepción", "mes_cierre": "Mes de cierre", "empleador": "Empleador",
    "convenios": "Convenios colectivos", "encargado": "Encargado del estudio (recibe los avisos)",
    "equipo": "También lo llevan (ven este cliente)",
    "contadores": "Contador/es a cargo", "emails": "Mails del cliente",
    "medios_vep": "Medios de pago del VEP (según sus bancos)",
    "no_corresponde": "Organismos que no le corresponden (no se reclaman claves ni se marcan fallas)",
    "iva_90_dias": "IVA a 90 días (beneficio PyME de pago diferido)",
    "actividad": "Actividad principal (según la inscripción: servicios / bienes)",
    "telefonos": "Teléfonos", "whatsapp": "WhatsApp", "importador": "Importador / exportador (Registro Aduanero)",
    "observaciones": "Observaciones",
}
OPCIONES_CLIENTE = {
    "condicion_iva": ["", "Responsable inscripto", "Monotributo", "Exento", "No alcanzado"],
    "condicion_ganancias": ["", "Inscripto", "No inscripto", "Exento", "Monotributo"],
    "bienes_personales": ["", "Inscripto", "No inscripto", "Responsable sustituto"],
    "regimen_iibb": ["", "Local", "Convenio Multilateral", "Régimen simplificado", "Exento"],
    "mes_cierre": [""] + ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre",
                          "Octubre", "Noviembre", "Diciembre"],
    "empleador": ["", "Sí", "No", "Casas particulares"],
    "iva_90_dias": ["", "Sí", "No"],
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
        nuevos["no_corresponde"] = ", ".join(o for o in ORGANISMOS_OPCIONALES if o in request.form.getlist("no_corresponde"))
        antes_d = usuarios.datos_cliente(cuit) or {}
        nuevos["razon_social_corregida"] = antes_d.get("razon_social_corregida", "")
        rz = re.sub(r"[\x00-\x1f<>]", "", request.form.get("razon_social", "")).strip()[:120]
        if session.get("rol") == "admin" and rz and rz != (info.get("razon_social") or ""):
            nuevos["razon_social_corregida"] = rz          # corrección de datos mal cargados: solo admin (20/11/2026)
            try:
                claves.encolar_razon_social(cuit, rz, session["usuario"])
            except Exception:
                pass
            usuarios.registrar(session["usuario"], "razón social corregida", f"{cuit}: {rz}", _ip())
        usuarios.guardar_datos_cliente(cuit, nuevos, session["usuario"])
        usuarios.registrar(session["usuario"], "datos del cliente", cuit, _ip())
        flash("Datos del cliente guardados", "ok")
        return redirect(url_for("cliente", cuit=cuit))
    return render_template("datos_cliente.html", c=info, d=usuarios.datos_cliente(cuit), campos=CAMPOS_CLIENTE,
                           opciones=OPCIONES_CLIENTE, medios_vep=MEDIOS_VEP, organismos=ORGANISMOS_OPCIONALES, encargados=[(u[0], u[1]) for u in usuarios.listar() if u[3]],
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
                claves = {k for k, d in usuarios.descartes_vigentes().items() if d["cuit"] == cuit}
                claves |= {d["clave"] for (c_, _t, _i), d in usuarios.items_descartados().items() if c_ == cuit}
                for clave in claves:
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
                    siempre = request.form.get("siempre") == "1"
                    for a in actuales:
                        usuarios.descartar(cuit, a["tipo"], a["texto"], motivo, nota, session["usuario"], session.get("nombre", ""),
                                           a.get("items"), siempre=siempre)
                    usuarios.registrar(session["usuario"], f"cliente descartado en alertas ({motivo}"
                                       + (", para siempre)" if siempre else ")"), cuit, _ip())
                    flash(f"{len(actuales)} alerta(s) del cliente descartadas: {motivo}. "
                          + ("No vuelven nunca más; si aparece una nueva, se muestra enseguida." if siempre else
                             f"Las que sigan igual vuelven en {usuarios.DIAS_DESCARTE} días; si aparece una nueva, se muestra enseguida."), "ok")
            return redirect(url_for("alertas", ver=request.args.get("ver", ""), enc=request.args.get("enc", "")))
        if accion == "restaurar":
            clave = request.form.get("clave", "")
            d = usuarios.descartes_vigentes().get(clave) or next(
                ({"cuit": c_} for (c_, _t, _i), x in usuarios.items_descartados().items() if x["clave"] == clave), None)
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
            elif not (a_ := next((a for a in actuales if a["tipo"] == tipo and a["texto"] == texto), None)):
                flash("Esa alerta ya cambió o no está más", "error")
            elif motivo == "Otro" and not request.form.get("nota", "").strip():
                flash("Con el motivo 'Otro' escribí una nota", "error")
            else:
                siempre = request.form.get("siempre") == "1"
                usuarios.descartar(cuit, tipo, texto, motivo, request.form.get("nota", "").strip(), session["usuario"],
                                   session.get("nombre", ""), a_.get("items"), siempre=siempre)
                usuarios.registrar(session["usuario"], f"alerta descartada ({motivo}" + (", para siempre)" if siempre else ")"),
                                   f"{cuit} {tipo}"[:120], _ip())
                flash(f"Alerta descartada para siempre: {motivo}. No vuelve a aparecer." if siempre else
                      f"Alerta descartada: {motivo}. Si en {usuarios.DIAS_DESCARTE} días sigue igual, vuelve a aparecer.", "ok")
        return redirect(url_for("alertas", ver=request.args.get("ver", ""), enc=request.args.get("enc", "")))
    desc = usuarios.descartes_vigentes()
    items_d = usuarios.items_descartados()
    grupos, descartadas = [], []
    for g in datos.alertas_del_dia(_solo()):
        quedan = []
        for a in g["alertas"]:
            clave = usuarios.clave_alerta(g["cuit"], a["tipo"], a["texto"])
            d = desc.get(clave)
            its = [items_d.get((g["cuit"], a["tipo"][:200], str(i)[:300])) for i, _ in a.get("items") or []]
            viejas = sum(1 for x in its if x and x["permanente"])
            if not d and its and all(its):
                # todos sus períodos descartados: los de antes de 2020 para siempre, el resto por 30 días (20/11/2026)
                ult = max(its, key=lambda x: x["fecha"])
                d = {**ult, "nota": "", "tipo": a["tipo"], "texto": a["texto"]}
                clave = ult["clave"]
            if d:
                nuevas = [x for x in its if x and not x["permanente"]] if its else None
                vuelve = (None if d.get("siempre") or (its and not nuevas) else
                          date.fromisoformat(max(x["fecha"] for x in nuevas)[:10] if nuevas else d["fecha"][:10])
                          + timedelta(days=usuarios.DIAS_DESCARTE))
                descartadas.append({**a, **d, "cuit": g["cuit"], "nombre_cliente": g["nombre"], "vuelve": vuelve,
                                    "clave": clave})
            else:
                if viejas:
                    a = {**a, "nota_viejas": f"{viejas} de antes de {usuarios.ANIO_DESCARTE_PERMANENTE} ya descartada(s): "
                                            "no vuelven; la alerta sigue por lo demás"}
                quedan.append(a)
        if quedan:
            grupos.append({**g, "alertas": quedan})
    por_cliente = {}
    for d in descartadas:
        por_cliente.setdefault(d["cuit"], {"cuit": d["cuit"], "nombre": d["nombre_cliente"], "alertas": []})["alertas"].append(d)
    # 25/11/2026: filtro por encargado / equipo (quién lleva el cliente)
    enc = request.args.get("enc", "")
    lleva = {}
    for cuit_ in {g["cuit"] for g in grupos} | {d["cuit"] for d in descartadas}:
        d_ = usuarios.datos_cliente(cuit_) or {}
        lleva[cuit_] = ({d_.get("encargado") or ""} | {x.strip() for x in str(d_.get("equipo") or "").split(",")}) - {""}
    nombres = {u[0]: (u[1] or u[0]) for u in usuarios.listar()}
    quienes = sorted({u for v in lleva.values() for u in v}, key=lambda u: nombres.get(u, u).upper())
    sin_nadie = sum(1 for g in grupos if not lleva.get(g["cuit"]))
    if enc:
        pasa = (lambda c: not lleva.get(c)) if enc == "-" else (lambda c: enc in lleva.get(c, set()))
        grupos = [g for g in grupos if pasa(g["cuit"])]
        descartadas = [d for d in descartadas if pasa(d["cuit"])]
        por_cliente = {k: v for k, v in por_cliente.items() if pasa(k)}
    return render_template("alertas.html", grupos=grupos, descartadas=descartadas, desc_grupos=list(por_cliente.values()),
                           motivos=usuarios.MOTIVOS_DESCARTE, anio_perm=usuarios.ANIO_DESCARTE_PERMANENTE,
                           dias=usuarios.DIAS_DESCARTE, ver=request.args.get("ver", ""), enc=enc, quienes=quienes,
                           nombres=nombres, sin_nadie=sin_nadie)


# ---------------------------------------------------------------- Clientes: listado completo y bajas (25/11/2026)
@app.route("/clientes")
@requiere_login
def listado_clientes():
    nombres = {u[0]: (u[1] or u[0]) for u in usuarios.listar()}
    filas = []
    for c in sorted(datos.lista_clientes(_solo()), key=lambda x: (x.get("razon_social") or x["cuit"]).upper()):
        try:
            datos.completar_regimen(c["cuit"])
        except Exception:
            pass
        dc = usuarios.datos_cliente(c["cuit"]) or {}
        arca = next((a for a in c.get("accesos") or [] if a.get("organismo") == "ARCA"), {})
        filas.append({**c, "condicion": dc.get("condicion_iva") or "", "iibb": " · ".join(x for x in (dc.get("regimen_iibb"), dc.get("jurisdicciones_iibb")) if x), "encargado": nombres.get(dc.get("encargado") or "", dc.get("encargado") or ""),
                      "equipo": ", ".join(nombres.get(x.strip(), x.strip()) for x in str(dc.get("equipo") or "").split(",") if x.strip()),
                      "clave": arca.get("estado") or ("sin clave" if not arca else ""), "_dc": dc})
    if request.args.get("excel"):
        return _excel_clientes(filas, nombres)
    return render_template("clientes.html", filas=filas, es_admin=session.get("rol") == "admin")


def _excel_clientes(filas: list, nombres: dict):
    """Excel de la solapa Clientes (Gaby 26/11/2026): los que ve el usuario, con los datos de la ficha. Sin claves."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    campos = [k for k in CAMPOS_CLIENTE if k not in ("no_corresponde",)]
    wb = Workbook()
    ws = wb.active
    ws.title = "Clientes"
    ws.append(["Cliente", "CUIT", *[CAMPOS_CLIENTE[k] for k in campos], "Clave ARCA (estado)"])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E78")
    for f in filas:
        dc = f["_dc"]
        vals = []
        for k in campos:
            v = dc.get(k) or ""
            if k == "encargado":
                v = nombres.get(v, v)
            elif k == "equipo":
                v = ", ".join(nombres.get(x.strip(), x.strip()) for x in str(v).split(",") if x.strip())
            vals.append(", ".join(map(str, v)) if isinstance(v, (list, tuple)) else str(v))
        ws.append([f.get("razon_social") or "", datos.cuit_fmt(f["cuit"]), *vals, f.get("clave") or ""])
    for i in range(1, ws.max_column + 1):
        ws.column_dimensions[get_column_letter(i)].width = 34 if i == 1 else 16 if i == 2 else 22
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions
    b = BytesIO()
    wb.save(b)
    b.seek(0)
    usuarios.registrar(session["usuario"], "bajó el Excel de clientes", f"{len(filas)} clientes", _ip())
    return send_file(b, as_attachment=True, download_name=f"clientes_{date.today().isoformat()}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/clientes/baja/<cuit>", methods=["GET", "POST"])
@requiere_login
def baja_cliente(cuit):
    if session.get("rol") != "admin":
        abort(403)
    info = _cliente_info(cuit)
    nombre = info.get("razon_social") or datos.cuit_fmt(cuit)
    if request.method == "POST":
        _controlar_csrf()
        if request.form.get("confirmo") != cuit:
            flash("Para dar de baja tenés que escribir el CUIT del cliente (sin guiones)", "error")
            return redirect(url_for("baja_cliente", cuit=cuit))
        try:
            claves.encolar_baja(cuit, nombre, session["usuario"])
        except claves.ErrorClaves as e:
            flash(str(e), "error")
            return redirect(url_for("listado_clientes"))
        usuarios.borrar_cliente(cuit, session["usuario"])
        flash(f"{nombre} dado de baja. El robot borra sus claves en unos minutos; lo que ya había bajado queda guardado aparte.", "ok")
        return redirect(url_for("listado_clientes"))
    return render_template("baja_cliente.html", c=info, nombre=nombre)


# ---------------------------------------------------------------- Revisiones diarias (Tomás, 25/11/2026)
@app.route("/revisiones", methods=["GET", "POST"])
@requiere_login
def revisiones_diarias():
    from . import revisiones as rv
    es_admin = session.get("rol") == "admin"
    con_rev = rv.usuarios_con_revisiones()
    quien = request.args.get("u") if _ve_todos() and request.args.get("u") else session["usuario"]
    if _ve_todos() and quien == session["usuario"] and session["usuario"] not in con_rev and con_rev:
        quien = con_rev[0]
    hoy = date.today()
    mes = _periodo_ok(request.args.get("mes")) or hoy.strftime("%Y-%m")
    if request.method == "POST":
        _controlar_csrf()
        if request.form.get("accion") == "usuarios" and es_admin:
            rv.fijar_usuarios([u for u in request.form.getlist("usuarios") if u in {x[0] for x in usuarios.listar()}])
            usuarios.registrar(session["usuario"], "usuarios con revisiones diarias", ", ".join(request.form.getlist("usuarios")), _ip())
            flash("Usuarios con revisiones diarias guardados", "ok")
        else:
            cuit, hecho = request.form.get("cuit", ""), request.form.get("hecho") == "1"
            if quien != session["usuario"] and not es_admin:
                abort(403)
            if rv.marcar(quien, mes, cuit, hecho, session["usuario"], request.form.get("nota", "").strip()):
                usuarios.registrar(session["usuario"], "revisión " + ("hecha" if hecho else "desmarcada"), f"{cuit} ({quien})", _ip())
        return redirect(url_for("revisiones_diarias", u=request.args.get("u", ""), mes=request.args.get("mes", "")))
    nombres = {c["cuit"]: c.get("razon_social") or "" for c in datos.lista_clientes()}
    filas = rv.plan(quien, mes) if quien in con_rev or not es_admin else []
    for f in filas:
        f["nombre"] = nombres.get(f["cuit"], "")
    hoy_iso = hoy.isoformat()
    atras = [f for f in filas if not f["hecho"] and f["dia"] < hoy_iso]
    de_hoy = [f for f in filas if f["dia"] == hoy_iso]
    proximos = [f for f in filas if f["dia"] > hoy_iso]
    hechos = [f for f in filas if f["hecho"] and f["dia"] < hoy_iso]
    us = usuarios.listar()
    resumen = []
    if es_admin:                                   # Tomás ve cómo viene cada uno (25/11/2026: sin mail, en pantalla)
        for u in con_rev:
            pl = rv.plan(u, hoy.strftime("%Y-%m"))
            resumen.append({"usuario": u, "nombre": next((x[1] or x[0] for x in us if x[0] == u), u), "total": len(pl),
                            "hechos": sum(1 for f in pl if f["hecho"]), "atrasados": len(rv.atrasados(u, hoy))})
    return render_template("revisiones.html", resumen=resumen, quien=quien, mes=mes, hoy=hoy, atras=atras, de_hoy=de_hoy, proximos=proximos,
                           hechos=hechos, total=len(filas), n_hechos=sum(1 for f in filas if f["hecho"]),
                           habiles=len(rv.dias_habiles(mes)), es_admin=es_admin, con_rev=con_rev,
                           usuarios_todos=[(u[0], u[1] or u[0]) for u in us if u[3]],
                           nombre_quien=next((u[1] or u[0] for u in us if u[0] == quien), quien))


# ---------------------------------------------------------------- Biblioteca de importables (Gaby, 25/11/2026)
def _periodo_ok(p):
    return p if re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", p or "") else None


@app.route("/biblioteca")
@requiere_login
def biblioteca_general():
    from . import biblioteca as bib
    periodo = _periodo_ok(request.args.get("periodo")) or bib.periodo_anterior()
    enc, est, cond = request.args.get("enc", ""), request.args.get("estado", ""), request.args.get("cond", "")
    filas = bib.grilla(datos.lista_clientes(_solo()), periodo)
    nombres = {u[0]: (u[1] or u[0]) for u in usuarios.listar()}
    quienes = set()
    for f in filas:
        f["lleva"] = ({f["dc"].get("encargado") or ""} | {x.strip() for x in str(f["dc"].get("equipo") or "").split(",")}) - {""}
        quienes |= f["lleva"]
        c_ = (f["dc"].get("condicion_iva") or "").lower()
        f["cond"] = "monotributo" if "monotrib" in c_ else "inscripto" if "inscripto" in c_ else ""
    if enc:
        filas = [f for f in filas if not f["lleva"]] if enc == "-" else [f for f in filas if enc in f["lleva"]]
    if cond:
        filas = [f for f in filas if f["cond"] == cond]
    if est:
        filas = [f for f in filas if est in f["estados"].values()]
    cuenta = {k: sum(1 for f in filas for v in f["estados"].values() if v == k) for k in bib.ESTADOS}
    hoy = date.today()
    periodos = [(hoy.replace(day=1) - timedelta(days=1 + 28 * i)).strftime("%Y-%m") for i in range(13)]
    periodos = list(dict.fromkeys(periodos))
    return render_template("biblioteca.html", filas=filas, periodo=periodo, periodos=periodos, fuentes=bib.FUENTES,
                           estados=bib.ESTADOS, cuenta=cuenta, enc=enc, est=est, cond=cond, nombres=nombres,
                           quienes=sorted(quienes, key=lambda u: nombres.get(u, u).upper()))


@app.route("/cliente/<cuit>/biblioteca", methods=["GET", "POST"])
@requiere_login
def biblioteca_cliente(cuit):
    from . import biblioteca as bib
    info = _cliente_info(cuit)
    dc = usuarios.datos_cliente(cuit) or {}
    if request.method == "POST":
        _controlar_csrf()
        nuevas = [f[0] for f in bib.FUENTES if request.form.get(f"f_{f[0]}") == "1"]
        antes = bib.elegidas(cuit, dc)
        d = {k: v for k, v in dc.items() if not k.startswith("_")}
        d["importables"] = nuevas
        usuarios.guardar_datos_cliente(cuit, d, session["usuario"])
        cambios = [("+" if f in nuevas else "−") + f for f in bib.NOMBRE if (f in nuevas) != (f in antes)]
        usuarios.registrar(session["usuario"], "importables del cliente", f"{cuit} {' '.join(cambios)}"[:300], _ip())
        flash("Fuentes de la biblioteca guardadas", "ok")
        return redirect(url_for("biblioteca_cliente", cuit=cuit))
    periodos = bib.periodos()                        # Gabriel (25/11/2026): siempre los 2 últimos meses, nunca más
    err = bib.errores_corrida(cuit)
    meses = []
    for p in periodos:
        fu = []
        for f in bib.FUENTES:
            e = bib.estado(cuit, p, f[0], dc, err)
            if e == "no":
                continue
            det = bib.detalle(cuit, p, f[0])
            fu.append({"id": f[0], "nombre": bib.NOMBRE[f[0]], "estado": e, "n": len(det), "archivos": bib.archivos(cuit, p, f[0]),
                       "importe": round(sum(x["Importe"] for x in det), 2), "totales": bib.totales(det)})
        meses.append({"periodo": p, "fuentes": fu, "saldos": bib.saldos_anteriores(cuit, p)})
    elegidas = bib.elegidas(cuit, dc)
    diag = [{"id": f, "nombre": bib.NOMBRE[f], "robot": bib.ROBOT_PEDIDO.get(f), **bib.diagnostico(cuit, f)}
            for f in ("arca_mr", "arba", "agip") if f in elegidas or bib.versiones_alguna(cuit, f)
            or os.path.exists(os.path.join(datos.DATOS, cuit, "biblioteca", "_diagnostico", f + ".json"))]
    capturas = sorted(glob.glob(os.path.join(datos.DATOS, cuit, "capturas", "*.png")), key=os.path.getmtime, reverse=True)[:12]
    capturas = [{"nombre": os.path.basename(x), "fecha": datetime.fromtimestamp(os.path.getmtime(x)).strftime("%d/%m %H:%M")}
                for x in capturas]
    return render_template("biblioteca_cliente.html", c=info, meses=meses, fuentes=bib.FUENTES, elegidas=elegidas, diag=diag,
                           capturas=capturas, conciliaciones=bib.conciliaciones(cuit),
                           por_defecto=not isinstance(dc.get("importables"), list), estados=bib.ESTADOS)


@app.route("/cliente/<cuit>/biblioteca/<periodo>/<fuente>.xlsx")
@requiere_login
def biblioteca_excel(cuit, periodo, fuente):
    from . import biblioteca as bib
    info = _cliente_info(cuit)
    if not _periodo_ok(periodo) or fuente not in bib.NOMBRE:
        abort(404)
    usuarios.registrar(session["usuario"], "bajó importable", f"{cuit} {periodo} {fuente}", _ip())
    return send_file(BytesIO(bib.excel(cuit, info.get("razon_social") or cuit, periodo, [fuente])), as_attachment=True,
                     download_name=f"{periodo}_{fuente}_{cuit}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/cliente/<cuit>/conciliacion/<tipo>/<nombre>")
@requiere_login
def biblioteca_conciliacion(cuit, tipo, nombre):
    """Excel de una conciliación guardada en el repositorio permanente (26/11/2026)."""
    from . import biblioteca as bib
    _cliente_info(cuit)
    if tipo not in bib.CONCILIACIONES or not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.xlsx", nombre):
        abort(404)
    r = os.path.join(datos.DATOS, cuit, "biblioteca", "_conciliaciones", tipo, nombre)
    if not os.path.isfile(r):
        abort(404)
    usuarios.registrar(session["usuario"], "bajó conciliación", f"{cuit} {tipo} {nombre}", _ip())
    return send_file(r, as_attachment=True, download_name=f"conciliacion_{tipo}_{cuit}_{nombre}")


@app.route("/cliente/<cuit>/biblioteca/<periodo>/<fuente>/archivo/<nombre>")
@requiere_login
def biblioteca_archivo(cuit, periodo, fuente, nombre):
    """Archivo tal como lo bajó el organismo (TXT para importar, constancia en PDF), 25/11/2026."""
    from . import biblioteca as bib
    _cliente_info(cuit)
    if not _periodo_ok(periodo) or fuente not in bib.NOMBRE or nombre not in bib.archivos(cuit, periodo, fuente):
        abort(404)
    usuarios.registrar(session["usuario"], "bajó archivo de la biblioteca", f"{cuit} {periodo} {fuente} {nombre}", _ip())
    return send_file(os.path.join(datos.DATOS, cuit, "biblioteca", periodo, fuente, "archivos", nombre), as_attachment=True,
                     download_name=nombre)


@app.route("/cliente/<cuit>/biblioteca/<periodo>.zip")
@requiere_login
def biblioteca_zip(cuit, periodo):
    from . import biblioteca as bib
    info = _cliente_info(cuit)
    if not _periodo_ok(periodo):
        abort(404)
    dc = usuarios.datos_cliente(cuit) or {}
    usuarios.registrar(session["usuario"], "bajó importables del mes (zip)", f"{cuit} {periodo}", _ip())
    return send_file(BytesIO(bib.zip_mes(cuit, info.get("razon_social") or cuit, periodo, bib.elegidas(cuit, dc))),
                     as_attachment=True, download_name=f"importables_{cuit}_{periodo}.zip", mimetype="application/zip")


@app.route("/intercliente", methods=["GET", "POST"])
@requiere_admin
def intercliente():
    """Facturación entre clientes del estudio y comisión por gestión de negocios (solo administradores, 26/11/2026)."""
    from . import intercliente as ic
    desde = _periodo_ok(request.values.get("desde")) or ""
    hasta = _periodo_ok(request.values.get("hasta")) or ""
    cliente = re.sub(r"\D", "", request.values.get("cliente") or "")[:11]
    if request.method == "POST":
        _controlar_csrf()
        c = ic.conf()
        try:
            c["porcentaje"] = max(0.0, min(100.0, float((request.form.get("porcentaje") or "0").replace(",", "."))))
        except ValueError:
            flash("El porcentaje tiene que ser un número", "error")
        visibles = set(request.form.getlist("par"))
        marcados = set(request.form.getlist("conocidos"))
        c["conocidos"] = sorted((set(c["conocidos"]) - visibles) | (marcados & visibles))
        # Exclusiones: del estudio (nosotros le facturamos) y mismo dueño (26/11/2026)
        for v in request.form.getlist("excluir"):
            k, _, que = v.partition(":")
            vend, _, comp = k.partition(">")
            if not (re.fullmatch(r"\d{11}", vend) and re.fullmatch(r"\d{11}", comp)):
                continue
            if que == "vendedor":
                c["propios"] = sorted(set(c["propios"]) | {vend})
            elif que == "comprador":
                c["propios"] = sorted(set(c["propios"]) | {comp})
            elif que == "grupo":
                c["grupos"] = ic.unir_grupo(c["grupos"], vend, comp)
        nuevo = re.sub(r"\D", "", request.form.get("agregar_propio") or "")
        if nuevo:
            if len(nuevo) == 11:
                c["propios"] = sorted(set(c["propios"]) | {nuevo})
            else:
                flash("El CUIT del estudio tiene que tener 11 números", "error")
        quitar = set(request.form.getlist("quitar_propio"))
        c["propios"] = [x for x in c["propios"] if x not in quitar]
        sacar = set(request.form.getlist("quitar_grupo"))
        c["grupos"] = [g for g in ([x for x in g if x not in sacar] for g in c["grupos"]) if len(g) > 1]
        ic.guardar_conf(c)
        usuarios.registrar(session["usuario"], "facturación entre clientes: marcas y porcentaje",
                           f"{c['porcentaje']} % · {len(c['conocidos'])} pares conocidos", _ip())
        flash("Guardado", "ok")
        return redirect(url_for("intercliente", desde=desde, hasta=hasta, cliente=cliente or None))
    if request.args.get("excel"):
        usuarios.registrar(session["usuario"], "bajó facturación entre clientes", f"{desde}-{hasta}", _ip())
        return send_file(BytesIO(ic.excel(desde, hasta, cliente)), as_attachment=True,
                         download_name=f"facturacion_entre_clientes_{cliente + '_' if cliente else ''}{date.today().isoformat()}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    nom = next((x.get("razon_social") or x["cuit"] for x in datos.lista_clientes() if x["cuit"] == cliente), "") if cliente else ""
    return render_template("intercliente.html", r=ic.resumen(desde, hasta, cliente), desde=desde, hasta=hasta,
                           cliente=cliente, nombre_cliente=nom)


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
    puede = bool(cuit) and asientos.puede_revisar(cuit, session["usuario"], "admin" if _ve_todos() else session.get("rol", ""))
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
                           estado=[x for x in pedidos.estado() if ok_(x)], nombres=pedidos.ROBOTS,
                           en_curso=_en_curso_visible(), fallas=datos.fallas_todos(_solo()))


def _en_curso_visible():
    d = datos.corrida_en_curso()
    if d and d.get("cuit") and not _puede(str(d["cuit"])):
        d["cuit"] = ""                               # el CUIT de un cliente ajeno no se muestra
    return d


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
        elif not _ve_todos() and a.get("encargado") and a["encargado"] != session["usuario"]:
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
        except ImportError as e:
            flash(f"Falta instalar openpyxl en la web ({e}). Avisá al administrador: se instala con ARREGLAR_OPENPYXL.bat", "error")
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
        except ImportError as e:
            flash(f"Falta instalar openpyxl en la web ({e}). Avisá al administrador: se instala con ARREGLAR_OPENPYXL.bat", "error")
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
            rol = request.form.get("rol", "colaborador")
            err = usuarios.crear(u, request.form.get("nombre", ""), request.form.get("clave", ""),
                                 rol if rol in usuarios.ROLES else "colaborador")
            if not err:
                usuarios.registrar(session["usuario"], "alta de usuario", u, _ip())
                flash(f"Usuario '{u}' creado. Pasale la contraseña en persona.", "ok")
        elif not usuarios.existe(u):
            err = "No existe ese usuario"
        elif accion == "rol":
            if u == session["usuario"]:
                err = "No podés cambiarte el rol a vos mismo"
            else:
                err = usuarios.cambiar_rol(u, request.form.get("rol", ""))
                if not err:
                    usuarios.registrar(session["usuario"], "cambio de rol", f"{u}: {request.form.get('rol')}", _ip())
                    flash(f"Rol de '{u}': {usuarios.NOMBRE_ROL.get(request.form.get('rol'), '')}. Lo toma en su próximo ingreso.", "ok")
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
        u = request.form.get("u_" + org, "") if org in ("ARCA", "AGIP") else ""
        if u and not claves.cuit_valido("".join(ch for ch in u if ch.isdigit())):
            err = f"El usuario de {org}, si lo completás, tiene que ser un CUIT válido"
            break
        u = "".join(ch for ch in u if ch.isdigit())
        if org == "AGIP" and not u and cuit[:2] not in ("30", "33", "34"):
            u = cuit                                      # 27/11/2026 (Garbuglia): una persona entra con su propio CUIT
        elif org == "AGIP" and not u:
            # AGIP (Gaby, 25/11/2026): una persona jurídica entra con el CUIT del REPRESENTANTE (persona física)
            acc = _cliente_info(cuit).get("accesos") or []
            ant = next((a.get("usuario") for a in acc if a.get("organismo") == "AGIP" and not a.get("detalle")), "")
            u_arca = next((a.get("usuario") for a in acc if a.get("organismo") == "ARCA"), "")
            if ant and ant != cuit:
                u = ant                                   # se mantiene el representante ya cargado
            elif u_arca and u_arca != cuit:
                u = u_arca                                # Gaby: es el mismo CUIT con el que se entra a ARCA
            elif cuit[:2] in ("30", "33", "34"):
                err = ("AGIP: para una sociedad hay que completar el CUIT del representante (persona física) con el que "
                       "se entra con Clave Ciudad")
                break
        try:
            claves.encolar(cuit, razon, org, u or cuit, k, session["usuario"])
        except claves.ErrorClaves as e:
            err = str(e)
            break
        usuarios.registrar(session["usuario"], "clave enviada" if not hay_razon else "alta de cliente / clave enviada",
                           f"{cuit} {org}", _ip())
        enviados.append(org)
    km, um = request.form.get("k_AGIP_MIBA", ""), request.form.get("u_AGIP_MIBA", "").strip()
    if km and not err:                                     # cuenta miBA de AGIP: usuario CUIL o mail (25/11/2026)
        if not um or len(um) > 60 or not (claves.cuit_valido("".join(ch for ch in um if ch.isdigit()))
                                          or re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", um)):
            return enviados, "AGIP miBA: completá el usuario (CUIL o mail) de la cuenta miBA"
        if um.replace("-", "").isdigit():
            um = um.replace("-", "")
        try:
            claves.encolar(cuit, razon, "AGIP", um, km, session["usuario"], detalle="miba")
        except claves.ErrorClaves as e:
            return enviados, str(e)
        usuarios.registrar(session["usuario"], "clave enviada", f"{cuit} AGIP miBA", _ip())
        enviados.append("AGIP miBA")
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
            if env and not _ve_todos() and not (usuarios.datos_cliente(cuit) or {}).get("encargado"):
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
