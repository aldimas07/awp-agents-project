"""Load a .env file and emit `set KEY=VALUE` lines for Windows batch consumption."""
import sys
import pathlib


def main():
    env_path = pathlib.Path(sys.argv[1])
    if not env_path.exists():
        return
    text = env_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        # Strip optional quotes
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        # Escape batch special characters in value: ^ & < > |
        value = value.replace("^", "^^")
        value = value.replace("&", "^&")
        value = value.replace("<", "^<")
        value = value.replace(">", "^>")
        value = value.replace("|", "^|")
        print(f"set {key}={value}")


if __name__ == "__main__":
    main()
