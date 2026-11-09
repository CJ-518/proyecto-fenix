"""
Proyecto Fenix - Menu interactivo para ejecutar los scripts de scripts/.

Colocar este archivo en la RAIZ del repositorio (junto a scripts/, datos/, salida/) y ejecutar:
    python menu.py

Cada opcion lanza el script correspondiente con el mismo interprete de Python que ejecuta el menu,
usando la raiz del repositorio como directorio de trabajo. Se pueden agregar argumentos extra
(por ejemplo rutas propias o --si) cuando el menu lo pregunta.
Cualquier otro .py que se agregue a scripts/ aparece solo en la seccion "Otros scripts".
"""
import os
import shlex
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(ROOT, "scripts")

# (etiqueta, script, argumentos fijos, descripcion)
ACCIONES = [
    ("Migracion ETL (Excel -> SQLite 3FN)", "migracion_fenix.py", [],
     "Reconstruye salida/fenix_normalizada.db y auditoria.json"),
    ("Benchmark (legacy vs normalizada)", "benchmark_fenix.py", [],
     "Compara tiempos y escribe salida/benchmark.json"),
    ("Seguridad: aplicar", "seguridad_fenix.py", ["aplicar"],
     "Crea bitacora, triggers y sello SHA-256"),
    ("Seguridad: verificar", "seguridad_fenix.py", ["verificar"],
     "Comprueba que la base no fue alterada"),
    ("Seguridad: sellar", "seguridad_fenix.py", ["sellar"],
     "Re-sella la base tras un cambio autorizado"),
    ("Cargar en Oracle", "cargar_oracle.py", [],
     "Copia la base normalizada a Oracle (pide la clave)"),
    ("Limpiar Oracle", "limpiar_oracle.py", [],
     "Borra de Oracle todo lo cargado (pide confirmacion)"),
]

REQUIREMENTS = os.path.join(ROOT, "requirements.txt")


def limpiar_pantalla():
    os.system("cls" if os.name == "nt" else "clear")


def pausar():
    input("\nPresione Enter para volver al menu...")


def ejecutar(cmd, descripcion):
    print(f"\n>>> {descripcion}")
    print(f">>> {' '.join(shlex.quote(c) for c in cmd)}\n" + "-" * 60)
    try:
        r = subprocess.run(cmd, cwd=ROOT, check=False)
        print("-" * 60)
        if r.returncode == 0:
            print("[OK] Finalizo correctamente.")
        else:
            print(f"[ERROR] El proceso termino con codigo {r.returncode}.")
    except KeyboardInterrupt:
        print("\n[INTERRUMPIDO] Cancelado por el usuario.")
    except OSError as exc:
        print(f"[ERROR] No se pudo ejecutar: {exc}")


def pedir_extra():
    extra = input("Argumentos extra (Enter para ninguno): ").strip()
    if not extra:
        return []
    try:
        return shlex.split(extra)
    except ValueError as exc:
        print(f"[AVISO] Argumentos ignorados ({exc}).")
        return []


def ejecutar_script(script, fijos, etiqueta, pedir_args=True):
    ruta = os.path.join(SCRIPTS, script)
    if not os.path.isfile(ruta):
        print(f"[ERROR] No existe {ruta}")
        return
    extra = pedir_extra() if pedir_args else []
    ejecutar([sys.executable, ruta, *fijos, *extra], etiqueta)


def instalar_dependencias():
    if not os.path.isfile(REQUIREMENTS):
        print("[ERROR] No se encontro requirements.txt")
        return
    ejecutar([sys.executable, "-m", "pip", "install", "-r", REQUIREMENTS],
             "Instalando dependencias")


def scripts_extra():
    """Scripts .py de scripts/ que no estan en ACCIONES (ni son importados como modulo)."""
    conocidos = {a[1] for a in ACCIONES}
    if not os.path.isdir(SCRIPTS):
        return []
    return sorted(f for f in os.listdir(SCRIPTS)
                  if f.endswith(".py") and f not in conocidos and not f.startswith("_"))


def estado():
    db = os.path.join(ROOT, "salida", "fenix_normalizada.db")
    datos = os.path.join(ROOT, "datos")
    hay_xls = os.path.isdir(datos) and any(
        f.startswith("Encabezado_") and f.lower().endswith((".xls", ".xlsx"))
        for f in os.listdir(datos))
    print(f"  Planillas en datos/ : {'si' if hay_xls else 'NO (ver datos/LEEME.md)'}")
    print(f"  Base normalizada    : {'si' if os.path.isfile(db) else 'no (ejecute la migracion)'}")


def mostrar_menu(extras):
    limpiar_pantalla()
    print("=" * 60)
    print("  PROYECTO FENIX - Menu de scripts")
    print("=" * 60)
    estado()
    print("-" * 60)
    for i, (etq, _, _, desc) in enumerate(ACCIONES, 1):
        print(f"  {i:>2}) {etq}\n        {desc}")
    n = len(ACCIONES)
    print("-" * 60)
    print(f"  {n + 1:>2}) Instalar dependencias (pip install -r requirements.txt)")
    for j, nombre in enumerate(extras, n + 2):
        print(f"  {j:>2}) Otros scripts: {nombre}")
    print("   0) Salir")
    print("=" * 60)


def main():
    if not os.path.isdir(SCRIPTS):
        sys.exit(f"No se encontro la carpeta scripts/ en {ROOT}. "
                 "Coloque menu.py en la raiz del repositorio.")
    while True:
        extras = scripts_extra()
        mostrar_menu(extras)
        try:
            op = input("Elija una opcion: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if op in ("0", "q", "Q", "salir"):
            break
        if not op.isdigit():
            print("Opcion invalida.")
            pausar()
            continue
        n = int(op)
        total = len(ACCIONES)
        if 1 <= n <= total:
            etq, script, fijos, _ = ACCIONES[n - 1]
            ejecutar_script(script, fijos, etq)
        elif n == total + 1:
            instalar_dependencias()
        elif total + 2 <= n <= total + 1 + len(extras):
            nombre = extras[n - total - 2]
            ejecutar_script(nombre, [], nombre)
        else:
            print("Opcion invalida.")
        pausar()
    print("Hasta luego.")


if __name__ == "__main__":
    main()
