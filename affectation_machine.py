"""Affectation machine : écrit dans CMNTR1 (colonne « Commentaire ») de chaque repère secondaire la machine
choisie par Claude (classeur « <affaire>_Preparation_Fabrication.xlsx », onglet T2, colonnes Rep / Machine).
Appelé dans le workflow, Gestion de production ouverte et filtrée sur l'affaire.
"""
import glob
import operator
import os
import re
import zipfile

import openpyxl
from _ctypes import COMError
from openpyxl.utils.exceptions import InvalidFileException
from pywinauto import Desktop
from pywinauto.keyboard import send_keys
from pywinauto.timings import TimeoutError as DelaiDepasse
from pywinauto.timings import wait_until

import pp
import claude

# ===== CONFIGURATION =====
MOTIF_CLASSEUR = "*.xlsx"           # cherché dans claude.dossier_sortie_affaire(affaire)
MOTS_ONGLET = ("affect", "verif")   # onglet « T2_Verif_Affectation »
ENTETE_REP = ("Rep", "Repère")
ENTETE_MACHINE = ("Machine / moyen", "Machine")

COLONNE_REPERE = "Secondaire"       # grille des repères secondaires (Ctrl+F6)
COLONNE_CMNTR1 = "Commentaire"
VIDE_GRILLE = "(null)"              # texte affiché par la grille pour une cellule vide

AUTO_ID_FICHE = "SpForm"
AUTO_ID_ONGLETS = "tsGeneral"
INDEX_ONGLET_CMNTR1 = 3
AUTO_ID_CMNTR1_MULTI = "tbCom1"     # fiche multiple (2 lignes ou plus), onglet INDEX_ONGLET_CMNTR1
AUTO_ID_CMNTR1_SEUL = "tbCmt1"      # fiche individuelle (1 ligne), visible dès l'ouverture

DESKTOP = Desktop(backend="uia")


# ===== LECTURE EXCEL =====
def lire_onglet(chemin, mots=MOTS_ONGLET):
    wb = openpyxl.load_workbook(
        chemin,
        read_only=True,
        data_only=True
    )

    try:
        # 1) Nom d'onglet contenant un des mots (« T2_Verif_Affectation », « T2 Vérification-affectation »...)
        noms_valides = [n for n in wb.sheetnames
                        if any(m in claude.comparable(n) for m in mots)]

        # 2) Repli : titre dans les 5 premières lignes contenant TOUS les mots
        #    (ex. « Tableau 2 – Vérification et affectation » en A1, onglet nommé « Tableau 2 »)
        if not noms_valides:
            for n in wb.sheetnames:
                titre = " ".join(
                    str(v)
                    for ligne in wb[n].iter_rows(max_row=5, values_only=True)
                    for v in ligne if v is not None
                )
                if all(m in claude.comparable(titre) for m in mots):
                    noms_valides.append(n)
                    break

        if not noms_valides:
            raise ValueError(
                f"Onglet d'affectation introuvable dans {chemin}. "
                f"Onglets disponibles : {wb.sheetnames}"
            )

        nom = noms_valides[0]

        print(f"Classeur : {os.path.basename(chemin)}")
        print(f"Onglet sélectionné : {nom}")

        return [
            [
                str(v).strip() if v is not None else ""
                for v in ligne
            ]
            for ligne in wb[nom].iter_rows(values_only=True)
        ]

    finally:
        wb.close()


def trouver_classeur(affaire):
    # Classeur le plus récent du dossier rapport qui contient l'onglet d'affectation
    dossier = claude.dossier_sortie_affaire(affaire)
    # « ~$... » = fichier de verrouillage d'Excel quand le classeur est ouvert
    fichiers = [f for f in glob.glob(os.path.join(dossier, MOTIF_CLASSEUR))
                if not os.path.basename(f).startswith("~$")]
    for f in sorted(fichiers, key=os.path.getmtime, reverse=True):
        try:
            lire_onglet(f)
            return f
        except (ValueError, zipfile.BadZipFile, InvalidFileException):
            continue   # pas d'onglet T2 ou fichier illisible : on essaie le suivant
    raise FileNotFoundError(f"Aucun classeur avec l'onglet {MOTS_ONGLET} dans {dossier}")


def cle_entete(texte):
    # En-tête comparable : accents, majuscules, apostrophe ’ et espaces ignorés
    # (« Profil d’origine » = « Profil d'origine », « Machine/moyen » = « Machine / moyen »)
    return re.sub(r"\s+", "", claude.comparable(texte))


def trouver_entetes(lignes, noms):
    # noms : chaque élément est un nom, ou un tuple de variants acceptées (ex. ("Rep", "Repère"))
    # (n° de la ligne d'en-tête, [index de colonne de chaque nom])
    groupes = [[cle_entete(v) for v in (n if isinstance(n, tuple) else (n,))] for n in noms]
    for i, l in enumerate(lignes):
        ligne = [cle_entete(v) for v in l]
        colonnes = []
        for variantes in groupes:
            trouve = next((ligne.index(c) for c in variantes if c in ligne), None)
            if trouve is None:
                break
            colonnes.append(trouve)
        else:
            return i, colonnes
    libelles = [" ou ".join(n) if isinstance(n, tuple) else n for n in noms]
    raise ValueError("En-têtes " + " / ".join(f"« {n} »" for n in libelles) + " introuvables")

def lire_affectations(chemin):
    # {repère: texte CMNTR1} ; texte = machine sans la partie entre parenthèses
    lignes = lire_onglet(chemin)
    entete, (i_rep, i_machine) = trouver_entetes(lignes, (ENTETE_REP, ENTETE_MACHINE))

    affectations = {}
    for l in lignes[entete + 1:]:
        rep = l[i_rep] if i_rep < len(l) else ""
        machine = l[i_machine] if i_machine < len(l) else ""
        if not rep or not machine:
            continue
        texte = re.sub(r"\s*\(.*?\)", "", machine).strip()
        if rep in affectations and affectations[rep] != texte:
            raise ValueError(f"Repère {rep} : deux machines différentes ({affectations[rep]!r} / {texte!r})")
        affectations[rep] = texte
    return affectations


# ===== STEEL PROJECTS =====
def grille_reperes(window):
    # Grille des repères secondaires (vue Ctrl+F6), relue à chaque appel
    return pp.trouver_grille(window, "Profil")


def lignes_donnees(grille):
    return [l for l in grille.children(control_type="Custom") if l.window_text() != "Ligne du haut"]


def valeurs_cmntr1(window):
    # {repère: [CMNTR1 de chaque ligne]} lu dans la grille (« (null) » -> "")
    resultat = {}
    for l in lignes_donnees(grille_reperes(window)):
        rep = pp.valeur_cellule(l, COLONNE_REPERE)
        if rep:
            v = pp.valeur_cellule(l, COLONNE_CMNTR1)
            resultat.setdefault(rep, []).append("" if v == VIDE_GRILLE else v)
    return resultat


def trouver_fiche(window, timeout=30):
    # La fiche s'ouvre soit dans la fenêtre principale, soit en fenêtre séparée
    dedans = window.child_window(auto_id=AUTO_ID_FICHE, control_type="Window")
    separee = DESKTOP.window(auto_id=AUTO_ID_FICHE, top_level_only=True)

    def visible():
        for f in (dedans, separee):
            try:
                if f.exists(timeout=0) and f.is_visible():
                    return f
            except COMError:
                pass
        return None

    return wait_until(timeout, 0.5, visible, None, operator.is_not)


def fermer_fiche(fiche, valider):
    # Clics « écran » : la fiche doit être au premier plan (sinon les clics tombent sur VS Code)
    fiche.set_focus()
    if valider:
        pp.cliquer(fiche.child_window(title="Valider", control_type="Button"))
    else:
        annuler = fiche.child_window(title="Annuler", control_type="Button")
        if annuler.exists(timeout=0) and annuler.is_enabled():
            pp.cliquer(annuler)
    pp.cliquer(fiche.child_window(title="Quitter", control_type="Button"))
    # Si Valider n'a pas encore pris effet, Quitter demande « Enregistrer les modifications » :
    # Oui pour enregistrer, Non pour abandonner
    reponse = fiche.child_window(title="Oui" if valider else "Non", control_type="Button")

    def fermee():
        try:
            if not fiche.exists(timeout=0):
                return True
            if reponse.exists(timeout=0):
                reponse.click_input()
        except COMError:
            pass   # fiche en cours de fermeture
        return False

    wait_until(30, 0.2, fermee)


def ecrire_groupe(window, reperes, texte, nb_lignes):
    # Écrit texte dans CMNTR1 de tous ces repères en une seule fiche
    window.set_focus()
    n = pp.selectionner_lignes(grille_reperes(window), COLONNE_REPERE, lambda v: v in reperes)
    if n != nb_lignes:
        raise RuntimeError(f"{n} ligne(s) sélectionnée(s) au lieu de {nb_lignes}")
    pp.attendre_appli(window)
    send_keys("{ENTER}")
    fiche = trouver_fiche(window)
    try:
        fiche.set_focus()
        if n > 1:
            onglets = fiche.child_window(auto_id=AUTO_ID_ONGLETS, control_type="Pane")
            pp.cliquer(onglets.child_window(control_type="TreeItem", found_index=INDEX_ONGLET_CMNTR1))
            champ = fiche.child_window(auto_id=AUTO_ID_CMNTR1_MULTI, control_type="Edit")
        else:
            champ = fiche.child_window(auto_id=AUTO_ID_CMNTR1_SEUL, control_type="Edit")
        # Vidage sans clavier : l'Entrée qui ouvre la fiche laisse un retour à la ligne dans tbCmt1
        pp.attendre(champ).set_edit_text("")
        champ.click_input()
        champ.type_keys(pp.echapper_keys(texte), with_spaces=True)
        try:
            wait_until(5, 0.2, lambda: (champ.get_value() or "").strip() == texte)
        except DelaiDepasse:
            raise RuntimeError(f"CMNTR1 incorrect : {champ.get_value()!r} au lieu de {texte!r}")
    except Exception:
        fermer_fiche(fiche, valider=False)   # Annuler + Quitter : rien n'est enregistré
        raise
    fermer_fiche(fiche, valider=True)
    pp.attendre_appli(window)


# ===== AFFECTATION =====
def affectation_machine(window, affaire):
    # Écrit la machine dans CMNTR1 des repères secondaires de l'affaire ; une valeur déjà remplie
    # et différente n'est jamais écrasée. Suppose Gestion de production ouverte et filtrée sur l'affaire.
    affectations = lire_affectations(trouver_classeur(affaire))
    window.set_focus()
    send_keys("^{F6}")  # vue Repère secondaire
    pp.attendre_appli(window)
    avant = valeurs_cmntr1(window)

    groupes = {}
    for rep, cible in sorted(affectations.items()):
        valeurs = avant.get(rep)
        if valeurs is None:
            print(f"{rep} : absent de Steel Projects")
        elif all(v.strip() == cible for v in valeurs):
            continue    # déjà fait
        elif any(v.strip() and v.strip() != cible for v in valeurs):
            autres = sorted({v.strip() for v in valeurs if v.strip() and v.strip() != cible})
            print(f"{rep} : CMNTR1 déjà rempli ({' / '.join(autres)}), non modifié")
        else:
            # Lignes vides (et éventuellement lignes déjà à la bonne valeur, réécrites à l'identique)
            groupes.setdefault(cible, []).append(rep)

    # Un groupe = une fiche : tous les repères qui reçoivent le même texte sont écrits ensemble
    for cible, reps in groupes.items():
        print(f"CMNTR1 « {cible} » sur {len(reps)} repère(s) : {', '.join(reps)}")
        ecrire_groupe(window, set(reps), cible, sum(len(avant[r]) for r in reps))

    apres = valeurs_cmntr1(window)
    erreurs = [r for cible, reps in groupes.items() for r in reps
               if any(v.strip() != cible for v in apres.get(r, []))]
    if erreurs:
        raise RuntimeError(f"CMNTR1 non vérifié pour : {', '.join(erreurs)}")
    print(f"Affectation machine : {sum(len(r) for r in groupes.values())} repère(s) écrit(s)")


if __name__ == "__main__":
    # Lancement seul : Steel Projects déjà connecté, affaire de pp.py
    window = DESKTOP.window(title_re=".*Steel Projects.*", found_index=0)
    window.set_focus()
    if "Gestion de production" not in window.window_text():
        pp.ouvrir_gestion_production(window)
    pp.filtrer_par_affaire(window)
    affectation_machine(window, pp.AFFAIRE)
