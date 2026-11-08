# -*- coding: utf-8 -*-
"""Demo 4 - Lo que revela la nueva base: consultas imposibles con las planillas separadas."""
from comun import *

con = conectar()
titulo("DEMO 4 · LO QUE REVELA LA NUEVA BASE", "Consultas que cruzan las cuatro fuentes con un solo SQL")

seccion("Inversion por categoria")
filas = sql(con, """SELECT categoria, COUNT(*) AS entregas, COUNT(DISTINCT cod_establecimiento) AS estab,
                           SUM(monto_adjudicado) AS monto FROM v_entregas_detalle GROUP BY categoria ORDER BY monto DESC""")
tabla(["categoria", "entregas", "establecimientos", "monto adjudicado"],
      [(a, n(b), n(c), n(d)) for a, b, c, d in filas], "lrrr")

seccion("Top 5 empresas por monto adjudicado (en las 4 categorias)")
filas = sql(con, """SELECT empresa, categorias, entregas, monto_total FROM v_resumen_empresa
                    ORDER BY monto_total DESC LIMIT 5""")
tabla(["empresa", "categorias", "entregas", "monto total"], [(a, b, n(c), n(d)) for a, b, c, d in filas], "lrrr")

seccion("Top 5 departamentos por monto adjudicado")
filas = sql(con, """SELECT departamento, SUM(establecimientos) , SUM(entregas), SUM(monto_total) AS m
                    FROM v_resumen_departamento GROUP BY departamento ORDER BY m DESC LIMIT 5""")
tabla(["departamento", "estab.-categoria", "entregas", "monto total"],
      [(a, n(b), n(c), n(d)) for a, b, c, d in filas], "lrrr")

seccion("Cobertura: cuantas categorias recibio cada establecimiento")
filas = sql(con, """SELECT categorias_recibidas, COUNT(*) FROM v_cobertura_establecimiento
                    GROUP BY 1 ORDER BY 1""")
total = sum(f[1] for f in filas)
tabla(["categorias recibidas", "establecimientos", "% del total"],
      [(a, n(b), n(100 * b / total, 1) + " %") for a, b in filas], "rrr")

seccion("Establecimientos sin ninguna entrega registrada (muestra)")
filas = sql(con, """SELECT codigo, nombre FROM v_cobertura_establecimiento
                    WHERE categorias_recibidas = 0 ORDER BY codigo LIMIT 5""")
tabla(["codigo", "nombre"], filas)

seccion("Trazabilidad: de una fila de la base a la celda de la planilla original")
filas = sql(con, """SELECT e.id_entrega, e.hoja_origen, e.fila_origen, i.descripcion, e.monto_adjudicado
                    FROM entrega e JOIN item i USING(id_item) ORDER BY e.id_entrega DESC LIMIT 3""")
tabla(["id_entrega", "hoja origen", "fila en Excel", "item", "monto"],
      [(a, b, c, d[:32], n(e)) for a, b, c, d, e in filas], "rlrlr")
print("\n  Cada dato conserva hoja y fila de origen: se puede auditar contra el Excel.")
