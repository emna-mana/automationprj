# from pywinauto import Desktop
# import time
# import io
# from contextlib import redirect_stdout
# # 1. Minuterie (Compte à rebours)
# DELAI = 5  # secondes pour vous laisser le temps d'ouvrir le menu à la souris

# print(f"--- MINUTERIE DE {DELAI} SECONDES ---")

# for i in range(DELAI, 0, -1):
#     print(f"Analyse dans {i} seconde(s)...", end="\r")
#     time.sleep(1)

# print("\n--- INSPETION DES COMPOSANTS EN COURS ---")
# # Connect to the Windows UI
# desktop = Desktop(backend="uia")

# window = desktop.window(title_re=".*Steel Projects.*")


# buffer = io.StringIO()
# with redirect_stdout(buffer):
#     window.print_control_identifiers()

# identifiers = buffer.getvalue()   # nothing was printed to the terminal
# f=open("tmp.txt","w")
# for line in identifiers.splitlines():
#     f.write(line+"\n")

# f.close()

#----------------------------------------------------------------------------------------
# import sys
# from pywinauto import Desktop

# # Affichage correct des accents dans la console
# sys.stdout.reconfigure(encoding="utf-8")

# # Connexion à la fenêtre déjà ouverte
# desktop = Desktop(backend="uia")
# window = desktop.window(title_re=".*Steel Projects - Gestion de production.*")
# window.wait("exists visible", timeout=30)

# # Grille des phases
# grille = window.child_window(auto_id="dgvData", control_type="Table")
# grille.wait("exists visible", timeout=30)

# # Structure de la grille (titres, types, hiérarchie)
# grille.print_control_identifiers(depth=2)

# # Puis les valeurs des cellules
# for ligne in grille.children(control_type="Custom"):
#     for c in ligne.children(control_type="Edit"):
#         print(c.window_text(), "=", c.get_value())
# ----------------------------------------------------------------------------------------
# script d'inspection, avec la fenêtre « Repère Secondaire »
# ----------------------------------------------------------------------------------------
# import sys
# from pywinauto import Desktop

# sys.stdout.reconfigure(encoding="utf-8")

# desktop = Desktop(backend="uia")
# window = desktop.window(title_re=".*Steel Projects.*")

# # Fenêtre "Repère Secondaire"
# repere = window.child_window(auto_id="SpForm", control_type="Window")
# repere.wait("exists visible", timeout=30)

# # Arbre complet de la fenêtre, enregistré dans un fichier
# repere.print_control_identifiers(filename="inspection_repere_secondaire.txt")
# print("Inspection enregistrée dans inspection_repere_secondaire.txt")

# # ----------------------------------------------------------------------------------------
# # script d'inspection, avec la fenêtre « Repère Secondaire » qui contient cmnt2
# # ----------------------------------------------------------------------------------------
# import sys
# from pywinauto import Desktop

# sys.stdout.reconfigure(encoding="utf-8")

# desktop = Desktop(backend="uia")
# window = desktop.window(title_re=".*Steel Projects.*")

# # Fenêtre "Repère Secondaire"
# repere = window.child_window(auto_id="SpForm", control_type="Window")
# repere.wait("exists visible", timeout=30)

# # 1. Zone des onglets (sans le détail des cellules de la grille) -> fichier
# zone = repere.child_window(auto_id="pnlPrincipal", control_type="Pane", found_index=0)
# zone.print_control_identifiers(depth=4, filename="inspection_commentaires.txt")
# print("Inspection enregistrée dans inspection_commentaires.txt")

# # 2. Liste rapide des champs de saisie, hors cellules de la grille
# print("\n--- CHAMPS DE SAISIE ---")
# for el in repere.descendants(control_type="Edit"):
#     if "Ligne" in el.window_text():
#         continue   # cellule de la grille : on l'ignore
#     print(f"titre={el.window_text()!r:20} auto_id={el.element_info.automation_id!r:25} "
#           f"visible={el.is_visible()} position={el.rectangle()}")

#------------------------------------------------------------------------------------------------------

# from pywinauto import Desktop
# import time
# import io
# from contextlib import redirect_stdout

# # 1. Minuterie (compte à rebours)
# DELAI = 5  # secondes pour vous laisser le temps d'afficher la fenêtre Aperçu

# print(f"--- MINUTERIE DE {DELAI} SECONDES ---")
# for i in range(DELAI, 0, -1):
#     print(f"Analyse dans {i} seconde(s)...", end="\r")
#     time.sleep(1)

# print("\n--- INSPECTION DES COMPOSANTS EN COURS ---")
# desktop = Desktop(backend="uia")

# # Fenêtre « Aperçu 1/132 » : le point remplace le « ç » pour éviter les problèmes d'accent
# window = desktop.window(title_re=r"Aper.u.*")

# buffer = io.StringIO()
# with redirect_stdout(buffer):
#     window.print_control_identifiers()

# # encoding="utf-8" : sinon les accents provoquent une erreur à l'écriture
# with open("apercu.txt", "w", encoding="utf-8") as f:
#     f.write(buffer.getvalue())

# print("Arborescence enregistrée dans apercu.txt")

#------------------------------------------------------------------------------
# from pywinauto import Desktop
# import io
# from contextlib import redirect_stdout

# # Cherche la boîte d'enregistrement sur le Bureau, puis dans la fenêtre Aperçu
# desktop = Desktop(backend="uia")
# TITRE = "Enregistrer le fichier PDF sous"

# boite = desktop.window(title=TITRE)
# if boite.exists(timeout=2):
#     print("Boîte trouvée : fenêtre de premier niveau (Bureau)")
# else:
#     apercu = desktop.window(title_re=r"Aper.u \d+/\d+")
#     boite = apercu.child_window(title=TITRE, control_type="Window")
#     if boite.exists(timeout=2):
#         print("Boîte trouvée : à l'intérieur de la fenêtre Aperçu")
#     else:
#         print("Boîte introuvable")
#         boite = None

# if boite is not None:
#     buffer = io.StringIO()
#     with redirect_stdout(buffer):
#         boite.print_control_identifiers()
#     with open("boite_pdf.txt", "w", encoding="utf-8") as f:
#         f.write(buffer.getvalue())
#     print("Arborescence enregistrée dans boite_pdf.txt")
#------------------------------------------------------------------------------
from pywinauto import Desktop
import time
import io
from contextlib import redirect_stdout

desktop = Desktop(backend="uia")
steel = desktop.window(title_re=".*Steel Projects.*")
cam3d = steel.child_window(auto_id="FormImport", control_type="Window")

# Clic sur la flèche du répertoire (le dialogue Import [CAM3D] doit être ouvert)
fleche = cam3d.child_window(auto_id="ptbLocalFolder", control_type="Pane").child_window(control_type="Button")
fleche.click_input()
time.sleep(2)

buffer = io.StringIO()
with redirect_stdout(buffer):
    print("== Liste des dossiers (SysListView32) ==")
    for w in desktop.windows(class_name="SysListView32"):
        desktop.window(handle=w.handle).print_control_identifiers()

    print("\n== Fenêtre sans titre (WinForms) ==")
    for w in desktop.windows(class_name="WindowsForms10.Window.8.app.0.34f5582_r8_ad1"):
        desktop.window(handle=w.handle).print_control_identifiers()

with open("tmp_popup.txt", "w", encoding="utf-8") as f:
    f.write(buffer.getvalue())
print("Écrit dans tmp_popup.txt")