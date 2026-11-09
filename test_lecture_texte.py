# Test de lecture de la cellule « Texte » (aucune écriture dans le dessin)
# Prérequis : Steel Projects ouvert, fenêtre Ctrl+D du jarret affichée à l'écran.
# Lancement : python test_lecture_texte.py            (cherche n'importe quelle fenêtre « xxx \ Jn »)
#             python test_lecture_texte.py 02IV       (cherche seulement l'affaire 02IV)
import sys
import time

from pywinauto import Desktop
from pywinauto.keyboard import send_keys

import corection_scribing as cs

DESKTOP = Desktop(backend="uia")


def trouver_fenetre_dessin(affaire=None):
    # Fenêtre de dessin ouverte par Ctrl+D : titre du type « 02IV \ J1 »
    trouvees = []
    for w in DESKTOP.windows():
        titre = w.window_text()
        if "\\" in titre and (affaire is None or affaire in titre):
            trouvees.append(w)
    print("Fenêtres avec « \\ » dans le titre :", [w.window_text() for w in trouvees])
    return DESKTOP.window(handle=trouvees[0].handle) if trouvees else None


def main():
    affaire = sys.argv[1] if len(sys.argv) > 1 else None
    fenetre = trouver_fenetre_dessin(affaire)
    if fenetre is None:
        print("Aucune fenêtre de dessin trouvée. Ouvre le jarret (Ctrl+D) puis relance.")
        return
    print("Fenêtre utilisée :", fenetre.window_text())

    grille = cs.grille_parametres(fenetre)
    r = grille.rectangle()
    x_rel = int(r.width() * 0.7)
    y_rel = 35 + 2 * 22   # ligne Texte

    for essai in range(1, 4):
        if essai % 2 == 1:
            grille.double_click_input(coords=(x_rel, y_rel))
        else:
            grille.click_input(coords=(x_rel, y_rel))
            time.sleep(0.3)
            send_keys("{F2}")
        time.sleep(0.5)
        cs.vider_presse_papiers()
        send_keys("^a^c")
        time.sleep(0.8)
        texte = cs.lire_presse_papiers()
        print(f"Essai {essai} : {texte!r}")
        send_keys("{ESC}")
        time.sleep(0.5)
        if texte.strip():
            break

    print("Fin du test. Aucune valeur n'a été modifiée.")


if __name__ == "__main__":
    main()