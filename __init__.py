def classFactory(iface):
    try:
        from .plugin import VeloronaPlugin
    except ImportError as exc:
        # A missing aei-*/skyfield package would otherwise abort plugin
        # loading with a traceback; load a stub that explains it instead.
        return _MissingDependenciesPlugin(iface, exc)

    return VeloronaPlugin(iface)


class _MissingDependenciesPlugin:
    """Loads in place of the real plugin when an import fails, so QGIS shows
    which packages to install rather than a bare load error."""

    def __init__(self, iface, error):
        from .core.dependencies import install_message, missing_requirements

        self.iface = iface
        self.message = install_message(missing_requirements(), detail=str(error))

    def initGui(self):
        from qgis.core import Qgis, QgsMessageLog

        QgsMessageLog.logMessage(self.message, "Velorona", Qgis.MessageLevel.Critical)
        self.iface.messageBar().pushMessage(
            "Velorona", self.message, level=Qgis.MessageLevel.Critical, duration=0
        )

    def unload(self):
        pass
