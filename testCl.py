import os
import shutil
import time
import unicodedata
import winreg
from datetime import datetime
from pathlib import Path
from collections import Counter

from pywinauto import Desktop
from pywinauto.keyboard import send_keys

IMPORT_DIRECTORY = r"C:\Users\E.BENAMOR\Desktop\01XY"
AFFAIRE = IMPORT_DIRECTORY.split("\\")[-1]

FICHIERS = [
    r"C:\Users\E.BENAMOR\Desktop\projetTravailler\02XY\02XY PLM.PDF",
    r"C:\Users\E.BENAMOR\Desktop\projetTravailler\02XY\CROQUIS DEBITAGE 02XY.pdf",
    r"C:\Users\E.BENAMOR\Desktop\projetTravailler\FER PLAT.xlsx"
]
 


PROMPT_LIGNES = [
    '',
    '# PROMPT – PRÉPARATION DE FABRICATION (GROUPE MATEM)',
    '',
    '## 1. RÔLE',
    'Tu es préparateur de fabrication en construction métallique pour GROUPE MATEM, expert en charpente métallique, en programmation CNC FICEP et en optimisation matière (mise en barre et mise en tôle).',
    '',
    "## 2. FICHIERS D'ENTRÉE",
    '| Réf. | Fichier | Rôle |',
    '|---|---|---|',
    '| F1 | « fichier 1.pdf » | Croquis de débitage à répartir (document de travail) |',
    '| F2 | « fichier 2.pdf » | Plans de référence (document qui fait foi) |',
    '| F3 | « Tableau fers plats disponibles » | Liste des fers plats standard en stock (largeur × épaisseur) |',
    '',
    'Si un fichier est absent ou illisible, arrête-toi et signale-le. Ne poursuis pas avec des données supposées.',
    '',
    '## 3. RÈGLES GÉNÉRALES (OBLIGATOIRES)',
    "- R1 : Utilise UNIQUEMENT les caractéristiques machines de la section 4 et les données des fichiers. N'invente aucune valeur. Si une donnée manque, écris « DONNÉE MANQUANTE : … ».",
    '- R2 : Traite TOUS les repères, un par un, sans en oublier et sans doublon. Chaque repère est affecté à UNE SEULE machine (sans recoupement).',
    "- R3 : En cas de divergence entre F1 et F2, c'est F2 qui fait foi. Signale la divergence, ne la corrige pas en silence.",
    '- R4 : Nuance de tous les matériaux : S275.',
    "- R5 : Un repère qu'aucune machine ne peut réaliser est marqué « HORS CAPACITÉ », avec la caractéristique dépassée.",
    '',
    "## 4. MOYENS DE L'ATELIER",
    '',
    "### MACHINE 1 – FICEP A164 : ligne d'usinage de cornières",
    '(Poinçonnage, marquage et coupe de cornières et de fers plats)',
    '',
    'Profilés usinables :',
    '- Cornières (acier 410 N/mm²) : mini 30x30x3 mm, maxi 160x160x19 mm',
    '- Fers plats (avec outillage en option) : mini 50x5 mm, maxi 160x19 mm',
    '',
    'Poinçonnage :',
    '- Capacité maxi de poinçonnage : 720 kN',
    '- Diamètres disponibles sur chaque aile de la cornière : 2',
    '- Diamètre maxi avec outillage standard : 32 mm',
    '- Diamètre x épaisseur maxi : 30x19 mm (acier 410 N/mm²), 25x19 mm (acier 510 N/mm²)',
    '',
    'Coupe :',
    '- Force maxi de coupe : 2200 kN (cisaillage)',
    '',
    'Autres :',
    '- Vitesse maxi de translation longitudinale de la barre : 40 m/min',
    '- Vitesse de positionnement des axes de traçage (trusquin) : 7 m/min',
    '- Longueur mini de chute de fin de barre : 220 mm',
    "- Nombre d'axes CNC : 6",
    '- Tolérances des profilés : UNI 5783-73 et UNI 5784-73',
    '',
    '### MACHINE 2 – FICEP GEMINI 254 PG : portique CNC de perçage, fraisage et coupe plasma de tôles',
    '',
    'Alimentation :',
    '- 400 V triphasé, 50 Hz, puissance installée 65 kW',
    "- Pression d'air : 6 à 8 bar",
    '',
    "Tôle à l'entrée :",
    '- Longueur : mini 1250 mm, maxi 12100 mm',
    '- Largeur : mini 800 mm, maxi 2540 mm',
    '',
    'Pièce à la sortie :',
    '- Longueur mini : 100 mm, largeur mini : 100 mm',
    '',
    'Perçage / fraisage :',
    '- 1 tête de perçage verticale, 1 broche',
    '- Diamètre maxi de perçage : 32 mm',
    '- Diamètre maxi de fraisage : 240 mm',
    '- Épaisseur de tôle : mini 5 mm, maxi de perçage 80 mm',
    '- Poussée axiale maxi (perçage) : 3200 N',
    '- Puissance broche (S3) : 11 kW',
    '- Vitesse de broche : 250 à 6000 tr/min, réglable en continu par programme',
    '',
    'Coupe plasma (option) :',
    '- HPR260XD : pleine tôle 38 mm, bord de tôle 64 mm, coupe inclinée 45° pleine tôle 27 mm, coupe inclinée 45° bord de tôle 45 mm',
    '- HPR400XD : pleine tôle 50 mm, bord de tôle 80 mm, coupe inclinée 45° pleine tôle 35 mm, coupe inclinée 45° bord de tôle 56 mm',
    '',
    'Vitesses et divers :',
    '- Translation longitudinale X maxi : 32 m/min',
    '- Positionnement transversal Y : 42 m/min, axe auxiliaire U : 42 m/min',
    '- Hauteur de travail : 650 mm',
    '- Normes tôle brute : UNI EN 10025 (fourniture), UNI EN 10029 (tolérances)',
    '',
    '### MACHINE 3 – FICEP 1003 DEB : ligne de perçage et de sciage CNC pour profilés lourds',
    '(Poutrelles, fers U, cornières, plats, tubes)',
    '',
    'Tous profilés :',
    '- Hauteur : mini 80 mm, maxi 1015 mm',
    '- Largeur : mini 10 mm, maxi 450 mm',
    '- Longueur mini transférable : 2500 mm (longueur maxi selon lay-out)',
    '',
    'Profilés acceptés :',
    '- Poutrelles double T (laminées ou reconstituées, sans cambrage) : hauteur 80 à 1015 mm, largeur des ailes 42 à 450 mm',
    '- Fers U (âme en bas) : hauteur 80 à 1015 mm, largeur des ailes 45 à 300 mm',
    '- Cornières (même inégales) : mini 80x80x8 mm, maxi 250x250x40 mm',
    '- Plats : largeur 100 à 1000 mm',
    '- Tubes carrés : 80x80 à 450x450 mm',
    '- Tubes rectangulaires : 80x40 à 1000x450 mm',
    '',
    'Perçage :',
    '- 3 têtes (1 verticale + 2 horizontales), 1 broche par tête',
    '- Diamètre maxi de perçage : 40 mm, épaisseur maxi de perçage : 100 mm',
    '- Puissance broche (S6-40%) : 27 kW, cône outil ISO 40',
    '- Vitesse de broche : 180 à 5000 tr/min, avance en perçage : 40 à 1000 mm/min',
    '- Approche/retour rapide : 12 m/min',
    '- Course trusquin : tête verticale 0 à 1015 mm, têtes horizontales -5 à 455 mm',
    '',
    'Coupe (scie à ruban) :',
    '- Coupe à 90° : mini 80x10 mm, maxi 1015x450 mm',
    '- Coupe à 45° : maxi 620x450 mm ; coupe à 60° : maxi 350x350 mm',
    '- Moteur ruban 9 kW, ruban 41x1,3x7880 mm, vitesse du ruban 60 à 170 m/min',
    '- Course de coupe : 0 à 450 mm',
    '',
    'Autres :',
    '- Poids maxi positionnable : 5400 kg, poids linéaire maxi : 220 kg/m',
    '- Translation longitudinale maxi : 50 m/min',
    '- Positionnement têtes horizontales : 12 m/min, tête verticale : 30 m/min',
    '- Hauteur de travail : 850 mm',
    '- Normes : UNI EN 10025 (fourniture) ; tolérances UNI ISO 5679, UNI ISO 5680, UNI 5397, UNI 5398, UNI EN 10024, UNI EN 10034, UNI EN 10279, UNI EN 10056-1, UNI EN 10056-2',
    '',
    '### MOYENS COMPLÉMENTAIRES',
    '- CISAILLE GUILLOTINE : épaisseur maxi 15 mm, longueur de coupe maxi 4000 mm (coupes droites uniquement).',
    "- POINÇONNEUSE FICEP P803 : poinçonnage des pièces cisaillées. Capacités non fournies : si un repère dépend d'une capacité de la P803, écris « DONNÉE MANQUANTE – capacité P803 ».",
    '- TRONÇONNEUSE LINÉAIRE : découpe des jarrets, pour séparer un profilé en deux jarrets.',
    '',
    "## 5. RÈGLES D'AFFECTATION (dans cet ordre)",
    '1. Jarrets (profilé découpé en deux jarrets) → TRONÇONNEUSE LINÉAIRE.',
    '2. Profilés lourds (IPE, HEA, HEB, UPN/UPE, tubes, grandes cornières ≥ 80x80x8, plats ≥ 100 mm) à percer et/ou scier → 1003 DEB (vérifier longueur ≥ 2500 mm, sinon le signaler).',
    '3. Petites cornières (≤ 160x160x19) et fers plats (≤ 160x19) avec trous Ø ≤ 32 mm → A164.',
    "4. Cornière entre 80x80x8 et 160x160x19 → A164 par défaut ; 1003 DEB si l'épaisseur ou le diamètre dépasse la capacité de poinçonnage, ou si une coupe d'onglet est nécessaire.",
    '5. Pièces en tôle rectangulaires, épaisseur ≤ 15 mm, longueur ≤ 4000 mm → CISAILLE + P803.',
    "6. Pièces en tôle de forme (angles ≠ 90°, découpes, échancrures) ou épaisseur > 15 mm → nesting Steel Project par épaisseur, puis GEMINI 254 PG (plasma jusqu'à 30 mm d'épaisseur).",
    '7. Petites pièces : tôle ou fer plat rectangulaire < 100 x 100 mm → à fabriquer dans les CHUTES (noter « CHUTE » et la machine utilisée). Rappel : la GEMINI ne sort pas de pièce < 100 x 100 mm.',
    "8. Contrôles systématiques : dimensions du profil, diamètre et épaisseur au droit du trou, longueur mini, nuance d'acier.",
    '',
    '## 6. RÈGLE DE CONVERSION TÔLE → FER PLAT',
    "- Une pièce en tôle RECTANGULAIRE (tous les angles à 90°, chanfreins tolérés) dont la largeur et l'épaisseur correspondent à un fer plat standard du tableau F3 → remplacer par ce fer plat.",
    '  Exemple : tôle ép. 10 x 80 de large → FER PLAT 80x10.',
    '- Une pièce avec un ou plusieurs angles différents de 90° (hors chanfreins) → RESTE EN TÔLE.',
    '- Aucun fer plat équivalent dans F3 → RESTE EN TÔLE (motif : « pas de FP disponible »).',
    "- N'utilise QUE les fers plats listés dans F3.",
    '',
    "## 7. TÂCHES À RÉALISER (dans l'ordre)",
    '',
    '### Tâche 1 – Comparaison F1 / F2, plan par plan et repère par repère',
    'Pour chaque repère, compare : désignation du profil, dimensions (L x l x ép.), quantité, nombre et diamètre des trous, angles et coupes, nuance.',
    '',
    "### Tâche 2 – Tableau de vérification et d'affectation (un seul tableau, tous les repères)",
    '',
    '### Tâche 3 – Découpage de F1',
    'Divise le PDF des croquis en classeurs séparés, un par moyen :',
    '1003 DEB / A164 / GEMINI (par épaisseur) / CISAILLE + P803 / TRONÇONNEUSE / CHUTES.',
    'Donne pour chaque classeur la liste des repères et des numéros de pages.',
    '',
    '### Tâche 4 – Mise en barre',
    '- Profilés : barres de 12 m et 15 m (choisir la combinaison qui donne le moins de chute)',
    '- Tubes : barres de 6 m',
    '- Cornières : barres de 12 m',
    '- Trait de scie : 5 mm entre chaque pièce',
    '- Respecter la chute mini de fin de barre de la machine affectée (A164 : 220 mm)',
    "Pour chaque barre, donner : profil, longueur de barre, repères placés (avec quantité et longueur), chute restante, taux d'utilisation.",
    '',
    '### Tâche 5 – Mise en tôle (nesting estimatif)',
    '- Fers plats et tôles : tout est pris en tôles de 3000 x 1500 mm',
    '- Regrouper par épaisseur',
    '- Marge de nesting : 5 mm entre pièces et en bord de tôle',
    "- Plasma GEMINI jusqu'à 30 mm d'épaisseur",
    "Pour chaque épaisseur : nombre de tôles, surface utile, taux de chute. Préciser que c'est une estimation à valider dans Steel Project.",
    '',
    "### Tâche 6 – Bon d'achat",
    "Regroupe les besoins issus des tâches 4 et 5 pour établir le bon d'achat.",
    '',
    '## 8. FORMAT DE SORTIE',
    '',
    'OBLIGATOIRE : toute la réponse est fournie dans UN SEUL fichier Excel (.xlsx). Chaque tableau (Tableau 1 à Tableau 6) est un onglet distinct, nommé « Tableau 1 » à « Tableau 6 ». Un onglet « Récapitulatif » liste toutes les valeurs « DONNÉE MANQUANTE » et « HORS CAPACITÉ ». Ne recopie pas les tableaux en texte dans le message : la réponse écrite se limite au nom du fichier livré et à un bref résumé.',
    '',
    '### Tableau 1 – Différences F1 / F2',
    '| Plan | Rep | Élément comparé | Valeur F1 | Valeur F2 | Écart | Action |',
    '|---|---|---|---|---|---|---|',
    'Si aucun écart pour un repère : une ligne « Conforme ».',
    '',
    '### Tableau 2 – Vérification et affectation',
    "| Rep | Qté | Profil d'origine | Dimensions | Angles ≠ 90° (O/N) | Profil retenu | FP dispo F3 (O/N) | Machine / moyen | Contrôle capacité (OK / dépassement) | Remarque |",
    '|---|---|---|---|---|---|---|---|---|---|',
    '',
    '### Tableau 3 – Classeurs par machine',
    '| Classeur | Repères | Pages F1 | Nb pièces |',
    '|---|---|---|---|',
    '',
    '### Tableau 4 – Mise en barre',
    '| Profil | Barre (m) | N° barre | Repères (qté x L) | Chute (mm) | Utilisation % |',
    '|---|---|---|---|---|---|',
    '',
    '### Tableau 5 – Mise en tôle',
    '| Épaisseur | Nb tôles 3000x1500 | Repères | Surface pièces (m²) | Chute % | Machine |',
    '|---|---|---|---|---|---|',
    '',
    "### Tableau 6 – Bon d'achat (GROUPE MATEM)",
    '| N° | Désignation | Dimensions | Longueur / format | Qté | Nuance | Poids unitaire (kg) | Poids total (kg) |',
    '|---|---|---|---|---|---|---|---|',
    'Ajouter le total du poids par famille (profilés, tubes, cornières, tôles) et le total général.',
    '',
    '## 9. CONTRÔLE FINAL (avant de répondre)',
    '- Le nombre de repères du tableau 2 est égal au nombre total de repères de F1 et F2.',
    '- Chaque repère est affecté à une seule machine.',
    '- Les quantités de la mise en barre et de la mise en tôle correspondent à celles du tableau 2.',
    '- Toutes les valeurs « DONNÉE MANQUANTE » et « HORS CAPACITÉ » sont listées dans un récapitulatif à la fin.',
]

DELAI_REPONSE = 1800 # secondes d'attente maximale pour la réponse de Claude
DOSSIER_SORTIE = os.path.join(r"C:\Users\E.BENAMOR\Desktop\projetTravailler", AFFAIRE)

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
    fenetres = Desktop(backend="uia").windows(title_re=r".*Claude.*")
    if not fenetres:
        raise RuntimeError("Fenêtre Claude introuvable : ouvrez l'application puis relancez le script.")
    fenetre = fenetres[0]
    fenetre.set_focus()
    time.sleep(0.5)
    return fenetre


def boutons_claude(fenetre):
    resultat = []
    for type_ctrl in ("Button", "Hyperlink"):
        try:
            resultat.extend(fenetre.descendants(control_type=type_ctrl))
        except Exception:
            pass
    return resultat


def trouver_bouton(fenetre, nom, timeout=10):
    fin = time.time() + timeout
    while time.time() < fin:
        for c in boutons_claude(fenetre):
            if c.window_text() == nom:
                return c
        time.sleep(0.5)
    raise RuntimeError(f"Bouton introuvable : {nom}")


def attendre_boite_ouvrir(timeout=15):
    """Attend la vraie boîte « Ouvrir » visible (titre Ouvrir ou Open)."""
    fin = time.time() + timeout
    while time.time() < fin:
        for w in Desktop(backend="win32").windows(class_name="#32770", visible_only=True):
            if w.window_text().strip() in ("Ouvrir", "Open"):
                return Desktop(backend="win32").window(handle=w.handle)
        time.sleep(0.5)
    raise RuntimeError("Boîte « Ouvrir » introuvable.")


def champ_nom_fichier(boite):
    # 1) Champ Edit identifié par son numéro de contrôle (1148)
    champ = boite.child_window(control_id=1148, class_name="Edit")
    if champ.exists(timeout=2):
        return champ

    # 2) Sinon, la zone combo du nom de fichier (contrôle 1148), puis son champ Edit
    combo = boite.child_window(control_id=1148, class_name="ComboBoxEx32")
    if combo.exists(timeout=2):
        return combo.child_window(class_name="Edit", found_index=0)

    # 3) Dernier recours : premier champ Edit de la boîte
    return boite.child_window(class_name="Edit", found_index=0)


def joindre_pdf(fenetre, chemin):
    if not os.path.exists(chemin):
        raise FileNotFoundError(f"PDF introuvable : {chemin}")
    fenetre.set_focus()
    send_keys("^u")
    time.sleep(1.5)

    trouver_bouton(fenetre, "Choisir des fichiers").click_input()
    time.sleep(1.5)

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
    champs = fenetre.descendants(control_type="Edit")
    if not champs:
        raise RuntimeError("Zone de saisie du message introuvable.")
    zone = max(champs, key=lambda e: e.rectangle().top)  # la zone de message est tout en bas

    zone.click_input()
    time.sleep(0.5)
    for i, ligne in enumerate(PROMPT_LIGNES):
        if ligne:
            zone.type_keys(echapper(ligne), with_spaces=True, pause=0.01)
        if i < len(PROMPT_LIGNES) - 1:
            send_keys("+{ENTER}")  # saut de ligne sans envoyer
    time.sleep(0.5)
    send_keys("{ENTER}")  # envoi du message


def noms_boutons(fenetre):
    """Compte les boutons visibles par leur nom, avant l'envoi du prompt."""
    return Counter(c.window_text().strip() for c in boutons_claude(fenetre) if c.window_text().strip())


def attendre_pdf_produit(fenetre, timeout, avant):
    """Attend le bouton de téléchargement du PDF de la dernière réponse (les images sont ignorées)."""
    fin = time.time() + timeout
    while time.time() < fin:
        actuels = boutons(fenetre)
        compte_actuel = Counter(c.window_text().strip() for c in actuels if c.window_text().strip())
        candidats = []
        for c in actuels:
            nom = c.window_text().strip()
            low = normaliser(nom)
            if not nom or "marquer" in low or "non lu" in low or "image" in low:
                continue
            if not any(m in low for m in ("telecharg", "download")):
                continue
            nouveau = compte_actuel[nom] > avant.get(nom, 0)
            if nouveau or "ouvrir" in low:
                candidats.append(c)
        if candidats:
            # le plus bas à l'écran = réponse la plus récente
            return sorted(candidats, key=lambda b: b.rectangle().top, reverse=True)[0]
        time.sleep(3)
    return None

def chercher_pdf_recent(debut):
    """Cherche les PDF modifiés après « debut » dans les dossiers probables."""
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
        try:
            fichiers = list(d.glob("*.pdf")) + list(d.glob("*/*.pdf"))
        except Exception:
            continue
        for f in fichiers:
            try:
                if f.stat().st_mtime >= debut - 2 and not Path(str(f) + ".crdownload").exists():
                    trouves.append(f)
            except Exception:
                continue
    return sorted(trouves, key=lambda f: f.stat().st_mtime, reverse=True)

def nom_unique(dossier, nom):
    """Renvoie un chemin qui n'existe pas encore (ajoute _2, _3... si besoin)."""
    cible = dossier / nom
    compteur = 2
    while cible.exists():
        cible = dossier / f"{Path(nom).stem}_{compteur}{Path(nom).suffix}"
        compteur += 1
    return cible

def enregistrer_pdf_produit(fenetre, avant):
    os.makedirs(DOSSIER_SORTIE, exist_ok=True)

    bouton = attendre_pdf_produit(fenetre, DELAI_REPONSE, avant)
    if bouton is None:
        print("Bouton de téléchargement introuvable. Boutons visibles :")
        for c in boutons(fenetre):
            if c.window_text():
                print(" -", repr(c.window_text()))
        return

    print("Bouton trouvé :", repr(bouton.window_text()))
    time.sleep(5)
    debut = time.time()
    bouton.click_input()
    print("Clic effectué. Recherche du PDF (Téléchargements, dossier temporaire, Bureau, Documents)...")

    trouves = []
    fin = time.time() + 120
    while time.time() < fin and not trouves:
        time.sleep(2)
        trouves = chercher_pdf_recent(debut)

    if not trouves:
        print("Aucun PDF trouvé après le clic.")
        return

    source = trouves[0]
    print("PDF trouvé :", source)
    destination = nom_unique(Path(DOSSIER_SORTIE), f"Comparaison_{datetime.now():%Y%m%d_%H%M}.pdf")
    shutil.copy2(str(source), str(destination))
    print("PDF copié vers :", destination)


if __name__ == "__main__":
    fenetre = fenetre_claude()

    # Nouvelle discussion (Ctrl+N) avant de joindre les fichiers
    fenetre.set_focus()
    send_keys("^n")
    time.sleep(3)  # laisser le temps à la nouvelle discussion de s'ouvrir

    for chemin in FICHIERS:
        print("Ajout :", chemin)
        joindre_pdf(fenetre, chemin)
    fenetre.set_focus()
    print("Les fichiers sont joints. Écriture du prompt...")
    avant = noms_boutons(fenetre)  # photo des boutons avant l'envoi
    envoyer_prompt(fenetre)
    print(f"Message envoyé. Attente de la réponse (jusqu'à {DELAI_REPONSE} s)...")
    enregistrer_pdf_produit(fenetre, avant)