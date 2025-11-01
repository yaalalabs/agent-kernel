import os
import pytest

from agentkernel.core.config import AKConfig


def test_config_defaults_no_file(monkeypatch):
    # Ensure no env interference
    monkeypatch.delenv("AK_DEBUG", raising=False)
    monkeypatch.delenv("AK_SESSION_TYPE", raising=False)
    # Use a non-existent file path to  check defaults
    cfg = AKConfig.get()
    cfg.__init__() # Reload
    assert cfg.debug is False
    assert cfg.session.type == "in_memory"
    
    # Defaults for nested redis should be None
    assert cfg.session.redis == None

@pytest.mark.usefixtures("tmp_path")
def test_config_yaml_and_env_override(tmp_path, monkeypatch):
    # Write YAML file
    yaml_text = (
        "debug: true\n"
        "session:\n"
        "  type: redis\n"
        "  redis:\n"
        "    url: redis://example:6379\n"
        "    ttl: 120\n"
        "    prefix: 'ak:test:'\n"
    )
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml_text)

    # Environment should override nested value, and env_prefix AK_ with nested delimiter _
    
    monkeypatch.setenv("AK_SESSION__TYPE", "in_memory")
    monkeypatch.setenv("AK_SESSION__REDIS__TTL", "999")

    # Lets point to the file we created and reload
    monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg_path))
    cfg_1 = AKConfig.get() # instance object which has no yaml file loaded or env settings
    cfg_2 = AKConfig() # object which loads yaml file and env settings


    # defaults from cfg_1
    assert cfg_1.debug is False
    assert cfg_1.session.type == "in_memory"
    assert cfg_1.session.redis is None
    
    # File value
    assert cfg_2.debug is True
    
    # file values overridden by env
    assert cfg_2.session.type == "in_memory"
    assert cfg_2.session.redis is not None
    assert cfg_2.session.redis.ttl == 999
    
    # File-provided values preserved where env not set
    assert cfg_2.session.redis.url == "redis://example:6379"
    assert cfg_2.session.redis.prefix == "ak:test:"

    # Reload and check default object again
    cfg_1.__init__() 
    # File value
    assert cfg_1.debug is True
    
    # File vaues overridden by env
    assert cfg_1.session.type == "in_memory"
    assert cfg_1.session.redis is not None
    assert cfg_1.session.redis.ttl == 999
    
    # File-provided values preserved where env not set
    assert cfg_1.session.redis.url == "redis://example:6379"
    assert cfg_1.session.redis.prefix == "ak:test:"

# @pytest.mark.parametrize(
#     "env_key,env_val,expect",
#     [
#         ("AK_", "", ""),  # empty key should be ignored
#         ("AK__", "value1", "value1"),  # double delimiter leading to empty parts ignored
#         ("AK_SESSION__TYPE", "value2", "value2"),  # double delimiter in middle ignored
#         ("AK_SESSION_REDIS_TTL_EXTRA", "value3", "value3"),  
#         ("AK_SESSION-REDIS-TTL", "value4", "value4"),  # wrong delimiter
#     ],
# )
# def test_env_ignored_edge_cases(tmp_path, monkeypatch, env_key, env_val, expect):
#     # Base file values
#     cfg_path = tmp_path / "config.yaml"
#     cfg_path.write_text("debug: false\n")

#     # Set weird env that should not break or set anything
#     monkeypatch.setenv(env_key, env_val)

#     cfg = AKConfig.__init__()
#     # Should remain default as in file
#     assert cfg.debug is False
#     assert cfg.get()
