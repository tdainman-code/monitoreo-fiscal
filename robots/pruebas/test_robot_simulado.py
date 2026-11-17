"""Prueba del robot Mis Comprobantes contra una simulación local de ARCA (sin internet).

Valida el recorrido y el manejo de errores; los selectores reales se confirman en la
primera corrida contra ARCA con --ver.
"""
import os
import re
import sys
import tempfile
from contextlib import contextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from robots import arca, robot_mis_comprobantes as rmc  # noqa: E402

CSV = {"emitidos": "/home/claude/datos/emitidos_2026-10.csv",
       "recibidos": "/home/claude/datos/recibidos_2026-10.csv"}
TOTAL = {"emitidos": "4.241", "recibidos": "116"}
MODO = {"login": "ok", "fecha": "api", "csv": "utf-8-sig", "zip": False}   # ok | mala | captcha | oculto | lento

LOGIN = """<html><body><form>
<div id=paso1><label for="F1:username">CUIT/CUIL</label><input id="F1:username" name="F1:username">
<input type=button id="F1:btnSiguiente" name="F1:btnSiguiente" value="Siguiente"
 onclick="document.getElementById('paso1').style.display='none';document.getElementById('paso2').style.display='block'"></div>
<div id=paso2 style="display:none"><input type=password id="F1:password" onkeydown="window._teclas=(window._teclas||0)+1">
<input type=button id="F1:btnIngresar" name="F1:btnIngresar" value="Ingresar" onclick="
 var v=document.getElementById('F1:password').value;
 if(v==='ClaveCorrecta' && (window._teclas||0)>=v.length){setTimeout(function(){location.href='https://portalcf.cloud.afip.gob.ar/portal/app/'}, window._demora||0)}
 else{document.getElementById('msg').textContent='Clave o usuario incorrecto'}"></div>
<span id=msg></span>%s</form></body></html>"""

PORTAL = "<html><body><h1>Portal</h1><a href='#' onclick='return false'>Salir</a></body></html>"
SERVICIOS = """<html><body><button title="mcmp" aria-label="mcmp"
 onclick="window.open('https://fes.afip.gob.ar/mcmp/jsp/index.do')">mcmp</button></body></html>"""
MC_INDEX = "<html><body>Mis Comprobantes – GONCALVES (20-33116278-8)</body></html>"
MC_CONSULTA = """<html><body><label for=fecha>Fecha del Comprobante</label><input id=fecha value="14/11/2026">
<script>
// Simula el calendario daterangepicker de ARCA: el valor "real" está en el objeto del calendario,
// no en el texto del campo. Pegar texto (fill) NO lo cambia.
var dp = {start:'14/11/2026', end:'14/11/2026', setStartDate:function(d){this.start=d}, setEndDate:function(d){this.end=d}};
var MODO_FECHA = '%s';
if (MODO_FECHA === 'api') {
  window.jQuery = function(el){ return {data:function(k){return dp}, val:function(v){el.value=v}, trigger:function(){}} };
}
var tecleado = '';
document.getElementById('fecha').addEventListener('keydown', function(e){
  if (MODO_FECHA !== 'teclado') return;
  if (e.key === 'Backspace') { tecleado = ''; return; }
  if (e.key.length === 1 && !e.ctrlKey) tecleado += e.key;
  if (e.key === 'Enter') { var p = tecleado.split(' - '); if (p.length===2){dp.start=p[0]; dp.end=p[1];} }
});
function buscar(){
  var r=document.getElementById('res'); r.style.display='block';
  document.getElementById('filtro').textContent = 'Fecha del Comprobante: ' + dp.start + (dp.end!==dp.start ? ' a ' + dp.end : '');
}
</script>
<button onclick="buscar()">Buscar</button>
<div id=res style="display:none"><div id=filtro></div>Mostrando registros 1 al 5 de un total de %s
<button title="Exportar como CSV" onclick="location.href='/mcmp/export/%s.csv'">CSV</button></div></body></html>"""


def servir(route):
    url = route.request.url
    html = lambda b: route.fulfill(status=200, content_type="text/html", body=b)
    if "auth.afip.gob.ar" in url:
        extra = {"captcha": "<img src='captcha.jpg' width=200 height=60 style='background:#ccc'>",
                 "oculto": "<div id='captchaContainer' style='display:none'></div><input type=hidden id='g-recaptcha-response'>"}
        demora = "<script>window._demora=8000</script>" if MODO["login"] == "lento" else ""
        return html(LOGIN % (extra.get(MODO["login"], "") + demora))
    if url.endswith("/mis-servicios"):
        return html(SERVICIOS)
    if "portalcf" in url:
        return html(PORTAL)
    m = re.search(r"/mcmp/export/(\w+)\.csv", url)
    if m:
        cuerpo = open(CSV[m[1]], encoding="utf-8-sig").read().encode(MODO["csv"])
        if MODO["zip"]:
            import io, zipfile
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr(f"comprobantes_consulta_csv_{m[1]}_1_20331162788_20261115-1039 (montos expresados en pesos).csv", cuerpo)
            cuerpo = buf.getvalue()
        return route.fulfill(status=200, headers={"Content-Disposition": f'attachment; filename="{m[1]}.csv"'},
                             content_type="text/csv", body=cuerpo)
    if "comprobantesEmitidos" in url:
        return html(MC_CONSULTA % (MODO["fecha"], TOTAL["emitidos"], "emitidos"))
    if "comprobantesRecibidos" in url:
        return html(MC_CONSULTA % (MODO["fecha"], TOTAL["recibidos"], "recibidos"))
    if "mcmp" in url:
        return html(MC_INDEX)
    return route.abort()


_original = arca.navegador


@contextmanager
def navegador_simulado(visible=False, carpeta_descargas=None):
    with _original(visible=False) as ctx:
        ctx.route("**/*", servir)
        yield ctx


arca.navegador = navegador_simulado
arca.pausa = lambda *a, **k: None   # sin esperas en la prueba


def caso(nombre, modo, clave, esperado, fecha="api", csv="utf-8-sig", zip_=False):
    MODO["login"], MODO["fecha"], MODO["csv"], MODO["zip"] = modo, fecha, csv, zip_
    try:
        r = rmc.correr("20331162788", "2026-10", "20331162788", clave)
        obtenido = "OK"
        detalle = {t: (i.get("registros"), len(i.get("alertas", []))) for t, i in r["archivos"].items()}
    except arca.ClaveInvalida:
        obtenido, detalle = "ClaveInvalida", ""
    except arca.RequiereIntervencion as e:
        obtenido, detalle = "RequiereIntervencion", str(e)
    except arca.ErrorRobot as e:
        obtenido, detalle = "ErrorRobot", str(e)[:90]
    print(f"{'✔' if obtenido == esperado else '✘'} {nombre}: {obtenido} {detalle}")
    return obtenido == esperado


if __name__ == "__main__":
    rmc.DATOS = tempfile.mkdtemp()
    ok = all([
        caso("Descarga completa", "ok", "ClaveCorrecta", "OK"),
        caso("Clave incorrecta (no reintenta)", "ok", "Mala", "ClaveInvalida"),
        caso("Login con captcha visible (se detiene)", "captcha", "ClaveCorrecta", "RequiereIntervencion"),
        caso("Captcha OCULTO como en ARCA real (sigue)", "oculto", "ClaveCorrecta", "OK"),
        caso("ARCA tarda 8 s en entrar al portal (espera)", "lento", "ClaveCorrecta", "OK"),
        caso("Fechas por teclado (sin API del calendario)", "ok", "ClaveCorrecta", "OK", fecha="teclado"),
        caso("ARCA ignora la fecha -> NO descarga", "ok", "ClaveCorrecta", "ErrorRobot", fecha="nada"),
        caso("CSV en codificación Windows (cp1252)", "ok", "ClaveCorrecta", "OK", csv="cp1252"),
        caso("CSV dentro de un ZIP, como en ARCA real", "ok", "ClaveCorrecta", "OK", csv="cp1252", zip_=True),
    ])
    for root, _, files in os.walk(rmc.DATOS):
        for f in files:
            print("  archivo:", os.path.relpath(os.path.join(root, f), rmc.DATOS))
    sys.exit(0 if ok else 1)
