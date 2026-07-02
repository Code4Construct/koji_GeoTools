# -*- coding: utf-8 -*-

from qgis.core import QgsProject


def move_layers_to_group(layers, group_name):
    group_name = str(group_name or '').strip()
    if not group_name:
        return

    project = QgsProject.instance()
    root = project.layerTreeRoot()
    group = root.findGroup(group_name)
    if group is None:
        group = root.addGroup(group_name)

    for layer in layers:
        if layer is None or not project.mapLayer(layer.id()):
            continue
        node = root.findLayer(layer.id())
        if node is None:
            continue
        parent = node.parent()
        clone = node.clone()
        group.addChildNode(clone)
        parent.removeChildNode(node)


def move_layers_to_nested_group(layers, parent_group_name, child_group_name):
    parent_group_name = str(parent_group_name or '').strip()
    child_group_name = str(child_group_name or '').strip()
    if not child_group_name:
        move_layers_to_group(layers, parent_group_name)
        return
    if not parent_group_name:
        move_layers_to_group(layers, child_group_name)
        return

    project = QgsProject.instance()
    root = project.layerTreeRoot()
    parent_group = root.findGroup(parent_group_name)
    if parent_group is None:
        parent_group = root.addGroup(parent_group_name)
    child_group = parent_group.findGroup(child_group_name)
    if child_group is None:
        child_group = parent_group.addGroup(child_group_name)

    for layer in layers:
        if layer is None or not project.mapLayer(layer.id()):
            continue
        node = root.findLayer(layer.id())
        if node is None:
            continue
        parent = node.parent()
        clone = node.clone()
        child_group.addChildNode(clone)
        parent.removeChildNode(node)


def copy_layer_tree_node_properties(source_layer, target_layer):
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    source_node = root.findLayer(source_layer.id()) if source_layer is not None else None
    target_node = root.findLayer(target_layer.id()) if target_layer is not None else None
    if source_node is None or target_node is None:
        return

    try:
        for key in source_node.customProperties():
            target_node.setCustomProperty(key, source_node.customProperty(key))
    except Exception:
        pass

    # QGIS stores "Show Feature Count" on the layer-tree node, not in renderer style.
    try:
        target_node.setCustomProperty(
            'showFeatureCount',
            source_node.customProperty('showFeatureCount', False),
        )
    except Exception:
        pass
