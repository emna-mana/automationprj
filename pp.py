import ctypes
import logging
import operator
import os
from datetime import datetime
import re
import time


from _ctypes import COMError
from pywinauto import Desktop
from pywinauto import mouse
from pywinauto.application import Application
from pywinauto.keyboard import send_keys
from pywinauto.timings import TimeoutError as DelaiDepasse
from pywinauto.timings import wait_until
from pywinauto.uia_defines import get_elem_interface

import affectation_machine
from conversion_fer_plat import convertir_fers_plats
import corection_scribing
import claude
import configuration

log = logging.getLogger("workflow")

# ===== CONFIGURATION =====
USERNAME = "eba"
PASSWORD = "EBA2026"
CHEMINS = configuration.charger_chemins()
EXE_PATH = CHEMINS["steel_projects_exe"]
IMPORT_DIRECTORY = os.path.join(CHEMINS["dossier_sources"], "02IV")
AFFAIRE = os.path.basename(os.path.normpath(IMPORT_DIRECTORY))  # transmise à claude pour la comparaison
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
TITRE_BOITE_PDF = "Enregistrer le fichier PDF sous"

# ===== OUTILS =====
def attendre(ctrl, etat="exists visible enabled", timeout=30):
    # Attend qu'un contrôle soit dans l'état voulu, puis le renvoie
    if hasattr(ctrl, "wait"):
        ctrl.wait(etat, timeout=timeout, retry_interval=0.2)
    else:
        # Élément trouvé directement (wrapper) : même attente, avec les méthodes du wrapper
        wait_until(timeout, 0.2, ctrl.is_visible)   # visible seulement : Action peut rester grisé
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


def trouver_comparaison_profils_externe():
    # La comparaison de profils CAM3D est une fenêtre séparée (titre « Import ») : on la cherche sur le bureau
    for w in DESKTOP.windows(title="Import", top_level_only=True):
        try:
            entetes = w.descendants(control_type="Header")
            if any(e.window_text().startswith("Cat") for e in entetes):
                return DESKTOP.window(handle=w.handle)
        except COMError:
            pass
    return None


def valider_comparaison(window):
    # Si la fenêtre de comparaison de profils est ouverte, clique sur Ok (intégrée ou fenêtre séparée)
    comparaison = window.child_window(auto_id="FormProfileComparison", control_type="Window")
    if comparaison.exists(timeout=0):
        barre = comparaison.child_window(auto_id="stateBar", control_type="Pane")
        attendre(barre.child_window(title="Ok", control_type="Button")).invoke()
        comparaison.wait_not("exists", timeout=30, retry_interval=0.2)
    else:
        externe = trouver_comparaison_profils_externe()
        if externe is None:
            return False
        cliquer_sans_souris(externe.child_window(title="Ok", control_type="Button"))
        externe.wait_not("exists visible", timeout=30, retry_interval=0.2)
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


def trouver_fiche_repere(window, timeout=30):
    # La fiche s'ouvre soit dans la fenêtre principale, soit en fenêtre séparée (un seul repère)
    dedans = window.child_window(auto_id="SpForm", control_type="Window")
    separee = DESKTOP.window(auto_id="SpForm", top_level_only=True)

    def visible():
        for f in (dedans, separee):
            try:
                if f.exists(timeout=0) and f.is_visible():
                    return f
            except COMError:
                pass  # appli occupée : on réessaie
        return None

    return wait_until(timeout, 0.5, visible, None, operator.is_not)


def champ_commentaire_2_fiche_seule(fiche):
    # Fiche individuelle : les onglets (Commentaire, Commentaire 2...) ne sont pas exposés par leur nom.
    # 1) le champ Commentaire 2 est déjà dans l'arbre ? 2) sinon clic sur l'onglet, placé par rapport
    # à la zone de texte « Commentaire » (tbCmt1) : l'onglet Commentaire 2 est à 0,436 de sa largeur.
    champ = fiche.child_window(auto_id="tbCmt2", control_type="Edit")
    try:
        if champ.exists(timeout=1) and champ.is_visible():
            return champ
    except COMError:
        pass

    # Clic dans la zone « Commentaire » (n'importe où dedans), puis Ctrl+Tab : onglet suivant.
    # Pas de coordonnées d'onglet : le résultat ne dépend pas de la taille de la fiche.
    zone = attendre(fiche.child_window(auto_id="tbCmt1", control_type="Edit")).wrapper_object().rectangle()
    fiche.set_focus()
    # Onglets : éléments non nommés juste au-dessus de la zone « Commentaire », triés de gauche à droite.
    # Positions relatives à la zone : valables quelle que soit la taille de la fiche.
    candidats = []
    for e in fiche.wrapper_object().descendants():
        try:
            r = e.rectangle()
            if (zone.top - 30 <= r.bottom <= zone.top + 5
                    and zone.left - 5 <= r.left and r.right <= zone.right + 5
                    and 20 < r.width() < 300 and r.height() <= 40):
                candidats.append((r.left, r, e))
        except COMError:
            pass
    candidats.sort(key=lambda c: c[0])
    onglets = []
    for left, r, e in candidats:
        if not onglets or left - onglets[-1][0] > 5:   # un seul élément par onglet
            onglets.append((left, r, e))
    log.info("Onglets détectés (gauche -> droite) : %s", [str(r) for _, r, _ in onglets])
    if len(onglets) < 2:
        raise RuntimeError(f"Onglet Commentaire 2 non détecté (onglets trouvés : {len(onglets)}, zone {zone})")
    onglets[1][2].click_input()   # 1er = Commentaire, 2e = Commentaire 2
    log.info("Onglet Commentaire 2 cliqué")
    time.sleep(0.5)

    try:
        return attendre(champ, timeout=10)
    except DelaiDepasse:
        # Diagnostic : champs et boutons de la fiche (identifiant et position), à m'envoyer
        n = 0
        for e in fiche.wrapper_object().descendants():
            try:
                info = e.element_info
                if info.control_type in ("Edit", "Document", "Tab", "TabItem", "Text", "Button"):
                    log.warning("Diagnostic fiche : %s | %r | auto_id=%r | %s",
                                info.control_type, info.name, info.automation_id, e.rectangle())
                    n += 1
                    if n >= 80:
                        break
            except COMError:
                pass
        raise RuntimeError(
            "Champ Commentaire 2 introuvable après Ctrl+Tab (voir Diagnostic fiche dans le journal)"
        )


def fermer_fiche_repere(fiche):
    # Ferme la fiche sans enregistrer : Annuler, Quitter, puis Non si Steel Projects demande d'enregistrer
    try:
        fiche.set_focus()
        annuler = fiche.child_window(title="Annuler", control_type="Button")
        if annuler.exists(timeout=0) and annuler.is_enabled():
            annuler.click_input()
        quitter = fiche.child_window(title="Quitter", control_type="Button")
        if quitter.exists(timeout=0):
            quitter.click_input()
        else:
            # Bouton Quitter non trouvé par son type : recherche par son texte, quel que soit le type
            for e in fiche.wrapper_object().descendants():
                if (e.window_text() or "").strip() == "Quitter":
                    e.click_input()
                    break
        non = fiche.child_window(title="Non", control_type="Button")
        if non.exists(timeout=2):
            non.click_input()
        fiche.wait_not("exists", timeout=30, retry_interval=0.2)
    except Exception:
        log.warning("Impossible de fermer la fiche repère proprement")


def remplir_commentaire_2(window, texte, nb_lignes):
    # Fiche des repères : 1 ligne = fiche individuelle ; 2 lignes ou plus = fiche multiple (onglet de l'arbre)
    fiche = trouver_fiche_repere(window)
    try:
        _remplir_fiche_repere(fiche, texte, nb_lignes)
    except Exception:
        fermer_fiche_repere(fiche)   # ne pas laisser la fiche ouverte après une erreur
        raise


def _remplir_fiche_repere(fiche, texte, nb_lignes):
    fiche.set_focus()
    attendre(fiche, "exists visible")

    if nb_lignes > 1:
        onglets = fiche.child_window(auto_id="tsGeneral", control_type="Pane")
        cliquer(onglets.child_window(control_type="TreeItem", found_index=3))
        champ = attendre(fiche.child_window(auto_id="tbCom2", control_type="Edit"))
    else:
        champ = champ_commentaire_2_fiche_seule(fiche)

    # Vidage sans clavier : l'Entrée qui ouvre la fiche peut laisser un retour à la ligne
    champ.set_edit_text("")
    champ.click_input()
    champ.type_keys(echapper_keys(texte), with_spaces=True)
    try:
        wait_until(5, 0.2, lambda: (champ.get_value() or "").strip() == texte)
    except DelaiDepasse:
        raise RuntimeError(f"Commentaire 2 incorrect : {champ.get_value()!r} au lieu de {texte!r}")

    cliquer(fiche.child_window(title="Valider", control_type="Button"))
    cliquer(fiche.child_window(title="Quitter", control_type="Button"))
    fiche.wait_not("exists", timeout=30, retry_interval=0.2)


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

def trouver_fenetre(window, titre_re, timeout=60):
    # Une boîte de dialogue peut être une fenêtre séparée ou un enfant de Steel Projects
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


def lignes_profil_strict(fenetre):
    # Une entrée par ligne : (« Ligne N », {colonne: valeur lue}, bouton Ajouter de la ligne)
    boutons = {b.window_text().strip(): b for b in fenetre.descendants(control_type="Button")
               if b.window_text().strip().startswith("Ligne ")}
    lignes = {}
    for e in fenetre.descendants(control_type="Edit"):
        m = re.match(r"^(Profil dans le fichier importé|Importer en tant que) (Ligne \d+)", e.window_text())
        if m:
            try:
                valeur = (e.get_value() or "").strip()
            except Exception as exc:
                valeur = f"<lecture impossible : {exc!r}>"
            lignes.setdefault(m.group(2), {})[m.group(1)] = valeur
    return [(ligne, colonnes, boutons.get(ligne)) for ligne, colonnes in lignes.items()]

def valider_profils_stricts(window, timeout=60):
    # Fenêtre « Profil Strict » : chaque jarret non encore ajouté reçoit un clic sur Ajouter
    # (bouton en bout de ligne) ; puis Ok. Les profils enregistrés sont journalisés après Ok.
    # Renvoie False si la fenêtre n'apparaît pas.
    try:
        dialogue = trouver_fenetre(window, r"Profil Strict", timeout=timeout)
    except DelaiDepasse:
        return False
    attendre(dialogue, "exists visible", timeout=30)
    fenetre = dialogue.wrapper_object()

    ajoutes = []
    for _ in range(50):  # garde-fou : une ligne qui ne se valide pas ne doit pas boucler indéfiniment
        a_ajouter = None
        for ligne, colonnes, bouton in lignes_profil_strict(fenetre):
            profil = colonnes.get("Profil dans le fichier importé", "")
            importer = colonnes.get("Importer en tant que", "")
            non_traite = importer in ("", "(null)")   # la grille affiche « (null) » pour une cellule vide
            if non_traite and bouton is not None:
                a_ajouter = (ligne, profil, bouton)
                break
        if a_ajouter is None:
            break
        ligne, profil, bouton = a_ajouter
        print(f"Profil strict : {ligne}, profil {profil}, ajout")
        bouton.click_input()
        ajoutes.append(profil)
        time.sleep(1)
    else:
        raise RuntimeError("Profil Strict : un profil reste non ajouté après 50 essais")

    cliquer(dialogue.child_window(title="Ok", control_type="Button"))
    dialogue.wait_not("exists visible", timeout=60, retry_interval=0.5)

    # Enregistrement validé par Ok : on journalise les profils ajoutés
    for profil in ajoutes:
        log.info("Profil enregistré : %s", profil)
    log.info("Profil Strict : %d profil(s) enregistré(s)", len(ajoutes))
    return True


def lister_fenetres_ouvertes():
    # Journalise le titre de chaque fenêtre ouverte (diagnostic en cas de blocage)
    for w in DESKTOP.windows(top_level_only=True):
        try:
            log.info("Fenêtre ouverte : %r", w.window_text())
        except COMError:
            pass


def attendre_une_des_fenetres(window, titres_re, timeout=600):
    # Attend qu'une des fenêtres (titres en expressions régulières) soit visible ; renvoie son motif
    def visible():
        for titre_re in titres_re:
            for f in (window.child_window(title_re=titre_re, control_type="Window"),
                      DESKTOP.window(title_re=titre_re, control_type="Window", top_level_only=True)):
                try:
                    if f.exists(timeout=0) and f.is_visible():
                        return titre_re
                except COMError:
                    pass
        return None

    try:
        return wait_until(timeout, 0.5, visible, None, operator.is_not)
    except DelaiDepasse:
        log.error("Aucune des fenêtres attendues n'est apparue : %s", titres_re)
        lister_fenetres_ouvertes()
        raise
def valider_comparaison_affaire(window, timeout=60):
    # Fenêtre « Comparaison [Affaire] » : Ajouter (barre du haut), puis Ok. Renvoie False si elle n'apparaît pas.
    try:
        comparaison = trouver_fenetre(window, r"Comparaison \[.*\]", timeout=timeout)
    except DelaiDepasse:
        log.info("Pas de fenêtre « Comparaison [Affaire] »")
        return False
    log.info("Fenêtre « Comparaison [Affaire] » ouverte")

    cliquer_sans_souris(comparaison.child_window(title="Ajouter", control_type="Button"))
    log.info("Ajouter cliqué dans « Comparaison [Affaire] »")
    cliquer_sans_souris(comparaison.child_window(title="Ok", control_type="Button"))
    log.info("Ok cliqué dans « Comparaison [Affaire] »")
    comparaison.wait_not("exists visible", timeout=60, retry_interval=0.5)
    log.info("Fenêtre « Comparaison [Affaire] » fermée")
    return True


def importer_tekla(window, dossier_xml):
    # Importe les fichiers XML Tekla du dossier donné ; journalise chaque étape
    chemin_xml = os.path.join(dossier_xml, "*.XML")
    log.info("IMPORT XML : début, dossier %s", chemin_xml)

    bouton_import = window.child_window(title="Import", control_type="Button")
    cliquer(bouton_import)
    log.info("Clic sur Import")
    cliquer_menu(bouton_import, "TEKLA_XML")
    log.info("Choix du menu TEKLA_XML")

    tekla = DESKTOP.window(title_re=".*Importation Tekla.*")
    attendre(tekla, "exists visible")
    log.info("Fenêtre « Importation Tekla » ouverte")

    # Le champ ne sélectionne les .XML que sur une vraie frappe clavier
    repertoire = tekla.child_window(title="Répertoire", auto_id="1001", control_type="Edit")
    saisir_texte(repertoire, chemin_xml)
    log.info("Chemin saisi dans Répertoire")

    cliquer(tekla.child_window(title="Ok", auto_id="1", control_type="Button"))
    log.info("Ok de « Importation Tekla » cliqué")

    # Fenêtre « Ventilation des plans » : Ok
    ok_validation = window.child_window(title="Ok", control_type="Button", best_match="Button3")
    cliquer_avec_comparaison(window, ok_validation, timeout=600)
    log.info("Ok de « Ventilation des plans » cliqué")

    # Ensuite : comparaison de profils, « Profil Strict » ou « Comparaison [Affaire] » (écran réel)
    suivante = attendre_une_des_fenetres(
        window, (r"Profil Strict", r"^Import$", r"Comparaison \[.*\]"), timeout=600
    )
    log.info("Fenêtre suivante détectée : %s", suivante)

    # Comparaison de profils : validée seulement si elle est réellement présente.
    # Elle peut ne pas s'ouvrir (la détection « Import » peut viser une autre fenêtre) : pas d'erreur.
    comparaison_profils = window.child_window(auto_id="FormProfileComparison", control_type="Window")
    if comparaison_profils.exists(timeout=5) and comparaison_profils.is_visible():
        cliquer_sans_souris(comparaison_profils.child_window(title="Ok", control_type="Button"))
        log.info("Ok de la comparaison de profils cliqué")
        comparaison_profils.wait_not("exists visible", timeout=60, retry_interval=0.5)
        log.info("Comparaison de profils fermée")
    else:
        log.info("Pas de comparaison de profils à valider")

    # « Profil Strict » : absente, la fonction renvoie False sans erreur
    if valider_profils_stricts(window, timeout=20):
        log.info("Profil Strict traité")

    # Fenêtre « Comparaison [Affaire] » : Ajouter, puis Ok
    valider_comparaison_affaire(window, timeout=60)

    log.info("Validation finale (FormConfigLog)")
    finir_import(window)
    log.info("IMPORT XML : terminé")


def finir_import(window, timeout=3600):
    # Attend la fin de l'import (la comparaison de profils est validée si elle apparaît),
    # puis clique sur Ok final
    dialog = window.child_window(auto_id="FormConfigLog", control_type="Window")
    barre_ok = dialog.child_window(auto_id="bar1", control_type="ToolBar")
    ok_final = barre_ok.child_window(title="Ok", control_type="Button")

    cliquer_avec_comparaison(window, ok_final, timeout=timeout)
    dialog.wait_not("exists", timeout=60, retry_interval=0.2)


def ouvrir_gestion_production(window):
    # Ouvre l'écran Gestion de production et attend qu'il soit réellement chargé
    window.set_focus()
    cliquer_sans_souris(window.child_window(title="Gestion de production", control_type="Button"))

    # 1) Le titre passe à « Steel Projects - Gestion de production » (l'écran est ouvert)
    try:
        wait_until(120, 0.5, lambda: "Gestion de production" in window.window_text())
    except DelaiDepasse:
        raise RuntimeError("Gestion de production ne s'est pas ouverte "
                           f"(fenêtre au premier plan : {titre_premier_plan()!r})")

    # 2) Attendre la fin du chargement (import de gros projets : plus long)
    attendre_appli(window, timeout=180)

    # 3) Barre d'outils de l'écran : délai allongé, 180 s au lieu de 60
    toolbar = window.child_window(auto_id="toolBar", control_type="ToolBar", found_index=0)
    try:
        attendre(toolbar, "exists visible", timeout=180)
    except DelaiDepasse:
        raise RuntimeError("Gestion de production ouverte mais barre d'outils introuvable "
                           f"(fenêtre au premier plan : {titre_premier_plan()!r})")
    log.info("Gestion de production ouverte")


def quitter_gestion_production(window, timeout=60):
    # Ferme l'écran Gestion de production (Ctrl+Q) et vérifie qu'il est bien fermé
    attendre_appli(window)
    window.set_focus()
    send_keys("^q")

    def fermee():
        # Fenêtre disparue (fermée d'elle-même) : c'est bien fermé, pas une erreur
        try:
            return "Gestion de production" not in window.window_text()
        except COMError:
            return True

    try:
        wait_until(timeout, 0.5, fermee)
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
                    # Visible ne suffit pas : après le retour de la comparaison, le champ peut encore être grisé
                    if edits and edits[0].is_visible() and edits[0].is_enabled():
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
    nb_lignes = sum(1 for l in grille.children(control_type="Custom") if l.window_text() != "Ligne du haut")
    send_keys("^a{ENTER}")
    remplir_commentaire_2(window, COMMENTAIRE_2, nb_lignes)


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

    send_keys("{ENTER}")  # ouvre la fiche pour les lignes sélectionnées
    remplir_commentaire_2(window, COMMENTAIRE_GR, n)


def trouver_boutons_fiche_action(window):
    # Gestion de production : boutons Fiche de débit et Action sans nom, dans la colonne d'icônes
    # à droite de la liste Sélection. Fiche de débit = le plus haut de la colonne, Action = le plus bas.
    largeur = window.wrapper_object().rectangle().width()
    groupes = []   # [centre x moyen, [(haut, bouton), ...]]
    for e in window.wrapper_object().descendants(control_type="Button"):
        try:
            if (e.window_text() or "").strip():
                continue
            r = e.rectangle()
            if not (40 <= r.width() <= 90 and 40 <= r.height() <= 60):
                continue
            centre = (r.left + r.right) // 2
            if centre < 0.15 * largeur:   # boutons de gauche (outils de la liste) : exclus
                continue
            for g in groupes:
                if abs(g[0] - centre) <= 20:
                    g[1].append((r.top, e))
                    break
            else:
                groupes.append([centre, [(r.top, e)]])
        except COMError:
            pass

    if not groupes:
        raise RuntimeError("Boutons Fiche de débit / Action introuvables dans Gestion de production")
    colonne = max(groupes, key=lambda g: len(g[1]))[1]
    if len(colonne) < 2:
        raise RuntimeError("Boutons Fiche de débit / Action introuvables dans Gestion de production")
    colonne.sort(key=lambda x: x[0])
    log.info("Fiche de débit = icône du haut, Action = icône du bas (%d icônes dans la colonne)", len(colonne))
    return colonne[0][1], colonne[-1][1]


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
    action_barre = barre_droite.child_window(control_type="Button", found_index=5)
    # Barre droite utilisée seulement si son bouton Action est réellement visible
    # (la barre peut exister dans Gestion de production sans être affichée)
    if barre_droite.exists(timeout=5) and action_barre.exists(timeout=2) and action_barre.is_visible():
        fiche_debit = barre_droite.child_window(control_type="Button", found_index=0)
        action = action_barre
    else:
        # Gestion de production : icônes sans nom de la colonne Sélection
        fiche_debit, action = trouver_boutons_fiche_action(window)
    attendre(action, "exists visible")

    # Action grisée = Fiche de débit non sélectionnée : on la sélectionne d'abord
    if not action.is_enabled():
        cliquer(fiche_debit)
        wait_until(30, 0.2, action.is_enabled)

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


def impression_gestion_production(window):
    # Même méthode que Gestion d'Affaires (Fiche de débit + Action, puis PDF),
    # mais dans l'écran Gestion de production déjà ouvert : pas d'ouverture ni de fermeture de Gestion d'Affaires
    # Filtre sur l'affaire, puis vue Repère secondaire directement (pas de filtre par phase)
    window.set_focus()
    filtrer_par_affaire(window)                    # l'affaire en cours (Ctrl+F3)
    filtrer_parrepere_secondaire(window)           # vue Repère secondaire (Ctrl+F6)
    attendre_appli(window)
    grille_reperes = trouver_grille(window, "Profil")
    nb_reperes = sum(1 for l in grille_reperes.children(control_type="Custom")
                     if l.window_text() != "Ligne du haut")
    log.info("Repères affichés pour l'impression : %d", nb_reperes)

    # Focus dans la grille des repères secondaires, puis sélection de toutes les lignes
    focus_grille_haut(window)
    send_keys("^a")
    attendre_appli(window)

    # Mettre en sélection : raccourci Maj+Inser
    window.set_focus()
    send_keys("+{INSERT}")
    attendre_appli(window)

    barre_droite = window.child_window(auto_id="barDroite", control_type="Pane")
    action_barre = barre_droite.child_window(control_type="Button", found_index=5)
    # Barre droite utilisée seulement si son bouton Action est réellement visible
    # (la barre peut exister dans Gestion de production sans être affichée)
    if barre_droite.exists(timeout=5) and action_barre.exists(timeout=2) and action_barre.is_visible():
        fiche_debit = barre_droite.child_window(control_type="Button", found_index=0)
        action = action_barre
    else:
        # Gestion de production : icônes sans nom de la colonne Sélection
        fiche_debit, action = trouver_boutons_fiche_action(window)
    attendre(action, "exists visible")

    # Action grisée = Fiche de débit non sélectionnée : on la sélectionne d'abord
    if not action.is_enabled():
        cliquer(fiche_debit)
        wait_until(30, 0.2, action.is_enabled)

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

    def fermee():
        # Fenêtre disparue (fermée d'elle-même) : c'est bien fermé, pas une erreur
        try:
            return TITRE_GESTION_AFFAIRES not in window.window_text()
        except COMError:
            return True

    try:
        wait_until(timeout, 0.5, fermee)
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

    # Impression dans la Gestion de production (sans la quitter)
    chemin_pdf = impression_gestion_production(window)
    fermer_pdf_ouverts(chemin_pdf)
    fermer_apercu()
    revenir_steel_projects(window)

    # Comparaison avec Claude, une fois l'impression terminée
    print("=== Comparaison avec Claude ===")
    fichiers = claude.comparer_avec_claude(
        claude.fichiers_affaire(AFFAIRE, chemin_pdf),
        claude.dossier_sortie_affaire(AFFAIRE),
    )
    # Visionneuses (Acrobat, Excel) ouvertes par les téléchargements : elles cachaient Steel Projects
    fermer_visionneuses(fichiers)
    revenir_steel_projects(window)

    # Étapes suivies dans la même Gestion de production
    # print("=== Correction scribing jarret ===")
    # corection_scribing.corriger_scribing_jarret(window, AFFAIRE)

    # Affectation machine (classeur de Claude) dans CMNTR1, même écran Gestion de production
    print("=== Affectation machine ===")
    affectation_machine.affectation_machine(window, AFFAIRE)
    convertir_fers_plats(window, AFFAIRE)
    quitter_gestion_production(window)
    print("projet réussi")


if __name__ == "__main__":
    main_complet()