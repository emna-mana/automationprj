import ctypes

from pywinauto import Desktop
from pywinauto.keyboard import send_keys
from pywinauto.uia_defines import get_elem_interface

import affectation_machine as am
import claude
import pp
import re
import unicodedata

ENTETE_ORIGINE = "Profil d'origine"
ENTETE_RETENU = "Profil retenu"
COLONNE_PROFIL = "Profil"                 # grille des repères secondaires
COLONNE_LONGUEUR = "Longueur"
CHECKBOX_CONTOUR_RECTANGULAIRE = "Contour rectangulaire"
AUTO_ID_CONTOUR = "chbRectangularOutline" # case « Contour rectangulaire » (Pane sans état lisible)
SEUIL_PIXELS_COCHE = 5                    # pixels foncés dans la case au-delà desquels elle est cochée
DESCENTES_OUTILS = 10                     # menu clic droit : position de « Outils »
DESCENTES_CONVERSION = 1                  # sous-menu ouvert par Entrée, un seul repère sélectionné
AUTO_ID_BOITE = "FormConvertToFlatStd"    # boîte « Convertir en larges plats »

DESKTOP = Desktop(backend="uia")


def est_tole(profil):
    texte = claude.normaliser(profil).strip()

    return (
        texte.startswith("tole")
        or bool(re.match(r"^pl\s*\d", texte))
    )

def est_fer_plat(profil):
    return claude.normaliser(profil).strip().startswith(
        ("fp", "fer plat")
    )

def est_entete_profil_origine(texte):
    nom = am.cle_entete(texte)

    variantes = (
        "profilorigine",
        "profildorigine",
        "profilorigin",
    )

    return any(
        nom.startswith(am.cle_entete(v))
        for v in variantes
    )
def lire_conversions(chemin):

    def normaliser_entete(texte):
        texte = unicodedata.normalize("NFKD", str(texte))
        texte = "".join(
            c for c in texte
            if not unicodedata.combining(c)
        )
        return re.sub(r"[^a-z0-9]", "", texte.lower())

    lignes = am.lire_onglet(chemin)

    entete = None
    indices = None

    for i, ligne in enumerate(lignes):

        colonnes = [
            normaliser_entete(v)
            for v in ligne
        ]

        def trouver(noms):
            for j, nom in enumerate(colonnes):
                if any(nom == n or nom.startswith(n)
                       for n in noms):
                    return j
            return None

        i_rep = trouver(("rep", "repere"))
        i_orig = trouver((
            "profildorigine",
            "profilorigine",
            "profilorigin",
        ))
        i_ret = trouver((
            "profilretenu",
        ))

        if all(x is not None for x in (i_rep, i_orig, i_ret)):
            entete = i
            indices = (i_rep, i_orig, i_ret)
            break

    if entete is None:
        print("En-têtes disponibles :")
        for ligne in lignes[:10]:
            print(ligne)

        raise ValueError(
            "Colonnes Rep / Profil origine / "
            "Profil retenu introuvables"
        )

    i_rep, i_orig, i_ret = indices

    print(
        f"Colonnes détectées : "
        f"Rep={i_rep + 1}, "
        f"Origine={i_orig + 1}, "
        f"Retenu={i_ret + 1}"
    )

    conversions = {}

    for ligne in lignes[entete + 1:]:

        if len(ligne) <= max(indices):
            continue

        rep = ligne[i_rep].strip()
        origine = ligne[i_orig].strip()
        retenu = ligne[i_ret].strip()

        if not rep:
            continue

        if est_tole(origine) and est_fer_plat(retenu):

            if rep in conversions and conversions[rep] != retenu:
                raise ValueError(
                    f"{rep} : profils retenus contradictoires"
                )

            conversions[rep] = retenu

    print(
        f"Conversion fers plats : "
        f"{len(conversions)} repère(s) détecté(s)"
    )

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


def trouver_contour_rectangulaire(boite, repere):
    # Case dessinée par Steel Projects : une Pane sans nom (le texte est une autre Pane à côté)
    case = boite.child_window(auto_id=AUTO_ID_CONTOUR, control_type="Pane")
    if not case.exists(timeout=5):
        raise RuntimeError(
            f"{repere} : option « {CHECKBOX_CONTOUR_RECTANGULAIRE} » ({AUTO_ID_CONTOUR}) "
            f"introuvable dans la boîte de conversion"
        )
    return case.wrapper_object()


def case_cochee(case):
    r = case.rectangle()
    cy = (r.top + r.bottom) // 2
    dc = ctypes.windll.user32.GetDC(0)
    try:
        fonces = 0
        for y in range(cy - 5, cy + 6):
            for x in range(r.left + 2, r.right - 2):
                p = ctypes.windll.gdi32.GetPixel(dc, x, y)
                if ((p & 255) + ((p >> 8) & 255) + ((p >> 16) & 255)) // 3 < 200:
                    fonces += 1
    finally:
        ctypes.windll.user32.ReleaseDC(0, dc)
    return fonces > SEUIL_PIXELS_COCHE


def lignes_en_tole(window, repere):
    # Lignes de la grille de ce repère encore en tôle (un repère peut occuper plusieurs lignes)
    return [l for l in am.lignes_donnees(am.grille_reperes(window))
            if pp.valeur_cellule(l, am.COLONNE_REPERE) == repere
            and est_tole(pp.valeur_cellule(l, COLONNE_PROFIL))]


def convertir_repere(window, repere):
    # Sélectionne seule la 1re ligne du repère encore en tôle,
    # puis clic droit > Outils > Convertir en larges plats > Ok
    window.set_focus()
    lignes = lignes_en_tole(window, repere)
    if not lignes:
        raise RuntimeError(f"{repere} : aucune ligne en tôle à convertir")
    ligne = lignes[0]
    # Sélection d'accessibilité : remplace la sélection et donne le focus à la grille (0x2 + 0x1)
    get_elem_interface(ligne.element_info.element, "LegacyIAccessible").Select(0x3)
    pp.attendre_appli(window)

    # Clic droit sur la ligne sélectionnée (elle doit être visible à l'écran)
    if not ligne.is_visible():
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
    if longueur > 800:
        contour = trouver_contour_rectangulaire(boite, repere)
        if case_cochee(contour):
            contour.click_input()
            # La relecture des pixels après le redessin peut encore détecter l'ancienne coche.
    pp.cliquer(boite.child_window(auto_id="stateBar", control_type="Pane")
                    .child_window(title="Ok", control_type="Button"))
    boite.wait_not("exists", timeout=120, retry_interval=0.5)
    pp.attendre_appli(window)

    # Enregistre la conversion (Ctrl+S) avant de passer à la suite
    window.set_focus()
    envoyer(window, "^s")
    pp.attendre_appli(window)

def convertir_fers_plats(window, affaire):
    # Convertit en fers plats les repères TOLE -> FP du classeur.
    # Un repère qui échoue est signalé par une ligne dans la console, puis le traitement continue.
    conversions = lire_conversions(am.trouver_classeur(affaire))
    window.set_focus()
    send_keys("^{F6}")  # vue Repère secondaire
    pp.attendre_appli(window)

    a_convertir = set()
    for rep, fp in conversions.items():
        try:
            n = len(lignes_en_tole(window, rep))
        except Exception as exc:
            print(f"ATTENTION {rep} : lecture de la grille impossible ({exc}), repère ignoré")
            continue
        if n == 0:
            continue

        print(f"Conversion {rep} -> {fp}" + (f" ({n} lignes)" if n > 1 else ""))
        a_convertir.add(rep)
        for _ in range(n):
            try:
                convertir_repere(window, rep)
            except Exception as exc:
                print(f"ATTENTION {rep} : non converti ({exc}), on continue")
                break

    restes = sorted(r for r in a_convertir if lignes_en_tole(window, r))
    if restes:
        print(f"ATTENTION repères toujours en tôle (non convertis) : {', '.join(restes)}")
    print(f"Conversion fers plats : {len(a_convertir) - len(restes)} repère(s) converti(s) sur {len(a_convertir)}")


if __name__ == "__main__":
    # Lancement seul : Steel Projects déjà connecté, affaire de pp.py
    window = DESKTOP.window(title_re=".*Steel Projects.*", found_index=0)
    window.set_focus()
    if "Gestion de production" not in window.window_text():
        pp.ouvrir_gestion_production(window)
    pp.filtrer_par_affaire(window)
    convertir_fers_plats(window, pp.AFFAIRE)
