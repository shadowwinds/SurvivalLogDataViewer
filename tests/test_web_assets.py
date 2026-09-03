from __future__ import annotations

import unittest
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


class WebAssetTests(unittest.TestCase):
    def test_achievement_navigation_and_detail_rendering_exist(self) -> None:
        index = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="categoryNav"', index)
        self.assertIn("/api/achievements", app)
        self.assertIn("encodeURIComponent(entryKey)", app)
        self.assertIn("完成条件", app)
        self.assertIn("角色限制", app)
        self.assertIn("achievement-visibility", app)

    def test_recipe_refresh_control_replaces_read_status(self) -> None:
        index = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
        styles = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="recipeSaveRefresh"', index)
        self.assertIn("存档更新", index)
        self.assertNotIn("recipeSaveStatus", index + app)
        self.assertNotIn("已读取", index + app + styles)
        self.assertIn("/api/recipe-plans/refresh", app)

    def test_recipe_lists_render_generic_results_before_rendering(self) -> None:
        app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

        self.assertNotIn("function visibleRecipeResults", app)
        self.assertIn("const matches = Array.isArray(save.matches) ? save.matches : [];", app)
        self.assertIn("const nearMatches = Array.isArray(save.near_matches) ? save.near_matches : [];", app)


if __name__ == "__main__":
    unittest.main()
