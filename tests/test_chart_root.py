# tests/test_chart_root.py

import sys
from pathlib import Path

# Add the parent folder to Python's import search path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import threading
import time
from chart_visualization import get_root, plot_candles_and_boxes

def test_root_does_not_duplicate():
    """
    Integration test:
    Check that chart_visualization.py prevents multiple root GUIs.
    """
    
    # Start the chart in its own thread (like main.py does)
    t = threading.Thread(target=plot_candles_and_boxes, args=(0,), name="chart_root")
    t.start()

    # Actively wait for root to appear, up to timeout seconds
    timeout = 10  # seconds
    poll_interval = 0.1
    waited = 0

    while get_root() is None and waited < timeout:
        time.sleep(poll_interval)
        waited += poll_interval

    print(f"Waited {waited:.1f} seconds for root to exist.")

    # Confirm root is not None
    assert get_root() is not None, "Root should exist after starting chart."

    # Try to start again
    if get_root() is None:
        print("Root is None unexpectedly, starting chart again.")
        t2 = threading.Thread(target=plot_candles_and_boxes, args=(0,), name="chart_root_2")
        t2.start()
        time.sleep(1)
        assert False, "Root was None when it should not be."
    else:
        print("Root detected correctly. No duplicate started.")

if __name__ == "__main__":
    test_root_does_not_duplicate()