def classFactory(iface):
    from .plugin import VeloronaPlugin

    return VeloronaPlugin(iface)
