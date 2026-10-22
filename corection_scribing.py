import ctypes
import operator
import time

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

def ecrire_valeur(fenetre_dessin, ligne, valeur):
    # Écrit une valeur dans la colonne Valeur. ligne = index dans la grille (0 = X, 1 = Y, ...)
    grille = grille_parametres(fenetre_dessin)
    r = grille.rectangle()
    x_rel = int(r.width() * 0.7)   # colonne Valeur
    y_rel = 35 + ligne * 22        # en-tête d'environ 35 px, lignes de 22 px
    grille.double_click_input(coords=(x_rel, y_rel))
    time.sleep(0.3)
    # Fin de la valeur, efface la valeur par défaut (ex. « 0.00 ») puis tape la nouvelle.
    # Ctrl+A ne sélectionne pas le texte dans cette cellule : on efface avec Retour arrière.
    # Valide avec Tab (pas Entrée : Entrée déclenche le bouton par défaut « Appliquer »)
    send_keys("{END}{BACKSPACE 15}" + pp.echapper_keys(str(valeur)) + "{TAB}")
    time.sleep(0.3)

def choisir_type_scribing(fenetre_dessin):
    # Liste déroulante « Type » : index 6 (7e ligne, en comptant à partir de 0)
    # Clic sur la cellule, F4 ouvre la liste, 2 flèches bas (Normal -> Disque -> Scribing),
    # puis Tab valide. Pas d'Entrée : elle déclenche le bouton Appliquer.
    grille = grille_parametres(fenetre_dessin)
    r = grille.rectangle()
    x_rel = int(r.width() * 0.7)   # colonne Valeur
    y_rel = 35 + 6 * 22            # ligne Type
    grille.double_click_input(coords=(x_rel, y_rel))
    time.sleep(5)
    send_keys("{DOWN 2}{TAB}")
    time.sleep(3)

def ecrire_texte_affaire(fenetre_dessin, affaire, ligne=2):
    # Ligne « Texte » (index 2) : Texte = texte existant + X + affaire + X + texte existant
    grille = grille_parametres(fenetre_dessin)
    r = grille.rectangle()
    x_rel = int(r.width() * 0.7)   # colonne Valeur
    y_rel = 35 + ligne * 22        # ligne Texte
    grille.double_click_input(coords=(x_rel, y_rel))
    time.sleep(0.3)
    # Presse-papiers vidé avant la copie : un champ vide ne doit pas recoller l'ancien contenu
    vider_presse_papiers()
    send_keys("^a^c")              # copie le texte existant
    time.sleep(0.3)
    texte = lire_presse_papiers().strip()
    marque = "X" + affaire + "X"
    if not texte:
        send_keys("{TAB}")
        raise RuntimeError("Texte du marquage vide : rien à recopier autour de l'affaire")
    if marque in texte:
        send_keys("{TAB}")         # déjà corrigé (script relancé) : texte laissé tel quel
        print(f"  Texte déjà corrigé : {texte!r}")
        return
    # Fin du texte (texte existant conservé), puis X + affaire + X, puis le texte copié (Ctrl+V), Tab valide
    send_keys("{END}" + pp.echapper_keys(marque) + "^v{TAB}")
    time.sleep(0.3)

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


def corriger_scribing_jarret(window, affaire):
    # Repères secondaires dont le profil contient « _ » : pour chacun, sélection de la ligne,
    # puis Ctrl+D, clic sur le plan, actions dans la fenêtre ouverte, qu'on ferme avant le suivant.
    # Suppose que Gestion de production est ouverte et l'affaire filtrée (fait dans main_complet).
    window.set_focus()
    send_keys("^{F6}")  # vue Repère secondaire
    pp.attendre_appli(window)

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
        pp.attendre_appli(window)

        avant = {w.handle for w in DESKTOP.windows()}
        send_keys("^d")
        nouvelle = attendre_nouvelle_fenetre(avant, affaire)
        if nouvelle is None:
            raise RuntimeError(f"Ctrl+D n'a ouvert aucune nouvelle fenêtre pour le profil {profil}")

        cliquer_plan(nouvelle)
        cliquer_marquage(nouvelle)
        traiter_fenetre_ctrl_d(nouvelle, profil)
        time.sleep(1)
        ecrire_valeur(nouvelle, 0, 100)    # X = 100
        ecrire_valeur(nouvelle, 1, -100)   # Y = -100
        ecrire_texte_affaire(nouvelle, affaire)  # Texte = texte existant + X + affaire + X + texte existant
        choisir_type_scribing(nouvelle)
        cliquer_appliquer_parametres(nouvelle)  # valide les paramètres dans le dessin
        time.sleep(1)
        enregistrer_dessin(nouvelle)            # Ctrl+S : enregistre le dessin
        fermer_fenetre(nouvelle)
        pp.attendre_appli(window)
        window.set_focus()


def main_complet():
    # Lancement seul : Steel Projects déjà connecté, affaire de pp.py
    window = DESKTOP.window(title_re=".*Steel Projects.*", found_index=0)
    window.set_focus()
    if "Gestion de production" not in window.window_text():
        pp.ouvrir_gestion_production(window)
    pp.filtrer_par_affaire(window)
    corriger_scribing_jarret(window, pp.AFFAIRE)


if __name__ == "__main__":
    main_complet()