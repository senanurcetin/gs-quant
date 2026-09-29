"""
Copyright 2026 Senanur Çetin.
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
"""

import pytest
from pydantic import ValidationError

from gs_quant.mcp.config import McpServiceConfig, SSLConfig
from gs_quant.session import Environment


def test_defaults():
    config = McpServiceConfig()
    assert config.base_path == "/mcp"
    assert config.port is None
    assert config.host == "0.0.0.0"
    assert config.env == Environment.PROD
    assert config.ssl_config is None


def test_accepts_camel_case_aliases():
    config = McpServiceConfig(**{"basePath": "/api", "sslConfig": {"certPath": "cert.pem", "keyPath": "key.pem"}})
    assert config.base_path == "/api"
    assert config.ssl_config == SSLConfig(cert_path="cert.pem", key_path="key.pem")


def test_accepts_python_field_names():
    config = McpServiceConfig(base_path="/x", port=1234, host="127.0.0.1", env=Environment.QA)
    assert (config.base_path, config.port, config.host, config.env) == ("/x", 1234, "127.0.0.1", Environment.QA)


def test_ssl_config_requires_both_paths():
    with pytest.raises(ValidationError):
        SSLConfig(cert_path="cert.pem")
    with pytest.raises(ValidationError):
        SSLConfig(key_path="key.pem")


def test_serialises_with_camel_case_aliases():
    dumped = McpServiceConfig(port=8080).model_dump(by_alias=True)
    assert dumped["basePath"] == "/mcp"
    assert dumped["port"] == 8080
    assert "sslConfig" in dumped
