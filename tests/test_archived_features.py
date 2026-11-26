from pathlib import Path


BOT_SOURCE = (Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8")


def test_crossword_and_puzzle_are_not_exposed_in_active_menus_or_handlers():
    assert "[BTN_SLIDE, BTN_CROSS]" not in BOT_SOURCE
    assert "        [BTN_TASK]," not in BOT_SOURCE
    assert 'CommandHandler(["krossvord", "crossword"], crossword_command)' not in BOT_SOURCE
    assert 'CallbackQueryHandler(cw_callback, pattern=r"^cw:")' not in BOT_SOURCE
    assert "MessageHandler(filters.StatusUpdate.WEB_APP_DATA, puzzle_webapp_data)" not in BOT_SOURCE
    assert "cw_match = re.match(" not in BOT_SOURCE


def test_museum_is_not_registered_as_an_active_bot_feature():
    assert "museum.install(app)" not in BOT_SOURCE
    assert "museum.on_text(update, context, text, _is_btn)" not in BOT_SOURCE
    assert "museum.on_media(update, context)" not in BOT_SOURCE


def test_archived_feature_data_keys_are_preserved():
    assert 'CW_APP_FILE = "cw_app_store.json"' in BOT_SOURCE
    assert 'PUZZLE_FILE = "puzzle_results.json"' in BOT_SOURCE
    assert 'museum_data' not in BOT_SOURCE  # storage key remains derived from museum.py, not bot.py
