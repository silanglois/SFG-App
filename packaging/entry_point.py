"""PyInstaller's Analysis needs a real script file as its entry point
(not an importable console_scripts function), so this just calls
straight into the app's real entry point."""
from sfg_app2.app.main import run

if __name__ == "__main__":
    run()
