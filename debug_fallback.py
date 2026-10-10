import os

path = 'static/images/themes/frutiger-aero/'
files = sorted(os.listdir(path))
print("Files:")
for f in files:
    print(f"  {repr(f)}")
