"""Configuration centrale de Wesley Investment Analytics (WIA).

Les constantes définies ici servent de point d'entrée unique pour les chemins,
les paramètres applicatifs et les options d'environnement. Aucune logique métier
n'est implémentée dans ce fichier.
"""

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH = DATA_DIR / "wia.sqlite3"
APP_NAME = "Wesley Investment Analytics"
APP_VERSION = "0.1.0"
