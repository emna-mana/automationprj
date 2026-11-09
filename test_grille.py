from pywinauto import Desktop
 
import corection_scribing as cs
 
DESKTOP = Desktop(backend="uia")
 
 
def main():
    fenetre = None
    for w in DESKTOP.windows():
        if "\\" in w.window_text() and "02IV" in w.window_text():
            fenetre = DESKTOP.window(handle=w.handle)
            break
    if fenetre is None:
        print("Aucune fenêtre 02IV \\ ... trouvée.")
        return
    grille = cs.grille_parametres(fenetre)
    gr = grille.rectangle()
    print(f"Grille : haut={gr.top} bas={gr.bottom} gauche={gr.left} droite={gr.right}")
    for el in grille.descendants():
        try:
            r = el.rectangle()
            print(f"{el.element_info.control_type:<12} "
                  f"y_centre={r.mid_point().y - gr.top:>4} x_centre={r.mid_point().x - gr.left:>4} "
                  f"h={r.height():>3} texte={el.window_text()!r}")
        except Exception as e:
            print("erreur :", e)
 
 
if __name__ == "__main__":
    main()
 