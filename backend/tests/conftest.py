import pytest
from pymongo import MongoClient


@pytest.fixture(scope="session", autouse=True)
def clean_account_test_databases():
    yield
    from test_api import TEST_DATABASES
    for uri, name in TEST_DATABASES:
        assert name.startswith(("bim_insight_test_", "test_bim_workspace_"))
        client = MongoClient(uri, serverSelectionTimeoutMS=1500)
        try:
            client.drop_database(name)
        finally:
            client.close()
