def test_repo_layout_exists():
    import importlib
    for mod in ["app.engine", "app.gateway", "app.contracts", "app.workflow"]:
        importlib.import_module(mod)
