# -*- coding: utf-8 -*-
"""Demo 3 - Conciliacion origen-destino y verificacion de integridad (en vivo)."""
from comun import *

con = conectar()
aud = cargar_json("auditoria.json")
titulo("DEMO 3 · CONCILIACIÓN ORIGEN–DESTINO", "Nada se pierde: cada fila migrada o rechazada con motivo")

seccion("Filas: origen = migradas + rechazadas")
migr = dict(sql(con, "SELECT hoja_origen, COUNT(*) FROM entrega GROUP BY 1"))
rech = dict(sql(con, "SELECT hoja, COUNT(*) FROM rechazo_migracion GROUP BY 1"))
filas, t = [], [0, 0, 0]
for hoja in ["PARQUES", "MATERIALES", "MOBILIARIO", "TIC"]:
    o, m, r = aud["filas_origen"][hoja], migr.get(hoja, 0), rech.get(hoja, 0)
    filas.append((hoja, n(o), n(m), n(r), "OK" if o == m + r else "REVISAR"))
    t = [t[0] + o, t[1] + m, t[2] + r]
filas.append(("TOTAL", n(t[0]), n(t[1]), n(t[2]), "OK" if t[0] == t[1] + t[2] else "REVISAR"))
tabla(["hoja", "origen", "migradas", "rechazadas", "cuadra"], filas, "lrrrl")

seccion("Montos adjudicados: planilla original vs. base (consulta en vivo)")
dest = dict(sql(con, "SELECT hoja_origen, SUM(monto_adjudicado) FROM entrega GROUP BY 1"))
filas, to, td = [], 0, 0
for hoja in ["PARQUES", "MATERIALES", "MOBILIARIO", "TIC"]:
    o, d = aud["monto_origen"][hoja], dest[hoja]
    # el monto de origen de MOBILIARIO ya excluye los duplicados (se midio tras estandarizar)
    filas.append((hoja, n(o), n(d), n(d - o), "OK" if abs(d - o) < 1 else "REVISAR"))
    to, td = to + o, td + d
filas.append(("TOTAL", n(to), n(td), n(td - to), "OK" if abs(td - to) < 1 else "REVISAR"))
tabla(["hoja", "monto origen", "monto base", "diferencia", "cuadra"], filas, "lrrrl")

seccion("Rechazos en cuarentena, por motivo")
filas = sql(con, "SELECT hoja, motivo, COUNT(*) FROM rechazo_migracion GROUP BY 1,2 ORDER BY 3 DESC")
tabla(["hoja", "motivo", "filas"], filas, "llr")
print("\n  Ejemplos (hoja y fila de la planilla original):")
for r in con.execute("SELECT hoja, fila, motivo, detalle FROM rechazo_migracion GROUP BY motivo"):
    print("   -", r)

seccion("Integridad (verificada ahora, no copiada del informe)")
fk = sql(con, "PRAGMA foreign_key_check")
print(f"  Violaciones de clave foranea : {len(fk)}")
print(f"  PRAGMA integrity_check       : {con.execute('PRAGMA integrity_check').fetchone()[0]}")

seccion("Conciliacion de pagos: monto adjudicado - pagado - multa")
filas = sql(con, """SELECT hoja_origen, COUNT(*) AS entregas,
                           SUM(ABS(diferencia) > 1) AS con_diferencia, MAX(ABS(diferencia)) AS max_dif
                    FROM v_conciliacion_pagos GROUP BY 1""")
tabla(["hoja", "entregas", "con diferencia > 1", "maxima diferencia"],
      [(h, n(e), n(c), n(m)) for h, e, c, m in filas], "lrrr")
print("\n  Entregas donde pagado + multa no cuadra con lo adjudicado (las 5 de mayor diferencia):")
filas = sql(con, """SELECT hoja_origen, fila_origen, monto_adjudicado, pagado, multa, diferencia
                    FROM v_conciliacion_pagos WHERE ABS(diferencia) > 1
                    ORDER BY ABS(diferencia) DESC LIMIT 5""")
tabla(["hoja", "fila", "adjudicado", "pagado", "multa", "diferencia"],
      [(a, b, n(c), n(d), n(e), n(f)) for a, b, c, d, e, f in filas], "lrrrrr")
