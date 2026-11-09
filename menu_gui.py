"""
Proyecto Fenix - Interfaz grafica para ejecutar los scripts de scripts/.

Uso (desarrollo):   python menu_gui.py
Ejecutable:         ver comando de PyInstaller al final de este archivo.

Coloque este archivo (o el .exe) en la RAIZ del repositorio, junto a scripts/, datos/ y salida/.
Los scripts se ejecutan dentro del mismo proceso (runpy), de modo que funciona igual como .py
que como .exe empaquetado. La salida de cada script se muestra en el panel de registro.
"""
import io
import os
import queue
import runpy
import shlex
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

MARCA = os.path.join("scripts", "migracion_fenix.py")  # identifica la raiz del repositorio


def _inicio():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def buscar_raiz():
    """Busca la carpeta que contiene scripts/, subiendo desde el .exe/.py y desde el cwd."""
    for base in (_inicio(), os.getcwd()):
        d = base
        for _ in range(5):
            if os.path.isfile(os.path.join(d, MARCA)):
                return d
            padre = os.path.dirname(d)
            if padre == d:
                break
            d = padre
    return _inicio()


ROOT = buscar_raiz()
SCRIPTS = os.path.join(ROOT, "scripts")
REQUIREMENTS = os.path.join(ROOT, "requirements.txt")
SALIDA = os.path.join(ROOT, "salida")


def fijar_raiz(ruta):
    global ROOT, SCRIPTS, REQUIREMENTS, SALIDA
    ROOT = ruta
    SCRIPTS = os.path.join(ROOT, "scripts")
    REQUIREMENTS = os.path.join(ROOT, "requirements.txt")
    SALIDA = os.path.join(ROOT, "salida")

# (etiqueta, script, argumentos fijos, descripcion, necesita_clave, pide_confirmacion)
ACCIONES = [
    ("1. Migracion ETL", "migracion_fenix.py", [],
     "Excel -> SQLite 3FN. Reconstruye la base y auditoria.json", False, False),
    ("2. Benchmark", "benchmark_fenix.py", [],
     "Compara planillas legacy vs. base normalizada", False, False),
    ("3. Seguridad: aplicar", "seguridad_fenix.py", ["aplicar"],
     "Bitacora, triggers y sello SHA-256", False, False),
    ("4. Seguridad: verificar", "seguridad_fenix.py", ["verificar"],
     "Comprueba que la base no fue alterada", False, False),
    ("5. Seguridad: sellar", "seguridad_fenix.py", ["sellar"],
     "Re-sella tras un cambio autorizado", False, False),
    ("6. Cargar en Oracle", "cargar_oracle.py", [],
     "Copia la base normalizada a Oracle", True, False),
    ("7. Limpiar Oracle", "limpiar_oracle.py", ["--si"],
     "Borra de Oracle todo lo cargado", True, True),
]


class Escritor(io.TextIOBase):
    """Envia lo que imprime un script a la cola de la interfaz."""

    def __init__(self, cola):
        self.cola = cola

    def write(self, texto):
        if texto:
            self.cola.put(texto)
        return len(texto)

    def flush(self):
        pass

    def isatty(self):
        return False


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Proyecto Fenix - Ejecutor de scripts")
        self.geometry("980x620")
        self.minsize(820, 480)
        self.cola = queue.Queue()
        self.ocupado = False
        self.botones = []
        self.botones_extra = []
        self._construir()
        self._actualizar_estado()
        self.after(100, self._vaciar_cola)
        if not os.path.isfile(os.path.join(ROOT, MARCA)):
            self.after(400, self._aviso_raiz)

    # ---------- interfaz ----------
    def _construir(self):
        izq = ttk.Frame(self, padding=10)
        izq.pack(side="left", fill="y")
        der = ttk.Frame(self, padding=(0, 10, 10, 10))
        der.pack(side="right", fill="both", expand=True)

        ttk.Label(izq, text="Scripts", font=("", 12, "bold")).pack(anchor="w")
        for etq, script, fijos, desc, clave, conf in ACCIONES:
            b = ttk.Button(izq, text=etq, width=28,
                           command=lambda s=script, f=fijos, e=etq, c=clave, k=conf:
                           self.lanzar(s, f, e, c, k))
            b.pack(fill="x", pady=(6, 0))
            ttk.Label(izq, text=desc, foreground="#666", wraplength=230).pack(anchor="w")
            self.botones.append(b)

        self.frame_extras = ttk.Frame(izq)
        self.frame_extras.pack(fill="x")
        self._cargar_extras()

        ttk.Separator(izq).pack(fill="x", pady=10)
        ttk.Label(izq, text="Argumentos extra (opcional)").pack(anchor="w")
        self.var_args = tk.StringVar()
        ttk.Entry(izq, textvariable=self.var_args).pack(fill="x")
        ttk.Label(izq, text="Ej.: rutas propias, --usuario X, --dsn host:1521/PDB",
                  foreground="#666", wraplength=230).pack(anchor="w")

        ttk.Separator(izq).pack(fill="x", pady=10)
        if not getattr(sys, "frozen", False):
            b = ttk.Button(izq, text="Instalar dependencias", command=self.instalar)
            b.pack(fill="x")
            self.botones.append(b)
        ttk.Button(izq, text="Cambiar carpeta del proyecto...", command=self.elegir_raiz).pack(fill="x")
        ttk.Button(izq, text="Abrir carpeta salida/", command=self.abrir_salida).pack(fill="x", pady=(6, 0))
        ttk.Button(izq, text="Salir", command=self.destroy).pack(fill="x", pady=(6, 0))

        self.var_estado = tk.StringVar()
        ttk.Label(der, textvariable=self.var_estado, foreground="#444", wraplength=640,
                  justify="left").pack(anchor="w")
        self.log = scrolledtext.ScrolledText(der, wrap="word", state="disabled",
                                             font=("Consolas", 10), height=20)
        self.log.pack(fill="both", expand=True, pady=6)
        self.log.tag_configure("info", foreground="#1a5fb4")
        self.log.tag_configure("ok", foreground="#26a269")
        self.log.tag_configure("err", foreground="#c01c28")
        barra = ttk.Frame(der)
        barra.pack(fill="x")
        self.progreso = ttk.Progressbar(barra, mode="indeterminate", length=160)
        self.progreso.pack(side="left")
        ttk.Button(barra, text="Limpiar registro", command=self.limpiar_log).pack(side="right")

    def _cargar_extras(self):
        conocidos = {a[1] for a in ACCIONES}
        if not os.path.isdir(SCRIPTS):
            return
        extras = sorted(f for f in os.listdir(SCRIPTS)
                        if f.endswith(".py") and f not in conocidos and not f.startswith("_"))
        if not extras:
            return
        ttk.Label(self.frame_extras, text="Otros scripts", font=("", 10, "bold")).pack(anchor="w", pady=(10, 0))
        for nombre in extras:
            b = ttk.Button(self.frame_extras, text=nombre, width=28,
                           command=lambda n=nombre: self.lanzar(n, [], n, False, False))
            b.pack(fill="x", pady=(4, 0))
            self.botones.append(b)
            self.botones_extra.append(b)

    def _aviso_raiz(self):
        messagebox.showwarning(
            "No se encontro scripts/",
            f"No se encontro la carpeta scripts/ cerca de:\n{_inicio()}\n\n"
            "Use 'Cambiar carpeta del proyecto...' y elija la carpeta del repositorio "
            "(la que contiene scripts/, datos/ y salida/).")

    def elegir_raiz(self):
        if self.ocupado:
            return
        ruta = filedialog.askdirectory(title="Carpeta del proyecto (contiene scripts/)", initialdir=ROOT)
        if not ruta:
            return
        ruta = os.path.normpath(ruta)
        if not os.path.isfile(os.path.join(ruta, MARCA)):
            messagebox.showerror("Carpeta incorrecta", f"No se encontro {MARCA} dentro de:\n{ruta}")
            return
        fijar_raiz(ruta)
        for b in self.botones_extra:
            if b in self.botones:
                self.botones.remove(b)
        for w in self.frame_extras.winfo_children():
            w.destroy()
        self.botones_extra = []
        self._cargar_extras()
        self._actualizar_estado()
        self.escribir(f"\nCarpeta del proyecto: {ROOT}\n", "info")

    def _actualizar_estado(self):
        datos = os.path.join(ROOT, "datos")
        hay = os.path.isdir(datos) and any(
            f.startswith("Encabezado_") and f.lower().endswith((".xls", ".xlsx"))
            for f in os.listdir(datos))
        db = os.path.isfile(os.path.join(SALIDA, "fenix_normalizada.db"))
        self.var_estado.set(f"Planillas en datos/: {'si' if hay else 'NO'}   |   "
                            f"Base normalizada: {'si' if db else 'no'}   |   Raiz: {ROOT}")

    # ---------- registro ----------
    def escribir(self, texto, tag=None):
        self.log.configure(state="normal")
        if tag:
            self.log.insert("end", texto, tag)
        else:
            self.log.insert("end", texto)
        self.log.see("end")
        self.log.configure(state="disabled")

    def limpiar_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _vaciar_cola(self):
        try:
            while True:
                item = self.cola.get_nowait()
                if isinstance(item, tuple):
                    if item[0] == "fin":
                        self._terminar(item[1])
                    else:
                        self.escribir(item[1], item[0])
                else:
                    self.escribir(item)
        except queue.Empty:
            pass
        self.after(100, self._vaciar_cola)

    # ---------- ejecucion ----------
    def _bloquear(self, bloquear):
        self.ocupado = bloquear
        for b in self.botones:
            b.configure(state="disabled" if bloquear else "normal")
        if bloquear:
            self.progreso.start(12)
        else:
            self.progreso.stop()

    def _terminar(self, codigo):
        if codigo == 0:
            self.escribir("\n[OK] Finalizo correctamente.\n", "ok")
        else:
            self.escribir(f"\n[ERROR] Termino con codigo {codigo}.\n", "err")
        self._bloquear(False)
        self._actualizar_estado()

    def lanzar(self, script, fijos, etiqueta, necesita_clave, confirmar):
        if self.ocupado:
            return
        ruta = os.path.join(SCRIPTS, script)
        if not os.path.isfile(ruta):
            messagebox.showerror("Falta el script", f"No existe:\n{ruta}")
            return
        if confirmar and not messagebox.askyesno(
                "Confirmar", "Se borraran todas las tablas y vistas cargadas en Oracle.\n\nContinuar?"):
            return
        clave = None
        if necesita_clave and not os.environ.get("FENIX_ORA_PASSWORD"):
            clave = simpledialog.askstring("Clave de Oracle", "Clave del usuario de Oracle:", show="*", parent=self)
            if clave is None:
                return
        try:
            extra = shlex.split(self.var_args.get())
        except ValueError as exc:
            messagebox.showerror("Argumentos invalidos", str(exc))
            return
        argv = [ruta, *fijos, *extra]
        self.escribir(f"\n>>> {etiqueta}\n>>> {' '.join(shlex.quote(a) for a in argv[1:])}\n" + "-" * 60 + "\n", "info")
        self._bloquear(True)
        threading.Thread(target=self._worker, args=(ruta, argv, clave), daemon=True).start()

    def _worker(self, ruta, argv, clave):
        salida = Escritor(self.cola)
        old = (sys.stdout, sys.stderr, sys.stdin, sys.argv, list(sys.path))
        old_clave = os.environ.get("FENIX_ORA_PASSWORD")
        codigo = 0
        try:
            sys.stdout = sys.stderr = salida
            sys.stdin = io.StringIO("")
            sys.argv = argv
            sys.path.insert(0, SCRIPTS)
            if clave is not None:
                os.environ["FENIX_ORA_PASSWORD"] = clave
            runpy.run_path(ruta, run_name="__main__")
        except SystemExit as exc:
            if exc.code is None or exc.code == 0:
                codigo = 0
            elif isinstance(exc.code, int):
                codigo = exc.code
            else:  # sys.exit("mensaje")
                print(exc.code)
                codigo = 1
        except BaseException:
            traceback.print_exc()
            codigo = 1
        finally:
            sys.stdout, sys.stderr, sys.stdin, sys.argv = old[:4]
            sys.path[:] = old[4]
            if clave is not None:
                if old_clave is None:
                    os.environ.pop("FENIX_ORA_PASSWORD", None)
                else:
                    os.environ["FENIX_ORA_PASSWORD"] = old_clave
            self.cola.put(("fin", codigo))

    def instalar(self):
        if self.ocupado:
            return
        if not os.path.isfile(REQUIREMENTS):
            messagebox.showerror("Falta archivo", "No se encontro requirements.txt")
            return
        self.escribir("\n>>> Instalando dependencias\n" + "-" * 60 + "\n", "info")
        self._bloquear(True)

        def trabajo():
            codigo = 1
            try:
                p = subprocess.Popen([sys.executable, "-m", "pip", "install", "-r", REQUIREMENTS],
                                     cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1)
                for linea in (p.stdout or []):
                    self.cola.put(linea)
                codigo = p.wait()
            except OSError as exc:
                self.cola.put(("err", f"{exc}\n"))
            self.cola.put(("fin", codigo))

        threading.Thread(target=trabajo, daemon=True).start()

    def abrir_salida(self):
        os.makedirs(SALIDA, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(SALIDA)  # noqa
            elif sys.platform == "darwin":
                subprocess.Popen(["open", SALIDA])
            else:
                subprocess.Popen(["xdg-open", SALIDA])
        except OSError as exc:
            messagebox.showerror("No se pudo abrir", str(exc))


if __name__ == "__main__":
    App().mainloop()

# ---------------------------------------------------------------------------
# Crear el ejecutable (ejecutar desde la raiz del repositorio):
#
#   pip install pyinstaller -r requirements.txt
#   pyinstaller --onefile --windowed --name FenixGUI ^
#       --hidden-import pandas --hidden-import openpyxl --hidden-import xlrd ^
#       --hidden-import oracledb --collect-submodules oracledb ^
#       menu_gui.py
#
# (en Linux/macOS use \ en lugar de ^ al final de cada linea)
# El ejecutable queda en dist/FenixGUI(.exe). Puede dejarlo en dist/ o copiarlo a la raiz:
# el programa busca scripts/ subiendo desde su carpeta (o use 'Cambiar carpeta del proyecto...').
# ---------------------------------------------------------------------------
