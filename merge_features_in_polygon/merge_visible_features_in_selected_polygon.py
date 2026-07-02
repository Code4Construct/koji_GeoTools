# -*- coding: utf-8 -*-

import os

from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox
from qgis.core import (
    QgsProject,
    QgsWkbTypes,
    QgsVectorLayer,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsFeatureRequest,
    QgsVectorFileWriter,
    QgsGeometry
)
from PyQt5.QtCore import QVariant

from ..layer_tree_utils import (
    copy_layer_tree_node_properties,
    move_layers_to_group,
    move_layers_to_nested_group,
)


# =========================================================
# 設定
# =========================================================
EXCLUDE_FIELD_NAMES = {"fid"}   # GeoPackageの主キー衝突回避
ADD_SOURCE_FID = True           # 元feature idを保存したい場合
SOURCE_FID_FIELD_NAME = "src_fid"


def apply_layer_display_settings(source_layer, target_layer):
    if source_layer is None or target_layer is None:
        return

    try:
        target_layer.setRenderer(source_layer.renderer().clone())
    except Exception:
        pass

    try:
        if source_layer.labeling() is not None:
            target_layer.setLabeling(source_layer.labeling().clone())
        target_layer.setLabelsEnabled(source_layer.labelsEnabled())
    except Exception:
        pass

    try:
        target_layer.setScaleBasedVisibility(source_layer.hasScaleBasedVisibility())
        target_layer.setMinimumScale(source_layer.minimumScale())
        target_layer.setMaximumScale(source_layer.maximumScale())
    except Exception:
        pass

    try:
        target_layer.setOpacity(source_layer.opacity())
    except Exception:
        pass

    try:
        for key in source_layer.customPropertyKeys():
            target_layer.setCustomProperty(key, source_layer.customProperty(key))
    except Exception:
        pass

    target_layer.triggerRepaint()


def run_merge_visible_features_in_selected_polygon(
    iface,
    output_path=None,
    output_layer_name=None,
    output_polygon_layer_name=None,
    output_crs=None,
    add_to_project=True,
    add_source_fid=True,
    inherit_style=True,
    layer_group_name='',
    output_mode='single',
    name_prefix='',
):
    """
    QGIS plugin の def run(self) から呼び出すための関数
    iface を受け取り、選択ポリゴン内にある表示中地物を抽出して
    GeoPackage に保存し、保存後にレイヤを読み込みます。
    """
    try:
        # =========================================================
        # 1. プロジェクト取得
        # =========================================================
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        transform_context = project.transformContext()

        # =========================================================
        # 2. 選択 feature を持つポリゴンレイヤを探す
        # =========================================================
        candidate_polygon_layers = []

        for lyr in project.mapLayers().values():
            if not isinstance(lyr, QgsVectorLayer):
                continue
            if lyr.geometryType() != QgsWkbTypes.PolygonGeometry:
                continue
            if lyr.selectedFeatureCount() > 0:
                candidate_polygon_layers.append(lyr)

        if not candidate_polygon_layers:
            raise Exception("選択 feature を持つポリゴンレイヤがありません。ポリゴン feature を選択してください。")

        if len(candidate_polygon_layers) > 1:
            layer_names = [lyr.name() for lyr in candidate_polygon_layers]
            raise Exception(
                "選択 feature を持つポリゴンレイヤが複数あります。"
                f" 1つだけにしてください: {layer_names}"
            )

        polygon_layer = candidate_polygon_layers[0]
        selected_polygon_features = polygon_layer.selectedFeatures()

        # =========================================================
        # 3. 選択ポリゴンを1つのジオメトリに結合
        # =========================================================
        selected_geoms = []

        for f in selected_polygon_features:
            g = f.geometry()
            if g is not None and not g.isEmpty():
                selected_geoms.append(g)

        if not selected_geoms:
            raise Exception("選択されたポリゴンに有効なジオメトリがありません。")

        merged_polygon_geom = QgsGeometry(selected_geoms[0])
        for g in selected_geoms[1:]:
            merged_polygon_geom = merged_polygon_geom.combine(g)

        polygon_crs = polygon_layer.crs()
        save_crs = QgsCoordinateReferenceSystem(str(output_crs or ''))
        if not save_crs.isValid():
            save_crs = polygon_crs
        save_crs_authid = save_crs.authid() or polygon_crs.authid()
        to_save_crs = None
        if save_crs.isValid() and polygon_crs.isValid() and save_crs != polygon_crs:
            to_save_crs = QgsCoordinateTransform(polygon_crs, save_crs, transform_context)
        if iface is not None:
            iface.messageBar().pushInfo(
                "保存CRS",
                "対象ポリゴンCRS: {0} / 保存CRS: {1}".format(
                    polygon_crs.authid() or polygon_crs.description(),
                    save_crs.authid() or save_crs.description(),
                ),
            )

        # =========================================================
        # 4. 表示中のポイントレイヤ取得
        # =========================================================
        visible_point_layers = []

        for lyr in project.mapLayers().values():
            if not isinstance(lyr, QgsVectorLayer):
                continue
            if lyr.geometryType() != QgsWkbTypes.PointGeometry:
                continue

            node = root.findLayer(lyr.id())
            if node is None:
                continue
            if not node.isVisible():
                continue

            visible_point_layers.append(lyr)

        if not visible_point_layers:
            pass

        visible_polygon_layers = []

        for lyr in project.mapLayers().values():
            if not isinstance(lyr, QgsVectorLayer):
                continue
            if lyr.geometryType() != QgsWkbTypes.PolygonGeometry:
                continue
            if lyr.id() == polygon_layer.id():
                continue

            node = root.findLayer(lyr.id())
            if node is None:
                continue
            if not node.isVisible():
                continue

            visible_polygon_layers.append(lyr)

        if not visible_point_layers and not visible_polygon_layers:
            raise Exception("表示されているポイントレイヤまたはポリゴンレイヤが見つかりません。")

        # =========================================================
        # 5. 出力フィールド作成
        #    表示中ポイントレイヤの全属性を統合
        #    ただし fid は除外
        # =========================================================
        out_fields = QgsFields()
        field_name_set = set()

        if add_source_fid:
            out_fields.append(QgsField(SOURCE_FID_FIELD_NAME, QVariant.LongLong))
            field_name_set.add(SOURCE_FID_FIELD_NAME)

        for lyr in visible_point_layers:
            for fld in lyr.fields():
                fld_name = fld.name()

                if fld_name.lower() in EXCLUDE_FIELD_NAMES:
                    continue

                if fld_name not in field_name_set:
                    out_fields.append(QgsField(fld))
                    field_name_set.add(fld_name)

        if visible_point_layers and len(out_fields) == 0:
            raise Exception("出力すべき属性フィールドがありません。")

        # =========================================================
        # 6. 保存ダイアログ
        # =========================================================
        project_path = project.fileName()

        if project_path:
            initial_dir = os.path.dirname(project_path)
        else:
            initial_dir = os.path.expanduser("~")

        default_file_name = "merged_points_in_polygon.gpkg"

        parent_widget = iface.mainWindow() if iface is not None else None

        save_path = output_path
        if not save_path:
            save_path, _ = QFileDialog.getSaveFileName(
                parent_widget,
                "GeoPackageとして保存",
                os.path.join(initial_dir, default_file_name),
                "GeoPackage (*.gpkg)"
            )

        if not save_path:
            return  # キャンセル時は静かに終了

        if not save_path.lower().endswith(".gpkg"):
            save_path += ".gpkg"

        if not output_layer_name:
            output_layer_name = os.path.splitext(os.path.basename(save_path))[0]
        if not output_polygon_layer_name:
            output_polygon_layer_name = "merged_polygons_in_polygon"

        def prefixed_name(name):
            return "{0}{1}".format(name_prefix or "", name)

        def unique_name(name, used_names):
            candidate = name
            index = 2
            while candidate in used_names:
                candidate = "{0}_{1}".format(name, index)
                index += 1
            used_names.add(candidate)
            return candidate

        def source_parent_group_name(layer):
            node = root.findLayer(layer.id())
            if node is None:
                return ""
            parent = node.parent()
            if parent is not None and parent != root and parent.name():
                return parent.name()
            return ""

        def fields_for_layer(source_layer):
            fields = QgsFields()
            names = set()
            if add_source_fid:
                fields.append(QgsField(SOURCE_FID_FIELD_NAME, QVariant.LongLong))
                names.add(SOURCE_FID_FIELD_NAME)
            for field in source_layer.fields():
                field_name = field.name()
                if field_name.lower() in EXCLUDE_FIELD_NAMES:
                    continue
                if field_name in names:
                    continue
                fields.append(QgsField(field))
                names.add(field_name)
            return fields

        def collect_features(source_layer, fields):
            features = []
            pt_crs = source_layer.crs()
            if pt_crs != polygon_crs:
                to_polygon_crs = QgsCoordinateTransform(pt_crs, polygon_crs, transform_context)
                to_point_crs = QgsCoordinateTransform(polygon_crs, pt_crs, transform_context)
                bbox_for_request = to_point_crs.transformBoundingBox(merged_polygon_geom.boundingBox())
            else:
                to_polygon_crs = None
                bbox_for_request = merged_polygon_geom.boundingBox()

            request = QgsFeatureRequest().setFilterRect(bbox_for_request)
            for feat in source_layer.getFeatures(request):
                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    continue
                test_geom = QgsGeometry(geom)
                if to_polygon_crs is not None:
                    try:
                        test_geom.transform(to_polygon_crs)
                    except Exception:
                        continue
                if not merged_polygon_geom.contains(test_geom):
                    continue
                out_geom = QgsGeometry(test_geom)
                if to_save_crs is not None:
                    try:
                        out_geom.transform(to_save_crs)
                    except Exception:
                        continue
                new_feat = QgsFeature(fields)
                new_feat.setGeometry(out_geom)
                attr_dict = {field.name(): None for field in fields}
                if add_source_fid:
                    attr_dict[SOURCE_FID_FIELD_NAME] = feat.id()
                for field in source_layer.fields():
                    field_name = field.name()
                    if field_name.lower() in EXCLUDE_FIELD_NAMES:
                        continue
                    if field_name in attr_dict:
                        try:
                            attr_dict[field_name] = feat[field_name]
                        except Exception:
                            attr_dict[field_name] = None
                new_feat.setAttributes([attr_dict[field.name()] for field in fields])
                features.append(new_feat)
            return features

        def collect_polygon_features(source_layer, fields):
            features = []
            source_crs = source_layer.crs()
            if source_crs.isValid() and source_crs != polygon_crs:
                to_polygon_crs = QgsCoordinateTransform(source_crs, polygon_crs, transform_context)
                to_source_crs = QgsCoordinateTransform(polygon_crs, source_crs, transform_context)
                bbox_for_request = to_source_crs.transformBoundingBox(merged_polygon_geom.boundingBox())
            else:
                to_polygon_crs = None
                bbox_for_request = merged_polygon_geom.boundingBox()

            request = QgsFeatureRequest().setFilterRect(bbox_for_request)
            for feat in source_layer.getFeatures(request):
                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    continue
                test_geom = QgsGeometry(geom)
                if to_polygon_crs is not None:
                    try:
                        test_geom.transform(to_polygon_crs)
                    except Exception:
                        continue
                if QgsWkbTypes.geometryType(test_geom.wkbType()) != QgsWkbTypes.PolygonGeometry:
                    continue
                if not merged_polygon_geom.intersects(test_geom):
                    continue
                out_geom = QgsGeometry(test_geom)
                if to_save_crs is not None:
                    try:
                        out_geom.transform(to_save_crs)
                    except Exception:
                        continue
                new_feat = QgsFeature(fields)
                new_feat.setGeometry(out_geom)
                attr_dict = {field.name(): None for field in fields}
                if add_source_fid:
                    attr_dict[SOURCE_FID_FIELD_NAME] = feat.id()
                for field in source_layer.fields():
                    field_name = field.name()
                    if field_name.lower() in EXCLUDE_FIELD_NAMES:
                        continue
                    if field_name in attr_dict:
                        try:
                            attr_dict[field_name] = feat[field_name]
                        except Exception:
                            attr_dict[field_name] = None
                new_feat.setAttributes([attr_dict[field.name()] for field in fields])
                features.append(new_feat)
            return features

        def polygon_union_fields():
            fields = QgsFields()
            names = set()
            if add_source_fid:
                fields.append(QgsField(SOURCE_FID_FIELD_NAME, QVariant.LongLong))
                names.add(SOURCE_FID_FIELD_NAME)
            for layer in visible_polygon_layers:
                for field in layer.fields():
                    field_name = field.name()
                    if field_name.lower() in EXCLUDE_FIELD_NAMES:
                        continue
                    if field_name in names:
                        continue
                    fields.append(QgsField(field))
                    names.add(field_name)
            return fields

        def save_single_polygon_layer():
            if not visible_polygon_layers:
                return None
            poly_fields = polygon_union_fields()
            if len(poly_fields) == 0:
                return None
            polygon_features = []
            for source_layer in visible_polygon_layers:
                polygon_features.extend(collect_polygon_features(source_layer, poly_fields))
            if not polygon_features:
                return None

            poly_layer = QgsVectorLayer(
                f"MultiPolygon?crs={save_crs_authid}",
                output_polygon_layer_name,
                "memory"
            )
            poly_dp = poly_layer.dataProvider()
            poly_dp.addAttributes(poly_fields)
            poly_layer.updateFields()
            poly_dp.addFeatures(polygon_features)
            poly_layer.updateExtents()

            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = output_polygon_layer_name
            options.fileEncoding = "UTF-8"
            options.destCRS = save_crs
            if os.path.exists(save_path):
                options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

            write_result = QgsVectorFileWriter.writeAsVectorFormatV3(
                poly_layer,
                save_path,
                transform_context,
                options
            )
            if write_result[0] != QgsVectorFileWriter.NoError:
                raise Exception(f"GPKG保存エラー: {write_result}")

            saved_uri = f"{save_path}|layername={output_polygon_layer_name}"
            saved_layer = QgsVectorLayer(saved_uri, output_polygon_layer_name, "ogr")
            if not saved_layer.isValid():
                return None
            if inherit_style and len(visible_polygon_layers) == 1:
                apply_layer_display_settings(visible_polygon_layers[0], saved_layer)
            if add_to_project:
                QgsProject.instance().addMapLayer(saved_layer)
                move_layers_to_group([saved_layer], layer_group_name)
                if inherit_style and len(visible_polygon_layers) == 1:
                    copy_layer_tree_node_properties(visible_polygon_layers[0], saved_layer)
            return {
                "layer_name": output_polygon_layer_name,
                "feature_count": len(polygon_features),
                "source_layers": [layer.name() for layer in visible_polygon_layers],
            }

        if output_mode == "split_by_source":
            saved_infos = []
            used_layer_names = set()

            for source_layer in visible_point_layers:
                split_fields = fields_for_layer(source_layer)
                if len(split_fields) == 0:
                    continue
                split_features = collect_features(source_layer, split_fields)
                if not split_features:
                    continue

                split_layer_name = unique_name(prefixed_name(source_layer.name()), used_layer_names)
                source_group_name = source_parent_group_name(source_layer)
                split_group_name = prefixed_name(source_group_name) if source_group_name else ""
                split_layer = QgsVectorLayer(
                    f"Point?crs={save_crs_authid}",
                    split_layer_name,
                    "memory"
                )
                split_dp = split_layer.dataProvider()
                split_dp.addAttributes(split_fields)
                split_layer.updateFields()
                split_dp.addFeatures(split_features)
                split_layer.updateExtents()

                options = QgsVectorFileWriter.SaveVectorOptions()
                options.driverName = "GPKG"
                options.layerName = split_layer_name
                options.fileEncoding = "UTF-8"
                options.destCRS = save_crs
                if os.path.exists(save_path):
                    options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

                write_result = QgsVectorFileWriter.writeAsVectorFormatV3(
                    split_layer,
                    save_path,
                    transform_context,
                    options
                )
                if write_result[0] != QgsVectorFileWriter.NoError:
                    raise Exception(f"GPKG保存エラー: {write_result}")

                saved_uri = f"{save_path}|layername={split_layer_name}"
                saved_layer = QgsVectorLayer(saved_uri, split_layer_name, "ogr")
                if not saved_layer.isValid():
                    continue
                if inherit_style:
                    apply_layer_display_settings(source_layer, saved_layer)
                if add_to_project:
                    QgsProject.instance().addMapLayer(saved_layer)
                    move_layers_to_nested_group([saved_layer], layer_group_name, split_group_name)
                    copy_layer_tree_node_properties(source_layer, saved_layer)

                saved_infos.append({
                    "source_layer": source_layer.name(),
                    "layer_name": split_layer_name,
                    "layer_group_name": split_group_name,
                    "parent_group_name": layer_group_name,
                    "feature_count": len(split_features),
                })

            for source_layer in visible_polygon_layers:
                split_fields = fields_for_layer(source_layer)
                if len(split_fields) == 0:
                    continue
                split_features = collect_polygon_features(source_layer, split_fields)
                if not split_features:
                    continue

                split_layer_name = unique_name(prefixed_name(source_layer.name()), used_layer_names)
                source_group_name = source_parent_group_name(source_layer)
                split_group_name = prefixed_name(source_group_name) if source_group_name else ""
                split_layer = QgsVectorLayer(
                f"MultiPolygon?crs={save_crs_authid}",
                    split_layer_name,
                    "memory"
                )
                split_dp = split_layer.dataProvider()
                split_dp.addAttributes(split_fields)
                split_layer.updateFields()
                split_dp.addFeatures(split_features)
                split_layer.updateExtents()

                options = QgsVectorFileWriter.SaveVectorOptions()
                options.driverName = "GPKG"
                options.layerName = split_layer_name
                options.fileEncoding = "UTF-8"
                options.destCRS = save_crs
                if os.path.exists(save_path):
                    options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

                write_result = QgsVectorFileWriter.writeAsVectorFormatV3(
                    split_layer,
                    save_path,
                    transform_context,
                    options
                )
                if write_result[0] != QgsVectorFileWriter.NoError:
                    raise Exception(f"GPKG保存エラー: {write_result}")

                saved_uri = f"{save_path}|layername={split_layer_name}"
                saved_layer = QgsVectorLayer(saved_uri, split_layer_name, "ogr")
                if not saved_layer.isValid():
                    continue
                if inherit_style:
                    apply_layer_display_settings(source_layer, saved_layer)
                if add_to_project:
                    QgsProject.instance().addMapLayer(saved_layer)
                    move_layers_to_nested_group([saved_layer], layer_group_name, split_group_name)
                    copy_layer_tree_node_properties(source_layer, saved_layer)

                saved_infos.append({
                    "source_layer": source_layer.name(),
                    "layer_name": split_layer_name,
                    "layer_group_name": split_group_name,
                    "parent_group_name": layer_group_name,
                    "feature_count": len(split_features),
                    "geometry": "polygon",
                })

            if not saved_infos:
                raise Exception("選択ポリゴン内に保存対象の表示中ポイント feature は見つかりませんでした。")

            polygon_layer.removeSelection()
            if iface is not None:
                iface.mapCanvas().refresh()
                iface.messageBar().pushSuccess("完了", "ポイント抽出レイヤをレイヤ別に保存しました。")

            QMessageBox.information(
                parent_widget,
                "完了",
                "保存完了\n{0}\n\n保存レイヤ数: {1}\n保存件数: {2}".format(
                    save_path,
                    len(saved_infos),
                    sum(info["feature_count"] for info in saved_infos),
                )
            )
            return {
                "save_path": save_path,
                "mode": "split_by_source",
                "layers": saved_infos,
                "feature_count": sum(info["feature_count"] for info in saved_infos),
            }

        # =========================================================
        # 7. 出力メモリレイヤ作成
        # =========================================================
        out_layer = QgsVectorLayer(
            f"Point?crs={save_crs_authid}",
            output_layer_name,
            "memory"
        )

        out_dp = out_layer.dataProvider()
        out_dp.addAttributes(out_fields)
        out_layer.updateFields()

        # =========================================================
        # 8. ポリゴン内の地物を抽出して追加
        # =========================================================
        new_features = []

        for pt_layer in visible_point_layers:
            print("処理中:", pt_layer.name())

            pt_crs = pt_layer.crs()

            if pt_crs != polygon_crs:
                to_polygon_crs = QgsCoordinateTransform(pt_crs, polygon_crs, transform_context)
                to_point_crs = QgsCoordinateTransform(polygon_crs, pt_crs, transform_context)
                bbox_for_request = to_point_crs.transformBoundingBox(merged_polygon_geom.boundingBox())
            else:
                to_polygon_crs = None
                bbox_for_request = merged_polygon_geom.boundingBox()

            request = QgsFeatureRequest().setFilterRect(bbox_for_request)

            for feat in pt_layer.getFeatures(request):
                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    continue

                test_geom = QgsGeometry(geom)

                if to_polygon_crs is not None:
                    try:
                        test_geom.transform(to_polygon_crs)
                    except Exception:
                        continue

                if not merged_polygon_geom.contains(test_geom):
                    continue

                new_feat = QgsFeature(out_fields)
                new_feat.setGeometry(test_geom)

                attr_dict = {fld.name(): None for fld in out_fields}

                if add_source_fid:
                    attr_dict[SOURCE_FID_FIELD_NAME] = feat.id()

                for fld in pt_layer.fields():
                    fname = fld.name()

                    if fname.lower() in EXCLUDE_FIELD_NAMES:
                        continue

                    if fname in attr_dict:
                        try:
                            attr_dict[fname] = feat[fname]
                        except Exception:
                            attr_dict[fname] = None

                new_feat.setAttributes([attr_dict[fld.name()] for fld in out_fields])
                new_features.append(new_feat)

        if not new_features:
            polygon_info = save_single_polygon_layer()
            if polygon_info is None:
                raise Exception("選択ポリゴン内にある表示中ポイントまたはポリゴン feature は見つかりませんでした。")
            polygon_layer.removeSelection()
            if iface is not None:
                iface.mapCanvas().refresh()
                iface.messageBar().pushSuccess("完了", "ポリゴン抽出レイヤを保存しました。")
            QMessageBox.information(
                parent_widget,
                "完了",
                "保存完了\n{0}\n\n保存ポリゴンレイヤ: {1}\n保存件数: {2}".format(
                    save_path,
                    polygon_info["layer_name"],
                    polygon_info["feature_count"],
                )
            )
            return {
                "save_path": save_path,
                "mode": "single",
                "polygon": polygon_info,
                "feature_count": polygon_info["feature_count"],
            }

        out_dp.addFeatures(new_features)
        out_layer.updateExtents()

        # =========================================================
        # 9. GPKG保存
        # =========================================================
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = output_layer_name
        options.fileEncoding = "UTF-8"
        options.destCRS = save_crs

        write_result = QgsVectorFileWriter.writeAsVectorFormatV3(
            out_layer,
            save_path,
            transform_context,
            options
        )

        result_code = write_result[0]

        if result_code != QgsVectorFileWriter.NoError:
            raise Exception(f"GPKG保存エラー: {write_result}")

        # =========================================================
        # 10. 保存したレイヤを読み込み
        # =========================================================
        saved_uri = f"{save_path}|layername={output_layer_name}"
        saved_layer = QgsVectorLayer(saved_uri, output_layer_name, "ogr")

        if saved_layer.isValid():
            if inherit_style and len(visible_point_layers) == 1:
                apply_layer_display_settings(visible_point_layers[0], saved_layer)

            if add_to_project:
                QgsProject.instance().addMapLayer(saved_layer)
                move_layers_to_group([saved_layer], layer_group_name)
                if inherit_style and len(visible_point_layers) == 1:
                    copy_layer_tree_node_properties(visible_point_layers[0], saved_layer)

            polygon_info = save_single_polygon_layer()

            polygon_layer.removeSelection()
            if iface is not None:
                iface.mapCanvas().refresh()

            msg = (
                f"保存完了:\n{save_path}\n\n"
                f"使用ポリゴンレイヤ: {polygon_layer.name()}\n"
                f"保存レイヤ名: {output_layer_name}\n"
                f"保存件数: {len(new_features)}"
            )
            result_info = {
                "save_path": save_path,
                "layer_name": output_layer_name,
                "feature_count": len(new_features),
                "source_layers": [layer.name() for layer in visible_point_layers],
                "layer_group_name": layer_group_name,
                "polygon": polygon_info,
            }
            if iface is not None:
                iface.messageBar().pushSuccess("完了", "ポイント結合レイヤを保存しました。")
            QMessageBox.information(parent_widget, "完了", msg)
            return result_info
        else:
            QMessageBox.warning(
                parent_widget,
                "注意",
                f"保存は完了しましたが、レイヤの再読込に失敗しました。\n保存先: {save_path}"
            )

    except Exception as e:
        parent_widget = iface.mainWindow() if iface is not None else None
        if iface is not None:
            iface.messageBar().pushCritical("エラー", str(e))
        QMessageBox.critical(parent_widget, "エラー", str(e))
        raise
