"""Deuda histórica de Cuentas Tributarias (estado de cumplimiento), réplica de las pantallas que mandó Gaby el 17/11/2026
(menú a la izquierda, contenido en un iframe, "AÑO ANTERIOR" año por año; datos de fantasía).
Uso: PYTHONPATH=. python3 robots/pruebas/test_sct_historico.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ["ROBOTS_DATOS"] = tempfile.mkdtemp()
from playwright.sync_api import sync_playwright  # noqa: E402
from robots import arca, robot_sct_historico as rh  # noqa: E402

arca.pausa = lambda *a, **k: None
CUIT = "20111111112"
B = "https://ctacte.cloud.afip.gob.ar/contribuyente/"
ANIO = {"v": 2026}


def tabla(titulo, filas, sub):
    filas = [f if len(f) == 6 else (*f, "") for f in filas]          # 6° dato opcional: S.L.D. (19/11/2026)
    tr = "".join(f"<tr><td>0</td><td>{p}</td><td>{c}</td><td>0</td><td><a style='color:{col}'>{d}</a></td><td>{sld}</td><td></td>"
                 f"<td></td><td></td><td>En Término</td><td></td><td></td><td>{e}</td></tr>" for p, c, d, col, e, sld in filas)
    return (f"<h4>{titulo}</h4><div><span>EXPORTAR TABLA CSV</span></div><table><thead><tr><th>Est.</th><th>Período</th><th>Concepto</th>"
            "<th>Ant. / Cuota</th><th>DEUDA</th><th>S. L. D.</th><th>SALDO TECNICO</th><th>OTROS CREDITOS</th><th>MULTAS NO FIRMES</th>"
            "<th>Temp. DDJJ</th><th>Estado DDJJ</th><th>Temp. Pago</th><th>Estado Pago</th></tr></thead>"
            f"<tbody>{tr}<tr><td></td><td></td><td>Subtotal</td><td></td><td>{sub}</td></tr></tbody></table>")


def consulta():
    a = ANIO["v"]
    cab = (f"<p>Período Fiscal consultado</p><p>{a}0000 a {a}1200</p><button>|&lt; AÑO ANTERIOR</button><button>AÑO SIGUIENTE &gt;|</button>"
           f"<div>PRUEBA JUAN (20-11111111-2)</div>")
    if a == 2026:
        tot = "<div>Deuda $ 22.105.640,35</div><div>Saldo Libre Disponibilidad $ 0,00</div><div>Saldo técnico $ 2.918.725,52</div>" \
              "<div>Otros Créditos $ 597.411,24</div><div>Multas no Firmes $ 0,00</div>"
        cuerpo = (tabla("28 - SEGURO DE VIDA COLECTIVO", [("20260900", "DDJJ", "0.00", "black", ""), ("20261000", "DDJJ", "5,520.06", "green", "")], "$ 5.520,06")
                  + tabla("30 - IVA", [("20260200", "DDJJ", "3,288,469.89", "red", "OBLIGACIÓN NOTIFICADA"),
                                       ("20260400", "DDJJ", "0.00", "black", "", "9,999.00"),
                                       ("20260300", "Intereses punitorios", "", "black", "")], "$ 3.288.469,89")
                  + tabla("302 - APORTES OBRAS SOCIALES", [("20260100", "Intereses resarcitorios", "6,362.93", "green", ""),
                                                           ("20260500", "DDJJ", "0.00", "black", "", "45,210.50")], "$ 6.362,93"))
    elif a == 2025:
        tot = "<div>Deuda $ 1.000,00</div><div>Saldo Libre Disponibilidad $ 1.237.687,97</div><div>Saldo técnico $ 0,00</div>" \
              "<div>Otros Créditos $ 0,00</div><div>Multas no Firmes $ 0,00</div>"
        cuerpo = tabla("312 - ASEG.RIESGO DE TRABAJO L 24557", [("20251100", "DDJJ", "1,000.00", "green", ""),
                                                                ("20250700", "DDJJ", "0.00", "black", "", "12,000.00")], "$ 1.000,00")
    else:
        tot = "<div>Deuda $ 0,00</div>"
        cuerpo = ""
    js = "<script>document.querySelector('button').onclick=()=>location.href='consulta?anio=" + str(a - 1) + "'</script>"
    return f"<html><body><h2>Mostrar Consulta</h2>{cab}{tot}{cuerpo}{js}<a href='parametros'>VOLVER</a></body></html>"


def ruteo(route):
    u = route.request.url
    h = "text/html; charset=utf-8"
    if "consulta" in u:
        if "anio=" in u:
            ANIO["v"] = int(u.split("anio=")[1][:4])
        else:                                    # consulta nueva desde los parámetros: año en curso
            ANIO["v"] = 2026
        return route.fulfill(content_type=h, body=consulta())
    if "parametros" in u:
        return route.fulfill(content_type=h, body="<html><body><h2>Ingreso de Parámetros</h2><p>Si no se ingresan valores se tomarán "
                             "en cuenta los períodos del año en curso</p><a href='consulta'>SIGUIENTE</a></body></html>")
    if "inicio" in u:
        return route.fulfill(content_type=h, body="<html><body><p>Sistema de cuentas tributarias</p></body></html>")
    return route.fulfill(content_type=h, body=f"""<html><body><nav><a>CUENTA CORRIENTE</a>
        <a onclick="var f=document.getElementById('c'); if (!/consulta/.test(f.contentWindow.location.href)) f.src='{B}parametros'">ESTADO DE CUMPLIMIENTO</a></nav>
        <iframe id="c" src="{B}inicio" style="width:1200px;height:2000px"></iframe></body></html>""")


ok = True


def chk(c, m):
    global ok
    print(("✔ " if c else "✘ ") + m)
    ok &= bool(c)


chk(rh._num("3,288,469.89") == 3288469.89 and rh._num("22.105.640,35") == 22105640.35 and rh._num("0,00") == 0.0
    and rh._num("5,520.06") == 5520.06, "importes en los dos formatos de la SCT")

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1366, "height": 900})
    ctx.route("https://ctacte.cloud.afip.gob.ar/**", ruteo)
    pg = ctx.new_page()
    pg.goto(B + "externo")
    # pantalla sin campos de período (versión vieja): NO se usa AÑO ANTERIOR (se cuelga); solo el año en curso y el
    # resto queda pendiente con el motivo (20/11/2026)
    _r0 = rh.leer_anios(pg, CUIT, anios=4)
    res = rh.resumir(_r0)
    anios = [a["anio"] for a in res["anios"]]
    chk(anios == ["2026"] and [p["anio"] for p in _r0["pendientes"]] == ["2025", "2024", "2023"],
        f"sin campos de período: solo el año en curso, el resto pendiente ({anios}, {_r0['pendientes']})")
    t = res["anios"][0]["totales"]
    chk(t["deuda"] == 22105640.35 and t["saldo_tecnico"] == 2918725.52 and t["otros_creditos"] == 597411.24, "totales del año")
    d = {(x["impuesto"], x["periodo"]): x for x in res["deudas"]}
    chk(set(d) == {("28", "20261000"), ("30", "20260200"), ("302", "20260100")},
        f"solo filas con deuda, sin subtotales ({sorted(d)})")
    chk(d[("30", "20260200")]["color"] == "rojo" and d[("302", "20260100")]["color"] == "verde"
        and d[("30", "20260200")]["estado_pago"] == "OBLIGACIÓN NOTIFICADA", "color de la deuda y estado de pago")
    chk(res["deuda_f931_otros"] == round(5520.06 + 6362.93, 2), f"F.931 fuera de 301/351 ({res['deuda_f931_otros']})")
    chk(res["alertas"] and "2026" in res["alertas"][0]["texto"], "alerta con los años")
    chk(res["deuda_terceros"] == round(5520.06 + 6362.93, 2) and res["deuda_arca"] == 3288469.89,
        "verde = para terceros (OS, ART, seguro de vida); rojo = propia de ARCA")
    sr = {(x["impuesto"], x["periodo"]): x["sld"] for x in res["saldos_recuperar"]}
    chk(sr == {("302", "20260500"): 45210.5} and res["saldos_recuperar_total"] == 45210.5,
        f"saldos a recuperar (S.L.D.) de cargas sociales, sin IVA ({sr})")
    chk(any("F.399" in a["texto"] and "302 05/2026" in a["texto"] for a in res["alertas"]), "alerta para reimputar con el F.399")
    try:
        ANIO["v"] = 2026
        pg.goto(B + "externo")
        rh.leer_anios(pg, "20222222223", anios=1)
        chk(False, "otro CUIT debe frenar")
    except arca.CuitEquivocado:
        chk(True, "con otro CUIT en pantalla frena")
    b.close()

# ---- 20/11/2026: parámetros con período e impuesto -> consulta NUEVA por año; un año trabado queda pendiente,
#      los demás se guardan, y la corrida siguiente retoma solo lo pendiente.
MODO = {"directo": False, "traba": set(), "consultas": []}
_ruteo_viejo = ruteo


def ruteo2(route):
    u = route.request.url
    h = "text/html; charset=utf-8"
    if not MODO["directo"]:
        return _ruteo_viejo(route)
    if "parametros" in u and MODO.get("combo"):   # combo con buscador (no <select>) y etiquetas sueltas
        return route.fulfill(content_type=h, body="""<html><body><h2>Ingreso de Parámetros</h2><script>window.imp='';</script>
          <div><span>Impuesto</span></div><div><span class="select2-selection" role="combobox"
             onclick="document.getElementById('ops').style.display='block'">Todos</span></div>
          <ul id="ops" style="display:none"><li onclick="window.imp='';this.parentNode.style.display='none'">Todos</li>
          <li onclick="window.imp='28';this.parentNode.style.display='none'">28 - SEGURO DE VIDA COLECTIVO</li>
          <li onclick="window.imp='312';this.parentNode.style.display='none'">312 - ASEG.RIESGO DE TRABAJO L 24557</li></ul>
          <div><span>Período Fiscal Desde</span></div><div><input placeholder="AAAAMMDD"></div>
          <div><span>Período Fiscal Hasta</span></div><div><input></div>
          <a href="#" onclick="var i=document.querySelectorAll('input');location.href='consulta?anio='+i[0].value+'&hasta='+i[1].value
             +'&imp='+window.imp">SIGUIENTE</a></body></html>""")
    if "parametros" in u and MODO.get("aviso"):   # 21/11: ARCA no acepta AAAA1200 y avisa en la misma pantalla
        return route.fulfill(content_type=h, body="""<html><body><h2>Ingreso de Parámetros</h2>
          <div><label>Impuesto</label><select name="impuesto" style="display:none"><option value="">Todos</option>
          <option value="28">28 - SEGURO DE VIDA COLECTIVO</option><option value="312">312 - ASEG.RIESGO DE TRABAJO L 24557</option></select></div>
          <p>Formato: AAAAMMDD o AAAAMM00 o AAAA0000</p>
          <div><label>Período Fiscal Desde</label><input id="d" maxlength="8"></div>
          <div><label>Período Fiscal Hasta</label><input id="h" maxlength="8"></div><p id="m"></p>
          <button onclick="var h=document.getElementById('h').value; if(h.slice(4)=='1200'){document.getElementById('m').textContent='Período Hasta inválido';return;}
             location.href='consulta?anio='+document.getElementById('d').value+'&hasta='+h
             +'&imp='+encodeURIComponent(document.querySelector('[name=impuesto]').value)">SIGUIENTE</button></body></html>""")
    if "parametros" in u:                         # como la captura de Gaby del 20/11/2026
        return route.fulfill(content_type=h, body="""<html><body><h2>Ingreso de Parámetros</h2>
          <div><label>Impuesto</label><select name="impuesto" style="display:none"><option value="">Todos</option>
          <option value="28">28 - SEGURO DE VIDA COLECTIVO</option><option value="30">30 - IVA</option>
          <option value="302">302 - APORTES OBRAS SOCIALES</option><option value="312">312 - ASEG.RIESGO DE TRABAJO L 24557</option></select>
          <span class="select2">Todos</span></div>
          <div><label>Período Fiscal Desde</label><input id="d" placeholder="AAAAMMDD" maxlength="8"></div>
          <div><label>Período Fiscal Hasta</label><input id="h" maxlength="8"></div>
          <a href="#" onclick="location.href='consulta?anio='+document.getElementById('d').value+'&hasta='+document.getElementById('h').value
             +'&imp='+encodeURIComponent(document.querySelector('[name=impuesto]').value)">SIGUIENTE</a></body></html>""")
    if "consulta" in u:
        _q = __import__("urllib.parse").parse.parse_qs(u.split("?", 1)[1]) if "?" in u else {}
        MODO.setdefault("rangos", []).append((_q.get("anio", [""])[0], _q.get("hasta", [""])[0]))
        a = int(_q["anio"][0][:4])
        imp = (_q.get("imp") or [""])[0]
        MODO["consultas"].append((a, imp))
        if imp in MODO.get("vacio", ()):
            return route.fulfill(content_type=h, body="<html><body><p>No se encontraron datos para la consulta realizada</p>"
                                                     "<a href='parametros'>VOLVER</a></body></html>")
        if (a, imp) in MODO["traba"]:
            return route.fulfill(content_type=h, body=f"<html><body><p>Período Fiscal consultado</p><p>{a}0000 a {a}1200</p>"
                                                     "<div>PRUEBA JUAN (20-11111111-2)</div><p>CARGANDO...</p></body></html>")
        ANIO["v"] = a
        cuerpo = consulta()
        if imp:                                        # solo la tabla del impuesto pedido
            cuerpo = re.sub(r"<h4>(?!" + re.escape(imp) + r" ).*?</table>", "", cuerpo, flags=re.S)
        return route.fulfill(content_type=h, body=cuerpo)
    return _ruteo_viejo(route)


import re  # noqa: E402
rh.ESPERA_CARGA = 2
C2 = "20111111112"
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1366, "height": 900})
    ctx.route("https://ctacte.cloud.afip.gob.ar/**", ruteo2)
    pg = ctx.new_page()
    MODO.update(directo=True, traba={(2025, "312")})
    if os.path.exists(rh._ruta_parcial(C2)):
        os.remove(rh._ruta_parcial(C2))                 # lo que dejó la prueba anterior (mismo CUIT)
    pg.goto(B + "externo")
    r1 = rh.leer_anios(pg, C2, anios=3)
    chk([a["anio"] for a in r1["anios"]] == ["2026", "2025", "2024"] and r1["anios"][1]["estado"] == "parcial"
        and r1["pendientes"] == [{"anio": "2025", "motivo": r1["pendientes"][0]["motivo"], "impuestos": ["312"]}],
        f"un impuesto trabado queda pendiente y se sigue con los demás ({r1['pendientes']})")
    chk(set(MODO["rangos"]) >= {("20260000", "20261200"), ("20250000", "20251200")} and not any(i == "" for _, i in MODO["consultas"])
        and {i for _, i in MODO["consultas"]} == {"28", "30", "302", "312"},
        "consulta por año (AAAA0000 a AAAA1200) y por cada impuesto del combo, sin AÑO ANTERIOR")
    import os as _os
    chk(_os.path.exists(rh._ruta_parcial(C2)), "se guarda año por año (_parcial.json)")
    MODO.update(traba=set(), consultas=[])
    pg.goto(B + "externo")
    r2 = rh.leer_anios(pg, C2, anios=3)
    chk(not r2["pendientes"] and set(MODO["consultas"]) == {(2025, "312")},
        f"si se corta y vuelve a entrar el mismo día, retoma solo lo pendiente ({sorted(set(MODO['consultas']))})")
    from datetime import date as _d, timedelta as _td
    MODO.update(consultas=[])
    pg.goto(B + "externo")
    rh.leer_anios(pg, C2, anios=3, hoy=_d.today() + _td(days=1))
    chk(set(MODO["consultas"]) == {(2026, "28"), (2026, "30"), (2026, "302"), (2026, "312")},
        f"otro día: el año en curso se lee de nuevo y lo viejo ya leído no ({sorted(set(MODO['consultas']))})")
    res2 = rh.resumir(r2)
    chk(any(x["impuesto"] == "312" for x in res2["saldos_recuperar"]), "con lo retomado aparecen los saldos del 312")
    chk(r2["anios"][0]["totales"]["deuda"] is not None, "totales del año sumando los impuestos")
    # otro contribuyente en pantalla en medio de la consulta por impuesto -> se detiene
    try:
        os.remove(rh._ruta_parcial("20222222223")) if os.path.exists(rh._ruta_parcial("20222222223")) else None
        pg.goto(B + "externo")
        rh.leer_anios(pg, "20222222223", anios=1)
        chk(False, "otro CUIT debe frenar (consulta por impuesto)")
    except arca.CuitEquivocado:
        chk(True, "consulta por impuesto: si la pantalla muestra otro contribuyente, se detiene")
    # combo con buscador y etiquetas no ligadas a los campos (como el ARCA real): igual consulta por año e impuesto
    MODO.update(combo=True, traba=set(), consultas=[], rangos=[])
    if os.path.exists(rh._ruta_parcial(C2)):
        os.remove(rh._ruta_parcial(C2))
    pg.goto(B + "externo")
    r3 = rh.leer_anios(pg, C2, anios=1)
    chk(set(MODO["consultas"]) == {(2026, "28"), (2026, "312")} and ("20260000", "20261200") in MODO["rangos"] and not r3["pendientes"],
        f"combo con buscador: lee los impuestos y consulta cada uno, sin AÑO ANTERIOR ({sorted(set(MODO['consultas']))})")
    # 21/11/2026 (Goncalves): tras SIGUIENTE no aparece la consulta -> se lee el aviso de ARCA y se prueba 0101-1231;
    # un impuesto sin datos no es error
    rh.ESPERA_SIGUIENTE = 4
    MODO.update(combo=False, aviso=True, vacio={"28"}, traba=set(), consultas=[], rangos=[])
    if os.path.exists(rh._ruta_parcial(C2)):
        os.remove(rh._ruta_parcial(C2))
    pg.goto(B + "externo")
    r4 = rh.leer_anios(pg, C2, anios=1)
    chk(("20260101", "20261231") in MODO["rangos"] and not r4["pendientes"] and r4["anios"] and r4["anios"][0]["estado"] == "OK",
        f"si ARCA no toma AAAA1200 prueba 01/01-31/12 y un impuesto sin datos no queda pendiente ({MODO['rangos']}, {r4['pendientes']})")
    # nada responde: queda pendiente con el motivo y NO corta la corrida
    MODO.update(vacio=set(), traba={(2026, "312")}, consultas=[], rangos=[])
    os.remove(rh._ruta_parcial(C2))
    _orig = rh._rangos
    rh._rangos = lambda anio, hoy: [(f"{anio}0000", f"{anio}1200")]
    pg.goto(B + "externo")
    r5 = rh.leer_anios(pg, C2, anios=1)
    rh._rangos = _orig
    chk(r5["pendientes"] and "inválido" in r5["pendientes"][0]["motivo"],
        f"sin respuesta: pendiente con el aviso de ARCA, la corrida sigue ({r5['pendientes']})")
    MODO.update(aviso=False)
    b.close()

print("OK" if ok else "FALLÓ")
sys.exit(0 if ok else 1)
