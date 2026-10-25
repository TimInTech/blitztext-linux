"""Nonblocking release updates, independent of settings persistence."""
from __future__ import annotations

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

from app import __version__
from app.i18n import t

# Keep jobs alive even when their settings dialog is destroyed. Qt disconnects
# the receiver automatically; no worker ever accesses a widget directly.
_ACTIVE_JOBS: set = set()


class _Signals(QObject):
    result = pyqtSignal(object)
    error = pyqtSignal(str)


class _Job(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = _Signals()

    def run(self):
        try:
            self.signals.result.emit(self.operation())
        except Exception as exc:
            self.signals.error.emit(str(exc)[:400])
        finally:
            _ACTIVE_JOBS.discard(self)


class UpdateController(QObject):
    """Application-owned job and status survive closing the settings dialog."""
    changed = pyqtSignal()

    def __init__(self, service):
        super().__init__(QApplication.instance())
        self.service = service
        self.release = None
        self.job = None
        self.installing = False
        self.installed = False
        self.status = 'updates.ready'
        self.status_args = {}

    def _start(self, operation):
        job = _Job(operation)
        job.signals.result.connect(self._finished)
        job.signals.error.connect(self._failed)
        self.job = job
        _ACTIVE_JOBS.add(job)
        self.changed.emit()
        QThreadPool.globalInstance().start(job)

    @pyqtSlot()
    def check(self):
        if self.job is not None or self.installed:
            return
        self.release = None
        self.installing = False
        self.status, self.status_args = 'updates.checking', {}
        service = self.service
        self._start(lambda: service.check_for_update(__version__))

    @pyqtSlot()
    def install(self):
        if self.job is not None or self.release is None or self.installed:
            return
        self.installing = True
        self.status, self.status_args = 'updates.installing', {}
        service, release = self.service, self.release
        self._start(lambda: service.install_release(release))

    @pyqtSlot(object)
    def _finished(self, result):
        self.job = None
        if self.installing:
            self.installed = True
            self.status = 'updates.installed'
            self.status_args = {'version': self.release.version}
        else:
            self.release = result
            self.status = 'updates.available' if result else 'updates.current'
            self.status_args = {'version': result.version} if result else {}
        self.changed.emit()

    @pyqtSlot(str)
    def _failed(self, message):
        self.job = None
        self.status, self.status_args = 'updates.failed', {'error': message}
        self.changed.emit()


def _default_controller():
    app = QApplication.instance()
    controller = getattr(app, '_blitztext_update_controller', None)
    if controller is None:
        from app.update_service import UpdateService
        controller = UpdateController(UpdateService())
        app._blitztext_update_controller = controller
    return controller


class UpdateWidget(QWidget):
    def __init__(self, parent=None, *, service=None, controller=None):
        super().__init__(parent)
        self._controller = controller or (
            UpdateController(service) if service is not None else _default_controller()
        )
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(t('settings.version').format(version=__version__)))
        help_label = QLabel(t('updates.help'))
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        self.check_button = QPushButton(t('updates.check'))
        self.check_button.clicked.connect(self._controller.check)
        layout.addWidget(self.check_button)
        self.install_button = QPushButton(t('updates.install'))
        self.install_button.clicked.connect(self._controller.install)
        layout.addWidget(self.install_button)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setAccessibleName(t('updates.status'))
        layout.addWidget(self.status_label)
        layout.addStretch()
        self._controller.changed.connect(self._refresh)
        self._refresh()

    @property
    def _job(self):
        return self._controller.job

    @pyqtSlot()
    def _refresh(self):
        controller = self._controller
        idle = controller.job is None and not controller.installed
        self.check_button.setEnabled(idle)
        self.install_button.setEnabled(idle and controller.release is not None)
        self.status_label.setText(t(controller.status).format(**controller.status_args))
