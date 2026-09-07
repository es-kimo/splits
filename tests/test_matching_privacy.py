from server.main import create_app


def test_public_api_does_not_expose_personal_record_matching():
    paths = create_app().openapi()["paths"]

    assert "/v1/match" not in paths
    assert all("match" not in path for path in paths)
