from pywinauto import Desktop
from pywinauto.application import Application
from pywinauto.timings import TimeoutError, wait_until
from pywinauto.keyboard import send_keys


import time

# CONFIGURATION

USERNAME = "EBA"
PASSWORD = "EBA2026"

EXE_PATH = r"C:\SteelProjects\Sp.Plm\Sp.Plm.exe"

IMPORT_DIRECTORY = r"C:\USERS\E.BENAMOR\DESKTOP\02-HC\*.XML"

AFFAIRE =  IMPORT_DIRECTORY.split("\\")[-2]

# Lancer Steel Projects

Application(backend="uia").start(EXE_PATH)
time.sleep(15)
desktop = Desktop(backend="uia")
window = desktop.window(title_re=".*Steel Projects.*")


# 1. Authentification

login_field = window.child_window(auto_id="tbLogin", control_type="Edit")
login_field.wait("exists visible enabled ready", timeout=30, retry_interval=0.2)

login_field.set_edit_text(USERNAME)

password_field = window.child_window(auto_id="tbPassword", control_type="Edit")
password_field.set_edit_text(PASSWORD)

# Bouton OK de l'authentification
time.sleep(1)

ok_button = window.child_window(title="Ok", control_type="Button")
ok_button.click_input()

#2. Importation

import_button = window.child_window(
    title="Import",
    control_type="Button"
)

import_button.wait("enabled", timeout=30)
import_button.click_input()

time.sleep(1)

next(x for x in import_button.wrapper_object().descendants(control_type="MenuItem") if x.window_text() == "TEKLA_XML").click_input()

# Fenetre Importation Tekla

tekla_window = desktop.window(title_re=".*Importation Tekla.*")

tekla_window.wait("exists", timeout=30)
tekla_window.wait("visible", timeout=30)

#selectionner le repertpoire du projet

directory = tekla_window.child_window(
    title="Répertoire",
    auto_id="1001",
    control_type="Edit"
)

directory.click_input()
directory.set_edit_text("")
directory.type_keys(IMPORT_DIRECTORY)

time.sleep(1)

# Valider importation TEKLA

ok_button = tekla_window.child_window(title="Ok", auto_id="1", control_type="Button")
ok_button.click_input()

# valider le selection

validate_button = window.child_window(title="Ok", control_type="Button", best_match="Button3")
validate_button.wait("exists visible enabled", timeout=600)
validate_button.click_input()

# Boutton ajouter de comparaison [affaire]
add_button = window.child_window(title="Ajouter", control_type="Button")
add_button.wait("enabled", timeout=3600)

add_button.click_input()


ok_button = window.child_window(title="Ok", control_type="Button", best_match="Button3")
ok_button.click_input()

import_dialog = window.child_window(
    title="Import",
    auto_id="FormConfigLog",
    control_type="Window"
)

ok_button = import_dialog.child_window(
    title="Ok",
    control_type="Button"
)

while not ok_button.exists() or not ok_button.is_enabled():
    time.sleep(0.5)

ok_button.click_input()
time.sleep(1)


#3. Gestion de production
production_button = window.child_window(title="Gestion de production", control_type="Button")
production_button.click_input()

time.sleep(10)
# Ajouter du scribing
# Mettre le filtre par affaire
window.set_focus()
send_keys("^{F3}")
time.sleep(1)

toolbar = window.child_window(auto_id="toolBar", control_type="ToolBar", found_index=0)
filtre = toolbar.child_window(control_type="Edit", found_index=0)

filtre.click_input()
filtre.type_keys(f"^a{{BACKSPACE}}{AFFAIRE}{{ENTER}}", with_spaces=True)
window.set_focus()
send_keys("^{F4}")

time.sleep(1)  # laisser l'UI se charger
window.set_focus()
send_keys("^a")

window.right_click_input()

time.sleep(0.5)            
send_keys("{DOWN 10}")     
send_keys("{ENTER}")


time.sleep(0.5)
send_keys("{DOWN 11}")
send_keys("{ENTER}")

time.sleep(1)

box = window.child_window(auto_id="cbxAddPositioningMark", control_type="Pane")
box.click_input()

time.sleep(1)

# Ok de la fenêtre de scribing
ok_button = window.child_window(title="Ok", control_type="Button")
ok_button.wait("enabled", timeout=30)
ok_button.click_input()

# Appliquer à tous
box = window.child_window(title_re="Appliquer . tous", control_type="Pane")
box.wait("exists visible enabled", timeout=600)
box.click_input()

# Bouton Non
non_button = window.child_window(title="Non", control_type="Button")
non_button.wait("exists visible enabled", timeout=30)
non_button.click_input()

# Attendre la fin du traitement
barre_progression = window.child_window(auto_id="barStatus", control_type="Pane")
annuler_progression = barre_progression.child_window(title="Annuler", control_type="Button")

annuler_progression.wait("exists visible", timeout=30)                           # la progression apparaît
annuler_progression.wait_not("exists visible", timeout=18000, retry_interval=1)  # elle disparaît (max 5 h)

# Sélectionner les phases entre 130 (incluse) et 140 (exclue)
grille = window.child_window(auto_id="dgvData", control_type="Table")
grille.wait("exists visible", timeout=30)

premiere = True
for ligne in grille.children(control_type="Custom"):
    if ligne.window_text() == "Ligne du haut":
        continue   # ligne des titres de colonnes

    # Lire la valeur de la colonne Phase
    phase = ""
    for c in ligne.children(control_type="Edit"):
        if c.window_text().startswith("Phase "):
            phase = (c.get_value() or "").strip()

    # Sélectionner la ligne si la phase est dans l'intervalle
    if phase.isdigit() and 130 <= int(phase) < 140:
        case = ligne.children(control_type="Header")[0]   # case grise à gauche de la ligne
        if premiere:
            case.click_input()                    # 1re ligne : nouvelle sélection
            premiere = False
        else:
            case.click_input(pressed="control")   # suivantes : Ctrl+clic pour ajouter
        print("Phase sélectionnée :", phase)

if premiere:
    print("Aucune phase entre 130 et 140")
time.sleep(2)
# Mettre le filtre par repere secondaire
send_keys("^{F6}")
time.sleep(2)

send_keys("^a") 
send_keys("{ENTER}")

# Fenêtre "Repère Secondaire"
repere = window.child_window(auto_id="SpForm", control_type="Window")
repere.wait("exists visible", timeout=30)

# Cliquer sur l'onglet "Commentaires" (4e onglet, index 3)
onglets = repere.child_window(auto_id="tsGeneral", control_type="Pane")
onglet_commentaires = onglets.child_window(control_type="TreeItem", found_index=3)
onglet_commentaires.wait("exists visible enabled", timeout=30)
onglet_commentaires.click_input()

#selectionner COMMENTAIRE_2
champ_com2 = repere.child_window(auto_id="tbCom2", control_type="Edit")
champ_com2.wait("exists visible enabled", timeout=30)
champ_com2.click_input()
champ_com2.type_keys("^a{BACKSPACE}PU")

# Valider
valider = repere.child_window(title="Valider", control_type="Button")
valider.wait("enabled", timeout=30)
valider.click_input()

quiter = repere.child_window(title="Quitter", control_type="Button")
quiter.wait("enabled", timeout=30)
quiter.click_input()