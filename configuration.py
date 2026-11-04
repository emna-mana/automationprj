import configparser
import os
from pathlib import Path


_DOSSIER_PROJET = Path(__file__).resolve().parent
FICHIER_CONFIGURATION = _DOSSIER_PROJET / "config.ini"

_DEFAUTS = {
    "steel_projects_exe": r"C:\Program Files (x86)\SteelProjects\Sp.Plm\Sp.Plm.exe",
    "dossier_projets": str(Path.home() / "Desktop" / "projetTravailler"),
    "dossier_sources": str(Path.home() / "Desktop" / "projetsATravailler"),
    "dossier_croquis": r"Y:\{affaire}-IRISOLARIS\4.DOSSIER DE FABRICATION\STRUCTURE\CROQUIS\DEBITAGE",
    "fichier_fer_plat": str(Path.home() / "Desktop" / "projetsATravailler" / "FER PLAT.xlsx"),
    "fichier_trusquinage_A164": str(Path.home() / "Desktop" / "projetsATravailler" / "trusquinage A164.pdf"),

}


def charger_chemins():
    configuration = configparser.ConfigParser(interpolation=None)
    if FICHIER_CONFIGURATION.is_file():
        configuration.read(FICHIER_CONFIGURATION, encoding="utf-8")

    section = configuration["chemins"] if configuration.has_section("chemins") else {}
    chemins = {}
    for nom, valeur_defaut in _DEFAUTS.items():
        valeur = section.get(nom, valeur_defaut).strip() or valeur_defaut
        chemins[nom] = os.path.normpath(os.path.expandvars(os.path.expanduser(valeur)))
    return chemins
