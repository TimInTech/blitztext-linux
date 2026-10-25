"""Update UI behavior using a real background job and an isolated fake service."""
import os
import threading
import time
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.environ.get('WHISPER_GUI_TESTS') != '1', reason='GUI tests')

@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def drain(qapp, predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.005)
    assert predicate()


class Service:
    def __init__(self):
        self.release = SimpleNamespace(version='9.0.0')
        self.calls = []
        self.error = None

    def check_for_update(self, version):
        self.calls.append(('check', threading.get_ident()))
        if self.error:
            raise RuntimeError(self.error)
        return self.release

    def install_release(self, release):
        self.calls.append(('install', threading.get_ident()))
        return '/isolated/release'


def test_check_then_install_runs_off_gui_thread(qapp):
    from app.update_widget import UpdateWidget
    service = Service()
    widget = UpdateWidget(service=service)
    assert not widget.install_button.isEnabled()
    widget.check_button.click()
    drain(qapp, lambda: widget.install_button.isEnabled())
    assert '9.0.0' in widget.status_label.text()
    widget.install_button.click()
    drain(qapp, lambda: widget._job is None)
    assert [call[0] for call in service.calls] == ['check', 'install']
    assert all(call[1] != threading.get_ident() for call in service.calls)
    assert not widget.install_button.isEnabled()
    assert not widget.check_button.isEnabled()
    assert '9.0.0' in widget.status_label.text()
    widget.deleteLater()


def test_check_failure_allows_retry_without_stale_install(qapp):
    from app.update_widget import UpdateWidget
    service = Service()
    widget = UpdateWidget(service=service)
    widget.check_button.click()
    drain(qapp, lambda: widget.install_button.isEnabled())
    service.error = 'offline'
    widget.check_button.click()
    drain(qapp, lambda: widget._job is None)
    assert widget.check_button.isEnabled()
    assert not widget.install_button.isEnabled()
    assert 'offline' in widget.status_label.text()
    widget.deleteLater()


def test_latest_version_does_not_offer_install(qapp):
    from app.update_widget import UpdateWidget
    service = Service()
    service.release = None
    widget = UpdateWidget(service=service)
    widget.check_button.click()
    drain(qapp, lambda: widget._job is None)
    assert not widget.install_button.isEnabled()
    assert widget.check_button.isEnabled()
    widget.deleteLater()


def test_destroy_widget_during_job_is_safe(qapp):
    from PyQt6 import sip
    from app.update_widget import UpdateWidget
    started, release, ended = threading.Event(), threading.Event(), threading.Event()
    class SlowService(Service):
        def check_for_update(self, version):
            started.set()
            release.wait(2)
            ended.set()
            return None
    widget = UpdateWidget(service=SlowService())
    widget.check_button.click()
    assert started.wait(1)
    sip.delete(widget)
    release.set()
    drain(qapp, ended.is_set)
    qapp.processEvents()


def test_reopened_widget_shares_running_install_and_result(qapp):
    from PyQt6 import sip
    from app.update_widget import UpdateWidget
    started, finish = threading.Event(), threading.Event()
    class SlowService(Service):
        def install_release(self, release):
            self.calls.append(('install', threading.get_ident()))
            started.set()
            finish.wait(2)
            return '/isolated/release'
    service = SlowService()
    first = UpdateWidget(service=service)
    first.check_button.click()
    drain(qapp, lambda: first.install_button.isEnabled())
    first.install_button.click()
    assert started.wait(1)
    controller = first._controller
    sip.delete(first)
    second = UpdateWidget(controller=controller)
    assert not second.check_button.isEnabled()
    assert not second.install_button.isEnabled()
    second.install_button.click()
    finish.set()
    drain(qapp, lambda: second._job is None)
    assert [x[0] for x in service.calls].count('install') == 1
    assert '9.0.0' in second.status_label.text()
    second.deleteLater()
