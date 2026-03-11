import irsdk
ibt = irsdk.IBT()
print("Attributes of IBT instance:")
for attr in dir(ibt):
    print(f"  {attr}")

if hasattr(ibt, '_header'):
    print("\n_header contents:")
    print(ibt._header)

if hasattr(ibt, '_disk_header'):
    print("\n_disk_header contents:")
    print(ibt._disk_header)
