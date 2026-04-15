import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
print("Current directory:", Path.cwd())
print("sys.path:", sys.path[:3])
try:
    import nexus_os.bridge.mem0_adapter
    print("Import successful")
except ModuleNotFoundError as e:
    print("Import failed:", e)
    # List what's in nexus_os/bridge
    bridge_path = Path.cwd() / "nexus_os" / "bridge"
    print("Contents of", bridge_path)
    for f in bridge_path.iterdir():
        print("  ", f.name)
