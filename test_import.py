import operator
import time
from _ctypes import COMError
from pywinauto import Desktop
from pywinauto.application import Application
from pywinauto.timings import wait_until, TimeoutError as PwaTimeoutError
from pywinauto.keyboard import send_keys

USERNAME = "EBA"
PASSWORD = "EBA2026"
EXE_PATH = r"C:\Program Files (x86)\SteelProjects\Sp.Plm\Sp.Plm.exe"
IMPORT_DIRECTORY = r"C:\Users\E.BENAMOR\Desktop\01XY"
DESKTOP = Desktop(backend="uia")


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


def lancer_application(timeout=90):
    # Lance Steel Projects et renvoie la fenêtre qui affiche l'écran de connexion
    Application(backend="uia").start(f'"{EXE_PATH}"')

    def fenetre_connexion():
        # Parmi toutes les fenêtres « Steel Projects », garde celle qui contient « Identification »
        for w in DESKTOP.windows(title_re=".*Steel Projects.*"):
            spec = DESKTOP.window(handle=w.handle)
            if spec.child_window(auto_id="SelectUser", control_type="Window").exists(timeout=0):
                return spec
        return None

    return wait_until(timeout, 1, fenetre_connexion, None, operator.is_not)


def s_authentifier(window):
    # Saisit l'identifiant et le mot de passe dans la fenêtre « Identification », puis valide
    ident = window.child_window(auto_id="SelectUser", control_type="Window")
    attendre(ident, "exists visible", timeout=90)

    attendre(ident.child_window(auto_id="tbLogin", control_type="Edit")).set_edit_text(USERNAME)
    attendre(ident.child_window(auto_id="tbPassword", control_type="Edit")).set_edit_text(PASSWORD)

    # Bouton Ok de la barre du bas, cliqué sans souris (insensible au splash screen et à Verr. Maj)
    barre = ident.child_window(auto_id="StatusBar", control_type="Pane")
    attendre(barre.child_window(title="Ok", control_type="Button")).invoke()

    # Attend la fermeture de la fenêtre Identification (connexion réussie)
    ident.wait_not("exists visible", timeout=60, retry_interval=0.5)

    # Attend la fin du chargement : l'écran de démarrage se ferme, puis l'appli se calme
    splash = window.child_window(auto_id="FormSplashScreen", control_type="Window")
    splash.wait_not("exists", timeout=180, retry_interval=0.5)
    attendre_appli(window, timeout=120)




def trouver_fenetre_cam3d(window, timeout=60):
    # La fenêtre « Import [CAM3D] » est un dialogue enfant de Steel Projects
    spec = window.child_window(title_re=r".*CAM3D.*")

    def presente():
        try:
            return spec.exists(timeout=0)
        except COMError:
            return False  # appli occupée : on réessaie

    wait_until(timeout, 0.5, presente)
    return spec




def importer_CAM3D(window):
    # Importe les fichiers XML Tekla et valide les fenêtres d'import
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
    send_keys(IMPORT_DIRECTORY + "{ENTER}", with_spaces=True, pause=0.05)
    time.sleep(2)

    # TEST : affiche les fichiers listés avant de valider
    liste = cam3d.child_window(auto_id="listView", control_type="List").wrapper_object()
    print("Fichiers affichés :", [i.window_text() for i in liste.children()])

    # Clic sur Ok du dialogue CAM3D
    cliquer(cam3d.child_window(title="Ok", control_type="Button"))
    finir_import(window)

    return

def finir_import(window, timeout=3600):
    # Attend la fin de l'import (la comparaison de profils est validée si elle apparaît),
    # puis clique sur Ok final
    dialog = window.child_window(auto_id="FormConfigLog", control_type="Window")
    barre_ok = dialog.child_window(auto_id="bar1", control_type="ToolBar")
    ok_final = barre_ok.child_window(title="Ok", control_type="Button")

    cliquer_avec_comparaison(window, ok_final, timeout=timeout)
    dialog.wait_not("exists", timeout=60, retry_interval=0.2)


def main_complet():
    # Enchaîne toutes les étapes du workflow
    window = lancer_application()
    s_authentifier(window)
    importer_CAM3D(window)


if __name__ == "__main__":
    main_complet()  # workflow complet : réactiver après le test