import os
import csv
import json
import time
import math
import shutil
import struct
import hashlib
import zipfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_NAME = "ECU Assistant V18 Ultra Pro IA"

DIRS = {
    "outputs": "cartos_creees",
    "reports": "rapports",
    "logs": "logs",
    "gold": "base_gold",
    "stock": "base_stock",
    "mod": "base_mod",
    "chinese": "base_chinoise",
    "valid": "mods_valides",
    "suspect": "mods_douteux",
    "reject": "mods_rejetes",
    "learning": "learning_db",
    "imports": "imports",
    "projects": "projets_clients",
    "visuals": "visualisations",
}

for d in DIRS.values():
    os.makedirs(d, exist_ok=True)

MAP_TYPES = [
    "Driver wish",
    "Torque limiter",
    "Smoke limiter",
    "Boost target",
    "Boost limiter",
    "Duration",
    "Rail pressure",
    "IQ to torque",
    "N75 / VNT",
    "SOI",
    "Unknown smooth map",
]

VEHICLE_BRANDS = [
    "Volkswagen", "Seat", "Skoda", "Audi",
    "BMW", "Mercedes", "Peugeot", "Citroen", "Renault",
    "Toyota", "Honda", "Mitsubishi", "Alfa Romeo",
    "Chevrolet", "Dodge", "Land Rover", "Unknown"
]

ECU_TYPES = [
    "EDC15", "EDC16", "EDC16U31", "EDC16U34",
    "EDC17", "ME7", "ME7.5", "MED9", "MED17",
    "Denso", "Siemens", "Delphi", "Marelli", "Unknown"
]


def now():
    return time.strftime("%Y%m%d_%H%M%S")


def sha1_bytes(data):
    return hashlib.sha1(data).hexdigest()


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_name(text):
    text = text.replace(" ", "_").replace("/", "_").replace("\\", "_")
    return "".join(c for c in text if c.isalnum() or c in "_-.+")[:150] or "file"


def copy_to(src, folder):
    os.makedirs(folder, exist_ok=True)
    name = os.path.basename(src)
    dst = os.path.join(folder, name)

    if os.path.exists(dst):
        base, ext = os.path.splitext(name)
        dst = os.path.join(folder, f"{base}_{now()}{ext}")

    shutil.copy2(src, dst)
    return dst


def read_bin(path):
    with open(path, "rb") as f:
        data = f.read()
    if not data:
        raise ValueError("Fichier vide")
    return data


def u16(data, off, signed=False):
    return struct.unpack_from(">h" if signed else ">H", data, off)[0]


def w16(data, off, val, signed=False):
    if signed:
        val = max(-32768, min(32767, int(round(val))))
        struct.pack_into(">h", data, off, val)
    else:
        val = max(0, min(65535, int(round(val))))
        struct.pack_into(">H", data, off, val)


def detect_role_from_name(name):
    u = name.upper()

    if any(x in u for x in ["ORI", "ORIGINAL", "STOCK", "READ", "OEM"]):
        return "stock"

    if any(x in u for x in ["GOLD", "SAFE", "VALID"]):
        return "gold"

    if any(x in u for x in ["CHINA", "CHINESE", "KESS", "KSUTE", "DIMS"]):
        return "chinese"

    if any(x in u for x in ["MOD", "STAGE", "STG", "+5", "+10", "TUN", "MIX", "HARD", "POP", "BANG", "CUT"]):
        return "mod"

    return "unknown"


def detect_brand_from_name(name):
    u = name.upper()

    tests = {
        "Volkswagen": ["VW", "VOLKSWAGEN", "GOLF", "PASSAT", "POLO", "BORA", "CADDY"],
        "Seat": ["SEAT", "ALTEA", "LEON", "IBIZA", "ALHAMBRA"],
        "Skoda": ["SKODA", "OCTAVIA", "FABIA", "SUPERB"],
        "Audi": ["AUDI", "A3", "A4", "A6", "TT"],
        "Toyota": ["TOYOTA", "HILUX", "YARIS", "COROLLA"],
        "Honda": ["HONDA", "CIVIC", "ACCORD"],
        "Mitsubishi": ["MITSUBISHI", "LANCER"],
        "Alfa Romeo": ["ALFA"],
        "Chevrolet": ["CHEVROLET"],
        "Dodge": ["DODGE"],
        "Land Rover": ["LAND", "ROVER"],
    }

    for brand, tokens in tests.items():
        if any(t in u for t in tokens):
            return brand

    return "Unknown"


def detect_ecu_from_name_or_size(name, size):
    u = name.upper()

    for ecu in ECU_TYPES:
        if ecu != "Unknown" and ecu.upper() in u:
            return ecu

    if 240000 <= size <= 270000:
        return "EDC15 / ME7 probable"
    if 500000 <= size <= 560000:
        return "EDC16 512k probable"
    if 1000000 <= size <= 1100000:
        return "EDC16 1MB probable"
    if 1900000 <= size <= 2200000:
        return "EDC17 / MED 2MB probable"

    return "Unknown"


def diff_stats(stock, mod):
    if len(stock) != len(mod):
        return {
            "same_size": False,
            "diff_bytes": "",
            "diff_ratio": "",
            "blocks": "",
            "largest_block": "",
        }

    diff = 0
    blocks = 0
    largest = 0
    cur = 0
    in_block = False

    for a, b in zip(stock, mod):
        if a != b:
            diff += 1
            cur += 1
            if not in_block:
                blocks += 1
                in_block = True
        else:
            if in_block:
                largest = max(largest, cur)
                cur = 0
            in_block = False

    largest = max(largest, cur)

    return {
        "same_size": True,
        "diff_bytes": diff,
        "diff_ratio": round(diff / max(1, len(stock)), 6),
        "blocks": blocks,
        "largest_block": largest,
    }


def score_mod_quality(stock_data, mod_data, mod_name):
    stats = diff_stats(stock_data, mod_data)
    score = 100
    reasons = []

    if not stats["same_size"]:
        return 0, "REJET", "taille différente", stats

    ratio = stats["diff_ratio"]
    blocks = stats["blocks"]
    largest = stats["largest_block"]

    if ratio == 0:
        score -= 85
        reasons.append("aucune différence")

    if ratio > 0.10:
        score -= 55
        reasons.append("énorme quantité de différences")
    elif ratio > 0.06:
        score -= 35
        reasons.append("beaucoup de différences")
    elif ratio > 0.035:
        score -= 18
        reasons.append("diff élevé")
    elif ratio < 0.00003:
        score -= 18
        reasons.append("trop peu de différences")

    if blocks > 5000:
        score -= 35
        reasons.append("trop de blocs modifiés")
    elif blocks > 3000:
        score -= 20
        reasons.append("beaucoup de blocs modifiés")

    if largest > len(stock_data) * 0.15:
        score -= 35
        reasons.append("très gros bloc continu modifié")
    elif largest > len(stock_data) * 0.08:
        score -= 18
        reasons.append("gros bloc continu modifié")

    name = mod_name.upper()

    if "MIX" in name:
        score -= 25
        reasons.append("MIX suspect")

    if "UNKNOWN" in name or "TEST" in name:
        score -= 10
        reasons.append("nom peu fiable")

    wild = 0
    tested = 0
    extreme = 0

    limit = min(len(stock_data), len(mod_data), 450000)

    for off in range(0, limit - 2, 2):
        if stock_data[off:off+2] == mod_data[off:off+2]:
            continue

        try:
            a = u16(stock_data, off)
            b = u16(mod_data, off)
        except Exception:
            continue

        if a > 0:
            delta = abs((b - a) / a)

            if delta > 0.50:
                wild += 1
            if delta > 2.0:
                extreme += 1

            tested += 1

        if tested >= 7000:
            break

    if tested:
        wild_ratio = wild / tested
        extreme_ratio = extreme / tested

        if extreme_ratio > 0.02:
            score -= 35
            reasons.append("deltas extrêmes détectés")

        if wild_ratio > 0.20:
            score -= 35
            reasons.append("beaucoup de deltas >50%")
        elif wild_ratio > 0.08:
            score -= 18
            reasons.append("quelques deltas forts")

    score = max(0, min(100, score))

    if score >= 82:
        bucket = "VALIDE"
    elif score >= 58:
        bucket = "DOUTEUX"
    else:
        bucket = "REJET"

    return score, bucket, " | ".join(reasons), stats


class MapCandidate:
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

    def min(self):
        return min(self.vals)

    def max(self):
        return max(self.vals)

    def avg(self):
        return sum(self.vals) / len(self.vals)


def map_smoothness(vals, rows, cols):
    mn, mx = min(vals), max(vals)
    rng = max(1, mx - mn)
    jumps = []

    for r in range(rows):
        for c in range(cols - 1):
            jumps.append(abs(vals[r*cols+c+1] - vals[r*cols+c]) / rng)

    for r in range(rows - 1):
        for c in range(cols):
            jumps.append(abs(vals[(r+1)*cols+c] - vals[r*cols+c]) / rng)

    return max(0, 1 - (sum(jumps) / len(jumps) if jumps else 1))


def map_monotonicity(vals, rows, cols):
    inc = 0
    dec = 0
    total = 0

    for r in range(rows):
        for c in range(cols - 1):
            a = vals[r*cols+c]
            b = vals[r*cols+c+1]
            if b >= a:
                inc += 1
            if b <= a:
                dec += 1
            total += 1

    for r in range(rows - 1):
        for c in range(cols):
            a = vals[r*cols+c]
            b = vals[(r+1)*cols+c]
            if b >= a:
                inc += 1
            if b <= a:
                dec += 1
            total += 1

    if not total:
        return 0

    return max(inc, dec) / total


def classify_map(vals, rows, cols):
    mn = min(vals)
    mx = max(vals)
    avg = sum(vals) / len(vals)
    zeros = vals.count(0)
    smooth = map_smoothness(vals, rows, cols)
    mono = map_monotonicity(vals, rows, cols)

    out = []

    if 850 <= mn <= 1700 and 1600 <= mx <= 2350 and smooth > .55:
        out.append(("Boost target", .86, "pression turbo probable"))

    if 1800 <= mn <= 7200 and 2200 <= mx <= 8800 and avg > 2500:
        out.append(("Boost limiter", .80, "limiteur turbo probable"))

    if 1000 <= mn <= 2800 and 4200 <= mx <= 7800 and smooth > .40:
        out.append(("Smoke limiter", .87, "smoke / air limiter probable"))

    if zeros >= 2 and 2200 <= mx <= 4300 and smooth > .25:
        out.append(("Torque limiter", .85, "limiteur couple probable"))

    if zeros >= 3 and 2800 <= mx <= 5400 and mono > .45:
        out.append(("Driver wish", .82, "demande pédale probable"))

    if 0 <= mn <= 1000 and 6000 <= mx <= 13000 and smooth > .30:
        out.append(("Duration", .78, "temps injection probable"))

    if 2000 <= mn <= 9000 and 9000 <= mx <= 22000:
        out.append(("Rail pressure", .72, "pression rail possible"))

    if 0 <= mn <= 1000 and 7000 <= mx <= 11000 and smooth > .30:
        out.append(("N75 / VNT", .68, "commande turbo possible"))

    if not out and smooth > .76 and len(set(vals)) > 12:
        out.append(("Unknown smooth map", .55, "map lisse inconnue"))

    return out
  def scan_maps(data):
    specs = [
        (16, 12),
        (11, 10),
        (4, 20),
        (16, 8),
        (12, 12),
        (8, 8),
        (10, 16),
        (6, 16),
        (1, 16),
        (1, 20),
    ]

    found = []

    for rows, cols in specs:
        size = rows * cols * 2

        for off in range(0, max(0, len(data) - size), 4):
            try:
                vals = [u16(data, off+i*2) for i in range(rows*cols)]
            except Exception:
                continue

            if min(vals) == max(vals):
                continue

            for name, conf, reason in classify_map(vals, rows, cols):
                found.append(MapCandidate(name, off, rows, cols, vals, conf, reason))

            if len(found) > 900:
                break

    clean = []
    seen = set()

    for m in sorted(found, key=lambda x: x.conf, reverse=True):
        key = (m.name, m.off // 16)

        if key not in seen:
            seen.add(key)
            clean.append(m)

    return clean[:450]


def analyse_viability(maps, level):
    names = {m.name for m in maps if m.conf >= .70}

    required = {"Driver wish", "Torque limiter", "Smoke limiter", "Boost target"}

    if level in ["Stage 1+", "Stage 2 light"]:
        required.add("Boost limiter")

    if level == "Stage 2 light":
        required.add("Duration")

    missing = sorted(required - names)
    score = max(0, 100 - len(missing) * 22)
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

    if "N75 / VNT" in names:
        alerts.append("N75/VNT détecté : modification auto déconseillée sans logs")

    score = max(0, min(100, score))

    if score >= 80 and not missing:
        status = "OK viable"
    elif score >= 55:
        status = "DOUTEUX / manuel conseillé"
    else:
        status = "NON VIABLE auto"

    return score, status, missing, alerts


def smooth_grid(grid, strength=.35):
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
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


def estimate_gain(stock_hp, stock_nm, score, level):
    level_factor = {
        "Stage 1": (0.18, 0.24),
        "Stage 1+": (0.24, 0.32),
        "Stage 2 light": (0.30, 0.40),
    }.get(level, (0.18, 0.24))

    confidence = max(.25, min(1.0, score / 100))

    hp_gain = stock_hp * level_factor[0] * confidence
    nm_gain = stock_nm * level_factor[1] * confidence

    risk = "faible" if score >= 80 and level == "Stage 1" else ("moyen" if score >= 60 else "élevé")

    return {
        "hp_est": round(stock_hp + hp_gain, 1),
        "nm_est": round(stock_nm + nm_gain, 1),
        "hp_gain": round(hp_gain, 1),
        "nm_gain": round(nm_gain, 1),
        "confidence": round(score, 1),
        "risk": risk,
    }


def write_rows_csv(path, rows):
    if not rows:
        with open(path, "w", encoding="utf-8") as f:
            f.write("empty\n")
        return

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1450x900")

        self.file = ""
        self.data = None
        self.maps = []

        self.brand = tk.StringVar(value="Volkswagen")
        self.ecu = tk.StringVar(value="EDC16")
        self.engine = tk.StringVar(value="1.9TDI")
        self.stage = tk.StringVar(value="Stage 1")
        self.stock_hp = tk.DoubleVar(value=105)
        self.stock_nm = tk.DoubleVar(value=250)
        self.apply_real = tk.BooleanVar(value=False)

        self.manual_idx = tk.IntVar(value=1)
        self.manual_op = tk.StringVar(value="%")
        self.manual_val = tk.DoubleVar(value=2.0)

        self.build()

    def build(self):
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=8, pady=6)

        ttk.Label(top, text="ECU Assistant V18 Ultra Pro IA", font=("Arial", 22, "bold")).pack(side="left")
        ttk.Label(top, text="Auto + manuel + apprentissage + tri base + scoring mods", font=("Arial", 10)).pack(side="left", padx=12)

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        self.t_project = ttk.Frame(nb)
        self.t_auto = ttk.Frame(nb)
        self.t_manual = ttk.Frame(nb)
        self.t_maps = ttk.Frame(nb)
        self.t_learning = ttk.Frame(nb)
        self.t_database = ttk.Frame(nb)
        self.t_reports = ttk.Frame(nb)

        nb.add(self.t_project, text="Projet")
        nb.add(self.t_auto, text="Auto")
        nb.add(self.t_manual, text="Manuel")
        nb.add(self.t_maps, text="Maps")
        nb.add(self.t_learning, text="Apprentissage IA")
        nb.add(self.t_database, text="Base")
        nb.add(self.t_reports, text="Rapports")

        self.build_project()
        self.build_auto()
        self.build_manual()
        self.build_maps()
        self.build_learning()
        self.build_database()
        self.build_reports()

        bottom = ttk.LabelFrame(self.root, text="Estimation live")
        bottom.pack(fill="x", padx=8, pady=6)

        self.live = ttk.Label(bottom, text="", font=("Arial", 12, "bold"))
        self.live.pack(anchor="w", padx=8, pady=4)

        self.update_gain()

    def build_project(self):
        ttk.Label(self.t_project, text="Projet véhicule / carto", font=("Arial", 18, "bold")).pack(pady=8)

        vehicle = ttk.LabelFrame(self.t_project, text="Véhicule")
        vehicle.pack(fill="x", padx=10, pady=6)

        row = ttk.Frame(vehicle)
        row.pack(fill="x", padx=8, pady=6)

        ttk.Label(row, text="Marque").pack(side="left")
        ttk.Combobox(row, textvariable=self.brand, values=VEHICLE_BRANDS, width=18).pack(side="left", padx=5)

        ttk.Label(row, text="ECU").pack(side="left")
        ttk.Combobox(row, textvariable=self.ecu, values=ECU_TYPES, width=18).pack(side="left", padx=5)

        ttk.Label(row, text="Moteur").pack(side="left")
        ttk.Entry(row, textvariable=self.engine, width=18).pack(side="left", padx=5)

        ttk.Label(row, text="Puissance stock").pack(side="left")
        ttk.Entry(row, textvariable=self.stock_hp, width=8).pack(side="left", padx=5)

        ttk.Label(row, text="Couple stock").pack(side="left")
        ttk.Entry(row, textvariable=self.stock_nm, width=8).pack(side="left", padx=5)

        filebox = ttk.LabelFrame(self.t_project, text="Carto à analyser/modifier")
        filebox.pack(fill="x", padx=10, pady=6)

        self.path_entry = ttk.Entry(filebox, width=130)
        self.path_entry.pack(side="left", fill="x", expand=True, padx=8, pady=8)

        ttk.Button(filebox, text="Importer carto", command=self.import_file).pack(side="left", padx=5)
        ttk.Button(filebox, text="Scan IA complet", command=self.scan).pack(side="left", padx=5)
        ttk.Button(filebox, text="Créer projet client", command=self.create_project).pack(side="left", padx=5)

        self.log = tk.Text(self.t_project, height=28)
        self.log.pack(fill="both", expand=True, padx=10, pady=10)

    def build_auto(self):
        ttk.Label(self.t_auto, text="Mode Auto intelligent", font=("Arial", 18, "bold")).pack(pady=8)

        row = ttk.Frame(self.t_auto)
        row.pack(pady=5)

        ttk.Label(row, text="Objectif").pack(side="left")
        ttk.Combobox(row, textvariable=self.stage, values=["Stage 1", "Stage 1+", "Stage 2 light"], state="readonly", width=16).pack(side="left", padx=5)

        ttk.Checkbutton(row, text="Appliquer réellement", variable=self.apply_real).pack(side="left", padx=8)

        ttk.Button(self.t_auto, text="Analyser viabilité", command=self.analyse_auto).pack(pady=5)
        ttk.Button(self.t_auto, text="Générer proposition AUTO", command=self.generate_auto).pack(pady=5)

        self.auto_txt = tk.Text(self.t_auto, height=34)
        self.auto_txt.pack(fill="both", expand=True, padx=10, pady=10)

    def build_manual(self):
        ttk.Label(self.t_manual, text="Mode Manuel ciblé", font=("Arial", 18, "bold")).pack(pady=8)

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

        self.manual_txt = tk.Text(self.t_manual, height=34)
        self.manual_txt.pack(fill="both", expand=True, padx=10, pady=10)
          def build_maps(self):
        ttk.Label(self.t_maps, text="Maps détectées", font=("Arial", 18, "bold")).pack(pady=8)

        row = ttk.Frame(self.t_maps)
        row.pack(pady=5)

        ttk.Button(row, text="Exporter maps CSV", command=self.export_maps).pack(side="left", padx=5)

        self.maps_txt = tk.Text(self.t_maps, height=36)
        self.maps_txt.pack(fill="both", expand=True, padx=10, pady=10)

    def build_learning(self):
        ttk.Label(self.t_learning, text="Apprentissage IA / tri des bases", font=("Arial", 18, "bold")).pack(pady=8)

        row = ttk.Frame(self.t_learning)
        row.pack(pady=5)

        ttk.Button(row, text="Importer stock", command=self.import_stock).pack(side="left", padx=5)
        ttk.Button(row, text="Importer mod", command=self.import_mod).pack(side="left", padx=5)
        ttk.Button(row, text="Importer golden", command=self.import_gold).pack(side="left", padx=5)
        ttk.Button(row, text="Importer pack ZIP", command=self.import_zip_pack).pack(side="left", padx=5)
        ttk.Button(row, text="Analyser / apprendre base", command=self.learn_base).pack(side="left", padx=5)

        self.learning_txt = tk.Text(self.t_learning, height=34)
        self.learning_txt.pack(fill="both", expand=True, padx=10, pady=10)

    def build_database(self):
        ttk.Label(self.t_database, text="Base locale", font=("Arial", 18, "bold")).pack(pady=8)

        row = ttk.Frame(self.t_database)
        row.pack(pady=5)

        ttk.Button(row, text="Rafraîchir base", command=self.refresh_base).pack(side="left", padx=5)
        ttk.Button(row, text="Ouvrir dossier logiciel", command=lambda: os.startfile(os.getcwd())).pack(side="left", padx=5)

        self.base_txt = tk.Text(self.t_database, height=34)
        self.base_txt.pack(fill="both", expand=True, padx=10, pady=10)

        self.refresh_base()

    def build_reports(self):
        ttk.Label(self.t_reports, text="Rapports / sorties", font=("Arial", 18, "bold")).pack(pady=8)

        row = ttk.Frame(self.t_reports)
        row.pack(pady=5)

        ttk.Button(row, text="Ouvrir rapports", command=lambda: os.startfile(DIRS["reports"])).pack(side="left", padx=5)
        ttk.Button(row, text="Ouvrir cartos créées", command=lambda: os.startfile(DIRS["outputs"])).pack(side="left", padx=5)
        ttk.Button(row, text="Ouvrir learning reports", command=lambda: os.startfile(DIRS["learning"])).pack(side="left", padx=5)

        self.reports_txt = tk.Text(self.t_reports, height=34)
        self.reports_txt.pack(fill="both", expand=True, padx=10, pady=10)

        self.refresh_reports()

    def import_file(self):
        self.file = filedialog.askopenfilename()

        if not self.file:
            return

        try:
            self.data = read_bin(self.file)
        except Exception as e:
            messagebox.showerror("Erreur", str(e))
            return

        self.path_entry.delete(0, tk.END)
        self.path_entry.insert(0, self.file)

        size = len(self.data)
        name = os.path.basename(self.file)
        brand = detect_brand_from_name(name)
        ecu = detect_ecu_from_name_or_size(name, size)

        self.brand.set(brand)
        self.ecu.set(ecu)

        self.log.insert(tk.END, f"Importé : {self.file}\n")
        self.log.insert(tk.END, f"Taille : {size} bytes\n")
        self.log.insert(tk.END, f"SHA1 : {sha1_bytes(self.data)}\n")
        self.log.insert(tk.END, f"Marque probable : {brand}\n")
        self.log.insert(tk.END, f"ECU probable : {ecu}\n\n")

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
            self.maps_txt.insert(
                tk.END,
                f"{i:03d} | {m.name} | {hex(m.off)} | {m.rows}x{m.cols} | conf {m.conf} | "
                f"min {m.min()} max {m.max()} avg {m.avg():.1f} | {m.reason}\n"
            )

        self.update_gain()

    def analyse_auto(self):
        if not self.maps:
            self.scan()

        score, status, missing, alerts = analyse_viability(self.maps, self.stage.get())
        est = estimate_gain(self.stock_hp.get(), self.stock_nm.get(), score, self.stage.get())

        self.auto_txt.delete("1.0", tk.END)
        self.auto_txt.insert(tk.END, f"Objectif : {self.stage.get()}\n")
        self.auto_txt.insert(tk.END, f"Score : {score}/100\n")
        self.auto_txt.insert(tk.END, f"Statut : {status}\n")
        self.auto_txt.insert(tk.END, f"Maps manquantes : {missing}\n")
        self.auto_txt.insert(tk.END, f"Alertes : {alerts}\n\n")
        self.auto_txt.insert(tk.END, f"Estimation : {est}\n")

        self.update_gain()

    def update_gain(self):
        if not hasattr(self, "live"):
            return

        score = 50

        if self.maps:
            score, _, _, _ = analyse_viability(self.maps, self.stage.get())

        est = estimate_gain(self.stock_hp.get(), self.stock_nm.get(), score, self.stage.get())

        self.live.config(
            text=f"Estimation live : {self.stock_hp.get():.0f}ch/{self.stock_nm.get():.0f}Nm → "
                 f"{est['hp_est']}ch/{est['nm_est']}Nm | +{est['hp_gain']}ch +{est['nm_gain']}Nm | "
                 f"confiance {est['confidence']}% | risque {est['risk']}"
        )

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
            self.manual_txt.insert(tk.END, f"{m.name} @ {hex(m.off)} {m.rows}x{m.cols} conf {m.conf}\n\n")

            for row in m.grid():
                self.manual_txt.insert(tk.END, " ".join(f"{v:6d}" for v in row) + "\n")

        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def apply_op(self, old):
        v = self.manual_val.get()
        op = self.manual_op.get()

        if op == "%":
            return old * (1 + v / 100)
        if op == "+":
            return old + v
        if op == "-":
            return old - v
        if op == "*":
            return old * v
        if op == "/":
            if v == 0:
                raise ValueError("Division par zéro")
            return old / v
        if op == "set":
            return v

        return old

    def save_output(self, data, changes, tag):
        if not self.file:
            raise ValueError("Aucun fichier chargé")

        base = os.path.splitext(os.path.basename(self.file))[0]
        mode = "APPLY" if self.apply_real.get() else "DRYRUN"

        out = os.path.join(DIRS["outputs"], f"{base}_{tag}_{mode}_{now()}.bin")
        rep = os.path.join(DIRS["reports"], f"{base}_{tag}_{mode}_{now()}.csv")

        with open(out, "wb") as f:
            f.write(data if self.apply_real.get() else self.data)

        write_rows_csv(rep, changes)

        messagebox.showinfo("OK", f"Fichier : {out}\nRapport : {rep}\nChangements : {len(changes)}")
        self.refresh_reports()

    def modify_manual(self):
        try:
            m = self.selected_map()
            data = bytearray(self.data)
            changes = []

            for i, old in enumerate(m.vals):
                new = self.apply_op(old)
                off = m.off + i * 2
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
                    off = m.off + (r * m.cols + c) * 2

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
            "Rail pressure": 18000,
        }

        multipliers = {
            "Stage 1": 0.50,
            "Stage 1+": 0.75,
            "Stage 2 light": 1.00,
        }

        level = multipliers.get(self.stage.get(), 0.50)

        for m in self.maps:
            if m.name not in caps or m.conf < .74:
                continue

            grid = m.grid()
            new_grid = []

            for row in grid:
                nr = []

                for old in row:
                    if m.name in ["Driver wish", "Torque limiter"]:
                        new = old * (1 + 0.05 * level)
                    elif m.name == "Smoke limiter":
                        new = old + 180 * level
                    elif m.name in ["Boost target", "Boost limiter"]:
                        new = old + 120 * level
                    elif m.name == "Duration":
                        new = old * (1 + 0.025 * level)
                    elif m.name == "Rail pressure":
                        new = old * (1 + 0.018 * level)
                    else:
                        new = old

                    nr.append(min(caps[m.name], int(round(new))))

                new_grid.append(nr)

            new_grid = smooth_grid(new_grid)

            for r in range(m.rows):
                for c in range(m.cols):
                    old = grid[r][c]
                    new = new_grid[r][c]
                    off = m.off + (r * m.cols + c) * 2

                    w16(data, off, new)

                    if old != new:
                        changes.append({"map": m.name, "offset": hex(off), "old": old, "new": new})

        self.save_output(data, changes, "auto")

    def export_maps(self):
        if not self.maps:
            self.scan()

        out = os.path.join(DIRS["reports"], f"maps_detectees_{now()}.csv")
        rows = []

        for i, m in enumerate(self.maps, 1):
            rows.append({
                "index": i,
                "map": m.name,
                "offset": hex(m.off),
                "rows": m.rows,
                "cols": m.cols,
                "confidence": m.conf,
                "min": m.min(),
                "max": m.max(),
                "avg": round(m.avg(), 1),
                "reason": m.reason,
            })

        write_rows_csv(out, rows)
        messagebox.showinfo("Export", out)
        self.refresh_reports()

    def create_project(self):
        name = safe_name(f"{self.brand.get()}_{self.ecu.get()}_{self.engine.get()}_{now()}")
        folder = os.path.join(DIRS["projects"], name)

        for sub in ["stock", "mods", "reports", "notes"]:
            os.makedirs(os.path.join(folder, sub), exist_ok=True)

        meta = {
            "brand": self.brand.get(),
            "ecu": self.ecu.get(),
            "engine": self.engine.get(),
            "stock_hp": self.stock_hp.get(),
            "stock_nm": self.stock_nm.get(),
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        with open(os.path.join(folder, "project.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        if self.file:
            shutil.copy2(self.file, os.path.join(folder, "stock", os.path.basename(self.file)))

        messagebox.showinfo("Projet", f"Projet créé : {folder}")

    def import_stock(self):
        files = filedialog.askopenfilenames()

        for f in files:
            copy_to(f, DIRS["stock"])

        self.refresh_base()
        messagebox.showinfo("OK", f"{len(files)} stock(s) importé(s)")

    def import_mod(self):
        files = filedialog.askopenfilenames()

        for f in files:
            copy_to(f, DIRS["mod"])

        self.refresh_base()
        messagebox.showinfo("OK", f"{len(files)} mod(s) importé(s)")

    def import_gold(self):
        files = filedialog.askopenfilenames()

        for f in files:
            copy_to(f, DIRS["gold"])

        self.refresh_base()
        messagebox.showinfo("OK", f"{len(files)} golden file(s) importé(s)")

    def import_zip_pack(self):
        path = filedialog.askopenfilename(filetypes=[("ZIP", "*.zip"), ("Tous", "*.*")])

        if not path:
            return

        count = 0

        with zipfile.ZipFile(path, "r") as z:
            for info in z.infolist():
                if info.is_dir():
                    continue

                name = info.filename
                size = info.file_size

                if size < 1024:
                    continue

                ext = os.path.splitext(name)[1].lower()

                if ext in [".txt", ".pdf", ".jpg", ".png", ".doc", ".docx", ".xls", ".xlsx", ".exe", ".dll"]:
                    continue

                try:
                    data = z.read(info)
                except Exception:
                    continue

                role = detect_role_from_name(name)

                if role == "stock":
                    folder = DIRS["stock"]
                elif role == "gold":
                    folder = DIRS["gold"]
                elif role == "chinese":
                    folder = DIRS["chinese"]
                elif role == "mod":
                    folder = DIRS["mod"]
                else:
                    folder = DIRS["imports"]

                out = os.path.join(folder, safe_name(os.path.basename(name)))

                if os.path.exists(out):
                    base, ext2 = os.path.splitext(out)
                    out = f"{base}_{now()}{ext2}"

                with open(out, "wb") as f:
                    f.write(data)

                count += 1

        self.refresh_base()
        messagebox.showinfo("ZIP", f"{count} fichier(s) importé(s) depuis ZIP")

    def learn_base(self):
        stocks = [os.path.join(DIRS["stock"], f) for f in os.listdir(DIRS["stock"])]
        golds = [os.path.join(DIRS["gold"], f) for f in os.listdir(DIRS["gold"])]
        mods = [os.path.join(DIRS["mod"], f) for f in os.listdir(DIRS["mod"])]
        chinese = [os.path.join(DIRS["chinese"], f) for f in os.listdir(DIRS["chinese"])]

        all_stocks = stocks + golds
        all_mods = mods + chinese

        rows = []

        self.learning_txt.delete("1.0", tk.END)
        self.learning_txt.insert(tk.END, "Analyse / apprentissage base en cours...\n")
        self.root.update()

        if not all_stocks:
            messagebox.showwarning("Base", "Aucun stock/golden file dans la base")
            return

        if not all_mods:
            messagebox.showwarning("Base", "Aucun mod/chinois dans la base")
            return

        for mod in all_mods:
            try:
                mod_data = read_bin(mod)
            except Exception:
                continue

            best_stock = None
            best_score = -1

            for stock in all_stocks:
                try:
                    stock_data = read_bin(stock)
                except Exception:
                    continue

                if len(stock_data) != len(mod_data):
                    continue

                a = os.path.basename(stock).lower()
                b = os.path.basename(mod).lower()

                name_score = 0

                for token in [
                    "golf", "seat", "skoda", "audi", "tdi", "edc", "bxe", "alh",
                    "asz", "arl", "toyota", "honda", "mitsubishi", "denso"
                ]:
                    if token in a and token in b:
                        name_score += 6

                if "ori" in a or "stock" in a:
                    name_score += 4

                if name_score > best_score:
                    best_score = name_score
                    best_stock = stock

            if not best_stock:
                rows.append({
                    "mod": mod,
                    "stock": "",
                    "score": 0,
                    "bucket": "REJET",
                    "reason": "aucun stock/golden même taille",
                })
                continue

            stock_data = read_bin(best_stock)
            score, bucket, reason, stats = score_mod_quality(stock_data, mod_data, os.path.basename(mod))

            if bucket == "VALIDE":
                copy_to(mod, DIRS["valid"])
            elif bucket == "DOUTEUX":
                copy_to(mod, DIRS["suspect"])
            else:
                copy_to(mod, DIRS["reject"])

            rows.append({
                "mod": mod,
                "stock": best_stock,
                "score": score,
                "bucket": bucket,
                "reason": reason,
                "diff_ratio": stats.get("diff_ratio", ""),
                "blocks": stats.get("blocks", ""),
                "largest_block": stats.get("largest_block", ""),
            })

            self.learning_txt.insert(
                tk.END,
                f"{os.path.basename(mod)} -> {bucket} score {score} | stock {os.path.basename(best_stock)} | {reason}\n"
            )
            self.root.update()

        report = os.path.join(DIRS["learning"], f"learning_report_{now()}.csv")
        write_rows_csv(report, rows)

        summary = {
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total": len(rows),
            "valides": sum(1 for r in rows if r["bucket"] == "VALIDE"),
            "douteux": sum(1 for r in rows if r["bucket"] == "DOUTEUX"),
            "rejetes": sum(1 for r in rows if r["bucket"] == "REJET"),
        }

        with open(os.path.join(DIRS["learning"], f"learning_summary_{now()}.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        self.learning_txt.insert(tk.END, f"\nRapport : {report}\n")
        self.learning_txt.insert(tk.END, f"Résumé : {summary}\n")

        self.refresh_base()
        self.refresh_reports()

    def refresh_base(self):
        self.base_txt.delete("1.0", tk.END)

        for key, folder in DIRS.items():
            count = len(os.listdir(folder)) if os.path.exists(folder) else 0
            self.base_txt.insert(tk.END, f"{key:12s} | {folder:20s} | {count} fichier(s)\n")

    def refresh_reports(self):
        self.reports_txt.delete("1.0", tk.END)

        for folder in [DIRS["reports"], DIRS["learning"], DIRS["outputs"], DIRS["valid"], DIRS["suspect"], DIRS["reject"]]:
            self.reports_txt.insert(tk.END, f"\n--- {folder} ---\n")

            if os.path.exists(folder):
                for f in os.listdir(folder)[-50:]:
                    self.reports_txt.insert(tk.END, f"{f}\n")


root = tk.Tk()
App(root)
root.mainloop()
