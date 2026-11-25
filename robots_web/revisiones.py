"""Revisiones diarias de clientes (Tomás, 25/11/2026).

Cada usuario con revisiones (por defecto Guido) tiene que revisar TODOS sus clientes una vez por mes. Los clientes
se reparten al azar entre los días hábiles del mes (lunes a viernes sin feriados nacionales ni días no laborables);
el reparto se guarda la primera vez que se arma el mes y no cambia (un cliente nuevo va al día hábil que queda con
menos; uno que ya no lleva sale del plan). En la bandeja "Revisiones diarias" tilda cada cliente como revisado.
Cada dos días sale un reporte a Tomás con lo que tenía que revisar y no revisó.

Uso por cron (lo instala nube/actualizar_desde_github.sh):  python -m robots_web.revisiones reporte
"""
from __future__ import annotations

import datetime as dt
import random
import sys

from . import usuarios

# Feriados nacionales y días no laborables con fines turísticos (Ley 27.399, Res. 164/2025). Revisar cada año.
FERIADOS = {
    # 2026
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-03-23", "2026-03-24", "2026-04-02", "2026-04-03", "2026-05-01",
    "2026-05-25", "2026-06-15", "2026-06-20", "2026-07-09", "2026-07-10", "2026-08-17", "2026-10-12", "2026-11-23",
    "2026-12-07", "2026-12-08", "2026-12-25",
    # 2027: solo los inamovibles y los trasladables según la ley (completar con el calendario oficial cuando salga)
    "2027-01-01", "2027-02-08", "2027-02-09", "2027-03-24", "2027-03-25", "2027-03-26", "2027-04-02", "2027-05-01",
    "2027-05-25", "2027-06-20", "2027-07-09", "2027-12-08", "2027-12-25",
}
REPORTE_CADA_DIAS = 2


def dias_habiles(mes: str) -> list[dt.date]:
    a, m = map(int, mes.split("-"))
    d = dt.date(a, m, 1)
    out = []
    while d.month == m:
        if d.weekday() < 5 and d.isoformat() not in FERIADOS:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def _tabla(con):
    con.execute("""CREATE TABLE IF NOT EXISTS revisiones (usuario TEXT, mes TEXT, cuit TEXT, dia TEXT,
                   hecho TEXT, hecho_por TEXT, nota TEXT, PRIMARY KEY (usuario, mes, cuit))""")
    con.execute("CREATE TABLE IF NOT EXISTS revisiones_usuarios (usuario TEXT PRIMARY KEY)")


def usuarios_con_revisiones() -> list[str]:
    con = usuarios.conectar()
    _tabla(con)
    r = [x[0] for x in con.execute("SELECT usuario FROM revisiones_usuarios ORDER BY usuario")]
    if not r:                                              # por defecto: los usuarios que se llaman Guido
        r = [u[0] for u in usuarios.listar() if u[3] and (u[0].lower().startswith("guido")
                                                          or (u[1] or "").lower().startswith("guido"))]
    con.close()
    return [] if r == ["-"] else [x for x in r if x != "-"]


def fijar_usuarios(lista: list[str]) -> None:
    con = usuarios.conectar()
    _tabla(con)
    with con:
        con.execute("DELETE FROM revisiones_usuarios")
        for u in lista:
            con.execute("INSERT OR IGNORE INTO revisiones_usuarios VALUES (?)", (u,))
        if not lista:                                      # nadie: se guarda un marcador para no volver al defecto
            con.execute("INSERT OR IGNORE INTO revisiones_usuarios VALUES ('-')")
    con.close()


def plan(usuario: str, mes: str) -> list[dict]:
    """Plan del mes del usuario, armándolo o completándolo con los clientes que lleva hoy."""
    clientes = sorted(usuarios.asignados(usuario))
    habiles = [d.isoformat() for d in dias_habiles(mes)]
    con = usuarios.conectar()
    _tabla(con)
    with con:
        guardado = {c: d for c, d in con.execute("SELECT cuit, dia FROM revisiones WHERE usuario=? AND mes=?", (usuario, mes))}
        nuevos = [c for c in clientes if c not in guardado]
        if nuevos and habiles:
            hoy = dt.date.today().isoformat()
            libres = [d for d in habiles if d >= hoy] or habiles[-1:]
            if not guardado:                               # primera vez en el mes: todos los días hábiles
                libres = habiles
            carga = {d: sum(1 for x in guardado.values() if x == d) for d in libres}
            rnd = random.Random(f"{usuario}-{mes}")
            rnd.shuffle(nuevos)
            for c in nuevos:
                d = min(libres, key=lambda x: (carga[x], rnd.random()))
                carga[d] += 1
                con.execute("INSERT INTO revisiones (usuario, mes, cuit, dia) VALUES (?,?,?,?)", (usuario, mes, c, d))
        # los que ya no lleva y no se revisaron salen del plan
        for c in set(guardado) - set(clientes):
            con.execute("DELETE FROM revisiones WHERE usuario=? AND mes=? AND cuit=? AND hecho IS NULL", (usuario, mes, c))
    filas = [dict(zip(("cuit", "dia", "hecho", "hecho_por", "nota"), f)) for f in con.execute(
        "SELECT cuit, dia, hecho, hecho_por, nota FROM revisiones WHERE usuario=? AND mes=? ORDER BY dia, cuit", (usuario, mes))]
    con.close()
    return filas


def marcar(usuario: str, mes: str, cuit: str, hecho: bool, por: str, nota: str = "") -> bool:
    con = usuarios.conectar()
    _tabla(con)
    with con:
        n = con.execute("UPDATE revisiones SET hecho=?, hecho_por=?, nota=? WHERE usuario=? AND mes=? AND cuit=?",
                        (usuarios.ahora() if hecho else None, por if hecho else None, nota[:300] if hecho else None,
                         usuario, mes, cuit)).rowcount
    con.close()
    return n == 1


def atrasados(usuario: str, hoy: dt.date | None = None) -> list[dict]:
    """Lo que tenía que revisar hasta AYER y no revisó (mes en curso y, en los primeros días, el anterior)."""
    hoy = hoy or dt.date.today()
    meses = [hoy.strftime("%Y-%m")]
    if hoy.day <= 7:
        meses.insert(0, (hoy.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m"))
    out = []
    for mes in meses:
        for f in plan(usuario, mes):
            if not f["hecho"] and f["dia"] < hoy.isoformat():
                out.append({**f, "mes": mes})
    return out


def texto_reporte(hoy: dt.date | None = None) -> tuple[str, str, int]:
    from . import datos
    hoy = hoy or dt.date.today()
    nombres = {c["cuit"]: c.get("razon_social") or "" for c in datos.lista_clientes()}
    us = {u[0]: (u[1] or u[0]) for u in usuarios.listar()}
    partes, total = [], 0
    for u in usuarios_con_revisiones():
        if u == "-":
            continue
        at = atrasados(u, hoy)
        total += len(at)
        mes = plan(u, hoy.strftime("%Y-%m"))
        hechos = sum(1 for f in mes if f["hecho"])
        partes.append(f"{us.get(u, u)}: {len(at)} cliente(s) sin revisar que ya tenía que haber revisado "
                      f"(en el mes lleva {hechos} de {len(mes)} revisados).")
        for f in at:
            d = dt.date.fromisoformat(f["dia"])
            partes.append(f"   • {d:%d/%m} — {nombres.get(f['cuit'], '')} ({datos.cuit_fmt(f['cuit'])})")
        partes.append("")
    asunto = f"Revisiones diarias: {total} cliente(s) sin revisar al {hoy:%d/%m/%Y}"
    cuerpo = ("Reporte automático del Monitoreo fiscal (cada dos días).\n\n" + "\n".join(partes)
              + "\nSe ve y se tilda en la web: menú Revisiones.")
    return asunto, cuerpo, total


def reporte(hoy: dt.date | None = None, forzar: bool = False) -> str:
    """Corre todos los días por cron; manda el reporte día por medio. El mail sale por la bandeja del robot."""
    hoy = hoy or dt.date.today()
    if not forzar and hoy.toordinal() % REPORTE_CADA_DIAS:
        return "hoy no toca"
    asunto, cuerpo, total = texto_reporte(hoy)
    from . import pedidos
    pedidos.encolar_reporte_revisiones(asunto, cuerpo)
    usuarios.registrar("sistema", "reporte de revisiones", f"{total} sin revisar", "")
    return f"encolado: {asunto}"


if __name__ == "__main__":
    if sys.argv[1:2] == ["reporte"]:
        print(reporte(forzar="--ya" in sys.argv))
    else:
        print(__doc__)
