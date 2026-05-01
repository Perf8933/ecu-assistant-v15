import os, csv, time, struct, hashlib
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP = "ECU Assistant V16 PRO"
OUT = "cartos_creees"
REP = "rapports"
for d in [OUT, REP, "base_stock", "base_mod", "base_gold"]:
    os.makedirs(d, exist_ok=True)

def now():
    return time.strftime("%Y%m%d_%H%M%S")

def sha1(data):
    return hashlib.sha1(data).hexdigest()

def u16(data, off):
    return struct.unpack_from(">H", data, off)[0]

def w16(data, off, val):
    struct.pack_into(">H", data, off, max(0, min(65535, int(round(val)))))

class Map:
    def __init__(self, name, off, rows, cols, vals, conf, reason):
        self.name = name
        self.off = off
        self.rows = rows
        self.cols = cols
        self.vals = vals
        self.conf = conf
        self.reason = reason

    def grid(self):
        return [self.vals[i*self.cols:(i+1)*self.cols] for i in range(self.rows)]

def smooth_score(vals, rows, cols):
    mn, mx = min(vals), max(vals)
    rng = max(1, mx - mn)
    jumps = []
    for r in range(rows):
        for c in range(cols-1):
            jumps.append(abs(vals[r*cols+c+1] - vals[r*cols+c]) / rng)
    for r in range(rows-1):
        for c in range(cols):
            jumps.append(abs(vals[(r+1)*cols+c] - vals[r*cols+c]) / rng)
    return max(0, 1 - (sum(jumps)/len(jumps) if jumps else 1))

def classify(vals, rows, cols):
    mn, mx = min(vals), max(vals)
    avg = sum(vals) / len(vals)
    zeros = vals.count(0)
    smooth = smooth_score(vals, rows, cols)
    out = []

    if 850 <= mn <= 1700 and 1600 <= mx <= 2350 and smooth > .55:
        out.append(("Boost target", .85, "pression turbo probable"))

    if 1800 <= mn <= 7000 and mx <= 8500 and avg > 2500:
        out.append(("Boost limiter", .78, "limiteur turbo probable"))

    if 1000 <= mn <= 2700 and 4200 <= mx <= 7600 and smooth > .40:
        out.append(("Smoke limiter", .86, "limiteur fumée / air probable"))

    if zeros >= 2 and 2200 <= mx <= 4200 and smooth > .25:
        out.append(("Torque limiter", .84, "limiteur couple probable"))

    if zeros >= 3 and 2800 <= mx <= 5200:
        out.append(("Driver wish", .80, "demande pédale probable"))

    if 0 <= mn <= 1000 and 6000 <= mx <= 12500 and smooth > .30:
        out.append(("Duration", .76, "temps injection probable"))

    if 2000 <= mn <= 8500 and 9000 <= mx <= 21000:
        out.append(("Rail pressure", .70, "pression rail possible"))

    if not out and smooth > .75 and len(set(vals)) > 10:
        out.append(("Unknown smooth map", .55, "map lisse inconnue"))

    return out

def scan_maps(data):
    specs = [(16,12), (11,10), (4,20), (16,8), (12,12), (8,8), (1,16), (1,20)]
    found = []
    for rows, cols in specs:
        size = rows * cols * 2
        for off in range(0, max(0, len(data)-size), 4):
            try:
                vals = [u16(data, off+i*2) for i in range(rows*cols)]
            except Exception:
                continue
            if min(vals) == max(vals):
                continue
            for name, conf, reason in classify(vals, rows, cols):
                found.append(Map(name, off, rows, cols, vals, conf, reason))
            if len(found) > 600:
                break

    clean, seen = [], set()
    for m in sorted(found, key=lambda x: x.conf, reverse=True):
        key = (m.name, m.off // 16)
        if key not in seen:
            seen.add(key)
            clean.append(m)
    return clean[:300]

def analyse_viability(maps, level):
    names = {m.name for m in maps if m.conf >= .70}
    req = {"Driver wish", "Torque limiter", "Smoke limiter", "Boost target"}
    if level in ["Stage 1+", "Stage 2 light"]:
        req.add("Boost limiter")
    if level == "Stage 2 light":
        req.add("Duration")

    missing = sorted(req - names)
    score = max(0, 100 - len(missing)*22)
    alerts = []

    if "Boost target" in names and "Smoke limiter" not in names:
        score -= 15
        alerts.append("Boost trouvé mais smoke absent")
    if "Duration" in names and "Smoke limiter" not in names:
        score -= 15
        alerts.append("Duration sans smoke fiable")
    if "Torque limiter" in names and "Driver wish" not in names:
        score -= 8
        alerts.append("Torque sans Driver Wish")

    score = max(0, min(100, score))
    if score >= 80 and not missing:
        status = "OK viable"
    elif score >= 55:
        status = "DOUTEUX / manuel conseillé"
    else:
        status = "NON VIABLE auto"
    return score, status, missing, alerts

def smooth_grid(grid, strength=.35):
    rows, cols = len(grid), len(grid[0])
    out = [r[:] for r in grid]
    for r in range(rows):
        for c in range(cols):
            vals = []
            if 0 < c < cols-1:
                vals += [grid[r][c-1], grid[r][c], grid[r][c+1]]
            if 0 < r < rows-1:
                vals += [grid[r-1][c], grid[r][c], grid[r+1][c]]
            if vals:
                out[r][c] = round(grid[r][c]*(1-strength) + sum(vals)/len(vals)*strength)
    return out

class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP)
        self.root.geometry("1250x780")
        self.file = ""
        self.data = None
        self.maps = []
        self.stage = tk.StringVar(value="Stage 1")
        self.stock_hp = tk.DoubleVar(value=105)
        self.stock_nm = tk.DoubleVar(value=250)
        self.apply_real = tk.BooleanVar(value=False)
        self.manual_idx = tk.IntVar(value=1)
        self.manual_op = tk.StringVar(value="%")
        self.manual_val = tk.DoubleVar(value=2.0)
        self.build()

    def build(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True)

        self.t_project = ttk.Frame(nb)
        self.t_auto = ttk.Frame(nb)
        self.t_manual = ttk.Frame(nb)
        self.t_maps = ttk.Frame(nb)
        self.t_base = ttk.Frame(nb)

        nb.add(self.t_project, text="Projet")
        nb.add(self.t_auto, text="Auto")
        nb.add(self.t_manual, text="Manuel")
        nb.add(self.t_maps, text="Maps")
        nb.add(self.t_base, text="Base")

        self.build_project()
        self.build_auto()
        self.build_manual()
        self.build_maps()
        self.build_base()

    def build_project(self):
        ttk.Label(self.t_project, text="ECU Assistant V16 PRO", font=("Arial", 22, "bold")).pack(pady=10)
        self.path_entry = ttk.Entry(self.t_project, width=120)
        self.path_entry.pack(pady=5)

        row = ttk.Frame(self.t_project)
        row.pack(pady=5)
        ttk.Button(row, text="Importer carto", command=self.import_file).pack(side="left", padx=5)
        ttk.Button(row, text="Scan IA complet", command=self.scan).pack(side="left", padx=5)
        ttk.Button(row, text="Exporter rapport", command=self.export_report).pack(side="left", padx=5)

        row2 = ttk.Frame(self.t_project)
        row2.pack(pady=5)
        ttk.Label(row2, text="Puissance stock").pack(side="left")
        ttk.Entry(row2, textvariable=self.stock_hp, width=8).pack(side="left", padx=4)
        ttk.Label(row2, text="Couple stock").pack(side="left")
        ttk.Entry(row2, textvariable=self.stock_nm, width=8).pack(side="left", padx=4)

        self.live = ttk.Label(self.t_project, text="", font=("Arial", 13, "bold"))
        self.live.pack(pady=10)

        self.log = tk.Text(self.t_project, height=28)
        self.log.pack(fill="both", expand=True, padx=10, pady=10)

    def build_auto(self):
        ttk.Label(self.t_auto, text="Mode Auto intelligent", font=("Arial", 18, "bold")).pack(pady=10)
        row = ttk.Frame(self.t_auto)
        row.pack(pady=5)
        ttk.Label(row, text="Objectif").pack(side="left")
        ttk.Combobox(row, textvariable=self.stage, values=["Stage 1", "Stage 1+", "Stage 2 light"], state="readonly", width=16).pack(side="left", padx=5)
        ttk.Checkbutton(row, text="Appliquer réellement", variable=self.apply_real).pack(side="left", padx=8)

        ttk.Button(self.t_auto, text="Analyser viabilité", command=self.analyse_auto).pack(pady=5)
        ttk.Button(self.t_auto, text="Générer proposition", command=self.generate_auto).pack(pady=5)

        self.auto_txt = tk.Text(self.t_auto, height=32)
        self.auto_txt.pack(fill="both", expand=True, padx=10, pady=10)

    def build_manual(self):
        ttk.Label(self.t_manual, text="Mode Manuel ciblé", font=("Arial", 18, "bold")).pack(pady=10)
        row = ttk.Frame(self.t_manual)
        row.pack(pady=5)
        ttk.Label(row, text="Index map").pack(side="left")
        ttk.Entry(row, textvariable=self.manual_idx, width=6).pack(side="left", padx=5)
        ttk.Label(row, text="Opération").pack(side="left")
        ttk.Combobox(row, textvariable=self.manual_op, values=["%", "+", "-", "*", "/", "set"], width=8).pack(side="left", padx=5)
        ttk.Label(row, text="Valeur").pack(side="left")
        ttk.Entry(row, textvariable=self.manual_val, width=8).pack(side="left", padx=5)

        ttk.Button(self.t_manual, text="Prévisualiser", command=self.preview_manual).pack(pady=4)
        ttk.Button(self.t_manual, text="Modifier map", command=self.modify_manual).pack(pady=4)
        ttk.Button(self.t_manual, text="Lisser map", command=self.smooth_manual).pack(pady=4)

        self.manual_txt = tk.Text(self.t_manual, height=32)
        self.manual_txt.pack(fill="both", expand=True, padx=10, pady=10)

    def build_maps(self):
        ttk.Button(self.t_maps, text="Exporter maps CSV", command=self.export_maps).pack(pady=5)
        self.maps_txt = tk.Text(self.t_maps, height=36)
        self.maps_txt.pack(fill="both", expand=True, padx=10, pady=10)

    def build_base(self):
        ttk.Label(self.t_base, text="Base locale", font=("Arial", 18, "bold")).pack(pady=10)
        ttk.Label(self.t_base, text="Dossiers créés automatiquement : base_stock / base_mod / base_gold / rapports / cartos_creees").pack(pady=5)
        ttk.Button(self.t_base, text="Ouvrir dossier du logiciel", command=lambda: os.startfile(os.getcwd())).pack(pady=5)
        self.base_txt = tk.Text(self.t_base, height=30)
        self.base_txt.pack(fill="both", expand=True, padx=10, pady=10)
        self.refresh_base()

    def import_file(self):
        self.file = filedialog.askopenfilename()
        if not self.file:
            return
        with open(self.file, "rb") as f:
            self.data = f.read()
        self.path_entry.delete(0, tk.END)
        self.path_entry.insert(0, self.file)
        self.log.insert(tk.END, f"Importé : {self.file}\nTaille : {len(self.data)} bytes\nSHA1 : {sha1(self.data)}\n\n")
        self.update_gain()

    def scan(self):
        if not self.data:
            messagebox.showerror("Erreur", "Importe une carto")
            return
        self.log.insert(tk.END, "Scan IA en cours...\n")
        self.root.update()
        self.maps = scan_maps(self.data)
        self.log.insert(tk.END, f"{len(self.maps)} maps candidates détectées\n\n")
        self.maps_txt.delete("1.0", tk.END)
        for i, m in enumerate(self.maps, 1):
            self.maps_txt.insert(tk.END, f"{i:03d} | {m.name} | {hex(m.off)} | {m.rows}x{m.cols} | conf {m.conf} | min {min(m.vals)} max {max(m.vals)} | {m.reason}\n")
        self.update_gain()

    def analyse_auto(self):
        if not self.maps:
            self.scan()
        score, status, missing, alerts = analyse_viability(self.maps, self.stage.get())
        self.auto_txt.delete("1.0", tk.END)
        self.auto_txt.insert(tk.END, f"Objectif : {self.stage.get()}\nScore : {score}/100\nStatut : {status}\n")
        self.auto_txt.insert(tk.END, f"Maps manquantes : {missing}\nAlertes : {alerts}\n")
        self.update_gain()

    def update_gain(self):
        if not hasattr(self, "live"):
            return
        score = 50
        if self.maps:
            score, _, _, _ = analyse_viability(self.maps, "Stage 1")
        hp, nm = self.stock_hp.get(), self.stock_nm.get()
        gain_hp = hp * .18 * score/100
        gain_nm = nm * .24 * score/100
        self.live.config(text=f"Estimation : {hp:.0f}ch/{nm:.0f}Nm → {hp+gain_hp:.0f}ch/{nm+gain_nm:.0f}Nm | +{gain_hp:.0f}ch +{gain_nm:.0f}Nm | confiance {score}%")

    def selected_map(self):
        if not self.maps:
            self.scan()
        idx = self.manual_idx.get() - 1
        if idx < 0 or idx >= len(self.maps):
            raise ValueError("Index map invalide")
        return self.maps[idx]

    def preview_manual(self):
        try:
            m = self.selected_map()
            self.manual_txt.delete("1.0", tk.END)
            self.manual_txt.insert(tk.END, f"{m.name} @ {hex(m.off)} {m.rows}x{m.cols}\n\n")
            for row in m.grid():
                self.manual_txt.insert(tk.END, " ".join(f"{v:6d}" for v in row) + "\n")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def apply_op(self, old):
        v = self.manual_val.get()
        op = self.manual_op.get()
        if op == "%": return old * (1 + v/100)
        if op == "+": return old + v
        if op == "-": return old - v
        if op == "*": return old * v
        if op == "/":
            if v == 0: raise ValueError("Division par zéro")
            return old / v
        if op == "set": return v
        return old

    def save_output(self, data, changes, tag):
        base = os.path.splitext(os.path.basename(self.file))[0]
        mode = "APPLY" if self.apply_real.get() else "DRYRUN"
        out = os.path.join(OUT, f"{base}_{tag}_{mode}_{now()}.bin")
        rep = os.path.join(REP, f"{base}_{tag}_{mode}_{now()}.csv")
        with open(out, "wb") as f:
            f.write(data if self.apply_real.get() else self.data)
        with open(rep, "w", newline="", encoding="utf-8") as f:
            if changes:
                w = csv.DictWriter(f, fieldnames=changes[0].keys())
                w.writeheader()
                w.writerows(changes)
        messagebox.showinfo("OK", f"Fichier : {out}\nRapport : {rep}\nChangements : {len(changes)}")

    def modify_manual(self):
        try:
            m = self.selected_map()
            data = bytearray(self.data)
            changes = []
            for i, old in enumerate(m.vals):
                new = self.apply_op(old)
                off = m.off + i*2
                w16(data, off, new)
                if int(old) != int(new):
                    changes.append({"map": m.name, "offset": hex(off), "old": old, "new": int(new)})
            self.save_output(data, changes, "manual")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def smooth_manual(self):
        try:
            m = self.selected_map()
            data = bytearray(self.data)
            old_grid = m.grid()
            new_grid = smooth_grid(old_grid)
            changes = []
            for r in range(m.rows):
                for c in range(m.cols):
                    old = old_grid[r][c]
                    new = new_grid[r][c]
                    off = m.off + (r*m.cols+c)*2
                    w16(data, off, new)
                    if old != new:
                        changes.append({"map": m.name, "offset": hex(off), "old": old, "new": new})
            self.save_output(data, changes, "smooth")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def generate_auto(self):
        if not self.maps:
            self.scan()
        score, status, missing, alerts = analyse_viability(self.maps, self.stage.get())
        if score < 55 and self.apply_real.get():
            messagebox.showerror("Bloqué", "Score trop faible pour APPLY")
            return

        data = bytearray(self.data)
        changes = []
        caps = {
            "Driver wish": 4200,
            "Torque limiter": 3500,
            "Smoke limiter": 6500,
            "Boost target": 2200,
            "Boost limiter": 2400,
            "Duration": 10000,
        }

        for m in self.maps:
            if m.name not in caps or m.conf < .74:
                continue
            grid = m.grid()
            new_grid = []
            for row in grid:
                nr = []
                for old in row:
                    if m.name in ["Driver wish", "Torque limiter"]:
                        new = old * 1.025
                    elif m.name == "Smoke limiter":
                        new = old + 90
                    elif m.name in ["Boost target", "Boost limiter"]:
                        new = old + 60
                    elif m.name == "Duration":
                        new = old * 1.015
                    else:
                        new = old
                    nr.append(min(caps[m.name], int(round(new))))
                new_grid.append(nr)

            new_grid = smooth_grid(new_grid)
            for r in range(m.rows):
                for c in range(m.cols):
                    old = grid[r][c]
                    new = new_grid[r][c]
                    off = m.off + (r*m.cols+c)*2
                    w16(data, off, new)
                    if old != new:
                        changes.append({"map": m.name, "offset": hex(off), "old": old, "new": new})

        self.save_output(data, changes, "auto")

    def export_maps(self):
        if not self.maps:
            self.scan()
        out = os.path.join(REP, f"maps_detectees_{now()}.csv")
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["index", "map", "offset", "rows", "cols", "confidence", "min", "max", "reason"])
            for i, m in enumerate(self.maps, 1):
                w.writerow([i, m.name, hex(m.off), m.rows, m.cols, m.conf, min(m.vals), max(m.vals), m.reason])
        messagebox.showinfo("Export", out)

    def export_report(self):
        self.export_maps()

    def refresh_base(self):
        self.base_txt.delete("1.0", tk.END)
        for d in ["base_stock", "base_mod", "base_gold", "cartos_creees", "rapports"]:
            count = len([x for x in os.listdir(d)]) if os.path.exists(d) else 0
            self.base_txt.insert(tk.END, f"{d} : {count} fichiers\n")

root = tk.Tk()
App(root)
root.mainloop()
