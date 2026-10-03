"""Read-only standalone MaixCAM2 session-log printer."""

SESSION_LOG_PATH = "/root/smart_hand_rehab_sessions.csv"
QUALITY_LOG_PATH = SESSION_LOG_PATH + ".quality.csv"
REASON_LOG_PATH = SESSION_LOG_PATH + ".reason.csv"


def print_csv(label, path):
    print("{} BEGIN".format(label))
    try:
        with open(path, "r") as handle:
            content = handle.read()
    except OSError as exc:
        print("{} ERROR: {}".format(label, exc))
        print("{} END".format(label))
        return False
    print(content.rstrip())
    print("{} END".format(label))
    return True


def main():
    base_ok = print_csv("SESSION CSV", SESSION_LOG_PATH)
    print_csv("QUALITY CSV", QUALITY_LOG_PATH)
    print_csv("REASON CSV", REASON_LOG_PATH)
    return 0 if base_ok else 1


if __name__ == "__main__":
    main()
