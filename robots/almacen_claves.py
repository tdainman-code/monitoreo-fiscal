"""Almacén de claves cifrado (corre SOLO en la máquina 'robots' del estudio).

- Cada clave se guarda cifrada (Fernet: AES-128-CBC + HMAC-SHA256) en una base SQLite.
- La llave maestra vive en un archivo aparte (por defecto /etc/robots/llave_maestra.key,
  permisos 600, dueño el usuario de los robots). El disco de la máquina además está cifrado.
- Ninguna función de este módulo imprime ni registra claves. El único punto que devuelve una
  clave en claro es `obtener_clave()`, y lo usan los robots al momento de ingresar.
- Cada uso queda auditado (cliente, organismo, fecha/hora, motivo), sin la clave.

Uso por consola:
    python3 -m robots.almacen_claves crear-llave
    python3 -m robots.almacen_claves importar plantilla_carga_clientes.xlsx
    python3 -m robots.almacen_claves listar
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import stat
import sys
from contextlib import closing

from cryptography.fernet import Fernet, InvalidToken

RUTA_LLAVE = os.environ.get("ROBOTS_LLAVE", "/etc/robots/llave_maestra.key")
RUTA_DB = os.environ.get("ROBOTS_DB", "/var/lib/robots/almacen.db")

ORGANISMOS = {"ARCA", "ARBA", "AGIP", "Provincia", "Municipio"}


class ErrorAlmacen(Exception):
    pass


# ---------------------------------------------------------------- llave maestra
def crear_llave(ruta: str = RUTA_LLAVE) -> None:
    if os.path.exists(ruta):
        raise ErrorAlmacen(f"Ya existe una llave en {ruta}. No se sobrescribe.")
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(Fernet.generate_key())


def _fernet(ruta: str = RUTA_LLAVE) -> Fernet:
    if not os.path.exists(ruta):
        raise ErrorAlmacen(f"No existe la llave maestra en {ruta}. Ejecutar 'crear-llave'.")
    modo = stat.S_IMODE(os.stat(ruta).st_mode)
    if modo & 0o077:
        raise ErrorAlmacen(f"La llave {ruta} tiene permisos {oct(modo)}; deben ser 600.")
    with open(ruta, "rb") as f:
        return Fernet(f.read().strip())


# ---------------------------------------------------------------- base de datos
ESQUEMA = """
CREATE TABLE IF NOT EXISTS clientes (
    cuit TEXT PRIMARY KEY, razon_social TEXT, datos TEXT
);
CREATE TABLE IF NOT EXISTS accesos (
    cuit TEXT NOT NULL, organismo TEXT NOT NULL, detalle TEXT NOT NULL DEFAULT '',
    usuario TEXT NOT NULL, clave_cifrada BLOB NOT NULL,
    nivel TEXT, token TEXT, metodo TEXT NOT NULL DEFAULT 'Directo',
    estado TEXT NOT NULL DEFAULT 'Sin verificar',      -- OK / Clave inválida / Requiere intervención
    actualizado TEXT NOT NULL,
    PRIMARY KEY (cuit, organismo, detalle)
);
CREATE TABLE IF NOT EXISTS relacionados (
    cuit TEXT NOT NULL, cuit_relacionado TEXT NOT NULL, nombre TEXT, vinculo TEXT,
    consolidar TEXT NOT NULL DEFAULT 'S', observaciones TEXT,
    PRIMARY KEY (cuit, cuit_relacionado)
);
CREATE TABLE IF NOT EXISTS accesos_previos (       -- última versión anterior de cada clave (cifrada), para recuperar
    cuit TEXT NOT NULL, organismo TEXT NOT NULL, detalle TEXT NOT NULL DEFAULT '',
    usuario TEXT, clave_cifrada BLOB NOT NULL, reemplazada TEXT NOT NULL,
    PRIMARY KEY (cuit, organismo, detalle)
);
CREATE TABLE IF NOT EXISTS auditoria (
    fecha TEXT NOT NULL, cuit TEXT, organismo TEXT, accion TEXT, motivo TEXT
);
"""


def conectar(ruta: str = RUTA_DB) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    nueva = not os.path.exists(ruta)
    con = sqlite3.connect(ruta)
    if nueva:
        os.chmod(ruta, 0o600)
    con.executescript(ESQUEMA)
    return con


def _ahora() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _auditar(con, cuit, organismo, accion, motivo=""):
    con.execute("INSERT INTO auditoria VALUES (?,?,?,?,?)", (_ahora(), cuit, organismo, accion, motivo))


# ---------------------------------------------------------------- operaciones
def guardar_acceso(cuit: str, organismo: str, usuario: str, clave: str, *, detalle: str = "",
                   nivel: str = "", token: str = "N", metodo: str = "Directo",
                   con: sqlite3.Connection | None = None, f: Fernet | None = None) -> None:
    cuit = _limpiar_cuit(cuit)
    if organismo not in ORGANISMOS:
        raise ErrorAlmacen(f"Organismo desconocido: {organismo}")
    if not clave:
        raise ErrorAlmacen(f"Clave vacía para {cuit} / {organismo}")
    f = f or _fernet()
    propia = con is None
    con = con or conectar()
    try:
        con.execute(
            "INSERT OR REPLACE INTO accesos VALUES (?,?,?,?,?,?,?,?,?,?)",
            (cuit, organismo, detalle or "", _limpiar_cuit(usuario) if usuario.replace("-", "").isdigit() else usuario,
             f.encrypt(clave.encode()), nivel, token, metodo, "Sin verificar", _ahora()))
        _auditar(con, cuit, organismo, "alta/modificación de clave")
        con.commit()
    finally:
        if propia:
            con.close()


def obtener_clave(cuit: str, organismo: str, motivo: str, detalle: str = "") -> tuple[str, str, str]:
    """Devuelve (usuario, clave, metodo). Solo para uso de los robots al ingresar."""
    cuit = _limpiar_cuit(cuit)
    with closing(conectar()) as con:
        fila = con.execute("SELECT usuario, clave_cifrada, metodo FROM accesos WHERE cuit=? AND organismo=? AND detalle=?",
                           (cuit, organismo, detalle)).fetchone()
        if not fila:
            raise ErrorAlmacen(f"No hay clave cargada para {cuit} / {organismo} {detalle}".strip())
        try:
            clave = _fernet().decrypt(fila[1]).decode()
        except InvalidToken as e:
            raise ErrorAlmacen("No se pudo descifrar la clave (¿llave maestra distinta?)") from e
        _auditar(con, cuit, organismo, "uso de clave", motivo)
        con.commit()
    return fila[0], clave, fila[2]


def marcar_estado(cuit: str, organismo: str, estado: str, detalle: str = "") -> None:
    with closing(conectar()) as con:
        con.execute("UPDATE accesos SET estado=?, actualizado=? WHERE cuit=? AND organismo=? AND detalle=?",
                    (estado, _ahora(), _limpiar_cuit(cuit), organismo, detalle))
        _auditar(con, cuit, organismo, f"estado: {estado}")
        con.commit()


def listar() -> list[tuple]:
    """Listado SIN claves: cuit, organismo, detalle, usuario, método, estado, actualizado."""
    with closing(conectar()) as con:
        return con.execute("SELECT cuit, organismo, detalle, usuario, metodo, estado, actualizado "
                           "FROM accesos ORDER BY cuit, organismo").fetchall()


def listar_relacionados() -> list[tuple]:
    with closing(conectar()) as con:
        return con.execute("SELECT cuit, cuit_relacionado, nombre, vinculo, consolidar FROM relacionados "
                           "ORDER BY cuit").fetchall()


def razon_social(cuit: str) -> str:
    with closing(conectar()) as con:
        f = con.execute("SELECT razon_social FROM clientes WHERE cuit=?", (cuit,)).fetchone()
        if f and f[0]:
            return f[0]
        f = con.execute("SELECT nombre FROM relacionados WHERE cuit_relacionado=? AND nombre<>''", (cuit,)).fetchone()
        return f[0] if f else ""


def _limpiar_cuit(c) -> str:
    if isinstance(c, float) and c.is_integer():   # Excel a veces guarda el CUIT como número
        c = int(c)
    c = "".join(ch for ch in str(c or "") if ch.isdigit())
    if len(c) != 11:
        raise ErrorAlmacen(f"CUIT inválido: {c!r}")
    return c


# ---------------------------------------------------------------- importador
CUIT_EJEMPLO = {"20000000001", "20000000002"}   # filas de ejemplo de la plantilla


def _hoja(wb, nombre: str):
    """Busca la hoja por nombre sin importar mayúsculas ni espacios."""
    for h in wb.sheetnames:
        if h.strip().lower() == nombre.lower():
            return wb[h]
    raise ErrorAlmacen(f"La planilla no tiene la hoja '{nombre}' (hojas encontradas: {', '.join(wb.sheetnames)})")


def _filas(ws):
    """Recorre desde la fila 3 hasta la última con datos. Columnas por TÍTULO (fila 1), no por posición."""
    enc = [str(c.value).strip() if c.value is not None else "" for c in next(ws.iter_rows(min_row=1, max_row=1))]
    if "CUIT" not in enc:
        raise ErrorAlmacen(f"La hoja '{ws.title}' no tiene la columna 'CUIT' en la fila 1")
    for n, fila in enumerate(ws.iter_rows(min_row=3, values_only=True), start=3):
        if not any(v not in (None, "") for v in fila):
            continue                                   # fila vacía
        yield n, dict(zip(enc, fila))


def _clave_texto(v) -> str:
    """Excel convierte claves numéricas en número (1234 -> 1234.0). Las devolvemos como texto.
    No puede recuperar ceros iniciales perdidos: por eso la columna Clave debe tener formato Texto."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)


def _es_ejemplo(cuit_txt: str) -> bool:
    return "".join(ch for ch in cuit_txt if ch.isdigit()) in CUIT_EJEMPLO


def importar_plantilla(ruta_xlsx: str) -> dict:
    """Importa la plantilla de carga. Devuelve un resumen SIN datos sensibles.
    Se puede volver a importar la misma planilla (o una nueva con más clientes):
    lo existente se actualiza y lo nuevo se agrega; no se duplica nada."""
    from openpyxl import load_workbook
    try:
        wb = load_workbook(ruta_xlsx, read_only=True, data_only=True)
    except Exception as e:
        raise ErrorAlmacen("No se pudo abrir la planilla (¿tiene contraseña de apertura? quitala solo "
                           "para la importación y borrá el archivo después)") from e
    f = _fernet()
    r = {"clientes": 0, "accesos": 0, "relacionados": 0, "errores": [], "avisos": []}
    with closing(conectar()) as con:
        cuits_clientes = set()
        for n, d in _filas(_hoja(wb, "Clientes")):
            if _es_ejemplo(str(d.get("CUIT") or "")):
                r["avisos"].append(f"Clientes fila {n}: es la fila de ejemplo, se ignora")
                continue
            try:
                cuit = _limpiar_cuit(d.get("CUIT"))
                otros = {k: v for k, v in d.items() if k not in ("CUIT", "Razón social") and v not in (None, "")}
                con.execute("INSERT OR REPLACE INTO clientes VALUES (?,?,?)",
                            (cuit, str(d.get("Razón social") or ""), repr(otros)))
                cuits_clientes.add(cuit)
                r["clientes"] += 1
            except ErrorAlmacen as e:
                r["errores"].append(f"Clientes fila {n}: {e}")

        cuits_accesos = set()
        for n, d in _filas(_hoja(wb, "Accesos")):
            if _es_ejemplo(str(d.get("CUIT") or "")):
                r["avisos"].append(f"Accesos fila {n}: es la fila de ejemplo, se ignora")
                continue
            try:
                cuit = _limpiar_cuit(d.get("CUIT"))
                if isinstance(d.get("Clave"), (int, float)):
                    r["avisos"].append(f"Accesos fila {n}: la clave está guardada como NÚMERO en Excel; "
                                       "si empieza con 0, se perdió. Poné la columna Clave en formato Texto")
                org = str(d.get("Organismo") or "").strip()
                if org == "ARCA" and d.get("Detalle organismo"):
                    r["avisos"].append(f"Accesos fila {n}: 'Detalle organismo' se ignora para ARCA")
                    d["Detalle organismo"] = ""
                guardar_acceso(
                    cuit, str(d.get("Organismo") or "").strip(),
                    str(d.get("Usuario") or cuit).strip(), _clave_texto(d.get("Clave")),
                    detalle=str(d.get("Detalle organismo") or "").strip(), nivel=str(d.get("Nivel clave ARCA") or ""),
                    token=str(d.get("Tiene token / 2FA") or "N").strip().upper()[:1] or "N",
                    metodo=str(d.get("Método de ingreso") or "Directo").strip() or "Directo",
                    con=con, f=f)
                cuits_accesos.add(cuit)
                r["accesos"] += 1
            except ErrorAlmacen as e:
                r["errores"].append(f"Accesos fila {n}: {e}")   # el mensaje nunca incluye la clave
        # Relacionados (opcional): grupos para los informes consolidados
        try:
            ws_rel = _hoja(wb, "Relacionados")
        except ErrorAlmacen:
            ws_rel = None
        if ws_rel is not None:
            enc = [str(c.value).strip() if c.value is not None else "" for c in next(ws_rel.iter_rows(min_row=1, max_row=1))]
            for n, fila in enumerate(ws_rel.iter_rows(min_row=3, values_only=True), start=3):
                if not any(v not in (None, "") for v in fila):
                    continue
                d = dict(zip(enc, fila))
                if _es_ejemplo(str(d.get("CUIT cliente") or "")) or _es_ejemplo(str(d.get("CUIT relacionado") or "")):
                    r["avisos"].append(f"Relacionados fila {n}: es la fila de ejemplo, se ignora")
                    continue
                try:
                    a, b = _limpiar_cuit(d.get("CUIT cliente")), _limpiar_cuit(d.get("CUIT relacionado"))
                    cons = str(d.get("Consolidar en informes") or "S").strip().upper()[:1]
                    con.execute("INSERT OR REPLACE INTO relacionados VALUES (?,?,?,?,?,?)",
                                (a, b, str(d.get("Nombre relacionado") or ""), str(d.get("Vínculo") or ""),
                                 "N" if cons == "N" else "S", str(d.get("Observaciones") or "")))
                    r["relacionados"] += 1
                except ErrorAlmacen as e:
                    r["errores"].append(f"Relacionados fila {n}: {e}")
        con.commit()
    for c in sorted(cuits_clientes - cuits_accesos):
        r["avisos"].append(f"El cliente ...{c[-4:]} no tiene ninguna clave en la hoja Accesos")
    for c in sorted(cuits_accesos - cuits_clientes):
        r["avisos"].append(f"La clave del CUIT ...{c[-4:]} no tiene fila en la hoja Clientes")
    return r


# ---------------------------------------------------------------- bandeja de la pantalla web
RUTA_SOBRES_PRIV = os.environ.get("ROBOTS_SOBRES_PRIV", "/etc/robots/sobres_privada.pem")
RUTA_SOBRES_PUB = os.environ.get("ROBOTS_SOBRES_PUB", "/etc/robots/sobres_publica.pem")
BANDEJA = os.environ.get("ROBOTS_BANDEJA", "/var/lib/robots-bandeja")
PUBLICO = os.environ.get("ROBOTS_PUBLICO", "/var/lib/robots/publico")


def crear_llaves_sobres() -> None:
    """Par RSA para los sobres de la pantalla web. La privada queda solo para este usuario."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    if os.path.exists(RUTA_SOBRES_PRIV):
        raise ErrorAlmacen(f"Ya existe {RUTA_SOBRES_PRIV}. No se sobrescribe.")
    os.makedirs(os.path.dirname(RUTA_SOBRES_PRIV), exist_ok=True)
    k = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    fd = os.open(RUTA_SOBRES_PRIV, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()))
    with open(RUTA_SOBRES_PUB, "wb") as f:
        f.write(k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))


def _abrir_sobre(clave_b64: str) -> str:
    import base64
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    with open(RUTA_SOBRES_PRIV, "rb") as f:
        priv = serialization.load_pem_private_key(f.read(), password=None)
    return priv.decrypt(base64.b64decode(clave_b64),
                        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)).decode()


def _verificar(cuit: str, organismo: str) -> str:
    """Una sola comprobación del ingreso tras cargar/cambiar una clave (no se reintenta)."""
    import subprocess
    cmd = {"ARCA": ["situacion_fiscal", "--cuit", cuit, "--solo", "sct"], "ARBA": ["arba_dfe", "--cuit", cuit]}.get(organismo)
    if not cmd:
        return "guardada (este organismo no se verifica automáticamente)"
    try:
        subprocess.run([sys.executable, "-m", "robots.correr", *cmd], capture_output=True, timeout=1500)
    except Exception:
        return "guardada; la verificación no se pudo completar"
    with closing(conectar()) as con:
        f = con.execute("SELECT estado FROM accesos WHERE cuit=? AND organismo=? AND detalle=''", (cuit, organismo)).fetchone()
    e = f[0] if f else "?"
    return {"OK": "aplicada y verificada: ingresó bien"}.get(e, f"aplicada; estado tras verificar: {e}")


def procesar_bandeja(verificar: bool = True) -> dict:
    """Aplica los sobres que dejó la pantalla web. Se puede correr cada pocos minutos; es idempotente."""
    import fcntl
    import json
    import shutil
    r = {"aplicados": 0, "rechazados": 0}
    if not os.path.isdir(BANDEJA):
        return r
    lock = open(os.path.join(os.path.dirname(RUTA_DB), "bandeja.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return r                                   # ya hay otro proceso trabajando
    hechos = []
    rech = os.path.join(BANDEJA, "rechazados")
    for n in sorted(os.listdir(BANDEJA)):
        if not n.endswith(".json"):
            continue
        ruta = os.path.join(BANDEJA, n)
        s = {}
        try:
            with open(ruta, encoding="utf-8") as f:
                s = json.load(f)
            cuit = _limpiar_cuit(s["cuit"])
            if s.get("tipo") == "razon_social":          # corrección de datos desde la web (solo admin, 20/11/2026)
                with closing(conectar()) as con:
                    ex = con.execute("SELECT datos FROM clientes WHERE cuit=?", (cuit,)).fetchone()
                    con.execute("INSERT OR REPLACE INTO clientes VALUES (?,?,?)",
                                (cuit, str(s.get("razon_social") or "")[:120], ex[0] if ex else "{}"))
                    _auditar(con, cuit, "-", "razón social corregida desde la web", f"por {s.get('por', '?')}")
                    con.commit()
                os.remove(ruta)
                r["aplicados"] += 1
                try:
                    from .publicar import publicar
                    publicar()
                except Exception:
                    pass
                continue
            org = s["organismo"]
            detalle = s.get("detalle") or ""
            clave = _abrir_sobre(s["clave_sellada"])
            with closing(conectar()) as con:
                ant = con.execute("SELECT usuario, clave_cifrada FROM accesos WHERE cuit=? AND organismo=? AND detalle=?",
                                  (cuit, org, detalle)).fetchone()
                if ant:
                    con.execute("INSERT OR REPLACE INTO accesos_previos VALUES (?,?,?,?,?,?)",
                                (cuit, org, detalle, ant[0], ant[1], _ahora()))
                usuario = s.get("usuario") or (ant[0] if ant else cuit)
                if s.get("razon_social"):
                    ex = con.execute("SELECT datos FROM clientes WHERE cuit=?", (cuit,)).fetchone()
                    con.execute("INSERT OR REPLACE INTO clientes VALUES (?,?,?)", (cuit, s["razon_social"], ex[0] if ex else "{}"))
                guardar_acceso(cuit, org, usuario, clave, detalle=detalle, con=con)
                _auditar(con, cuit, org, "clave cargada desde la pantalla", f"por {s.get('por', '?')}")
                con.commit()
            clave = ""
            os.remove(ruta)
            r["aplicados"] += 1
            hechos.append({"fecha": _ahora(), "cuit": cuit, "organismo": org, "estado": "aplicado",
                           "motivo": "guardada, verificando" if verificar else "guardada"})
        except Exception as e:                      # el mensaje nunca incluye la clave
            os.makedirs(rech, exist_ok=True)
            try:
                shutil.move(ruta, os.path.join(rech, n))
            except OSError:
                pass
            r["rechazados"] += 1
            hechos.append({"fecha": _ahora(), "cuit": s.get("cuit", ""), "organismo": s.get("organismo", ""),
                           "estado": "rechazado", "motivo": type(e).__name__ + (f": {e}" if isinstance(e, ErrorAlmacen) else "")})
    _publicar_estado(hechos)
    if verificar:
        for h in hechos:
            if h["estado"] == "aplicado":
                h["motivo"] = _verificar(h["cuit"], h["organismo"])
        _reescribir_estado(hechos)
    try:
        from . import publicar
        publicar.publicar()
    except Exception:
        pass
    return r


def _ruta_estado() -> str:
    return os.path.join(PUBLICO, "bandeja_estado.json")


def _leer_estado() -> list:
    import json
    try:
        with open(_ruta_estado(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _publicar_estado(nuevos: list) -> None:
    import json
    os.makedirs(PUBLICO, exist_ok=True)
    lista = (nuevos[::-1] + _leer_estado())[:50]
    tmp = _ruta_estado() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lista, f, ensure_ascii=False)
    os.chmod(tmp, 0o640)
    os.replace(tmp, _ruta_estado())


def _reescribir_estado(hechos: list) -> None:
    """Actualiza el texto de resultado de lo recién aplicado, una vez verificado."""
    import json
    lista = _leer_estado()
    for h in hechos:
        for x in lista:
            if x["fecha"] == h["fecha"] and x["cuit"] == h["cuit"] and x["organismo"] == h["organismo"]:
                x["motivo"] = h["motivo"]
    tmp = _ruta_estado() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lista, f, ensure_ascii=False)
    os.chmod(tmp, 0o640)
    os.replace(tmp, _ruta_estado())


def _main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "crear-llave":
        crear_llave()
        print(f"Llave creada en {RUTA_LLAVE}. Hacé una copia en un pendrive guardado bajo llave: sin ella no se pueden leer las claves.")
    elif cmd == "importar":
        r = importar_plantilla(sys.argv[2])
        print(f"Clientes cargados: {r['clientes']} | Accesos cargados: {r['accesos']} | "
              f"Relacionados: {r['relacionados']} | Errores: {len(r['errores'])}")
        for e in r["errores"]:
            print("  ERROR -", e)
        for a in r["avisos"]:
            print("  aviso -", a)
    elif cmd == "crear-llaves-sobres":
        crear_llaves_sobres()
        print(f"Llaves creadas: privada en {RUTA_SOBRES_PRIV} (solo este usuario), pública en {RUTA_SOBRES_PUB}.")
    elif cmd == "procesar-bandeja":
        r = procesar_bandeja(verificar="--sin-verificar" not in sys.argv)
        if r["aplicados"] or r["rechazados"]:
            print(f"Bandeja: {r['aplicados']} aplicada(s), {r['rechazados']} rechazada(s)")
    elif cmd == "listar":
        for fila in listar():
            print(" | ".join(str(x) for x in fila))
        rel = listar_relacionados()
        if rel:
            print("\n== Relacionados ==")
            for fila in rel:
                print(" | ".join(str(x) for x in fila))
    else:
        print(__doc__)


if __name__ == "__main__":
    try:
        _main()
    except ErrorAlmacen as e:
        print("ERROR:", e)
        sys.exit(1)
