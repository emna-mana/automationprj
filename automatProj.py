import ctypes
import operator
import os
from datetime import datetime
import time

from _ctypes import COMError
from pywinauto import Desktop
from pywinauto.application import Application
from pywinauto.keyboard import send_keys
from pywinauto.timings import TimeoutError as DelaiDepasse
from pywinauto.timings import wait_until
from pywinauto.uia_defines import get_elem_interface
import configuration

# ===== CONFIGURATION =====
CHEMINS = configuration.charger_chemins()
USERNAME = os.environ.get("STEEL_PROJECTS_USERNAME", "")
PASSWORD = os.environ.get("STEEL_PROJECTS_PASSWORD", "")
EXE_PATH = CHEMINS["steel_projects_exe"]
IMPORT_DIRECTORY = os.path.join(CHEMINS["dossier_sources"], "02XY")
AFFAIRE = os.path.basename(os.path.normpath(IMPORT_DIRECTORY))
DOSSIER_PROJETS_TRAVAILLER = CHEMINS["dossier_projets"]

PHASE_MIN = 130
PHASE_MAX = 140
COMMENTAIRE_2 = "PU"

PHASE_SEUIL_GR = 700    # phases strictement supérieures à ce seuil
COMMENTAIRE_GR = "GR"   # commentaire 2 des repères secondaires dont le profil contient « _ »

DESKTOP = Desktop(backend="uia")

# Titres des fenêtres (regroupés ici pour être corrigés facilement)
TITRE_APERCU = r"Aper.u \d+/\d+"
TITRE_GESTION_AFFAIRES = "Gestion d'Affaires"

# ===== OUTILS =====
def attendre(ctrl, etat="exists visible enabled", timeout=30):
    # Attend qu'un contrôle soit dans l'état voulu, puis le renvoie
    ctrl.wait(etat, timeout=timeout, retry_interval=0.2)
    return ctrl

def echapper_keys(texte):
    # Entoure de accolades les caractères spéciaux de type_keys pour qu'ils soient tapés tels quels
    return "".join("{" + c + "}" if c in "+^%~(){}[]" else c for c in texte)

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
    print("Comparaison de profils validée")
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
            # Interface d'accessibilité de la ligne
            legacy = get_elem_interface(ligne.element_info.element, "LegacyIAccessible")
            # 1re ligne : remplace la sélection et donne le focus à la grille (0x2 + 0x1)
            # lignes suivantes : ajout à la sélection (0x8)
            legacy.Select(0x3 if n == 0 else 0x8)
            n += 1
    return n

def afficher_colonne(grille, colonne):
    # Diagnostic : affiche la valeur de la colonne pour chaque ligne de la grille
    for ligne in grille.children(control_type="Custom"):
        if ligne.window_text() != "Ligne du haut":
            print(f"  {ligne.window_text()} | {colonne} = {valeur_cellule(ligne, colonne)!r}")


def remplir_commentaire_2(window, texte):
    # Fenêtre d'édition des repères (ouverte par Entrée) : écrit texte dans Commentaire 2, valide, quitte
    repere = window.child_window(auto_id="SpForm", control_type="Window")
    attendre(repere, "exists visible")

    onglets = repere.child_window(auto_id="tsGeneral", control_type="Pane")
    cliquer(onglets.child_window(control_type="TreeItem", found_index=3))

    com2 = attendre(repere.child_window(auto_id="tbCom2", control_type="Edit"))
    com2.click_input()
    com2.type_keys("^a{BACKSPACE}" + texte, with_spaces=True)

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


def dossier_affaire_pdf():
    # Dossier de l'affaire : DOSSIER_PROJETS_TRAVAILLER\<AFFAIRE>, créé s'il n'existe pas
    dossier = os.path.join(DOSSIER_PROJETS_TRAVAILLER, AFFAIRE)

    if not os.path.isdir(dossier):
        os.makedirs(dossier)
        print("Dossier créé :", dossier)
    return dossier

def enregistrer_pdf(timeout=120):
    # Remplit la boîte « Enregistrer le fichier PDF sous » avec « AFFAIRE PLM.pdf » dans le dossier de l'affaire
    chemin = os.path.join(dossier_affaire_pdf(), f"{AFFAIRE} PLM.pdf")

    boite = DESKTOP.window(title="Enregistrer le fichier PDF sous")
    attendre(boite, "exists visible", timeout=timeout)
    handle = boite.wrapper_object().handle
    boite = DESKTOP.window(handle=handle)

    # Attend que la boîte réponde (Steel Projects peut être occupé pendant la génération du PDF)
    wait_until(300, 1, lambda: not ctypes.windll.user32.IsHungAppWindow(handle))

    # Ramène la boîte au premier plan : elle peut être cachée derrière la fenêtre de l'appli
    boite.set_focus()

    # Champ « Nom du fichier » (control_type obligatoire : la barre d'adresse a aussi l'auto_id 1001)
    nom = attendre(boite.child_window(auto_id="1001", control_type="Edit"))
    nom.set_edit_text(chemin)
    wait_until(10, 0.2, lambda: (nom.get_value() or "") == chemin)

    # Reprend le focus avant le clic, puis clique sur Enregistrer
    boite.set_focus()
    cliquer(boite.child_window(auto_id="1", control_type="Button"))

    # Si le fichier existe déjà, Windows demande confirmation : on répond Oui
    confirmer = DESKTOP.window(title_re="Confirmer l.enregistrement.*")
    if confirmer.exists(timeout=3):
        cliquer(confirmer.child_window(title="Oui", control_type="Button"))

    # Attend la fermeture de la boîte, puis vérifie que le PDF existe
    wait_until(60, 0.5, lambda: not ctypes.windll.user32.IsWindow(handle))
    wait_until(300, 1, lambda: os.path.exists(chemin))
    print("PDF enregistré :", chemin)
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

    # Bouton Ok de la barre du bas, cliqué sans souris (insensible au splash screen et à Verr. Maj)
    barre = ident.child_window(auto_id="StatusBar", control_type="Pane")
    attendre(barre.child_window(title="Ok", control_type="Button")).invoke()

    # Attend la fermeture de la fenêtre Identification (connexion réussie)
    ident.wait_not("exists visible", timeout=60, retry_interval=0.5)

    # Attend la fin du chargement : l'écran de démarrage se ferme, puis l'appli se calme
    splash = window.child_window(auto_id="FormSplashScreen", control_type="Window")
    splash.wait_not("exists", timeout=180, retry_interval=0.5)
    attendre_appli(window, timeout=120)


def importer_tekla(window, dossier_xml):
    # Importe les fichiers XML Tekla du dossier donné et valide les fenêtres d'import
    chemin_xml = os.path.join(dossier_xml, "*.XML")

    bouton_import = window.child_window(title="Import", control_type="Button")
    cliquer(bouton_import)
    cliquer_menu(bouton_import, "TEKLA_XML")

    tekla = DESKTOP.window(title_re=".*Importation Tekla.*")
    attendre(tekla, "exists visible")

    # Clic dans le champ « Répertoire », vidage (Ctrl+A puis Retour arrière), puis saisie du chemin complet
    repertoire = tekla.child_window(title="Répertoire", auto_id="1001", control_type="Edit")
    attendre(repertoire).click_input()
    repertoire.type_keys("^a{BACKSPACE}" + chemin_xml, with_spaces=True)

    # Vérifie que le champ contient bien le chemin complet avant de valider
    wait_until(10, 0.2, lambda: (repertoire.get_value() or "").strip().upper() == chemin_xml.upper())

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

    # L'écran est ouvert quand le titre devient « Steel Projects - Gestion d'Affaires »
    wait_until(120, 0.5, lambda: "Gestion d'Affaires" in window.window_text())
    attendre_appli(window, timeout=120)


def filtrer_par_affaire(window, timeout=30):
    # Filtre la liste sur l'affaire en cours
    window.set_focus()
    send_keys("^{F3}")
    attendre_appli(window)  # laisse la nouvelle vue se charger avant de chercher le champ

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
    filtre.type_keys(f"^a{{BACKSPACE}}{AFFAIRE}{{ENTER}}", with_spaces=True)
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
            print("Phase sélectionnée :", phase)

    if premiere:
        print(f"Aucune phase entre {PHASE_MIN} et {PHASE_MAX}")


def modifier_repere_secondaire(window):
    # Écrit COMMENTAIRE_2 dans tous les repères secondaires
    attendre_appli(window)
    send_keys("^{F6}")
    attendre_appli(window)

    # Attend que la grille des repères secondaires (colonne Profil) soit chargée, puis lui donne le focus
    grille = trouver_grille(window, "Profil")
    focus_premiere_ligne(grille)
    send_keys("^a{ENTER}")
    remplir_commentaire_2(window, COMMENTAIRE_2)


def commentaire_gr(window):
    # Phases > PHASE_SEUIL_GR, puis repères secondaires dont le profil contient « _ » : Commentaire 2 = GR
    filtre_par_phase(window)  # vue Phase (Ctrl+F4)
    grille = trouver_grille(window, "Phase")
    print("--- Phases lues ---")
    afficher_colonne(grille, "Phase")

    n = selectionner_lignes(grille, "Phase", lambda v: v.isdigit() and int(v) >= PHASE_SEUIL_GR)
    print(f"{n} phase(s) >= {PHASE_SEUIL_GR} sélectionnée(s)")
    if n == 0:
        return

    attendre_appli(window)
    send_keys("^{F6}")  # vue Repère secondaire des phases sélectionnées
    attendre_appli(window)

    grille = trouver_grille(window, "Profil")
    print("--- Profils lus ---")
    afficher_colonne(grille, "Profil")

    n = selectionner_lignes(grille, "Profil", lambda v: "_" in v)
    print(f"{n} repère(s) secondaire(s) avec « _ » dans le profil")
    if n == 0:
        return

    send_keys("{ENTER}")  # ouvre la fenêtre d'édition pour les lignes sélectionnées
    remplir_commentaire_2(window, COMMENTAIRE_GR)


def impression(window):
    # Ouvre Gestion d'Affaires, filtre, met tout en sélection, Fiche de débit + Action, puis PDF
    ouvrir_gestion_affaires(window)
    filtrer_par_affaire(window)
    filtrer_parrepere_secondaire(window)
    attendre_appli(window)

    # Focus dans la grille des repères secondaires, puis sélection de toutes les lignes
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

    # Fenêtre « Aperçu x/y » ouverte par Action : Fichier > Imprimer tout
    apercu = DESKTOP.window(title_re=r"Aper.u \d+/\d+")
    attendre(apercu, "exists visible", timeout=60)
    menu = apercu.child_window(title="Application", control_type="MenuBar")
    cliquer(menu.child_window(title="Fichier", control_type="MenuItem"))

    # « Imprimer tout » : ID de commande MFC 32775 (le menu apparaît deux fois dans l'arborescence)
    imprimer_tout = apercu.child_window(auto_id="32775", control_type="MenuItem", found_index=0)
    cliquer(imprimer_tout)
    enregistrer_pdf()


def fermer_apercu(timeout=60):
    # Ferme toutes les fenêtres « Aperçu x/y » ouvertes, une fois le PDF enregistré
    apercus = DESKTOP.windows(title_re=TITRE_APERCU)
    if not apercus:
        print("Aucune fenêtre d'aperçu à fermer")
        return

    handles = [w.handle for w in apercus]
    for w in apercus:
        w.close()  # demande la fermeture (WM_CLOSE)

    # Attend que toutes les fenêtres aient réellement disparu
    for handle in handles:
        wait_until(timeout, 0.5, lambda h=handle: not ctypes.windll.user32.IsWindow(h))
    print(f"{len(handles)} fenêtre(s) d'aperçu fermée(s)")


def revenir_steel_projects(window, timeout=300):
    # Attend que Steel Projects réponde de nouveau (il peut rester occupé après l'impression),
    # puis lui redonne le focus
    handle = window.wrapper_object().handle
    wait_until(timeout, 1, lambda: not ctypes.windll.user32.IsHungAppWindow(handle))
    window.set_focus()
    attendre_appli(window)


def quitter_gestion_affaires(window, timeout=60):
    # Ferme l'écran Gestion d'Affaires (Ctrl+Q, hypothèse à vérifier) et contrôle le titre
    attendre_appli(window)
    window.set_focus()
    send_keys("^q")
    try:
        wait_until(timeout, 0.5, lambda: TITRE_GESTION_AFFAIRES not in window.window_text())
    except DelaiDepasse:
        raise RuntimeError("L'écran Gestion d'Affaires ne s'est pas fermé avec Ctrl+Q")
    attendre_appli(window)
    print("Gestion d'Affaires fermée")


# ===== SCRIPT PRINCIPAL =====
def main_complet():
    # Enchaîne toutes les étapes du workflow
    window = lancer_application()

    s_authentifier(window)
    # importer_tekla(window, IMPORT_DIRECTORY)    #/ importer_CAM3D(window)
    # ouvrir_gestion_production(window)
    # filtrer_par_affaire(window)
    # filtre_par_phase(window)
    # ajouter_scribing(window)
    # selectionner_phases(window)
    # modifier_repere_secondaire(window)
    # commentaire_gr(window)
    # quitter_gestion_production(window)
    impression(window)
    fermer_apercu()
    revenir_steel_projects(window)
    quitter_gestion_affaires(window)


if __name__ == "__main__":
    main_complet()    