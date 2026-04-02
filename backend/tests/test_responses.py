import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.responses import success_response, error_response


class TestResponses:
    """Test API response utilities."""

    def test_success_response_default(self):
        result = success_response()
        assert result["code"] == 200
        assert result["message"] == "success"
        assert result["data"] is None

    def test_success_response_with_data(self):
        result = success_response(data={"key": "value"}, message="Done")
        assert result["code"] == 200
        assert result["message"] == "Done"
        assert result["data"] == {"key": "value"}

    def test_success_response_with_list(self):
        result = success_response(data=[1, 2, 3])
        assert result["data"] == [1, 2, 3]

    def test_success_response_with_code(self):
        result = success_response(code=201)
        assert result["code"] == 201

    def test_error_response_default(self):
        result = error_response("Something went wrong")
        assert result["code"] == 400
        assert result["message"] == "Something went wrong"
        assert result["data"] is None

    def test_error_response_custom_code(self):
        result = error_response("Not found", code=404)
        assert result["code"] == 404
        assert result["message"] == "Not found"

    def test_error_response_server_error(self):
        result = error_response("Internal error", code=500)
        assert result["code"] == 500
