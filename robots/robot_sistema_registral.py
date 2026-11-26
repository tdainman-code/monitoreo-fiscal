"""ARCA · Sistema Registral: datos registrales del cliente para autocompletar su ficha.

Recorrido mostrado por Gabriel el 25/11/2026 con NABAJUMA S.A. (30-71222757-1):
  Portal ARCA -> buscador "Sistema registral" (seti.afip.gob.ar/padron-puc-consulta-internet)
  -> "Elegí una persona para ingresar": YO / Mis representados (tarjetas NOMBRE + CUIT xx-xxxxxxxx-x)
  -> Inicio (Estado de la CUIT: Activa · Mi dependencia) -> menú izquierdo "Consulta" -> Datos registrales:
     encabezado (CUIT, DENOMINACIÓN, FECHA CONTRATO SOCIAL, FORMA JURÍDICA)
     Datos fiscales (DEPENDENCIA, REGIÓN, SISTEMA DE CONTROL, MES DE CIERRE, FECHA DE INSCRIPCIÓN, TIPO DE INSCRIPCIÓN,
       PASIVO DECRETO 1299, ÚLTIMA ACTUALIZACIÓN, REGISTRA IMPUESTOS ACTIVOS?)
     Domicilio fiscal electrónico · Domicilios (Tipo, Estado, Dirección, Localidad, Provincia) · E-Mails · Teléfonos
     Ganancia Simplificada · Caracterizaciones (Código, Descripción, Período, Motivo)
     Impuestos y/o Aportes (Código, Descripción, Estado, Período)  <- 30 IVA, 10 Ganancias, 5900 IIBB CM, 301 Empleador...
     Datos de actividad económica (Nomenclador, Código, Descripción, Orden) · Traslados · Otros datos
  -> "Registros Especiales" -> Registro Aduanero "DESPLEGAR" -> "Consulta de datos Aduaneros":
     Situación en el Sistema Registral (Tipo de Operador IMPORTADOR/EXPORTADOR, fechas) · Estados del operador (HABILITADO)
Solo consulta. Resultado: DATOS/<cuit>/sistema_registral/<fecha>.json (la web completa la ficha con lo que falte).
"""
from __future__ import annotations

import json
import os
import re
from datetime import date

from . import arca

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
arca.SERVICIOS.setdefault("sistema_registral", "texto:SISTEMA\\s+REGISTRAL")

JS_SECCIONES = r"""() => {
  // cada tabla con el título de su tarjeta (el encabezado más cercano hacia arriba)
  const titulo = t => { let e = t;
    for (let i = 0; i < 8 && e; i++, e = e.parentElement) {
      const h = e.querySelector('h1,h2,h3,h4,h5,.card-title,.panel-title,[class*=titulo],[class*=title]');
      if (h && !t.contains(h) && h.innerText.trim()) return h.innerText.trim(); }
    return ''; };
  return [...document.querySelectorAll('table')].map(t => ({titulo: titulo(t),
    filas: [...t.querySelectorAll('tr')].map(r => [...r.cells].map(c => c.innerText.replace(/\s+/g, ' ').trim()))}));
}"""

ETIQUETAS = {
    "denominacion": r"DENOMINACI[OÓ]N", "fecha_contrato": r"FECHA CONTRATO SOCIAL", "forma_juridica": r"FORMA JUR[IÍ]DICA",
    "dependencia": r"DEPENDENCIA", "region": r"REGI[OÓ]N", "sistema_control": r"SISTEMA DE CONTROL",
    "mes_cierre": r"MES DE CIERRE", "fecha_inscripcion": r"FECHA DE INSCRIPCI[OÓ]N", "tipo_inscripcion": r"TIPO DE INSCRIPCI[OÓ]N",
    "pasivo_1299": r"PASIVO DECRETO 1299", "ultima_actualizacion": r"[UÚ]LTIMA ACTUALIZACI[OÓ]N",
    "impuestos_activos": r"REGISTRA IMPUESTOS ACTIVOS\??",
}


def leer_datos(texto: str) -> dict:
    """Pares 'ETIQUETA: valor' de los bloques de arriba (el valor puede venir en la línea siguiente)."""
    lineas = [l.strip() for l in texto.replace("\xa0", " ").splitlines() if l.strip()]
    out = {}
    for k, pat in ETIQUETAS.items():
        for i, l in enumerate(lineas):
            m = re.match(rf"^{pat}\s*:\s*(.*)$", l, re.I)
            if m:
                v = m[1].strip() or (lineas[i + 1] if i + 1 < len(lineas) and not re.search(r":\s*$", lineas[i + 1]) else "")
                out[k] = v
                break
    m = re.search(r"adherido al domicilio fiscal electr[oó]nico:\s*(S[IÍ]|NO)", texto, re.I)
    if m:
        out["dfe_adherido"] = m[1].upper().startswith("S")
    m = re.search(r"Estado de la CUIT\s*\n?\s*(\w+)", texto, re.I)
    if m:
        out["estado_cuit"] = m[1]
    return out


def _tabla(secciones: list[dict], patron: str) -> list[dict]:
    for s in secciones:
        if re.search(patron, s.get("titulo") or "", re.I) and s.get("filas"):
            cab = s["filas"][0]
            return [dict(zip(cab, f)) for f in s["filas"][1:] if any(x for x in f)]
    return []


def leer_secciones(secciones: list[dict]) -> dict:
    imp = [{"codigo": f.get("Código", ""), "descripcion": f.get("Descripción", ""), "estado": f.get("Estado", ""),
            "periodo": f.get("Período", "")} for f in _tabla(secciones, r"Impuestos")]
    return {
        "impuestos": imp,
        "actividades": [{"nomenclador": f.get("Nomenclador", ""), "codigo": f.get("Código", ""),
                         "descripcion": f.get("Descripción", ""), "orden": f.get("Orden", "")}
                        for f in _tabla(secciones, r"actividad")],
        "caracterizaciones": [{"codigo": f.get("Código", ""), "descripcion": f.get("Descripción", ""),
                               "periodo": f.get("Período", ""), "motivo": f.get("Motivo", "")}
                              for f in _tabla(secciones, r"Caracterizaci")],
        "domicilios": [{"tipo": f.get("Tipo", ""), "estado": f.get("Estado", ""), "direccion": f.get("Dirección", ""),
                        "localidad": f.get("Localidad", ""), "provincia": f.get("Provincia", "")}
                       for f in _tabla(secciones, r"Domicilios")],
        "emails": [{"mail": f.get("Mail", ""), "tipo": f.get("Tipo", "")} for f in _tabla(secciones, r"E-?Mails")],
        "telefonos": [{"numero": f.get("Número de teléfono", ""), "tipo": f.get("Tipo", "")}
                      for f in _tabla(secciones, r"Tel[eé]fonos")],
    }


def leer_aduana(texto: str) -> dict:
    """Consulta de datos Aduaneros: tipo de operador y su estado."""
    t = re.sub(r"[ \t]+", " ", texto)
    m = re.search(r"Tipo de Operador.*?\n\s*([A-ZÁÉÍÓÚ/ ]{4,})\s+(\d{2}-\d{2}-\d{4})", t, re.S)
    e = re.search(r"Estados del operador.*?Fecha vigencia desde\s*\n?\s*([A-ZÁÉÍÓÚ/ ]{4,}?)\s+(HABILITADO|INHABILITADO|SUSPENDIDO|[A-Z]+)\s",
                  t, re.S)
    # Gaby 26/11/2026 (su CUIT): quien NO es operador ve solo Domicilio aduanero electrónico / Solvencia económica /
    # Datos digitales, sin "Tipo de Operador": no es importador.
    no_operador = not m and bool(re.search(r"Solvencia econ[oó]mica|Domicilio aduanero electr[oó]nico", t, re.I))
    return {"operador": (m[1].strip() if m else ""), "desde": (m[2] if m else ""), "no_operador": no_operador,
            "estado": (e[2] if e else ""), "sicnea": bool(re.search(r"adherido al SICNEA\s*\n?\s*SI", t, re.I))}


def resumen_ficha(r: dict) -> dict:
    """Lo que se puede completar en Datos del cliente (la web solo llena lo vacío)."""
    activos = {i["codigo"]: i for i in r.get("impuestos") or [] if re.match(r"ACTIVO", i.get("estado") or "", re.I)}
    desc = " ".join(i["descripcion"].upper() for i in activos.values())
    out = {}
    if "30" in activos:
        out["condicion_iva"] = "Responsable inscripto"
    elif re.search(r"MONOTRIBUTO|R[EÉ]GIMEN SIMPLIFICADO", desc) or {"20", "21"} & set(activos):
        out["condicion_iva"] = "Monotributo"
    elif "32" in activos or "IVA EXENTO" in desc:
        out["condicion_iva"] = "Exento"
    if {"10", "11"} & set(activos):
        out["condicion_ganancias"] = "Inscripto"
    elif out.get("condicion_iva") == "Monotributo":
        out["condicion_ganancias"] = "Monotributo"
    if "211" in activos:
        out["bienes_personales"] = "Responsable sustituto"
    elif "180" in activos:
        out["bienes_personales"] = "Inscripto"
    if "5900" in activos or "CONVENIO MULTILATERAL" in desc:
        out["regimen_iibb"] = "Convenio Multilateral"
    if "301" in activos:
        out["empleador"] = "Sí"
    meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre",
             "Noviembre", "Diciembre"]
    mc = re.sub(r"\D", "", str(r.get("mes_cierre") or ""))
    if mc and 1 <= int(mc) <= 12:
        out["mes_cierre"] = meses[int(mc) - 1]
    mails = [m["mail"] for m in r.get("emails") or [] if m.get("mail")]
    if mails:
        out["emails"] = ", ".join(mails)
    tels = [t["numero"] for t in r.get("telefonos") or [] if t.get("numero")]
    if tels:
        out["telefonos"] = ", ".join(tels)
    ad = r.get("aduana") or {}
    if ad.get("operador"):
        out["importador"] = f"{ad['operador']} ({ad.get('estado') or 'sin estado'})"
    elif ad.get("no_operador"):
        out["importador"] = "No"
    return out


# ------------------------------------------------------------------ navegación
URL_INDEX = "https://seti.afip.gob.ar/padron-puc-consulta-internet/ResponsiveIndexInternetAction.do?idPersona={}"


def _elegir_persona(pag, cuit: str) -> None:
    for _ in range(20):                                  # la página tarda: o pide persona o ya muestra el inicio
        t = pag.inner_text("body")
        if re.search(r"Eleg[ií] una persona|Estado de la CUIT|Sistema registral", t, re.I):
            break
        pag.wait_for_timeout(1000)
    if not re.search(r"Eleg[ií] una persona", pag.inner_text("body"), re.I):
        return
    tarjeta = pag.get_by_text(arca.cuit_fmt(cuit), exact=False).locator("visible=true")
    if not tarjeta.count():
        raise arca.SinRepresentado(f"Sistema Registral: {arca.cuit_fmt(cuit)} no está entre las personas para ingresar")
    tarjeta.first.click()
    pag.wait_for_load_state("domcontentloaded")
    pag.wait_for_timeout(3000)


def _en_marcos(pag):
    """La página principal y sus marcos (iframes): el Sistema Registral puede dibujar el menú dentro de uno."""
    return [pag] + [f for f in pag.frames if f is not pag.main_frame]


def _menu(pag, nombre: str, cuit: str):
    """Menú izquierdo del Sistema Registral (Inicio / Consulta / Constancias / ... / Registros Especiales).
    Se busca en la página y en sus marcos; si no aparece, se entra directo al inicio del representado y se reintenta.
    Devuelve el marco donde quedó el contenido."""
    patron = re.compile(rf"^\s*{nombre}\s*$", re.I)
    for intento in range(3):
        for _ in range(12):
            for fr in _en_marcos(pag):
                try:
                    m = fr.locator("a, li, button, span, div").filter(has_text=patron).locator("visible=true")
                    if m.count():
                        m.last.click()
                        pag.wait_for_timeout(3000)
                        return fr
                except Exception:
                    continue
            pag.wait_for_timeout(1000)
        menu = pag.locator("button.navbar-toggler, [aria-label*='men' i], .menu-toggle, .hamburger").filter(visible=True)
        if menu.count():                                 # menú plegado en un botón (☰)
            menu.first.click()
            pag.wait_for_timeout(1000)
            continue
        if intento == 0:
            pag.goto(URL_INDEX.format(cuit), wait_until="domcontentloaded")
            pag.wait_for_timeout(3000)
    raise arca.ErrorRobot(f"Sistema Registral: no aparece '{nombre}' en el menú (página: {pag.url[:90]}; "
                          f"marcos: {len(pag.frames) - 1})")


def _ingresar_datos_registrales(pag, fr) -> None:
    """Gaby 26/11/2026 (su propio CUIT): "Consulta" muestra tarjetas — Datos registrales / Datos registrales
    jurisdiccionales / Datos aduaneros — cada una con INGRESAR. Se entra a "Datos registrales" (la primera, no la
    jurisdiccional) y se baja por la página desplegando las secciones."""
    for _ in range(20):
        for f in [fr] + _en_marcos(pag):
            try:
                if re.search(r"Impuestos y/o Aportes", f.inner_text("body", timeout=2000), re.I):
                    return
                tarjeta = f.locator("div, section, article").filter(
                    has=f.get_by_text(re.compile(r"^\s*Datos registrales\s*$", re.I))).filter(
                    has=f.get_by_text(re.compile(r"^\s*INGRESAR\s*$", re.I)))
                if tarjeta.count():
                    tarjeta.last.get_by_text(re.compile(r"^\s*INGRESAR\s*$", re.I)).first.click()
                    pag.wait_for_timeout(3000)
                    _desplegar_todo(pag)
                    return
            except Exception:
                continue
        pag.wait_for_timeout(1000)


def _desplegar_todo(pag) -> None:
    """Baja hasta el final (algunas secciones se cargan al verlas) y abre las que estén plegadas."""
    for f in _en_marcos(pag):
        try:
            f.evaluate("""() => { document.querySelectorAll('[aria-expanded="false"]').forEach(b => { try { b.click(); } catch (e) {} });
                                  window.scrollTo(0, document.body.scrollHeight); }""")
        except Exception:
            continue
    pag.wait_for_timeout(1500)


def _marco_con(pag, patron: str, espera_s: int = 45):
    for _ in range(espera_s):
        for fr in _en_marcos(pag):
            try:
                if re.search(patron, fr.inner_text("body", timeout=3000), re.I):
                    return fr
            except Exception:
                continue
        pag.wait_for_timeout(1000)
    raise arca.ErrorRobot(f"Sistema Registral: no apareció '{patron}'")


def leer(ctx, portal, cuit: str) -> dict:
    pag = arca.abrir_servicio(ctx, portal, "sistema_registral")
    try:
        try:                                             # la página es "responsive": angosta, esconde el menú izquierdo
            pag.set_viewport_size({"width": 1440, "height": 900})
        except Exception:
            pass
        _elegir_persona(pag, cuit)
        inicio = pag.inner_text("body")
        frc = _menu(pag, "Consulta", cuit)
        _ingresar_datos_registrales(pag, frc)
        fr = _marco_con(pag, r"Impuestos y/o Aportes")
        texto = fr.inner_text("body")
        if cuit not in re.sub(r"\D", "", texto[:4000]) and cuit not in re.sub(r"\D", "", pag.inner_text("body")[:4000]):
            raise arca.CuitEquivocado(f"Sistema Registral: no muestra el CUIT {arca.cuit_fmt(cuit)}")
        r = {**leer_datos(inicio + "\n" + texto), **leer_secciones(fr.evaluate(JS_SECCIONES))}
        try:                                             # importador / exportador (Registro Aduanero)
            vol = pag.get_by_text(re.compile(r"^\s*VOLVER\s*$", re.I)).locator("visible=true")
            if vol.count():
                vol.first.click()
                pag.wait_for_timeout(1500)
            fr2 = _menu(pag, "Registros Especiales", cuit)
            d = fr2.locator("button, a").filter(has_text=re.compile(r"DESPLEGAR", re.I)).locator("visible=true")
            if d.count():
                d.first.click()
                pag.wait_for_timeout(1000)
            antes = set(ctx.pages)
            fr2.get_by_text(re.compile(r"Consulta de datos Aduaneros", re.I)).first.click()
            pag.wait_for_timeout(3500)
            nuevas = [p for p in ctx.pages if p not in antes]
            dest = nuevas[-1] if nuevas else pag
            dest.wait_for_load_state("domcontentloaded")
            r["aduana"] = leer_aduana(_marco_con(dest, r"Tipo de Operador|Situaci[oó]n en el Sistema Registral|Solvencia econ[oó]mica|Domicilio aduanero electr[oó]nico", 30).inner_text("body"))
            if dest is not pag:
                dest.close()
        except Exception as e:
            r["aduana"] = {"error": str(e).splitlines()[0][:160] if str(e) else type(e).__name__}
        return r
    finally:
        pag.close()


def paso(cuit: str, estado: dict):
    def fn(ctx, portal):
        hoy = date.today()
        r = leer(ctx, portal, cuit)
        r.update(cuit=cuit, fecha=hoy.isoformat())
        r["ficha"] = resumen_ficha(r)
        d = os.path.join(DATOS, cuit, "sistema_registral")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{hoy.isoformat()}.json"), "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        estado.update(resultado=f"OK ({len(r.get('impuestos') or [])} impuestos, {len(r['ficha'])} datos para la ficha)")
        return "OK"
    return fn


def correr(cuit, periodo, usuario, clave, metodo="Directo", visible=False, **_):
    estado: dict = {}
    arca.ejecutar(usuario, clave, [("sistema_registral", paso(cuit, estado))], os.path.join(DATOS, cuit, "capturas"), visible)
    return {"cuit": cuit, "sistema_registral": estado.get("resultado"), "archivos": {"sistema_registral": {"alertas": []}}}
