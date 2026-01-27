"""Tests for docling_client module."""

from unittest.mock import patch, Mock
import pytest
import requests
from pathlib import Path

from mdify.docling_client import (
    check_health,
    convert_file,
    convert_file_async,
    poll_status,
    get_result,
    ConvertResult,
    StatusResult,
    DoclingHTTPError,
)


class TestCheckHealth:
    """Test health check function."""

    def test_check_health_success(self):
        """Test health check with successful response."""
        with patch("mdify.docling_client.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"status": "healthy"}

            assert check_health("http://localhost:5001") is True

    def test_check_health_failure_404(self):
        """Test health check with 404 response."""
        with patch("mdify.docling_client.requests.get") as mock_get:
            mock_get.return_value.status_code = 404

            assert check_health("http://localhost:5001") is False

    def test_check_health_connection_error(self):
        """Test health check with connection error."""
        with patch("mdify.docling_client.requests.get") as mock_get:
            mock_get.side_effect = requests.ConnectionError()

            assert check_health("http://localhost:5001") is False

    def test_check_health_timeout(self):
        """Test health check with timeout."""
        with patch("mdify.docling_client.requests.get") as mock_get:
            mock_get.side_effect = requests.Timeout()

            assert check_health("http://localhost:5001") is False


class TestConvertFile:
    """Test synchronous file conversion."""

    def test_convert_file_success_list_format(self, tmp_path):
        """Test successful file conversion with list response format."""
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"fake pdf content")

        with patch("mdify.docling_client.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = [
                {"content": "# Test Document\n\nContent here."}
            ]
            mock_post.return_value = mock_response

            result = convert_file("http://localhost:5001", test_file)

            assert result.success is True
            assert "# Test Document" in result.content
            assert result.error is None
            assert result.format == "md"

    def test_convert_file_success_dict_format(self, tmp_path):
        """Test successful file conversion with dict response format."""
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"fake pdf content")

        with patch("mdify.docling_client.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"content": "# Test Document"}
            mock_post.return_value = mock_response

            result = convert_file("http://localhost:5001", test_file)

            assert result.success is True
            assert "# Test Document" in result.content

    def test_convert_file_http_error(self, tmp_path):
        """Test file conversion with HTTP error."""
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"fake pdf")

        with patch("mdify.docling_client.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_post.return_value = mock_response

            with pytest.raises(DoclingHTTPError) as exc_info:
                convert_file("http://localhost:5001", test_file)

            assert exc_info.value.status_code == 500

    def test_convert_file_connection_error(self, tmp_path):
        """Test file conversion with connection error."""
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"fake pdf")

        with patch("mdify.docling_client.requests.post") as mock_post:
            mock_post.side_effect = requests.ConnectionError("Connection refused")

            result = convert_file("http://localhost:5001", test_file)

            assert result.success is False
            assert "Connection refused" in result.error

    def test_convert_file_with_custom_format(self, tmp_path):
        """Test file conversion with custom output format."""
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"fake pdf")

        with patch("mdify.docling_client.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = [{"content": "Result"}]
            mock_post.return_value = mock_response

            result = convert_file("http://localhost:5001", test_file, to_format="html")

            assert result.format == "html"


class TestConvertFileAsync:
    """Test async file conversion."""

    def test_convert_file_async_success(self, tmp_path):
        """Test async conversion returns task ID."""
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"fake pdf")

        with patch("mdify.docling_client.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"task_id": "abc123"}
            mock_post.return_value = mock_response

            task_id = convert_file_async("http://localhost:5001", test_file)

            assert task_id == "abc123"

    def test_convert_file_async_http_error(self, tmp_path):
        """Test async conversion with HTTP error."""
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"fake pdf")

        with patch("mdify.docling_client.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 400
            mock_response.text = "Bad Request"
            mock_post.return_value = mock_response

            with pytest.raises(DoclingHTTPError):
                convert_file_async("http://localhost:5001", test_file)

    def test_convert_file_async_missing_task_id(self, tmp_path):
        """Test async conversion with missing task_id in response."""
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"fake pdf")

        with patch("mdify.docling_client.requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {}
            mock_post.return_value = mock_response

            with pytest.raises(DoclingHTTPError):
                convert_file_async("http://localhost:5001", test_file)

    def test_convert_file_async_connection_error(self, tmp_path):
        """Test async conversion with connection error."""
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"fake pdf")

        with patch("mdify.docling_client.requests.post") as mock_post:
            mock_post.side_effect = requests.ConnectionError("Connection refused")

            with pytest.raises(DoclingHTTPError):
                convert_file_async("http://localhost:5001", test_file)


class TestPollStatus:
    """Test status polling."""

    def test_poll_status_completed(self):
        """Test polling with completed status."""
        with patch("mdify.docling_client.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "task_id": "abc123",
                "status": "completed",
            }
            mock_get.return_value = mock_response

            status = poll_status("http://localhost:5001", "abc123")

            assert status.task_id == "abc123"
            assert status.status == "completed"

    def test_poll_status_pending(self):
        """Test polling with pending status."""
        with patch("mdify.docling_client.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"task_id": "abc123", "status": "pending"}
            mock_get.return_value = mock_response

            status = poll_status("http://localhost:5001", "abc123")

            assert status.status == "pending"

    def test_poll_status_failed(self):
        """Test polling with failed status."""
        with patch("mdify.docling_client.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "task_id": "abc123",
                "status": "failed",
                "error": "Processing error",
            }
            mock_get.return_value = mock_response

            status = poll_status("http://localhost:5001", "abc123")

            assert status.status == "failed"
            assert status.error == "Processing error"

    def test_poll_status_http_error(self):
        """Test polling with HTTP error."""
        with patch("mdify.docling_client.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 500
            mock_response.text = "Server error"
            mock_get.return_value = mock_response

            with pytest.raises(DoclingHTTPError):
                poll_status("http://localhost:5001", "abc123")


class TestGetResult:
    """Test result retrieval."""

    def test_get_result_success_list_format(self):
        """Test getting result for completed task with list format."""
        with patch("mdify.docling_client.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = [{"content": "# Result\n\nContent."}]
            mock_get.return_value = mock_response

            result = get_result("http://localhost:5001", "abc123")

            assert result.success is True
            assert "# Result" in result.content

    def test_get_result_success_dict_format(self):
        """Test getting result for completed task with dict format."""
        with patch("mdify.docling_client.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"content": "# Result"}
            mock_get.return_value = mock_response

            result = get_result("http://localhost:5001", "abc123")

            assert result.success is True
            assert "# Result" in result.content

    def test_get_result_http_error(self):
        """Test getting result with HTTP error."""
        with patch("mdify.docling_client.requests.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 404
            mock_response.text = "Task not found"
            mock_get.return_value = mock_response

            with pytest.raises(DoclingHTTPError):
                get_result("http://localhost:5001", "nonexistent")

    def test_get_result_connection_error(self):
        """Test getting result with connection error."""
        with patch("mdify.docling_client.requests.get") as mock_get:
            mock_get.side_effect = requests.ConnectionError()

            result = get_result("http://localhost:5001", "abc123")

            assert result.success is False
            assert result.error is not None


class TestDataClasses:
    """Test dataclass definitions."""

    def test_convert_result_creation(self):
        """Test ConvertResult dataclass creation."""
        result = ConvertResult(content="Test", format="md", success=True)

        assert result.content == "Test"
        assert result.format == "md"
        assert result.success is True
        assert result.error is None

    def test_convert_result_with_error(self):
        """Test ConvertResult with error."""
        result = ConvertResult(
            content="", format="md", success=False, error="Test error"
        )

        assert result.success is False
        assert result.error == "Test error"

    def test_status_result_creation(self):
        """Test StatusResult dataclass creation."""
        status = StatusResult(status="completed", task_id="abc123")

        assert status.status == "completed"
        assert status.task_id == "abc123"
        assert status.error is None

    def test_status_result_with_error(self):
        """Test StatusResult with error."""
        status = StatusResult(status="failed", task_id="abc123", error="Failed")

        assert status.status == "failed"
        assert status.error == "Failed"


class TestDoclingHTTPError:
    """Test custom HTTP error."""

    def test_http_error_message(self):
        """Test HTTP error message formatting."""
        error = DoclingHTTPError(500, "Internal Server Error")

        assert error.status_code == 500
        assert "500" in str(error)
        assert "Internal Server Error" in str(error)

    def test_http_error_inheritance(self):
        """Test HTTP error is proper exception type."""
        error = DoclingHTTPError(400, "Bad Request")

        assert isinstance(error, Exception)
