import ctypes

from pywinauto import Desktop
from pywinauto.keyboard import send_keys

import affectation_machine as am
import pp

ENTETE_ORIGINE = "Profil d'origine"
ENTETE_RETENU = "Profil retenu"
COLONNE_PROFIL = "Profil"                 # grille des repères secondaires
COLONNE_LONGUEUR = "Longueur"
AUTO_ID_CONTOUR_RECTANGULAIRE = "chbRectangularOutline"
DESCENTES_OUTILS = 10                     # menu clic droit : position de « Outils »
DESCENTES_CONVERSION = 1                  # sous-menu ouvert par Entrée, un seul repère sélectionné
AUTO_ID_BOITE = "FormConvertToFlatStd"    # boîte « Convertir en larges plats »

DESKTOP = Desktop(backend="uia")


def lire_conversions(chemin):
    # {repère: FP retenu} : Profil d'origine « TOLE… » et Profil retenu « FP … »
    lignes = am.lire_onglet(chemin)
    entete = next(i for i, l in enumerate(lignes) if am.ENTETE_REP in l and ENTETE_RETENU in l)
    i_rep, i_orig, i_ret = (lignes[entete].index(c) for c in (am.ENTETE_REP, ENTETE_ORIGINE, ENTETE_RETENU))
    conversions = {}
    for l in lignes[entete + 1:]:
        if l[i_rep] and l[i_orig].upper().startswith("TOLE") and l[i_ret].upper().startswith("FP"):
            conversions[l[i_rep]] = l[i_ret]
    return conversions


def envoyer(window, touches):
    # Les touches ne partent que si Steel Projects (ou son menu) est au premier plan
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(ctypes.windll.user32.GetForegroundWindow(), ctypes.byref(pid))
    if pid.value != window.wrapper_object().process_id():
        raise RuntimeError(f"Steel Projects n'est plus au premier plan : « {touches} » non envoyé")
    send_keys(touches)


def lire_longueur_repere(ligne, repere):
    valeur = pp.valeur_cellule(ligne, COLONNE_LONGUEUR)
    try:
        return float(valeur.replace("\u00a0", "").replace(" ", "").replace(",", "."))
    except ValueError as exc:
        raise RuntimeError(f"{repere} : longueur absente ou invalide ({valeur!r})") from exc


def trouver_contour_rectangulaire(boite):
    return pp.attendre(boite.child_window(
        auto_id=AUTO_ID_CONTOUR_RECTANGULAIRE, control_type="Pane"))


def convertir_repere(window, repere):
    # Sélectionne le repère seul, puis clic droit > Outils > Convertir en larges plats > Ok
    window.set_focus()
    grille = am.grille_reperes(window)
    n = pp.selectionner_lignes(grille, am.COLONNE_REPERE, lambda v: v == repere)
    if n != 1:
        raise RuntimeError(f"{repere} : {n} ligne(s) sélectionnée(s) au lieu de 1")
    pp.attendre_appli(window)

    # Clic droit sur la ligne sélectionnée (elle doit être visible à l'écran)
    ligne = next((l for l in am.lignes_donnees(grille)
                  if pp.valeur_cellule(l, am.COLONNE_REPERE) == repere and l.is_visible()), None)
    if ligne is None:
        raise RuntimeError(f"{repere} : ligne non visible pour le clic droit")
    longueur = lire_longueur_repere(ligne, repere)
    window.set_focus()
    ligne.children(control_type="Header")[0].right_click_input()
    pp.attendre_appli(window)
    envoyer(window, f"{{DOWN {DESCENTES_OUTILS}}}{{ENTER}}")
    pp.attendre_appli(window)
    envoyer(window, f"{{DOWN {DESCENTES_CONVERSION}}}{{ENTER}}")

    # Boîte « Convertir en larges plats » : paramètres par défaut, Ok dans la barre du bas
    boite = window.child_window(auto_id=AUTO_ID_BOITE, control_type="Window")   # dans la fenêtre principale
    pp.attendre(boite, "exists visible")
    boite.set_focus()
    if longueur > 8000:
        contour = trouver_contour_rectangulaire(boite)
        contour.set_focus()
        if not contour.has_keyboard_focus():
            raise RuntimeError(f"{repere} : focus impossible sur « Contour rectangulaire »")
        envoyer(window, "{SPACE}")
    pp.cliquer(boite.child_window(auto_id="stateBar", control_type="Pane")
                    .child_window(title="Ok", control_type="Button"))
    boite.wait_not("visible", timeout=120, retry_interval=0.5)
    pp.attendre_appli(window)

    # Enregistre la conversion (Ctrl+S) avant de passer à la suite
    window.set_focus()
    envoyer(window, "^s")
    pp.attendre_appli(window)


def profils_grille(window):
    # {repère: profil} lu dans la grille des repères secondaires
    return {pp.valeur_cellule(l, am.COLONNE_REPERE): pp.valeur_cellule(l, COLONNE_PROFIL)
            for l in am.lignes_donnees(am.grille_reperes(window))}


def convertir_fers_plats(window, affaire):
    # Convertit en fers plats les repères TOLE -> FP du classeur ; erreur si l'un reste en tôle
    conversions = lire_conversions(am.trouver_classeur(affaire))
    window.set_focus()
    send_keys("^{F6}")  # vue Repère secondaire
    pp.attendre_appli(window)

    # Un repère à la fois ; seuls ceux encore en tôle dans Steel Projects sont convertis
    profils = profils_grille(window)
    a_convertir = set()
    for rep, fp in conversions.items():
        if not profils.get(rep, "").upper().startswith("TOLE"):
            continue
        print(f"Conversion {rep} -> {fp}")
        convertir_repere(window, rep)
        a_convertir.add(rep)

    profils = profils_grille(window)
    restes = sorted(r for r in a_convertir if profils.get(r, "").upper().startswith("TOLE"))
    if restes:
        raise RuntimeError(f"Toujours en tôle après conversion : {', '.join(restes)}")
    print(f"Conversion fers plats : {len(a_convertir)} repère(s) converti(s)")


if __name__ == "__main__":
    # Lancement seul : Steel Projects déjà connecté, affaire de pp.py
    window = DESKTOP.window(title_re=".*Steel Projects.*", found_index=0)
    window.set_focus()
    if "Gestion de production" not in window.window_text():
        pp.ouvrir_gestion_production(window)
    pp.filtrer_par_affaire(window)
    convertir_fers_plats(window, pp.AFFAIRE)
