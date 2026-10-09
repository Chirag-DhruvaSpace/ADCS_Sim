import orekit_jpype as orekit
orekit.initVM()

from orekit_jpype.pyhelpers import setup_orekit_data  # noqa: E402
setup_orekit_data(from_pip_library=True)

from org.orekit.time import TimeScalesFactory  # noqa: E402
utc = TimeScalesFactory.getUTC()
last_leap_second = utc.getLastKnownLeapSecond()
assert last_leap_second.getComponents(utc).getDate().getYear() >= 2016
