import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os, time

BASE_DIR = "base"
OUT_DIR = "cartos_creees"
os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)

class ECUApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ECU Assistant V15 PRO")
        self.root.geometry("900x600")

        self.file = ""
        self.build()

    def build(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True)

        self.tab_main = ttk.Frame(nb)
        self.tab_auto = ttk.Frame(nb)
        self.tab_manual = ttk.Frame(nb)

        nb.add(self.tab_main, text="Projet")
        nb.add(self.tab_auto, text="Auto")
        nb.add(self.tab_manual, text="Manuel")

        self.build_main()
        self.build_auto()
        self.build_manual()

    def build_main(self):
        ttk.Label(self.tab_main, text="ECU Assistant V15 PRO", font=("Arial", 18)).pack(pady=10)

        self.entry = ttk.Entry(self.tab_main, width=80)
        self.entry.pack(pady=5)

        ttk.Button(self.tab_main, text="Importer fichier", command=self.import_file).pack(pady=5)
        ttk.Button(self.tab_main, text="Analyse simple", command=self.analyse).pack(pady=5)

        self.log = tk.Text(self.tab_main, height=20)
        self.log.pack(fill="both", expand=True, padx=10, pady=10)

    def build_auto(self):
        ttk.Label(self.tab_auto, text="Mode Auto", font=("Arial", 16)).pack(pady=10)

        self.stage = tk.IntVar(value=50)
        ttk.Scale(self.tab_auto, from_=0, to=100, variable=self.stage).pack(fill="x", padx=20)

        ttk.Button(self.tab_auto, text="Stage 1 AUTO", command=lambda: self.auto_mod(1.05)).pack(pady=5)
        ttk.Button(self.tab_auto, text="Stage 1+", command=lambda: self.auto_mod(1.10)).pack(pady=5)

    def build_manual(self):
        ttk.Label(self.tab_manual, text="Mode Manuel", font=("Arial", 16)).pack(pady=10)

        self.value = tk.DoubleVar(value=5)
        ttk.Label(self.tab_manual, text="Pourcentage").pack()
        ttk.Entry(self.tab_manual, textvariable=self.value).pack()

        ttk.Button(self.tab_manual, text="Appliquer", command=self.manual_mod).pack(pady=5)

    def import_file(self):
        self.file = filedialog.askopenfilename()
        self.entry.delete(0, tk.END)
        self.entry.insert(0, self.file)

    def analyse(self):
        if not self.file:
            messagebox.showerror("Erreur", "Importe un fichier")
            return

        size = os.path.getsize(self.file)
        self.log.insert(tk.END, f"Fichier : {self.file}\nTaille : {size} bytes\n\n")

    def auto_mod(self, factor):
        if not self.file:
            messagebox.showerror("Erreur", "Importe un fichier")
            return

        with open(self.file, "rb") as f:
            data = bytearray(f.read())

        for i in range(0, len(data), 8):
            data[i] = min(255, int(data[i] * factor))

        name = os.path.basename(self.file)
        out = os.path.join(OUT_DIR, name.replace(".bin", "_auto.bin"))

        with open(out, "wb") as f:
            f.write(data)

        messagebox.showinfo("OK", f"Carto créée : {out}")

    def manual_mod(self):
        if not self.file:
            messagebox.showerror("Erreur", "Importe un fichier")
            return

        factor = 1 + (self.value.get() / 100)

        with open(self.file, "rb") as f:
            data = bytearray(f.read())

        for i in range(0, len(data), 10):
            data[i] = min(255, int(data[i] * factor))

        name = os.path.basename(self.file)
        out = os.path.join(OUT_DIR, name.replace(".bin", "_manual.bin"))

        with open(out, "wb") as f:
            f.write(data)

        messagebox.showinfo("OK", f"Carto modifiée : {out}")

root = tk.Tk()
app = ECUApp(root)
root.mainloop()
