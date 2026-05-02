import sys
import os

# Remove the corrupted .py file temporarily
corrupted_path = '/teamspace/studios/this_studio/pt-narrative-os/review/mission_control.py'
if os.path.exists(corrupted_path):
    os.remove(corrupted_path)

sys.path.insert(0, '/teamspace/studios/this_studio/pt-narrative-os/review')
try:
    import mission_control
    print("Successfully imported mission_control from pyc")
    # Try to get source
    import inspect
    source = inspect.getsource(mission_control)
    print(f"Source length: {len(source)}")
    # Save it
    with open('/tmp/mission_control_recovered.py', 'w') as f:
        f.write(source)
    print("Saved recovered source to /tmp/mission_control_recovered.py")
except Exception as e:
    print(f"Error: {e}")
