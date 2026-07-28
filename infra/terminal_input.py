import os
import sys
import time

try:
    import msvcrt
except ImportError:
    msvcrt = None

try:
    import select
    import termios
    import tty
except ImportError:
    select = termios = tty = None

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:

    def _get_char_windows() -> str | None:
        """Reads a single character on Windows via `msvcrt` without blocking execution.

        Captures raw keyboard input using `msvcrt.getwch()`. Consumes 2-byte
        extended keys (such as arrow and function keys) without polluting the system
        input buffer. Relieves CPU usage with a short sleep when the buffer is idle.

        Returns:
            str | None: The decoded character read from the Windows console, or
            `None` if no key is pressed or if an extended key sequence is discarded.

        Raises:
            NotImplementedError: If the `msvcrt` module is not available.
        """
        if msvcrt is None:
            raise NotImplementedError(
                "_get_char_windows cannot be implemented without msvcrt lib"
            )

        # If no key is in the buffer, sleep 50ms to reduce CPU usage
        if not msvcrt.kbhit():  # type: ignore
            time.sleep(0.05)
            return None

        ch = msvcrt.getwch()  # type: ignore

        # Discard the 2nd byte of extended keys (Arrows, F1-F12, etc.)
        if ch in ("\x00", "\xe0"):
            msvcrt.getwch()  # type: ignore
            return None

        return ch

else:

    def _get_char_posix() -> str | None:
        """Reads a single character on POSIX/Linux systems via non-blocking I/O
        directly from the kernel (`os.read`).

        Uses `select.select` and the `os.read` system call directly on the stdin
        file descriptor (`fd`). This bypasses Python's internal I/O buffer,
        ensuring immediate capture and purging of multi-byte ANSI escape
        sequences (e.g., arrow keys `\\x1b[D`).

        Returns:
            str | None: The normalized character (`\\r` for Enter, `\\x08` for Backspace),
            or `None` if no key is pressed or if an escape sequence is discarded.

        Raises:
            NotImplementedError: If `select`, `termios`, or `tty` are unavailable.
        """
        if select is None or termios is None or tty is None:
            raise NotImplementedError(
                "_get_char_posix cannot be implemented without libs select, termios and tty"
            )

        fd = sys.stdin.fileno()
        r_list, _, _ = select.select([fd], [], [], 0.05)

        if r_list:
            # Raw (unbuffered) read from File Descriptor to avoid misguiding select
            ch_bytes = os.read(fd, 1)

            if not ch_bytes:
                return None

            ch = ch_bytes.decode("utf-8", errors="ignore")

            # Purge ANSI escape sequences (Arrows/Functions) from the kernel buffer
            if ch == "\x1b":
                while select.select([fd], [], [], 0)[0]:
                    os.read(fd, 1)
                return None

            # POSIX key normalization
            if ch == "\n":
                return "\r"

            if ch == "\x7f":
                return "\x08"

            return ch
        return None


def custom_input(
    prompt: str = "",
    inactive_timeout: float | None = None,
    total_timeout: float | None = None,
    only_alphanumeric: bool = True,
):
    """Prompts for and captures a line of text character-by-character with custom filtering
    and dual-timeout support.

    Switches POSIX terminals to cbreak mode during execution and guarantees
    restoration of original settings in a `finally` block. Supports real-time echo,
    visual character deletion (Backspace), optional alphanumeric restriction, and
    both inactivity and total session timeouts.

    Args:
        prompt (str, optional): Instruction text displayed to the user.
            Defaults to "".
        inactive_timeout (float | None, optional): Maximum allowed user inactivity time
            between keypresses in seconds. `None` disables this limit. Defaults to None.
        total_timeout (float | None, optional): Maximum total allowed duration for the
            entire input session in seconds. `None` disables this limit. Defaults to None.
        only_alphanumeric (bool, optional): If True, restricts character input to letters,
            digits, and spaces. Defaults to True.

    Returns:
        str: The string containing the input typed by the user up to the Enter key.

    Raises:
        TimeoutError: If either `inactive_timeout` or `total_timeout` is exceeded.
    """
    if IS_WINDOWS:
        _get_char_fn = _get_char_windows
    else:
        _get_char_fn = _get_char_posix
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)  # type: ignore
        tty.setcbreak(fd)  # type: ignore

    buffer: list[str] = []
    start_time = time.time()
    last_activity = time.time()

    sys.stdout.write(prompt)
    sys.stdout.flush()

    try:
        while True:
            inactivity_exceeded = False
            timeout_exceeded = False
            timeout_msg = None
            char = _get_char_fn()
            now = time.time()

            if inactive_timeout:
                if char:
                    last_activity = time.time()

                inactivity_exceeded = (now - last_activity) > inactive_timeout
                if inactivity_exceeded:
                    timeout_msg = "Inactive timeout exceeded"

            if total_timeout:
                timeout_exceeded = (now - start_time) > total_timeout
                if timeout_exceeded:
                    timeout_msg = "Total timeout exceeded"

            if inactivity_exceeded or timeout_exceeded:
                sys.stdout.write("\n")
                sys.stdout.flush()
                raise TimeoutError(timeout_msg)

            if not char:
                continue

            # Enter key (Finalize input)
            if char == "\r":
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(buffer)

            # Backspace key (Remove from buffer and screen)
            elif char == "\x08":
                if buffer:
                    buffer.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()

            # Character echo and filtering
            elif char.isprintable():
                if only_alphanumeric and not (char.isalnum() or char == " "):
                    continue
                buffer.append(char)
                sys.stdout.write(char)
                sys.stdout.flush()
    finally:
        # Ensure POSIX terminal restoration even if exceptions or timeouts occur
        if not IS_WINDOWS:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)  # type: ignore
