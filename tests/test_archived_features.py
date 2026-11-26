import ast
import unittest
from pathlib import Path


BOT_SOURCE = (Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8")


class ArchivedFeatureTests(unittest.TestCase):
    def test_crossword_and_puzzle_are_not_exposed_in_active_menus_or_handlers(self):
        self.assertNotIn("[BTN_SLIDE, BTN_CROSS]", BOT_SOURCE)
        self.assertNotIn("        [BTN_TASK],", BOT_SOURCE)
        self.assertNotIn('CommandHandler(["krossvord", "crossword"], crossword_command)', BOT_SOURCE)
        self.assertNotIn('CallbackQueryHandler(cw_callback, pattern=r"^cw:")', BOT_SOURCE)
        self.assertNotIn("MessageHandler(filters.StatusUpdate.WEB_APP_DATA, puzzle_webapp_data)", BOT_SOURCE)
        self.assertNotIn("cw_match = re.match(", BOT_SOURCE)

    def test_active_menu_contains_only_logistics_and_education_at_top_level(self):
        tree = ast.parse(BOT_SOURCE)
        functions = {
            node.name: ast.get_source_segment(BOT_SOURCE, node)
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        collapsed = functions["collapsed_menu"]
        teacher = functions["teacher_menu"]
        student = functions["student_menu"]
        self.assertIn("rows.append([BTN_EDU])", collapsed)
        self.assertIn("rows.append([BTN_SUPPLY])", collapsed)
        for menu in (teacher, student):
            self.assertNotIn("BTN_CROSS", menu)
            self.assertNotIn("BTN_TASK", menu)

    def test_museum_is_not_registered_as_an_active_bot_feature(self):
        self.assertNotIn("museum.install(app)", BOT_SOURCE)
        self.assertNotIn("museum.on_text(update, context, text, _is_btn)", BOT_SOURCE)
        self.assertNotIn("museum.on_media(update, context)", BOT_SOURCE)

    def test_archived_feature_storage_keys_are_preserved(self):
        self.assertIn('CW_APP_FILE = "cw_app_store.json"', BOT_SOURCE)
        self.assertIn('PUZZLE_FILE = "puzzle_results.json"', BOT_SOURCE)


if __name__ == "__main__":
    unittest.main()
