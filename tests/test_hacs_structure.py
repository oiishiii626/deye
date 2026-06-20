"""Test HACS compatibility and file structure for the Deye Cloud integration.

Validates:
- Required files exist in custom_components/deye_cloud/
- manifest.json has correct fields and semver version
- hacs.json has required fields
- strings.json and translations/en.json have matching structure
- All platform files exist
- services.yaml exists

Validates: Requirements 17.1, 17.2, 17.3, 17.4
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# Root of the integration directory
INTEGRATION_DIR = Path(__file__).parent.parent / "custom_components" / "deye_cloud"


class TestRequiredFiles:
    """Test that all required files exist in the integration directory."""

    REQUIRED_FILES = [
        "__init__.py",
        "manifest.json",
        "config_flow.py",
        "strings.json",
        "hacs.json",
        "sensor.py",
        "binary_sensor.py",
        "number.py",
        "select.py",
        "switch.py",
        "time.py",
        "event.py",
        "services.yaml",
    ]

    def test_integration_directory_exists(self):
        """Verify the integration directory exists."""
        assert INTEGRATION_DIR.exists(), (
            f"Integration directory not found: {INTEGRATION_DIR}"
        )
        assert INTEGRATION_DIR.is_dir()

    @pytest.mark.parametrize("filename", REQUIRED_FILES)
    def test_required_file_exists(self, filename: str):
        """Verify each required file exists."""
        filepath = INTEGRATION_DIR / filename
        assert filepath.exists(), f"Required file missing: {filename}"
        assert filepath.is_file()

    def test_translations_directory_exists(self):
        """Verify translations directory exists."""
        translations_dir = INTEGRATION_DIR / "translations"
        assert translations_dir.exists(), "translations/ directory missing"
        assert translations_dir.is_dir()

    def test_translations_en_json_exists(self):
        """Verify translations/en.json exists."""
        en_json = INTEGRATION_DIR / "translations" / "en.json"
        assert en_json.exists(), "translations/en.json missing"
        assert en_json.is_file()


class TestManifestJson:
    """Test manifest.json has correct fields for HACS detection."""

    @pytest.fixture
    def manifest(self) -> dict:
        """Load manifest.json."""
        manifest_path = INTEGRATION_DIR / "manifest.json"
        with manifest_path.open() as f:
            return json.load(f)

    def test_domain_is_deye_cloud(self, manifest: dict):
        """Verify domain is set to deye_cloud."""
        assert manifest["domain"] == "deye_cloud"

    def test_has_name(self, manifest: dict):
        """Verify name field exists and is non-empty."""
        assert "name" in manifest
        assert isinstance(manifest["name"], str)
        assert len(manifest["name"]) > 0

    def test_version_is_semver(self, manifest: dict):
        """Verify version follows semantic versioning (MAJOR.MINOR.PATCH)."""
        assert "version" in manifest
        version = manifest["version"]
        semver_pattern = r"^\d+\.\d+\.\d+$"
        assert re.match(semver_pattern, version), (
            f"Version '{version}' does not match semver format MAJOR.MINOR.PATCH"
        )

    def test_has_dependencies_or_requirements(self, manifest: dict):
        """Verify dependencies array exists."""
        # manifest.json uses 'requirements' for PyPI deps
        assert "requirements" in manifest or "dependencies" in manifest

    def test_has_iot_class(self, manifest: dict):
        """Verify iot_class is present and valid."""
        assert "iot_class" in manifest
        valid_iot_classes = [
            "cloud_polling",
            "cloud_push",
            "local_polling",
            "local_push",
            "assumed_state",
            "calculated",
        ]
        assert manifest["iot_class"] in valid_iot_classes, (
            f"iot_class '{manifest['iot_class']}' is not a valid HA iot_class"
        )

    def test_has_codeowners(self, manifest: dict):
        """Verify codeowners array exists with at least one entry."""
        assert "codeowners" in manifest
        assert isinstance(manifest["codeowners"], list)
        assert len(manifest["codeowners"]) >= 1
        # Each codeowner should start with @
        for owner in manifest["codeowners"]:
            assert owner.startswith("@"), (
                f"Codeowner '{owner}' should start with @"
            )

    def test_has_config_flow(self, manifest: dict):
        """Verify config_flow is enabled."""
        assert manifest.get("config_flow") is True


class TestHacsJson:
    """Test hacs.json has required fields."""

    @pytest.fixture
    def hacs(self) -> dict:
        """Load hacs.json."""
        hacs_path = INTEGRATION_DIR / "hacs.json"
        with hacs_path.open() as f:
            return json.load(f)

    def test_has_name(self, hacs: dict):
        """Verify name field exists."""
        assert "name" in hacs
        assert isinstance(hacs["name"], str)
        assert len(hacs["name"]) > 0

    def test_has_content_in_root(self, hacs: dict):
        """Verify content_in_root field exists."""
        assert "content_in_root" in hacs
        assert isinstance(hacs["content_in_root"], bool)


class TestStringsAndTranslations:
    """Test strings.json and translations/en.json consistency."""

    @pytest.fixture
    def strings(self) -> dict:
        """Load strings.json."""
        strings_path = INTEGRATION_DIR / "strings.json"
        with strings_path.open() as f:
            return json.load(f)

    @pytest.fixture
    def translations_en(self) -> dict:
        """Load translations/en.json."""
        en_path = INTEGRATION_DIR / "translations" / "en.json"
        with en_path.open() as f:
            return json.load(f)

    def test_strings_has_config_section(self, strings: dict):
        """Verify strings.json has config section."""
        assert "config" in strings

    def test_strings_has_entity_section(self, strings: dict):
        """Verify strings.json has entity section."""
        assert "entity" in strings

    def test_translations_has_config_section(self, translations_en: dict):
        """Verify translations/en.json has config section."""
        assert "config" in translations_en

    def test_translations_has_entity_section(self, translations_en: dict):
        """Verify translations/en.json has entity section."""
        assert "entity" in translations_en

    def test_config_structure_matches(self, strings: dict, translations_en: dict):
        """Verify config step keys match between strings.json and translations."""
        strings_steps = set(strings.get("config", {}).get("step", {}).keys())
        trans_steps = set(translations_en.get("config", {}).get("step", {}).keys())
        assert strings_steps == trans_steps, (
            f"Config steps mismatch. strings.json: {strings_steps}, "
            f"translations/en.json: {trans_steps}"
        )

    def test_entity_platforms_match(self, strings: dict, translations_en: dict):
        """Verify entity platform keys match between strings.json and translations."""
        strings_platforms = set(strings.get("entity", {}).keys())
        trans_platforms = set(translations_en.get("entity", {}).keys())
        assert strings_platforms == trans_platforms, (
            f"Entity platforms mismatch. strings.json: {strings_platforms}, "
            f"translations/en.json: {trans_platforms}"
        )

    def test_entity_keys_match_per_platform(self, strings: dict, translations_en: dict):
        """Verify entity keys match per platform between strings and translations."""
        for platform in strings.get("entity", {}):
            strings_keys = set(strings["entity"][platform].keys())
            trans_keys = set(translations_en.get("entity", {}).get(platform, {}).keys())
            assert strings_keys == trans_keys, (
                f"Entity keys mismatch for platform '{platform}'. "
                f"strings.json: {strings_keys}, translations/en.json: {trans_keys}"
            )


class TestServicesYaml:
    """Test services.yaml exists and has basic structure."""

    def test_services_yaml_exists(self):
        """Verify services.yaml exists."""
        services_path = INTEGRATION_DIR / "services.yaml"
        assert services_path.exists(), "services.yaml missing"

    def test_services_yaml_is_valid(self):
        """Verify services.yaml is valid YAML with expected service keys."""
        import yaml

        services_path = INTEGRATION_DIR / "services.yaml"
        with services_path.open() as f:
            services = yaml.safe_load(f)

        assert isinstance(services, dict)
        expected_services = [
            "send_modbus_command",
            "read_control_strategy",
            "write_control_strategy",
            "force_refresh",
        ]
        for service_name in expected_services:
            assert service_name in services, (
                f"Service '{service_name}' not found in services.yaml"
            )
            assert "name" in services[service_name]
            assert "description" in services[service_name]
            assert "fields" in services[service_name]
