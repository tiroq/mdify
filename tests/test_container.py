"""Tests for container module."""

from unittest.mock import patch, Mock
import pytest
import subprocess

from mdify.container import DoclingContainer


class TestDoclingContainerInit:
    """Test DoclingContainer initialization."""

    def test_init_sets_attributes(self):
        """Test initialization sets correct attributes."""
        container = DoclingContainer("docker", "test-image:latest", port=8080)

        assert container.runtime == "docker"
        assert container.image == "test-image:latest"
        assert container.port == 8080
        assert container.container_name.startswith("mdify-serve-")
        assert container.container_id is None

    def test_init_default_port(self):
        """Test initialization with default port."""
        container = DoclingContainer("docker", "test-image")

        assert container.port == 5001

    def test_base_url_property(self):
        """Test base_url property returns correct URL."""
        container = DoclingContainer("docker", "test-image", port=5001)

        assert container.base_url == "http://localhost:5001"

    def test_base_url_custom_port(self):
        """Test base_url property with custom port."""
        container = DoclingContainer("docker", "test-image", port=8080)

        assert container.base_url == "http://localhost:8080"

    def test_container_name_unique(self):
        """Test that each container gets unique name."""
        container1 = DoclingContainer("docker", "test-image")
        container2 = DoclingContainer("docker", "test-image")

        assert container1.container_name != container2.container_name


class TestDoclingContainerStart:
    """Test container startup."""

    def test_start_success(self):
        """Test successful container startup."""
        with patch("mdify.container.subprocess.run") as mock_run, patch(
            "mdify.container.check_health"
        ) as mock_health:
            # Mock container start
            mock_result = Mock()
            mock_result.stdout = "abc123container_id\n"
            mock_run.return_value = mock_result

            # Mock health check
            mock_health.return_value = True

            container = DoclingContainer("docker", "test-image")
            container.start(timeout=5)

            assert container.container_id == "abc123container_id"
            assert mock_run.called
            assert mock_health.called

    def test_start_subprocess_error(self):
        """Test container start with subprocess error."""
        with patch("mdify.container.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, ["docker", "run"], stderr="Image not found"
            )

            container = DoclingContainer("docker", "test-image")

            with pytest.raises(subprocess.CalledProcessError):
                container.start()

    def test_start_health_timeout(self):
        """Test container start with health check timeout."""
        with patch("mdify.container.subprocess.run") as mock_run, patch(
            "mdify.container.check_health"
        ) as mock_health, patch("mdify.container.time.sleep"):
            mock_result = Mock()
            mock_result.stdout = "container_id\n"
            mock_run.return_value = mock_result

            # Health check always fails
            mock_health.return_value = False

            container = DoclingContainer("docker", "test-image")

            with pytest.raises(TimeoutError):
                container.start(timeout=1)

    def test_start_with_correct_command(self):
        """Test start uses correct docker command."""
        with patch("mdify.container.subprocess.run") as mock_run, patch(
            "mdify.container.check_health"
        ) as mock_health:
            mock_result = Mock()
            mock_result.stdout = "container_id\n"
            mock_run.return_value = mock_result
            mock_health.return_value = True

            container = DoclingContainer("docker", "my-image:v1", port=8080)
            container.start(timeout=5)

            # Verify the command structure
            call_args = mock_run.call_args[0][0]
            assert "docker" in call_args
            assert "run" in call_args
            assert "-d" in call_args
            assert "--rm" in call_args
            assert "--name" in call_args
            assert container.container_name in call_args
            assert "-p" in call_args
            assert "8080:5001" in call_args
            assert "my-image:v1" in call_args


class TestDoclingContainerStop:
    """Test container stop."""

    def test_stop_success(self):
        """Test successful container stop."""
        with patch("mdify.container.subprocess.run") as mock_run:
            container = DoclingContainer("docker", "test-image")
            container.container_name = "test-container"

            container.stop()

            assert mock_run.called
            call_args = mock_run.call_args[0][0]
            assert "docker" in call_args
            assert "stop" in call_args
            assert "test-container" in call_args

    def test_stop_idempotent(self):
        """Test stop can be called multiple times safely."""
        with patch("mdify.container.subprocess.run") as mock_run:
            container = DoclingContainer("docker", "test-image")

            container.stop()
            container.stop()  # Should not raise

            assert mock_run.call_count == 2

    def test_stop_with_podman(self):
        """Test stop works with podman runtime."""
        with patch("mdify.container.subprocess.run") as mock_run:
            container = DoclingContainer("podman", "test-image")

            container.stop()

            call_args = mock_run.call_args[0][0]
            assert "podman" in call_args
            assert "stop" in call_args


class TestDoclingContainerIsReady:
    """Test is_ready method."""

    def test_is_ready_true(self):
        """Test is_ready returns True when healthy."""
        with patch("mdify.container.check_health") as mock_health:
            mock_health.return_value = True

            container = DoclingContainer("docker", "test-image")

            assert container.is_ready() is True

    def test_is_ready_false(self):
        """Test is_ready returns False when unhealthy."""
        with patch("mdify.container.check_health") as mock_health:
            mock_health.return_value = False

            container = DoclingContainer("docker", "test-image")

            assert container.is_ready() is False

    def test_is_ready_exception(self):
        """Test is_ready returns False on exception."""
        with patch("mdify.container.check_health") as mock_health:
            mock_health.side_effect = Exception("Connection error")

            container = DoclingContainer("docker", "test-image")

            assert container.is_ready() is False


class TestDoclingContainerContextManager:
    """Test context manager functionality."""

    def test_context_manager_calls_start_stop(self):
        """Test context manager calls start and stop."""
        with patch("mdify.container.subprocess.run") as mock_run, patch(
            "mdify.container.check_health"
        ) as mock_health:
            mock_result = Mock()
            mock_result.stdout = "container_id\n"
            mock_run.return_value = mock_result
            mock_health.return_value = True

            with DoclingContainer("docker", "test-image") as container:
                assert container.container_id is not None

            # Verify start was called (docker run)
            # Verify stop was called (docker stop)
            assert mock_run.call_count >= 2

    def test_context_manager_cleanup_on_exception(self):
        """Test context manager stops container even on exception."""
        with patch("mdify.container.subprocess.run") as mock_run, patch(
            "mdify.container.check_health"
        ) as mock_health:
            mock_result = Mock()
            mock_result.stdout = "container_id\n"
            mock_run.return_value = mock_result
            mock_health.return_value = True

            try:
                with DoclingContainer("docker", "test-image") as container:
                    raise RuntimeError("Test error")
            except RuntimeError:
                pass

            # Stop should still have been called
            stop_calls = [
                call for call in mock_run.call_args_list if "stop" in str(call)
            ]
            assert len(stop_calls) > 0

    def test_context_manager_return_value(self):
        """Test context manager returns container instance."""
        with patch("mdify.container.subprocess.run") as mock_run, patch(
            "mdify.container.check_health"
        ) as mock_health:
            mock_result = Mock()
            mock_result.stdout = "test_id\n"
            mock_run.return_value = mock_result
            mock_health.return_value = True

            with DoclingContainer("docker", "test-image", port=9000) as container:
                assert isinstance(container, DoclingContainer)
                assert container.port == 9000
                assert container.container_id == "test_id"

    def test_context_manager_does_not_suppress_exception(self):
        """Test context manager does not suppress exceptions."""
        with patch("mdify.container.subprocess.run") as mock_run, patch(
            "mdify.container.check_health"
        ) as mock_health:
            mock_result = Mock()
            mock_result.stdout = "container_id\n"
            mock_run.return_value = mock_result
            mock_health.return_value = True

            with pytest.raises(ValueError, match="Test error"):
                with DoclingContainer("docker", "test-image"):
                    raise ValueError("Test error")


class TestDoclingContainerIntegration:
    """Integration-like tests with mocked subprocess."""

    def test_full_lifecycle(self):
        """Test full start-check-stop lifecycle."""
        with patch("mdify.container.subprocess.run") as mock_run, patch(
            "mdify.container.check_health"
        ) as mock_health:
            mock_result = Mock()
            mock_result.stdout = "abc123\n"
            mock_run.return_value = mock_result
            mock_health.return_value = True

            container = DoclingContainer("docker", "test-image", port=5001)

            # Start
            container.start(timeout=10)
            assert container.container_id == "abc123"

            # Check
            assert container.is_ready() is True

            # Stop
            container.stop()

    def test_multiple_containers_independent(self):
        """Test multiple containers are independent."""
        with patch("mdify.container.subprocess.run") as mock_run, patch(
            "mdify.container.check_health"
        ) as mock_health:
            mock_result1 = Mock()
            mock_result1.stdout = "id1\n"
            mock_result2 = Mock()
            mock_result2.stdout = "id2\n"
            mock_run.side_effect = [
                mock_result1,
                mock_health,
                mock_result2,
                mock_health,
            ]
            mock_health.return_value = True

            container1 = DoclingContainer("docker", "image1", port=5001)
            container2 = DoclingContainer("docker", "image2", port=5002)

            # Each should be independent
            assert container1.port == 5001
            assert container2.port == 5002
            assert container1.container_name != container2.container_name
