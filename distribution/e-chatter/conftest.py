"""Independent Qt fixture; never imports the workbench application."""
import pytest


@pytest.fixture(scope="session")
def qt_app():
    from ai_workbench.e_chatter.app import create_application
    return create_application()
