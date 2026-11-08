"""Demo 2 - Calidad de datos antes y despues de la migracion."""
from comun import cargar_json, conectar, n, seccion, sql, tabla, titulo

con = conectar()
aud = cargar_json("auditoria.json")
bench = cargar_json("benchmark.json")
titulo("DEMO 2 · CALIDAD DE DATOS: ANTES Y DESPUÉS", "Lo que traian las planillas vs. lo que hay en la base")

seccion("Resumen")
tabla(["problema en las planillas", "antes", "despues"], [
    ("Formatos distintos de latitud/longitud", f"{bench['formatos_latitud_origen']} formatos de texto",
     f"{n(bench['latitud_no_decimal_destino'])} valores no decimales"),
    ("Nombres de empresa (con variantes)", f"{aud['empresas_variantes']} nombres", f"{aud['empresas_unicas']} empresas"),
    ("Codigos de licitacion escritos distinto", f"{aud['variantes_codigo_licitacion']} variantes", "unificados por ID de llamado"),
    ("Filas duplicadas exactas en mobiliario", f"{aud['rechazos_por_motivo']['MOBILIARIO|DUPLICADO_EXACTO']} filas", "0 en la base (en cuarentena)"),
    ("Monto inflado por esos duplicados", n(aud['mob_duplicados_monto']), "0"),
], "lrr")

seccion("Codigos de establecimiento: todos deben tener 7 caracteres (ceros iniciales)")
ok, tot, sin = sql(con, "SELECT SUM(length(codigo)=7), COUNT(codigo), SUM(codigo IS NULL) FROM establecimiento")[0]
print(f"  {n(ok)} de {n(tot)} codigos tienen exactamente 7 caracteres ({sin} establecimientos vienen sin codigo en la fuente)")
print("  Ejemplos:", ", ".join(r[0] for r in con.execute("SELECT codigo FROM establecimiento WHERE codigo LIKE '0%' LIMIT 5")))

seccion("Coordenadas: de texto grados/minutos/segundos a decimal")
filas = sql(con, """SELECT codigo, latitud, longitud, typeof(latitud) FROM establecimiento
                    WHERE latitud IS NOT NULL AND codigo IS NOT NULL ORDER BY codigo LIMIT 5""")
tabla(["codigo", "latitud", "longitud", "tipo"], filas, "lrrl")
nul = aud["coord_nulas_estab"]
print(f"\n  Sin coordenada utilizable (se conserva como NULL, no se inventa): {nul} establecimientos")

seccion("Variantes de nombre de empresa que se unificaron")
filas = sql(con, "SELECT nombre FROM empresa ORDER BY nombre")
print("  Empresas unicas en la base:", len(filas))
for (nm,) in filas[:8]:
    print("   -", nm)
print("   ...")

seccion("Conflictos entre planillas para un mismo establecimiento (se resolvieron por moda)")
tabla(["atributo", "establecimientos con valores en conflicto"],
      sorted(aud["conflictos_atributos_establecimiento"].items(), key=lambda x: -x[1]), "lr")

seccion("Fechas de acta que no eran fecha completa (se conserva el texto original)")
print(f"  {aud['fechas_acta_parciales']} entregas con fecha_acta_texto (ej. 'XX/11/2021')")
for r in con.execute("SELECT hoja_origen, fila_origen, fecha_acta_texto FROM entrega WHERE fecha_acta_texto IS NOT NULL LIMIT 3"):
    print("   -", r)
