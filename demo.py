"""
Proyecto Fenix - Lanzador de demos para la presentacion.

Uso:
  python demo.py            menu interactivo
  python demo.py 3          ejecuta solo la demo 3
  python demo.py todo       ejecuta las demos 1 a 5, una tras otra
  python demo.py migracion  ejecuta la migracion real (requiere las planillas en datos/)
  python demo.py benchmark  ejecuta el benchmark completo (requiere las planillas en datos/)
  python demo.py oracle     carga la base migrada en Oracle (para verla en DBeaver)
  python demo.py limpiar    borra de Oracle todo lo cargado (para repetir la demostracion)

La salida de cada demo se muestra paginada: se limpia la pantalla y, si el texto no cabe
sin hacer scroll, se espera una tecla para ver la pagina siguiente (q = saltar el resto).

Oracle: requiere  python -m pip install oracledb  y el usuario creado con
scripts/oracle_crear_usuario.sql. La clave se pide una sola vez por sesion (o se toma de la
variable de entorno FENIX_ORA_PASSWORD).
"""
import getpass
import glob
import os
import shutil
import subprocess
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
DEMOS = {
    "1": ("Modelo rediseñado (11 tablas en 3FN, reglas en el motor)", "demos/d1_modelo.py"),
    "2": ("Calidad de datos: antes y después", "demos/d2_calidad.py"),
    "3": ("Conciliación origen–destino e integridad", "demos/d3_conciliacion.py"),
    "4": ("Lo que revela la nueva base", "demos/d4_hallazgos.py"),
    "5": ("Optimización y rendimiento", "demos/d5_rendimiento.py"),
}
PIPELINE = {
    "migracion": ("Migración real (Excel -> SQLite 3FN)", "scripts/migracion_fenix.py"),
    "benchmark": ("Benchmark completo (planillas vs. base)", "scripts/benchmark_fenix.py"),
    "oracle": ("Cargar la base migrada en Oracle (ver en DBeaver)", "scripts/cargar_oracle.py"),
    "limpiar": ("Borrar de Oracle todo lo cargado", "scripts/limpiar_oracle.py"),
}
ATAJOS = {"m": "migracion", "b": "benchmark", "o": "oracle", "l": "limpiar", "t": "todo"}
_SESION = {}  # datos que se recuerdan mientras el menu esta abierto (la clave de Oracle)

_reconfigure = getattr(sys.stdout, "reconfigure", None)
if _reconfigure:
    _reconfigure(encoding="utf-8")


# ------------------------------------------------------------------ terminal
def interactivo():
    return sys.stdin.isatty() and sys.stdout.isatty()


def limpiar():
    if not interactivo():
        return
    os.system("cls" if os.name == "nt" else "clear")


def esperar_tecla():
    """Espera una sola tecla (sin Enter). Devuelve el caracter pulsado."""
    if not interactivo():
        return ""
    if sys.platform == "win32":
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):  # tecla especial (flechas, F1...): descartar el 2.o codigo
            msvcrt.getwch()
            return ""
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch
    try:
        import termios
        import tty
    except ImportError:  # plataforma sin termios: se pide Enter
        input()
        return ""
    try:
        fd = sys.stdin.fileno()
        viejo = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, viejo)
    except (OSError, ValueError, termios.error):  # terminal sin modo "raw": se pide Enter
        input()
        return ""
    if ch == "\x03":
        raise KeyboardInterrupt
    return ch


def filas_de(linea, ancho):
    """Cuantas filas de pantalla ocupa una linea (considerando que se parte si es mas ancha)."""
    return max(1, -(-len(linea.expandtabs()) // ancho))


def paginar(lineas, pie_final=True):
    """Muestra las lineas por paginas. Devuelve False si el usuario pidio saltar el resto."""
    if not interactivo():
        print("\n".join(lineas))
        return True
    cols, filas = shutil.get_terminal_size((100, 30))
    capacidad = max(5, filas - 2)  # reserva el pie y la linea del cursor
    # 1) partir en paginas respetando el ajuste de lineas largas
    paginas, actual, usadas = [], [], 0
    for ln in lineas:
        h = filas_de(ln, cols)
        if usadas + h > capacidad and actual:
            # preferir cortar en una linea en blanco cercana al final (no partir tablas)
            corte = None
            for i in range(len(actual) - 1, max(len(actual) * 6 // 10, 0), -1):
                # no cortar justo despues de un titulo de seccion ("--- ...") para no dejarlo huerfano
                if not actual[i].strip() and not (i > 0 and actual[i - 1].lstrip().startswith("---")):
                    corte = i
                    break
            if corte is not None:
                paginas.append(actual[:corte])
                actual = actual[corte + 1:]
            else:
                paginas.append(actual)
                actual = []
            usadas = sum(filas_de(x, cols) for x in actual)
        actual.append(ln)
        usadas += h
    if actual:
        paginas.append(actual)
    # 2) mostrar
    total = len(paginas)
    for i, pag in enumerate(paginas, 1):
        limpiar()
        print("\n".join(pag))
        ultima = i == total
        if ultima and not pie_final:
            break
        if ultima:
            print(f"\n[fin · pagina {i}/{total} · pulse una tecla]", end="", flush=True)
        else:
            print(f"\n[pagina {i}/{total} · cualquier tecla = continuar · q = saltar el resto]", end="", flush=True)
        tecla = esperar_tecla()
        print()
        if tecla.lower() == "q" and not ultima:
            return False
    return True


# ------------------------------------------------------------------ ejecucion
def hay_planillas():
    return bool(glob.glob(os.path.join(RAIZ, "datos", "Encabezado_*.xls*")))


def clave_oracle():
    """Clave del usuario FENIX de Oracle: variable de entorno o se pide una vez por sesion."""
    if "clave" not in _SESION:
        _SESION["clave"] = os.environ.get("FENIX_ORA_PASSWORD") or getpass.getpass("Clave de FENIX en Oracle: ")
    return _SESION["clave"]


def correr(ruta, pie_final=True, args=(), env_extra=None):
    """Ejecuta un script, captura su salida y la muestra paginada."""
    if interactivo():
        limpiar()
        print(f"Ejecutando {ruta} ...")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", **(env_extra or {}))
    r = subprocess.run([sys.executable, os.path.join(RAIZ, ruta), *args], cwd=RAIZ, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    salida = r.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n").rstrip("\n")
    lineas = salida.split("\n")
    if r.returncode:
        lineas += ["", f"[el script termino con codigo {r.returncode}]"]
        if "openpyxl" in salida or "xlrd" in salida:
            lineas += ["Faltan dependencias. Instalelas con:  python -m pip install -r requirements.txt"]
        if "oracledb" in salida and "Falta el paquete" in salida:
            lineas += ["Instale el driver de Oracle con:  python -m pip install oracledb"]
    paginar(lineas, pie_final)


def correr_oracle(op, pie_final):
    """Carga (oracle) o borra (limpiar) lo cargado en Oracle, pasando la clave por entorno."""
    try:
        env = {"FENIX_ORA_PASSWORD": clave_oracle()}
    except (EOFError, KeyboardInterrupt):
        print("\nCancelado: no se ingreso la clave.")
        return
    # el menu ya pidio confirmacion: el script de limpieza no vuelve a preguntar
    correr(PIPELINE[op][1], pie_final=pie_final, args=("--si",) if op == "limpiar" else (), env_extra=env)


def confirmar_limpieza():
    print("Se borraran de Oracle todas las tablas y vistas cargadas (el usuario FENIX se conserva).")
    print("Continuar? [s/N]: ", end="", flush=True)
    try:
        return input().strip().lower() in ("s", "si", "y", "yes")
    except EOFError:
        return False


def menu():
    while True:
        limpiar()
        print("PROYECTO FÉNIX · demos\n")
        for k, (t, _) in DEMOS.items():
            print(f"  {k}) {t}")
        estado = "planillas encontradas" if hay_planillas() else "faltan las planillas en datos/"
        print(f"  m) {PIPELINE['migracion'][0]}   [{estado}]")
        print(f"  b) {PIPELINE['benchmark'][0]}")
        print(f"  o) {PIPELINE['oracle'][0]}")
        print(f"  l) {PIPELINE['limpiar'][0]}")
        print("  t) Todas las demos (1 a 5)")
        print("  q) Salir")
        print("\nElija una opcion y pulse Enter: ", end="", flush=True)
        try:
            op = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if op in ("q", ""):
            limpiar()
            return
        ejecutar(op, desde_menu=True)


def ejecutar(op, desde_menu=False):
    op = ATAJOS.get(op, op)
    if op in DEMOS:
        correr(DEMOS[op][1], pie_final=desde_menu)
    elif op in ("oracle", "limpiar"):
        if op == "limpiar" and interactivo() and not confirmar_limpieza():
            print("Cancelado: no se borro nada.")
            if desde_menu:
                esperar_tecla()
            return
        correr_oracle(op, pie_final=desde_menu)
    elif op in PIPELINE:
        correr(PIPELINE[op][1], pie_final=desde_menu)
    elif op == "todo":
        for _, ruta in DEMOS.values():
            correr(ruta, pie_final=True)
    else:
        print(f"Opcion no valida: {op}")
        if desde_menu:
            esperar_tecla()


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1:
            ejecutar(sys.argv[1].lower())
        else:
            menu()
    except KeyboardInterrupt:
        print()
