import ctypes
import operator
import sys
import time

from _ctypes import COMError
import win32clipboard
from pywinauto import Desktop
from pywinauto.keyboard import send_keys
from pywinauto.timings import TimeoutError as DelaiDepasse
from pywinauto.timings import wait_until
from pywinauto.uia_defines import get_elem_interface

import pp   # utilisé seulement dans les fonctions : pp importe aussi ce module

DESKTOP = Desktop(backend="uia")

# ===== corection scribing =====
def selectionner_une_ligne(ligne):
    # Sélectionne uniquement cette ligne (sans souris) et donne le focus à la grille
    legacy = get_elem_interface(ligne.element_info.element, "LegacyIAccessible")
    legacy.Select(0x3)


def lignes_donnees(grille):
    # Lignes de données de la grille (sans l'en-tête « Ligne du haut »)
    return [l for l in grille.children(control_type="Custom") if l.window_text() != "Ligne du haut"]

def ligne_de_profil(window, index):
    # Relit la grille (elle peut changer après une fenêtre) et renvoie la ligne n° index
    return lignes_donnees(pp.trouver_grille(window, "Profil"))[index]

def index_profils_underscore(window):
    # Positions des lignes dont le profil contient « _ », relues dans la grille actuelle
    grille = pp.trouver_grille(window, "Profil")
    return [i for i, l in enumerate(lignes_donnees(grille)) if "_" in pp.valeur_cellule(l, "Profil")]


def attendre_nouvelle_fenetre(avant, affaire, timeout=20):
    # Renvoie la fenêtre de dessin « <affaire> \ <repère> » apparue après Ctrl+D, ou None
    # (une autre fenêtre qui s'ouvre au même moment, notification ou autre appli, est ignorée)
    def nouvelle():
        for w in DESKTOP.windows():
            titre = w.window_text()
            if w.handle not in avant and affaire in titre and "\\" in titre:
                return DESKTOP.window(handle=w.handle)
        return None
    try:
        return wait_until(timeout, 0.5, nouvelle, None, operator.is_not)
    except DelaiDepasse:
        return None


def fermer_fenetre(w, timeout=30):
    # Demande la fermeture de la fenêtre et attend qu'elle ait disparu
    handle = w.handle
    w.close()
    wait_until(timeout, 0.5, lambda: not ctypes.windll.user32.IsWindow(handle))


def traiter_fenetre_ctrl_d(nouvelle, profil):
    # À COMPLÉTER : actions à faire dans la fenêtre ouverte par Ctrl+D, pour ce profil.
    # Pour l'instant : affiche le titre et les boutons de la fenêtre, pour savoir quoi faire ensuite.
    print(f"  Fenêtre Ctrl+D pour {profil} : {nouvelle.window_text()!r}")
    for c in nouvelle.descendants(control_type="Button"):
        if c.window_text().strip():
            print("    bouton :", repr(c.window_text()))

def cliquer_plan(fenetre_dessin):
    # Clique au centre de la zone du plan (fenêtre de dessin ouverte par Ctrl+D)
    fenetre_dessin.set_focus()
    plan = fenetre_dessin.child_window(auto_id="59648", control_type="Pane")
    plan.wait("exists visible", timeout=10)
    plan.click_input()

def cliquer_marquage(fenetre_dessin):
    # Bouton « Marquage » (A) : barre Usinage (59400), contrôle « CheckBox3 » (L153, T95)
    barre = fenetre_dessin.child_window(auto_id="59400", control_type="ToolBar")
    barre.child_window(best_match="CheckBox3").click_input()

def grille_parametres(fenetre_dessin):
    # Grille « Paramètres / Valeur » : contrôle 9062 situé en haut à droite (top < 400)
    for g in fenetre_dessin.descendants(control_type="Pane"):
        if g.automation_id() == "9062" and g.rectangle().top < 400:
            return g
    raise RuntimeError("Grille Paramètres / Valeur introuvable")

# Grille Paramètres : UI Automation ne donne que les barres de défilement, pas les lignes.
# Positions mesurées sur les captures (coordonnées relatives au haut de la grille) :
# en-tête d'environ 32 px, puis une ligne tous les 27,5 px. Ordre des lignes : X, Y, Texte, Angle,
# Hauteur, Face, Type…
LIGNES = {"X": 0, "Y": 1, "Texte": 2, "Angle": 3, "Hauteur": 4, "Face": 5, "Type": 6}
PREMIERE_LIGNE_Y = 43
HAUTEUR_LIGNE = 27.5


def point_cellule(grille, libelle):
    # Point à cliquer dans la colonne Valeur, sur la ligne « libelle » (relatif à la grille)
    ligne = LIGNES[libelle]
    gr = grille.rectangle()
    return int(gr.width() * 0.7), int(PREMIERE_LIGNE_Y + HAUTEUR_LIGNE * ligne)


def ecrire_valeur(fenetre_dessin, libelle, valeur):
    # Écrit une valeur dans la colonne Valeur de la ligne « libelle » (ex. « X », « Y »)
    grille = grille_parametres(fenetre_dessin)
    x, y = point_cellule(grille, libelle)
    grille.double_click_input(coords=(x, y))
    time.sleep(0.3)
    # Fin de la valeur, efface la valeur par défaut puis tape la nouvelle.
    # Valide avec Tab (pas Entrée : Entrée déclenche le bouton par défaut « Appliquer »)
    send_keys("{END}{BACKSPACE 15}" + pp.echapper_keys(str(valeur)) + "{TAB}")
    time.sleep(0.3)


def choisir_type_scribing(fenetre_dessin):
    # Liste déroulante « Type » : clic sur la cellule, F4 ouvre la liste, 2 flèches bas
    # (Normal -> Disque -> Scribing), puis Tab valide. Pas d'Entrée : elle déclenche Appliquer.
    grille = grille_parametres(fenetre_dessin)
    x, y = point_cellule(grille, "Type")
    grille.double_click_input(coords=(x, y))
    time.sleep(5)
    send_keys("{DOWN 2}{TAB}")
    time.sleep(3)


def lire_texte_cellule(grille):
    # Copie le texte de la cellule « Texte » en édition (Ctrl+A, Ctrl+C) et le lit dans le presse-papiers
    x, y = point_cellule(grille, "Texte")
    for essai in range(2):
        if essai == 0:
            grille.double_click_input(coords=(x, y))
        else:
            grille.click_input(coords=(x, y))
            time.sleep(0.3)
            send_keys("{F2}")
        time.sleep(0.5)
        vider_presse_papiers()
        send_keys("^a^c")
        time.sleep(0.8)
        texte = lire_presse_papiers().strip()
        if texte:
            return texte
        send_keys("{ESC}")
        time.sleep(0.5)
    return ""


def ecrire_texte_affaire(fenetre_dessin, affaire):
    # Ligne « Texte » : Texte = texte existant + X + affaire + X + texte existant
    grille = grille_parametres(fenetre_dessin)
    texte = lire_texte_cellule(grille)
    print(f"  Texte du marquage lu : {texte!r}")
    if not texte:
        raise RuntimeError("Texte du marquage vide : la cellule Texte n'a pas été lue")
    marque = "X" + affaire + "X"
    if marque in texte:
        print(f"  Texte déjà corrigé : {texte!r}")
        return
    x, y = point_cellule(grille, "Texte")
    grille.double_click_input(coords=(x, y))
    time.sleep(0.3)
    # Curseur en fin de texte, puis X + affaire + X, puis le texte existant ; Tab valide
    send_keys("{END}" + pp.echapper_keys(marque + texte) + "{TAB}")
    time.sleep(0.5)


def enregistrer_dessin(fenetre_dessin):
    # Ctrl+S dans la fenêtre de dessin, puis attente de la fin de l'enregistrement avant de la fermer
    fenetre_dessin.set_focus()
    time.sleep(0.3)
    send_keys("^s")
    time.sleep(1)
    pp.attendre_appli(fenetre_dessin)

def cliquer_appliquer_parametres(fenetre_dessin):
    # Bouton « Appliquer » du panneau Paramètres (auto_id 9069, en haut à droite)
    appliquer = next((b for b in fenetre_dessin.descendants(control_type="Button")
                      if b.automation_id() == "9069" and b.rectangle().top < 500), None)
    if appliquer is None:
        raise RuntimeError("Bouton « Appliquer » des paramètres introuvable")
    appliquer.click_input()


def vider_presse_papiers():
    # win32clipboard plutôt que tkinter : le presse-papiers Tk plantait Python (violation d'accès)
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
    finally:
        win32clipboard.CloseClipboard()


def lire_presse_papiers():
    # Lit le texte copié (Ctrl+C) dans le presse-papiers Windows ; "" s'il est vide
    win32clipboard.OpenClipboard()
    try:
        if not win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
            return ""
        return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


def fenetres_de_dessin(affaire):
    # Fenêtres de dessin déjà ouvertes (titre du type « 02IV \\ J2 »)
    return [w for w in DESKTOP.windows() if affaire in w.window_text() and "\\" in w.window_text()]


def fenetre_principale():
    # Steel Projects peut être recréée (ex. après fermeture de « Gestion d'Affaires » pendant la
    # comparaison Claude) : on reprend toujours la fenêtre fraîche, pas un ancien objet
    return DESKTOP.window(title_re=".*Steel Projects.*", found_index=0)


def attendre_principale(window, essais=5):
    # Attend la fin de travail de la fenêtre principale. Si son handle a disparu (COMError),
    # on la reprend et on réessaie
    for essai in range(essais):
        try:
            window.set_focus()
            pp.attendre_appli(window)
            return window
        except COMError:
            print(f"  Fenêtre Steel Projects à reprendre (essai {essai + 1}/{essais})")
            time.sleep(2)
            window = fenetre_principale()
    raise RuntimeError("Fenêtre Steel Projects introuvable après plusieurs essais")


def corriger_scribing_jarret(window, affaire):
    # Repères secondaires dont le profil contient « _ » : pour chacun, sélection de la ligne,
    # puis Ctrl+D, clic sur le plan, actions dans la fenêtre ouverte, qu'on ferme avant le suivant.
    # Suppose que Gestion de production est ouverte et l'affaire filtrée (fait dans main_complet).
    # Une fenêtre de dessin restée ouverte (ex. d'un test) empêche de reconnaître celle du Ctrl+D
    ouvertes = fenetres_de_dessin(affaire)
    if ouvertes:
        raise RuntimeError("Ferme d'abord les fenêtres de dessin déjà ouvertes : "
                           + ", ".join(w.window_text() for w in ouvertes))
    # La fenêtre reçue peut être périmée (comparaison Claude entre-temps) : on la reprend
    window = attendre_principale(fenetre_principale())
    send_keys("^{F6}")  # vue Repère secondaire
    window = attendre_principale(window)

    nb = len(index_profils_underscore(window))
    print(f"{nb} repère(s) secondaire(s) avec « _ » dans le profil")

    for k in range(nb):
        positions = index_profils_underscore(window)
        if k >= len(positions):
            print("Liste des profils modifiée : arrêt de la boucle.")
            break
        index = positions[k]
        profil = pp.valeur_cellule(ligne_de_profil(window, index), "Profil")
        print(f"[{k + 1}/{nb}] Profil {profil}")

        selectionner_une_ligne(ligne_de_profil(window, index))
        window = attendre_principale(window)

        avant = {w.handle for w in DESKTOP.windows()}
        send_keys("^d")
        nouvelle = attendre_nouvelle_fenetre(avant, affaire)
        if nouvelle is None:
            titres = [w.window_text() for w in DESKTOP.windows() if "\\" in w.window_text()]
            raise RuntimeError(f"Ctrl+D n'a ouvert aucune nouvelle fenêtre pour le profil {profil} "
                               f"(affaire cherchée : {affaire!r} ; fenêtres avec « \\ » : {titres})")

        cliquer_plan(nouvelle)
        cliquer_marquage(nouvelle)
        time.sleep(2)   # la grille Paramètres passe en mode marquage
        traiter_fenetre_ctrl_d(nouvelle, profil)
        time.sleep(1)
        ecrire_valeur(nouvelle, "X", 100)    # X = 100
        ecrire_valeur(nouvelle, "Y", -100)   # Y = -100
        ecrire_texte_affaire(nouvelle, affaire)  # Texte = texte existant + X + affaire + X + texte existant
        choisir_type_scribing(nouvelle)
        cliquer_appliquer_parametres(nouvelle)  # valide les paramètres dans le dessin
        time.sleep(1)
        enregistrer_dessin(nouvelle)            # Ctrl+S : enregistre le dessin
        fermer_fenetre(nouvelle)
        time.sleep(2)
        # La fenêtre principale peut être recréée après la fermeture du dessin : on la reprend
        window = attendre_principale(fenetre_principale())


def main_complet():
    # Lancement seul : Steel Projects déjà connecté, affaire de pp.py
    window = DESKTOP.window(title_re=".*Steel Projects.*", found_index=0)
    window.set_focus()
    if "Gestion de production" not in window.window_text():
        pp.ouvrir_gestion_production(window)
    pp.filtrer_par_affaire(window)
    affaire = sys.argv[1] if len(sys.argv) > 1 else pp.AFFAIRE
    print(f"Affaire utilisée : {affaire}")
    corriger_scribing_jarret(window, affaire)


if __name__ == "__main__":
    main_complet()