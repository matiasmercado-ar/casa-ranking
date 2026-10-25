"""UI strings. Spanish is the default; English is optional (cookie `lang`)."""

DEFAULT_LANG = "es"
LANGS = ("es", "en")

STRINGS: dict[str, dict[str, str]] = {
    "app_name": {"es": "Casa Ranking", "en": "Casa Ranking"},
    "tagline": {"es": "Elegí tu próxima casa con datos, no con corazonadas.", "en": "Pick your next home with data, not hunches."},
    "nav_ranking": {"es": "Ranking", "en": "Ranking"},
    "nav_compare": {"es": "Comparar", "en": "Compare"},
    "nav_settings": {"es": "Ajustes", "en": "Settings"},
    "nav_add": {"es": "Agregar casa", "en": "Add house"},
    "logout": {"es": "Salir", "en": "Log out"},
    # topics
    "ubicacion": {"es": "Ubicación", "en": "Location"},
    "construccion": {"es": "Construcción", "en": "Construction"},
    "antiguedad": {"es": "Antigüedad", "en": "Age"},
    "antiguedad_hint": {"es": "10 = a estrenar / muy nueva", "en": "10 = brand new"},
    # features
    "mejorable": {"es": "¿Mejorable?", "en": "Room to improve?"},
    "supermercado": {"es": "Supermercado cerca", "en": "Supermarket nearby"},
    "colegio": {"es": "Colegio cerca", "en": "School nearby"},
    "transporte": {"es": "Transporte público cerca", "en": "Public transport nearby"},
    "gimnasio": {"es": "Gimnasio cerca", "en": "Gym nearby"},
    "ciclovia": {"es": "Ciclovía", "en": "Bike lane"},
    "plaza": {"es": "Plaza", "en": "Park / square"},
    "hospital": {"es": "Hospital / clínica cerca", "en": "Hospital / clinic nearby"},
    "short_mejorable": {"es": "Mejorable", "en": "Improvable"},
    "short_supermercado": {"es": "Súper", "en": "Market"},
    "short_colegio": {"es": "Colegio", "en": "School"},
    "short_transporte": {"es": "Transporte", "en": "Transit"},
    "short_gimnasio": {"es": "Gimnasio", "en": "Gym"},
    "short_ciclovia": {"es": "Ciclovía", "en": "Bike lane"},
    "short_plaza": {"es": "Plaza", "en": "Park"},
    "short_hospital": {"es": "Salud", "en": "Health"},
    "yes": {"es": "Sí", "en": "Yes"},
    "no": {"es": "No", "en": "No"},
    "unknown": {"es": "?", "en": "?"},
    # statuses
    "status": {"es": "Estado", "en": "Status"},
    "activa": {"es": "Activa", "en": "Active"},
    "visitada": {"es": "Visitada", "en": "Visited"},
    "favorita": {"es": "Favorita", "en": "Favourite"},
    "descartada": {"es": "Descartada", "en": "Discarded"},
    # house fields
    "link": {"es": "Link de la publicación", "en": "Listing link"},
    "title": {"es": "Título", "en": "Title"},
    "title_hint": {"es": "Si lo dejás vacío intentamos leerlo del link.", "en": "Leave empty and we'll try to read it from the link."},
    "address": {"es": "Dirección / barrio", "en": "Address / neighbourhood"},
    "price": {"es": "Precio", "en": "Price"},
    "currency": {"es": "Moneda", "en": "Currency"},
    "image_url": {"es": "URL de foto", "en": "Photo URL"},
    "notes": {"es": "Notas", "en": "Notes"},
    "save": {"es": "Guardar", "en": "Save"},
    "saved": {"es": "Guardado", "en": "Saved"},
    "cancel": {"es": "Cancelar", "en": "Cancel"},
    "delete": {"es": "Eliminar", "en": "Delete"},
    "delete_confirm": {"es": "¿Eliminar esta casa y todos sus puntajes?", "en": "Delete this house and all its ratings?"},
    "edit": {"es": "Editar", "en": "Edit"},
    "open_listing": {"es": "Ver publicación", "en": "Open listing"},
    "refresh_preview": {"es": "Releer título y foto del link", "en": "Re-read title and photo from link"},
    "untitled": {"es": "Casa sin título", "en": "Untitled house"},
    # ranking
    "score": {"es": "Puntaje", "en": "Score"},
    "amenities": {"es": "Cerca", "en": "Nearby"},
    "not_rated": {"es": "Sin puntuar", "en": "Not rated"},
    "rated_by": {"es": "Puntuada por {n} de {total}", "en": "Rated by {n} of {total}"},
    "show_discarded": {"es": "Mostrar descartadas", "en": "Show discarded"},
    "hide_discarded": {"es": "Ocultar descartadas", "en": "Hide discarded"},
    "empty_title": {"es": "Todavía no hay casas", "en": "No houses yet"},
    "empty_body": {"es": "Pegá el link de una publicación y empezá a puntuar.", "en": "Paste a listing link and start rating."},
    "houses_count": {"es": "{n} casas", "en": "{n} houses"},
    # detail
    "ratings": {"es": "Puntajes", "en": "Ratings"},
    "ratings_hint": {"es": "Cada persona puntúa por su cuenta de 0 a 10. El ranking usa el promedio.", "en": "Each person rates on their own from 0 to 10. The ranking uses the average."},
    "features": {"es": "Características", "en": "Features"},
    "average": {"es": "Promedio", "en": "Average"},
    "clear": {"es": "Borrar", "en": "Clear"},
    "details": {"es": "Datos", "en": "Details"},
    "added_on": {"es": "Agregada el", "en": "Added on"},
    # settings
    "raters": {"es": "Personas que puntúan", "en": "People who rate"},
    "raters_hint": {"es": "Cambiá los nombres, agregá o quitá personas. Quitar a alguien borra sus puntajes.", "en": "Rename, add or remove people. Removing someone deletes their ratings."},
    "add_rater": {"es": "Agregar persona", "en": "Add person"},
    "new_rater_placeholder": {"es": "Nombre", "en": "Name"},
    "weights": {"es": "Peso de cada tema", "en": "Weight of each topic"},
    "weights_hint": {"es": "El puntaje final es un promedio ponderado. 1 = normal, 2 = el doble de importante, 0 = no cuenta.", "en": "The final score is a weighted average. 1 = normal, 2 = twice as important, 0 = ignored."},
    "language": {"es": "Idioma", "en": "Language"},
    "backup": {"es": "Exportar datos", "en": "Export data"},
    "backup_hint": {"es": "Descargá todo para hacer un backup o abrirlo en una planilla.", "en": "Download everything as a backup or to open in a spreadsheet."},
    # login
    "password": {"es": "Contraseña", "en": "Password"},
    "login": {"es": "Entrar", "en": "Log in"},
    "bad_password": {"es": "Contraseña incorrecta", "en": "Wrong password"},
}


def translate(key: str, lang: str, **kw) -> str:
    entry = STRINGS.get(key)
    text = entry.get(lang) or entry[DEFAULT_LANG] if entry else key
    return text.format(**kw) if kw else text
