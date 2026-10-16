from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from cortaflow.ui.pages import editor_page
from cortaflow.ui.pages.editor_page import EditorPage


def test_editor_exposes_basic_playback_controls(qtbot, tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "fixtures" / "vídeo teste.mp4"
    page = EditorPage()
    qtbot.addWidget(page)

    page.load_media(source, fps=50.0)
    assert page.frame_duration_ms == 20
    assert "50 FPS" in page.status_label.text()
    page.rate.setCurrentIndex(3)
    assert page.player.playbackRate() == 2.0
    page.mute_button.setChecked(True)
    assert page.audio.isMuted()
    assert len(page.shortcuts) == 15


def test_export_selection_runs_in_worker(qtbot, monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    destination = tmp_path / "cut.mp4"
    source.write_bytes(b"source")

    def fake_export(source_path, destination_path, clip, progress, cancelled):
        assert source_path == source
        assert clip.start_ms == 100
        assert clip.end_ms == 1_000
        progress({"status": "processing"})
        destination_path.write_bytes(b"exported")
        return destination_path

    monkeypatch.setattr(editor_page, "export_clip", fake_export)
    monkeypatch.setattr(
        editor_page.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(destination), "Vídeo MP4 (*.mp4)"),
    )
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args, **kwargs: messages.append(str(args[2])),
    )

    page = EditorPage()
    qtbot.addWidget(page)
    page.source_path = source
    page.in_ms = 100
    page.out_ms = 1_000
    page.export_selection()

    assert not page.export_button.isEnabled()
    assert page.cancel_export_button.isEnabled()
    qtbot.waitUntil(lambda: page.export_worker is None, timeout=5_000)
    assert destination.read_bytes() == b"exported"
    assert page.export_button.isEnabled()
    assert messages and str(destination) in messages[0]
