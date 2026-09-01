from pathlib import Path
import sys
import traceback


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

try:
    from ttc3018_control.qt.main import main  # noqa: E402
except BaseException:
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "pine-bootstrap.log").open("a", encoding="utf-8") as handle:
        handle.write(traceback.format_exc())
        handle.write("\n")
    raise


if __name__ == "__main__":
    main()

