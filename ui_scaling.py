# -*- coding: utf-8 -*-

from qgis.PyQt.QtGui import QGuiApplication
from qgis.PyQt.QtWidgets import QWidget


def dpi_px(value):
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return int(value)
    return max(1, int(round(value * screen.logicalDotsPerInch() / 96.0)))


def display_metrics_text():
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return 'DPI: - / 表示倍率: -'
    dpi = screen.logicalDotsPerInch()
    ratio = screen.devicePixelRatio()
    return 'DPI: {0:.0f} / 表示倍率: {1:.0f}%'.format(dpi, ratio * 100)


def dpi_scale():
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return 1.0
    return max(1.0, screen.logicalDotsPerInch() / 96.0)


def scale_widget_tree_geometries(root):
    scale = dpi_scale()
    if abs(scale - 1.0) < 0.01:
        return
    for widget in root.findChildren(QWidget):
        geometry = widget.geometry()
        if geometry.isValid():
            widget.setGeometry(
                dpi_px(geometry.x()),
                dpi_px(geometry.y()),
                dpi_px(geometry.width()),
                dpi_px(geometry.height()),
            )
        minimum_size = widget.minimumSize()
        if minimum_size.width() > 0 or minimum_size.height() > 0:
            widget.setMinimumSize(dpi_px(minimum_size.width()), dpi_px(minimum_size.height()))
        maximum_size = widget.maximumSize()
        if maximum_size.width() < 16777215 or maximum_size.height() < 16777215:
            widget.setMaximumSize(
                dpi_px(maximum_size.width()) if maximum_size.width() < 16777215 else maximum_size.width(),
                dpi_px(maximum_size.height()) if maximum_size.height() < 16777215 else maximum_size.height(),
            )
    root.resize(dpi_px(root.width()), dpi_px(root.height()))
