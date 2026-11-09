"""
Proyecto Fenix - Seguridad y proteccion de datos (Fase 3)
Agrega a la base normalizada: bitacora de cambios por triggers, campos de
trazabilidad inmutables, sellado de integridad (SHA-256) y verificacion.
Uso:
  python scripts/seguridad_fenix.py aplicar    [ruta_db]   # crea bitacora, triggers y sello
  python scripts/seguridad_fenix.py verificar  [ruta_db]   # recalcula el hash y lo compara
  python scripts/seguridad_fenix.py sellar     [ruta_db]   # re-sella tras un cambio autorizado
Solo biblioteca estandar. Por defecto usa salida/fenix_normalizada.db.
"""
import hashlib
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLAS = ["departamento", "distrito", "establecimiento", "institucion", "empresa",
          "llamado", "contrato", "item", "entrega", "concepto_pago", "pago"]

DDL = """
CREATE TABLE IF NOT EXISTS bitacora_cambios(
  id_cambio INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f','now')),
  tabla TEXT NOT NULL,
  operacion TEXT NOT NULL CHECK(operacion IN ('UPDATE','DELETE')),
  clave INTEGER NOT NULL,
  detalle TEXT);
CREATE TABLE IF NOT EXISTS control_integridad(
  id INTEGER PRIMARY KEY CHECK(id = 1),
  sha256 TEXT NOT NULL,
  filas INTEGER NOT NULL,
  sellado_en TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f','now')));

-- Trazabilidad a la fila de Excel: no se puede modificar ni siquiera por error
CREATE TRIGGER IF NOT EXISTS trg_entrega_origen_inmutable
BEFORE UPDATE OF hoja_origen, fila_origen ON entrega
BEGIN SELECT RAISE(ABORT, 'hoja_origen y fila_origen son inmutables'); END;

-- La bitacora es de solo anadir: no admite UPDATE ni DELETE
CREATE TRIGGER IF NOT EXISTS trg_bitacora_sin_update
BEFORE UPDATE ON bitacora_cambios
BEGIN SELECT RAISE(ABORT, 'la bitacora no se modifica'); END;
CREATE TRIGGER IF NOT EXISTS trg_bitacora_sin_delete
BEFORE DELETE ON bitacora_cambios
BEGIN SELECT RAISE(ABORT, 'la bitacora no se borra'); END;

-- Registro de montos y borrados en las tablas sensibles
CREATE TRIGGER IF NOT EXISTS trg_entrega_upd AFTER UPDATE ON entrega
BEGIN INSERT INTO bitacora_cambios(tabla, operacion, clave, detalle)
  VALUES('entrega','UPDATE',OLD.id_entrega,
   'monto '||IFNULL(OLD.monto_adjudicado,'NULL')||' -> '||IFNULL(NEW.monto_adjudicado,'NULL')||
   '; multa '||OLD.multa||' -> '||NEW.multa||
   '; contrato '||OLD.id_contrato||' -> '||NEW.id_contrato); END;
CREATE TRIGGER IF NOT EXISTS trg_entrega_del AFTER DELETE ON entrega
BEGIN INSERT INTO bitacora_cambios(tabla, operacion, clave, detalle)
  VALUES('entrega','DELETE',OLD.id_entrega,
   'monto '||IFNULL(OLD.monto_adjudicado,'NULL')||'; origen '||OLD.hoja_origen||'#'||OLD.fila_origen); END;
CREATE TRIGGER IF NOT EXISTS trg_pago_upd AFTER UPDATE ON pago
BEGIN INSERT INTO bitacora_cambios(tabla, operacion, clave, detalle)
  VALUES('pago','UPDATE',OLD.id_pago,'monto '||OLD.monto||' -> '||NEW.monto); END;
CREATE TRIGGER IF NOT EXISTS trg_pago_del AFTER DELETE ON pago
BEGIN INSERT INTO bitacora_cambios(tabla, operacion, clave, detalle)
  VALUES('pago','DELETE',OLD.id_pago,'monto '||OLD.monto||'; entrega '||OLD.id_entrega); END;
CREATE TRIGGER IF NOT EXISTS trg_contrato_upd AFTER UPDATE ON contrato
BEGIN INSERT INTO bitacora_cambios(tabla, operacion, clave, detalle)
  VALUES('contrato','UPDATE',OLD.id_contrato,
   'empresa '||OLD.id_empresa||' -> '||NEW.id_empresa||'; llamado '||OLD.id_llamado||' -> '||NEW.id_llamado); END;
CREATE TRIGGER IF NOT EXISTS trg_contrato_del AFTER DELETE ON contrato
BEGIN INSERT INTO bitacora_cambios(tabla, operacion, clave, detalle)
  VALUES('contrato','DELETE',OLD.id_contrato,'empresa '||OLD.id_empresa); END;
CREATE TRIGGER IF NOT EXISTS trg_empresa_upd AFTER UPDATE ON empresa
BEGIN INSERT INTO bitacora_cambios(tabla, operacion, clave, detalle)
  VALUES('empresa','UPDATE',OLD.id_empresa,OLD.nombre||' -> '||NEW.nombre); END;
CREATE TRIGGER IF NOT EXISTS trg_empresa_del AFTER DELETE ON empresa
BEGIN INSERT INTO bitacora_cambios(tabla, operacion, clave, detalle)
  VALUES('empresa','DELETE',OLD.id_empresa,OLD.nombre); END;
"""


def calcular_hash(con):
    """SHA-256 del contenido de las tablas de negocio, en orden determinista."""
    h = hashlib.sha256()
    filas = 0
    for t in TABLAS:
        h.update(t.encode())
        for fila in con.execute(f"SELECT * FROM {t} ORDER BY 1"):
            h.update(repr(fila).encode())
            filas += 1
    return h.hexdigest(), filas


def sellar(con):
    sha, filas = calcular_hash(con)
    con.execute("INSERT INTO control_integridad(id, sha256, filas) VALUES(1,?,?) "
                "ON CONFLICT(id) DO UPDATE SET sha256=excluded.sha256, filas=excluded.filas, "
                "sellado_en=strftime('%Y-%m-%d %H:%M:%f','now')", (sha, filas))
    con.commit()
    return sha, filas


def verificar(con):
    fila = con.execute("SELECT sha256, filas, sellado_en FROM control_integridad WHERE id=1").fetchone()
    if not fila:
        return None, "No hay sello: ejecute 'aplicar' primero."
    sha, filas = calcular_hash(con)
    if sha == fila[0]:
        return True, f"INTEGRO: {filas} filas coinciden con el sello del {fila[2]}."
    cambios = con.execute("SELECT COUNT(*) FROM bitacora_cambios").fetchone()[0]
    return False, (f"ALTERADO: el contenido no coincide con el sello del {fila[2]} "
                   f"({cambios} cambios en la bitacora).")


def main():
    accion = sys.argv[1] if len(sys.argv) > 1 else "verificar"
    ruta = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "salida", "fenix_normalizada.db")
    if not os.path.exists(ruta):
        sys.exit(f"No existe la base: {ruta}")
    if accion == "verificar":   # solo lectura: no puede alterar la base
        con = sqlite3.connect(f"file:{os.path.abspath(ruta)}?mode=ro", uri=True)
        ok, msg = verificar(con)
        print(msg)
        sys.exit(0 if ok else 1)
    con = sqlite3.connect(ruta)
    con.execute("PRAGMA foreign_keys = ON")
    if accion == "aplicar":
        con.executescript(DDL)
        sha, filas = sellar(con)
        print(f"Triggers y bitacora creados. Sello SHA-256 sobre {filas} filas:\n{sha}")
    elif accion == "sellar":
        sha, filas = sellar(con)
        print(f"Re-sellado ({filas} filas): {sha}")
    else:
        sys.exit("Uso: seguridad_fenix.py [aplicar|verificar|sellar] [ruta_db]")


if __name__ == "__main__":
    main()
