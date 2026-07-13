"""Point d'entrée Streamlit de Wesley Investment Analytics (WIA).

Ce module est volontairement minimal à ce stade : il initialise uniquement
l'application et documente l'emplacement futur de l'interface utilisateur.
"""

import streamlit as st


st.set_page_config(
    page_title="WIA - Wesley Investment Analytics",
    page_icon="📊",
    layout="wide",
)

st.title("WIA - Wesley Investment Analytics")
st.caption("Analyse patrimoniale spécialisée dans les cryptomonnaies.")
st.info("Structure du projet initialisée. Les fonctionnalités métier seront ajoutées ultérieurement.")
