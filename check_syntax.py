import py_compile
try:
    py_compile.compile('review/mission_control.py', doraise=True)
    print("VALID")
except py_compile.PyCompileError as e:
    print(f"INVALID: {e}")
