"""Applying a language to the running app: our text, Qt's own text, and the calendar."""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator

from ..i18n import SOURCE_LANGUAGE, current_language, set_language

_installed: list[QTranslator] = []


def apply_language(code: str) -> None:
    """Set the language for everything built from now on.

    Existing widgets keep their text. The main window rebuilds itself after a change.
    Qt's translation covers its own words: Yes, Cancel, and the right-click menu in a field.
    """
    set_language(code)
    language = current_language()
    QLocale.setDefault(QLocale(language))

    app = QCoreApplication.instance()
    if app is None:
        return
    for translator in _installed:
        app.removeTranslator(translator)
    _installed.clear()
    if language != SOURCE_LANGUAGE:
        translator = QTranslator(app)
        folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if translator.load(f"qtbase_{language}", folder):
            app.installTranslator(translator)
            _installed.append(translator)
