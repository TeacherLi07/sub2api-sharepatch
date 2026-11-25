"""Patch scripts must reject upstream drift without partially writing a file."""

import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PatchAnchorTests(unittest.TestCase):
    def test_missing_or_ambiguous_regex_anchors_leave_source_unchanged(self):
        for name in ("apply-overlay", "apply-codex-customizations"):
            script = load_script(name)
            for source, count in (("unrelated source\n", 0), ("anchor\nanchor\n", 2)):
                with self.subTest(script=name, count=count), tempfile.TemporaryDirectory() as temp:
                    path = Path(temp) / "source.ts"
                    path.write_text(source)
                    with self.assertRaisesRegex(SystemExit, f"found {count}"):
                        script.patch_regex(path, r"^anchor$", "patched", "test", "patched")
                    self.assertEqual(path.read_text(), source)

    def test_payment_route_is_located_without_matching_its_arguments(self):
        overlay = load_script("apply-overlay")
        for call in ("\troutes.RegisterPaymentRoutes(v1, addedDependency)\n", "\troutes.RegisterPaymentRoutes(\n\t\tv1,\n\t)\n"):
            with self.subTest(call=call), tempfile.TemporaryDirectory() as temp:
                router = Path(temp) / "router.go"
                router.write_text(call)
                overlay.register_sharepatch_routes(router)
                overlay.register_sharepatch_routes(router)
                self.assertEqual(router.read_text().count("routes.RegisterSharepatchRoutes("), 1)
                self.assertTrue(router.read_text().endswith(call))

                router.write_text(call * 2)
                with self.assertRaisesRegex(SystemExit, "shared billing API route registration:.*found 2"):
                    overlay.register_sharepatch_routes(router)
                self.assertEqual(router.read_text(), call * 2)

    def test_ccswitch_model_anchor_accepts_new_models_and_ts_formatting(self):
        codex = load_script("apply-codex-customizations")
        source = (
            'import type {GroupPlatform} from "@/types";\n'
            'export const OPENAI_CC_SWITCH_CODEX_MODEL: string = "new-upstream-model";\n'
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ccswitchImport.ts"
            path.write_text(source)
            self.assertEqual(codex.patch_ccswitch_default_model(path), "new-upstream-model")
            updated = path.read_text()
            self.assertIn("import { CODEX_WEBSOCKET_DEFAULT_MODEL }", updated)
            self.assertIn("export const OPENAI_CC_SWITCH_CODEX_MODEL = CODEX_WEBSOCKET_DEFAULT_MODEL", updated)

            path.write_text(source * 2)
            with self.assertRaisesRegex(SystemExit, "default model declaration.*found 2"):
                codex.patch_ccswitch_default_model(path)
            self.assertEqual(path.read_text(), source * 2)

    def test_account_homepage_fixture_tracks_only_the_centered_row_layout(self):
        overlay = load_script("apply-overlay")
        old = "    expect(tooltip.classes()).toEqual(expect.arrayContaining(['self-start']))\n"
        layout = (
            '              <div class="flex items-center gap-1">\n'
            '                <HelpTooltip\n'
            '                  v-if="accountHomepageUrl(row)"\n'
            '                  :content="accountHomepageUrl(row)"\n'
            '                  width-class="w-max max-w-sm break-all"\n'
            '                  class="-ml-1"\n'
        )
        with tempfile.TemporaryDirectory() as temp:
            frontend = Path(temp)
            test = frontend / "views/admin/__tests__/AccountsView.sparkShadow.spec.ts"
            test.parent.mkdir(parents=True)
            view = frontend / "views/admin/AccountsView.vue"
            test.write_text(old)
            view.write_text(layout.replace('class="-ml-1"', 'class="-ml-1 self-start"'))
            overlay.fix_account_homepage_layout_test(frontend)
            self.assertEqual(test.read_text(), old)

            view.write_text(layout)
            overlay.fix_account_homepage_layout_test(frontend)
            updated = test.read_text()
            self.assertIn("['flex', 'items-center', 'gap-1']", updated)
            overlay.fix_account_homepage_layout_test(frontend)
            self.assertEqual(test.read_text(), updated)
            self.assertEqual(view.read_text(), layout)

            test.write_text(old * 2)
            with self.assertRaisesRegex(SystemExit, "expected one anchor.*found 2"):
                overlay.fix_account_homepage_layout_test(frontend)
            self.assertEqual(test.read_text(), old * 2)
            test.write_text(old)
            view.write_text(layout * 2)
            with self.assertRaisesRegex(SystemExit, "expected one centered row"):
                overlay.fix_account_homepage_layout_test(frontend)
            self.assertEqual(test.read_text(), old)

    def test_ultrafast_fixture_preserves_current_wording_and_valid_assertions(self):
        overlay = load_script("apply-overlay")
        old = '        ultrafastHint: expect.stringContaining("service_tier=ultrafast"),\n'
        with tempfile.TemporaryDirectory() as temp:
            frontend = Path(temp)
            test_file = frontend / "views/admin/__tests__/groupsOpenAIFast.spec.ts"
            test_file.parent.mkdir(parents=True)
            test_file.write_text(old)
            locales = [frontend / f"i18n/locales/{locale}/admin/overview.ts" for locale in ("zh", "en")]
            for locale in locales:
                locale.parent.mkdir(parents=True)
                locale.write_text("        ultrafastHint: 'Sets service_tier=ultrafast',\n")
            overlay.fix_ultrafast_locale_test(frontend)
            self.assertEqual(test_file.read_text(), old)

            translated = '        ultrafastHint: "选择已支持的加速档位",\n'
            locales[0].write_text(translated)
            overlay.fix_ultrafast_locale_test(frontend)
            self.assertIn("ultrafastHint: expect.any(String)", test_file.read_text())
            self.assertEqual(locales[0].read_text(), translated)


if __name__ == "__main__":
    unittest.main()
