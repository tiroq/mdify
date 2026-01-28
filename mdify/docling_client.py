"""HTTP client for docling-serve REST API."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import mimetypes

import requests


@dataclass
class ConvertResult:
    """Result from document conversion."""

    content: str
    format: str
    success: bool
    error: Optional[str] = None


@dataclass
class StatusResult:
    """Status of async conversion task."""

    status: str  # "pending", "completed", "failed"
    task_id: str
    error: Optional[str] = None


class DoclingClientError(Exception):
    """Base exception for docling client errors."""

    pass


class DoclingHTTPError(DoclingClientError):
    """HTTP error from docling-serve API."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {message}")


def _get_mime_type(file_path: Path) -> str:
    """Get MIME type for file, with fallback for unknown types."""
    mime_type, _ = mimetypes.guess_type(str(file_path))
    return mime_type or "application/octet-stream"


def _extract_content(result_data) -> str:
    """Extract content from API response, supporting both old and new formats.

    Supports:
    - New format: {"document": {"md_content": "..."}}
    - Fallback: {"document": {"content": "..."}}
    - Old format: {"content": "..."}
    - List format: [{"document": {...}} or {"content": "..."}]

    Args:
        result_data: Response data from docling-serve API

    Returns:
        Extracted content string, or empty string if not found
    """
    if isinstance(result_data, dict):
        # New format with document field
        if "document" in result_data:
            doc = result_data["document"]
            # Try md_content first, then content
            return doc.get("md_content", "") or doc.get("content", "")
        # Old format without document field
        return result_data.get("content", "")
    elif isinstance(result_data, list) and len(result_data) > 0:
        # List format - process first item
        first_result = result_data[0]
        if isinstance(first_result, dict):
            if "document" in first_result:
                doc = first_result["document"]
                # Try md_content first, then content
                return doc.get("md_content", "") or doc.get("content", "")
            # Old format without document field
            return first_result.get("content", "")
    return ""


def check_health(base_url: str) -> bool:
    """Check if docling-serve is healthy.

    Args:
        base_url: Base URL of docling-serve (e.g., "http://localhost:8000")

    Returns:
        True if healthy, False otherwise
    """
    try:
        response = requests.get(f"{base_url}/health")
        return response.status_code == 200
    except requests.RequestException:
        return False


def convert_file(
    base_url: str, file_path: Path, to_format: str = "md", do_ocr: bool = True
) -> ConvertResult:
    """Convert a file synchronously.

    Args:
        base_url: Base URL of docling-serve
        file_path: Path to file to convert
        to_format: Output format (default: "md")
        do_ocr: Whether to perform OCR (default: True)

    Returns:
        ConvertResult with conversion output

    Raises:
        DoclingHTTPError: If HTTP request fails
    """
    try:
        with open(file_path, "rb") as f:
            response = requests.post(
                f"{base_url}/v1/convert/file",
                files={"files": (file_path.name, f, _get_mime_type(file_path))},
                data={"to_formats": to_format, "do_ocr": str(do_ocr).lower()},
            )

        if response.status_code != 200:
            raise DoclingHTTPError(
                response.status_code, response.text or "Conversion failed"
            )

        result_data = response.json()
        content = _extract_content(result_data)

        if content or isinstance(result_data, (dict, list)):
            return ConvertResult(content=content, format=to_format, success=True)
        else:
            raise DoclingHTTPError(200, f"Unexpected response format: {result_data}")

    except requests.RequestException as e:
        return ConvertResult(content="", format=to_format, success=False, error=str(e))


def convert_file_async(
    base_url: str, file_path: Path, to_format: str = "md", do_ocr: bool = True
) -> str:
    """Start async file conversion.

    Args:
        base_url: Base URL of docling-serve
        file_path: Path to file to convert
        to_format: Output format (default: "md")
        do_ocr: Whether to perform OCR (default: True)

    Returns:
        Task ID for polling

    Raises:
        DoclingHTTPError: If HTTP request fails
    """
    try:
        with open(file_path, "rb") as f:
            response = requests.post(
                f"{base_url}/v1/convert/file/async",
                files={"files": (file_path.name, f, _get_mime_type(file_path))},
                data={"to_formats": to_format, "do_ocr": str(do_ocr).lower()},
            )

        if response.status_code != 200:
            raise DoclingHTTPError(
                response.status_code, response.text or "Async conversion failed"
            )

        result_data = response.json()
        task_id = result_data.get("task_id")

        if not task_id:
            raise DoclingHTTPError(200, f"No task_id in response: {result_data}")

        return task_id

    except requests.RequestException as e:
        raise DoclingHTTPError(500, str(e))


def poll_status(base_url: str, task_id: str) -> StatusResult:
    """Poll status of async conversion task.

    Args:
        base_url: Base URL of docling-serve
        task_id: Task ID from convert_file_async

    Returns:
        StatusResult with current status

    Raises:
        DoclingHTTPError: If HTTP request fails
    """
    try:
        response = requests.get(f"{base_url}/v1/status/poll/{task_id}")

        if response.status_code != 200:
            raise DoclingHTTPError(
                response.status_code, response.text or "Status poll failed"
            )

        result_data = response.json()

        return StatusResult(
            status=result_data.get("status", "unknown"),
            task_id=task_id,
            error=result_data.get("error"),
        )

    except requests.RequestException as e:
        raise DoclingHTTPError(500, str(e))


def get_result(base_url: str, task_id: str) -> ConvertResult:
    """Get result of completed async conversion.

    Args:
        base_url: Base URL of docling-serve
        task_id: Task ID from convert_file_async

    Returns:
        ConvertResult with conversion output

    Raises:
        DoclingHTTPError: If HTTP request fails or task not completed
    """
    try:
        response = requests.get(f"{base_url}/v1/result/{task_id}")

        if response.status_code != 200:
            raise DoclingHTTPError(
                response.status_code, response.text or "Result retrieval failed"
            )

        result_data = response.json()
        content = _extract_content(result_data)

        # Determine format from response, defaulting to "md"
        result_format = "md"
        if isinstance(result_data, dict):
            result_format = result_data.get("format", "md")
        elif isinstance(result_data, list) and len(result_data) > 0:
            first_result = result_data[0]
            if isinstance(first_result, dict):
                result_format = first_result.get("format", "md")

        if content or isinstance(result_data, (dict, list)):
            return ConvertResult(
                content=content,
                format=result_format,
                success=True,
            )
        else:
            raise DoclingHTTPError(200, f"Unexpected response format: {result_data}")

    except requests.RequestException as e:
        return ConvertResult(content="", format="md", success=False, error=str(e))
