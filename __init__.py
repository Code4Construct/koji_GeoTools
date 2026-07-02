# -*- coding: utf-8 -*-


def classFactory(iface):  # pylint: disable=invalid-name
    """Load koji Geotools plugin."""
    from .koji_GeoTools import KojiGeoTools

    return KojiGeoTools(iface)
