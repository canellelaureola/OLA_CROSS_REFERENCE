from flask import Flask, render_template, request
import sqlite3
import difflib
import re
import unicodedata
import os


app = Flask(__name__)

DATABASE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "cross_reference_ola.db"
)


# ============================================================
# BASE DE DONNÉES
# ============================================================





# ============================================================
# NORMALISATION
# ============================================================

def normaliser_texte(texte):
    """
    Transforme le texte pour faciliter la recherche.

    Exemple :
    "POWER  OIL" -> "power oil"
    "PÖWER"      -> "power"
    "POWER-OIL"  -> "power oil"
    """

    if not texte:
        return ""

    texte = str(texte).lower().strip()

    # Suppression des accents
    texte = unicodedata.normalize("NFD", texte)

    texte = "".join(
        caractere
        for caractere in texte
        if unicodedata.category(caractere) != "Mn"
    )

    # Les caractères spéciaux deviennent des espaces
    texte = re.sub(r"[^a-z0-9]+", " ", texte)

    # Suppression des espaces multiples
    texte = re.sub(r"\s+", " ", texte)

    return texte.strip()


# ============================================================
# SCORE DE RESSEMBLANCE ENTRE DEUX MOTS
# ============================================================

def score_mot(mot_recherche, mot_produit):
    """
    Compare deux mots.

    Exemple :
        power / power = 1.0
        powr  / power = score élevé
        power / spiro = score faible
    """

    if mot_recherche == mot_produit:
        return 1.0

    return difflib.SequenceMatcher(
        None,
        mot_recherche,
        mot_produit
    ).ratio()


# ============================================================
# SCORE DU PRODUIT
# ============================================================

def calculer_score(recherche, nom_produit):

    recherche = normaliser_texte(recherche)
    nom_produit = normaliser_texte(nom_produit)

    if not recherche or not nom_produit:
        return 0

    # --------------------------------------------------------
    # 1. Correspondance exacte
    # --------------------------------------------------------

    if recherche == nom_produit:
        return 1.0

    mots_recherche = recherche.split()
    mots_produit = nom_produit.split()

    # --------------------------------------------------------
    # 2. Recherche par mots
    # --------------------------------------------------------

    scores_mots = []

    for mot_recherche in mots_recherche:

        meilleur_score = 0

        for mot_produit in mots_produit:

            score = score_mot(
                mot_recherche,
                mot_produit
            )

            if score > meilleur_score:
                meilleur_score = score

        scores_mots.append(
            meilleur_score
        )

    if not scores_mots:
        return 0

    # Score moyen des mots recherchés
    score_moyen = sum(scores_mots) / len(scores_mots)

    # --------------------------------------------------------
    # 3. Vérification de présence réelle des mots
    # --------------------------------------------------------

    mots_exactement_presents = 0

    for mot_recherche in mots_recherche:

        if mot_recherche in mots_produit:
            mots_exactement_presents += 1

    proportion_exacte = (
        mots_exactement_presents / len(mots_recherche)
    )

    # --------------------------------------------------------
    # 4. Recherche contenue dans le nom
    # --------------------------------------------------------

    score_contenu = 0

    if recherche in nom_produit:
        score_contenu = 0.97

    # --------------------------------------------------------
    # 5. Score final
    # --------------------------------------------------------

    score = max(
        score_moyen,
        proportion_exacte,
        score_contenu
    )

    return score


# ============================================================
# RECHERCHE INTELLIGENTE
# ============================================================

def rechercher_produit(nom_recherche):

    connexion = sqlite3.connect(DATABASE)

    produits = connexion.execute(
        """
        SELECT
            c.id,
            c.nom,
            c.id_marque,
            m.nom,
            c.type_huile,
            c.grade_sae,
            o.nom,
            o.type_huile,
            o.grade_sae

        FROM produits c

        LEFT JOIN marques m
            ON c.id_marque = m.id

        LEFT JOIN equivalences e
            ON e.id_produit_concurrent = c.id

        LEFT JOIN produits o
            ON e.id_produit_ola = o.id
        """
    ).fetchall()

    connexion.close()

    resultats = []

    recherche_normalisee = normaliser_texte(
        nom_recherche
    )

    mots_recherche = recherche_normalisee.split()

    for produit in produits:

        nom_produit = produit[1]

        nom_normalise = normaliser_texte(
            nom_produit
        )

        mots_produit = nom_normalise.split()

        score = calculer_score(
            recherche_normalisee,
            nom_normalise
        )

        # ----------------------------------------------------
        # RÈGLES DE RECHERCHE
        # ----------------------------------------------------

        accepter = False

        # Cas 1 : correspondance exacte
        if recherche_normalisee == nom_normalise:

            accepter = True

        # Cas 2 : la recherche complète est contenue
        # dans le nom du produit
        elif recherche_normalisee in nom_normalise:

            accepter = True

        # Cas 3 : recherche par mots
        else:

            tous_les_mots_trouves = True

            for mot_recherche in mots_recherche:

                meilleur_score = 0

                for mot_produit in mots_produit:

                    score_mot_actuel = score_mot(
                        mot_recherche,
                        mot_produit
                    )

                    if score_mot_actuel > meilleur_score:
                        meilleur_score = score_mot_actuel

                # Une petite faute de frappe est acceptée.
                #
                # Exemple :
                # powr -> power
                #
                # Mais :
                # power -> spiro
                # ne passera pas ce seuil.

                if meilleur_score < 0.80:

                    tous_les_mots_trouves = False
                    break

            if tous_les_mots_trouves:

                accepter = True

        # ----------------------------------------------------
        # AJOUT DU RÉSULTAT
        # ----------------------------------------------------

        if accepter:

            resultats.append(
                (
                    score,
                    produit
                )
            )

    # --------------------------------------------------------
    # MEILLEURS RÉSULTATS EN PREMIER
    # --------------------------------------------------------

    resultats.sort(
        key=lambda x: x[0],
        reverse=True
    )

    # Maximum 20 résultats
    resultats = resultats[:20]

    return [
        produit
        for score, produit in resultats
    ]


# ============================================================
# ACCUEIL
# ============================================================

@app.route("/")
def accueil():

    return render_template(
        "index.html"
    )


# ============================================================
# RECHERCHE
# ============================================================

@app.route("/rechercher", methods=["POST"])
def rechercher():

    produit_recherche = request.form.get(
        "produit",
        ""
    ).strip()

    if not produit_recherche:

        return render_template(
            "index.html",
            produit=[],
            recherche=""
        )

    produits = rechercher_produit(
        produit_recherche
    )

    return render_template(
        "index.html",
        produit=produits,
        recherche=produit_recherche
    )


# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":

    app.run(
    host="0.0.0.0",
    port=5000,
    debug=True
)