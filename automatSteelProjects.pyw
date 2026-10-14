import ctypes
import logging
import operator
import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import comtypes
from _ctypes import COMError
from pywinauto import Desktop
from pywinauto.application import Application
from pywinauto.keyboard import send_keys
from pywinauto.timings import TimeoutError as DelaiDepasse
from pywinauto.timings import wait_until
from pywinauto.uia_defines import get_elem_interface

# ===== CONFIGURATION (valeurs par défaut, modifiables dans l'interface) =====
USERNAME = "EBA"
PASSWORD = "EBA2026"
EXE_PATH = r"C:\Program Files (x86)\SteelProjects\Sp.Plm\Sp.Plm.exe"
DOSSIER_PROJETS_DEFAUT = r"C:/Users/E.BENAMOR/Desktop/PROJETS"

PHASE_MIN = 130
PHASE_MAX = 140
COMMENTAIRE_2 = "PU"

PHASE_SEUIL_GR = 700     # phases strictement supérieures à ce seuil
COMMENTAIRE_GR = "GR"    # commentaire 2 des repères secondaires dont le profil contient « _ »

NOM_DOSSIER_PDF = "Impressions Steel Projects"
FICHIER_LOG = "workflow_steel_projects.log"

DESKTOP = Desktop(backend="uia")

# Titres des fenêtres (regroupés ici pour être corrigés facilement)
TITRE_APERCU = r"Aper.u \d+/\d+"
TITRE_GESTION_AFFAIRES = "Gestion d'Affaires"

log = logging.getLogger("workflow")
log.setLevel(logging.INFO)


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


# ===== OUTILS =====
def echapper_keys(texte):
    # Entoure de accolades les caractères spéciaux de type_keys pour qu'ils soient tapés tels quels
    return "".join("{" + c + "}" if c in "+^%~(){}[]" else c for c in texte)


def attendre(ctrl, etat="exists visible enabled", timeout=30):
    # Attend qu'un contrôle soit dans l'état voulu, puis le renvoie
    ctrl.wait(etat, timeout=timeout, retry_interval=0.2)
    return ctrl


def cliquer(ctrl, timeout=30):
    # Attend qu'un contrôle soit cliquable, puis clique dessus
    attendre(ctrl, timeout=timeout).click_input()


def cliquer_menu(bouton, texte, timeout=30):
    # Attend qu'un élément de menu apparaisse sous le bouton, puis clique dessus
    item = wait_until(
        timeout, 0.2,
        lambda: next((x for x in bouton.wrapper_object().descendants(control_type="MenuItem")
                      if x.window_text() == texte), None),
        None, operator.is_not,
    )
    item.click_input()


def attendre_appli(window, timeout=30):
    # Attend que l'application ait fini de travailler (CPU au repos)
    pid = window.wrapper_object().process_id()
    app = Application(backend="uia").connect(process=pid)
    app.wait_cpu_usage_lower(threshold=5, timeout=timeout)


def valider_comparaison(window):
    # Si la fenêtre de comparaison de profils est ouverte, clique sur Ok
    comparaison = window.child_window(auto_id="FormProfileComparison", control_type="Window")
    if not comparaison.exists(timeout=0):
        return False
    barre = comparaison.child_window(auto_id="stateBar", control_type="Pane")
    attendre(barre.child_window(title="Ok", control_type="Button")).invoke()
    comparaison.wait_not("exists", timeout=30, retry_interval=0.2)
    log.info("Comparaison de profils validée")
    return True


def cliquer_avec_comparaison(window, ctrl, timeout=30):
    # Attend que ctrl soit cliquable ; valide la comparaison de profils si elle apparaît.
    # Les erreurs UIA temporaires (appli occupée) sont ignorées et l'attente continue.
    def pret():
        try:
            if valider_comparaison(window):
                return False
            return ctrl.exists(timeout=0) and ctrl.is_visible() and ctrl.is_enabled()
        except COMError:
            return False

    wait_until(timeout, 0.5, pret)
    ctrl.click_input()


def trouver_grille(window, colonne="Phase", timeout=30):
    # Plusieurs tables « dgvData » peuvent exister : garde la visible qui a la colonne demandée
    # (si plusieurs conviennent, prend celle qui a le plus de lignes)
    def chercher():
        try:
            candidates = []
            for g in window.wrapper_object().descendants(control_type="Table"):
                if g.automation_id() != "dgvData" or not g.is_visible():
                    continue
                lignes = [l for l in g.children(control_type="Custom") if l.window_text() != "Ligne du haut"]
                if lignes and any(c.window_text().startswith(colonne + " ")
                                  for c in lignes[0].children(control_type="Edit")):
                    candidates.append((len(lignes), g))
            if not candidates:
                return None
            return max(candidates, key=lambda x: x[0])[1]
        except COMError:
            return None

    return wait_until(timeout, 0.5, chercher, None, operator.is_not)


def focus_premiere_ligne(grille):
    # Donne le focus clavier à la grille en sélectionnant sa 1re ligne (sans souris)
    for ligne in grille.children(control_type="Custom"):
        if ligne.window_text() != "Ligne du haut":
            legacy = get_elem_interface(ligne.element_info.element, "LegacyIAccessible")
            legacy.Select(0x3)  # remplace la sélection + donne le focus à la grille
            return True
    return False


def valeur_cellule(ligne, colonne):
    # Valeur de la cellule de « colonne » dans une ligne (cellule nommée « <colonne> Ligne N, ... »)
    for c in ligne.children(control_type="Edit"):
        if c.window_text().startswith(colonne + " "):
            return (c.get_value() or "").strip()
    return ""


def selectionner_lignes(grille, colonne, condition):
    # Sélectionne les lignes dont la cellule vérifie la condition, SANS souris
    # (sélection d'accessibilité) : fonctionne aussi pour les lignes hors de l'écran
    n = 0
    for ligne in grille.children(control_type="Custom"):
        if ligne.window_text() == "Ligne du haut":
            continue
        if condition(valeur_cellule(ligne, colonne)):
            legacy = get_elem_interface(ligne.element_info.element, "LegacyIAccessible")
            # 1re ligne : remplace la sélection et donne le focus (0x2 + 0x1)
            # lignes suivantes : ajout à la sélection (0x8)
            legacy.Select(0x3 if n == 0 else 0x8)
            n += 1
    return n


def afficher_colonne(grille, colonne):
    # Diagnostic : affiche la valeur de la colonne pour chaque ligne de la grille
    for ligne in grille.children(control_type="Custom"):
        if ligne.window_text() != "Ligne du haut":
            log.info("  %s | %s = %r", ligne.window_text(), colonne, valeur_cellule(ligne, colonne))


def remplir_commentaire_2(window, texte):
    # Fenêtre d'édition des repères (ouverte par Entrée) : écrit texte dans Commentaire 2, valide, quitte
    repere = window.child_window(auto_id="SpForm", control_type="Window")
    attendre(repere, "exists visible")

    onglets = repere.child_window(auto_id="tsGeneral", control_type="Pane")
    cliquer(onglets.child_window(control_type="TreeItem", found_index=3))

    com2 = attendre(repere.child_window(auto_id="tbCom2", control_type="Edit"))
    com2.click_input()
    com2.type_keys("^a{BACKSPACE}" + echapper_keys(texte), with_spaces=True)

    cliquer(repere.child_window(title="Valider", control_type="Button"))
    cliquer(repere.child_window(title="Quitter", control_type="Button"))
    repere.wait_not("exists", timeout=30, retry_interval=0.2)


def focus_grille_haut(window, timeout=30):
    # Met le focus clavier dans la grille visible du haut (zone Affaire / Plan / RP / RS)
    # en cliquant sur l'en-tête de la première ligne
    zone = window.child_window(auto_id="pnlAffairePlanRpRs", control_type="Pane")

    def entete_premiere_ligne():
        try:
            for g in zone.wrapper_object().descendants(control_type="Table"):
                if g.automation_id() != "dgvData" or not g.is_visible():
                    continue
                for ligne in g.children(control_type="Custom"):
                    if ligne.window_text() == "Ligne du haut":
                        continue
                    entetes = ligne.children(control_type="Header")
                    if entetes:
                        return entetes[0]
        except COMError:
            pass  # appli occupée : on réessaie
        return None

    entete = wait_until(timeout, 0.5, entete_premiere_ligne, None, operator.is_not)
    entete.click_input()


def dossier_pdf():
    # Chemin réel du Bureau (fonctionne aussi si le Bureau est redirigé vers OneDrive),
    # puis création du sous-dossier des PDF s'il n'existe pas
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)  # 0x10 = Bureau
    dossier = os.path.join(buf.value, NOM_DOSSIER_PDF)
    os.makedirs(dossier, exist_ok=True)
    return dossier


def enregistrer_pdf(affaire, timeout=120):
    # Remplit la boîte « Enregistrer le fichier PDF sous » :
    # nom = affaire + date/heure, dans le dossier du Bureau, puis vérifie le fichier créé
    dossier = dossier_pdf()
    horodatage = datetime.now().strftime("%Y%m%d_%H%M")
    chemin = os.path.join(dossier, f"{affaire}_{horodatage}.pdf")

    boite = DESKTOP.window(title="Enregistrer le fichier PDF sous")
    attendre(boite, "exists visible", timeout=timeout)
    handle = boite.wrapper_object().handle
    boite = DESKTOP.window(handle=handle)

    # Champ « Nom du fichier » (control_type obligatoire : la barre d'adresse a aussi l'auto_id 1001)
    nom = attendre(boite.child_window(auto_id="1001", control_type="Edit"))
    nom.click_input()
    nom.type_keys("^a{BACKSPACE}" + echapper_keys(chemin), with_spaces=True)

    # Vérifie que le champ contient bien le chemin complet avant d'enregistrer
    wait_until(10, 0.2, lambda: (nom.get_value() or "") == chemin)

    cliquer(boite.child_window(auto_id="1", control_type="Button"))  # Enregistrer
    # Attend la fermeture de la boîte
    wait_until(60, 0.2, lambda: not ctypes.windll.user32.IsWindow(handle))

    # Vérifie que le PDF a bien été créé
    wait_until(300, 1, lambda: os.path.exists(chemin))
    log.info("PDF enregistré : %s", chemin)
    return chemin


# ===== ÉTAPES =====
def lancer_application(timeout=90):
    # Lance Steel Projects et renvoie la fenêtre qui affiche l'écran de connexion
    Application(backend="uia").start(f'"{EXE_PATH}"')

    def fenetre_connexion():
        # Parmi toutes les fenêtres « Steel Projects », garde celle qui contient « Identification »
        for w in DESKTOP.windows(title_re=".*Steel Projects.*"):
            spec = DESKTOP.window(handle=w.handle)
            if spec.child_window(auto_id="SelectUser", control_type="Window").exists(timeout=0):
                return spec
        return None

    return wait_until(timeout, 1, fenetre_connexion, None, operator.is_not)


def s_authentifier(window):
    # Saisit l'identifiant et le mot de passe dans la fenêtre « Identification », puis valide
    ident = window.child_window(auto_id="SelectUser", control_type="Window")
    attendre(ident, "exists visible", timeout=90)

    attendre(ident.child_window(auto_id="tbLogin", control_type="Edit")).set_edit_text(USERNAME)
    attendre(ident.child_window(auto_id="tbPassword", control_type="Edit")).set_edit_text(PASSWORD)

    barre = ident.child_window(auto_id="StatusBar", control_type="Pane")
    attendre(barre.child_window(title="Ok", control_type="Button")).invoke()

    ident.wait_not("exists visible", timeout=60, retry_interval=0.5)

    splash = window.child_window(auto_id="FormSplashScreen", control_type="Window")
    splash.wait_not("exists", timeout=180, retry_interval=0.5)
    attendre_appli(window, timeout=120)
    log.info("Connexion réussie")


def importer_tekla(window, dossier_projet):
    # Importe les fichiers XML Tekla du projet donné et valide les fenêtres d'import
    chemin_xml = os.path.join(dossier_projet, "*.XML")

    bouton_import = window.child_window(title="Import", control_type="Button")
    cliquer(bouton_import)
    cliquer_menu(bouton_import, "TEKLA_XML")

    tekla = DESKTOP.window(title_re=".*Importation Tekla.*")
    attendre(tekla, "exists visible")

    repertoire = tekla.child_window(title="Répertoire", auto_id="1001", control_type="Edit")
    attendre(repertoire).click_input()
    repertoire.set_edit_text("")
    repertoire.type_keys(echapper_keys(chemin_xml), with_spaces=True)
    cliquer(tekla.child_window(title="Ok", auto_id="1", control_type="Button"))

    ok_validation = window.child_window(title="Ok", control_type="Button", best_match="Button3")
    cliquer_avec_comparaison(window, ok_validation, timeout=600)
    cliquer_avec_comparaison(window, window.child_window(title="Ajouter", control_type="Button"), timeout=3600)
    cliquer_avec_comparaison(window, ok_validation, timeout=3600)

    finir_import(window)


def finir_import(window, timeout=3600):
    # Attend la fin de l'import (la comparaison de profils est validée si elle apparaît),
    # puis clique sur Ok final
    dialog = window.child_window(auto_id="FormConfigLog", control_type="Window")
    barre_ok = dialog.child_window(auto_id="bar1", control_type="ToolBar")
    ok_final = barre_ok.child_window(title="Ok", control_type="Button")

    cliquer_avec_comparaison(window, ok_final, timeout=timeout)
    dialog.wait_not("exists", timeout=60, retry_interval=0.2)


def ouvrir_gestion_production(window):
    # Ouvre l'écran Gestion de production
    cliquer(window.child_window(title="Gestion de production", control_type="Button"))
    toolbar = window.child_window(auto_id="toolBar", control_type="ToolBar", found_index=0)
    attendre(toolbar, "exists visible", timeout=60)


def quitter_gestion_production(window, timeout=60):
    # Ferme l'écran Gestion de production (Ctrl+Q) et vérifie qu'il est bien fermé
    attendre_appli(window)
    window.set_focus()
    send_keys("^q")
    try:
        wait_until(timeout, 0.5, lambda: "Gestion de production" not in window.window_text())
    except DelaiDepasse:
        raise RuntimeError("L'écran Gestion de production ne s'est pas fermé avec Ctrl+Q")
    attendre_appli(window)


def ouvrir_gestion_affaires(window):
    # Ouvre l'écran Gestion d'Affaires et attend qu'il soit réellement chargé
    window.set_focus()
    cliquer(window.child_window(title="Gestion d'Affaires", control_type="Button"))
    wait_until(120, 0.5, lambda: "Gestion d'Affaires" in window.window_text())
    attendre_appli(window, timeout=120)


def filtrer_par_affaire(window, affaire, timeout=30):
    # Filtre la liste sur l'affaire donnée (nom du sous-dossier du projet)
    window.set_focus()
    send_keys("^{F3}")
    attendre_appli(window)

    def champ_filtre():
        # Premier champ de saisie d'une barre « toolBar » visible
        try:
            for tb in window.wrapper_object().descendants(control_type="ToolBar"):
                if tb.automation_id() == "toolBar" and tb.is_visible():
                    edits = tb.children(control_type="Edit")
                    if edits and edits[0].is_visible():
                        return edits[0]
        except COMError:
            pass  # appli occupée : on réessaie
        return None

    filtre = wait_until(timeout, 0.5, champ_filtre, None, operator.is_not)
    filtre.click_input()
    filtre.type_keys("^a{BACKSPACE}" + echapper_keys(affaire) + "{ENTER}", with_spaces=True)
    attendre_appli(window)


def filtre_par_phase(window):
    # Passe sur la vue Phase (Ctrl+F4)
    window.set_focus()
    send_keys("^{F4}")
    attendre_appli(window)


def filtrer_parrepere_secondaire(window):
    # Passe sur la vue Repère secondaire (Ctrl+F6)
    window.set_focus()
    send_keys("^{F6}")


def ajouter_scribing(window):
    # Ajoute le scribing à toutes les pièces et attend la fin du traitement
    window.set_focus()
    send_keys("^a")
    window.right_click_input()
    attendre_appli(window)
    send_keys("{DOWN 10}{ENTER}")
    attendre_appli(window)
    send_keys("{DOWN 11}{ENTER}")

    cliquer(window.child_window(auto_id="cbxAddPositioningMark", control_type="Pane"))
    cliquer(window.child_window(title="Ok", control_type="Button"))
    cliquer(window.child_window(title_re="Appliquer . tous", control_type="Pane"), timeout=600)
    cliquer(window.child_window(title="Non", control_type="Button"))

    barre = window.child_window(auto_id="barStatus", control_type="Pane")
    annuler = barre.child_window(title="Annuler", control_type="Button")
    annuler.wait("exists visible", timeout=30)
    annuler.wait_not("exists visible", timeout=18000, retry_interval=1)


def selectionner_phases(window):
    # Sélectionne les lignes dont la phase est entre PHASE_MIN et PHASE_MAX
    grille = trouver_grille(window)

    premiere = True
    for ligne in grille.children(control_type="Custom"):
        if ligne.window_text() == "Ligne du haut":
            continue

        phase = ""
        for c in ligne.children(control_type="Edit"):
            if c.window_text().startswith("Phase "):
                phase = (c.get_value() or "").strip()

        if phase.isdigit() and PHASE_MIN <= int(phase) < PHASE_MAX:
            case = ligne.children(control_type="Header")[0]
            if premiere:
                case.click_input()
                premiere = False
            else:
                case.click_input(pressed="control")
            log.info("Phase sélectionnée : %s", phase)

    if premiere:
        log.info("Aucune phase entre %s et %s", PHASE_MIN, PHASE_MAX)


def modifier_repere_secondaire(window):
    # Écrit COMMENTAIRE_2 dans tous les repères secondaires
    attendre_appli(window)
    send_keys("^{F6}")
    attendre_appli(window)

    grille = trouver_grille(window, "Profil")
    focus_premiere_ligne(grille)
    send_keys("^a{ENTER}")
    remplir_commentaire_2(window, COMMENTAIRE_2)


def commentaire_gr(window):
    # Phases > PHASE_SEUIL_GR, puis repères secondaires dont le profil contient « _ » : Commentaire 2 = GR
    filtre_par_phase(window)
    grille = trouver_grille(window, "Phase")
    log.info("--- Phases lues ---")
    afficher_colonne(grille, "Phase")

    n = selectionner_lignes(grille, "Phase", lambda v: v.isdigit() and int(v) >= PHASE_SEUIL_GR)
    log.info("%d phase(s) >= %s sélectionnée(s)", n, PHASE_SEUIL_GR)
    if n == 0:
        return

    attendre_appli(window)
    send_keys("^{F6}")
    attendre_appli(window)

    grille = trouver_grille(window, "Profil")
    log.info("--- Profils lus ---")
    afficher_colonne(grille, "Profil")

    n = selectionner_lignes(grille, "Profil", lambda v: "_" in v)
    log.info("%d repère(s) secondaire(s) avec « _ » dans le profil", n)
    if n == 0:
        return

    send_keys("{ENTER}")
    remplir_commentaire_2(window, COMMENTAIRE_GR)

def lister_apercus():
    # Toutes les fenêtres « Aperçu x/y » ouvertes (il peut y en avoir plusieurs)
    try:
        return DESKTOP.windows(title_re=TITRE_APERCU, top_level_only=True)
    except Exception:
        return []


def fermer_toutes_apercus(timeout=60):
    # Ferme toutes les fenêtres « Aperçu x/y », sans jamais s'appuyer sur une fenêtre unique
    handles = [w.handle for w in lister_apercus()]
    if not handles:
        log.info("Aucune fenêtre d'aperçu à fermer")
        return

    log.info("%d fenêtre(s) d'aperçu à fermer", len(handles))
    for handle in handles:
        try:
            DESKTOP.window(handle=handle).wrapper_object().close()  # demande la fermeture (WM_CLOSE)
            wait_until(timeout, 0.5, lambda h=handle: not ctypes.windll.user32.IsWindow(h))
        except Exception:
            # La fenêtre a pu se fermer toute seule entre-temps : on continue
            log.info("Fenêtre d'aperçu déjà fermée ou non fermable (handle %s)", handle)
    log.info("Fenêtre(s) d'aperçu traitée(s)")


def fermer_apercu(timeout=60):
    # Ferme les fenêtres « Aperçu » ouvertes par Action, une fois le PDF enregistré
    fermer_toutes_apercus(timeout)


def impression(window, affaire):
    # Ouvre Gestion d'Affaires, filtre sur l'affaire, sélectionne tout, Fiche de débit + Action, puis PDF
    ouvrir_gestion_affaires(window)
    filtrer_par_affaire(window, affaire)
    filtrer_parrepere_secondaire(window)
    attendre_appli(window)

    # Nettoyage : aucune fenêtre d'aperçu résiduelle avant d'en ouvrir une nouvelle
    fermer_toutes_apercus()

    focus_grille_haut(window)
    send_keys("^a")
    attendre_appli(window)

    # Mettre en sélection : raccourci Maj+Inser
    window.set_focus()
    send_keys("+{INSERT}")
    attendre_appli(window)

    barre_droite = window.child_window(auto_id="barDroite", control_type="Pane")
    fiche_debit = barre_droite.child_window(control_type="Button", found_index=0)
    action = barre_droite.child_window(control_type="Button", found_index=5)
    attendre(action, "exists visible")

    # Action grisée = Fiche de débit non sélectionnée : on la sélectionne d'abord
    if not action.is_enabled():
        cliquer(fiche_debit)
        action.wait("enabled", timeout=30, retry_interval=0.2)

    cliquer(action)
    attendre_appli(window)

    # Fenêtre « Aperçu x/y » ouverte par Action : on prend la plus récente (évite l'ambiguïté)
    apercus = wait_until(60, 0.5, lambda: lister_apercus() or None, None, operator.is_not)
    if len(apercus) > 1:
        log.warning("%d fenêtres d'aperçu détectées, la dernière est utilisée", len(apercus))
    apercu = DESKTOP.window(handle=apercus[-1].handle)
    attendre(apercu, "exists visible", timeout=60)

    # Fichier > Imprimer tout
    menu = apercu.child_window(title="Application", control_type="MenuBar")
    cliquer(menu.child_window(title="Fichier", control_type="MenuItem"))

    # « Imprimer tout » : ID de commande MFC 32775 (le menu apparaît deux fois dans l'arborescence)
    imprimer_tout = apercu.child_window(auto_id="32775", control_type="MenuItem", found_index=0)
    cliquer(imprimer_tout)
    enregistrer_pdf(affaire)


def revenir_steel_projects(window):
    # Redonne le focus à la fenêtre principale Steel Projects
    window.set_focus()
    attendre_appli(window)


def quitter_gestion_affaires(window, timeout=60):
    # Ferme l'écran Gestion d'Affaires (Ctrl+Q) et contrôle le titre
    attendre_appli(window)
    window.set_focus()
    send_keys("^q")
    try:
        wait_until(timeout, 0.5, lambda: TITRE_GESTION_AFFAIRES not in window.window_text())
    except DelaiDepasse:
        raise RuntimeError("L'écran Gestion d'Affaires ne s'est pas fermé avec Ctrl+Q")
    attendre_appli(window)
    log.info("Gestion d'Affaires fermée")


# ===== WORKFLOW PAR PROJET =====
def lister_projets(dossier_racine):
    # Un projet = un sous-dossier contenant au moins un fichier XML (trié par nom)
    def contient_xml(dossier):
        return any(f.upper().endswith(".XML") for f in os.listdir(dossier))

    projets = [os.path.join(dossier_racine, nom) for nom in sorted(os.listdir(dossier_racine))]
    projets = [p for p in projets if os.path.isdir(p) and contient_xml(p)]

    # Cas particulier : le dossier choisi est lui-même un projet (XML directement dedans)
    if not projets and contient_xml(dossier_racine):
        projets = [dossier_racine]
    return projets


def traiter_projet(window, dossier_projet):
    # Enchaîne toutes les étapes pour UN projet (une affaire)
    affaire = os.path.basename(dossier_projet)
    log.info("=== Début du projet %s ===", affaire)

    importer_tekla(window, dossier_projet)
    ouvrir_gestion_production(window)
    filtrer_par_affaire(window, affaire)
    filtre_par_phase(window)
    ajouter_scribing(window)
    selectionner_phases(window)
    modifier_repere_secondaire(window)
    commentaire_gr(window)
    quitter_gestion_production(window)
    impression(window, affaire)
    fermer_apercu()
    revenir_steel_projects(window)
    quitter_gestion_affaires(window)

    log.info("=== Fin du projet %s ===", affaire)


def recuperer_apres_erreur(window):
    # Meilleur effort pour revenir à l'écran principal après un échec, sans jamais quitter l'appli
    try:
        fermer_apercu(timeout=10)
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
        revenir_steel_projects(window)
    except Exception:
        log.warning("Impossible de revenir sur la fenêtre principale")


def appliquer_configuration(cfg):
    # Recopie les paramètres saisis dans l'interface dans les constantes utilisées par les étapes
    global USERNAME, PASSWORD, EXE_PATH, PHASE_MIN, PHASE_MAX
    global COMMENTAIRE_2, PHASE_SEUIL_GR, COMMENTAIRE_GR
    USERNAME = cfg["utilisateur"]
    PASSWORD = cfg["mot_de_passe"]
    EXE_PATH = cfg["exe"]
    PHASE_MIN = cfg["phase_min"]
    PHASE_MAX = cfg["phase_max"]
    COMMENTAIRE_2 = cfg["commentaire_2"]
    PHASE_SEUIL_GR = cfg["seuil_gr"]
    COMMENTAIRE_GR = cfg["commentaire_gr"]


def executer_workflow(projets, stop_event, messages):
    # Tourne dans un thread séparé : connexion une seule fois, puis boucle projet par projet
    try:
        comtypes.CoInitialize()  # obligatoire pour UIA dans un thread autre que le principal
    except Exception:
        pass

    reussis, echoues = [], []
    try:
        window = lancer_application()
        s_authentifier(window)

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

        # 3. Projets (sélection multiple)
        cadre = ttk.LabelFrame(self, text="3. Projets trouvés (sélectionnez ceux à traiter)")
        cadre.grid(row=3, column=0, sticky="nsew", **marge)
        cadre.columnconfigure(0, weight=1)
        cadre.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(cadre, columns=("projet", "xml", "statut"), show="headings",
                                 selectmode="extended")
        self.tree.heading("projet", text="Projet (affaire)")
        self.tree.heading("xml", text="Fichiers XML")
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

    def actualiser_projets(self):
        dossier = self.var_dossier.get().strip()
        if not os.path.isdir(dossier):
            messagebox.showerror("Dossier introuvable", f"Ce dossier n'existe pas :\n{dossier}", parent=self)
            return

        for iid in self.tree.get_children():
            self.tree.delete(iid)

        projets = lister_projets(dossier)
        for chemin in projets:
            nb_xml = sum(1 for f in os.listdir(chemin) if f.upper().endswith(".XML"))
            self.tree.insert("", "end", iid=chemin,
                             values=(os.path.basename(chemin), nb_xml, "En attente"))
        self.tree.selection_set(projets)  # tous sélectionnés par défaut

        self.var_statut.set(f"{len(projets)} projet(s) trouvé(s)")
        if not projets:
            messagebox.showwarning("Aucun projet",
                                   "Aucun sous-dossier contenant des fichiers XML n'a été trouvé.",
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
                "phase_min": int(self.var_phase_min.get()),
                "phase_max": int(self.var_phase_max.get()),
                "commentaire_2": self.var_com2.get().strip(),
                "seuil_gr": int(self.var_seuil_gr.get()),
                "commentaire_gr": self.var_com_gr.get().strip(),
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