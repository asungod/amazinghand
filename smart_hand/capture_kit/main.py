"""MaixVision project entry for the standalone V-landmark capture kit.

This does not start the web application or any Titan/servo communication.
Capture consent and pose settings live in sign_landmark_capture.py.
"""

from sign_landmark_capture import main


if __name__ == "__main__":
    raise SystemExit(main())
