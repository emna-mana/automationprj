import ctypes
import operator
import os
from datetime import datetime
import time


from _ctypes import COMError
from pywinauto import Desktop
from pywinauto.application import Application
from pywinauto.keyboard import send_keys
from pywinauto.timings import TimeoutError as DelaiDepasse
from pywinauto.timings import wait_until
from pywinauto.uia_defines import get_elem_interface


DESKTOP = Desktop(backend="uia")


# ===== OUTILS =====
def attendre(ctrl, etat="exists visible enabled", timeout=30):
    # Attend qu'un contrôle soit dans l'état voulu, puis le renvoie
    ctrl.wait(etat, timeout=timeout, retry_interval=0.2)
    return ctrl


def cliquer(ctrl, timeout=30):
    # Attend qu'un contrôle soit cliquable, puis clique dessus
    attendre(ctrl, timeout=timeout).click_input()


def cliquer_menu(bouton, texte, timeout=30):
    # Attend qu'un élément de menu apparaisse sous le bouton, puis clique dessus
    item = wait_until(
        timeout, 0.2,
        lambda: next((x for x in bouton.wrapper_object().descendants(control_type="MenuItem")
                      if x.window_text() == texte), None),
        None, operator.is_not,
    )
    item.click_input()


def attendre_appli(window, timeout=30):
    # Attend que l'application ait fini de travailler (CPU au repos)
    pid = window.wrapper_object().process_id()
    app = Application(backend="uia").connect(process=pid)
    app.wait_cpu_usage_lower(threshold=5, timeout=timeout)


def valider_comparaison(window):
    # Si la fenêtre de comparaison de profils est ouverte, clique sur Ok
    comparaison = window.child_window(auto_id="FormProfileComparison", control_type="Window")
    if not comparaison.exists(timeout=0):
        return False
    barre = comparaison.child_window(auto_id="stateBar", control_type="Pane")
    attendre(barre.child_window(title="Ok", control_type="Button")).invoke()
    comparaison.wait_not("exists", timeout=30, retry_interval=0.2)
    print("Comparaison de profils validée")
    return True


def cliquer_avec_comparaison(window, ctrl, timeout=30):
    # Attend que ctrl soit cliquable ; valide la comparaison de profils si elle apparaît.
    # Les erreurs UIA temporaires (appli occupée) sont ignorées et l'attente continue.
    def pret():
        try:
            if valider_comparaison(window):
                return False
            return ctrl.exists(timeout=0) and ctrl.is_visible() and ctrl.is_enabled()
        except COMError:
            return False

    wait_until(timeout, 0.5, pret)
    ctrl.click_input()


def trouver_fenetre(window, titre_re, timeout=60):
    # Une boîte de dialogue peut être une fenêtre séparée (barre de titre propre) ou un enfant
    # de Steel Projects : on cherche aux deux endroits, et on renvoie la première visible.
    def visible():
        for f in (window.child_window(title_re=titre_re),
                  DESKTOP.window(title_re=titre_re, top_level_only=True)):
            try:
                if f.exists(timeout=0) and f.is_visible():
                    return f
            except COMError:
                pass   # appli occupée : on réessaie
        return None

    return wait_until(timeout, 0.5, visible, None, operator.is_not)


def trouver_fenetre_cam3d(window, timeout=60):
    # La fenêtre « Import [CAM3D] »
    return trouver_fenetre(window, r".*CAM3D.*", timeout=timeout)


def valider_ventilation_plans(window, timeout=120):
    # Attend la fenêtre « Ventilation des plans » (apparaît après le Ok de CAM3D) puis clique sur Ok
    ventilation = trouver_fenetre(window, r"Ventilation des plans", timeout=timeout)
    cliquer(ventilation.child_window(title="Ok", control_type="Button"))
    ventilation.wait_not("exists visible", timeout=60, retry_interval=0.5)


def selectionner_cam3d(cam3d):
    # Clique sur la ligne du fichier .cam3d.tsm dans la liste, pour qu'il soit sélectionné
    def ligne_trouvee():
        return next((i for i in cam3d.wrapper_object().descendants(control_type="ListItem")
                     if ".cam3d.tsm" in i.window_text().lower()), None)

    ligne = wait_until(30, 0.5, ligne_trouvee, None, operator.is_not)
    ligne.click_input()
    print("Fichier sélectionné :", ligne.window_text())


def importer_CAM3D(window, dossier):
    # Importe les fichiers CAM3D Tekla du dossier donné, puis valide les fenêtres d'import
    bouton_import = window.child_window(title="Import", control_type="Button")
    cliquer(bouton_import)
    cliquer_menu(bouton_import, "CAM3D")

    cam3d = trouver_fenetre_cam3d(window, timeout=60)
    attendre(cam3d, "exists visible", timeout=60)

    # Clic dans la zone du chemin (pas sur la flèche) pour placer le curseur
    chemin = cam3d.child_window(auto_id="ptbLocalFolder", control_type="Pane")
    attendre(chemin).click_input()
    time.sleep(0.5)

    # Efface l'ancien chemin, tape le nouveau, valide avec Entrée
    send_keys("^a", pause=0.1)
    send_keys(dossier + "{ENTER}", with_spaces=True, pause=0.05)
    time.sleep(2)

    # Sélectionne le fichier avant de valider (sinon Ok ne fait rien)
    selectionner_cam3d(cam3d)

    # Clic sur Ok du dialogue CAM3D
    cliquer(cam3d.child_window(title="Ok", control_type="Button"))

    # Clic sur Ok de la fenêtre « Ventilation des plans »
    valider_ventilation_plans(window)

    finir_import(window)


def finir_import(window, timeout=3600):
    # Attend la fin de l'import (la comparaison de profils est validée si elle apparaît),
    # puis clique sur Ok final
    dialog = window.child_window(auto_id="FormConfigLog", control_type="Window")
    barre_ok = dialog.child_window(auto_id="bar1", control_type="ToolBar")
    ok_final = barre_ok.child_window(title="Ok", control_type="Button")

    cliquer_avec_comparaison(window, ok_final, timeout=timeout)
    dialog.wait_not("exists", timeout=60, retry_interval=0.2)