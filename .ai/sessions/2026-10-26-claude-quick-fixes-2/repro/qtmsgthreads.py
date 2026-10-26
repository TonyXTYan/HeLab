"""Diagnostic: record each Qt message pytest-qt's handler gets, with its thread and the test phase."""
import sys, threading
import pytest
from pytestqt import logging as qtlogging

SEEN = []
PHASE = ["?"]
original = qtlogging._QtMessageCapture._handle_with_context

def handle(self, msg_type, context, message):
    SEEN.append((PHASE[0], threading.current_thread().name, str(msg_type), message[:160]))
    return original(self, msg_type, context, message)

qtlogging._QtMessageCapture._handle_with_context = handle

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item):
    PHASE[0] = f"setup {item.name}"; yield

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    PHASE[0] = f"call {item.name}"; yield

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item):
    PHASE[0] = f"teardown {item.name}"; yield
    PHASE[0] = "after"

def pytest_sessionfinish(session):
    for row in SEEN:
        sys.stderr.write("QTMSG %s | %s | %s | %s\n" % row)
