"""Verify the monotonic clock API required by main.py on MaixCAM2."""

from maix import time


def main():
    ticks_ms = getattr(time, "ticks_ms", None)
    if ticks_ms is None:
        raise RuntimeError("maix.time.ticks_ms is unavailable")

    start_ms = ticks_ms()
    time.sleep_ms(50)
    end_ms = ticks_ms()

    ticks_diff = getattr(time, "ticks_diff", None)
    if ticks_diff is None:
        elapsed_ms = end_ms - start_ms
        diff_api = "fallback subtraction"
    else:
        # MaixPy uses ticks_diff(previous, current), as confirmed on MaixCAM2.
        elapsed_ms = ticks_diff(start_ms, end_ms)
        diff_api = "maix.time.ticks_diff"

    print("ticks_ms start={} end={}".format(start_ms, end_ms))
    print("elapsed_ms={} via {}".format(elapsed_ms, diff_api))
    if elapsed_ms < 30 or elapsed_ms > 1000:
        raise RuntimeError("monotonic clock elapsed time is implausible")
    print("TIME API PROBE OK")


main()
