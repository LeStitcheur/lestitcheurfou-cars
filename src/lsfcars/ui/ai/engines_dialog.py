"""Paramètres des moteurs IA : mode, confirmation cloud, délais, cache, configuration par moteur.

Les clés API se saisissent ici et vont dans le coffre Windows (DPAPI) ; seul un masque est
affiché. Les tests de connexion n'utilisent que des appels gratuits (solde, liste des modèles,
état du serveur). L'installation de TripoSR lance ``scripts/install_triposr.ps1`` après
confirmation explicite (liste des téléchargements et tailles).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from lsfcars.ai import secrets as secrets_mod
from lsfcars.ai.errors import AIError
from lsfcars.core.paths import is_frozen
from lsfcars.ui.design.components import LSInput, LSSelect, LSTabs, label
from lsfcars.ui.editor.panels import Page, button, spin
from lsfcars.ui.livery.panels import check

KEY_PROVIDERS = ("meshy", "anthropic")
TRIPOSR_DOWNLOADS = (
    "uv (gestionnaire Python, via pip) et Python 3.12 — environ 60 Mo",
    "PyTorch (download.pytorch.org, CUDA 12.8 ou CPU) — environ 2,5 à 3 Go",
    "Dépendances (transformers, trimesh, PyMCubes, imageio…) — environ 150 Mo",
    "Code TripoSR (GitHub VAST-AI-Research/TripoSR, licence MIT) — quelques Mo",
    "Poids stabilityai/TripoSR (Hugging Face, licence MIT) — environ 1,7 Go",
)


def install_script() -> Path | None:
    candidates = [Path(__file__).resolve().parents[4] / "scripts" / "install_triposr.ps1"]
    if is_frozen():
        candidates.insert(0, Path(getattr(sys, "_MEIPASS", ".")) / "scripts" / "install_triposr.ps1")
    return next((c for c in candidates if c.is_file()), None)


def selectable(text: str, role: str = "faint") -> QLabel:
    widget = label(text, role, wrap=True)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


class EnginesDialog(QDialog):
    def __init__(self, page, parent: QWidget | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.page = page
        self.manager = page.manager
        self.process: QProcess | None = None
        self.install_log: QPlainTextEdit | None = None
        self.key_inputs: dict[str, QLineEdit] = {}
        self.key_states: dict[str, QLabel] = {}
        self.status_labels: dict[str, QLabel] = {}
        self.setWindowTitle("Moteurs IA")
        self.resize(780, 660)
        layout = QVBoxLayout(self)
        self.tabs = LSTabs()
        layout.addWidget(self.tabs, 1)
        self.tabs.addTab(self._general(), "Général")
        for engine_id, adapter in self.manager.adapters.items():
            self.tabs.addTab(self._engine_tab(engine_id, adapter), adapter.info.name)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # --- Général ------------------------------------------------------------------------------
    def _general(self) -> QWidget:
        page = Page()
        config = self.manager.config
        section = page.section("Fonctionnement", "Réglages enregistrés hors des projets (aucune clé ici).")
        form = QFormLayout()
        self.mode = LSSelect(
            [("Automatique", "auto"), ("Local uniquement", "local"), ("Cloud uniquement", "cloud")]
        )
        self.mode.select_data(config.get("mode", "auto"))
        self.mode.currentIndexChanged.connect(
            lambda _i: self.manager.set_option("mode", self.mode.currentData())
        )
        form.addRow("Mode par défaut", self.mode)
        self.confirm_cloud = check(
            "Toujours confirmer avant un transfert cloud", bool(config.get("confirm_cloud", True))
        )
        self.confirm_cloud.toggled.connect(
            lambda value: self.manager.set_option("confirm_cloud", bool(value))
        )
        form.addRow("", self.confirm_cloud)
        self.timeout = spin(float(config.get("timeout_s") or 1800) / 60, 1, 240, 1, 0, " min")
        self.timeout.editingFinished.connect(
            lambda: self.manager.set_option("timeout_s", int(self.timeout.value() * 60))
        )
        form.addRow("Délai maximal d'une tâche", self.timeout)
        self.max_credits = spin(float(config.get("max_credits") or 0), 0, 10000, 5, 0, " crédits")
        self.max_credits.setSpecialValueText("aucun plafond")
        self.max_credits.editingFinished.connect(
            lambda: self.manager.set_option("max_credits", self.max_credits.value() or None)
        )
        form.addRow("Plafond de coût", self.max_credits)
        section.body.addLayout(form)
        cache = page.section("Cache et fichiers temporaires", str(self.manager.cache_dir))
        self.cache_label = label("", "faint")
        cache.body.addWidget(self.cache_label)
        cache.row(
            button("Nettoyer (plus de 7 jours)", "trash-2", lambda: self.clean_cache(7)),
            button("Tout nettoyer", "trash-2", lambda: self.clean_cache(0)),
        )
        self._update_cache()
        engines = page.section("Emplacement des moteurs locaux", "Variable LSFCARS_ENGINES pour le modifier.")
        engines.body.addWidget(selectable(str(self.manager.engines_dir)))
        page.finish()
        return page

    def _update_cache(self) -> None:
        self.cache_label.setText(f"Taille actuelle : {self.manager.cache_size() / 2**20:.1f} Mo")

    def clean_cache(self, days: float) -> None:
        if self.manager.queue.active():
            self.page.notify("Cache", "Une tâche est en cours : nettoyage reporté.", "warning")
            return
        removed = self.manager.cleanup(days)
        self._update_cache()
        self.page.notify("Cache", f"{removed} dossier(s) temporaire(s) supprimé(s).", "info")

    # --- Moteurs ------------------------------------------------------------------------------
    def _engine_tab(self, engine_id: str, adapter) -> QWidget:  # type: ignore[no-untyped-def]
        page = Page()
        info = adapter.info
        about = page.section(info.name, f"{info.method_label} · {info.kind}")
        capabilities = ", ".join(c.label for c in sorted(info.capabilities, key=lambda c: c.value))
        lines = [
            f"Version : {info.version}",
            f"Capacités : {capabilities}",
            f"Entrées : {', '.join(info.input_formats)} · Sorties : {', '.join(info.output_formats)}",
            f"Ressources : {info.resources}",
            f"Authentification : {info.auth}",
            f"Limites : {', '.join(f'{k} = {v}' for k, v in info.limits.items()) or '—'}",
            f"Coût : {info.cost}",
            f"Licence : {info.license}",
            f"Vérification : {info.verification}",
        ]
        if info.docs_url:
            lines.append(f"Documentation : {info.docs_url}")
        about.body.addWidget(selectable("\n".join(lines), "muted"))
        status = page.section("État")
        availability = self.manager.availability.get(engine_id)
        text = f"{availability.status.label} — {availability.message}" if availability else "Non détecté."
        self.status_labels[engine_id] = selectable(text)
        status.body.addWidget(self.status_labels[engine_id])
        status.row(
            button(
                "Tester", "refresh-cw", lambda e=engine_id: self.test(e), "Appel gratuit (état, solde, liste)"
            )
        )
        settings = page.section("Configuration")
        form = QFormLayout()
        stored = self.manager.config["engines"].get(engine_id, {})
        if engine_id == "triposr":
            root = LSInput("Dossier du moteur")
            root.setText(str(adapter.root))
            root.editingFinished.connect(
                lambda: self.manager.configure_engine("triposr", {"root": root.text().strip()})
            )
            form.addRow("Dossier", root)
            settings.body.addLayout(form)
            settings.row(
                button(
                    "Installer…",
                    "download",
                    self.install_triposr,
                    "Téléchargements listés avant confirmation",
                )
            )
            self.install_log = QPlainTextEdit()
            self.install_log.setReadOnly(True)
            self.install_log.setMaximumHeight(140)
            settings.body.addWidget(self.install_log)
        elif engine_id == "comfyui":
            url = LSInput("http://127.0.0.1:8188")
            url.setText(stored.get("url", ""))
            url.editingFinished.connect(
                lambda: self.manager.configure_engine("comfyui", {"url": url.text().strip()})
            )
            form.addRow("Adresse", url)
            workflow = LSInput("Workflow au format API (.json)")
            workflow.setText(stored.get("workflow", ""))
            workflow.editingFinished.connect(
                lambda: self.manager.configure_engine("comfyui", {"workflow": workflow.text().strip()})
            )
            form.addRow("Workflow", workflow)
            settings.body.addLayout(form)
            settings.row(
                button("Choisir le workflow…", "folder-open", lambda: self.choose_workflow(workflow))
            )
            settings.body.addWidget(
                selectable(
                    "Exportez votre workflow avec « Save (API) ». Il doit contenir un nœud LoadImage et "
                    "produire un maillage (GLB, glTF, OBJ ou PLY). Les nœuds et modèles restent ceux que "
                    "vous installez dans "
                    "ComfyUI, sous leurs licences."
                )
            )
        elif engine_id in KEY_PROVIDERS:
            key = QLineEdit()
            key.setEchoMode(QLineEdit.EchoMode.Password)
            key.setPlaceholderText("Clé API (jamais enregistrée dans un projet)")
            self.key_inputs[engine_id] = key
            form.addRow("Clé API", key)
            self.key_states[engine_id] = label("", "faint")
            form.addRow("", self.key_states[engine_id])
            self._update_key_state(engine_id)
            if engine_id == "anthropic":
                model = LSInput("claude-opus-5-5")
                model.setText(stored.get("model", ""))
                model.editingFinished.connect(
                    lambda: self.manager.configure_engine("anthropic", {"model": model.text().strip()})
                )
                form.addRow("Modèle", model)
            settings.body.addLayout(form)
            settings.row(
                button(
                    "Enregistrer la clé",
                    "save",
                    lambda e=engine_id: self.save_key(e),
                    "Coffre Windows (DPAPI)",
                ),
                button("Supprimer la clé", "trash-2", lambda e=engine_id: self.delete_key(e)),
            )
            settings.body.addWidget(
                selectable(
                    f"Variable d'environnement possible : {secrets_mod.env_name(engine_id)}. "
                    "Chaque opération "
                    "facturée demande votre confirmation ; aucune image n'est envoyée sans votre accord."
                )
            )
        else:
            settings.body.addWidget(label("Aucun réglage : moteur intégré à l'application.", "faint"))
        page.finish()
        return page

    def _update_key_state(self, provider: str) -> None:
        source = self.manager.secrets.source(provider)
        current = self.manager.secrets.get(provider) if source else None
        self.key_states[provider].setText(
            f"Clé enregistrée : {secrets_mod.masked(current)} ({source})" if current else "Aucune clé."
        )

    def test(self, engine_id: str) -> None:
        availability = self.manager.test_connection(engine_id)
        widget = self.status_labels.get(engine_id)
        if widget is not None:
            widget.setText(f"{availability.status.label} — {availability.message}")
        self.page.after_detection()

    def choose_workflow(self, field: LSInput) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Workflow ComfyUI (format API)", "", "JSON (*.json)")
        if path:
            field.setText(path)
            self.manager.configure_engine("comfyui", {"workflow": path})

    def save_key(self, provider: str) -> None:
        field = self.key_inputs[provider]
        try:
            self.manager.secrets.set(provider, field.text())
        except AIError as exc:
            QMessageBox.warning(self, "Clé API", str(exc))
            return
        field.clear()
        self._update_key_state(provider)
        self.page.notify("Clé API", "Clé enregistrée dans le coffre Windows.", "success")
        self.test(provider)

    def delete_key(self, provider: str) -> None:
        if self.manager.secrets.delete(provider):
            self.page.notify("Clé API", "Clé supprimée du coffre.", "info")
        self._update_key_state(provider)
        self.test(provider)

    def install_triposr(self) -> None:
        script = install_script()
        if script is None or self.install_log is None:
            QMessageBox.information(
                self, "TripoSR", "Script d'installation introuvable (scripts/install_triposr.ps1)."
            )
            return
        details = "\n".join(f"• {line}" for line in TRIPOSR_DOWNLOADS)
        answer = QMessageBox.question(
            self,
            "Installer TripoSR",
            f"Les fichiers suivants seront téléchargés dans\n{self.manager.engines_dir / 'triposr'} :\n\n"
            f"{details}\n\n"
            "Total : environ 5 à 6 Go. Rien n'est ajouté à l'application ni à vos projets. Continuer ?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        log = self.install_log
        process.readyReadStandardOutput.connect(
            lambda: log.appendPlainText(
                bytes(process.readAllStandardOutput()).decode("utf-8", "replace").rstrip()
            )
        )
        process.finished.connect(lambda code, _status: self._installed(code))
        process.start(
            "powershell",
            [
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-EnginesDir",
                str(self.manager.engines_dir),
            ],
        )
        self.process = process

    def _installed(self, code: int) -> None:
        if self.install_log is not None:
            self.install_log.appendPlainText(f"Terminé (code {code}).")
        self.manager.availability.pop("triposr", None)
        adapter = self.manager.adapters.get("triposr")
        if adapter is not None:
            adapter._probe = None  # nouvelle détection des versions installées
        self.test("triposr")
