import hashlib
import os
import re
import shutil
import time
import unicodedata
import winreg
from datetime import datetime
from pathlib import Path

import win32clipboard
import win32gui
from pywinauto import Desktop
from pywinauto.keyboard import send_keys

# ===== CONFIGURATION (l'affaire n'est définie qu'ici) =====
DOSSIER_PROJETS = r"C:\Users\E.BENAMOR\Desktop\projetTravailler"
AFFAIRE = "02XY"


def fichiers_affaire(affaire, pdf_plm=None):
    """Fichiers envoyés à Claude pour une affaire : croquis, PDF PLM (Steel Projects), fers plats.

    pdf_plm : chemin exact du PDF produit par test_pp.py ; sinon « <affaire> PLM.pdf ».
    """
    dossier = os.path.join(DOSSIER_PROJETS, affaire)
    return [
        os.path.join(dossier, f"CROQUIS DEBITAGE {affaire}.pdf"),
        pdf_plm or os.path.join(dossier, f"{affaire} PLM.pdf"),
        os.path.join(DOSSIER_PROJETS, "FER PLAT.xlsx"),
    ]


def dossier_sortie_affaire(affaire):
    return os.path.join(DOSSIER_PROJETS, affaire, "rapport")


FICHIERS = fichiers_affaire(AFFAIRE)

PROMPT_LIGNES = [
    '# PROMPT – PRÉPARATION DE FABRICATION (GROUPE MATEM) – v3 ',
    '',
    '## 1. RÔLE',
    'Tu es préparateur de fabrication en construction métallique pour GROUPE MATEM. Tu es expert en charpente métallique, en programmation CNC FICEP et en optimisation matière (mise en barre et mise en tôle).',
    '',
    "## 2. FICHIERS D'ENTRÉE",
    '| Réf. | Fichier | Rôle |',
    '|---|---|---|',
    '| F1 | « fichier 1.pdf » | Croquis de débitage à répartir (document de travail, Tekla) |',
    '| F2 | « fichier 2.pdf » | Plans CN de référence (document qui fait foi, Steel Projects) |',
    '| F3 | « Tableau fers plats disponibles » | Fers plats en stock (largeur × épaisseur) |',
    "| F4 | « Règle de trusquinage A164 » | Pinces et entraxes mini de l'A164 |",
    '',
    '* F1 ou F2 absent ou illisible : arrête-toi et signale-le.',
    '* F3 absent : continue avec la gamme standard EN 10058 (largeurs 20 à 300, ép. 5 à 25), en signalant « DONNÉE MANQUANTE – F3 » dans chaque ligne concernée.',
    "* F4 absent : affecte quand même à l'A164, en écrivant « DONNÉE MANQUANTE – trusquinage A164 » pour chaque pièce percée.",
    '* F2 peut être un PDF image (texte non extractible) : lis les cartouches visuellement, pas par OCR seul.',
    '',
    '## 3. RÈGLES GÉNÉRALES (OBLIGATOIRES)',
    '',
    "* R1 : utilise UNIQUEMENT les caractéristiques de la section 4 et les données des fichiers. N'invente aucune valeur. Si une donnée manque, écris « DONNÉE MANQUANTE : … ».",
    '* R2 : traite TOUS les repères, un par un, sans oubli ni doublon. Chaque repère va à UNE SEULE machine (sans recoupement).',
    '* R3 : en cas de divergence entre F1 et F2, F2 fait foi. Signale la divergence, ne la corrige pas en silence.',
    "* R4 : nuance de tous les matériaux : S275JR, même si F1 ou F2 indique S235JR. Signale l'écart.",
    "* R5 : un repère qu'aucune machine ne peut réaliser est marqué « HORS CAPACITÉ », avec la caractéristique dépassée.",
    '* R6 : les règles atelier de la section 4.1 sont PRIORITAIRES sur les fiches techniques constructeur.',
    '',
    "## 4. MOYENS DE L'ATELIER",
    '',
    "### 4.1 RÈGLES ATELIER (chef d'atelier – prioritaires)",
    '',
    '**OPÉRATION MANUELLE**',
    '',
    '1. Cornières sans trous et de longueur ≤ 2050 mm.',
    "2. Tubes sans trous, coupes d'équerre (angle droit).",
    '3. Fers ronds.',
    '4. Tiges filetées.',
    '5. Grugeage des pièces uniques (profilés).',
    '',
    '**CISAILLE + POINÇONNEUSE FICEP P803**',
    '',
    '1. Trusquinage (distance axe du trou → bord) ≥ 25 mm.',
    '2. Poinçonnage / perçage : Ø maxi ≤ 32 mm.',
    '3. Longueur maxi de la pièce : 800 mm.',
    '4. Largeur maxi de la pièce : 500 mm.',
    '5. Trous oblongs : NON exécutables.',
    '6. Épaisseur de tôle maxi : 15 mm.',
    '7. Cisaille guillotine : épaisseur maxi 15 mm, longueur de coupe maxi 4000 mm, coupes droites uniquement.',
    '',
    '**FICEP A164**',
    '',
    "1. Ø mini poinçonnable selon l'épaisseur : Ø8 si ép. ≤ 6 mm ; Ø10 si ép. ≤ 8 mm ; Ø12 si ép. ≤ 10 mm.",
    '2. Fers plats : largeur 50 à 160 mm.',
    '3. Cornières : aile 30 à 160 mm.',
    '4. Longueur mini de la barre chargée : ≥ 2050 mm.',
    '5. Trusquinage : selon le document F4.',
    '6. Coupe droite uniquement : les chanfreins sont à reprendre en manuel.',
    '',
    '**FICEP GEMINI 254 PG**',
    '',
    '1. Toutes les pièces avec trous Ø ≥ 32 mm.',
    '2. Toutes les pièces avec trous oblongs.',
    '3. Découpe plasma : tôle ≤ 35 mm ; découpe oxycoupage : tôle ≤ 80 mm.',
    "4. Nombre d'outils (Ø de perçage différents) par nesting : ≤ 7.",
    '5. Pièce de sortie mini : 100 x 100 mm. Une pièce plus étroite est signalée « DÉPASSEMENT – sortie mini » (micro-attaches ou évacuation manuelle).',
    '6. Épaisseur mini : 5 mm.',
    '',
    '**FICEP 1003 DEB**',
    '',
    '1. Fers plats acceptés uniquement si largeur ≥ 200 mm ET épaisseur ≥ 15 mm. Un fer plat plus étroit ou plus mince ne passe pas sur la 1003 DEB.',
    '',
    '**TRONÇONNEUSE LINÉAIRE**',
    '',
    "* Sépare une ébauche de profilé en deux jarrets (coupe longitudinale de l'âme).",
    '',
    '### 4.2 FICHES TECHNIQUES CONSTRUCTEUR',
    '',
    "#### MACHINE 1 – FICEP A164 : ligne d'usinage de cornières et de fers plats",
    '',
    '* Cornières (acier 410 N/mm²) : mini 30x30x3 mm, maxi 160x160x19 mm.',
    '* Fers plats (outillage en option) : mini 50x5 mm, maxi 160x19 mm.',
    '* Poinçonnage : 720 kN ; 2 diamètres par aile ; Ø maxi 32 mm (outillage standard) ; Ø x ép. maxi 30x19 (410 N/mm²) et 25x19 (510 N/mm²).',
    '* Coupe : 2200 kN (cisaillage).',
    '* Translation barre : 40 m/min ; trusquin : 7 m/min ; 6 axes CNC.',
    '* Chute mini de fin de barre : 220 mm.',
    '* Tolérances : UNI 5783-73, UNI 5784-73.',
    '',
    '#### MACHINE 2 – FICEP GEMINI 254 PG : portique CNC de perçage, fraisage et coupe thermique de tôles',
    '',
    "* Tôle à l'entrée : longueur 1250 à 12100 mm ; largeur 800 à 2540 mm.",
    '* Pièce à la sortie : mini 100 x 100 mm.',
    '* Perçage : 1 tête verticale ; Ø maxi 32 mm ; épaisseur 5 à 80 mm ; poussée 3200 N ; broche 11 kW, 250 à 6000 tr/min.',
    '* Fraisage : Ø maxi 240 mm.',
    '* Plasma HPR260XD : 38 mm pleine tôle, 27 mm à 45°. Plasma HPR400XD : 50 mm pleine tôle, 35 mm à 45°.',
    '* Vitesses : X 32 m/min ; Y et U 42 m/min. Hauteur de travail : 650 mm.',
    '* Normes : UNI EN 10025, UNI EN 10029.',
    '',
    '#### MACHINE 3 – FICEP 1003 DEB : ligne de perçage et de sciage CNC pour profilés',
    '',
    '* Hauteur 80 à 1015 mm ; largeur 10 à 450 mm ; longueur mini transférable 2500 mm.',
    '* Poutrelles I/H : h 80 à 1015, ailes 42 à 450. Fers U : h 80 à 1015, ailes 45 à 300.',
    '* Cornières : 80x80x8 à 250x250x40. Plats : largeur 100 à 1000.',
    '* Tubes carrés : 80x80 à 450x450. Tubes rectangulaires : 80x40 à 1000x450.',
    '* Perçage : 3 têtes ; Ø maxi 40 mm ; épaisseur maxi 100 mm ; ISO 40 ; 27 kW.',
    '* Sciage : à 90° mini 80x10 et maxi 1015x450 ; à 45° maxi 620x450 ; à 60° maxi 350x350.',
    "  → Pour les fers plats, la règle atelier (largeur ≥ 200 et ép. ≥ 15) s'applique.",
    '* Poids maxi : 5400 kg ; 220 kg/m.',
    '* Chute mini de fin de barre : non fournie → « DONNÉE MANQUANTE ».',
    '',
    "## 5. RÈGLES D'AFFECTATION (appliquer dans cet ordre, la première qui convient l'emporte)",
    '',
    '1. Fer rond, tige filetée, grugeage de pièce unique → MANUEL.',
    "2. Tube sans trous et à coupes d'équerre → MANUEL.",
    '3. Cornière sans trous de longueur ≤ 2050 mm → MANUEL.',
    "4. Jarret → TRONÇONNEUSE LINÉAIRE. L'ébauche est débitée sur la 1003 DEB et comptée dans la mise en barre ; 1 ébauche = 2 jarrets.",
    '5. Poutrelles IPE/HEA/HEB, fers U, tubes percés ou à coupe biaise, cornières ≥ 80x80x8 percées → 1003 DEB. Une pièce < 2500 mm est débitée en fin de barre (à signaler).',
    "6. Cornière percée de 30 à 160 mm (hors règle 5) → A164 (vérifier le Ø mini selon l'épaisseur).",
    '7. Tôle ou plat avec un trou Ø ≥ 32 mm ou un trou oblong → GEMINI (épaisseur concernée).',
    '8. Pièce de moins de 100 x 100 mm → CHUTES. Si percée : P803 si trusquinage ≥ 25 mm, sinon perçage MANUEL.',
    '9. Fer plat retenu (section 6) de largeur ≥ 200 mm et ép. ≥ 15 mm → 1003 DEB.',
    '10. Fer plat retenu de largeur 50 à 160, avec un Ø ≥ Ø mini A164 → A164.',
    "11. Pièce rectangulaire (chanfreins tolérés) d'ép. ≤ 15 mm :",
    '    - sans trou → CISAILLE ;',
    '    - percée, avec L ≤ 800, l ≤ 500, Ø ≤ 32, trusquinage ≥ 25 et sans oblong → CISAILLE + P803 ;',
    '    - sinon → GEMINI.',
    '12. Toute autre pièce (forme, angles ≠ 90°, ép. > 15 mm) → nesting Steel Project par épaisseur, puis GEMINI (plasma ≤ 35 mm, oxycoupage ≤ 80 mm).',
    '',
    'Contrôles systématiques pour chaque repère : dimensions, Ø et épaisseur au droit du trou, trusquinage, longueur mini, nuance, et longueur de pièce comparée à la longueur de barre achetée.',
    '',
    '## 6. RÈGLE DE CONVERSION TÔLE → FER PLAT',
    '',
    "* Pièce RECTANGULAIRE (tous les angles à 90° ; coins coupés à 45° ≤ 25 mm = chanfreins tolérés) dont la largeur et l'épaisseur existent dans F3 → remplacer par ce fer plat. Exemple : tôle ép. 10 x 80 de large → FER PLAT 80x10.",
    '* Pièce avec au moins un angle ≠ 90° hors chanfreins (gousset, trapèze, échancrure) → RESTE EN TÔLE.',
    '* Aucun équivalent dans F3 → RESTE EN TÔLE (motif : « pas de FP disponible »).',
    "* Achat : sauf instruction contraire, les fers plats sont achetés en tôles 3000 x 1500 et refendus à la cisaille. Donne aussi, à titre d'option, les mètres linéaires par section de fer plat.",
    '',
    "## 7. TÂCHES À RÉALISER (dans l'ordre)",
    '',
    '### Tâche 1 – Comparaison F1 / F2, plan par plan et repère par repère',
    '',
    '* F2 peut répartir un même repère sur plusieurs plans (ex. 700 et 701) : ADDITIONNE les quantités de tous les plans avant de comparer.',
    '* Quantité F1 : compare la quantité du cartouche ET le total du tableau « Répartition par assemblage ». Signale tout écart.',
    '* Compare : repère (détecter les renommages, ex. W72 ↔ G10), profil, dimensions (rectangle englobant L x l x ép), quantité, nombre et Ø des trous, angles et coupes, nuance.',
    '* Jarrets : compare la longueur hors-tout F1 et la longueur CN F2 (« À VÉRIFIER ») ; vérifie que la quantité des ébauches jumelées (ex. J6XJ8) = nombre de paires nécessaires.',
    '* Repère présent dans un seul fichier : le signaler.',
    '',
    "### Tâche 2 – Tableau de vérification et d'affectation (un seul tableau, tous les repères)",
    '',
    '### Tâche 3 – Découpage de F1',
    'Divise le PDF des croquis en un classeur par moyen : 1003 DEB / A164 / TRONÇONNEUSE / CISAILLE + P803 / CISAILLE / GEMINI ép. x (un par épaisseur) / MANUEL / CHUTES. Donne pour chaque classeur la liste des repères et des numéros de pages.',
    '',
    '* Un fichier PDF par classeur, nommé « Affaire_MACHINE.pdf » (ex. 26DU_1003_DEB.pdf, 26DU_GEMINI_ép10.pdf, 26DU_CISAILLE_P803.pdf).',
    "* Chaque page de F1 est copiée telle quelle, sans modification ni recadrage, dans l'ordre des repères de F1.",
    '* Une page de F1 va dans un seul classeur, celui de la machine affectée au repère (tableau 2).',
    '* Ne crée pas de classeur vide.',
    '* Le total des pages des classeurs doit être égal au nombre de pages de F1 : aucune page oubliée, aucune page en double.',
    '* Regroupe tous les PDF et le classeur Excel dans un fichier .zip nommé « Affaire_Preparation_vX.zip ».',
    '',
    '### Tâche 4 – Mise en barre',
    '',
    '* Profilés : barres de 12 m et de 15 m ; choisis, barre par barre, la combinaison qui minimise la longueur totale achetée.',
    '* Tubes : barres de 6 m. Si une pièce dépasse la barre : « DÉPASSEMENT », propose des barres de 12 m ou un aboutage, et calcule les deux.',
    '* Cornières : barres de 12 m ; réserve la chute mini A164 de 220 mm.',
    "* Ébauches de jarrets : incluses dans les barres du profil d'origine.",
    '* Trait de scie : 5 mm entre chaque pièce.',
    "Pour chaque barre, donne : profil, longueur, repères (qté x L), chute, taux d'utilisation, machine.",
    '',
    '### Tâche 5 – Mise en tôle (nesting estimatif)',
    '',
    '* Fers plats et tôles : tout en tôles de 3000 x 1500 mm, regroupés par épaisseur.',
    '* Marge de nesting : 5 mm entre pièces et en bord de tôle.',
    '* Exclure les pièces « CHUTES ».',
    '* Vérifier pour chaque nesting GEMINI : ≤ 7 Ø différents, épaisseur ≤ 35 mm (plasma) ou ≤ 80 mm (oxycoupage).',
    "Pour chaque épaisseur, donne : nombre de tôles, surface des pièces, taux de chute, nombre d'outils. Précise que c'est une estimation à valider dans Steel Project.",
    '',
    "### Tâche 6 – Bon d'achat",
    'Regroupe les besoins des tâches 4 et 5 : désignation, dimensions, longueur ou format, quantité, nuance S275JR, poids unitaire et poids total. Indique les kg/m utilisés et leur source.',
    '',
    '## 8. FORMAT DE SORTIE',
    'Livre un classeur Excel (un onglet par tableau, totaux en formules), les PDF des classeurs par machine (tâche 3) et un .zip qui regroupe le tout.',
    '',
    '**Précision (prioritaire sur le paragraphe ci-dessus) : ne crée PAS de fichier .zip. Livre les PDF des classeurs par machine directement, un fichier PDF par classeur, en plus du classeur Excel.**',
    '',
    '### Tableau 1 – Différences F1 / F2',
    '| Plan F2 | Rep | Élément comparé | Valeur F1 | Valeur F2 | Écart (OUI / NON / À VÉRIFIER) | Action |',
    '|---|---|---|---|---|---|---|',
    'Si aucun écart pour un repère : une ligne « Conforme ».',
    '',
    '### Tableau 2 – Vérification et affectation',
    "| Rep | Qté | Profil d'origine | Dimensions | Perçages (nb x Ø) | Trusquinage mini | Angles ≠ 90° (O/N) | Profil retenu | FP dispo F3 (O/N) | Machine / moyen | Contrôle capacité (OK / DONNÉE MANQUANTE / DÉPASSEMENT / HORS CAPACITÉ) | Remarque | Page F1 |",
    '|---|---|---|---|---|---|---|---|---|---|---|---|---|',
    '',
    '### Tableau 3 – Classeurs par machine',
    '| Classeur | Repères | Pages F1 | Nb repères | Nb pièces |',
    '|---|---|---|---|---|',
    '',
    '### Tableau 4 – Mise en barre',
    '| Profil | Barre (m) | N° barre | Repères (qté x L) | Longueur utilisée | Chute (mm) | Utilisation % | Machine |',
    '|---|---|---|---|---|---|---|---|',
    '',
    '### Tableau 5 – Mise en tôle',
    '| Épaisseur | Nb tôles 3000x1500 | Repères | Surface pièces (m²) | Chute % | Machine(s) | Outils GEMINI (≤ 7) |',
    '|---|---|---|---|---|---|---|',
    '',
    "### Tableau 6 – Bon d'achat (GROUPE MATEM)",
    '| N° | Désignation | Dimensions | Longueur / format | Qté | Nuance | Poids unitaire (kg) | Poids total (kg) |',
    '|---|---|---|---|---|---|---|---|',
    'Ajoute le total du poids par famille (profilés, tubes, cornières, tôles) et le total général.',
    '',
    '## 9. CONTRÔLE FINAL (avant de répondre)',
    '',
    '* Le nombre de repères du tableau 2 = nombre de repères distincts de F1 (plus ceux de F2 seuls, signalés).',
    '* Chaque repère est affecté à une seule machine ; le total des pages des classeurs = nombre de pages de F1.',
    '* Les quantités de la mise en barre et de la mise en tôle = celles du tableau 2 (quantités F2 retenues).',
    "* Aucune pièce plus longue que sa barre d'achat sans signalement.",
    '* Toutes les mentions « DONNÉE MANQUANTE », « DÉPASSEMENT » et « HORS CAPACITÉ », ainsi que les hypothèses, sont listées dans un récapitulatif final.',
    '',
]

PROMPT = "\n".join(PROMPT_LIGNES)

DELAI_REPONSE = 3600 # secondes d'attente maximale pour la réponse de Claude
DOSSIER_SORTIE = dossier_sortie_affaire(AFFAIRE)

def echapper(texte):
    """Protège les caractères spéciaux de pywinauto (accolades, +, ^, %, ~, parenthèses)."""
    return "".join("{" + c + "}" if c in "+^%~(){}[]" else c for c in texte)
def normaliser(texte):
    """Minuscules et sans accents, pour comparer les noms de boutons."""
    t = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def boutons(fenetre):
    """Liste tous les boutons et liens visibles de la fenêtre."""
    resultat = []
    for type_ctrl in ("Button", "Hyperlink"):
        try:
            resultat.extend(fenetre.descendants(control_type=type_ctrl))
        except Exception:
            pass
    return resultat

def dossier_telechargements():
    cle = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
    guid_telechargements = "{374DE290-123F-4565-9164-39C4925E467B}"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, cle) as k:
        chemin, _ = winreg.QueryValueEx(k, guid_telechargements)
    return Path(os.path.expandvars(chemin))


def fenetre_claude():
    # Titre exact : « .*Claude.* » trouvait aussi VS Code quand testClaude.py est ouvert
    fenetres = Desktop(backend="uia").windows(title="Claude")
    if not fenetres:
        raise RuntimeError("Fenêtre Claude introuvable : ouvrez l'application puis relancez le script.")
    fenetre = fenetres[0]
    if fenetre.is_minimized():
        fenetre.restore()
    fenetre.set_focus()
    time.sleep(0.5)
    return fenetre


def comparable(texte):
    """Texte comparable : sans accents, minuscules, apostrophe typographique ’ remplacée par '."""
    return normaliser(texte.replace("’", "'").strip())


def trouver_element(fenetre, noms, types=("Button", "Hyperlink", "ListItem"), timeout=10):
    """Premier élément dont le nom est l'un de « noms » (accents, majuscules et apostrophes ignorés)."""
    cibles = {comparable(n) for n in noms}
    fin = time.time() + timeout
    while time.time() < fin:
        for type_ctrl in types:
            try:
                for c in fenetre.descendants(control_type=type_ctrl):
                    if comparable(c.window_text()) in cibles:
                        return c
            except Exception:
                pass  # interface en cours de mise à jour : on réessaie
        time.sleep(0.5)
    raise RuntimeError(f"Élément introuvable : {' / '.join(noms)}")


def attendre_boite_ouvrir(timeout=15):
    """Attend la vraie boîte « Ouvrir » visible (titre Ouvrir ou Open)."""
    fin = time.time() + timeout
    while time.time() < fin:
        for w in Desktop(backend="win32").windows(class_name="#32770", visible_only=True):
            if w.window_text().strip() in ("Ouvrir", "Open"):
                return Desktop(backend="win32").window(handle=w.handle)
        time.sleep(0.5)
    raise RuntimeError("Boîte « Ouvrir » introuvable.")


def zone_message(fenetre):
    """Zone de saisie du message (le champ le plus bas de la fenêtre)."""
    champs = fenetre.descendants(control_type="Edit")
    if not champs:
        raise RuntimeError("Zone de saisie du message introuvable.")
    return max(champs, key=lambda e: e.rectangle().top)


def donner_clavier(fenetre):
    """Donne vraiment le clavier à Claude : set_focus seul ne suffit pas toujours
    (après Steel Projects, les raccourcis partaient ailleurs). Un clic dans la zone de message, si."""
    fenetre.set_focus()
    zone_message(fenetre).click_input()
    time.sleep(0.5)


def nouvelle_discussion(fenetre):
    """Ouvre une nouvelle discussion par le bouton « Nouveau » (au lieu de Ctrl+N)."""
    fenetre.set_focus()
    trouver_element(fenetre, ("Nouveau", "Nouvelle discussion", "Nouveau chat"), types=("Button",)).click_input()
    time.sleep(3)  # laisser le temps à la nouvelle discussion de s'ouvrir


def joindre_fichier(fenetre, chemin, essais=3):
    if not os.path.exists(chemin):
        raise FileNotFoundError(f"Fichier introuvable : {chemin}")

    # Ancienne interface : bouton « Choisir des fichiers » ;
    # nouvelle (fenêtre « Importer ou ajouter des fichiers ») : élément de liste « Importer depuis l’ordinateur »
    noms = ("Choisir des fichiers", "Importer depuis l'ordinateur")
    for essai in range(1, essais + 1):
        donner_clavier(fenetre)
        send_keys("^u")
        try:
            element = trouver_element(fenetre, noms, timeout=5)
            break
        except RuntimeError:
            print(f"Fenêtre d'import non ouverte (essai {essai}/{essais})")
            send_keys("{ESC}")
    else:
        raise RuntimeError("Ctrl+U n'ouvre pas la fenêtre d'import de Claude.")
    element.click_input()

    try:
        boite = attendre_boite_ouvrir(timeout=5)
    except RuntimeError:
        # Nouvelle interface en deux temps : « Importer depuis l’ordinateur » affiche
        # un bouton « Choisir des fichiers », qui ouvre la boîte « Ouvrir »
        trouver_element(fenetre, ("Choisir des fichiers",), types=("Button",), timeout=5).click_input()
        boite = attendre_boite_ouvrir()
    boite.set_focus()
    time.sleep(0.5)
    # Le champ « Nom de fichier » a le focus à l'ouverture : on y tape le chemin complet
    send_keys(echapper(chemin), with_spaces=True, pause=0.01)
    time.sleep(0.5)
    send_keys("{ENTER}")  # équivaut à cliquer sur « Ouvrir »

    fin = time.time() + 10
    while time.time() < fin and boite.exists():
        time.sleep(0.5)
    time.sleep(2)

def envoyer_prompt(fenetre):
    zone = zone_message(fenetre)

    # Collage par le presse-papiers : quelques secondes au lieu de plusieurs minutes de frappe,
    # et pas de risque qu'une touche pressée pendant la saisie corrompe le prompt
    copier_presse_papiers(PROMPT)
    zone.click_input()
    time.sleep(0.5)
    send_keys("^v")
    time.sleep(3)  # laisser Claude intégrer le texte collé
    send_keys("{ENTER}")  # envoi du message


def copier_presse_papiers(texte):
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(texte, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


EXTENSIONS = ("*.pdf", "*.xlsx")


def boutons_telechargement(fenetre):
    """Tous les boutons « Télécharger… » de la discussion (images exclues)."""
    resultat = []
    for c in boutons(fenetre):
        low = normaliser(c.window_text().strip())
        if not low or "image" in low:
            continue
        if low.startswith(("telecharg", "download")):  # exclut « Plus d'options pour … download … »
            resultat.append(c)
    return resultat


def boutons_au_premier_plan(fenetre):
    """Ramène brièvement Claude au premier plan pour lire des boutons à jour, puis rend la main.

    En arrière-plan, Claude ne met plus à jour ses boutons pour le script : la réponse
    pouvait être finie sans que le script la voie.
    """
    precedente = win32gui.GetForegroundWindow()
    if precedente == fenetre.handle:
        return boutons_telechargement(fenetre)
    try:
        fenetre.set_focus()
        time.sleep(2)
        return boutons_telechargement(fenetre)
    finally:
        try:
            Desktop(backend="win32").window(handle=precedente).set_focus()
        except Exception:
            pass  # fenêtre précédente fermée entre-temps


def attendre_tous_les_fichiers(fenetre, timeout, stabilite=120, rafraichissement=120):
    """Attend que le nombre de boutons de téléchargement reste stable pendant « stabilite » s."""
    fin = time.time() + timeout
    nb_prec, depuis = -1, time.time()
    dernier_message = 0
    dernier_rafraichissement = time.time()
    while time.time() < fin:
        if time.time() - dernier_rafraichissement >= rafraichissement:
            liste = boutons_au_premier_plan(fenetre)
            dernier_rafraichissement = time.time()
        else:
            liste = boutons_telechargement(fenetre)
        if len(liste) != nb_prec:
            nb_prec, depuis = len(liste), time.time()
            print(f"{datetime.now():%H:%M:%S} – {len(liste)} fichier(s) détecté(s).")
            dernier_message = time.time()
        elif liste and time.time() - depuis >= stabilite:
            return sorted(liste, key=lambda b: b.rectangle().top)
        if time.time() - dernier_message >= 60:  # message d'attente toutes les minutes
            etat = "vérification que la réponse est finie" if liste else "réponse en cours"
            print(f"{datetime.now():%H:%M:%S} – {etat}, {len(liste)} fichier(s) détecté(s).")
            dernier_message = time.time()
        time.sleep(3)
    return []


def chercher_fichiers_recents(debut, deja):
    """Cherche les PDF/XLSX modifiés après « debut », hors fichiers déjà récupérés."""
    dossiers = [
        dossier_telechargements(),
        Path(os.environ.get("TEMP", r"C:\Windows\Temp")),
        Path.home() / "Desktop",
        Path.home() / "Documents",
    ]
    trouves = []
    for d in dossiers:
        if not d.exists():
            continue
        for motif in EXTENSIONS:
            try:
                fichiers = list(d.glob(motif)) + list(d.glob("*/" + motif))
            except Exception:
                continue
            for f in fichiers:
                try:
                    if (f not in deja and not f.name.startswith("~$")
                            and f.stat().st_mtime >= debut - 2
                            and not Path(str(f) + ".crdownload").exists()):
                        trouves.append(f)
                except Exception:
                    continue
    return sorted(trouves, key=lambda f: f.stat().st_mtime, reverse=True)


def attendre_nouveau_fichier(debut, deja, timeout=30):
    """Attend un nouveau fichier téléchargé et la fin de son écriture."""
    fin = time.time() + timeout
    while time.time() < fin:
        time.sleep(2)
        trouves = chercher_fichiers_recents(debut, deja)
        if trouves:
            f = trouves[0]
            taille = -1
            while taille != f.stat().st_size:
                taille = f.stat().st_size
                time.sleep(1)
            return f
    return None

def nom_unique(dossier, nom):
    """Renvoie un chemin qui n'existe pas encore (ajoute _2, _3... si besoin)."""
    cible = dossier / nom
    compteur = 2
    while cible.exists():
        cible = dossier / f"{Path(nom).stem}_{compteur}{Path(nom).suffix}"
        compteur += 1
    return cible

def nom_propre(source):
    """Retire le suffixe _1, _2… ajouté au téléchargement quand le nom existait déjà."""
    m = re.match(r"^(.*)_\d+$", source.stem)
    if m and (source.parent / (m.group(1) + source.suffix)).exists():
        return m.group(1) + source.suffix
    return source.name


def empreinte(chemin):
    return hashlib.md5(Path(chemin).read_bytes()).hexdigest()


def cliquer_bouton(fenetre, bouton):
    """Fait défiler jusqu'au bouton puis clique à la souris (invoke() échoue hors écran)."""
    fenetre.set_focus()  # Excel ou Acrobat a pu prendre le focus au clic précédent
    try:
        bouton.iface_scroll_item.ScrollIntoView()
    except Exception:
        pass
    time.sleep(1)
    try:
        bouton.click_input()
    except Exception:
        bouton.invoke()


def telecharger_bouton(fenetre, i, deja, essais=2):
    """Clique le i-ème bouton de téléchargement ; reclique une fois si aucun fichier n'arrive."""
    for essai in range(1, essais + 1):
        # liste relue à chaque fois : elle peut changer après un clic ou un défilement
        liste = sorted(boutons_telechargement(fenetre), key=lambda b: b.rectangle().top)
        if i > len(liste):
            return None
        debut = time.time()
        cliquer_bouton(fenetre, liste[i - 1])
        source = attendre_nouveau_fichier(debut, deja)
        if source is not None:
            return source
        if essai < essais:
            print(f"[{i}] Aucun fichier après le clic, nouvel essai...")
    return None


def enregistrer_fichiers_produits(fenetre, dossier_sortie=DOSSIER_SORTIE):
    """Télécharge tous les fichiers de la réponse dans dossier_sortie ; renvoie les chemins copiés."""
    os.makedirs(dossier_sortie, exist_ok=True)

    liste = attendre_tous_les_fichiers(fenetre, DELAI_REPONSE)
    if not liste:
        print("Aucun bouton de téléchargement trouvé. Boutons visibles :")
        for c in boutons(fenetre):
            if c.window_text():
                print(" -", repr(c.window_text()))
        return []

    total = len(liste)
    print(f"{total} fichier(s) à télécharger.")
    deja = set()
    copies = set()  # empreintes des fichiers déjà copiés (évite les doublons)
    resultats = []
    for i in range(1, total + 1):
        source = telecharger_bouton(fenetre, i, deja)
        if source is None:
            print(f"[{i}/{total}] ÉCHEC : aucun fichier téléchargé.")
            continue
        deja.add(source)
        h = empreinte(source)
        if h in copies:
            print(f"[{i}/{total}] {source.name} : doublon ignoré.")
            continue
        copies.add(h)
        os.makedirs(dossier_sortie, exist_ok=True)  # recréé s'il a été supprimé pendant l'attente
        destination = nom_unique(Path(dossier_sortie), nom_propre(source))
        shutil.copy2(str(source), str(destination))
        resultats.append(destination)
        print(f"[{i}/{total}] {source.name} -> {destination}")
        time.sleep(2)

    print(f"{len(resultats)} fichier(s) enregistré(s) dans {dossier_sortie}")
    return resultats


def comparer_avec_claude(fichiers=FICHIERS, dossier_sortie=DOSSIER_SORTIE):
    """Envoie les fichiers et le prompt à Claude, puis télécharge sa réponse dans dossier_sortie."""
    manquants = [f for f in fichiers if not os.path.exists(f)]
    if manquants:  # vérifié avant d'ouvrir une discussion
        raise FileNotFoundError("Fichier(s) introuvable(s) :\n" + "\n".join(manquants))

    fenetre = fenetre_claude()

    nouvelle_discussion(fenetre)

    for chemin in fichiers:
        print("Ajout :", chemin)
        joindre_fichier(fenetre, chemin)
    fenetre.set_focus()
    print("Les fichiers sont joints. Envoi du prompt...")
    envoyer_prompt(fenetre)
    print(f"Message envoyé. Attente de la réponse (jusqu'à {DELAI_REPONSE} s)...")
    return enregistrer_fichiers_produits(fenetre, dossier_sortie)


if __name__ == "__main__":
    comparer_avec_claude()