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
    return f"<html><body><h2>Mostrar Consulta</h2>{cab}{tot}{cuerpo}{js}</body></html>"


def ruteo(route):
    u = route.request.url
    h = "text/html; charset=utf-8"
    if "consulta" in u:
        if "anio=" in u:
            ANIO["v"] = int(u.split("anio=")[1][:4])
        return route.fulfill(content_type=h, body=consulta())
    if "parametros" in u:
        return route.fulfill(content_type=h, body="<html><body><h2>Ingreso de Parámetros</h2><p>Si no se ingresan valores se tomarán "
                             "en cuenta los períodos del año en curso</p><a href='consulta'>SIGUIENTE</a></body></html>")
    if "inicio" in u:
        return route.fulfill(content_type=h, body="<html><body><p>Sistema de cuentas tributarias</p></body></html>")
    return route.fulfill(content_type=h, body=f"""<html><body><nav><a>CUENTA CORRIENTE</a>
        <a onclick="document.getElementById('c').src='{B}parametros'">ESTADO DE CUMPLIMIENTO</a></nav>
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
    res = rh.resumir(rh.leer_anios(pg, CUIT, anios=4))
    anios = [a["anio"] for a in res["anios"]]
    chk(anios == ["2026", "2025", "2024", "2023"], f"recorre año por año con AÑO ANTERIOR ({anios})")
    t = res["anios"][0]["totales"]
    chk(t["deuda"] == 22105640.35 and t["saldo_tecnico"] == 2918725.52 and t["otros_creditos"] == 597411.24, "totales del año")
    d = {(x["impuesto"], x["periodo"]): x for x in res["deudas"]}
    chk(set(d) == {("28", "20261000"), ("30", "20260200"), ("302", "20260100"), ("312", "20251100")},
        f"solo filas con deuda, sin subtotales ({sorted(d)})")
    chk(d[("30", "20260200")]["color"] == "rojo" and d[("302", "20260100")]["color"] == "verde"
        and d[("30", "20260200")]["estado_pago"] == "OBLIGACIÓN NOTIFICADA", "color de la deuda y estado de pago")
    chk(res["deuda_f931_otros"] == round(5520.06 + 6362.93 + 1000.0, 2), f"F.931 fuera de 301/351 ({res['deuda_f931_otros']})")
    chk(res["alertas"] and "2025, 2026" in res["alertas"][0]["texto"], "alerta con los años")
    chk(res["deuda_terceros"] == round(5520.06 + 6362.93 + 1000.0, 2) and res["deuda_arca"] == 3288469.89,
        "verde = para terceros (OS, ART, seguro de vida); rojo = propia de ARCA")
    sr = {(x["impuesto"], x["periodo"]): x["sld"] for x in res["saldos_recuperar"]}
    chk(sr == {("302", "20260500"): 45210.5, ("312", "20250700"): 12000.0} and res["saldos_recuperar_total"] == 57210.5,
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

print("OK" if ok else "FALLÓ")
sys.exit(0 if ok else 1)
