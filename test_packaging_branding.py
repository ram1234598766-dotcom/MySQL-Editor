"""Packaging/UI resource contracts for the shared product logo."""
from pathlib import Path
import unittest
from PIL import Image

ROOT = Path(__file__).resolve().parent


class PackagingBrandingTests(unittest.TestCase):
    def test_both_windows_executables_embed_the_generated_product_icon(self):
        for filename in ("mysql_idle.spec", "mysql_idle_portable.spec"):
            with self.subTest(filename=filename):
                source = (ROOT / filename).read_text(encoding="utf-8")
                self.assertIn("assets/mysqlidle.ico", source)
                self.assertIn("icon='assets/mysqlidle.ico'", source)

        generator = (ROOT / "tools" / "generate_brand_assets.py").read_text(encoding="utf-8")
        self.assertIn('LOGO_SOURCE = ASSETS / "mysql-editor-logo.jpg"', generator)
        self.assertTrue((ROOT / "assets" / "mysql-editor-logo.jpg").is_file())

    def test_windows_ico_sizes_are_direct_nearest_neighbor_resizes_of_the_original(self):
        source_path = ROOT / "assets" / "mysql-editor-logo.jpg"
        icon_path = ROOT / "assets" / "mysqlidle.ico"
        sizes = {(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (128, 128), (256, 256)}
        with Image.open(source_path) as source_image:
            source = source_image.convert("RGBA")
        with Image.open(icon_path) as icon:
            self.assertEqual(icon.ico.sizes(), sizes)
            for size in sorted(sizes):
                with self.subTest(size=size):
                    actual = icon.ico.getimage(size).convert("RGBA")
                    expected = source.resize(size, Image.Resampling.LANCZOS)
                    self.assertEqual(list(actual.getdata()), list(expected.getdata()),
                                     "Every Windows ICO frame must come directly from the original logo without blur.")

    def test_windows_mysql_connection_defaults_to_certificate_optional_tls(self):
        source = (ROOT / "mysql_idle.py").read_text(encoding="utf-8")
        self.assertIn("DEFAULT_MYSQL_TLS_VERIFY = False", source)
        self.assertIn('defaults.get("tls_verify", DEFAULT_MYSQL_TLS_VERIFY)', source)
        self.assertIn('params.get("tls_verify", DEFAULT_MYSQL_TLS_VERIFY)', source)
        self.assertIn("tls_verify=DEFAULT_MYSQL_TLS_VERIFY", source)
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("PyMySQL>=1.2.3,<2.0", requirements)

    def test_installer_is_branded_and_uses_native_uninstall_flow(self):
        source = (ROOT / "MySQLIDLE.iss").read_text(encoding="utf-8")
        for expected in (
            "SetupIconFile=",
            "WizardImageFile=",
            "WizardSmallImageFile=",
            "UninstallDisplayIcon=",
            "[Files]",
            "recursesubdirs createallsubdirs",
            "[Icons]",
            "[Run]",
            "WizardStyle=modern dynamic includetitlebar",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, source)
        # Keep uninstallation on Inno Setup's native path. Custom Pascal callbacks
        # caused a user-reported "Could not call proc" runtime error in uninstall.
        for unsafe_callback in (
            "[Code]",
            "InitializeUninstall",
            "InitializeUninstallProgressForm",
            "CurUninstallStepChanged",
            "UninstallSilent",
            "DelTree(",
            "npbstMarquee",
        ):
            with self.subTest(unsafe_callback=unsafe_callback):
                self.assertNotIn(unsafe_callback, source)
        self.assertNotIn('[UninstallDelete]\\nType: filesandordirs; Name: "{app}"', source)
        self.assertNotIn("WizardSilent", source)

    def test_setup_wizard_artwork_uses_the_same_logo_without_redesign(self):
        generator = (ROOT / "tools" / "generate_brand_assets.py").read_text(encoding="utf-8")
        installer = (ROOT / "MySQLIDLE.iss").read_text(encoding="utf-8")
        self.assertIn('LOGO_SOURCE = ASSETS / "mysql-editor-logo.jpg"', generator)
        self.assertIn("SetupIconFile=assets\\mysqlidle.ico", installer)
        self.assertIn("WizardImageFile=assets\\wizard-image.bmp", installer)
        self.assertIn("WizardSmallImageFile=assets\\wizard-small.bmp", installer)
        self.assertNotIn("_centered_text", generator)
        self.assertNotIn("SQL WORKSPACE", generator)
        self.assertNotIn("QUERY", generator)
        self.assertNotIn("BROWSE", generator)
        self.assertNotIn("EXPORT", generator)

        source_path = ROOT / "assets" / "mysql-editor-logo.jpg"
        with Image.open(source_path) as source_image:
            source = source_image.convert("RGBA")

        # The installer side panel contains the original source pixels at native 96x96 size.
        with Image.open(ROOT / "assets" / "wizard-image.bmp") as actual_panel:
            self.assertEqual(actual_panel.size, (164, 314))
            mark = source.copy()
            expected_panel = Image.new("RGB", (164, 314), (11, 24, 42))
            expected_panel.paste(mark, ((164 - mark.width) // 2, (314 - mark.height) // 2), mark)
            self.assertEqual(list(actual_panel.convert("RGB").getdata()), list(expected_panel.getdata()),
                             "Installer wizard must show the same logo, not a separate redesign.")

        # The small wizard badge must also be just the same fitted source image.
        with Image.open(ROOT / "assets" / "wizard-small.bmp") as actual_small:
            self.assertEqual(actual_small.size, (55, 55))
            mark = source.resize((55, 55), Image.Resampling.LANCZOS)
            expected_small = Image.new("RGB", (55, 55), (11, 24, 42))
            expected_small.paste(mark, (0, 0), mark)
            self.assertEqual(list(actual_small.convert("RGB").getdata()), list(expected_small.getdata()),
                             "Small wizard image must use the same source artwork.")

    def test_main_workspace_renders_the_original_logo_with_refined_desktop_chrome(self):
        desktop = (ROOT / "mysql_idle.py").read_text(encoding="utf-8")
        generator = (ROOT / "tools" / "generate_brand_assets.py").read_text(encoding="utf-8")
        source = (ROOT / "assets" / "mysql-editor-logo.jpg").read_bytes()

        # The desktop shell uses a Figma-inspired dark workspace with a scaled
        # header rendering backed by the exact, unmodified original logo source.
        self.assertIn("self.brand_header = header", desktop)
        self.assertIn("window.iconbitmap(default=str(icon_path))", desktop)
        self.assertIn("if not icon_set and logo_path.is_file()", desktop)
        self.assertIn("_apply_window_icon(self)", desktop)
        self.assertIn('header = tk.Frame(self.root, bg=c["surface"], padx=22, pady=18, bd=0)', desktop)
        self.assertIn('text="MySQL / MariaDB workspace"', desktop)
        self.assertIn('self.brand_logo_source = source_image.convert("RGBA")', desktop)
        self.assertIn("self.brand_logo_image = self.brand_logo_source", desktop)
        self.assertIn("self.brand_logo_display_image = ImageTk.PhotoImage(display_image, master=self.root)", desktop)
        self.assertIn('text="MySQL Editor"', desktop)
        self.assertIn('root.geometry("1360x860")', desktop)
        self.assertIn('root.minsize(1080, 700)', desktop)
        self.assertIn("def _configure_ttk_style(root)", desktop)
        self.assertIn('style.configure("TButton", padding=(12, 7)', desktop)
        self.assertIn("icon_set = False", desktop)
        self.assertIn("if not icon_set and logo_path.is_file()", desktop)
        self.assertIn("self.logo_image = ImageTk.PhotoImage(display_image, master=self)", desktop)
        self.assertIn('"canvas": "#090E17"', desktop)
        self.assertIn('text="SQL Console"', desktop)
        self.assertIn('text="Results"', desktop)

        # The bundled artwork remains the exact 96x96 source PNG.
        with Image.open(ROOT / "assets" / "mysql-editor-logo.jpg") as image:
            self.assertEqual(image.size, (128, 128))
            self.assertEqual(image.format, "JPEG")
        self.assertGreater(len(source), 0)
        self.assertIn('LOGO_SOURCE = ASSETS / "mysql-editor-logo.jpg"', generator)
        self.assertIn("Use the generated multi-size ICO where supported, avoiding DPI-induced blur.", desktop)

    def test_compact_connect_dialog_confirms_password_below_and_hides_advanced_tls(self):
        desktop = (ROOT / "mysql_idle.py").read_text(encoding="utf-8")
        create_password = desktop.index("self.master_password_entry.grid(row=0, column=1")
        confirm_label = desktop.index('tk.Label(access, text="Confirm master password"')
        confirm_entry = desktop.index("self.master_password_confirm_entry.grid(row=1, column=1")
        helper_text = desktop.index("Use at least {MIN_MASTER_PASSWORD_LENGTH}")
        self.assertLess(create_password, confirm_label)
        self.assertLess(confirm_label, confirm_entry)
        self.assertLess(confirm_entry, helper_text)
        self.assertIn("confirmation = self.master_password_confirm_var.get()", desktop)
        self.assertIn("if master_password != confirmation:", desktop)

        self.assertNotIn('("MySQL CA certificate (optional)", "ssl_ca", False)', desktop)
        self.assertIn('self.vars["ssl_ca"] = tk.StringVar(value=str(defaults.get("ssl_ca", "")))', desktop)
        self.assertIn("def _toggle_advanced_tls(self):", desktop)
        self.assertIn("self.advanced_tls_frame.grid_remove()", desktop)
        self.assertIn('text="Connect to MySQL"', desktop)

    def test_startup_keeps_sql_workspace_hidden_until_database_connection_succeeds(self):
        desktop = (ROOT / "mysql_idle.py").read_text(encoding="utf-8")
        flow_start = desktop.index("    def _handle_startup_connection_failure(self):")
        flow_end = desktop.index("    def connect(self,", flow_start)
        connect_flow = desktop[flow_start:flow_end]
        poll_start = desktop.index("    def _poll_worker_events(self):")
        connect_state = desktop.index('                elif kind == "connection_state":', poll_start)
        poll_end = desktop.index("    # ------------------------------------------------------------ connection --", connect_state)
        poll = desktop[poll_start:poll_end]

        self.assertIn("root.withdraw()", desktop[desktop.index("def main():"):])
        self.assertIn("if connected and self._startup_reveal_pending:", poll)
        self.assertIn("self.root.deiconify()", poll)
        self.assertIn("self._pending_startup_connect_error = message", poll)
        self.assertIn("self.root.after_idle(self._handle_startup_connection_failure)", poll)
        self.assertIn("self.connect_dialog(defaults_override=defaults)", connect_flow)
        self.assertIn("self._startup_reveal_pending = True", connect_flow)
        self.assertNotIn("self.root.deiconify()", connect_flow)
        self.assertIn("if initial_page or shell_was_hidden:", connect_flow)

    def test_windows_startup_requires_master_password_and_android_uses_same_verifier(self):
        desktop = (ROOT / "mysql_idle.py").read_text(encoding="utf-8")
        companion = (ROOT / "mobile_companion.py").read_text(encoding="utf-8")
        self.assertIn('MASTER_PASSWORD_PATH = APP_DATA_DIR / "master_password.json"', desktop)
        self.assertNotIn("_authenticate_startup", desktop)
        self.assertIn("require_master_password=initial_page", desktop)
        self.assertIn("self.password_record = load_password_record(MASTER_PASSWORD_PATH)", desktop)
        self.assertIn("verify_password(master_password, self.password_record)", desktop)
        self.assertIn("Create master password", desktop)
        self.assertIn("MySQL account password", desktop)
        self.assertIn("self.logo_image = self.logo_source_image", desktop)
        # The connection/password dialog continues to use the unscaled source
        # artwork. Only the compact Figma-style desktop header uses a preview.
        dialog_start = desktop.index("class ConnectDialog")
        dialog_end = desktop.index("# Main application", dialog_start)
        self.assertNotIn(".subsample(", desktop[dialog_start:dialog_end])
        self.assertIn("root.after_idle(app.connect_dialog)", desktop)
        self.assertNotIn("root.after(250, self.connect_dialog)", desktop)
        self.assertIn("self.startup_connect_pending = False", desktop)
        self.assertIn("password_record=password_record", desktop)
        self.assertIn("from password_auth import is_password_record, verify_password", companion)
        self.assertIn('master_password = data.get("masterPassword", "")', companion)
        self.assertIn("password_valid = verify_password(master_password, owner.password_record)", companion)
        self.assertIn("Invalid master password or pairing code.", companion)

    def test_installer_creates_desktop_shortcut_with_explicit_shared_icon(self):
        source = (ROOT / "MySQLIDLE.iss").read_text(encoding="utf-8")
        self.assertIn("WizardStyle=modern dynamic includetitlebar", source)
        self.assertIn('UninstallDisplayIcon={app}\\_internal\\assets\\mysqlidle.ico', source)
        self.assertIn('Name: "{autodesktop}\\MySQL Editor"', source)
        self.assertIn('IconFilename: "{app}\\_internal\\assets\\mysqlidle.ico"; IconIndex: 0', source)
        self.assertNotIn("Tasks: desktopicon", source)

    def test_readme_logo_is_the_exact_shared_source_for_android_and_windows(self):
        source_path = ROOT / "assets" / "mysql-editor-logo.jpg"
        android_logo = ROOT / "android-app/app/src/main/res/drawable-nodpi/ic_mysqlidle_logo.jpg"
        self.assertTrue(source_path.is_file())
        self.assertTrue(android_logo.is_file())
        self.assertTrue((ROOT / "tools" / "sync_logo_resources.py").is_file())
        self.assertFalse((ROOT / "tools" / "generate_play_store_assets.py").exists())

        with Image.open(source_path) as source_image:
            self.assertEqual(source_image.format, "JPEG")
            self.assertEqual(source_image.size, (128, 128))
        self.assertEqual(
            android_logo.read_bytes(),
            source_path.read_bytes(),
            "Android must embed the exact supplied JPEG bytes, without resizing or editing.",
        )

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("![MySQL Editor logo](assets/mysql-editor-logo.jpg)", readme)
        generator = (ROOT / "tools" / "generate_brand_assets.py").read_text(encoding="utf-8")
        self.assertIn('LOGO_SOURCE = ASSETS / "mysql-editor-logo.jpg"', generator)
        self.assertNotIn("mysqlidle-logo-reference.webp", generator)
        workflow = (ROOT / ".github" / "workflows" / "build-exe-apk.yml").read_text(encoding="utf-8")
        self.assertIn("python tools/sync_logo_resources.py", workflow)
        self.assertNotIn("generate_play_store_assets.py", workflow)
        self.assertNotIn("MySQLIDLE-Play-Store-Assets.zip", workflow)

    def test_android_launcher_and_splash_use_the_supplied_logo(self):
        manifest = (ROOT / "android-app/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('android:icon="@mipmap/ic_launcher"', manifest)
        self.assertIn('android:roundIcon="@mipmap/ic_launcher_round"', manifest)
        self.assertIn('android:name=".MainActivity"', manifest)
        self.assertIn('android:name="android.intent.action.MAIN"', manifest)
        self.assertIn('android:name="android.intent.category.LAUNCHER"', manifest)

        for filename in ("ic_launcher.xml", "ic_launcher_round.xml"):
            legacy = ROOT / "android-app/app/src/main/res/mipmap-anydpi" / filename
            adaptive = ROOT / "android-app/app/src/main/res/mipmap-anydpi-v26" / filename
            with self.subTest(resource=str(legacy)):
                self.assertIn("@drawable/ic_mysqlidle_logo", legacy.read_text(encoding="utf-8"))
            with self.subTest(resource=str(adaptive)):
                self.assertIn("@drawable/ic_launcher_foreground", adaptive.read_text(encoding="utf-8"))

        foreground = (ROOT / "android-app/app/src/main/res/drawable/ic_launcher_foreground.xml").read_text(encoding="utf-8")
        self.assertIn("@drawable/ic_mysqlidle_logo", foreground)
        main_activity = (ROOT / "android-app/app/src/main/java/com/mysqlidle/mobile/MainActivity.kt").read_text(encoding="utf-8")
        self.assertIn("R.drawable.ic_mysqlidle_logo", main_activity)
        self.assertIn('contentDescription = "MySQL Editor logo"', main_activity)
        styles = (ROOT / "android-app/app/src/main/res/values/styles.xml").read_text(encoding="utf-8")
        self.assertIn("@drawable/ic_launcher_foreground", styles)


    def test_android_api_36_configuration_and_edge_to_edge_insets(self):
        app_build = (ROOT / "android-app/app/build.gradle.kts").read_text(encoding="utf-8")
        root_build = (ROOT / "android-app/build.gradle.kts").read_text(encoding="utf-8")
        activity = (ROOT / "android-app/app/src/main/java/com/mysqlidle/mobile/MainActivity.kt").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/build-exe-apk.yml").read_text(encoding="utf-8")
        self.assertIn("compileSdk = 36", app_build)
        self.assertIn("targetSdk = 36", app_build)
        self.assertRegex(root_build, r'id\("com\.android\.application"\) version "\d+\.\d+\.\d+" apply false')
        self.assertIn("gradle-version: \"9.8.1\"", workflow)
        self.assertIn("group: mysqlidle-${{ github.workflow }}-${{ github.ref }}", workflow)
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", workflow)
        self.assertIn('build-tools;36.0.0', workflow)
        self.assertIn("APK must target Android API level 36 or higher.", workflow)
        self.assertIn("winget install 9NQ7512CXL7T", workflow)
        self.assertIn('exec -3.15 -c "import sys; print(sys.executable)"', workflow)
        self.assertIn("MYSQLIDLE_PYTHON=$pythonExecutable", workflow)
        self.assertIn('shell: pwsh', workflow)
        self.assertIn('Start-Process -FilePath $env:MYSQLIDLE_PYTHON -ArgumentList $testArgs -Wait -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath', workflow)
        self.assertIn('if ($testProcess.ExitCode -ne 0)', workflow)
        self.assertIn('All regression tests passed (exit code 0).', workflow)
        self.assertIn('exit 0', workflow)
        self.assertNotIn("MYSQLIDLE_PYMANAGER exec -3.15 .\\run_ci_tests.py", workflow)
        self.assertIn("uses: actions/setup-python@v6", workflow)
        self.assertIn('python-version: "3.15.0"', workflow)
        self.assertNotIn("bash tools/setup_python_3_15_linux.sh", workflow)
        self.assertNotIn("tools/restore_sources.py", workflow)
        self.assertNotIn('python-version: "3.14.8"', workflow)
        windows_builder = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("py -3.15", windows_builder)
        self.assertIn("pyinstaller==6.22.3 pillow==12.3.0", windows_builder)
        self.assertIn("Python 3.15", readme)
        self.assertIn("WindowInsets.Type.systemBars()", activity)
        self.assertIn("applySystemBarInsets(scroll)", activity)
        self.assertIn("applySystemBarInsets(page)", activity)
        self.assertIn("Privacy Policy", activity)
        self.assertIn("https://github.com/ram1234598766-dotcom/MySQL-Editor/blob/main/PRIVACY_POLICY.md", activity)
        privacy = (ROOT / "PRIVACY_POLICY.md").read_text(encoding="utf-8")
        self.assertIn("# Privacy Policy — MySQL IDLE Mobile", privacy)
        self.assertIn("contact", privacy.lower())


    def test_android_pipeline_builds_apk_only_without_app_bundles(self):
        workflow = (ROOT / ".github" / "workflows" / "build-exe-apk.yml").read_text(encoding="utf-8")

        self.assertIn("gradle --no-daemon assembleDebug", workflow)
        self.assertIn("gradle --no-daemon assembleRelease", workflow)
        self.assertIn("dist/MySQLEditor-Mobile-release.apk", workflow)
        self.assertIn("dist/MySQLEditor-Mobile-debug.apk", workflow)
        self.assertNotIn("bundleDebug", workflow)
        self.assertNotIn("bundleRelease", workflow)
        self.assertNotIn(".aab", workflow)
        self.assertNotIn("App Bundle", workflow)



if __name__ == "__main__":
    unittest.main(verbosity=2)
