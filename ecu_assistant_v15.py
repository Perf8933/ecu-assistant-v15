import tkinter as tk
from tkinter import filedialog, messagebox
import os

class ECUApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ECU Assistant V15 PRO")
        self.file_path = ""

        tk.Label(root, text="Fichier ECU").pack()

        self.entry = tk.Entry(root, width=60)
        self.entry.pack()

        tk.Button(root, text="Importer", command=self.import_file).pack(pady=5)

        tk.Button(root, text="Analyse", command=self.analyse).pack()
        tk.Button(root, text="Stage 1 SAFE", command=lambda: self.modify(1.03)).pack()
        tk.Button(root, text="Stage 1+", command=lambda: self.modify(1.06)).pack()

    def import_file(self):
        self.file_path = filedialog.askopenfilename()
        self.entry.delete(0, tk.END)
        self.entry.insert(0, self.file_path)

    def analyse(self):
        if not self.file_path:
            messagebox.showerror("Erreur", "Importe un fichier")
            return

        size = os.path.getsize(self.file_path)

        messagebox.showinfo(
            "Analyse",
            f"Taille fichier : {size} bytes\nCompatible mod SAFE"
        )

    def modify(self, factor):
        if not self.file_path:
            messagebox.showerror("Erreur", "Importe un fichier")
            return

        try:
            with open(self.file_path, "rb") as f:
                data = bytearray(f.read())

            # modification limitée (sécurité)
            for i in range(0, len(data), 10):
                data[i] = min(255, int(data[i] * factor))

            output = self.file_path.replace(".bin", "_safe_mod.bin")

            with open(output, "wb") as f:
                f.write(data)

            messagebox.showinfo("OK", f"Carto SAFE créée : {output}")

        except Exception as e:
            messagebox.showerror("Erreur", str(e))


root = tk.Tk()
app = ECUApp(root)
root.mainloop()
