from financial_bot import __version__
from financial_bot.app import APP_NAME


def test_project_metadata_is_importable() -> None:
    assert APP_NAME == "Family Finance Telegram Bot"
    assert __version__ == "0.1.0"
