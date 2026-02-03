"""File transfer and progress tracking for SSH."""

import asyncio
import gzip
import hashlib
import logging
from pathlib import Path
from typing import Callable
from mdify.ssh.models import TransferSession

logger = logging.getLogger(__name__)


class FileTransferManager:
    """Manages file transfers with compression and progress tracking."""
    
    def __init__(
        self,
        ssh_client,
        compression_threshold: int = 1024 * 1024,  # 1MB
        chunk_size: int = 64 * 1024,  # 64KB
        verify_checksum: bool = True
    ):
        """Initialize file transfer manager.
        
        Parameters:
            ssh_client: Connected AsyncSSHClient instance
            compression_threshold: Compress files larger than this (bytes)
            chunk_size: Read/write chunk size for progress updates
            verify_checksum: Calculate SHA256 checksums
        """
        self.ssh_client = ssh_client
        self.compression_threshold = compression_threshold
        self.chunk_size = chunk_size
        self.verify_checksum = verify_checksum
    
    async def upload_file(
        self,
        local_path: str,
        remote_path: str,
        progress_callback: Callable[[TransferSession], None] | None = None,
        overwrite: bool = False,
        compress: bool | None = None
    ) -> TransferSession:
        """Upload file to remote server.
        
        Parameters:
            local_path: Local file path
            remote_path: Remote destination path
            progress_callback: Called with TransferSession after each chunk
            overwrite: Allow overwriting existing files
            compress: Force compression (None = auto-detect by size)
            
        Returns:
            TransferSession with transfer results
            
        Raises:
            FileNotFoundError: Local file doesn't exist
            FileExistsError: Remote file exists and overwrite=False
        """
        local_file = Path(local_path)
        if not local_file.exists():
            raise FileNotFoundError(f"Local file not found: {local_path}")
        
        file_size = local_file.stat().st_size
        
        # Auto-detect compression
        if compress is None:
            compress = file_size > self.compression_threshold
        
        session = TransferSession(
            local_path=local_path,
            remote_path=remote_path,
            direction="upload",
            total_bytes=file_size,
            status="in_progress"
        )
        
        try:
            # Check if remote file exists
            if not overwrite:
                stdout, stderr, code = await self.ssh_client.run_command(
                    f"test -f {remote_path}"
                )
                if code == 0:
                    raise FileExistsError(f"Remote file exists: {remote_path}")
            
            # Prepare source data
            if compress:
                logger.debug(f"Compressing {local_file.name} for upload...")
                session.status = "in_progress"
                data = await self._compress_file(local_file)
                actual_remote_path = f"{remote_path}.gz"
                session.status = "in_progress"
            else:
                with open(local_file, 'rb') as f:
                    data = f.read()
                actual_remote_path = remote_path
            
            # Upload via SFTP
            async with self.ssh_client.connection.get_sftp_client() as sftp:
                # Write file with progress tracking
                bytes_written = 0
                with open(local_file, 'rb') as local_fp:
                    async with await sftp.open(actual_remote_path, 'wb') as remote_fp:
                        while True:
                            chunk = local_fp.read(self.chunk_size)
                            if not chunk:
                                break
                            
                            await remote_fp.write(chunk)
                            bytes_written += len(chunk)
                            session.update_progress(bytes_written)
                            
                            if progress_callback:
                                progress_callback(session)
            
            # Verify checksum if enabled
            if self.verify_checksum:
                await self._verify_upload_checksum(
                    local_file, actual_remote_path, session
                )
            
            session.complete()
            logger.info(f"Upload complete: {local_path} → {actual_remote_path}")
            return session
            
        except Exception as e:
            session.fail(e)
            logger.error(f"Upload failed: {e}")
            raise
    
    async def download_file(
        self,
        remote_path: str,
        local_path: str,
        progress_callback: Callable[[TransferSession], None] | None = None,
        overwrite: bool = False
    ) -> TransferSession:
        """Download file from remote server.
        
        Parameters:
            remote_path: Remote file path
            local_path: Local destination path
            progress_callback: Called with TransferSession after each chunk
            overwrite: Allow overwriting existing files
            
        Returns:
            TransferSession with transfer results
        """
        local_file = Path(local_path)
        
        # Check if local file exists
        if local_file.exists() and not overwrite:
            raise FileExistsError(f"Local file exists: {local_path}")
        
        session = TransferSession(
            remote_path=remote_path,
            local_path=local_path,
            direction="download",
            status="in_progress"
        )
        
        try:
            # Get remote file size
            stdout, stderr, code = await self.ssh_client.run_command(
                f"wc -c < {remote_path}"
            )
            if code == 0:
                try:
                    session.total_bytes = int(stdout.strip())
                except ValueError:
                    session.total_bytes = 0
            
            # Download via SFTP
            async with self.ssh_client.connection.get_sftp_client() as sftp:
                bytes_read = 0
                with open(local_file, 'wb') as local_fp:
                    async with await sftp.open(remote_path, 'rb') as remote_fp:
                        while True:
                            chunk = await remote_fp.read(self.chunk_size)
                            if not chunk:
                                break
                            
                            local_fp.write(chunk)
                            bytes_read += len(chunk)
                            session.update_progress(bytes_read)
                            
                            if progress_callback:
                                progress_callback(session)
            
            session.complete()
            logger.info(f"Download complete: {remote_path} → {local_path}")
            return session
            
        except Exception as e:
            session.fail(e)
            logger.error(f"Download failed: {e}")
            raise
    
    async def _compress_file(self, file_path: Path) -> bytes:
        """Compress file for transfer.
        
        Parameters:
            file_path: Path to file to compress
            
        Returns:
            Compressed file data
        """
        with open(file_path, 'rb') as f_in:
            compressed = gzip.compress(f_in.read())
        return compressed
    
    async def _verify_upload_checksum(
        self,
        local_file: Path,
        remote_path: str,
        session: TransferSession
    ) -> None:
        """Verify uploaded file checksum.
        
        Parameters:
            local_file: Local file path
            remote_path: Remote file path
            session: Transfer session for error reporting
            
        Raises:
            ValueError: Checksum mismatch
        """
        # Calculate local checksum
        local_sha256 = hashlib.sha256()
        with open(local_file, 'rb') as f:
            for chunk in iter(lambda: f.read(self.chunk_size), b''):
                local_sha256.update(chunk)
        local_checksum = local_sha256.hexdigest()
        
        # Calculate remote checksum
        stdout, stderr, code = await self.ssh_client.run_command(
            f"sha256sum {remote_path} | awk '{{print $1}}'"
        )
        
        if code == 0:
            remote_checksum = stdout.strip()
            
            if local_checksum != remote_checksum:
                raise ValueError(
                    f"Checksum mismatch: {local_checksum} != {remote_checksum}"
                )
            
            logger.debug(f"Checksum verified: {local_checksum}")
        else:
            logger.warning(f"Could not verify checksum: {stderr}")


class ProgressBar:
    """Simple progress bar display."""
    
    def __init__(self, total_bytes: int, debug_mode: bool = False):
        """Initialize progress bar.
        
        Parameters:
            total_bytes: Total bytes to transfer
            debug_mode: Enable detailed logging
        """
        self.total_bytes = total_bytes
        self.debug_mode = debug_mode
        self.last_update = 0
    
    def update(self, session: TransferSession) -> str:
        """Format progress display.
        
        Parameters:
            session: TransferSession with current progress
            
        Returns:
            Formatted progress string
        """
        if session.total_bytes == 0:
            return ""
        
        percent = 100 * session.transferred_bytes / session.total_bytes
        bar_width = 40
        filled = int(bar_width * session.transferred_bytes / session.total_bytes)
        bar = "█" * filled + "░" * (bar_width - filled)
        
        speed_str = f"{session.avg_speed_mbps:.1f}MB/s"
        eta_str = f"ETA {session.eta_seconds}s" if session.eta_seconds else "Computing..."
        
        return f"[{bar}] {percent:3.0f}% {speed_str} {eta_str}"
    
    def log_chunk(self, chunk_num: int, bytes_transferred: int, speed_mbps: float) -> None:
        """Log chunk transfer (debug mode).
        
        Parameters:
            chunk_num: Chunk number
            bytes_transferred: Total bytes transferred so far
            speed_mbps: Current speed in MB/s
        """
        if self.debug_mode:
            logger.debug(f"Chunk {chunk_num}: {bytes_transferred} bytes ({speed_mbps:.1f}MB/s)")
