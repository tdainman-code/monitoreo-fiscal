"""Usuarios de la aplicación web (propios, no son las claves fiscales) y registro de actividad.

Alta y mantenimiento desde la máquina robots:
  sudo -u web /opt/robots-web/venv/bin/python -m robots_web.usuarios crear gabriel "Gabriel Mancovsky" --admin
  sudo -u web /opt/robots-web/venv/bin/python -m robots_web.usuarios crear juan "Juan Pérez"
  sudo -u web /opt/robots-web/venv/bin/python -m robots_web.usuarios clave juan       (nueva contraseña)
  sudo -u web /opt/robots-web/venv/bin/python -m robots_web.usuarios baja juan
  sudo -u web /opt/robots-web/venv/bin/python -m robots_web.usuarios listar
La contraseña se pide por teclado (no se ve) y se guarda solo como hash.
"""
from __future__ import annotations

import datetime as dt
import getpass
import os
import re
import sqlite3
import sys

from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.environ.get("ROBOTS_WEB_DATOS", "/var/lib/robots-web")
DB = os.path.join(BASE, "web.db")
MIN_LARGO = 10
BLOQUEO_INTENTOS, BLOQUEO_MIN = 5, 15


def conectar():
    os.makedirs(BASE, exist_ok=True)
    nueva = not os.path.exists(DB)
    con = sqlite3.connect(DB)
    if nueva:
        os.chmod(DB, 0o600)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS usuarios (usuario TEXT PRIMARY KEY, nombre TEXT, hash TEXT NOT NULL,
        rol TEXT NOT NULL DEFAULT 'empleado', activo INTEGER NOT NULL DEFAULT 1, fallos INTEGER NOT NULL DEFAULT 0,
        bloqueado_hasta TEXT, creado TEXT, ultimo_ingreso TEXT);
    CREATE TABLE IF NOT EXISTS actividad (fecha TEXT, usuario TEXT, accion TEXT, detalle TEXT, ip TEXT);
    CREATE TABLE IF NOT EXISTS notas (id INTEGER PRIMARY KEY, cuit TEXT, fecha TEXT, usuario TEXT, nombre TEXT,
        texto TEXT, borrada INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS sugerencias (id INTEGER PRIMARY KEY, fecha TEXT, usuario TEXT, nombre TEXT,
        tipo TEXT, texto TEXT, estado TEXT NOT NULL DEFAULT 'Nueva', respuesta TEXT);
    CREATE TABLE IF NOT EXISTS vistos (clave TEXT PRIMARY KEY, cuit TEXT, fecha TEXT, usuario TEXT, nombre TEXT, nota TEXT);
    CREATE TABLE IF NOT EXISTS informadas (id TEXT PRIMARY KEY, cuit TEXT, fecha TEXT, usuario TEXT, nombre TEXT);
    CREATE TABLE IF NOT EXISTS datos_cliente (cuit TEXT PRIMARY KEY, datos TEXT, actualizado TEXT, usuario TEXT);
    """)
    try:                                   # mail de cada usuario (avisos al encargado, 17/11/2026)
        con.execute("ALTER TABLE usuarios ADD COLUMN email TEXT")
    except sqlite3.OperationalError:
        pass
    return con


def ahora():
    return dt.datetime.now().isoformat(timespec="seconds")


def registrar(usuario, accion, detalle="", ip=""):
    con = conectar()
    with con:
        con.execute("INSERT INTO actividad VALUES (?,?,?,?,?)", (ahora(), usuario, accion, detalle[:300], ip))
    con.close()


def verificar(usuario: str, clave: str) -> tuple[dict | None, str]:
    con = conectar()
    f = con.execute("SELECT usuario, nombre, hash, rol, activo, fallos, bloqueado_hasta FROM usuarios WHERE usuario=?",
                    (usuario.strip().lower(),)).fetchone()
    if not f or not f[4]:
        con.close()
        return None, "Usuario o contraseña incorrectos"
    if f[6] and f[6] > ahora():
        con.close()
        return None, f"Usuario bloqueado por intentos fallidos. Probá de nuevo en {BLOQUEO_MIN} minutos."
    ok = check_password_hash(f[2], clave)
    with con:
        if ok:
            con.execute("UPDATE usuarios SET fallos=0, bloqueado_hasta=NULL, ultimo_ingreso=? WHERE usuario=?", (ahora(), f[0]))
        else:
            fallos = f[5] + 1
            hasta = (dt.datetime.now() + dt.timedelta(minutes=BLOQUEO_MIN)).isoformat(timespec="seconds") \
                if fallos >= BLOQUEO_INTENTOS else None
            con.execute("UPDATE usuarios SET fallos=?, bloqueado_hasta=? WHERE usuario=?",
                        (0 if hasta else fallos, hasta, f[0]))
    con.close()
    if ok:
        return {"usuario": f[0], "nombre": f[1], "rol": f[3]}, ""
    return None, "Usuario o contraseña incorrectos"


def cambiar_clave(usuario: str, nueva: str) -> str:
    if len(nueva) < MIN_LARGO:
        return f"La contraseña tiene que tener al menos {MIN_LARGO} caracteres"
    con = conectar()
    with con:
        con.execute("UPDATE usuarios SET hash=? WHERE usuario=?", (generate_password_hash(nueva), usuario))
    con.close()
    return ""


USUARIO_RE = re.compile(r"^[a-z0-9._-]{2,30}$")


def crear(usuario: str, nombre: str, clave: str, rol: str = "empleado") -> str:
    """Alta desde la pantalla. Devuelve un mensaje de error, o '' si salió bien."""
    usuario = usuario.strip().lower()
    if not USUARIO_RE.match(usuario):
        return "El usuario va en minúsculas, sin espacios ni tildes (2 a 30 caracteres: letras, números, punto, guion)"
    if len(clave) < MIN_LARGO:
        return f"La contraseña tiene que tener al menos {MIN_LARGO} caracteres"
    if rol not in ("empleado", "admin"):
        return "Rol inválido"
    con = conectar()
    try:
        if con.execute("SELECT 1 FROM usuarios WHERE usuario=?", (usuario,)).fetchone():
            return f"Ya existe el usuario '{usuario}'"
        with con:
            con.execute("INSERT INTO usuarios (usuario, nombre, hash, rol, activo, creado) VALUES (?,?,?,?,1,?)",
                        (usuario, (nombre.strip() or usuario)[:80], generate_password_hash(clave), rol, ahora()))
    finally:
        con.close()
    return ""


def poner_activo(usuario: str, activo: bool) -> str:
    con = conectar()
    try:
        f = con.execute("SELECT rol, activo FROM usuarios WHERE usuario=?", (usuario,)).fetchone()
        if not f:
            return "No existe ese usuario"
        if not activo and f[0] == "admin":
            n = con.execute("SELECT COUNT(*) FROM usuarios WHERE rol='admin' AND activo=1").fetchone()[0]
            if n <= 1:
                return "No se puede dar de baja al único administrador"
        with con:
            con.execute("UPDATE usuarios SET activo=?, fallos=0, bloqueado_hasta=NULL WHERE usuario=?", (1 if activo else 0, usuario))
    finally:
        con.close()
    return ""


def existe(usuario: str) -> bool:
    con = conectar()
    r = con.execute("SELECT 1 FROM usuarios WHERE usuario=?", (usuario,)).fetchone()
    con.close()
    return bool(r)


def actividad(n=200):
    con = conectar()
    filas = con.execute("SELECT fecha, usuario, accion, detalle, ip FROM actividad ORDER BY fecha DESC LIMIT ?", (n,)).fetchall()
    con.close()
    return filas


def agregar_nota(cuit, usuario, nombre, texto):
    con = conectar()
    with con:
        con.execute("INSERT INTO notas (cuit, fecha, usuario, nombre, texto) VALUES (?,?,?,?,?)",
                    (cuit, ahora(), usuario, nombre, texto[:2000]))
    con.close()


def notas(cuit=None, n=200):
    con = conectar()
    if cuit:
        filas = con.execute("SELECT id, cuit, fecha, usuario, nombre, texto FROM notas WHERE cuit=? AND borrada=0 "
                            "ORDER BY fecha DESC LIMIT ?", (cuit, n)).fetchall()
    else:
        filas = con.execute("SELECT id, cuit, fecha, usuario, nombre, texto FROM notas WHERE borrada=0 "
                            "ORDER BY fecha DESC LIMIT ?", (n,)).fetchall()
    con.close()
    return [dict(zip(("id", "cuit", "fecha", "usuario", "nombre", "texto"), f)) for f in filas]


def borrar_nota(id_, usuario, es_admin):
    con = conectar()
    with con:
        if es_admin:
            con.execute("UPDATE notas SET borrada=1 WHERE id=?", (id_,))
        else:
            con.execute("UPDATE notas SET borrada=1 WHERE id=? AND usuario=?", (id_, usuario))
    con.close()


def agregar_sugerencia(usuario, nombre, tipo, texto):
    con = conectar()
    with con:
        con.execute("INSERT INTO sugerencias (fecha, usuario, nombre, tipo, texto) VALUES (?,?,?,?,?)",
                    (ahora(), usuario, nombre, tipo, texto[:4000]))
    con.close()


def sugerencias():
    con = conectar()
    filas = con.execute("SELECT id, fecha, nombre, tipo, texto, estado, respuesta FROM sugerencias "
                        "ORDER BY CASE estado WHEN 'Nueva' THEN 0 WHEN 'En curso' THEN 1 ELSE 2 END, fecha DESC").fetchall()
    con.close()
    return [dict(zip(("id", "fecha", "nombre", "tipo", "texto", "estado", "respuesta"), f)) for f in filas]


def responder_sugerencia(id_, estado, respuesta):
    con = conectar()
    with con:
        con.execute("UPDATE sugerencias SET estado=?, respuesta=? WHERE id=?", (estado, respuesta[:2000], id_))
    con.close()


# ---------------------------------------------------------------- traído de Radar fiscal (17/11/2026)
def marcar_informada(id_, cuit, usuario, nombre, informada=True):
    """Comunicación del DFE que alguien del estudio ya le informó al cliente (sale de las pendientes)."""
    con = conectar()
    with con:
        if informada:
            con.execute("INSERT OR REPLACE INTO informadas VALUES (?,?,?,?,?)", (id_, cuit, ahora(), usuario, nombre))
        else:
            con.execute("DELETE FROM informadas WHERE id=?", (id_,))
    con.close()


def marcar_visto(clave, cuit, usuario, nombre, nota="", visto=True):
    """Deuda histórica (Convenio, Cuentas Tributarias) que el encargado ya revisó: "visto, me ocupo" (17/11/2026)."""
    con = conectar()
    with con:
        if visto:
            con.execute("INSERT OR REPLACE INTO vistos VALUES (?,?,?,?,?,?)", (clave, cuit, ahora(), usuario, nombre, nota[:500]))
        else:
            con.execute("DELETE FROM vistos WHERE clave=?", (clave,))
    con.close()


def vistos(cuit=None) -> dict:
    con = conectar()
    q = "SELECT clave, fecha, nombre, nota, usuario FROM vistos" + (" WHERE cuit=?" if cuit else "")
    r = {f[0]: {"fecha": f[1], "nombre": f[2], "nota": f[3], "usuario": f[4]} for f in con.execute(q, (cuit,) if cuit else ())}
    con.close()
    return r


def informadas() -> dict:
    con = conectar()
    r = {f[0]: {"fecha": f[1], "nombre": f[2]} for f in con.execute("SELECT id, fecha, nombre FROM informadas")}
    con.close()
    return r


def datos_cliente(cuit) -> dict:
    import json as _json
    con = conectar()
    f = con.execute("SELECT datos, actualizado, usuario FROM datos_cliente WHERE cuit=?", (cuit,)).fetchone()
    con.close()
    if not f:
        return {}
    try:
        d = _json.loads(f[0])
    except ValueError:
        d = {}
    d["_actualizado"], d["_usuario"] = f[1], f[2]
    return d


def guardar_datos_cliente(cuit, datos: dict, usuario):
    import json as _json
    con = conectar()
    with con:
        con.execute("INSERT OR REPLACE INTO datos_cliente VALUES (?,?,?,?)",
                    (cuit, _json.dumps(datos, ensure_ascii=False), ahora(), usuario))
    con.close()
    try:
        publicar_contactos()
    except OSError:
        pass


def listar():
    con = conectar()
    filas = con.execute("SELECT usuario, nombre, rol, activo, ultimo_ingreso, email FROM usuarios ORDER BY usuario").fetchall()
    con.close()
    return filas


EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def poner_email(usuario: str, email: str) -> str:
    email = (email or "").strip()
    if email and not EMAIL_RE.match(email):
        return "El mail no es válido"
    con = conectar()
    with con:
        con.execute("UPDATE usuarios SET email=? WHERE usuario=?", (email, usuario))
    con.close()
    publicar_contactos()
    return ""


def publicar_contactos() -> None:
    """Deja en la bandeja los contactos que usan los avisos del robot (el robot no ve la base de la web):
    {cuit: {razon_social, encargado, encargado_nombre, encargado_email, emails_cliente}}."""
    import json as _json
    from . import pedidos
    if not pedidos.listo():
        return
    con = conectar()
    us = {u: (n, e) for u, n, e in con.execute("SELECT usuario, nombre, email FROM usuarios WHERE activo=1")}
    admins = [e for (e,) in con.execute("SELECT email FROM usuarios WHERE activo=1 AND rol='admin' AND email<>''") if e]
    filas = con.execute("SELECT cuit, datos FROM datos_cliente").fetchall()
    con.close()
    out = {}
    for cuit, d in filas:
        try:
            d = _json.loads(d)
        except ValueError:
            continue
        enc = d.get("encargado", "")
        out[cuit] = {"encargado": enc, "encargado_nombre": (us.get(enc) or ("", ""))[0] or "",
                     "encargado_email": (us.get(enc) or ("", ""))[1] or "",
                     "medios_vep": [m for m in (d.get("medios_vep") or "").split(", ") if m],
                     "emails_cliente": [m.strip() for m in re.split(r"[,;\s]+", d.get("emails", "")) if EMAIL_RE.match(m.strip())]}
    out["_admins"] = admins
    ruta = os.path.join(pedidos.PEDIDOS, "_contactos.txt")
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump(out, f, ensure_ascii=False)
    os.replace(tmp, ruta)


def _pedir_clave():
    while True:
        a = getpass.getpass(f"Contraseña nueva (mínimo {MIN_LARGO} caracteres, no se ve): ")
        b = getpass.getpass("Repetila: ")
        if a != b:
            print("No coinciden.")
        elif len(a) < MIN_LARGO:
            print("Muy corta.")
        else:
            return a


def _main(a):
    if not a or a[0] not in ("crear", "clave", "baja", "alta", "listar"):
        print(__doc__)
        return 1
    con = conectar()
    if a[0] == "listar":
        for u in listar():
            print(f"{u[0]:15} {u[1] or '':30} {u[2]:9} {'activo' if u[3] else 'BAJA':7} último ingreso: {u[4] or '-'}")
        return 0
    usuario = a[1].strip().lower()
    if a[0] == "crear":
        nombre = a[2] if len(a) > 2 and not a[2].startswith("--") else usuario
        rol = "admin" if "--admin" in a else "empleado"
        clave = _pedir_clave()
        with con:
            con.execute("INSERT OR REPLACE INTO usuarios (usuario, nombre, hash, rol, activo, creado) VALUES (?,?,?,?,1,?)",
                        (usuario, nombre, generate_password_hash(clave), rol, ahora()))
        print(f"Usuario '{usuario}' creado ({rol}).")
    elif a[0] == "clave":
        print(cambiar_clave(usuario, _pedir_clave()) or "Contraseña cambiada.")
    elif a[0] in ("baja", "alta"):
        with con:
            con.execute("UPDATE usuarios SET activo=? WHERE usuario=?", (1 if a[0] == "alta" else 0, usuario))
        print(f"Usuario '{usuario}': {a[0]}.")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
