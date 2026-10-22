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

import affectation_machine
from conversion_fer_plat import convertir_fers_plats
import corection_scribing
import claude


# ===== CONFIGURATION =====
USERNAME = "EBA"
PASSWORD = "EBA2026"
EXE_PATH = r"C:\Program Files (x86)\SteelProjects\Sp.Plm\Sp.Plm.exe"
IMPORT_DIRECTORY = r"C:\Users\E.BENAMOR\Desktop\projetsAtravailler\02XY"
AFFAIRE = IMPORT_DIRECTORY.split("\\")[-1]   # transmise à claude pour la comparaison
DOSSIER_PROJETS_TRAVAILLER = claude.DOSSIER_PROJETS  # même dossier que celui lu par claude
PHASE_MIN = 130
PHASE_MAX = 140
COMMENTAIRE_2 = "PU"

PHASE_SEUIL_GR = 700    # phases strictement supérieures à ce seuil
COMMENTAIRE_GR = "GR"   # commentaire 2 des repères secondaires dont le profil contient « _ »

DESKTOP = Desktop(backend="uia")

# Titres des fenêtres (regroupés ici pour être corrigés facilement)
TITRE_APERCU = r"Aper.u \d+/\d+"
TITRE_GESTION_AFFAIRES = "Gestion d'Affaires"
TITRE_BOITE_PDF = "Enregistrer le fichier PDF sous"

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


def cliquer_sans_souris(ctrl, timeout=30):
    # invoke() : clic sans souris, insensible aux fenêtres posées par-dessus (Claude, Acrobat, Excel)
    ctrl = attendre(ctrl, timeout=timeout)
    try:
        ctrl.invoke()
    except Exception:
        ctrl.click_input()   # contrôle sans interface Invoke : clic souris comme avant


def titre_premier_plan():
    # Titre de la fenêtre au premier plan (diagnostic quand un écran ne s'ouvre pas)
    try:
        return DESKTOP.window(handle=ctypes.windll.user32.GetForegroundWindow()).window_text()
    except Exception:
        return "?"


def saisir_texte(champ, texte, essais=3):
    # Remplit un champ par une VRAIE frappe clavier, puis vérifie son contenu (jusqu'à « essais » fois).
    # set_edit_text seul ne suffit pas : les boîtes Tekla et « Enregistrer sous » ne tiennent compte
    # que de la frappe. Et Ctrl+A ne vidait pas toujours le champ : vidage sans clavier d'abord.
    attendre(champ)

    def correct():
        return (champ.get_value() or "").strip().upper() == texte.upper()

    for essai in range(1, essais + 1):
        champ.set_edit_text("")
        champ.click_input()
        champ.type_keys(echapper_keys(texte), with_spaces=True, pause=0.02)
        try:
            wait_until(5, 0.2, correct)
            return
        except DelaiDepasse:
            print(f"Champ incorrect (essai {essai}/{essais}) : {champ.get_value()!r}")
    raise RuntimeError(f"Champ incorrect : {champ.get_value()!r} au lieu de {texte!r}")


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
    debut = time.time()  # le PDF retenu doit être écrit après cet instant (pas un ancien fichier)

    # Handle par l'API Windows (FindWindow) et non par UIA : pendant la génération du PDF
    # la boîte ne répond pas, et une recherche UIA échoue (ElementNotFoundError)
    def boite_visible():
        h = ctypes.windll.user32.FindWindowW(None, TITRE_BOITE_PDF)
        return h if h and ctypes.windll.user32.IsWindowVisible(h) else None
    handle = wait_until(timeout, 0.5, boite_visible, None, operator.is_not)

    # Attend que la boîte réponde (Steel Projects peut être occupé pendant la génération du PDF)
    wait_until(300, 1, lambda: not ctypes.windll.user32.IsHungAppWindow(handle))
    boite = DESKTOP.window(handle=handle)

    # Ramène la boîte au premier plan : elle peut être cachée derrière la fenêtre de l'appli
    boite.set_focus()

    # Champ « Nom du fichier » (control_type obligatoire : la barre d'adresse a aussi l'auto_id 1001)
    # Frappe réelle : avec set_edit_text, la boîte gardait son nom par défaut
    # (« Steel-Projects PLM.pdf » dans « Impressions Steel Projects »)
    nom = boite.child_window(auto_id="1001", control_type="Edit")
    saisir_texte(nom, chemin)

    # Reprend le focus avant le clic, puis clique sur Enregistrer
    boite.set_focus()
    cliquer(boite.child_window(auto_id="1", control_type="Button"))

    # Attend la fermeture de la boîte. Si Windows demande « Confirmer l'enregistrement »
    # (à tout moment de l'attente) : Oui seulement si c'est bien notre fichier, sinon Non et arrêt
    nom_fichier = os.path.basename(chemin)
    fin = time.time() + 60
    while ctypes.windll.user32.IsWindow(handle):
        if time.time() > fin:
            raise RuntimeError("La boîte « Enregistrer le fichier PDF sous » ne s'est pas fermée")
        confirmer = DESKTOP.window(title_re="Confirmer l.enregistrement.*")
        try:
            if confirmer.exists(timeout=0):
                message = " ".join(t.window_text() for t in confirmer.descendants(control_type="Text"))
                if nom_fichier.lower() in message.lower():
                    cliquer(confirmer.child_window(title="Oui", control_type="Button"))
                    print("Ancien PDF remplacé :", nom_fichier)
                else:
                    cliquer(confirmer.child_window(title="Non", control_type="Button"))
                    raise RuntimeError(f"Enregistrement refusé, mauvais fichier : {message!r} (attendu : {chemin})")
        except COMError:
            pass  # boîte en cours de fermeture : on réessaie
        time.sleep(0.5)

    # Puis un PDF écrit pendant ce lancement
    # (si l'ancien PDF existait déjà, os.path.exists seul était vrai tout de suite)
    wait_until(300, 1, lambda: os.path.exists(chemin) and os.path.getmtime(chemin) >= debut - 2)

    # Attend que la taille ne bouge plus : PDF entièrement écrit
    taille = -1
    while taille != os.path.getsize(chemin):
        taille = os.path.getsize(chemin)
        time.sleep(2)
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

    # Champ « Répertoire » : la fenêtre ne sélectionne les .XML que sur une vraie frappe clavier
    repertoire = tekla.child_window(title="Répertoire", auto_id="1001", control_type="Edit")
    saisir_texte(repertoire, chemin_xml)

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
    window.set_focus()
    cliquer_sans_souris(window.child_window(title="Gestion de production", control_type="Button"))
    toolbar = window.child_window(auto_id="toolBar", control_type="ToolBar", found_index=0)
    try:
        attendre(toolbar, "exists visible", timeout=60)
    except DelaiDepasse:
        raise RuntimeError("Gestion de production ne s'est pas ouverte "
                           f"(fenêtre au premier plan : {titre_premier_plan()!r})")


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
    cliquer_sans_souris(window.child_window(title=TITRE_GESTION_AFFAIRES, control_type="Button"))

    # L'écran est ouvert quand le titre devient « Steel Projects - Gestion d'Affaires »
    try:
        wait_until(120, 0.5, lambda: TITRE_GESTION_AFFAIRES in window.window_text())
    except DelaiDepasse:
        raise RuntimeError("Gestion d'Affaires ne s'est pas ouverte "
                           f"(fenêtre au premier plan : {titre_premier_plan()!r})")
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
    return enregistrer_pdf()


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


def fermer_pdf_ouverts(chemin_pdf, timeout=60, attente=15):
    # Ferme les visionneuses (Acrobat, Edge...) ouvertes automatiquement sur le PDF enregistré :
    # fenêtres dont le titre contient le nom du fichier
    # attente : temps laissé à la visionneuse pour s'ouvrir avant de conclure qu'aucun PDF n'est ouvert
    nom = os.path.splitext(os.path.basename(chemin_pdf))[0].lower()

    def fenetres_pdf():
        return [w for w in DESKTOP.windows() if nom in w.window_text().lower()] or None

    try:
        fenetres = wait_until(attente, 0.5, fenetres_pdf, None, operator.is_not)  # laisse la visionneuse s'ouvrir
    except DelaiDepasse:
        print("Aucun PDF ouvert à fermer")
        return

    # Ctrl+W ferme seulement l'onglet du PDF : fermer la fenêtre entière fait demander à Acrobat
    # « fermer tous les onglets ou l'onglet actif ? » quand d'autres onglets sont ouverts
    for _ in range(len(fenetres)):
        fenetre = fenetres_pdf()
        if not fenetre:
            break
        fenetre[0].set_focus()
        send_keys("^w")
        time.sleep(1)

    try:
        wait_until(timeout, 0.5, lambda: fenetres_pdf() is None)
    except DelaiDepasse:
        raise RuntimeError(f"Le PDF est toujours ouvert : {[w.window_text() for w in fenetres_pdf() or []]}")
    print(f"{len(fenetres)} PDF fermé(s)")


def fermer_visionneuses(fichiers, timeout=60):
    # Ferme les PDF/classeurs ouverts par les téléchargements de Claude.
    # Acrobat ouvre tout en onglets d'UNE fenêtre dont le titre ne montre que l'onglet actif :
    # on répète Ctrl+W tant qu'une fenêtre porte le nom d'un des fichiers (onglet suivant ensuite).
    # Le nom téléchargé (« 02XY_CHUTES_2.pdf ») contient le nom enregistré (« 02XY_CHUTES »).
    noms = [os.path.splitext(os.path.basename(str(f)))[0].lower() for f in fichiers]
    if not noms:
        return

    def fenetres_ouvertes():
        try:
            return [w for w in DESKTOP.windows()
                    if any(n in w.window_text().lower() for n in noms)]
        except COMError:
            return []  # fenêtre en cours de fermeture : on réessaie

    excel = set()  # fenêtres Excel dont on a fermé un classeur
    fermes = 0
    fin = time.time() + timeout
    while time.time() < fin:
        fenetres = fenetres_ouvertes()
        if not fenetres:
            break
        w = fenetres[0]
        try:
            w.set_focus()
            # Ctrl+W seulement si la fenêtre est vraiment au premier plan
            # (sinon il partait vers une autre fenêtre, par exemple Excel)
            if ctypes.windll.user32.GetForegroundWindow() != w.handle:
                time.sleep(0.5)
                continue
            if w.window_text().endswith("Excel"):
                excel.add(w.handle)
            send_keys("^w")
            fermes += 1
        except Exception:
            pass  # fenêtre fermée entre-temps : on réessaie
        time.sleep(1)

    # Excel reste ouvert sans classeur (titre « Excel ») après Ctrl+W : on ferme ces fenêtres-là
    for handle in excel:
        try:
            w = DESKTOP.window(handle=handle)
            if w.exists(timeout=0) and w.window_text().strip() == "Excel":
                w.close()
        except Exception:
            pass

    restants = [w.window_text() for w in fenetres_ouvertes()]
    if restants:
        print(f"ATTENTION, fichier(s) encore ouvert(s) : {restants}")
    print(f"{fermes} fichier(s) téléchargé(s) fermé(s)")


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
    # window = DESKTOP.window(title_re=".*Steel Projects.*", found_index=0)

    s_authentifier(window)
    importer_tekla(window, IMPORT_DIRECTORY)    #/ importer_CAM3D(window)
    ouvrir_gestion_production(window)
    filtrer_par_affaire(window)
    filtre_par_phase(window)
    ajouter_scribing(window)
    selectionner_phases(window)
    modifier_repere_secondaire(window)
    commentaire_gr(window)
    quitter_gestion_production(window)
    chemin_pdf = impression(window)
    chemin_pdf = r"C:\Users\E.BENAMOR\Desktop\projetTravailler\02XY\02XY PLM.pdf"
    fermer_pdf_ouverts(chemin_pdf)
    fermer_apercu()
    revenir_steel_projects(window)
    quitter_gestion_affaires(window)

   
    # Comparaison avec Claude, une fois l'impression terminée et Steel Projects revenu à l'accueil
    print("=== Comparaison avec Claude ===")
    fichiers = claude.comparer_avec_claude(
        claude.fichiers_affaire(AFFAIRE, chemin_pdf),
        claude.dossier_sortie_affaire(AFFAIRE),
    )
    # Visionneuses (Acrobat, Excel) ouvertes par les téléchargements : elles cachaient Steel Projects
    fermer_visionneuses(fichiers)
    revenir_steel_projects(window)

    # Correction des repères « _ » : rouvre la Gestion de production sur l'affaire
    print("=== Correction scribing jarret ===")
    ouvrir_gestion_production(window)
    filtrer_par_affaire(window)
    corection_scribing.corriger_scribing_jarret(window, AFFAIRE)

    # Affectation machine (classeur de Claude) dans CMNTR1, même écran Gestion de production
    print("=== Affectation machine ===")
    affectation_machine.affectation_machine(window, AFFAIRE)
    # quitter_gestion_production(window)
    convertir_fers_plats(window,AFFAIRE)
    quitter_gestion_production(window)
    print("projet réussi")


if __name__ == "__main__":
    main_complet()    