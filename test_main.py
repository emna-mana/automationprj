from configuration import charger_chemins
p = charger_chemins()["fichier_trusquinage_A164"]
print(repr(p))
print("longueur :", len(p))
import os
print("existe :", os.path.exists(p))
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
# from pywinauto import Desktop

# DESKTOP = Desktop(backend="uia")
# SORTIE = r"C:\automationprj\import_controles.txt"
# lignes = []

# principale = DESKTOP.window(title="Steel Projects", top_level_only=True)

# imports = principale.children(title="Import", control_type="Window")
# lignes.append(f"Nombre de fenêtres « Import » sous Steel Projects : {len(imports)}")
# lignes.append("")

# for n, fenetre in enumerate(imports, start=1):
#     lignes.append(f"=== Fenêtre « Import » n°{n} ===")
#     try:
#         r = fenetre.rectangle()
#         lignes.append(f"Position : x={r.left}-{r.right} y={r.top}-{r.bottom}")
#         lignes.append(f"Visible : {fenetre.is_visible()}")
#     except Exception as exc:
#         lignes.append(f"<erreur fenêtre {exc!r}>")
#     for e in fenetre.descendants():
#         info = e.element_info
#         try:
#             texte = e.window_text()
#         except Exception as exc:
#             texte = f"<erreur {exc!r}>"
#         try:
#             valeur = e.get_value() if info.control_type == "Edit" else ""
#         except Exception:
#             valeur = ""
#         try:
#             r = e.rectangle()
#             pos = f"x={r.left}-{r.right} y={r.top}-{r.bottom}"
#         except Exception:
#             pos = "x=? y=?"
#         lignes.append(
#             f"{info.control_type:<12} auto_id={info.automation_id!r:<14} "
#             f"texte={texte!r:<40} valeur={valeur!r:<12} {pos}"
#         )
#     lignes.append("")

# with open(SORTIE, "w", encoding="utf-8") as f:
#     f.write("\n".join(lignes))
# print("\n".join(lignes[:20]))
# print("\nFichier écrit :", SORTIE)
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
