from app import load_config, DEFAULT_CONFIG


def test_load_config_returns_dict():
    cfg = load_config()
    assert isinstance(cfg, dict)
    assert all(k in cfg for k in DEFAULT_CONFIG)


def test_load_config_recipients_enforced():
    cfg = load_config()
    assert cfg['recipients'] == ["nictipoff@gmail.com", "mdk32366@gmail.com"]
