"""Single source of truth for the application version.

Versioning convention (adopted at v4.0.0):
  * MAJOR — a storage / architecture break (e.g. JSON → SQLite in 4.0.0).
  * MINOR — each completed build step / feature (property edit-delete, service
            layer, scraper, …). See poc_nicegui/TODO.md for the planned steps.
  * PATCH — bug fixes.

Keep README.md's title and changelog.md's latest entry in sync with this value.
"""

__version__ = "4.11.3"
