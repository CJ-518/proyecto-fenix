"""
Proyecto Fenix - Elimina de Oracle todo lo cargado por cargar_oracle.py.

Borra las 5 vistas y las 13 tablas del esquema (los indices y restricciones se van con las
tablas) y verifica que no quede ningun objeto. El usuario FENIX se conserva, de modo que la
demostracion se repite con:  limpiar_oracle.py  ->  cargar_oracle.py

Uso:
  python scripts/limpiar_oracle.py            pide confirmacion
  python scripts/limpiar_oracle.py --si       sin confirmacion (para la demo)
  python scripts/limpiar_oracle.py --usuario FENIX --dsn localhost:1521/FREEPDB1

La clave se lee de la variable FENIX_ORA_PASSWORD o, si no existe, se pide por teclado.
"""
import argparse
import getpass
import os
import sys

import cargar_oracle as co

ORA_NO_EXISTE = 942  # ORA-00942: la tabla o vista no existe


def borrar(cur, tipo, nombre):
    """Borra un objeto. Devuelve True si existia y se borro, False si ya no estaba."""
    sentencia = f"DROP VIEW {nombre}" if tipo == "vista" else f"DROP TABLE {nombre} CASCADE CONSTRAINTS PURGE"
    try:
        cur.execute(sentencia)
    except co.oracledb.DatabaseError as exc:
        if getattr(exc.args[0], "code", None) == ORA_NO_EXISTE:
            return False
        raise
    return True


def objetos_restantes(cur):
    """Objetos que quedan en el esquema (tablas, vistas, indices, secuencias)."""
    cur.execute("""SELECT object_type, object_name FROM user_objects
                   WHERE object_type IN ('TABLE', 'VIEW', 'INDEX', 'SEQUENCE')
                   ORDER BY object_type, object_name""")
    return cur.fetchall()


def main():
    ap = argparse.ArgumentParser(description="Elimina de Oracle lo cargado por cargar_oracle.py.")
    ap.add_argument("--usuario", default=os.environ.get("FENIX_ORA_USER", "FENIX"))
    ap.add_argument("--dsn", default=os.environ.get("FENIX_ORA_DSN", "localhost:1521/FREEPDB1"),
                    help="host:puerto/servicio (por defecto localhost:1521/FREEPDB1)")
    ap.add_argument("--si", action="store_true", help="no pedir confirmacion")
    args = ap.parse_args()

    if not args.si:
        resp = input(f"Se borraran todas las tablas y vistas de {args.usuario}@{args.dsn}. Continuar? [s/N]: ")
        if resp.strip().lower() not in ("s", "si", "y", "yes"):
            sys.exit("Cancelado: no se borro nada.")
    clave = os.environ.get("FENIX_ORA_PASSWORD") or getpass.getpass(f"Clave de {args.usuario}@{args.dsn}: ")

    try:
        con = co.oracledb.connect(user=args.usuario, password=clave, dsn=args.dsn)
    except co.oracledb.DatabaseError as exc:
        sys.exit(f"No se pudo conectar a Oracle: {exc}")

    with con:
        cur = con.cursor()
        borradas = 0
        # Vistas primero y tablas hijas antes que las padres (orden inverso al de la carga).
        for v in reversed(list(co.VISTAS)):
            ok = borrar(cur, "vista", v)
            borradas += ok
            print(f"  vista  {v:<30}{'borrada' if ok else 'no existia'}")
        for t in reversed(list(co.TABLAS)):
            ok = borrar(cur, "tabla", t)
            borradas += ok
            print(f"  tabla  {t:<30}{'borrada' if ok else 'no existia'}")
        restantes = objetos_restantes(cur)

    if restantes:
        print("\nATENCION: quedan objetos en el esquema:")
        for tipo, nombre in restantes:
            print(f"  {tipo:<10}{nombre}")
        sys.exit(1)
    print(f"\nListo: {borradas} objetos borrados y el esquema {args.usuario} quedo vacio.")
    print("Para volver a cargar:  python scripts/cargar_oracle.py")


if __name__ == "__main__":
    main()
