import os
import shutil
import time
import unicodedata
import winreg
from collections import Counter
from datetime import datetime
from pathlib import Path

from pywinauto import Desktop
from pywinauto.keyboard import send_keys

PDF_FICHIERS = [
    r"C:\Users\E.BENAMOR\Desktop\Impressions Steel Projects\26IR C D.pdf",
    r"Y:\26IR-IRISOLARIS\4.DOSSIER DE FABRICATION\STRUCTURE\CROQUIS\DEBITAGE\CROQUIS DEBITAGE.pdf",
]

PROMPT_LIGNES = [
    "Compare intégralement les deux PDF, plan par plan et repère par repère, sans omission.",
    "",
    "COMPARAISON :",
    "Pour chaque repère, vérifier présence, quantité, profil, épaisseur, dimensions,",
    "cotes, trous, perçages, angles, chanfreins et géométrie dans toutes les vues.",
    "Indiquer précisément chaque différence entre PDF1 et PDF2.",
    "",
    "OPTIMISATION :",
    "Proposer le remplacement des tôles par du fer plat standard lorsque possible.",
    "Exemple : tôle 10 mm largeur 80 mm => fer plat 80x10.",
    "Pour W11, W38 et W40, si plusieurs angles à 90° hors chanfreins,",
    "conserver obligatoirement la fabrication en tôle.",
    "Justifier chaque substitution et indiquer A VALIDER si nécessaire.",
    "",
    "MACHINES DISPONIBLES :",
    "FICEP 1003DB : profilés et perçage.",
    "FICEP Gemini : tôles, perçage, plasma, oxycoupage (12000x2000 mm).",
    "FICEP A164 : cornières.",
    "Cisaille guillotine : épaisseur max 15 mm, longueur max 4000 mm.",
    "FICEP P803 : poinçonnage.",
    "Affecter chaque repère à la machine adaptée selon ses capacités.",
    "",
    "RAPPORT :",
    "Créer un tableau complet avec :",
    "Repère | Qté PDF1 | Qté PDF2 | Profil PDF1 | Profil PDF2 |",
    "Epaisseur | Dimensions | Différences | Fer plat proposé |",
    "Machine | Fabrication | Observations.",
    "",
    "Ajouter un tableau des substitutions en fer plat à vérifier.",
    "Indiquer les pages des plans et les repères absents.",
    "",
    "FORMAT :",
    "Générer un PDF professionnel A4 paysage, téléchargeable.",
    "Aucune colonne coupée, retour à la ligne et en-têtes répétés.",
    "Répartir le tableau sur plusieurs pages si nécessaire.",
    "",
    "REGLES :",
    "Analyser tous les repères et toutes les vues.",
    "Ne rien inventer. Signaler les informations illisibles.",
    "Ne pas confondre chanfreins et angles.",
    "Ne proposer aucune substitution sans justification technique.",
]

DELAI_REPONSE = 1800 
DOSSIER_SORTIE = r"C:\Users\E.BENAMOR\Desktop\Comparaison TEKLA et PLM"


def normaliser(texte):
    """Minuscules et sans accents, pour comparer les noms de boutons."""
    t = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def echapper(texte):
    """Protège les caractères spéciaux de pywinauto."""
    return "".join("{" + c + "}" if c in "+^%~(){}[]" else c for c in texte)


def dossier_telechargements():
    cle = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
    guid_telechargements = "{374DE290-123F-4565-9164-39C4925E467B}"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, cle) as k:
        chemin, _ = winreg.QueryValueEx(k, guid_telechargements)
    return Path(os.path.expandvars(chemin))


def fenetre_chatgpt():
    fenetre = Desktop(backend="uia").window(title="ChatGPT", control_type="Window")
    fenetre.set_focus()
    time.sleep(1)
    return fenetre.wrapper_object()


def boutons(fenetre):
    resultat = []
    for type_ctrl in ("Button", "Hyperlink"):
        try:
            resultat.extend(fenetre.descendants(control_type=type_ctrl))
        except Exception:
            pass
    return resultat


def trouver_bouton(fenetre, morceau, timeout=10):
    cible = normaliser(morceau)
    fin = time.time() + timeout
    while time.time() < fin:
        for c in boutons(fenetre):
            if cible in normaliser(c.window_text()):
                return c
        time.sleep(0.5)
    raise RuntimeError(f"Bouton introuvable : {morceau}")


def noms_boutons(fenetre):
    """Compte les boutons par nom, avant l'envoi du prompt."""
    return Counter(c.window_text().strip() for c in boutons(fenetre) if c.window_text().strip())


def attendre_boite_ouvrir(timeout=15):
    fin = time.time() + timeout
    while time.time() < fin:
        boites = Desktop(backend="win32").windows(class_name="#32770")
        if boites:
            return Desktop(backend="win32").window(handle=boites[0].handle)
        time.sleep(0.5)
    raise RuntimeError("Boîte « Ouvrir » introuvable.")


def champ_nom_fichier(boite):
    champ = boite.child_window(control_id=1148, class_name="Edit")
    if champ.exists(timeout=2):
        return champ
    combo = boite.child_window(control_id=1148, class_name="ComboBoxEx32")
    if combo.exists(timeout=2):
        return combo.child_window(class_name="Edit", found_index=0)
    return boite.child_window(class_name="Edit", found_index=0)
def trouver_menu(texte, timeout=5):
    """Cherche l'élément de menu « Ajouter des fichiers » (en excluant le bouton « ... et plus encore »)."""
    cible = normaliser(texte)
    fin = time.time() + timeout
    while time.time() < fin:
        candidats = []
        for fen in Desktop(backend="uia").windows():
            try:
                for c in fen.descendants():
                    nom = c.window_text()
                    if not nom:
                        continue
                    low = normaliser(nom)
                    if cible in low and "plus encore" not in low:
                        candidats.append(c)
            except Exception:
                continue
        for c in candidats:
            if c.element_info.control_type == "MenuItem":
                return c
        if candidats:
            return candidats[0]
        time.sleep(0.5)
    raise RuntimeError(f"Menu introuvable : {texte}")


def attendre_boite_ouvrir(timeout=15):
    """Attend la boîte « Ouvrir » réellement visible à l'écran."""
    fin = time.time() + timeout
    while time.time() < fin:
        for b in Desktop(backend="win32").windows(class_name="#32770", visible_only=True):
            if "ouvrir" in normaliser(b.window_text()):
                return Desktop(backend="win32").window(handle=b.handle)
        time.sleep(0.5)
    visibles = [b.window_text() for b in Desktop(backend="win32").windows(class_name="#32770", visible_only=True)]
    raise RuntimeError(f"Boîte « Ouvrir » visible introuvable. Boîtes visibles : {visibles}")

def saisir_chemin_ouvrir(chemin, timeout=15):
    """Tape le chemin dans la boîte « Ouvrir ». Retourne True si la boîte s'est fermée."""
    boite = attendre_boite_ouvrir(timeout)
    try:
        boite.set_focus()
    except Exception:
        pass
    time.sleep(1)
    send_keys(echapper(chemin), with_spaces=True, pause=0.03)
    time.sleep(0.5)
    send_keys("{ENTER}")

    fin = time.time() + 15
    while time.time() < fin:
        if not boite.exists():
            return True
        time.sleep(0.5)
    return False


def pdf_visible_dans_chatgpt(fenetre, chemin, timeout=20):
    """Vérifie que le nom du PDF apparaît dans la conversation ChatGPT."""
    cible = normaliser(Path(chemin).stem)
    fin = time.time() + timeout
    while time.time() < fin:
        for c in fenetre.descendants():
            try:
                nom = c.window_text()
            except Exception:
                continue
            if nom and cible in normaliser(nom):
                return True
        time.sleep(1)
    return False


def joindre_pdf(fenetre, chemin):
    if not os.path.exists(chemin):
        raise FileNotFoundError(f"PDF introuvable : {chemin}")
    fenetre.set_focus()
    trouver_bouton(fenetre, "Ajouter des fichiers").click_input()
    time.sleep(1.5)

    trouver_menu("Ajouter des fichiers").click_input()
    time.sleep(1.5)

    if not saisir_chemin_ouvrir(chemin):
        raise RuntimeError(f"La boîte « Ouvrir » ne s'est pas fermée pour : {chemin}")

    fenetre = fenetre_chatgpt()
    if pdf_visible_dans_chatgpt(fenetre, chemin):
        print("  -> joint :", Path(chemin).name)
    else:
        raise RuntimeError(f"Le fichier n'apparaît pas dans ChatGPT : {Path(chemin).name}")

def nouveau_chat(fenetre):
    try:
        trouver_bouton(fenetre, "Nouveau chat", timeout=3).click_input()
        time.sleep(2)
    except RuntimeError:
        print("Bouton « Nouveau chat » non trouvé : on reste dans la conversation actuelle.")


def envoyer_prompt(fenetre):
    champs = fenetre.descendants(control_type="Edit")
    if not champs:
        raise RuntimeError("Zone de saisie du message introuvable.")
    zone = max(champs, key=lambda e: e.rectangle().top)  # la zone de saisie est en bas

    zone.click_input()
    time.sleep(0.5)
    for i, ligne in enumerate(PROMPT_LIGNES):
        if ligne:
            zone.type_keys(echapper(ligne), with_spaces=True, pause=0.01)
        if i < len(PROMPT_LIGNES) - 1:
            send_keys("+{ENTER}")  # saut de ligne sans envoyer
    time.sleep(0.5)
    send_keys("{ENTER}")  # envoi du message


def attendre_pdf_produit(fenetre, timeout, avant):
    """Attend un NOUVEAU bouton de téléchargement, apparu après l'envoi du prompt."""
    fin = time.time() + timeout
    while time.time() < fin:
        actuels = boutons(fenetre)
        compte_actuel = Counter(c.window_text().strip() for c in actuels if c.window_text().strip())
        for c in sorted(actuels, key=lambda b: b.rectangle().top, reverse=True):
            nom = c.window_text().strip()
            low = normaliser(nom)
            if not nom or "marquer" in low or "non lu" in low:
                continue
            if not any(m in low for m in ("telecharg", "download")):
                continue
            if compte_actuel[nom] > avant.get(nom, 0):
                return c
        time.sleep(3)
    return None


def nom_unique(dossier, nom):
    cible = dossier / nom
    compteur = 2
    while cible.exists():
        cible = dossier / f"{Path(nom).stem}_{compteur}{Path(nom).suffix}"
        compteur += 1
    return cible


def enregistrer_pdf_produit(fenetre, avant):
    os.makedirs(DOSSIER_SORTIE, exist_ok=True)
    dossier_dl = dossier_telechargements()
    print("Dossier surveillé :", dossier_dl)

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
    time.sleep(2)

    nouveau = None
    fin = time.time() + 120
    while time.time() < fin and nouveau is None:
        time.sleep(1)
        for f in dossier_dl.glob("*.pdf"):
            partiel = Path(str(f) + ".crdownload")
            if f.stat().st_mtime >= debut and not partiel.exists():
                nouveau = f
                break

    if nouveau is None:
        print("Aucun nouveau PDF détecté dans", dossier_dl)
        return

    destination = nom_unique(Path(DOSSIER_SORTIE), f"Comparaison_{datetime.now():%Y%m%d_%H%M}.pdf")
    shutil.move(str(nouveau), str(destination))
    print("PDF déplacé vers :", destination)


if __name__ == "__main__":
    fenetre = fenetre_chatgpt()
    nouveau_chat(fenetre)
    for chemin in PDF_FICHIERS:
        print("Ajout :", chemin)
        joindre_pdf(fenetre, chemin)
    fenetre = fenetre_chatgpt()
    fenetre.set_focus()
    print("Les deux PDF sont joints. Écriture du prompt...")
    avant = noms_boutons(fenetre)
    envoyer_prompt(fenetre)
    print(f"Message envoyé. Attente de la réponse (jusqu'à {DELAI_REPONSE} s)...")
    enregistrer_pdf_produit(fenetre, avant)