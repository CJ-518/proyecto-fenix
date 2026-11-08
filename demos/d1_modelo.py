# -*- coding: utf-8 -*-
"""Demo 1 - El modelo rediseñado: 11 tablas en 3FN, claves y reglas dentro del motor."""
from comun import *

con = conectar()
titulo("DEMO 1 · MODELO REDISEÑADO", "De cuatro planillas anchas a tablas en tercera forma normal")

seccion("Tablas del modelo y cantidad de filas")
tablas = [r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid")]
filas = []
for t in tablas:
    cols = len(con.execute(f"PRAGMA table_info({t})").fetchall())
    fks = len(con.execute(f"PRAGMA foreign_key_list({t})").fetchall())
    filas.append((t, cols, fks, n(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])))
tabla(["tabla", "columnas", "claves foraneas", "filas"], filas, "lrrr")
print("\n  (11 tablas del modelo + rechazo_migracion y log_migracion, que guardan la auditoria)")

seccion("Reglas que ahora aplica el motor (no la persona que digita)")
ddl = " ".join(r[0] or "" for r in con.execute("SELECT sql FROM sqlite_master WHERE type='table'"))
print(f"  Claves foraneas declaradas : {sum(len(con.execute(f'PRAGMA foreign_key_list({t})').fetchall()) for t in tablas)}")
print(f"  Restricciones CHECK        : {ddl.count('CHECK(')}")
n_idx = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name LIKE 'ix_%'").fetchone()[0]
n_vis = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='view'").fetchone()[0]
print(f"  Indices secundarios (ix_*) : {n_idx}")
print(f"  Vistas de consulta         : {n_vis}")

seccion("Una entrega, reconstruida a partir de las tablas relacionadas")
filas = sql(con, """
  SELECT e.id_entrega, es.codigo, i.categoria, i.descripcion, emp.nombre, c.nro_lote, e.monto_adjudicado
  FROM entrega e
  JOIN establecimiento es USING(id_establecimiento)
  JOIN item i USING(id_item)
  JOIN contrato c USING(id_contrato)
  JOIN empresa emp USING(id_empresa)
  WHERE es.codigo = '0405002' ORDER BY e.id_entrega LIMIT 5""")
tabla(["id", "establecimiento", "categoria", "item", "empresa", "lote", "monto"],
      [(a, b, c, d[:30], e[:24], f, n(g)) for a, b, c, d, e, f, g in filas], "rllllrr")

seccion("Pagos: antes eran columnas repetidas, ahora una tabla hija")
filas = sql(con, """
  SELECT cp.nombre, COUNT(*) AS pagos, SUM(p.monto) AS total
  FROM pago p JOIN concepto_pago cp USING(id_concepto)
  GROUP BY cp.nombre ORDER BY total DESC""")
tabla(["concepto", "pagos", "monto total"], [(a, n(b), n(c)) for a, b, c in filas], "lrr")

seccion("El motor rechaza datos invalidos (se prueba en memoria, la base no se toca)")
mem = sqlite3.connect(":memory:")
con.backup(mem)
mem.execute("PRAGMA foreign_keys = ON")
pruebas = [
    ("Codigo de establecimiento de 3 caracteres",
     "INSERT INTO establecimiento(codigo,nombre) VALUES('123','Prueba')"),
    ("Latitud fuera de Paraguay (+10)",
     "INSERT INTO establecimiento(codigo,nombre,latitud) VALUES('9999999','Prueba',10)"),
    ("Entrega con establecimiento inexistente",
     "INSERT INTO entrega(id_establecimiento,id_contrato,id_item,hoja_origen,fila_origen) VALUES(99999,1,1,'X',1)"),
    ("Monto adjudicado negativo",
     "INSERT INTO entrega(id_establecimiento,id_contrato,id_item,monto_adjudicado,hoja_origen,fila_origen) VALUES(1,1,1,-5,'X',2)"),
]
for desc, stmt in pruebas:
    try:
        mem.execute(stmt)
        mem.commit()
        res = "ACEPTADO (inesperado)"
    except sqlite3.Error as e:
        res = f"RECHAZADO -> {e}"
    print(f"  {desc}\n      {res}")
mem.close()
