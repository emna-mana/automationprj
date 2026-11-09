import ctypes
import logging
import os
import operator
import queue
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from _ctypes import COMError
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import comtypes
from pywinauto import Desktop
from pywinauto import mouse
from pywinauto.keyboard import send_keys
from pywinauto.timings import TimeoutError as DelaiDepasse
from pywinauto.timings import wait_until

import claude
import affectation_machine
import corection_scribing
import pp
import configuration
from conversion_fer_plat import convertir_fers_plats

DESKTOP = Desktop(backend="uia")

# ===== CONFIGURATION (valeurs par défaut, modifiables dans l'interface) =====
USERNAME, PASSWORD = configuration.charger_identifiants()  # config.ini [identifiants]

CHEMINS = configuration.charger_chemins()
EXE_PATH = CHEMINS["steel_projects_exe"]
DOSSIER_PROJETS_DEFAUT = CHEMINS["dossier_sources"]

PHASE_MIN = 130
PHASE_MAX = 140
COMMENTAIRE_2 = "PU"

PHASE_SEUIL_GR = 700     # phases strictement supérieures à ce seuil
COMMENTAIRE_GR = "GR"    # commentaire 2 des repères secondaires dont le profil contient « _ »

DOSSIER_PROJETS_TRAVAILLER = CHEMINS["dossier_projets"]

COMPARAISON_CLAUDE = True    # comparaison avec Claude après l'impression
CORRECTION_SCRIBING = False  # correction du scribing des repères « _ » (Ctrl+D)
AFFECTATION_MACHINE = True   # affectation depuis le classeur de Claude
CONVERSION_FERS_PLATS = True # conversion des tôles retenues en fers plats
FORMAT_IMPORT = "CAM3D"

FICHIER_LOG = "workflow_steel_projects.log"


# Titres des fenêtres (regroupés ici pour être corrigés facilement)
TITRE_GESTION_AFFAIRES = "Gestion d'Affaires"

log = logging.getLogger("workflow")
log.setLevel(logging.INFO)

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_set_thread_execution_state = _kernel32.SetThreadExecutionState
_set_thread_execution_state.argtypes = (wintypes.DWORD,)
_set_thread_execution_state.restype = wintypes.DWORD

ES_CONTINUOUS = 0x80000000
ES_DISPLAY_REQUIRED = 0x00000002


# ===== JOURNAL =====
class GestionnaireFile(logging.Handler):
    # Envoie chaque message de log à l'interface (via une file thread-safe)
    def __init__(self, messages):
        super().__init__()
        self.messages = messages

    def emit(self, record):
        self.messages.put(("log", self.format(record)))


def configurer_journal(messages):
    # Journal dans le fichier + dans la fenêtre (pas de console : compatible pythonw)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fichier = logging.FileHandler(FICHIER_LOG, encoding="utf-8")
    fichier.setFormatter(fmt)
    fenetre = GestionnaireFile(messages)
    fenetre.setFormatter(fmt)
    log.addHandler(fichier)
    log.addHandler(fenetre)


class FluxVersJournal:
    # Remplace sys.stdout : chaque ligne écrite par print (ex. claude) part dans le journal
    def __init__(self):
        self.tampon = ""

    def write(self, texte):
        self.tampon += texte
        while "\n" in self.tampon:
            ligne, self.tampon = self.tampon.split("\n", 1)
            if ligne.strip():
                log.info(ligne)

    def flush(self):
        pass


# ===== WORKFLOW PAR PROJET =====
def lister_projets(dossier_racine, format_import=FORMAT_IMPORT):
    extension = ".tsm" if format_import == "CAM3D" else ".xml"

    def contient_fichier(dossier):
        return any(f.lower().endswith(extension) for f in os.listdir(dossier))

    projets = [os.path.join(dossier_racine, nom) for nom in sorted(os.listdir(dossier_racine))]
    projets = [p for p in projets if os.path.isdir(p) and contient_fichier(p)]

    # Cas particulier : le dossier choisi est lui-même un projet.
    if not projets and contient_fichier(dossier_racine):
        projets = [dossier_racine]
    return projets


def trouver_fenetre(window, titre_re, timeout=60):
    # Les boîtes de dialogue CAM3D et « Ventilation des plans » ont leur propre barre de titre :
    # ce sont des fenêtres séparées, pas des enfants de Steel Projects. On cherche aux deux endroits.
    def visible():
        for f in (window.child_window(title_re=titre_re),
                  DESKTOP.window(title_re=titre_re, top_level_only=True)):
            try:
                if f.exists(timeout=0) and f.is_visible():
                    return f
            except COMError:
                pass   # appli occupée : on réessaie
        return None

    return wait_until(timeout, 0.5, visible, None, operator.is_not)


def trouver_fenetre_cam3d(window, timeout=60):
    return trouver_fenetre(window, r".*CAM3D.*", timeout)


def valider_ventilation_plans(window, timeout=120):
    ventilation = trouver_fenetre(window, r"Ventilation des plans", timeout)
    pp.cliquer(ventilation.child_window(title="Ok", control_type="Button"))
    ventilation.wait_not("exists visible", timeout=60, retry_interval=0.5)


def lister_fichiers_cam3d(dialogue):
    liste = dialogue.child_window(auto_id="listView", control_type="List").wrapper_object()
    fichiers = set()
    for element in liste.descendants():
        nom = element.window_text().strip()
        if nom.lower().endswith(".tsm"):
            fichiers.add(nom)
    return sorted(fichiers) or None

def importer_cam3d_projet(window, dossier_projet):
    fichiers_dossier = [
        nom for nom in os.listdir(dossier_projet)
        if nom.lower().endswith(".tsm")
    ]
    if not fichiers_dossier:
        raise FileNotFoundError(f"Aucun fichier .tsm dans le dossier CAM3D : {dossier_projet}")

    bouton_import = window.child_window(title="Import", control_type="Button")
    pp.cliquer(bouton_import)
    pp.cliquer_menu(bouton_import, "CAM3D")

    dialogue = trouver_fenetre_cam3d(window, timeout=60)
    pp.attendre(dialogue, "exists visible", timeout=60)

    chemin = dialogue.child_window(auto_id="ptbLocalFolder", control_type="Pane")
    pp.attendre(chemin, timeout=10).click_input()
    time.sleep(0.5)
    send_keys("^a", pause=0.1)
    dossier = os.path.abspath(dossier_projet)
    log.info("Navigation CAM3D vers : %s", dossier)
    send_keys(pp.echapper_keys(dossier + os.sep) + "{ENTER}", with_spaces=True, pause=0.05)
    attendus = {nom.lower() for nom in fichiers_dossier}

    fin_attente = time.monotonic() + 20
    fichiers = []
    while time.monotonic() < fin_attente:
        fichiers = lister_fichiers_cam3d(dialogue) or []
        if attendus.intersection(nom.lower() for nom in fichiers):
            break
        time.sleep(0.5)
    else:
        dialogue.set_focus()
        send_keys("{ESC}")
        raise RuntimeError(
            f"Le dossier contient {fichiers_dossier}, mais ces fichiers n'apparaissent pas "
            f"dans la liste CAM3D après actualisation : {dossier!r}. "
        )
    log.info("Fichiers CAM3D affichés : %s", fichiers)

    liste = dialogue.child_window(auto_id="listView", control_type="List").wrapper_object()
    fichier_a_importer = next(
        (
            element for element in liste.descendants()
            if element.window_text().strip().lower() in attendus
        ),
        None,
    )
    if fichier_a_importer is None:
        raise RuntimeError(f"Impossible de sélectionner le fichier CAM3D dans la liste : {fichiers_dossier}")
    fichier_a_importer.click_input()

    bouton_ok = dialogue.child_window(title="Ok", control_type="Button")
    pp.attendre(bouton_ok, timeout=10)
    dialogue.set_focus()
    rectangle_ok = bouton_ok.wrapper_object().rectangle()
    mouse.click(
        button="left",
        coords=(
            (rectangle_ok.left + rectangle_ok.right) // 2,
            (rectangle_ok.top + rectangle_ok.bottom) // 2,
        ),
    )
    try:
        dialogue.wait_not("exists visible", timeout=5, retry_interval=0.2)
    except DelaiDepasse:
        log.warning("Le clic sur OK n'a pas fermé le dialogue CAM3D ; nouvel essai avec Entrée")
        dialogue.set_focus()
        send_keys("{ENTER}")
        try:
            dialogue.wait_not("exists visible", timeout=10, retry_interval=0.2)
        except DelaiDepasse as exc:
            raise RuntimeError("Le dialogue CAM3D reste ouvert après le clic sur OK et la touche Entrée") from exc

    valider_ventilation_plans(window)
    # Ensuite : « Profil Strict » (+ sur chaque profil, puis Ok), puis « Comparaison [Affaire] » (Ajouter, Ok)
    pp.valider_profils_stricts(window, timeout=60)
    pp.valider_comparaison_affaire(window, timeout=60)
    pp.finir_import(window)


def traiter_projet(window, dossier_projet):
    # Enchaîne toutes les étapes pour UN projet (une affaire)
    affaire = os.path.basename(dossier_projet)
    pp.AFFAIRE = affaire
    log.info("=== Début du projet %s ===", affaire)

    if FORMAT_IMPORT == "CAM3D":
        log.info("Import CAM3D")
        importer_cam3d_projet(window, dossier_projet)
    else:
        log.info("Import TEKLA_XML")
        pp.importer_tekla(window, dossier_projet)
    pp.ouvrir_gestion_production(window)
    pp.filtrer_par_affaire(window)
    pp.filtre_par_phase(window)
    pp.ajouter_scribing(window)
    pp.selectionner_phases(window)
    pp.modifier_repere_secondaire(window)
    pp.commentaire_gr(window)
    pp.quitter_gestion_production(window)
    pp.fermer_apercu()
    chemin_pdf = pp.impression(window)
    pp.fermer_pdf_ouverts(chemin_pdf)
    pp.fermer_apercu()
    pp.revenir_steel_projects(window)
    pp.quitter_gestion_affaires(window)

    # Comparaison avec Claude, une fois l'impression terminée et Steel Projects revenu à l'accueil
    if COMPARAISON_CLAUDE:
        log.info("=== Comparaison avec Claude ===")
        fichiers = claude.comparer_avec_claude(
            claude.fichiers_affaire(affaire, chemin_pdf),
            claude.dossier_sortie_affaire(affaire),
        )
        # Visionneuses (Acrobat, Excel) ouvertes par les téléchargements : elles cachaient Steel Projects
        pp.fermer_visionneuses(fichiers)
        pp.revenir_steel_projects(window)  # Claude avait pris le focus

    if CORRECTION_SCRIBING or AFFECTATION_MACHINE or CONVERSION_FERS_PLATS:
        pp.ouvrir_gestion_production(window)
        pp.filtrer_par_affaire(window)
        # Correction scribing jarret désactivée (bloc commenté)
#        if CORRECTION_SCRIBING:
#            log.info("=== Correction scribing jarret ===")
#            corection_scribing.corriger_scribing_jarret(window, affaire)
        if AFFECTATION_MACHINE:
            log.info("=== Affectation machine ===")
            affectation_machine.affectation_machine(window, affaire)
        if CONVERSION_FERS_PLATS:
            log.info("=== Conversion fers plats ===")
            convertir_fers_plats(window, affaire)
        pp.quitter_gestion_production(window)

    log.info("=== Fin du projet %s ===", affaire)


def recuperer_apres_erreur(window):
    # Meilleur effort pour revenir à l'écran principal après un échec, sans jamais quitter l'appli
    try:
        pp.fermer_apercu(timeout=10)
    except Exception:
        log.warning("Impossible de fermer la fenêtre d'aperçu")

    for ecran in ("Gestion de production", TITRE_GESTION_AFFAIRES):
        try:
            if ecran in window.window_text():
                window.set_focus()
                send_keys("^q")
                wait_until(30, 0.5, lambda: ecran not in window.window_text())
        except Exception:
            log.warning("Impossible de fermer l'écran « %s »", ecran)

    try:
        pp.revenir_steel_projects(window)
    except Exception:
        log.warning("Impossible de revenir sur la fenêtre principale")


def appliquer_configuration(cfg):
    # Recopie les paramètres saisis dans l'interface dans les constantes utilisées par les étapes
    global USERNAME, PASSWORD, EXE_PATH, PHASE_MIN, PHASE_MAX
    global COMMENTAIRE_2, PHASE_SEUIL_GR, COMMENTAIRE_GR
    global COMPARAISON_CLAUDE, CORRECTION_SCRIBING
    global AFFECTATION_MACHINE, CONVERSION_FERS_PLATS, FORMAT_IMPORT
    USERNAME = cfg["utilisateur"]
    PASSWORD = cfg["mot_de_passe"]
    EXE_PATH = cfg["exe"]
    claude.DOSSIER_PROJETS_A_TRAVAILLER = cfg["dossier_sources"]
    PHASE_MIN = cfg["phase_min"]
    PHASE_MAX = cfg["phase_max"]
    COMMENTAIRE_2 = cfg["commentaire_2"]
    PHASE_SEUIL_GR = cfg["seuil_gr"]
    COMMENTAIRE_GR = cfg["commentaire_gr"]
    COMPARAISON_CLAUDE = cfg["comparaison_claude"]
    CORRECTION_SCRIBING = cfg["correction_scribing"]
    AFFECTATION_MACHINE = cfg["affectation_machine"]
    CONVERSION_FERS_PLATS = cfg["conversion_fers_plats"]
    FORMAT_IMPORT = cfg["format_import"]
    pp.USERNAME = USERNAME
    pp.PASSWORD = PASSWORD
    pp.EXE_PATH = EXE_PATH
    pp.PHASE_MIN = PHASE_MIN
    pp.PHASE_MAX = PHASE_MAX
    pp.COMMENTAIRE_2 = COMMENTAIRE_2
    pp.PHASE_SEUIL_GR = PHASE_SEUIL_GR
    pp.COMMENTAIRE_GR = COMMENTAIRE_GR
    pp.DOSSIER_PROJETS_TRAVAILLER = DOSSIER_PROJETS_TRAVAILLER


def executer_workflow(projets, stop_event, messages):
    # Les print de claude vont dans le journal (pas de console avec pythonw)
    ancien_stdout = sys.stdout
    sys.stdout = FluxVersJournal()
    try:
        if not _set_thread_execution_state(ES_CONTINUOUS | ES_DISPLAY_REQUIRED):
            raise ctypes.WinError(ctypes.get_last_error())

        executer_projets(projets, stop_event, messages)
    finally:
        if not _set_thread_execution_state(ES_CONTINUOUS):
            log.error(
                "Impossible de rétablir la gestion normale de l'écran : %s",
                ctypes.WinError(ctypes.get_last_error()),
            )
        sys.stdout = ancien_stdout


def executer_projets(projets, stop_event, messages):
    # Tourne dans un thread séparé : connexion une seule fois, puis boucle projet par projet
    try:
        comtypes.CoInitialize()  # obligatoire pour UIA dans un thread autre que le principal
    except Exception:
        pass

    reussis, echoues = [], []
    try:
        window = pp.lancer_application()
        pp.s_authentifier(window)

        for i, chemin in enumerate(projets, start=1):
            if stop_event.is_set():
                log.warning("Arrêt demandé : les projets restants ne sont pas traités")
                break
            affaire = os.path.basename(chemin)
            messages.put(("statut", chemin, "En cours"))
            try:
                traiter_projet(window, chemin)
                reussis.append(affaire)
                messages.put(("statut", chemin, "Terminé"))
            except Exception as e:
                # Un projet en échec ne bloque pas les suivants
                log.exception("Échec du projet %s : %s", affaire, e)
                echoues.append(affaire)
                messages.put(("statut", chemin, "Erreur"))
                recuperer_apres_erreur(window)
            messages.put(("progression", i, len(projets)))
    except Exception as e:
        log.exception("Arrêt du workflow : %s", e)

    log.info("Bilan : %d réussi(s), %d en échec", len(reussis), len(echoues))
    if echoues:
        log.warning("Projets en échec : %s", ", ".join(echoues))
    messages.put(("fin", None))


# ===== INTERFACE =====
class InterfaceWorkflow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Steel Projects – Workflow automatique")
        self.geometry("1000x760")
        self.minsize(880, 660)

        self.messages = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None

        self._construire_interface()
        configurer_journal(self.messages)
        self.protocol("WM_DELETE_WINDOW", self._a_la_fermeture)
        self.after(100, self._traiter_messages)
        self.actualiser_projets()   # liste les projets du dossier dès l'ouverture

    def _construire_interface(self):
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        marge = {"padx": 8, "pady": 4}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self.rowconfigure(5, weight=1)

        # 1. Dossier des projets
        cadre = ttk.LabelFrame(self, text="1. Dossier contenant les projets")
        cadre.grid(row=0, column=0, sticky="ew", **marge)
        cadre.columnconfigure(0, weight=1)
        self.var_dossier = tk.StringVar(value=DOSSIER_PROJETS_DEFAUT)
        ttk.Entry(cadre, textvariable=self.var_dossier).grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        self.btn_parcourir = ttk.Button(cadre, text="Parcourir…", command=self.choisir_dossier)
        self.btn_parcourir.grid(row=0, column=1, padx=4)
        self.btn_actualiser = ttk.Button(cadre, text="Actualiser", command=self.actualiser_projets)
        self.btn_actualiser.grid(row=0, column=2, padx=(4, 6))

        # 2. Connexion
        cadre = ttk.LabelFrame(self, text="2. Connexion à Steel Projects")
        cadre.grid(row=1, column=0, sticky="ew", **marge)
        cadre.columnconfigure(5, weight=1)
        self.var_user = tk.StringVar(value=USERNAME)
        self.var_pwd = tk.StringVar(value=PASSWORD)
        self.var_exe = tk.StringVar(value=EXE_PATH)
        ttk.Label(cadre, text="Utilisateur").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(cadre, textvariable=self.var_user, width=14).grid(row=0, column=1, padx=4)
        ttk.Label(cadre, text="Mot de passe").grid(row=0, column=2, sticky="w", padx=6)
        ttk.Entry(cadre, textvariable=self.var_pwd, show="*", width=14).grid(row=0, column=3, padx=4)
        ttk.Label(cadre, text="Exécutable").grid(row=0, column=4, sticky="w", padx=6)
        ttk.Entry(cadre, textvariable=self.var_exe).grid(row=0, column=5, sticky="ew", padx=(4, 6))
        self.var_format_import = tk.StringVar(value=FORMAT_IMPORT)
        ttk.Label(cadre, text="Type d'import").grid(row=1, column=0, sticky="w", padx=6, pady=(0, 6))
        ttk.Combobox(
            cadre,
            textvariable=self.var_format_import,
            values=("TEKLA_XML", "CAM3D"),
            state="readonly",
            width=14,
        ).grid(row=1, column=1, columnspan=2, sticky="w", padx=4, pady=(0, 6))
        self.var_format_import.trace_add("write", self._format_import_change)

        # Paramètres de traitement
        cadre = ttk.LabelFrame(self, text="Paramètres de traitement")
        cadre.grid(row=2, column=0, sticky="ew", **marge)
        self.var_phase_min = tk.StringVar(value=str(PHASE_MIN))
        self.var_phase_max = tk.StringVar(value=str(PHASE_MAX))
        self.var_com2 = tk.StringVar(value=COMMENTAIRE_2)
        self.var_seuil_gr = tk.StringVar(value=str(PHASE_SEUIL_GR))
        self.var_com_gr = tk.StringVar(value=COMMENTAIRE_GR)
        champs = [
            ("Phase min", self.var_phase_min, 6),
            ("Phase max", self.var_phase_max, 6),
            ("Commentaire 2", self.var_com2, 8),
            ("Seuil GR (phase >)", self.var_seuil_gr, 6),
            ("Commentaire GR", self.var_com_gr, 8),
        ]
        for col, (libelle, var, largeur) in enumerate(champs):
            ttk.Label(cadre, text=libelle).grid(row=0, column=col * 2, sticky="w", padx=(8, 2), pady=6)
            ttk.Entry(cadre, textvariable=var, width=largeur).grid(row=0, column=col * 2 + 1, padx=(0, 6))

        self.var_claude = tk.BooleanVar(value=COMPARAISON_CLAUDE)
        self.var_scribing = tk.BooleanVar(value=CORRECTION_SCRIBING)
        self.var_affectation = tk.BooleanVar(value=AFFECTATION_MACHINE)
        self.var_conversion_fp = tk.BooleanVar(value=CONVERSION_FERS_PLATS)
        ttk.Checkbutton(cadre, text="Comparaison Claude", variable=self.var_claude).grid(
            row=1, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 6))
        ttk.Checkbutton(cadre, text="Correction scribing jarret", variable=self.var_scribing).grid(
            row=1, column=4, columnspan=4, sticky="w", padx=8, pady=(0, 6))
        ttk.Checkbutton(cadre, text="Affectation machine", variable=self.var_affectation).grid(
            row=2, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 6))
        ttk.Checkbutton(cadre, text="Conversion fers plats", variable=self.var_conversion_fp).grid(
            row=2, column=4, columnspan=4, sticky="w", padx=8, pady=(0, 6))

        # 3. Projets (sélection multiple)
        cadre = ttk.LabelFrame(self, text="3. Projets trouvés (sélectionnez ceux à traiter)")
        cadre.grid(row=3, column=0, sticky="nsew", **marge)
        cadre.columnconfigure(0, weight=1)
        cadre.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(cadre, columns=("projet", "xml", "statut"), show="headings",
                                 selectmode="extended")
        self.tree.heading("projet", text="Projet (affaire)")
        self.tree.heading("xml", text="Fichiers XML" if FORMAT_IMPORT == "TEKLA_XML" else "Fichiers TSM")
        self.tree.heading("statut", text="Statut")
        self.tree.column("projet", width=380)
        self.tree.column("xml", width=110, anchor="center")
        self.tree.column("statut", width=160, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        defil = ttk.Scrollbar(cadre, orient="vertical", command=self.tree.yview)
        defil.grid(row=0, column=1, sticky="ns", pady=6)
        self.tree.configure(yscrollcommand=defil.set)

        barre = ttk.Frame(cadre)
        barre.grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 6))
        ttk.Button(barre, text="Tout sélectionner",
                   command=lambda: self._selectionner_tout(True)).pack(side="left", padx=(0, 4))
        ttk.Button(barre, text="Tout désélectionner",
                   command=lambda: self._selectionner_tout(False)).pack(side="left")

        # 4. Exécution
        cadre = ttk.LabelFrame(self, text="4. Exécution")
        cadre.grid(row=4, column=0, sticky="ew", **marge)
        cadre.columnconfigure(2, weight=1)
        self.btn_demarrer = ttk.Button(cadre, text="Démarrer", command=self.demarrer)
        self.btn_demarrer.grid(row=0, column=0, padx=6, pady=6)
        self.btn_arreter = ttk.Button(cadre, text="Arrêter", command=self.arreter, state="disabled")
        self.btn_arreter.grid(row=0, column=1, padx=4)
        self.progression = ttk.Progressbar(cadre, mode="determinate", maximum=1)
        self.progression.grid(row=0, column=2, sticky="ew", padx=6)
        self.var_statut = tk.StringVar(value="Prêt")
        ttk.Label(cadre, textvariable=self.var_statut, width=34).grid(row=0, column=3, padx=6)

        # 5. Journal
        cadre = ttk.LabelFrame(self, text="5. Journal")
        cadre.grid(row=5, column=0, sticky="nsew", **marge)
        cadre.columnconfigure(0, weight=1)
        cadre.rowconfigure(0, weight=1)
        self.journal = ScrolledText(cadre, height=10, state="disabled", font=("Consolas", 9))
        self.journal.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

    # --- Actions de l'interface ---
    def choisir_dossier(self):
        dossier = filedialog.askdirectory(
            title="Dossier contenant les projets",
            initialdir=self.var_dossier.get() or DOSSIER_PROJETS_DEFAUT,
            parent=self,
        )
        if dossier:
            self.var_dossier.set(dossier)
            self.actualiser_projets()

    def _format_import_change(self, *_):
        if hasattr(self, "tree"):
            self.actualiser_projets()

    def actualiser_projets(self):
        dossier = self.var_dossier.get().strip()
        if not os.path.isdir(dossier):
            messagebox.showerror("Dossier introuvable", f"Ce dossier n'existe pas :\n{dossier}", parent=self)
            return

        extension = ".TSM" if self.var_format_import.get() == "CAM3D" else ".XML"
        self.tree.heading("xml", text=f"Fichiers {extension[1:]}")
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        projets = lister_projets(dossier, self.var_format_import.get())
        for chemin in projets:
            nb_fichiers = sum(1 for f in os.listdir(chemin) if f.upper().endswith(extension))
            self.tree.insert("", "end", iid=chemin,
                             values=(os.path.basename(chemin), nb_fichiers, "En attente"))
        self.tree.selection_set(projets)  # tous sélectionnés par défaut

        self.var_statut.set(f"{len(projets)} projet(s) trouvé(s)")
        if not projets:
            type_fichier = "TSM" if extension == ".TSM" else "XML"
            messagebox.showwarning("Aucun projet",
                                   f"Aucun sous-dossier contenant des fichiers {type_fichier} n'a été trouvé.",
                                   parent=self)

    def _selectionner_tout(self, actif):
        enfants = self.tree.get_children()
        if actif:
            self.tree.selection_set(enfants)
        else:
            self.tree.selection_remove(enfants)

    def _lire_parametres(self):
        # Lit et contrôle les paramètres saisis ; renvoie None si une valeur est invalide
        try:
            return {
                "utilisateur": self.var_user.get().strip(),
                "mot_de_passe": self.var_pwd.get(),
                "exe": self.var_exe.get().strip(),
                "format_import": self.var_format_import.get(),
                "phase_min": int(self.var_phase_min.get()),
                "phase_max": int(self.var_phase_max.get()),
                "commentaire_2": self.var_com2.get().strip(),
                "seuil_gr": int(self.var_seuil_gr.get()),
                "commentaire_gr": self.var_com_gr.get().strip(),
                "comparaison_claude": self.var_claude.get(),
                "correction_scribing": self.var_scribing.get(),
                "affectation_machine": self.var_affectation.get(),
                "conversion_fers_plats": self.var_conversion_fp.get(),
            }
        except ValueError:
            messagebox.showerror("Paramètres invalides",
                                 "Les phases et le seuil GR doivent être des nombres entiers.", parent=self)
            return None

    def demarrer(self):
        if self.worker and self.worker.is_alive():
            return

        selection = set(self.tree.selection())
        projets = [c for c in self.tree.get_children() if c in selection]  # ordre affiché
        if not projets:
            messagebox.showwarning("Aucun projet", "Sélectionnez au moins un projet.", parent=self)
            return

        cfg = self._lire_parametres()
        if cfg is None:
            return
        cfg["dossier_sources"] = self.var_dossier.get().strip()
        if not messagebox.askyesno("Confirmation",
                                   f"Lancer le traitement de {len(projets)} projet(s) ?", parent=self):
            return

        appliquer_configuration(cfg)
        for chemin in projets:
            self.tree.set(chemin, "statut", "En attente")

        self.stop_event.clear()
        self.progression["value"] = 0
        self._activer(False)
        self.var_statut.set("Démarrage…")
        log.info("Démarrage : %d projet(s) sélectionné(s)", len(projets))

        self.worker = threading.Thread(
            target=executer_workflow,
            args=(projets, self.stop_event, self.messages),
            daemon=True,
        )
        self.worker.start()

    def arreter(self):
        self.stop_event.set()
        self.var_statut.set("Arrêt demandé…")
        log.warning("Arrêt demandé : le projet en cours sera terminé, puis le traitement s'arrêtera")

    def _activer(self, actif):
        etat_normal = "normal" if actif else "disabled"
        for bouton in (self.btn_demarrer, self.btn_parcourir, self.btn_actualiser):
            bouton.configure(state=etat_normal)
        self.btn_arreter.configure(state="disabled" if actif else "normal")

    def _ajouter_journal(self, texte):
        self.journal.configure(state="normal")
        self.journal.insert("end", texte + "\n")
        self.journal.see("end")
        self.journal.configure(state="disabled")

    def _traiter_messages(self):
        # Lit les messages du thread de travail (le Tk ne doit être modifié que dans ce thread)
        try:
            while True:
                message = self.messages.get_nowait()
                genre = message[0]
                if genre == "log":
                    self._ajouter_journal(message[1])
                elif genre == "statut":
                    _, chemin, texte = message
                    if self.tree.exists(chemin):
                        self.tree.set(chemin, "statut", texte)
                elif genre == "progression":
                    _, fait, total = message
                    self.progression["maximum"] = total
                    self.progression["value"] = fait
                    self.var_statut.set(f"{fait}/{total} projet(s) traité(s)")
                elif genre == "fin":
                    self._activer(True)
                    self.var_statut.set("Terminé")
                    self.worker = None
        except queue.Empty:
            pass
        self.after(100, self._traiter_messages)

    def _a_la_fermeture(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(
                "Traitement en cours",
                "Un traitement est en cours. L'arrêter après le projet en cours et fermer ?",
                parent=self,
            ):
                return
            self.stop_event.set()
        self.destroy()


if __name__ == "__main__":
    app = InterfaceWorkflow()
    app.mainloop()