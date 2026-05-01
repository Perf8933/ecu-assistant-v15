import os, csv, json, time, struct, hashlib
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP = "ECU Assistant V15 PRO"
OUT_DIR = "cartos_creees"
REP_DIR = "rapports"
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(REP_DIR, exist_ok=True)

def now():
    return time.strftime("%Y%m%d_%H%M%S")

def sha1(data):
    return hashlib.sha1(data).hexdigest()

def u16(data, off):
    return struct.unpack_from(">H", data, off)[0]

def w16(data, off, val):
    val = max(0, min(65535, int(round(val))))
    struct.pack_into(">H", data, off, val)

class Map:
    def __init__(self, kind, off, rows, cols, conf, vals, reason):
        self.kind = kind
        self.off = off
        self.rows = rows
        self.cols = cols
        self.conf = conf
        self.vals = vals
        self.reason = reason

    def grid(self):
        return [self.vals[i*self.cols:(i+1)*self.cols] for i in range(self.rows)]

def metrics(vals, rows, cols):
    mn, mx = min(vals), max(vals)
    rng = max(1, mx - mn)
    jumps, inc, dec, total = [], 0, 0, 0

    for r in range(rows):
        for c in range(cols - 1):
            a, b = vals[r*cols+c], vals[r*cols+c+1]
            jumps.append(abs(b-a)/rng)
            inc += b >= a
            dec += b <= a
            total += 1

    for r in range(rows - 1):
        for c in range(cols):
            a, b = vals[r*cols+c], vals[(r+1)*cols+c]
            jumps.append(abs(b-a)/rng)
            inc += b >= a
            dec += b <= a
            total += 1

    smooth = max(0, 1 - (sum(jumps)/len(jumps) if jumps else 1))
    mono = max(inc, dec) / total if total else 0
    return smooth, mono

def classify(vals, rows, cols):
    mn, mx = min(vals), max(vals)
    avg = sum(vals) / len(vals)
    zeros = vals.count(0)
    smooth, mono = metrics(vals, rows, cols)
    out = []

    if 850 <= mn <= 1700 and 1600 <= mx <= 2300 and smooth > .55:
        out.append(("boost_target", .80, "pression turbo probable"))

    if 1800 <= mn <= 7000 and mx <= 8500 and avg > 2500:
        out.append(("boost_limiter", .76, "limiteur pression probable"))

    if 1000 <= mn <= 2600 and 4200 <= mx <= 7200 and smooth > .45:
        out.append(("smoke_limiter", .82, "smoke / air limiter probable"))

    if zeros >= 2 and 2200 <= mx <= 3900 and smooth > .30:
        out.append(("torque_limiter", .80, "limiteur couple probable"))

    if zeros >= 3 and 3000 <= mx <= 5000 and mono > .55:
        out.append(("driver_wish", .78, "driver wish probable"))

    if 0 <= mn <= 1000 and 6000 <= mx <= 12000 and smooth > .35:
        out.append(("duration", .74, "duration injection probable"))

    if mn <= 300 and 5000 <= mx <= 9000 and mono > .45:
        out.append(("iq_to_torque", .72, "conversion IQ / couple probable"))

    if 2000 <= mn <= 8000 and 9000 <= mx <= 20000:
        out.append(("rail_pressure", .68, "pression rail possible"))

    if not out and smooth > .72 and len(set(vals)) > 8:
        out.append(("unknown_smooth_map", .50, "map lisse inconnue"))

    return out

def scan_maps(data):
    specs = [(16,12), (11,10), (4,20), (16,8), (8,8), (12,12), (1,16), (1,20)]
    maps = []
    for rows, cols in specs:
        size = rows * cols * 2
        for off in range(0, max(0, len(data)-size), 4):
            try:
                vals = [u16(data, off+i*2) for i in range(rows*cols)]
            except:
                continue
            if min(vals) == max(vals):
                continue
            for kind, conf, reason in classify(vals, rows, cols):
                maps.append(Map(kind, off, rows, cols, conf, vals, reason))
            if len(maps) > 450:
                break
    maps.sort(key=lambda m: m.conf, reverse=True)

    clean, seen = [], set()
    for m in maps:
        key = (m.kind, m.off // 16)
        if key not in seen:
            seen.add(key)
            clean.append(m)
    return clean[:250]

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
                out[r][c] = round(grid[r][c]*(1-strength) + (sum(vals)/len(vals))*strength)
    return out

def viability(maps, goal):
    found = {m.kind for m in maps if m.conf >= .70}

    req = {
        "stage1": {"driver_wish", "torque_limiter", "smoke_limiter", "boost_target"},
        "stage1plus": {"driver_wish", "torque_limiter", "smoke_limiter", "boost_target", "boost_limiter"},
        "stage2": {"driver_wish", "torque_limiter", "smoke_limiter", "boost_target", "boost_limiter", "duration"},
    }[goal]

    missing = sorted(req - found)
    score = 100 - len(missing)*22

    warnings = []
    if "boost_target" in found and "smoke_limiter" not in found:
        score -= 15
        warnings.append("Boost trouvé mais smoke absent")
    if "duration" in found and "smoke_limiter" not in found:
        score -= 15
        warnings.append("Duration trouvée sans smoke")
    if "torque_limiter" in found and "driver_wish" not in found:
        score -= 8
        warnings.append("Torque sans Driver Wish")

    score = max(0, min(100, score))

    if score >= 80 and not missing:
        status = "OK viable"
    elif score >= 55:
        status = "DOUTEUX / manuel conseillé"
    else:
        status = "NON VIABLE en auto"

    return score, status, missing, warnings

class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP)
        self.file = ""
        self.data = None
        self.maps = []

        self.stock_hp = tk.DoubleVar(value=105)
        self.stock_nm = tk.DoubleVar(value=250)
        self.stage = tk.IntVar(value=50)
        self.apply_real = tk.BooleanVar(value=False)

        self.build()

    def build(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True)

        self.tab_main = ttk.Frame(nb)
        self.tab_auto = ttk.Frame(nb)
        self.tab_manual = ttk.Frame(nb)
        self.tab_maps = ttk.Frame(nb)

        nb.add(self.tab_main, text="Projet")
        nb.add(self.tab_auto, text="Auto")
        nb.add(self.tab_manual, text="Manuel")
        nb.add(self.tab_maps, text="Maps")

        self.build_main()
        self.build_auto()
        self.build_manual()
        self.build_maps()

    def build_main(self):
        ttk.Label(self.tab_main, text="ECU Assistant V15 PRO", font=("Arial", 18, "bold")).pack(pady=10)

        self.entry = ttk.Entry(self.tab_main, width=90)
        self.entry.pack(pady=5)

        ttk.Button(self.tab_main, text="Importer carto", command=self.import_file).pack(pady=5)
        ttk.Button(self.tab_main, text="Scanner IA", command=self.scan).pack(pady=5)

        f = ttk.Frame(self.tab_main)
        f.pack(pady=5)
        ttk.Label(f, text="Puissance stock ch").grid(row=0, column=0)
        ttk.Entry(f, textvariable=self.stock_hp, width=8).grid(row=0, column=1)
        ttk.Label(f, text="Couple stock Nm").grid(row=0, column=2)
        ttk.Entry(f, textvariable=self.stock_nm, width=8).grid(row=0, column=3)

        self.live = ttk.Label(self.tab_main, text="", font=("Arial", 12, "bold"))
        self.live.pack(pady=10)

        self.log = tk.Text(self.tab_main, height=22, width=110)
        self.log.pack(padx=10, pady=10)

    def build_auto(self):
        ttk.Label(self.tab_auto, text="Mode Auto intelligent", font=("Arial", 16, "bold")).pack(pady=10)

        ttk.Label(self.tab_auto, text="Curseur stage : 0 stock / 50 stage1 / 75 stage1+ / 100 stage2").pack()
        ttk.Scale(self.tab_auto, from_=0, to=100, variable=self.stage, command=lambda e: self.update_gain()).pack(fill="x", padx=20)

        ttk.Checkbutton(self.tab_auto, text="Appliquer réellement (sinon DRY-RUN)", variable=self.apply_real).pack(pady=5)

        ttk.Button(self.tab_auto, text="Analyse Stage 1", command=lambda: self.analyse_goal("stage1")).pack(pady=3)
        ttk.Button(self.tab_auto, text="Analyse Stage 1+", command=lambda: self.analyse_goal("stage1plus")).pack(pady=3)
        ttk.Button(self.tab_auto, text="Analyse Stage 2 light", command=lambda: self.analyse_goal("stage2")).pack(pady=3)
        ttk.Button(self.tab_auto, text="Générer proposition AUTO", command=self.generate_auto).pack(pady=10)

        self.auto_text = tk.Text(self.tab_auto, height=28, width=110)
        self.auto_text.pack(padx=10, pady=10)

    def build_manual(self):
        ttk.Label(self.tab_manual, text="Mode Manuel", font=("Arial", 16, "bold")).pack(pady=10)

        f = ttk.Frame(self.tab_manual)
        f.pack(pady=5)

        self.map_index = tk.IntVar(value=1)
        self.op = tk.StringVar(value="pourcentage")
        self.val = tk.DoubleVar(value=2.0)
        self.manual_apply = tk.BooleanVar(value=False)

        ttk.Label(f, text="Index map").grid(row=0, column=0)
        ttk.Entry(f, textvariable=self.map_index, width=6).grid(row=0, column=1)
        ttk.Label(f, text="Opération").grid(row=0, column=2)
        ttk.Combobox(f, textvariable=self.op, values=["pourcentage", "addition", "soustraction", "multiplication", "division", "set"], width=15).grid(row=0, column=3)
        ttk.Label(f, text="Valeur").grid(row=0, column=4)
        ttk.Entry(f, textvariable=self.val, width=8).grid(row=0, column=5)

        ttk.Checkbutton(self.tab_manual, text="Appliquer réellement", variable=self.manual_apply).pack()
        ttk.Button(self.tab_manual, text="Prévisualiser map", command=self.preview_map).pack(pady=3)
        ttk.Button(self.tab_manual, text="Modifier map", command=self.modify_manual).pack(pady=3)
        ttk.Button(self.tab_manual, text="Lisser map", command=self.smooth_manual).pack(pady=3)

        self.manual_text = tk.Text(self.tab_manual, height=30, width=110)
        self.manual_text.pack(padx=10, pady=10)

    def build_maps(self):
        ttk.Button(self.tab_maps, text="Exporter liste maps CSV", command=self.export_maps).pack(pady=8)
        self.maps_text = tk.Text(self.tab_maps, height=35, width=120)
        self.maps_text.pack(padx=10, pady=10)

    def import_file(self):
        self.file = filedialog.askopenfilename()
        if not self.file:
            return
        self.entry.delete(0, tk.END)
        self.entry.insert(0, self.file)
        with open(self.file, "rb") as f:
            self.data = f.read()
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
        self.maps_text.delete("1.0", tk.END)
        for i, m in enumerate(self.maps, 1):
            line = f"{i:03d} | {m.kind} | offset {hex(m.off)} | {m.rows}x{m.cols} | conf {m.conf} | min {min(m.vals)} max {max(m.vals)} | {m.reason}\n"
            self.maps_text.insert(tk.END, line)
        self.update_gain()

    def update_gain(self):
        if not hasattr(self, "live"):
            return
        score = 50
        if self.maps:
            score, _, _, _ = viability(self.maps, "stage1")
        st = self.stage.get()
        hp = self.stock_hp.get()
        nm = self.stock_nm.get()

        hp_gain = hp * (0.18 * st/50) * (score/100)
        nm_gain = nm * (0.24 * st/50) * (score/100)

        self.live.config(text=f"Estimation live : {hp:.0f}ch/{nm:.0f}Nm → {hp+hp_gain:.0f}ch/{nm+nm_gain:.0f}Nm | +{hp_gain:.0f}ch +{nm_gain:.0f}Nm | confiance {score}%")

    def analyse_goal(self, goal):
        if not self.maps:
            self.scan()
        score, status, missing, warnings = viability(self.maps, goal)
        self.auto_text.delete("1.0", tk.END)
        self.auto_text.insert(tk.END, f"Objectif : {goal}\nScore : {score}/100\nStatut : {status}\n")
        self.auto_text.insert(tk.END, f"Maps manquantes : {missing}\n")
        self.auto_text.insert(tk.END, f"Alertes : {warnings}\n")
        self.update_gain()

    def selected_map(self):
        if not self.maps:
            self.scan()
        idx = self.map_index.get() - 1
        if idx < 0 or idx >= len(self.maps):
            raise ValueError("Index map invalide")
        return self.maps[idx]

    def preview_map(self):
        try:
            m = self.selected_map()
            self.manual_text.delete("1.0", tk.END)
            self.manual_text.insert(tk.END, f"{m.kind} @ {hex(m.off)} {m.rows}x{m.cols}\n\n")
            for r in m.grid():
                self.manual_text.insert(tk.END, " ".join(f"{v:6d}" for v in r) + "\n")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def apply_op(self, old):
        v = self.val.get()
        if self.op.get() == "pourcentage":
            return old * (1 + v/100)
        if self.op.get() == "addition":
            return old + v
        if self.op.get() == "soustraction":
            return old - v
        if self.op.get() == "multiplication":
            return old * v
        if self.op.get() == "division":
            if v == 0:
                raise ValueError("Division par zéro")
            return old / v
        if self.op.get() == "set":
            return v
        return old

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
                    changes.append({"offset": hex(off), "old": old, "new": int(new), "map": m.kind})
            self.save_output(data, changes, "manual", self.manual_apply.get())
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
                        changes.append({"offset": hex(off), "old": old, "new": new, "map": m.kind})
            self.save_output(data, changes, "smooth", self.manual_apply.get())
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def generate_auto(self):
        if not self.maps:
            self.scan()

        score, status, missing, warnings = viability(self.maps, "stage1")
        if score < 55 and self.apply_real.get():
            messagebox.showerror("Bloqué", "Score trop faible pour appliquer automatiquement")
            return

        data = bytearray(self.data)
        changes = []
        level = self.stage.get() / 100

        caps = {
            "driver_wish": 4200,
            "torque_limiter": 3500,
            "smoke_limiter": 6500,
            "boost_target": 2200,
            "boost_limiter": 2400,
            "duration": 10000,
        }

        for m in self.maps[:40]:
            if m.kind not in caps or m.conf < .74:
                continue
            grid = m.grid()
            new_grid = []
            for row in grid:
                nr = []
                for old in row:
                    if m.kind in ["driver_wish", "torque_limiter"]:
                        new = old * (1 + 0.05 * level)
                    elif m.kind == "smoke_limiter":
                        new = old + 180 * level
                    elif m.kind in ["boost_target", "boost_limiter"]:
                        new = old + 120 * level
                    elif m.kind == "duration":
                        new = old * (1 + 0.025 * level)
                    else:
                        new = old
                    nr.append(min(caps[m.kind], int(round(new))))
                new_grid.append(nr)

            new_grid = smooth_grid(new_grid)

            for r in range(m.rows):
                for c in range(m.cols):
                    old = grid[r][c]
                    new = new_grid[r][c]
                    off = m.off + (r*m.cols+c)*2
                    w16(data, off, new)
                    if old != new:
                        changes.append({"offset": hex(off), "old": old, "new": new, "map": m.kind})

        self.save_output(data, changes, "auto_stage", self.apply_real.get())

    def save_output(self, data, changes, tag, apply):
        base = os.path.splitext(os.path.basename(self.file))[0]
        mode = "APPLY" if apply else "DRYRUN"
        out = os.path.join(OUT_DIR, f"{base}_{tag}_{mode}_{now()}.bin")
        rep = os.path.join(REP_DIR, f"{base}_{tag}_{mode}_{now()}.csv")

        with open(out, "wb") as f:
            f.write(data if apply else self.data)

        with open(rep, "w", newline="", encoding="utf-8") as f:
            if changes:
                w = csv.DictWriter(f, fieldnames=changes[0].keys())
                w.writeheader()
                w.writerows(changes)

        messagebox.showinfo("OK", f"Fichier : {out}\nRapport : {rep}\nChangements : {len(changes)}")

    def export_maps(self):
        if not self.maps:
            self.scan()
        out = os.path.join(REP_DIR, f"maps_detectees_{now()}.csv")
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["index", "kind", "offset", "rows", "cols", "confidence", "min", "max", "avg", "reason"])
            for i, m in enumerate(self.maps, 1):
                w.writerow([i, m.kind, hex(m.off), m.rows, m.cols, m.conf, min(m.vals), max(m.vals), sum(m.vals)/len(m.vals), m.reason])
        messagebox.showinfo("Export", out)

root = tk.Tk()
root.geometry("1050x720")
App(root)
root.mainloop()
