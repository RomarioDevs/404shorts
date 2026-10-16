"""Application entry point."""

import logging
import sys

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from cortaflow.config import AppConfig
from cortaflow.logging_config import configure_logging
from cortaflow.infrastructure.database import (
    get_setting,
    initialize_database,
    recover_interrupted_tasks,
)
from cortaflow.infrastructure.certificates import configure_system_certificates
from cortaflow.services.media_previews import (
    clear_media_preview_cache,
    stop_and_clear_media_preview_cache,
)
from cortaflow.ui.main_window import MainWindow


def main() -> int:
    """Start the desktop application."""
    clear_media_preview_cache()
    config = AppConfig()
    config.ensure_directories()
    configure_system_certificates(config.cache_dir / "certificates")
    configure_logging(config.log_dir)
    connection = initialize_database(config.data_dir / "cortaflow.db")
    try:
        task_limit = int(get_setting(connection, "max_concurrent_tasks", config.max_concurrent_tasks))
        recover_interrupted_tasks(connection)
    finally:
        connection.close()
    logging.getLogger(__name__).info("Aplicação iniciada")

    app = QApplication(sys.argv)
    app.setApplicationName(config.app_name)
    app.setOrganizationName(config.organization)
    app.aboutToQuit.connect(stop_and_clear_media_preview_cache)
    QThreadPool.globalInstance().setMaxThreadCount(max(1, min(8, task_limit)))
    window = MainWindow()
    if "--smoke-test" in sys.argv:
        logging.getLogger(__name__).info("Smoke test concluído")
        return 0
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
