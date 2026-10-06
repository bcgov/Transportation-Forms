"""Regression checks for the proxy IP policy and Route gates."""

import os
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class CaddyPolicyTests(unittest.TestCase):
    def test_denials_abort_before_site_handlers(self):
        caddyfile = (ROOT / "apps" / "frontend" / "Caddyfile").read_text(
            encoding="utf-8"
        )
        entrypoint = (ROOT / "apps" / "frontend" / "entrypoint.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("order abort before handle", caddyfile)
        self.assertIn("abort @missing_xff", entrypoint)
        self.assertIn("abort @unlisted", entrypoint)
        self.assertIn("@unlisted not client_ip", entrypoint)
        self.assertNotIn("respond @missing_xff", entrypoint)
        self.assertNotIn("respond @unlisted", entrypoint)


class CIDRValidationTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "Run Bash checks inside WSL")
    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    def test_accepts_ipv4_addresses_and_ranges(self):
        result = subprocess.run(
            [
                "bash",
                "-c",
                '. apps/shared/ip-access.sh; ip_access_validate_file <(printf "%s" "$1") /dev/stdout',
                "--",
                "142.22.0.0/16\r\n\n10.0.0.1\n",
            ],
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "142.22.0.0/16\n10.0.0.1\n")

    @unittest.skipIf(os.name == "nt", "Run Bash checks inside WSL")
    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    def test_rejects_empty_invalid_and_directive_input(self):
        for candidate in (
            "",
            "1.2.3.4/33\n",
            "256.0.0.1\n",
            "10.0.0.0/8\nallow all;\n",
        ):
            with self.subTest(candidate=candidate):
                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        '. apps/shared/ip-access.sh; ip_access_validate_file <(printf "%s" "$1") /dev/null',
                        "--",
                        candidate,
                    ],
                    text=True,
                    capture_output=True,
                    cwd=ROOT,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)


class RoutePolicyTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("helm"), "Helm is required")
    def test_enabled_policy_mounts_both_secret_lists(self):
        for chart in ("frontend", "public-frontend"):
            with self.subTest(chart=chart):
                command = [
                    "helm",
                    "template",
                    "ipcheck",
                    str(ROOT / "infra" / "charts" / chart),
                    "--show-only",
                    "templates/deployment.yaml",
                    "--set",
                    "global.ipAccess.enabled=true",
                    "--set-string",
                    "global.ipAccess.existingSecret=ip-access-policy",
                    "--set-string",
                    "global.ipAccess.routeProxyCidrs=142.34.53.0/24 142.34.226.0/24",
                ]
                rendered = subprocess.run(
                    command, text=True, capture_output=True, check=False
                )
                self.assertEqual(rendered.returncode, 0, rendered.stderr)
                for required in (
                    'secretName: "ip-access-policy"',
                    "key: trustedProxyCidrs",
                    "key: allowedClientCidrs",
                    "mountPath: /etc/ip-access",
                ):
                    self.assertIn(required, rendered.stdout)

    @unittest.skipUnless(shutil.which("helm"), "Helm is required")
    def test_active_frontend_routes_only_admit_reverse_proxies(self):
        for chart, route_switch in (
            ("frontend", []),
            ("public-frontend", ["--set", "route.enabled=true"]),
        ):
            with self.subTest(chart=chart):
                command = [
                    "helm",
                    "template",
                    "ipcheck",
                    str(ROOT / "infra" / "charts" / chart),
                    "--show-only",
                    "templates/route.yaml",
                    *route_switch,
                    "--set",
                    "global.ipAccess.enabled=true",
                    "--set-string",
                    "global.ipAccess.routeProxyCidrs=142.34.53.0/24 142.34.226.0/24",
                    "--set-string",
                    "global.ipAccess.existingSecret=ip-access-policy",
                ]
                rendered = subprocess.run(
                    command, text=True, capture_output=True, check=False
                )
                self.assertEqual(rendered.returncode, 0, rendered.stderr)
                self.assertIn(
                    'haproxy.router.openshift.io/ip_whitelist: "142.34.53.0/24 142.34.226.0/24"',
                    rendered.stdout,
                )
                self.assertNotIn("142.34.0.0/16", rendered.stdout)

                command[command.index("global.ipAccess.enabled=true")] = (
                    "global.ipAccess.enabled=false"
                )
                disabled = subprocess.run(
                    command, text=True, capture_output=True, check=False
                )
                self.assertEqual(disabled.returncode, 0, disabled.stderr)
                self.assertNotIn("ip_whitelist", disabled.stdout)


if __name__ == "__main__":
    unittest.main()