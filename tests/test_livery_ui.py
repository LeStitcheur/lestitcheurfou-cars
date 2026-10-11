"""Livery Studio Pro (interface) : parcours d'acceptation du prompt 6 dans la vraie fenêtre.

Ouvrir → importer un véhicule → Livery Studio → texture et UV → nouveau document → peindre
sur le véhicule (3D) → logo → texte → bandes → calques → aperçu 3D → seconde variante →
sauvegarder → fermer → rouvrir sans perte → exporter.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QItemSelectionModel

from lsfcars.livery import export
from lsfcars.livery.logos import LogoLibrary
from lsfcars.project.model import VehicleRole, VehicleType
from lsfcars.ui.dialogs.new_project import NewProjectRequest


@pytest.fixture
def livery_window(window, qtbot, projects_dir, livery_glb, tmp_path):
    logos = LogoLibrary(tmp_path / "logos")
    logos.ensure_builtins()
    window.livery.set_logos(logos)
    request = NewProjectRequest("Livrée UI", projects_dir, VehicleType.CAR, VehicleRole.LSPD, "")
    assert window.new_project(request)
    with qtbot.waitSignal(window.controller.import_finished, timeout=30000) as blocker:
        assert window.import_model(livery_glb)
    assert blocker.args[0]
    window.navigate("liveries")
    qtbot.wait(50)
    return window


def test_livery_acceptance_flow(livery_window, qtbot, tmp_path):
    window = livery_window
    page = window.livery
    assert window.current_page() == "liveries"  # 3. Livery Studio ouvert
    assert [page.left.tabText(i) for i in range(4)] == ["Outils", "Formes", "Logos", "Modèles"]
    assert [page.right.tabText(i) for i in range(4)] == ["Calques", "Propriétés", "Couleurs", "Matériaux"]
    assert [page.bottom.tabText(i) for i in range(3)] == ["Historique", "Progression", "Diagnostics"]
    assert page.new_button.isVisible()
    doc = page.create_document(size=512, name="LSPD Patrol")  # 5. nouveau document
    assert doc is not None and doc.base_texture  # 4. texture d'origine chargée
    qtbot.wait(50)
    page.bottom.setCurrentWidget(page.uv_panel)
    page.uv_panel.refresh()
    assert "îlots" in page.uv_panel.report.text()  # 4. UV visibles et analysées
    page.set_view_mode("uv")
    assert page.canvas.isVisible() and not page.viewport.isVisible()
    page.set_view_mode("3d")
    assert page.viewport.isVisible() and not page.canvas.isVisible()
    page.set_view_mode("split")
    qtbot.wait(50)
    session = window.controller.session
    viewport = page.viewport
    viewport.frame_bounds(session.world_bounds())

    # 6. Peinture directe sur le véhicule (vue 3D) : les pixels de la texture changent
    page.set_tool("brush")
    page.colors.set_color("#2563EB")
    before = page.studio.composite()
    surface = page.studio.surface()
    w, h = viewport.width(), viewport.height()
    candidates = [(x, y) for y in np.linspace(0.35, 0.75, 9) * h for x in np.linspace(0.3, 0.7, 9) * w]
    spot = next((p for p in candidates if surface.raycast(*viewport.screen_ray(*p)) is not None), None)
    assert spot is not None
    assert page.begin(spot[0], spot[1], 1.0)
    page.move(spot[0] + 25, spot[1] + 5, 0.8)
    page.end()
    painted = page.studio.composite()
    assert (np.abs(painted.astype(int) - before.astype(int)).max(axis=-1) > 4).sum() > 50

    # 7. Logo (bibliothèque) sur les deux flancs
    assert page.logos_panel.select_logo("lsf-shield")
    assert len(page.logos_panel.add_sides()) == 2
    # 8. Texte (marquage) et 9. bandes
    page.markings.text.setText("POLICE")
    assert len(page.markings.add_marking()) == 2
    page.markings.pattern.select_data("checker")
    assert page.markings.add_band() is not None
    qtbot.wait(50)
    variant = page.studio.require().active_variant
    kinds = [layer.kind for layer in variant.walk()]
    assert kinds.count("image") == 2 and kinds.count("text") == 2 and "band" in kinds

    # 10. Organisation des calques : groupe, opacité
    page.refresh()
    tree = page.layers.tree  # sélection comme un clic : par le modèle de sélection
    tree.clearSelection()
    model = tree.model()
    for row in range(model.rowCount()):
        index = model.index(row, 0)
        if str(model.data(index)).startswith("POLICE"):
            tree.selectionModel().select(index, QItemSelectionModel.SelectionFlag.Select)
    group = page.group_selected()
    assert group is not None and page.studio.layer(group).kind == "group"
    assert len(page.studio.layer(group).children) == 2
    page.select_layer(group)
    page.layers.opacity.setValue(60)
    page.commit_edit()
    assert abs(page.studio.layer(group).opacity - 0.6) < 1e-6

    # Propriétés : édition du texte (aperçu puis une seule étape d'historique)
    text_id = next(layer.id for layer in page.studio.require().active_variant.walk() if layer.kind == "text")
    page.select_layer(text_id)
    history = len(session.stack.history())
    page.properties.text.setPlainText("POLICE 27")
    page.commit_edit()
    assert page.studio.layer(text_id).params["text"] == "POLICE 27"
    assert len(session.stack.history()) == history + 1

    # 11. Aperçu 3D : la texture composée est celle du viewport (et du Vehicle Editor)
    page.refresh()
    material = page.studio.require().targets[0]
    assert session.live_textures[material] is page.studio.live
    assert any(item.live_texture is page.studio.live for item in viewport.draw_items())
    window.navigate("studio")
    assert any(item.live_texture is not None for item in window.studio.viewport.draw_items())
    window.navigate("liveries")

    # 12. Seconde variante (modèle EMS)
    page.variants.name.setText("EMS Rescue")
    page.variants.template.select_data("ems")
    second = page.variants.create()
    assert second is not None and len(page.studio.require().variants) == 2
    qtbot.wait(50)

    # 16. Export des textures (comparé au viewport après réouverture)
    expected = {v.id: page.studio.composite(v.id) for v in page.studio.require().variants}
    reports = page.export_now(str(tmp_path / "export"), export.ExportOptions("png", padding=0), "all")
    assert len(reports) == 2 and all(r.verified for r in reports)

    # 13-15. Sauvegarder, fermer, rouvrir sans perdre les calques
    assert window.save_project()
    path = session.file_path
    assert window.close_project()
    assert window.open_project(path)
    window.navigate("liveries")
    qtbot.wait(50)
    page.refresh()
    reopened = page.studio.require()
    assert [v.name for v in reopened.variants] == ["LSPD Patrol", "EMS Rescue"]
    for variant_id, array in expected.items():
        assert np.array_equal(page.studio.composite(variant_id), array)
    patrol = reopened.variants[0]
    assert any(layer.params.get("text") == "POLICE 27" for layer in patrol.walk())  # toujours éditable
    exported = np.array(Image.open(reports[0].path).convert("RGBA"))
    assert np.array_equal(exported, expected[patrol.id])  # export = viewport

    # Annuler / rétablir depuis la fenêtre
    page.run("Livrée", lambda: page.studio.activate_variant(patrol.id))
    window.controller.undo()
    assert page.studio.require().active == reopened.variants[1].id
    window.controller.redo()
    assert page.studio.require().active == patrol.id


def test_canvas_tools_2d(livery_window, qtbot):
    page = livery_window.livery
    page.create_document(size=256)
    qtbot.wait(50)
    canvas = page.canvas
    page.set_tool("rect")
    canvas.press(20, 20)
    canvas.drag(80, 60)
    canvas.release()
    page.set_tool("polygon")
    for point in ((100, 100), (150, 100), (125, 140)):
        canvas.press(*point)
        canvas.release()
    canvas.finish_points()
    page.set_tool("text")
    canvas.press(128, 200)
    shapes = [layer.params.get("shape") for layer in page.studio.require().active_variant.walk()]
    assert "rect" in shapes and "polygon" in shapes
    text = page.current_layer()
    assert text.kind == "text" and page.tool == "move"
    x0, y0 = text.params["x"], text.params["y"]
    canvas.press(x0, y0)  # déplacement de l'élément (poignée centrale)
    canvas.drag(x0 + 20, y0)
    canvas.release()
    assert abs(page.studio.layer(text.id).params["x"] - (x0 + 20)) < 1e-6
    page.set_tool("select")
    canvas.press(10, 10)
    canvas.drag(100, 100)
    canvas.release()
    assert page.studio.selection is not None
    page.set_tool("brush")
    paint = page.studio.require().active_variant.layers[0]
    page.current_layer_id = paint.id
    canvas.press(50, 50)
    canvas.drag(200, 50)  # hors de la sélection : non peint
    canvas.release()
    pixels = page.studio.scene.images[paint.image].array
    assert pixels[50, 50, 3] > 0 and pixels[50, 180, 3] == 0
    page.set_tool("pipette")
    canvas.press(60, 40)
    assert page.colors.color().startswith("#")
    page.set_view_mode("uv")
    canvas.set_zoom(4.0)
    canvas.fit()
    assert 0 < canvas.zoom < 4.0


def test_document_errors_are_notifications(window, qtbot, projects_dir, sample_glb, tmp_path):
    window.livery.set_logos(LogoLibrary(tmp_path / "logos"))
    request = NewProjectRequest("Sans UV", projects_dir, VehicleType.CAR, VehicleRole.CIVILIAN, "")
    assert window.new_project(request)
    with qtbot.waitSignal(window.controller.import_finished, timeout=30000):
        assert window.import_model(sample_glb)
    window.navigate("liveries")
    page = window.livery
    messages = []
    window.controller.notify.connect(lambda title, message, level: messages.append(message))
    assert page.create_document() is None  # modèle sans UV : refus expliqué
    assert any("UV absentes" in m for m in messages)
    assert page.project_uvs(confirm=False)
    assert page.create_document(size=256) is not None
