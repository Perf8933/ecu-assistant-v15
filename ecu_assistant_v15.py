import tkinter as tk
from tkinter import filedialog, messagebox
import os

class ECUApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ECU Assistant V15")
        self.file_path = ""

        tk.Label(root, text="Fichier ECU").pack()

        self.entry = tk.Entry(root, width=60)
        self.entry.pack()

        tk.Button(root, text="Importer", command=self.import_file).pack(pady=5)

        tk.Button(root, text="Stage 1", command=lambda: self.modify(1.05)).pack()
        tk.Button(root, text="Stage 1+", command=lambda: self.modify(1.10)).pack()
        tk.Button(root, text="Stage 2", command=lambda: self.modify(1.15)).pack()

    def import_file(self):
        self.file_path = filedialog.askopenfilename()
        self.entry.delete(0, tk.END)
        self.entry.insert(0, self.file_path)

    def modify(self, factor):
        if not self.file_path:
            messagebox.showerror("Erreur", "Importe un fichier")
            return

        try:
            with open(self.file_path, "rb") as f:
                data = bytearray(f.read())

            for i in range(len(data)):
                data[i] = min(255, int(data[i] * factor))

            output = self.file_path.replace(".bin", "_mod.bin")

            with open(output, "wb") as f:
                f.write(data)

            messagebox.showinfo("OK", f"Fichier créé : {output}")

        except Exception as e:
            messagebox.showerror("Erreur", str(e))


root = tk.Tk()
app = ECUApp(root)
root.mainloop()
