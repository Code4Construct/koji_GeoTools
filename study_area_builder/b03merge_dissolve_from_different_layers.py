import processing
from qgis.core import QgsProject, QgsWkbTypes
from qgis.utils import iface


def _fix_geometries(layer):
    return processing.run("native:fixgeometries", {
        "INPUT": layer,
        "OUTPUT": "memory:"
    })["OUTPUT"]


def _reproject_to_crs(layer, crs):
    if layer.crs() == crs:
        return layer
    return processing.run("native:reprojectlayer", {
        "INPUT": layer,
        "TARGET_CRS": crs,
        "OUTPUT": "memory:"
    })["OUTPUT"]


def _union_layers(layers):
    if len(layers) == 1:
        return layers[0]

    unioned = processing.run("native:union", {
        "INPUT": layers[0],
        "OVERLAY": layers[1],
        "OVERLAY_FIELDS_PREFIX": "",
        "OUTPUT": "memory:"
    })["OUTPUT"]

    for overlay in layers[2:]:
        unioned = processing.run("native:union", {
            "INPUT": unioned,
            "OVERLAY": overlay,
            "OVERLAY_FIELDS_PREFIX": "",
            "OUTPUT": "memory:"
        })["OUTPUT"]

    return unioned


def dissolve_selected_polygons(
    output_layer_name="dissolved_selected_polygons",
    remove_scratch_layers=True,
    remove_existing_output=True
):
    project = QgsProject.instance()

    # =========================
    # ① プロジェクト内の全レイヤから
    #    feature が選択されているポリゴンレイヤを取得
    # =========================
    poly_layers = [
        lyr for lyr in project.mapLayers().values()
        if lyr.type() == lyr.VectorLayer
        and QgsWkbTypes.geometryType(lyr.wkbType()) == QgsWkbTypes.PolygonGeometry
        and lyr.selectedFeatureCount() > 0
    ]

    if len(poly_layers) == 0:
        raise RuntimeError("feature が選択されているポリゴンレイヤが見つかりません。")

    print("対象レイヤ:")
    for lyr in poly_layers:
        print(f"  - {lyr.name()} ({lyr.selectedFeatureCount()}件選択, provider={lyr.providerType()})")

    # =========================
    # ② 元レイヤのうち Temporary Scratch Layer(memory) を記録
    # =========================
    scratch_source_layers = [
        lyr for lyr in poly_layers
        if lyr.providerType() == "memory"
    ]

    # =========================
    # ③ 各レイヤの選択地物だけ抽出
    # =========================
    selected_layers = []
    target_crs = poly_layers[0].crs()

    for lyr in poly_layers:
        result = processing.run("native:saveselectedfeatures", {
            "INPUT": lyr,
            "OUTPUT": "memory:"
        })
        selected = _reproject_to_crs(result["OUTPUT"], target_crs)
        selected_layers.append(_fix_geometries(selected))

    # =========================
    # ④ Union
    # =========================
    unioned = _union_layers(selected_layers)
    unioned = _fix_geometries(unioned)

    # =========================
    # ⑤ 完全Dissolve（全部まとめる）
    # =========================
    dissolved = processing.run("native:dissolve", {
        "INPUT": unioned,
        "FIELD": [],
        "OUTPUT": "memory:"
    })["OUTPUT"]
    dissolved = _fix_geometries(dissolved)

    dissolved.setName(output_layer_name)

    # =========================
    # ⑥ すべてのベクターレイヤの選択を解除
    # =========================
    for lyr in project.mapLayers().values():
        if lyr.type() == lyr.VectorLayer:
            lyr.removeSelection()

    # =========================
    # ⑦ 元レイヤの Temporary Scratch Layer を削除
    # =========================
    if remove_scratch_layers:
        for lyr in scratch_source_layers:
            if project.mapLayer(lyr.id()):
                print(f"Temporary Scratch Layer を削除: {lyr.name()}")
                project.removeMapLayer(lyr.id())

    # =========================
    # ⑧ 既存の同名出力レイヤがあれば削除
    # =========================
    if remove_existing_output:
        existing_outputs = project.mapLayersByName(output_layer_name)
        for lyr in existing_outputs:
            if project.mapLayer(lyr.id()):
                print(f"既存の出力レイヤを削除: {lyr.name()}")
                project.removeMapLayer(lyr.id())

    # =========================
    # ⑨ 最終レイヤを追加
    # =========================
    project.addMapLayer(dissolved)

    # =========================
    # ⑩ 最終レイヤをアクティブにして選択
    # =========================
    iface.setActiveLayer(dissolved)
    dissolved.selectAll()

    iface.mapCanvas().refresh()

    print("選択ポリゴンをマージして完全Dissolveしました。")
    print(f"作成レイヤ '{output_layer_name}' を追加し、選択しました。")

    return dissolved


if __name__ == "__console__":
    dissolve_selected_polygons()
