import irsdk
print(dir(irsdk.IBT()))
print(irsdk.IBT().get_all.__doc__)
print(getattr(irsdk.IBT(), 'session_info', 'No session info attr'))
